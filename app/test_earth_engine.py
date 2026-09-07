"""
app/test_earth_engine.py
--------------------------
This is your EXISTING Earth Engine module -- same file, same name, same
place in your project (crop_service.py already does
`from app.test_earth_engine import get_soil_moisture`). This is a
replacement for what's inside it: initialize_earth_engine(),
_build_texture_image(), and get_soil_texture_sync() are UNCHANGED from
your current version and should stay exactly as they are -- only
get_soil_moisture() itself is being split below.

Split from the original get_soil_moisture() into two independently-cacheable
pieces, because they have very different real-world "shelf lives":

  - get_soil_static_properties(): nutrients (N/P/K), organic carbon, pH.
    These describe slow-changing soil chemistry -- safe to cache for weeks,
    same TTL class as reverse_geocode_state / rainfall climatology in
    crop_service.py.

  - get_soil_dynamic_bands(): SMAP-derived moisture, water-balance,
    vegetation, and historical scores. SMAP's own query window is a
    rolling 7 days (see start_date below) -- caching this for 30 days
    would silently serve week-old-or-worse moisture readings. Short TTL.

Both are keyed by (lat, lon) ONLY, not by user -- this is a property of a
place, and two different farmers at the same coordinates genuinely have
the same soil. No cross-user conflict risk here; the only risk was
mismatched TTLs, which this split fixes.

farm_health_score is a blend of both (fertility_score + ph_score come from
the static half, moisture/water-balance/vegetation from the dynamic half)
-- it's cheap CPU-only math, so it's recomputed fresh every call rather
than cached itself; only the two expensive Earth Engine fetches are cached.
"""

import os
import concurrent.futures
from datetime import datetime, timezone, timedelta

from dotenv import load_dotenv
import ee

from app.farmScore import calculate_ph_score, fertilityScore, weighted_average
from app.soil_service import analyze_soil_condition  # your EXISTING app/soil_service.py -- unchanged
from app.texture_triangle import classify_texture_bucket

load_dotenv()


# --- UNCHANGED from your current test_earth_engine.py -----------------
def initialize_earth_engine():
    try:
        secret_path = "/etc/secrets/earth-engine-key.json"
        if os.path.exists(secret_path):
            credentials = ee.ServiceAccountCredentials(
                email=None,
                key_file=secret_path
            )
            ee.Initialize(credentials, project=os.getenv(
                "EARTH_ENGINE_PROJECT"))
        else:
            ee.Initialize(project=os.getenv("EARTH_ENGINE_PROJECT"))

        print("Earth Engine initialized successfully")
    except Exception as error:
        print(f"Earth Engine initialization failed: {error}")
        raise error
# ------------------------------------------------------------------------  # existing SMAP band logic


def _reduce_with_fallback(
    image,
    point,
    scale,
    reducer=None,
    crs=None,
    buffer_radii=(0, 250, 1000, 5000, 10000),
):
    """Unchanged from the original -- tries progressively larger buffer
    radii until a non-null sample is found."""
    reducer = reducer or ee.Reducer.mean()

    def fetch_radius(radius):
        geometry = point if radius == 0 else point.buffer(radius)
        kwargs = {
            "reducer": reducer,
            "geometry": geometry,
            "scale": scale,
            "bestEffort": True,
            "tileScale": 4,
        }
        if crs is not None:
            kwargs["crs"] = crs
        return radius, image.reduceRegion(**kwargs).getInfo()

    results = {}
    with concurrent.futures.ThreadPoolExecutor(max_workers=len(buffer_radii)) as executor:
        futures = [executor.submit(fetch_radius, r) for r in buffer_radii]
        for future in concurrent.futures.as_completed(futures):
            radius, values = future.result()
            results[radius] = values

    last_values = {}
    for radius in buffer_radii:
        values = results.get(radius, {})
        last_values = values
        if any(v is not None for v in values.values()):
            return values, radius

    return last_values, None


# --- UNCHANGED from your current test_earth_engine.py -----------------
def _build_texture_image():
    clay_image = ee.Image(
        "projects/soilgrids-isric/clay_mean").select("clay_0-5cm_mean")
    sand_image = ee.Image(
        "projects/soilgrids-isric/sand_mean").select("sand_0-5cm_mean")

    clay_pct_img = clay_image.divide(10).rename("clay_pct")
    sand_pct_img = sand_image.divide(10).rename("sand_pct")

    return ee.Image.cat([clay_pct_img, sand_pct_img])


def get_soil_texture_sync(latitude: float, longitude: float) -> dict:
    """Fast, standalone soil-texture lookup. Safe to call on its own
    (e.g. from a lightweight endpoint used to suggest a form value)."""
    point = ee.Geometry.Point([longitude, latitude])
    texture_image = _build_texture_image()

    texture_values, texture_radius = _reduce_with_fallback(
        texture_image, point, scale=250,
    )

    clay_value = texture_values.get("clay_pct")
    sand_value = texture_values.get("sand_pct")

    texture_result = classify_texture_bucket(sand_value, clay_value)

    return {
        "usda_class": texture_result["usda_class"],
        "suggested_bucket": texture_result["model_bucket"],
        "clay_pct": clay_value,
        "sand_pct": sand_value,
        "sample_radius_m": texture_radius,
        "source": "ISRIC SoilGrids",
    }
# ------------------------------------------------------------------------


# --- NEW: split from the old get_soil_moisture() ------------------------
def get_soil_static_properties(latitude: float, longitude: float) -> dict:
    """Nutrients + organic carbon + pH. Slow-changing -- cache long (weeks)."""
    point = ee.Geometry.Point([longitude, latitude])

    raw_nitrogen = ee.Image("ISDASOIL/Africa/v1/nitrogen_total").select("mean_0_20")
    raw_phosphorus = ee.Image("ISDASOIL/Africa/v1/phosphorus_extractable").select("mean_0_20")
    raw_potassium = ee.Image("ISDASOIL/Africa/v1/potassium_extractable").select("mean_0_20")

    nitrogen = raw_nitrogen.divide(100).exp().subtract(1).rename("nitrogen_g_kg")
    phosphorus = raw_phosphorus.divide(10).exp().subtract(1).rename("phosphorus_mg_kg")
    potassium = raw_potassium.divide(10).exp().subtract(1).rename("potassium_mg_kg")
    soil_nutrients = ee.Image.cat([nitrogen, phosphorus, potassium])

    soc_image = ee.Image("projects/soilgrids-isric/soc_mean")
    carbon = soc_image.select("soc_0-5cm_mean").multiply(0.1).rename("organic_carbon_g_kg")

    ph_image = ee.Image("projects/soilgrids-isric/phh2o_mean")
    ph = ph_image.select("phh2o_0-5cm_mean").multiply(0.1).rename("soil_ph")

    water_collection = ee.ImageCollection("ISRIC/SoilGrids250m/v2_0")
    first_water_image = ee.Image(water_collection.first())
    water = first_water_image.select("val_0_5cm_mean").multiply(
        0.001).rename("water_content_volume_fraction")

    properties_image = ee.Image.cat([carbon, ph, water])

    with concurrent.futures.ThreadPoolExecutor(max_workers=2) as executor:
        nutrients_future = executor.submit(
            _reduce_with_fallback, soil_nutrients, point, 30
        )
        properties_future = executor.submit(
            _reduce_with_fallback, properties_image, point, 250
        )
        nutrient_values, nutrient_radius = nutrients_future.result()
        values, soil_radius = properties_future.result()

    nutrient = {
        "nitrogen": (
            nutrient_values.get("nitrogen_g_kg") * 1000
            if nutrient_values.get("nitrogen_g_kg") is not None else None
        ),
        "phosphorus": nutrient_values.get("phosphorus_mg_kg"),
        "potassium": nutrient_values.get("potassium_mg_kg"),
        "depth": "0-20 cm",
        "source": "iSDAsoil Africa",
        "sample_radius_m": nutrient_radius,
    }

    fertility_score = fertilityScore(nutrient)
    ph_value = values.get("soil_ph")
    ph_score = calculate_ph_score(ph_value)

    organ = {
        "organic_carbon": {"value": values.get("organic_carbon_g_kg"), "unit": "g/kg"},
        "ph": {"value": ph_value, "unit": "pH"},
        "water_content_at_field_capacity": {
            "value": values.get("water_content_volume_fraction"),
            "unit": "cm3/cm3",
            "suction": "33 kPa",
        },
        "depth": "0-5 cm",
        "source": "ISRIC SoilGrids",
        "sample_radius_m": soil_radius,
    }

    return {
        "nutrient": nutrient,
        "organ": organ,
        "fertility_score": fertility_score,
        "ph_score": ph_score,
    }


def get_soil_dynamic_bands(latitude: float, longitude: float) -> dict:
    """SMAP-derived moisture/water-balance/vegetation. Rolling 7-day window
    -- cache SHORT (hours), never at the same TTL as static properties."""
    point = ee.Geometry.Point([longitude, latitude])

    now = datetime.now(timezone.utc)
    start_date = (now - timedelta(days=7)).strftime("%Y-%m-%d")
    end_date = (now + timedelta(days=1)).strftime("%Y-%m-%d")

    collection = (
        ee.ImageCollection("NASA/SMAP/SPL4SMGP/008")
        .filterDate(start_date, end_date)
        .sort("system:time_start", False)
    )
    image = ee.Image(collection.first())
    selected_bands = image.select([
        "sm_surface", "sm_rootzone", "sm_profile",
        "sm_surface_wetness", "sm_rootzone_wetness", "sm_profile_wetness",
        "surface_temp", "precipitation_total_surface_flux",
        "land_evapotranspiration_flux", "vegetation_greenness_fraction",
        "leaf_area_index", "sm_rootzone_pctl", "sm_profile_pctl",
        "sm_surface_anomaly", "overland_runoff_flux",
    ])
    smap_values, smap_radius = _reduce_with_fallback(
        selected_bands, point, scale=9000,
        reducer=ee.Reducer.first(),
        buffer_radii=(0, 4500, 9000),
    )

    if not any(v is not None for v in smap_values.values()):
        return {
            "success": False,
            "message": "No soil moisture images found for the requested date range",
            "date_range": {"start": start_date, "end": end_date},
        }

    bands = analyze_soil_condition(smap_values)
    return {
        "success": True,
        "bands": bands,
        "date_range": {"start": start_date, "end": end_date},
        "sample_radius_m": smap_radius,
    }


def combine_soil_profile(static: dict, dynamic: dict) -> dict:
    """Cheap, non-cached combination step -- always recomputed fresh from
    (possibly cached) static + dynamic halves."""
    bands = dynamic.get("bands", {}) if dynamic.get("success") else {}
    vegetation_score = bands.get("vegetation_score")
    moisture_score_100 = bands.get("moisture_score_100")
    historical_score_100 = bands.get("historical_score_100")
    watre_balance_100 = bands.get("watre_balance_100")

    farm_health_score = weighted_average([
        (static["fertility_score"], 0.30),
        (static["ph_score"], 0.15),
        (moisture_score_100, 0.20),
        (historical_score_100, 0.10),
        (watre_balance_100, 0.10),
        (vegetation_score, 0.15),
    ])
    farm_health_score_confidence = (
        "full"
        if all(v is not None for v in [
            static["fertility_score"], static["ph_score"], moisture_score_100,
            historical_score_100, watre_balance_100, vegetation_score,
        ])
        else "partial"
    )

    return {
        "bands": bands,
        "source": "NASA SMAP L4 + iSDAsoil Africa + ISRIC SoilGrids",
        "date_range": dynamic.get("date_range"),
        "nutrient": static["nutrient"],
        "organ": static["organ"],
        "farm_health_score": (
            round(farm_health_score, 2) if farm_health_score is not None else None
        ),
        "farm_health_score_confidence": farm_health_score_confidence,
        "soil_moisture": moisture_score_100,
    }