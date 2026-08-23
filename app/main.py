import asyncio

from app.crop_service import get_crop_recommendation, reverse_geocode_state
from fastapi import APIRouter, FastAPI, HTTPException, Query
from pydantic import BaseModel
from typing import Any, Dict, Optional
from app.firebase import addUserData, getUserData, get_state_list
from app.firebase import get_irrigation_options
from app.texture_options import get_texture_options
from app.weather import forecast, geocode_state, get_weather
from app.test_earth_engine import get_soil_texture_sync, initialize_earth_engine

from fastapi.middleware.cors import CORSMiddleware


class stateRequest(BaseModel):
    state: str


class WeatherRequest(BaseModel):
    city: Optional[str] = None
    lat: Optional[float] = None
    lon: Optional[float] = None


class addRequest(BaseModel):
    farmName: str
    farmData: Dict[str, Any]
    userId: str


class CropRecommendationRequest(BaseModel):
    lat: float
    lon: float
    farm_size_ha: float
    soil_texture: Optional[str] = None
    irrigation_type: Optional[str] = None


app = FastAPI(
    title="Smart Farm Advisory API",
    version="1.0.0",
)
initialize_earth_engine()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


router = APIRouter()

@app.api_route("/health", methods=["GET", "HEAD"])
async def health():
    return {"status": "healthy"}

@router.get("/soil-texture")
async def soilTexture(
    lat: float, lon: float
):
    try:
        return await asyncio.to_thread(get_soil_texture_sync, lat, lon)
    except Exception as e:
        raise HTTPException(
            status_code=502, detail=f"Couldn't fetch soil texture: {e}")


@router.post("/forecast")
async def get_weather_endpoint(request: WeatherRequest):
    return await forecast(city=request.city,
                          lat=request.lat,
                          lon=request.lon,)


@router.post("/currentweather")
async def get_currweather_endpoint(request: WeatherRequest):
    return await get_weather(city=request.city,
                             lat=request.lat,
                             lon=request.lon,)


@router.post("/crop-recommendation")
async def crop_recommendation(request: CropRecommendationRequest):
    try:
        result = await get_crop_recommendation(
            lat=request.lat,
            lon=request.lon,
            farm_size_ha=request.farm_size_ha,
            manual_soil_texture=request.soil_texture,
            irrigation_type=request.irrigation_type
        )
        return result
    except Exception as error:
        raise HTTPException(
            status_code=500,
            detail=f"Failed to generate crop recommendation: {str(error)}"
        )


@router.post("/addUser")
def register_endpoint(request: addRequest):
    addUserData(request.farmData, request.userId, request.farmName)


@router.get("/getUserData")
async def getUser_endpoint(userId: str = Query(...)):
    return await getUserData(userId)


@router.get("/soil")
def get_soil():
    return get_texture_options()


@router.get("/irrigation")
async def get_irrigation():
    return get_irrigation_options()


@router.get("/states")
def get_states():
    return get_state_list()


@router.get("/reverse-geocode")
async def reverse_geocode(lat: float, lon: float):
    return await reverse_geocode_state(lat, lon)


@router.post("/geocode")
async def geocode_endpoint(request: stateRequest):
    return await geocode_state(request.state)


app.include_router(router)
