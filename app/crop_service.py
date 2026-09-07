"""
app/crop_service.py  (v9 -- cache soil lookups by location, split by TTL)
--------------------------------------------------------------------------
Same behavior/response shape as v8. This pass adds caching to the two
Earth Engine soil calls, which were previously the only uncached lookups
in this function (everything else -- geocode, rainfall -- already used
`cached()`).

Why split into two cached calls instead of one:
  - Soil nutrients/pH change slowly -> safe to cache 30 days, same as
    state/rainfall.
  - SMAP soil moisture is explicitly a rolling 7-day window -> a 30-day
    cache would silently serve stale moisture. It gets its own short TTL.

Why keyed by (lat, lon) only, not by user/farm ID:
  These are properties of a PLACE, not a user -- two different farmers at
  the same coordinates genuinely have the same soil pH and nutrient
  levels. Keying by location is correct here, not a cross-user leak risk.
  (Contrast with manual_soil_texture / irrigation_type below, which are
  farmer-entered and are NOT cached -- they're recomputed fresh from
  whatever farmData was just passed in, every call, which is already the
  safe behavior for user-editable input.)
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
from app.test_earth_engine import (
    get_soil_static_properties,
    get_soil_dynamic_bands,
    combine_soil_profile,
)

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

# Static/slow-changing facts -- long TTL.
_STATE_CACHE_TTL_SECONDS = 60 * 60 * 24 * 30       # 30 days
_RAINFALL_CACHE_TTL_SECONDS = 60 * 60 * 24 * 30    # 30 days
_SOIL_STATIC_CACHE_TTL_SECONDS = 60 * 60 * 24 * 30  # 30 days (N/P/K, pH, carbon)

# Dynamic/fast-changing facts -- short TTL. SMAP's own query window is a
# rolling 7 days; 6 hours keeps moisture reasonably fresh while still
# absorbing repeated logins/refreshes within the same day.
_SOIL_DYNAMIC_CACHE_TTL_SECONDS = 60 * 60 * 6      # 6 hours

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


_STATE_ALIASES: dict[str, str] = {
    "federal capital territory": "fct",
    "federal capital territory fct": "fct",
    "abuja": "fct",
    "abuja fct": "fct",
}


def _normalize(name: str) -> str:
    name = name.strip().lower()
    name = re.sub(r"[^\w\s]", " ", name)
    name = re.sub(r"\s+", " ", name).strip()
    return name


def _resolve_state_key(name: str) -> str:
    normalized = _normalize(name)
    return _STATE_ALIASES.get(normalized, normalized)


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
    manual_soil_texture: str | None = None,
    irrigation_type: str | None = None,
) -> dict:
    from app.weather import forecast

    # --- Kick off every independent lookup at once ---------------------
    # Soil is now TWO cached tasks instead of one uncached one:
    #   - static: N/P/K, pH, organic carbon -> 30-day TTL, keyed by (lat, lon)
    #   - dynamic: SMAP moisture/vegetation/water-balance -> 6-hour TTL,
    #     keyed by (lat, lon)
    # Both run on worker threads (asyncio.to_thread) since the underlying
    # Earth Engine calls are blocking, same as before -- the only change
    # is that a cache hit skips the blocking call entirely.
    soil_static_task = cached(
        prefix="soil_static", lat=lat, lon=lon,
        fetch=lambda: asyncio.to_thread(get_soil_static_properties, lat, lon),
        ttl_seconds=_SOIL_STATIC_CACHE_TTL_SECONDS,
    )
    soil_dynamic_task = cached(
        prefix="soil_dynamic", lat=lat, lon=lon,
        fetch=lambda: asyncio.to_thread(get_soil_dynamic_bands, lat, lon),
        ttl_seconds=_SOIL_DYNAMIC_CACHE_TTL_SECONDS,
    )
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

    (
        soil_static, soil_dynamic, weather_forecast, state, rainfall_result,
    ) = await asyncio.gather(
        soil_static_task, soil_dynamic_task, weather_task, state_task,
        rainfall_task,
        return_exceptions=True,
    )

    # Static soil properties and weather are load-bearing -- raise on failure.
    if isinstance(soil_static, Exception):
        raise soil_static
    if isinstance(weather_forecast, Exception):
        raise weather_forecast

    # Dynamic soil (moisture bands) degrades gracefully: farm_health_score
    # and moisture-dependent fields become partial/None rather than the
    # whole request failing, since crop prediction itself doesn't need them.
    if isinstance(soil_dynamic, Exception):
        soil_dynamic = {"success": False, "bands": {}}

    if isinstance(state, Exception):
        state = None

    if isinstance(rainfall_result, Exception):
        rainfall_mm = sum(item.get("rain", {}).get("3h", 0)
                          for item in weather_forecast.get("list", []))
    else:
        rainfall_mm = rainfall_result

    soil = combine_soil_profile(soil_static, soil_dynamic)

    current = weather_forecast["list"][0]["main"]

    final_bucket = (
        validate_and_map_manual_texture(manual_soil_texture)
        if manual_soil_texture
        else "Loamy"
    )
    # NOTE: manual_soil_texture / irrigation_type are farmer-entered and
    # deliberately NOT part of any cache key above -- they're applied
    # fresh here, every call, straight from whatever farmData was just
    # passed in. If a farmer edits either field, the very next call
    # reflects it immediately; there's no stale-cache path for these.
    texture_source = "farmer_input" if manual_soil_texture else "default"

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