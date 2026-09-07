"""
app/fertilizer_data.py
-----------------------
Static agronomic reference data for the Fertilizer Advisor.

IMPORTANT: The blanket NPK rates below are compiled from commonly-cited
Nigerian extension/agronomy sources (IITA, FMARD/state ADP fertilizer
guides) as representative midpoints for a reference/base yield. They are
reasonable defaults for a v1 launch, but should be reviewed against your
state ADP's current fertilizer recommendation sheet before this is treated
as authoritative in production -- rates do get revised, and some states
publish their own. Treat this file as the single place to update when
that review happens.

Everything downstream (fertilizer_service.py) is written so that improving
these numbers later doesn't require touching the calculation logic.
"""

from dataclasses import dataclass


@dataclass(frozen=True)
class CropNPKRate:
    crop: str
    # Blanket recommendation, kg/ha of nutrient, at reference_yield_t_ha
    n_kg_ha: float
    p2o5_kg_ha: float
    k2o_kg_ha: float
    reference_yield_t_ha: float
    # Rates are scaled by (target_yield / reference_yield), clamped to
    # this range so an unrealistic target yield doesn't produce an
    # unrealistic dose.
    min_scale: float = 0.6
    max_scale: float = 1.6
    notes: str = ""


# Base rates at a reference (typical smallholder) yield level.
# Sources: IITA agronomy guides / FMARD & state ADP blanket recommendations,
# cross-checked against commonly published ranges for each crop.
CROP_NPK_RATES: dict[str, CropNPKRate] = {
    "maize": CropNPKRate(
        crop="maize", n_kg_ha=120, p2o5_kg_ha=60, k2o_kg_ha=60,
        reference_yield_t_ha=4.0,
        notes="Split N: basal + top-dress at 4-6 weeks.",
    ),
    "rice": CropNPKRate(
        crop="rice", n_kg_ha=120, p2o5_kg_ha=60, k2o_kg_ha=60,
        reference_yield_t_ha=4.5,
        notes="Lowland/irrigated rate; upland rainfed rates run lower.",
    ),
    "cassava": CropNPKRate(
        crop="cassava", n_kg_ha=80, p2o5_kg_ha=40, k2o_kg_ha=80,
        reference_yield_t_ha=15.0,
        notes="K demand is high for tuber bulking.",
    ),
    "yam": CropNPKRate(
        crop="yam", n_kg_ha=60, p2o5_kg_ha=60, k2o_kg_ha=100,
        reference_yield_t_ha=12.0,
        notes="Keep N moderate -- excess N favours vine growth over tubers.",
    ),
    "sorghum": CropNPKRate(
        crop="sorghum", n_kg_ha=60, p2o5_kg_ha=30, k2o_kg_ha=30,
        reference_yield_t_ha=2.0,
    ),
    "millet": CropNPKRate(
        crop="millet", n_kg_ha=60, p2o5_kg_ha=30, k2o_kg_ha=30,
        reference_yield_t_ha=1.5,
        notes="Drought-tolerant, low-input crop -- avoid over-fertilizing.",
    ),
    "cocoa": CropNPKRate(
        crop="cocoa", n_kg_ha=100, p2o5_kg_ha=40, k2o_kg_ha=100,
        reference_yield_t_ha=0.6,
        min_scale=0.8, max_scale=1.3,
        notes="Mature-tree hectare-equivalent rate; establishment-phase rates differ substantially.",
    ),
    "oil_palm": CropNPKRate(
        crop="oil_palm", n_kg_ha=60, p2o5_kg_ha=30, k2o_kg_ha=150,
        reference_yield_t_ha=3.5,
        min_scale=0.8, max_scale=1.3,
        notes="Mature-palm hectare-equivalent rate; K-hungry crop.",
    ),
}


@dataclass(frozen=True)
class FertilizerProduct:
    name: str
    n_pct: float = 0.0
    p2o5_pct: float = 0.0
    k2o_pct: float = 0.0


FERTILIZER_PRODUCTS: dict[str, FertilizerProduct] = {
    "urea": FertilizerProduct(name="Urea", n_pct=0.46),
    "ssp": FertilizerProduct(name="Single Super Phosphate (SSP)", p2o5_pct=0.18),
    "mop": FertilizerProduct(name="Muriate of Potash (MOP)", k2o_pct=0.60),
    "npk_15_15_15": FertilizerProduct(
        name="NPK 15-15-15", n_pct=0.15, p2o5_pct=0.15, k2o_pct=0.15,
    ),
    "npk_20_10_10": FertilizerProduct(
        name="NPK 20-10-10", n_pct=0.20, p2o5_pct=0.10, k2o_pct=0.10,
    ),
    "npk_12_12_17": FertilizerProduct(
        name="NPK 12-12-17", n_pct=0.12, p2o5_pct=0.12, k2o_pct=0.17,
    ),
}


# --------------------------------------------------------------------
# Soil test interpretation bands.
#
# iSDAsoil (Africa, 0-20cm) reports:
#   - nitrogen: TOTAL nitrogen, mg/kg  (not directly plant-available --
#     used here only as a fertility signal, not to size the N dose)
#   - phosphorus: EXTRACTABLE phosphorus, mg/kg
#   - potassium: EXTRACTABLE potassium, mg/kg
#
# Bands below are adapted from commonly used extractable-P / exchangeable-K
# critical-level ranges for tropical soils. As with the crop rates, these
# are reasonable v1 defaults -- if you have iSDAsoil-specific calibration
# data for Nigeria, swap these bounds in without touching the service logic.
# --------------------------------------------------------------------

def classify_p_level(p_mg_kg: float | None) -> str:
    if p_mg_kg is None:
        return "unknown"
    if p_mg_kg < 10:
        return "low"
    if p_mg_kg < 20:
        return "medium"
    return "high"


def classify_k_level(k_mg_kg: float | None) -> str:
    if k_mg_kg is None:
        return "unknown"
    if k_mg_kg < 90:
        return "low"
    if k_mg_kg < 180:
        return "medium"
    return "high"


# Multiplier applied to the blanket P2O5 / K2O rate based on the soil's
# existing extractable level -- low soil level -> apply full (or boosted)
# rate, high existing level -> cut back, since the crop's need is already
# partly met by the soil.
LEVEL_ADJUSTMENT_MULTIPLIER = {
    "low": 1.15,
    "medium": 1.0,
    "high": 0.6,
    "unknown": 1.0,
}


def ph_note(ph: float | None) -> str | None:
    if ph is None:
        return None
    if ph < 5.5:
        return (
            f"Soil pH is {ph:.1f} (acidic). Nutrient uptake, especially P, "
            "is reduced below pH 5.5 -- consider agricultural lime ahead of "
            "the next planting season."
        )
    if ph > 7.5:
        return (
            f"Soil pH is {ph:.1f} (alkaline). Micronutrient availability "
            "(Zn, Fe) can drop at this range -- watch for deficiency symptoms."
        )
    return None
