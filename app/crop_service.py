"""
app/crop_service.py  (v8 -- performance pass 2)
-----------------------------------------------
Same behavior/response shape as v7. Further speed-only changes:

  4. reverse_geocode_state() and get_rainfall_climatology_mm() each
     opened a brand new httpx.AsyncClient() (and paid a fresh TLS
     handshake) on every call. They now share one module-level,
     connection-pooled client.
  5. enrich_with_state_data() recomputed a normalized copy of the
     entire state_lookup["state"] column from scratch for every crop
     in top_crops, even though the table never changes between those
     calls. That normalization is now computed once per request (and
     cached across requests, since _state_lookup is static) and passed
     in, instead of being recomputed per crop.

v7 changes (still in effect, see previous docstring):
  1. get_soil_moisture() runs via asyncio.to_thread instead of
     blocking the event loop.
  2. Soil moisture, weather forecast, reverse geocoding, and rainfall
     climatology run concurrently with asyncio.gather.
  3. Reverse-geocoded state and rainfall climatology are cached by
     rounded (lat, lon).
"""
import re
import os
import asyncio
import httpx
import pandas as pd
import joblib
from catboost import CatBoostClassifier
from app.harvest_lookup import get_harvest_info
from app.market_demand import get_market_demand
from app.texture_options import validate_and_map_manual_texture
from app.irrigation_options import validate_irrigation_type
from app.irrigation_advisor import get_irrigation_advice
from app.geo_cache import cached

_ARTIFACT_DIR = os.path.dirname(os.path.abspath(__file__))

_model = CatBoostClassifier()
_model.load_model(os.path.join(
    _ARTIFACT_DIR, "catboost_nigeria_crop_model_v3.cbm"))
_label_encoder = joblib.load(os.path.join(
    _ARTIFACT_DIR, "label_encoder_v3.pkl"))
_feature_cols = joblib.load(os.path.join(
    _ARTIFACT_DIR, "feature_columns_v3.pkl"))
_state_lookup = pd.read_csv(os.path.join(
    _ARTIFACT_DIR, "state_crop_lookup.csv"))

NOMINATIM_URL = "https://nominatim.openstreetmap.org/reverse"
NASA_POWER_URL = "https://power.larc.nasa.gov/api/temporal/climatology/point"

# State boundaries and rainfall climatology are effectively static.
_STATE_CACHE_TTL_SECONDS = 60 * 60 * 24 * 30      # 30 days
_RAINFALL_CACHE_TTL_SECONDS = 60 * 60 * 24 * 30    # 30 days

# Shared, connection-pooled HTTP client instead of opening a new
# httpx.AsyncClient() (and paying a fresh TLS handshake) on every
# reverse-geocode / rainfall call. Same request semantics (params,
# headers, timeout) -- just reused across calls.
_http_client: httpx.AsyncClient | None = None


def _get_http_client() -> httpx.AsyncClient:
    global _http_client
    if _http_client is None:
        _http_client = httpx.AsyncClient()
    return _http_client


async def reverse_geocode_state(lat: float, lon: float) -> str | None:
    params = {"lat": lat, "lon": lon, "format": "json", "zoom": 8}
    headers = {
        "User-Agent": "SmartFarmAdvisoryAPI/1.0 (contact@yourdomain.com)"}
    client = _get_http_client()
    resp = await client.get(NOMINATIM_URL, params=params, headers=headers, timeout=15.0)
    resp.raise_for_status()
    data = resp.json()
    state = data.get("address", {}).get("state")
    if state:
        state = state.replace(" State", "").strip()
    return state


async def get_rainfall_climatology_mm(lat: float, lon: float) -> float:
    params = {"parameters": "PRECTOTCORR", "community": "AG",
              "longitude": lon, "latitude": lat, "format": "JSON"}
    client = _get_http_client()
    resp = await client.get(NASA_POWER_URL, params=params, timeout=20.0)
    resp.raise_for_status()
    data = resp.json()
    ann = data["properties"]["parameter"]["PRECTOTCORR"].get("ANN")
    return round(ann * 30, 2) if ann is not None else None


def predict_top_crops(features: dict) -> list[dict]:
    row_values = [features.get(c, "Loamy") if c == "soil_texture"
                  else features[c] for c in _feature_cols]
    row = pd.DataFrame([row_values], columns=_feature_cols)
    proba = _model.predict_proba(row)[0]
    ranked = sorted(zip(_label_encoder.classes_, proba),
                    key=lambda x: x[1], reverse=True)
    return [{"crop": crop, "confidence": round(float(p) * 100, 1)} for crop, p in ranked]


# Add any other naming variants you find in your CSV / geocoder output.
# Keys and values should all be in "normalized" form (see _normalize).
_STATE_ALIASES: dict[str, str] = {
    "federal capital territory": "fct",
    "federal capital territory fct": "fct",
    "abuja": "fct",
    "abuja fct": "fct",
}


def _normalize(name: str) -> str:
    # lowercase, strip, collapse whitespace, drop punctuation like
    # parentheses so "Federal Capital Territory (FCT)" and
    # "federal capital territory" normalize to the same string
    name = name.strip().lower()
    name = re.sub(r"[^\w\s]", " ", name)
    name = re.sub(r"\s+", " ", name).strip()
    return name


def _resolve_state_key(name: str) -> str:
    normalized = _normalize(name)
    return _STATE_ALIASES.get(normalized, normalized)


# `_state_lookup["state"]` is a static, module-level table -- its
# normalized form never changes across requests, let alone across the
# crops within a single request. Previously enrich_with_state_data()
# recomputed this normalization from scratch on every call (once per
# crop in top_crops). It's now computed once, lazily, and reused --
# same values, just not redone 5-10x per request.
_normalized_state_lookup_col: "pd.Series | None" = None


def _get_normalized_state_lookup_states() -> pd.Series:
    global _normalized_state_lookup_col
    if _normalized_state_lookup_col is None:
        _normalized_state_lookup_col = _state_lookup["state"].map(
            lambda s: _resolve_state_key(s) if isinstance(s, str) else s
        )
    return _normalized_state_lookup_col


def enrich_with_state_data(crop: str, state: str | None, state_lookup) -> dict:
    if not state:
        return {"state_avg_yield_t_ha": None, "note": "State not detected"}
    target_key = _resolve_state_key(state)
    normalized_states = _get_normalized_state_lookup_states()
    match = _state_lookup[(_state_lookup["crop"] == crop)
                          & (normalized_states == target_key)]
    if match.empty:
        return {"state_avg_yield_t_ha": None, "note": f"No historical records for {crop} in {state}"}
    r = match.iloc[0]
    return {
        "state_avg_yield_t_ha": round(float(r["avg_yield_t_ha"]), 2),
        "note": f"Historical average in {state}: {r['avg_yield_t_ha']:.2f} t/ha (informational only)",
    }


async def get_crop_recommendation(
    lat: float,
    lon: float,
    farm_size_ha: float,
    manual_soil_texture: str | None = None,   # e.g. "Sandy Clay Loam", optional
    irrigation_type: str | None = None,
) -> dict:
    from app.test_earth_engine import get_soil_moisture
    from app.weather import forecast

    # --- Kick off every independent lookup at once ---------------------
    # soil: blocking Earth Engine call -> runs on a worker thread so it
    #   doesn't stall the event loop or block other requests.
    # weather / state / rainfall: independent async HTTP calls.
    soil_task = asyncio.to_thread(
        get_soil_moisture, latitude=lat, longitude=lon)
    weather_task = forecast(lat=lat, lon=lon)
    state_task = cached(
        prefix="state", lat=lat, lon=lon,
        fetch=lambda: reverse_geocode_state(lat, lon),
        ttl_seconds=_STATE_CACHE_TTL_SECONDS,
    )
    rainfall_task = cached(
        prefix="rainfall", lat=lat, lon=lon,
        fetch=lambda: get_rainfall_climatology_mm(lat, lon),
        ttl_seconds=_RAINFALL_CACHE_TTL_SECONDS,
    )

    soil, weather_forecast, state, rainfall_result = await asyncio.gather(
        soil_task, weather_task, state_task, rainfall_task,
        return_exceptions=True,
    )

    # soil and weather are load-bearing for the rest of this function --
    # if either failed, raise so the caller gets a real error instead of
    # a confusing downstream AttributeError.
    if isinstance(soil, Exception):
        raise soil
    if isinstance(weather_forecast, Exception):
        raise weather_forecast

    # state is nice-to-have (only used for historical yield enrichment)
    if isinstance(state, Exception):
        state = None

    # rainfall falls back to summing the short-range forecast, same as
    # the original try/except behavior
    if isinstance(rainfall_result, Exception):
        rainfall_mm = sum(item.get("rain", {}).get("3h", 0)
                          for item in weather_forecast.get("list", []))
    else:
        rainfall_mm = rainfall_result

    current = weather_forecast["list"][0]["main"]
    # auto_texture = soil.get("texture", {})
    # auto_bucket = auto_texture.get("texture_class") or "Loamy"

    texture_source = "satellite"
    final_bucket = (
        validate_and_map_manual_texture(manual_soil_texture)
        if manual_soil_texture
        else "Loamy"
    )
    texture_source = "farmer_input" if manual_soil_texture else "default"

    # Irrigation type defaults to "none" (rain-fed) if the farmer hasn't set it
    validated_irrigation_type = validate_irrigation_type(
        irrigation_type or "none")

    features = {
        "N": soil["nutrient"]["nitrogen"],
        "P": soil["nutrient"]["phosphorus"],
        "K": soil["nutrient"]["potassium"],
        "temperature": current["temp"],
        "humidity": current["humidity"],
        "ph": soil["organ"]["ph"]["value"],
        "rainfall": rainfall_mm,
        "soil_texture": final_bucket,
    }

    # Pulled once for all crops -- these come from analyze_soil_condition's
    # "bands" dict, already computed per farm on every get_soil_moisture() call
    bands = soil.get("bands", {})
    moisture_score_100 = bands.get("moisture_score_100")
    water_balance_score_100 = bands.get("watre_balance_100")

    top_crops = predict_top_crops(features)
    for c in top_crops:
        c.update(enrich_with_state_data(c["crop"], state, _state_lookup))
        c["estimated_production_t"] = (
            round(c["state_avg_yield_t_ha"] * farm_size_ha, 2)
            if c.get("state_avg_yield_t_ha") else None
        )
        c["time_to_harvest"] = get_harvest_info(c["crop"])
        c["market_demand"] = get_market_demand(c["crop"])
        c["irrigation"] = get_irrigation_advice(
            crop=c["crop"],
            irrigation_type=validated_irrigation_type,
            soil_texture_bucket=final_bucket,
            moisture_score_100=moisture_score_100,
            water_balance_score_100=water_balance_score_100,
        )

    return {
        "state": state,
        "soil_texture": {
            "used_for_prediction": final_bucket,
            "source": texture_source,
        },
        "irrigation_type_used": validated_irrigation_type,
        "farm_size_ha": farm_size_ha,
        "features_used": features,
        "farm_health_score": soil.get("farm_health_score"),
        "recommendations": top_crops,
        "soil_moisture": soil.get("soil_moisture"),
    }