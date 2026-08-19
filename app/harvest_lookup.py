"""
harvest_lookup.py
------------------
Time-to-harvest is a fixed agronomic fact per crop, not something the ML model
should predict from soil chemistry -- no dataset or training needed. This is a
static reference table (typical ranges for common Nigerian varieties).

NOTE: cocoa and oil_palm are perennial tree crops -- "time to harvest" means
something different for them (years to FIRST bearing, then continuous annual
harvest) vs annual crops (one harvest per planting cycle). The UI should
probably label these differently so farmers aren't misled.
"""

HARVEST_INFO = {
    "maize":    {"type": "annual",    "min_days": 90,  "max_days": 120, "display": "90–120 days"},
    "rice":     {"type": "annual",    "min_days": 105, "max_days": 150, "display": "105–150 days"},
    "cassava":  {"type": "annual",    "min_days": 240, "max_days": 365, "display": "8–12 months"},
    "millet":   {"type": "annual",    "min_days": 70,  "max_days": 100, "display": "70–100 days"},
    "sorghum":  {"type": "annual",    "min_days": 90,  "max_days": 120, "display": "90–120 days"},
    "yam":      {"type": "annual",    "min_days": 180, "max_days": 300, "display": "6–10 months"},
    "cocoa":    {"type": "perennial", "min_days": 730, "max_days": 1095,
                 "display": "First harvest in 2–3 years, then continuous (2 seasons/yr)"},
    "oil_palm": {"type": "perennial", "min_days": 900, "max_days": 1095,
                 "display": "First harvest in 30–36 months, then continuous year-round"},
}


def get_harvest_info(crop: str) -> dict:
    return HARVEST_INFO.get(crop, {"type": "unknown", "display": "Not available"})
