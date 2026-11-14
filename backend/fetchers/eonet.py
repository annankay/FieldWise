"""NASA EONET: natural events (floods, droughts, storms, wildfires, heat) recorded near the field.

Docs: https://eonet.gsfc.nasa.gov/docs/v3  (no key needed)
"""
from __future__ import annotations

import math
import time

import requests

URL = "https://eonet.gsfc.nasa.gov/api/v3/events"
CATEGORIES = "drought,floods,severeStorms,wildfires,tempExtremes,dustHaze,landslides"
_cache: dict = {}


def _distance_km(lat1, lon1, lat2, lon2) -> float:
    r = 6371.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp, dl = p2 - p1, math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))


def _points(geom: dict) -> list[tuple[float, float]]:
    coords = geom.get("coordinates")
    if geom.get("type") == "Point" and coords:
        return [(coords[1], coords[0])]
    pts = []

    def walk(c):
        if isinstance(c, (list, tuple)) and len(c) == 2 and all(isinstance(x, (int, float)) for x in c):
            pts.append((c[1], c[0]))
        elif isinstance(c, (list, tuple)):
            for x in c:
                walk(x)
    walk(coords)
    return pts


def nearby_events(lat: float, lon: float, radius_km: float = 300, years: int = 10, timeout: int = 20) -> dict:
    key = (round(lat, 1), round(lon, 1), radius_km, years)
    hit = _cache.get(key)
    if hit and time.time() - hit[0] < 6 * 3600:
        return hit[1]
    dlat = radius_km / 111.0
    dlon = radius_km / (111.0 * max(0.2, math.cos(math.radians(lat))))
    bbox = f"{lon - dlon:.3f},{lat + dlat:.3f},{lon + dlon:.3f},{lat - dlat:.3f}"   # minLon,maxLat,maxLon,minLat
    end = time.strftime("%Y-%m-%d")
    start = time.strftime("%Y-%m-%d", time.gmtime(time.time() - years * 365.25 * 86400))
    params = {"bbox": bbox, "status": "all", "start": start, "end": end, "category": CATEGORIES, "limit": 200}
    resp = requests.get(URL, params=params, timeout=timeout)
    resp.raise_for_status()
    events = []
    for ev in resp.json().get("events", []):
        best = None
        for g in ev.get("geometry", []):
            for plat, plon in _points(g):
                d = _distance_km(lat, lon, plat, plon)
                if best is None or d < best[0]:
                    best = (d, g.get("date"))
        if best is None or best[0] > radius_km:
            continue
        events.append({"id": ev.get("id"), "title": ev.get("title"),
                       "category": (ev.get("categories") or [{}])[0].get("id"),
                       "category_title": (ev.get("categories") or [{}])[0].get("title"),
                       "date": (best[1] or "")[:10], "distance_km": round(best[0]),
                       "link": (ev.get("sources") or [{}])[0].get("url")})
    events.sort(key=lambda e: e["date"], reverse=True)
    out = {"events": events[:25], "radius_km": radius_km, "years": years, "source": "NASA EONET v3",
           "fetched": end}
    _cache[key] = (time.time(), out)
    return out

