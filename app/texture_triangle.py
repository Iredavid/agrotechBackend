"""
texture_triangle.py
--------------------
Full USDA soil texture classification, using the `soiltexture` package
(pip install soiltexture) -- a tested implementation of the actual USDA
texture triangle, rather than a hand-rolled approximation of the boundary
geometry (which is easy to get subtly wrong at edge cases).

Maps the resulting 12-class USDA texture down to the 3 broad buckets
(Sandy/Loamy/Clay) the crop model was trained on.
"""
import soiltexture

# Map every USDA class the library can return down to our 3 model buckets.
# Grounded in drainage/tuber-formation behaviour:
#   - Sandy bucket: fast-draining, low water/nutrient retention
#   - Clay bucket: slow-draining, high water retention, compaction risk
#   - Loamy bucket: the agronomic middle ground
USDA_TO_BUCKET = {
    "sand": "Sandy", "loamy sand": "Sandy", "sandy loam": "Sandy",
    "loam": "Loamy", "silt loam": "Loamy", "silt": "Loamy",
    "sandy clay loam": "Loamy", "clay loam": "Loamy", "silty clay loam": "Loamy",
    "sandy clay": "Clay", "silty clay": "Clay", "clay": "Clay",
}


def classify_texture_bucket(sand_pct: float, clay_pct: float) -> dict:
    """sand_pct, clay_pct: percentages (0-100). Silt is the implied remainder."""
    if sand_pct is None or clay_pct is None:
        return {"usda_class": None, "model_bucket": "Loamy"}  # neutral fallback
    usda_class = soiltexture.getTexture(sand_pct, clay_pct)
    bucket = USDA_TO_BUCKET.get(usda_class, "Loamy")
    return {"usda_class": usda_class, "model_bucket": bucket}
