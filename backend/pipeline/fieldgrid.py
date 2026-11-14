from __future__ import annotations

import numpy as np
from scipy import ndimage


def _norm(a: np.ndarray) -> np.ndarray:
    lo, hi = np.nanpercentile(a, 2), np.nanpercentile(a, 98)
    return np.clip((a - lo) / (hi - lo + 1e-9), 0, 1)


def vulnerability_grid(dem: dict, lat: float, lon: float, heavy_days_per_year: float,
                       frost_days_per_year: float) -> dict | None:
    if not dem or "elev" not in dem:
        return None
    elev = np.array(dem["elev"], dtype=float)
    cell = float(dem.get("cell_m", 30))
    gy, gx = np.gradient(elev, cell)
    slope_pct = np.hypot(gx, gy) * 100
    local_mean = ndimage.uniform_filter(elev, size=7, mode="nearest")
    rel_elev = elev - local_mean                      # <0 hollows, >0 ridges
    # crude topographic wetness: low + flat = wet
    wetness = _norm(-rel_elev) * 0.6 + (1 - _norm(slope_pct)) * 0.4

    storm_factor = min(1.0, heavy_days_per_year / 8.0)
    erosion = np.clip(_norm(slope_pct) * (0.4 + 0.6 * storm_factor) * (0.5 + slope_pct.mean() / 10), 0, 1)
    frost_factor = min(1.0, frost_days_per_year / 60.0)
    frost = np.clip(_norm(-rel_elev) * frost_factor, 0, 1)
    water_stress = np.clip(1 - wetness, 0, 1)

    n = elev.shape[0]
    # cell size in degrees for drawing rectangles on the map
    dlat = cell / 111_320.0
    dlon = cell / (111_320.0 * np.cos(np.radians(lat)))
    origin_lat = lat + dlat * n / 2
    origin_lon = lon - dlon * n / 2

def pack(a):
        return np.round(a, 3).tolist()

return {
        "cells": n, "cell_m": cell, "origin": [origin_lat, origin_lon], "dlat": dlat, "dlon": dlon,
        "layers": {"erosion": pack(erosion), "frost": pack(frost), "water_stress": pack(water_stress),
                   "slope_pct": pack(slope_pct)},
        "summary": {
            "mean_slope_pct": round(float(slope_pct.mean()), 2),
            "max_slope_pct": round(float(slope_pct.max()), 2),
            "high_erosion_share": round(float((erosion > 0.6).mean()), 3),
            "frost_pocket_share": round(float((frost > 0.5).mean()), 3),
            "dry_spot_share": round(float((water_stress > 0.65).mean()), 3),
            "elev_range_m": round(float(elev.max() - elev.min()), 1),
        },
        "source": dem.get("source", "SRTM"),
    }
