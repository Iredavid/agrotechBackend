from app.farmScore import calculate_moisture_score, calculate_water_balance_score


def analyze_soil_condition(values):
    surface = values.get("sm_surface")
    rootzone = values.get("sm_rootzone")
    profile = values.get("sm_profile")

    surface_wetness = values.get("sm_surface_wetness")
    rootzone_wetness = values.get("sm_rootzone_wetness")
    profile_wetness = values.get("sm_profile_wetness")

    profile_percentile = values.get("sm_profile_pctl")
    surface_anomaly = values.get("sm_surface_anomaly")
    surface_temp = values.get("surface_temp")
    land_evapotranspiration_flux = values.get("land_evapotranspiration_flux")

    raw_greenness = values.get("vegetation_greenness_fraction")
    vegetation_greenness = raw_greenness * 100 if raw_greenness is not None else None

    raw_lai = values.get("leaf_area_index")
    normalized_lai = (
        (min(max(raw_lai, 0), 6) / 6) * 100
        if raw_lai is not None
        else None
    )

    runOff = values.get("overland_runoff_flux")
    evapotranspiration = values.get("land_evapotranspiration_flux")
    precipitation = values.get("precipitation_total_surface_flux")

    surface_percent = surface * 100 if surface is not None else None
    rootzone_percent = rootzone * 100 if rootzone is not None else None
    profile_percent = profile * 100 if profile is not None else None

    moisture_index = (
        (rootzone or 0) * 0.50
        + (surface or 0) * 0.25
        + (profile or 0) * 0.25
    )
    moisture_index_percent = moisture_index * 100

    wetness_index = (
        (rootzone_wetness or 0) * 0.50
        + (surface_wetness or 0) * 0.25
        + (profile_wetness or 0) * 0.25
    )
    wetness_index_percent = wetness_index * 100

    moisture_score_100 = calculate_moisture_score(moisture_index_percent)

    # Guard: profile_percentile may be missing for this pixel/date
    historical_score_100 = (
        max(0, min(100, profile_percentile))
        if profile_percentile is not None
        else None
    )

    # Guard: any of these three can legitimately be None from Earth Engine
    if precipitation is not None and evapotranspiration is not None and runOff is not None:
        water_balance = (precipitation - evapotranspiration - runOff) * 86400
        watre_balance_100 = calculate_water_balance_score(water_balance)
    else:
        water_balance = None
        watre_balance_100 = None

    surface_temperature_celsius = (
        surface_temp - 273.15 if surface_temp is not None else None
    )

    vegetation_score = (
        vegetation_greenness * 0.70 + normalized_lai * 0.3
        if vegetation_greenness is not None and normalized_lai is not None
        else None
    )

    return {
        "overall_moisture_index": round(moisture_index_percent, 2),
        "overall_wetness_index": round(wetness_index_percent, 2),
        "historical_percentile": profile_percentile,
        "surface_anomaly": surface_anomaly,
        "surface_temperature_celsius": surface_temperature_celsius,
        "land_evapotranspiration": land_evapotranspiration_flux,
        "vegetation_score": vegetation_score,
        "water_balance": water_balance,
        "moisture_score_100": moisture_score_100,
        "historical_score_100": historical_score_100,
        "watre_balance_100": watre_balance_100,
    }