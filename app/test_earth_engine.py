import os
import concurrent.futures

from dotenv import load_dotenv
import ee
from datetime import datetime, timezone, timedelta


from app.farmScore import calculate_ph_score, fertilityScore, weighted_average
from app.soil_service import analyze_soil_condition
from app.texture_triangle import classify_texture_bucket

load_dotenv()

# Initialize Earth Engine once when the application starts


def initialize_earth_engine():
    try:
        secret_path = "/etc/secrets/earth-engine-key.json"
        if os.path.exists(secret_path):
            # Render — service account
            credentials = ee.ServiceAccountCredentials(
                email=None,  # read from the key file itself
                key_file=secret_path
            )
            ee.Initialize(credentials, project=os.getenv(
                "EARTH_ENGINE_PROJECT"))
        else:
            # Local dev — interactive login (already authenticated on your machine)
            ee.Initialize(project=os.getenv("EARTH_ENGINE_PROJECT"))

        print("Earth Engine initialized successfully")
    except Exception as error:
        print(f"Earth Engine initialization failed: {error}")
        raise error


def _reduce_with_fallback(
    image,
    point,
    scale,
    reducer=None,
    crs=None,
    buffer_radii=(0, 250, 1000, 5000, 10000),
):
    """Try progressively larger buffer radii until a non-null sample is
    found, returning the SMALLEST (most spatially precise) radius that
    succeeded -- identical selection rule to the original sequential
    version.

    Performance note: the radii are independent .getInfo() network
    calls, so instead of walking them one at a time (paying for the
    sum of every radius up to and including the first success), we
    fire them all concurrently and then pick the smallest successful
    one from the completed results. This changes *when* each call
    happens, not *which* result wins -- output is unchanged.
    """
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

    # Same selection rule as the original: smallest radius (in the
    # original ordering) whose result has at least one non-null band.
    last_values = {}
    for radius in buffer_radii:
        values = results.get(radius, {})
        last_values = values
        if any(v is not None for v in values.values()):
            return values, radius

    # All radii exhausted, nothing but nulls
    return last_values, None


# ---------------------------------------------------------------------
# SOIL TEXTURE -- standalone, reusable.
#
# This is deliberately kept as its own tiny function (one small
# reduceRegion over just clay/sand) so it can power a fast, separate
# "/soil-texture-suggestion" endpoint for prefilling a form field,
# without paying for the rest of the soil-moisture pipeline.
# ---------------------------------------------------------------------
def _build_texture_image():
    clay_image = ee.Image(
        "projects/soilgrids-isric/clay_mean").select("clay_0-5cm_mean")
    sand_image = ee.Image(
        "projects/soilgrids-isric/sand_mean").select("sand_0-5cm_mean")

    # SoilGrids clay/sand are in g/kg, scaled by 10 -- divide to get %
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


def get_soil_moisture(latitude: float, longitude: float):

    point = ee.Geometry.Point([longitude, latitude])

    now = datetime.now(timezone.utc)
    start_date = (now - timedelta(days=7)).strftime("%Y-%m-%d")
    end_date = (now + timedelta(days=1)).strftime("%Y-%m-%d")

    # NUTRIENTS (iSDAsoil) -- scale 30
    raw_nitrogen = ee.Image(
        "ISDASOIL/Africa/v1/nitrogen_total").select("mean_0_20")
    raw_phosphorus = ee.Image(
        "ISDASOIL/Africa/v1/phosphorus_extractable").select("mean_0_20")
    raw_potassium = ee.Image(
        "ISDASOIL/Africa/v1/potassium_extractable").select("mean_0_20")

    nitrogen = raw_nitrogen.divide(
        100).exp().subtract(1).rename("nitrogen_g_kg")
    phosphorus = raw_phosphorus.divide(
        10).exp().subtract(1).rename("phosphorus_mg_kg")
    potassium = raw_potassium.divide(
        10).exp().subtract(1).rename("potassium_mg_kg")

    soil_nutrients = ee.Image.cat([nitrogen, phosphorus, potassium])

    # ORGANIC CARBON + PH + WATER -- scale 250. Texture is NOT part of
    # this pipeline anymore -- it only ever comes from the farmer's
    # saved profile (manual_soil_texture in crop_service), which is
    # itself only ever prefilled once, at onboarding, by the standalone
    # /soil-texture endpoint (get_soil_texture_sync). No texture lookup
    # happens here, concurrent or otherwise.
    soc_image = ee.Image("projects/soilgrids-isric/soc_mean")
    carbon = soc_image.select(
        "soc_0-5cm_mean").multiply(0.1).rename("organic_carbon_g_kg")

    ph_image = ee.Image("projects/soilgrids-isric/phh2o_mean")
    ph = ph_image.select("phh2o_0-5cm_mean").multiply(0.1).rename("soil_ph")

    water_collection = ee.ImageCollection("ISRIC/SoilGrids250m/v2_0")
    first_water_image = ee.Image(water_collection.first())
    water = first_water_image.select("val_0_5cm_mean").multiply(
        0.001).rename("water_content_volume_fraction")

    properties_image = ee.Image.cat([carbon, ph, water])

    # SMAP -- scale 9000
    collection = (
        ee.ImageCollection("NASA/SMAP/SPL4SMGP/008")
        .filterDate(start_date, end_date)
        .sort("system:time_start", False)
    )

    def fetch_nutrients():
        return _reduce_with_fallback(soil_nutrients, point, scale=30)

    def fetch_properties():
        return _reduce_with_fallback(properties_image, point, scale=250)

    def fetch_smap():
        image = ee.Image(collection.first())
        selected_bands = image.select([
            "sm_surface", "sm_rootzone", "sm_profile",
            "sm_surface_wetness", "sm_rootzone_wetness", "sm_profile_wetness",
            "surface_temp", "precipitation_total_surface_flux",
            "land_evapotranspiration_flux", "vegetation_greenness_fraction",
            "leaf_area_index", "sm_rootzone_pctl", "sm_profile_pctl",
            "sm_surface_anomaly", "overland_runoff_flux",
        ])
        return _reduce_with_fallback(
            selected_bands, point, scale=9000,
            reducer=ee.Reducer.first(),
            buffer_radii=(0, 4500, 9000),
        )

    with concurrent.futures.ThreadPoolExecutor(max_workers=3) as executor:
        nutrients_future = executor.submit(fetch_nutrients)
        properties_future = executor.submit(fetch_properties)
        smap_future = executor.submit(fetch_smap)

        nutrient_values, nutrient_radius = nutrients_future.result()
        values, soil_radius = properties_future.result()
        smap_values, smap_radius = smap_future.result()

    if not any(v is not None for v in smap_values.values()):
        return {
            "success": False,
            "message": "No soil moisture images found for the requested date range",
            "date_range": {"start": start_date, "end": end_date},
        }

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

    organicComp = {
        "organic_carbon": {"value": values.get("organic_carbon_g_kg"), "unit": "g/kg"},
        "ph": {"value": values.get("soil_ph"), "unit": "pH"},
        "water_content_at_field_capacity": {
            "value": values.get("water_content_volume_fraction"),
            "unit": "cm3/cm3",
            "suction": "33 kPa",
        },
        "depth": "0-5 cm",
        "source": "ISRIC SoilGrids",
        "sample_radius_m": soil_radius,
    }

    soilServ_band = analyze_soil_condition(smap_values)

    vegetation_score = soilServ_band.get("vegetation_score")
    moisture_score_100 = soilServ_band.get("moisture_score_100")
    historical_score_100 = soilServ_band.get("historical_score_100")
    watre_balance_100 = soilServ_band.get("watre_balance_100")

    farm_health_score = weighted_average([
        (fertility_score, 0.30),
        (ph_score, 0.15),
        (moisture_score_100, 0.20),
        (historical_score_100, 0.10),
        (watre_balance_100, 0.10),
        (vegetation_score, 0.15),
    ])

    farm_health_score_confidence = (
        "full"
        if all(v is not None for v in [
            fertility_score, ph_score, moisture_score_100,
            historical_score_100, watre_balance_100, vegetation_score,
        ])
        else "partial"
    )

    return {
        "bands": soilServ_band,
        "source": "NASA SMAP L4",
        "date_range": {"start": start_date, "end": end_date},
        "nutrient": nutrient,
        "organ": organicComp,
        "farm_health_score": (
            round(farm_health_score, 2) if farm_health_score is not None else None
        ),
        "farm_health_score_confidence": farm_health_score_confidence,
        "soil_moisture": moisture_score_100,
    }
