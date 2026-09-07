# """
# app/fertilizer_routes.py
# --------------------------
# Thin FastAPI route wiring for the Fertilizer Advisor. Wire this router into
# your existing app the same way crop_service's router is mounted.

# The frontend calls this AFTER already having a farm profile (i.e. after
# get_crop_recommendation() has run once and features_used / farm_size_ha are
# known) -- no new soil/weather fetch happens here, this is pure calculation.
# """

# from fastapi import APIRouter, HTTPException
# from pydantic import BaseModel

# from app.fertilizer_service import get_fertilizer_recommendation
# from app.fertilizer_data import CROP_NPK_RATES

# router = APIRouter(prefix="/fertilizer", tags=["fertilizer"])


# class SoilFeatures(BaseModel):
#     N: float
#     P: float
#     K: float
#     ph: float
#     soil_texture: str | None = None
#     temperature: float | None = None
#     humidity: float | None = None
#     rainfall: float | None = None


# class FertilizerRequest(BaseModel):
#     crop: str
#     target_yield_t_ha: float
#     farm_size_ha: float
#     features: SoilFeatures


# @router.post("/recommendation")
# async def fertilizer_recommendation(payload: FertilizerRequest):
#     if payload.crop not in CROP_NPK_RATES:
#         raise HTTPException(
#             status_code=400,
#             detail=(
#                 f"Unsupported crop '{payload.crop}'. "
#                 f"Supported crops: {sorted(CROP_NPK_RATES)}"
#             ),
#         )
#     return await get_fertilizer_recommendation(
#         crop=payload.crop,
#         target_yield_t_ha=payload.target_yield_t_ha,
#         farm_size_ha=payload.farm_size_ha,
#         features=payload.features.model_dump(),
#     )
