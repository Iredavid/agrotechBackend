"""
app/fertilizer_service.py
--------------------------
Computes a farm-specific NPK requirement and a concrete product/application
plan (which fertilizer, how many kg, when to apply).

Design:
  1. Start from the published blanket NPK rate for the crop (fertilizer_data),
     scaled by the farmer's target yield vs. the reference yield.
  2. Adjust the P and K portion of that rate using the farm's real
     extractable-P / extractable-K soil test (iSDAsoil, already fetched by
     crop_service.get_crop_recommendation -- no new external call needed).
     N is left at the published rate: total soil N (iSDAsoil) isn't a
     reliable proxy for how much of it will mineralize into plant-available
     form this season, so it's surfaced as an informational note rather than
     used to shrink the N dose.
  3. Convert the adjusted kg/ha nutrient requirement into an actual product
     plan: an NPK 15-15-15 basal dose sized to cover P and K, topped up with
     Urea to cover any remaining N -- the same two-product pattern already
     used in the current frontend mock, just computed instead of hardcoded.
  4. Scale everything by farm_size_ha for total quantities.

This function takes the SAME `features` shape crop_service.py already builds
(features_used) plus farm_size_ha, so it can be called right after
get_crop_recommendation() with no extra soil/weather fetch.
"""


from app.fertilizer_data import (
    CROP_NPK_RATES,
    FERTILIZER_PRODUCTS,
    classify_p_level,
    classify_k_level,
    LEVEL_ADJUSTMENT_MULTIPLIER,
    ph_note,
)


def _clamp(value: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, value))


def calculate_npk_requirement(
    crop: str,
    target_yield_t_ha: float,
    soil_p_mg_kg: float | None,
    soil_k_mg_kg: float | None,
) -> dict:
    """Returns the adjusted per-hectare N / P2O5 / K2O requirement (kg/ha)
    for one crop on one farm, plus the reasoning behind the adjustment."""

    rate = CROP_NPK_RATES.get(crop)
    if rate is None:
        raise ValueError(
            f"No fertilizer reference rate configured for crop '{crop}'. "
            f"Supported crops: {sorted(CROP_NPK_RATES)}"
        )

    yield_scale = _clamp(
        target_yield_t_ha / rate.reference_yield_t_ha,
        rate.min_scale,
        rate.max_scale,
    )

    p_level = classify_p_level(soil_p_mg_kg)
    k_level = classify_k_level(soil_k_mg_kg)
    p_multiplier = LEVEL_ADJUSTMENT_MULTIPLIER[p_level]
    k_multiplier = LEVEL_ADJUSTMENT_MULTIPLIER[k_level]

    n_req = rate.n_kg_ha * yield_scale
    p_req = rate.p2o5_kg_ha * yield_scale * p_multiplier
    k_req = rate.k2o_kg_ha * yield_scale * k_multiplier

    return {
        "crop": crop,
        "n_kg_ha": round(n_req, 1),
        "p2o5_kg_ha": round(p_req, 1),
        "k2o_kg_ha": round(k_req, 1),
        "yield_scale_applied": round(yield_scale, 2),
        "soil_p_level": p_level,
        "soil_k_level": k_level,
        "crop_notes": rate.notes or None,
    }


def build_product_plan(n_req: float, p_req: float, k_req: float) -> dict:
    """Converts a kg/ha N / P2O5 / K2O requirement into an actual two-product
    application plan: NPK 15-15-15 basal dose sized to cover P and K, then
    Urea top-dress to cover any N shortfall left after the basal dose."""

    blend = FERTILIZER_PRODUCTS["npk_15_15_15"]
    urea = FERTILIZER_PRODUCTS["urea"]

    # Basal blend must supply at least as much P and K as required --
    # take whichever nutrient demands the larger blend quantity.
    blend_kg_ha_for_p = p_req / blend.p2o5_pct if p_req > 0 else 0
    blend_kg_ha_for_k = k_req / blend.k2o_pct if k_req > 0 else 0
    basal_blend_kg_ha = max(blend_kg_ha_for_p, blend_kg_ha_for_k)

    n_supplied_by_blend = basal_blend_kg_ha * blend.n_pct
    remaining_n = max(0.0, n_req - n_supplied_by_blend)
    topdress_urea_kg_ha = remaining_n / urea.n_pct if remaining_n > 0 else 0

    return {
        "basal": {
            "product": blend.name,
            "timing": "At planting",
            "kg_per_ha": round(basal_blend_kg_ha, 1),
        },
        "topdress": {
            "product": urea.name,
            "timing": "4-6 weeks after planting",
            "kg_per_ha": round(topdress_urea_kg_ha, 1),
        },
        "n_supplied_by_basal_kg_ha": round(n_supplied_by_blend, 1),
    }


async def get_fertilizer_recommendation(
    crop: str,
    target_yield_t_ha: float,
    farm_size_ha: float,
    features: dict,
) -> dict:
    """Main entry point. `features` is the same dict crop_service.py already
    builds as `features_used` (N, P, K, ph, soil_texture, ...) -- no new
    soil/weather fetch needed."""

    soil_p = features.get("P")
    soil_k = features.get("K")
    soil_n = features.get("N")
    ph = features.get("ph")

    requirement = calculate_npk_requirement(
        crop=crop,
        target_yield_t_ha=target_yield_t_ha,
        soil_p_mg_kg=soil_p,
        soil_k_mg_kg=soil_k,
    )

    plan_per_ha = build_product_plan(
        n_req=requirement["n_kg_ha"],
        p_req=requirement["p2o5_kg_ha"],
        k_req=requirement["k2o_kg_ha"],
    )

    farm_totals = {
        "basal_total_kg": round(
            plan_per_ha["basal"]["kg_per_ha"] * farm_size_ha, 1
        ),
        "topdress_total_kg": round(
            plan_per_ha["topdress"]["kg_per_ha"] * farm_size_ha, 1
        ),
    }

    notes = []
    if requirement["crop_notes"]:
        notes.append(requirement["crop_notes"])
    soil_ph_note = ph_note(ph)
    if soil_ph_note:
        notes.append(soil_ph_note)
    if soil_n is not None:
        notes.append(
            f"Soil total nitrogen reading: {soil_n:.0f} mg/kg. Used as a "
            "fertility signal only -- the N dose above follows the "
            "published crop rate rather than being derived from this value."
        )

    return {
        "crop": crop,
        "farm_size_ha": farm_size_ha,
        "target_yield_t_ha": target_yield_t_ha,
        "requirement_per_ha": {
            "n_kg_ha": requirement["n_kg_ha"],
            "p2o5_kg_ha": requirement["p2o5_kg_ha"],
            "k2o_kg_ha": requirement["k2o_kg_ha"],
        },
        "soil_context": {
            "p_level": requirement["soil_p_level"],
            "k_level": requirement["soil_k_level"],
            "ph": ph,
        },
        "application_plan": {
            "per_ha": plan_per_ha,
            "farm_totals": farm_totals,
        },
        "notes": notes,
    }
