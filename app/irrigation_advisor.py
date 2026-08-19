"""
irrigation_advisor.py
-----------------------
Rule-based (NOT ML) irrigation text suggestion. Uses data already flowing
through the pipeline:
  - moisture_score_100 / water_balance (from SMAP, already computed per farm)
  - the recommended crop's rainfall requirement (already in the model's
    agronomic training ranges)
  - soil texture bucket (Sandy/Loamy/Clay -- already fetched)
  - the farmer's own stated irrigation_type (or "none")

No training data needed -- this is a comparison + a small lookup table.
"""

# Per-crop irrigation type fit, grounded in real agronomic behaviour:
#   preferred: best-suited methods for this crop
#   avoid: methods that actively risk harming this crop
CROP_IRRIGATION_FIT = {
    # paddy rice wants standing water
    "rice":     {"preferred": ["flood", "pump"], "avoid": []},
    # waterlogging rots tubers
    "yam":      {"preferred": ["manual", "drip", "treadle_pump"], "avoid": ["flood"]},
    "cassava":  {"preferred": ["manual", "drip", "treadle_pump"], "avoid": ["flood"]},
    # targeted root-zone watering for tree crops
    "cocoa":    {"preferred": ["drip", "manual"], "avoid": ["flood"]},
    "oil_palm": {"preferred": ["drip", "pump", "manual"], "avoid": ["flood"]},
    "maize":    {"preferred": ["sprinkler", "drip", "pump"], "avoid": []},
    # drought-tolerant, flood wastes water
    "sorghum":  {"preferred": ["sprinkler", "drip"], "avoid": ["flood"]},
    "millet":   {"preferred": ["sprinkler", "drip"], "avoid": ["flood"]},
}

# Soil texture affects HOW irrigation should be applied, regardless of crop
TEXTURE_IRRIGATION_NOTE = {
    "Sandy": "Sandy soil drains quickly, so water needs replenishing more often in smaller amounts -- drip or frequent light watering works better than flooding, which mostly runs off before the roots absorb it.",
    "Clay":  "Clay soil drains slowly and holds water -- avoid flood irrigation here, as it raises waterlogging and root-rot risk. Slower, controlled methods (drip, manual) are safer.",
    "Loamy": "Loamy soil has balanced drainage, so most irrigation methods work reasonably well here.",
}

# app/irrigation_advisor.py

# Rough water-need tiers by soil texture bucket (sandy soils drain fast -> need more frequent irrigation;
# clay soils hold water longer -> need less frequent but deeper irrigation)
_TEXTURE_WATER_NEED = {
    "Sandy": "high",
    "Sandy Loam": "moderate-high",
    "Loamy": "moderate",
    "Loam": "moderate",
    "Clay Loam": "moderate-low",
    "Clay": "low",
    "Silty": "moderate",
}


def get_fallback_irrigation_advice(
    crop: str,
    irrigation_type: str,
    soil_texture_bucket: str,
) -> str:
    """
    Rule-based irrigation guidance used when satellite moisture/water-balance
    scores are unavailable for this location. Based only on soil texture
    and the farmer's stated irrigation method -- no live soil data required.
    """
    water_need = _TEXTURE_WATER_NEED.get(soil_texture_bucket, "moderate")

    if irrigation_type in (None, "none", "rain-fed", "Rain-fed"):
        if water_need in ("high", "moderate-high"):
            return (
                f"{soil_texture_bucket} soil drains quickly, so {crop} may need "
                "supplemental watering during dry spells if rainfall is inconsistent. "
                "Monitor topsoil moisture manually, especially in the first 4-6 weeks after planting."
            )
        else:
            return (
                f"{soil_texture_bucket} soil retains moisture well, so rain-fed "
                f"conditions are usually adequate for {crop}. Watch for waterlogging "
                "after heavy rain."
            )

    # Farmer has an active irrigation system
    if water_need in ("high", "moderate-high"):
        return (
            f"Given {soil_texture_bucket} soil's fast drainage, irrigate {crop} more "
            f"frequently but in lighter amounts using your {irrigation_type} system."
        )
    else:
        return (
            f"Given {soil_texture_bucket} soil's water retention, irrigate {crop} "
            f"less frequently but more deeply using your {irrigation_type} system, "
            "and check for waterlogging risk."
        )


def _water_status(moisture_score_100: float | None, water_balance_score_100: float | None) -> str:
    """Combine the two existing 0-100 scores into a simple 3-tier status."""
    scores = [s for s in (moisture_score_100,
                          water_balance_score_100) if s is not None]
    if not scores:
        return "unknown"
    avg = sum(scores) / len(scores)
    if avg >= 70:
        return "sufficient"
    elif avg >= 40:
        return "moderate"
    return "deficit"


def get_irrigation_advice(
    crop: str,
    irrigation_type: str,          # "none" or one of IRRIGATION_OPTIONS values
    soil_texture_bucket: str,      # "Sandy" / "Loamy" / "Clay"
    moisture_score_100: float | None,
    water_balance_score_100: float | None,
) -> dict:
    if moisture_score_100 is None or water_balance_score_100 is None:
        return {
            "advice": get_fallback_irrigation_advice(crop, irrigation_type, soil_texture_bucket),
            "confidence": "low",
            "reason": "satellite_moisture_data_unavailable",
        }
    status = _water_status(moisture_score_100, water_balance_score_100)
    fit = CROP_IRRIGATION_FIT.get(crop, {"preferred": ["drip"], "avoid": []})

    def _texture_caution_for(irr_type: str) -> str:
        """Only surface a texture caution on a genuine mismatch -- e.g. flood
        on clay is fine (even ideal) for rice, but risky for yam/cassava/cocoa.
        Flood on sandy soil is always wasteful (drains before roots absorb it),
        regardless of crop preference."""
        if irr_type in fit.get("avoid", []):
            return TEXTURE_IRRIGATION_NOTE.get(soil_texture_bucket, "")
        if irr_type == "flood" and soil_texture_bucket == "Sandy":
            return TEXTURE_IRRIGATION_NOTE.get("Sandy", "")
        return ""

    suggested_task = None

    if irrigation_type == "none":
        if status == "deficit":
            best_type = fit["preferred"][0]
            best_label = best_type.replace("_", " ").title()
            caution = _texture_caution_for(best_type)
            message = (
                f"Soil moisture looks low for {crop} right now, and this farm is rain-fed. "
                f"Consider irrigating -- {best_label} tends to suit {crop} well."
                + (f" {caution}" if caution else "")
            )
            suggested_task = {
                "title": f"Irrigate {crop} plot",
                "priority": "high",
                "reason": "Low soil moisture detected, no irrigation system in use",
            }
        elif status == "moderate":
            message = f"Soil moisture is moderate for {crop}. Rain-fed conditions are holding for now, but worth monitoring if dry weather continues."
        else:
            message = f"Rainfall and soil moisture currently look sufficient for {crop} -- no irrigation needed right now."
    else:
        type_label = irrigation_type.replace("_", " ").title()
        caution = _texture_caution_for(irrigation_type)
        mismatch_warning = f" Note: {type_label} irrigation carries some risk for {crop} here -- {caution}" if caution else ""

        if status == "deficit":
            message = (
                f"Soil moisture is still low for {crop} despite {type_label} irrigation -- "
                f"consider increasing frequency or checking coverage.{mismatch_warning}"
            )
            suggested_task = {
                "title": f"Check {type_label} irrigation coverage for {crop} plot",
                "priority": "medium",
                "reason": "Soil moisture still low despite active irrigation",
            }
        else:
            message = f"Your {type_label} irrigation appears well-matched to current conditions for {crop}.{mismatch_warning}"

    return {
        "water_status": status,
        "irrigation_type_used": irrigation_type,
        "advice_text": message,
        "suggested_task": suggested_task,
    }
