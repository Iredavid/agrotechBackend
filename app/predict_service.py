# """
# Full crop-recommendation service:
#   1. reverse_geocode_state(lat, lon)  -> Nigerian state name
#   2. predict_top_crops(features_dict) -> top-3 crops with confidence
#   3. enrich_with_state_data(crop, state) -> historical avg yield for display

# Drop this alongside your existing app/soil_service.py, app/farmScore.py, etc.
# """
# import httpx
# import pandas as pd
# import joblib
# from catboost import CatBoostClassifier

# # ---------------------------------------------------------------
# # 1. STATE FROM LOCATION (reverse geocoding)
# # ---------------------------------------------------------------
# NOMINATIM_URL = "https://nominatim.openstreetmap.org/reverse"

# async def reverse_geocode_state(lat: float, lon: float) -> str | None:
#     """
#     Nominatim returns address.state directly for Nigeria (e.g. 'Ekiti', 'Kano').
#     Free, no API key, but rate-limited to ~1 req/sec and requires a User-Agent.
#     """
#     params = {"lat": lat, "lon": lon, "format": "json", "zoom": 8}
#     headers = {"User-Agent": "YourAppName/1.0 (contact@yourapp.com)"}
#     async with httpx.AsyncClient(timeout=15.0) as client:
#         resp = await client.get(NOMINATIM_URL, params=params, headers=headers)
#     resp.raise_for_status()
#     data = resp.json()
#     state = data.get("address", {}).get("state")
#     # Nominatim sometimes returns "Kano State" -- normalize to match your lookup table
#     if state:
#         state = state.replace(" State", "").strip()
#     return state


# def reverse_geocode_state_fallback(lat: float, lon: float, states_geojson_path: str) -> str | None:
#     """
#     Fallback if Nominatim is unavailable/rate-limited: point-in-polygon against
#     a bundled Nigeria states GeoJSON (e.g. from Nigeria's OCHA/HDX admin boundaries).
#     Requires: pip install shapely
#     """
#     import json
#     from shapely.geometry import shape, Point

#     with open(states_geojson_path) as f:
#         geo = json.load(f)

#     pt = Point(lon, lat)
#     for feature in geo["features"]:
#         poly = shape(feature["geometry"])
#         if poly.contains(pt):
#             return feature["properties"].get("state") or feature["properties"].get("NAME_1")
#     return None


# # ---------------------------------------------------------------
# # 2. CROP MODEL
# # ---------------------------------------------------------------
# _model = CatBoostClassifier()
# _model.load_model("catboost_nigeria_crop_model.cbm")
# _label_encoder = joblib.load("label_encoder.pkl")
# _feature_cols = joblib.load("feature_columns.pkl")
# _state_lookup = pd.read_csv("state_crop_lookup.csv")


# def predict_top_crops(features: dict, top_k: int = 3) -> list[dict]:
#     """
#     features must contain: N, P, K, temperature, humidity, ph, rainfall
#     (N/P/K from iSDAsoil, temperature/humidity from OpenWeather,
#      ph from ISRIC SoilGrids, rainfall summed from OpenWeather forecast)
#     """
#     row = pd.DataFrame([[features[c] for c in _feature_cols]], columns=_feature_cols)
#     proba = _model.predict_proba(row)[0]

#     ranked = sorted(
#         zip(_label_encoder.classes_, proba), key=lambda x: x[1], reverse=True
#     )[:top_k]

#     return [
#         {"crop": crop, "confidence": round(float(p) * 100, 1)}
#         for crop, p in ranked
#     ]


# def enrich_with_state_data(crop: str, state: str | None) -> dict:
#     """Attach historical yield context for the farmer's state, if we have it."""
#     if not state:
#         return {"state_avg_yield_t_ha": None, "note": "State not detected"}

#     match = _state_lookup[
#         (_state_lookup["crop"] == crop) & (_state_lookup["state"] == state)
#     ]
#     if match.empty:
#         return {"state_avg_yield_t_ha": None, "note": f"No historical records for {crop} in {state}"}

#     r = match.iloc[0]
#     return {
#         "state_avg_yield_t_ha": round(float(r["avg_yield_t_ha"]), 2),
#         "state_rank_among_crops": int(r["state_rank"]),
#         "note": f"Historical average in {state}: {r['avg_yield_t_ha']:.2f} t/ha "
#                 f"(informational only -- not used to filter recommendations)",
#     }


# # ---------------------------------------------------------------
# # 3. END-TO-END EXAMPLE
# # ---------------------------------------------------------------
# async def get_recommendation(lat: float, lon: float, farm_size_ha: float, soil_features: dict):
#     state = await reverse_geocode_state(lat, lon)
#     top_crops = predict_top_crops(soil_features, top_k=3)
#     for c in top_crops:
#         c.update(enrich_with_state_data(c["crop"], state))
#         c["farm_size_ha"] = farm_size_ha
#     return {"state": state, "recommendations": top_crops}
