"""ISRIC SoilGrids v2 point query (250 m modelled soil properties). Not NASA, but needed for soil context.

Docs: https://rest.isric.org/soilgrids/v2.0/docs
"""
from __future__ import annotations

import requests

URL = "https://rest.isric.org/soilgrids/v2.0/properties/query"
PROPERTIES = ["clay", "sand", "silt", "soc", "phh2o", "bdod"]
DEPTHS = ["0-5cm", "5-15cm", "15-30cm"]

# SoilGrids returns "mapped units"; dividing by the layer's d_factor gives conventional units:
# clay/sand/silt g/kg -> %, soc dg/kg -> g/kg, phh2o pH*10 -> pH, bdod cg/cm³ -> kg/dm³.
FRIENDLY = {
    "clay": ("clay", 1.0),
    "sand": ("sand", 1.0),
    "silt": ("silt", 1.0),
    "soc": ("soc", 1.0),
    "phh2o": ("ph", 1.0),
    "bdod": ("bdod", 1.0),
}


def fetch_soilgrids(lat: float, lon: float, timeout: int = 60) -> dict:
    params = [("lon", lon), ("lat", lat), ("value", "mean")]
    params += [("property", p) for p in PROPERTIES]
    params += [("depth", d) for d in DEPTHS]
    resp = requests.get(URL, params=params, timeout=timeout)
    resp.raise_for_status()
    return parse_soilgrids(resp.json())


def parse_soilgrids(payload: dict) -> dict:
    """Average the 0-30 cm layers (thickness weighted) into one topsoil record."""
    weights = {"0-5cm": 5, "5-15cm": 10, "15-30cm": 15}
    out: dict = {"source": "ISRIC SoilGrids v2 (250 m, modelled)", "depth": "0-30 cm"}
    for layer in payload.get("properties", {}).get("layers", []):
        name = layer.get("name")
        if name not in FRIENDLY:
            continue
        d_factor = layer.get("unit_measure", {}).get("d_factor", 1) or 1
        total, wsum = 0.0, 0.0
        for depth in layer.get("depths", []):
            label = depth.get("label")
            val = depth.get("values", {}).get("mean")
            if val is None or label not in weights:
                continue
            total += (val / d_factor) * weights[label]
            wsum += weights[label]
        if wsum:
            key, extra_div = FRIENDLY[name]
            out[key] = round(total / wsum / extra_div, 2)
    return out


def texture_class(soil: dict) -> str:
    """Very simplified USDA texture triangle."""
    clay, sand, silt = soil.get("clay"), soil.get("sand"), soil.get("silt")
    if clay is None or sand is None:
        return "unknown"
    if clay >= 40:
        return "clay"
    if sand >= 70 and clay < 15:
        return "loamy sand" if sand < 85 else "sand"
    if sand >= 52 and clay < 20:
        return "sandy loam"
    if silt is not None and silt >= 50 and clay < 27:
        return "silt loam"
    if clay >= 27:
        return "clay loam"
    return "loam"

