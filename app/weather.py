

import httpx
import os
from dotenv import load_dotenv

load_dotenv()

NOMINATIM_SEARCH_URL = "https://nominatim.openstreetmap.org/search"


async def geocode_state(state: str, country: str = "Nigeria") -> dict:
    """
    Forward-geocode a Nigerian state name to its lat/lon using Nominatim.
    Uses structured query params to avoid name-collision issues.
    """
    params = {
        "state": state,
        "country": country,
        "format": "json",
        "limit": 1,
    }
    headers = {"User-Agent": "SmartFarmAdvisoryAPI/1.0 (contact@yourdomain.com)"}

    async with httpx.AsyncClient(timeout=15.0) as client:
        resp = await client.get(NOMINATIM_SEARCH_URL, params=params, headers=headers)
    resp.raise_for_status()
    data = resp.json()

    if not data:
        raise ValueError(f"State not found: {state}, {country}")

    result = data[0]
    return {
        # "state": state,
        "latitude": float(result["lat"]),
        "longitude": float(result["lon"]),
    }

# async def geocode(city: str):
#     url = "https://api.openweathermap.org/geo/1.0/direct"

#     params = {
#         "q": f"{city},NG",
#         "limit": 1,
#         "appid": os.getenv("OPENWEATHER_API_KEY"),
#     }

#     async with httpx.AsyncClient(timeout=30.0) as client:
#         response = await client.get(url, params=params)

#     response.raise_for_status()

#     data = response.json()

#     if not data:
#         raise ValueError(f"Location not found: {city}")

#     return data[0]


async def forecast(
    city: str | None = None,
    lat: float | None = None,
    lon: float | None = None,
):
    curr_weather_url = "https://api.openweathermap.org/data/2.5/forecast"

    if lat is not None and lon is not None:
        # Current location flow
        curr_params = {
            "lat": lat,
            "lon": lon,
            "appid": os.getenv("OPENWEATHER_API_KEY"),
            "units": "metric",
        }

    elif city:
        # City name flow
        location = await geocode_state(city)

        curr_params = {
            "lat": location["lat"],
            "lon": location["lon"],
            "appid": os.getenv("OPENWEATHER_API_KEY"),
            "units": "metric",
        }

    else:
        raise ValueError(
            "Either city or both latitude and longitude are required"
        )

    async with httpx.AsyncClient(timeout=30.0) as client:
        response = await client.get(
            curr_weather_url,
            params=curr_params,
        )

    response.raise_for_status()

    return response.json()


async def get_weather(city: str | None = None,
                      lat: float | None = None,
                      lon: float | None = None,):

    if lat is not None and lon is not None:
        # Current location flow
        curr_params = {
            "lat": lat,
            "lon": lon,
            "appid": os.getenv("OPENWEATHER_API_KEY"),
            "units": "metric",
        }

    elif city:
        # City name flow
        location = await geocode_state(city)

        curr_params = {
            "lat": location["lat"],
            "lon": location["lon"],
            "appid": os.getenv("OPENWEATHER_API_KEY"),
            "units": "metric",
        }

    forecast_url = "https://api.openweathermap.org/data/2.5/weather"

    async with httpx.AsyncClient(timeout=30.0) as client:
        response = await client.get(forecast_url, params=curr_params)
    return response.json()

# print("API KEY EXISTS:", bool(os.getenv("OPENWEATHER_API_KEY")))
