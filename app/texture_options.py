"""
texture_options.py
--------------------
The full 12-class USDA soil texture system -- the same classes SoilGrids-based
auto-detection can return (via texture_triangle.py). Exposing this exact list
in the frontend dropdown means manual farmer input and satellite auto-detection
always speak the same language -- no separate/simplified vocabulary to
reconcile.

Each entry includes a plain-language "feel test" description so a farmer who
has never heard "silty clay loam" can still identify their soil by touch,
plus which of the model's 3 broad buckets it maps to.
"""

# value = what the frontend sends back / what SoilGrids classification returns
# (lowercase, matches soiltexture package output exactly)


from app.firebase import get_texture_options


TEXTURE_VALUES = {opt["value"] for opt in get_texture_options()}
VALUE_TO_BUCKET = {opt["value"]: opt["bucket"]
                   for opt in get_texture_options()}


def validate_and_map_manual_texture(value: str) -> str:
    """Farmer's manual selection -> model bucket (Sandy/Loamy/Clay)."""
    normalized = value.strip().lower()
    if normalized not in TEXTURE_VALUES:
        raise ValueError(
            f"Unknown soil texture '{value}'. Must be one of: {sorted(TEXTURE_VALUES)}"
        )
    return VALUE_TO_BUCKET[normalized]
