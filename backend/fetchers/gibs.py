"""NASA GIBS (the imagery behind Worldview): daily satellite map tiles for the 'time machine' map.

Layer names change as NASA reprocesses data, so instead of hard-coding them we read GIBS's
GetCapabilities once a day and pick the first available layer for each theme. Tiles are then loaded
directly by the farmer's browser from GIBS (no key, nothing stored on our server).
"""
from __future__ import annotations

import re
import time
import xml.etree.ElementTree as ET

import requests

CAPS_URL = "https://gibs.earthdata.nasa.gov/wmts/epsg3857/best/wmts.cgi?SERVICE=WMTS&REQUEST=GetCapabilities"
TILE_ROOT = "https://gibs.earthdata.nasa.gov/wmts/epsg3857/best"
NS = {"wmts": "http://www.opengis.net/wmts/1.0", "ows": "http://www.opengis.net/ows/1.1",
      "xlink": "http://www.w3.org/1999/xlink"}

# theme -> candidate layer ids in order of preference (regexes)
THEMES = [
    ("truecolor", "Satellite photo", "MODIS Terra true colour (250 m)",
     [r"^MODIS_Terra_CorrectedReflectance_TrueColor$", r"^VIIRS_SNPP_CorrectedReflectance_TrueColor$"]),
    ("ndvi", "Greenness (NDVI)", "MODIS vegetation index",
     [r"^MODIS_Terra_NDVI_8Day$", r"^MODIS_Aqua_NDVI_8Day$", r"^MODIS_Terra_L3_NDVI_16Day$",
      r"^MODIS_Terra_L3_NDVI_Monthly$", r"NDVI"]),
    ("soil", "Soil moisture", "SMAP L4 root-zone soil moisture (9 km)",
     [r"^SMAP_L4_Analyzed_Root_Zone_Soil_Moisture$", r"^SMAP_L4_Analyzed_Surface_Soil_Moisture$",
      r"^SMAP_L4_.*Root_Zone_Soil_Moisture$", r"^SMAP_L3.*Soil_Moisture"]),
    ("lst", "Ground heat", "MODIS land surface temperature (day)",
     [r"^MODIS_Terra_L3_Land_Surface_Temp_8Day_Day$", r"^MODIS_Terra_L3_Land_Surface_Temp_Daily_Day$",
      r"^MODIS_Terra_Land_Surface_Temp_Day$", r"Land_Surface_Temp.*Day"]),
    ("rain", "Rainfall", "GPM IMERG precipitation",
     [r"^IMERG_Precipitation_Rate$", r"^IMERG_Precipitation_Rate_30min$", r"IMERG.*Precip"]),
    ("et", "Water use (ET)", "Evapotranspiration",
     [r"ECOSTRESS.*(ET|Evapotranspiration)", r"MODIS.*Evapotranspiration", r"_ET_"]),
]

_cache: dict = {"t": 0, "data": None}


def _parse_time(dim_values: list[str]) -> dict:
    """GIBS time dimension values are like '2000-02-24/2026-11-01/P8D' or single dates."""
    starts, ends, period = [], [], None
    for v in dim_values:
        parts = v.strip().split("/")
        if len(parts) == 3:
            starts.append(parts[0][:10])
            ends.append(parts[1][:10])
            period = parts[2]
        elif parts and parts[0]:
            starts.append(parts[0][:10])
            ends.append(parts[0][:10])
    if not starts:
        return {}
    return {"start": min(starts), "end": max(ends), "period": period}


def parse_capabilities(xml_text: str) -> dict:
    root = ET.fromstring(xml_text)
    layers = {}
    for layer in root.iter(f"{{{NS['wmts']}}}Layer"):
        ident = layer.findtext("ows:Identifier", namespaces=NS)
        if not ident:
            continue
        tms = [t.findtext("wmts:TileMatrixSet", namespaces=NS) for t in layer.findall("wmts:TileMatrixSetLink", NS)]
        fmt = layer.findtext("wmts:Format", namespaces=NS) or "image/png"
        dims = {}
        for d in layer.findall("wmts:Dimension", NS):
            name = d.findtext("ows:Identifier", namespaces=NS)
            dims[name] = {"default": d.findtext("wmts:Default", namespaces=NS),
                          "values": [v.text for v in d.findall("wmts:Value", NS) if v.text]}
        legend = None
        for st in layer.findall("wmts:Style", NS):
            for lg in st.findall("wmts:LegendURL", NS):
                href = lg.get(f"{{{NS['xlink']}}}href")
                if href and (legend is None or "horizontal" in href.lower()):
                    legend = href
        title = layer.findtext("ows:Title", namespaces=NS)
        layers[ident] = {"id": ident, "title": title, "tms": tms[0] if tms else None, "format": fmt,
                         "time": _parse_time(dims.get("Time", {}).get("values", [])) if "Time" in dims else None,
                         "default_time": dims.get("Time", {}).get("default"), "legend": legend}
    return layers


def pick_themes(layers: dict) -> list[dict]:
    out = []
    ids = list(layers)
    for key, label, about, patterns in THEMES:
        chosen = None
        for pat in patterns:
            match = next((i for i in ids if re.search(pat, i) and layers[i]["tms"]), None)
            if match:
                chosen = layers[match]
                break
        if not chosen:
            continue
        ext = "jpg" if "jpeg" in chosen["format"] else "png"
        max_zoom = int(re.search(r"Level(\d+)", chosen["tms"]).group(1)) if re.search(r"Level(\d+)", chosen["tms"] or "") else 9
        out.append({"key": key, "label": label, "about": about, "layer": chosen["id"], "title": chosen["title"],
                    "max_native_zoom": max_zoom, "time": chosen["time"], "legend": chosen["legend"],
                    "template": f"{TILE_ROOT}/{chosen['id']}/default/{{time}}/{chosen['tms']}/{{z}}/{{y}}/{{x}}.{ext}"})
    return out


def themes(timeout: int = 30) -> dict:
    if _cache["data"] and time.time() - _cache["t"] < 24 * 3600:
        return _cache["data"]
    resp = requests.get(CAPS_URL, timeout=timeout)
    resp.raise_for_status()
    data = {"themes": pick_themes(parse_capabilities(resp.text)), "source": "NASA GIBS / Worldview",
            "attribution": "Imagery: NASA EOSDIS GIBS"}
    _cache.update(t=time.time(), data=data)
    return data

