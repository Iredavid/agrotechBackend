"""
market_demand.py
------------------
IMPORTANT CAVEAT: this is a STRUCTURAL demand estimate, not live pricing.
It is grounded in real, documented supply/demand dynamics (Nigeria's rice
import dependency, cassava's locally-saturated production, cocoa/oil_palm's
export demand, etc.) but it does NOT reflect this week's or this month's
actual market prices. It should be labeled to the farmer as an estimate,
not presented as live data.

REAL FIX (not built here, needs credentials): commodity.ng is a Nigerian
agri-commodity platform with live state-level prices for 50+ commodities
and mentions a "Developer API" -- but it isn't publicly documented, so you'd
need to contact them directly for API access. Once you have that, swap
get_market_demand() below for a real API call -- the rest of the pipeline
(enrichment shape, UI contract) doesn't need to change.
"""

MARKET_DEMAND = {
    "rice":      {"tier": "High",   "note": "Nigeria imports a large share of rice consumed; strong structural demand-supply gap"},
    "maize":     {"tier": "High",   "note": "Key input for poultry feed and food processing; demand consistently outpaces domestic supply"},
    "cassava":   {"tier": "Medium", "note": "Nigeria's largest staple by volume (60M+ MT/yr) -- high total demand, but also high local supply, so price premium is moderate unless processed (garri, starch, flour)"},
    "yam":       {"tier": "Medium", "note": "Strong regional/local demand, especially in South-East/South-South and West Africa export corridor; limited by short shelf life"},
    "sorghum":   {"tier": "Medium", "note": "Steady demand from brewing/food industries in the North; less price volatility than rice/maize"},
    "millet":    {"tier": "Medium", "note": "Staple demand concentrated in the North; smaller commercial market than maize/rice/sorghum"},
    "cocoa":     {"tier": "High",   "note": "Export cash crop with strong global demand; price driven by international market, not just local"},
    "oil_palm":  {"tier": "High",   "note": "Nigeria is a net importer of palm oil despite domestic production; strong structural demand"},
}


def get_market_demand(crop: str) -> dict:
    info = MARKET_DEMAND.get(crop, {"tier": "Unknown", "note": "No demand data available for this crop"})
    return {
        "demand_tier": info["tier"],
        "demand_note": info["note"],
        "data_type": "structural_estimate",  # NOT live pricing -- flag this in the UI
    }
