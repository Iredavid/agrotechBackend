

from app.firebase import get_irrigation_options


IRRIGATION_VALUES = {opt["value"] for opt in get_irrigation_options()}


def validate_irrigation_type(value: str) -> str:
    normalized = value.strip().lower().replace(" ", "_").replace("-", "_")
    if normalized == "rain_fed":
        normalized = "none"
    if normalized not in IRRIGATION_VALUES:
        raise ValueError(
            f"Unknown irrigation type '{value}'. Must be one of: {sorted(IRRIGATION_VALUES)}"
        )
    return normalized
