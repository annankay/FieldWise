from __future__ import annotations

import numpy as np
import pandas as pd

from backend.pipeline.features import MONTH_NAMES, Climate

MOIST_RATIO = 0.5   # FAO length-of-growing-period rule: rain >= half of ET0


def _runs(flags: np.ndarray) -> list[list[int]]:
    """Circular runs of True months (0-based)."""
    if flags.all():
        return [list(range(12))]
    if not flags.any():
        return []
    start = int(np.argmin(flags))  # begin scan at a dry month so runs don't split at Dec/Jan
    runs, cur = [], []
    for k in range(12):
        m = (start + k) % 12
        if flags[m]:
            cur.append(m)
        elif cur:
            runs.append(cur)
            cur = []
    if cur:
        runs.append(cur)
    return runs

def growing_windows(clim: pd.DataFrame) -> list[dict]:
    flags = (clim["ratio"].to_numpy() >= MOIST_RATIO) & (clim["tmean"].to_numpy() >= 5)
    out = []
    for run in _runs(flags):
        out.append({"start": run[0] + 1, "end": run[-1] + 1, "length": len(run),
                    "months": [m + 1 for m in run],
                    "label": f"{MONTH_NAMES[run[0]]}–{MONTH_NAMES[run[-1]]}"})
    return out


def sowing_opportunities(clim: pd.DataFrame, climate_type: str) -> list[int]:
    """Months (1-12) when sowing is plausible. Crop-level fit decides what actually goes in."""
    ops: set[int] = set()
    rain = clim["rain"].to_numpy()
    for w in growing_windows(clim):
        months = w["months"]
        # any month with at least 3 moist months left is a sowing option (staggered / relay planting)
        for i, m in enumerate(months):
            if len(months) - i >= 3:
                ops.add(m)
        # bimodal: a dip in rain inside the window marks a second (minor) season start
        for i in range(1, len(months) - 1):
            a, b, c = (rain[months[i - 1] - 1], rain[months[i] - 1], rain[months[i + 1] - 1])
            if b < a and b < c and c > 0.8 * a:
                ops.add(months[i + 1])
                ops.add(months[i])
    if climate_type == "temperate":
        tmean = clim["tmean"].to_numpy()
        frost = clim["frost_days"].to_numpy()
        # autumn sowing for overwintering crops, spring sowing after the last frost
        for m in range(12):
            if 8 <= m + 1 <= 10 and 10 <= tmean[m] <= 20:
                ops.add(m + 1)
            if 3 <= m + 1 <= 6 and frost[m] < 1 and frost[m - 1] >= 1:
                ops.add(m + 1)
                ops.add(m % 12 + 1)
        ops.update({4, 5, 6, 7})  # spring/summer double-crop options
    if not ops:
        ops.add(int(np.argmax(rain)) + 1)
    return sorted(ops)


def onset_search_doy(clim: pd.DataFrame, climate_type: str) -> int | None:
    if climate_type != "tropical":
        return None
    windows = growing_windows(clim)
    if not windows:
        return None
    longest = max(windows, key=lambda w: w["length"])
    month_before = (longest["start"] - 2) % 12 + 1
    return int(pd.Timestamp(2001, month_before, 15).dayofyear)


def bare_months_from_ndvi(sat: pd.DataFrame) -> dict | None:
    if sat is None or "ndvi" not in sat or sat["ndvi"].notna().sum() < 24:
        return None
    clim = sat["ndvi"].groupby(sat.index.month).mean().reindex(range(1, 13))
    lo, hi = clim.min(), clim.max()
    thr = min(0.33, lo + 0.3 * (hi - lo))
    bare = [int(m) for m, v in clim.items() if v <= thr]
    return {"threshold": round(float(thr), 3), "months": bare,
            "ndvi_clim": [round(float(v), 3) for v in clim.to_numpy()]}


def rotation_coverage(plantings: list[dict], crops: dict, cycle: int = 24) -> np.ndarray:
    """Average fraction of years each calendar month has a living crop (0-1)."""
    occ = np.zeros(cycle)
    for p in plantings:
        dur = p.get("duration_m") or crops[p["crop"]]["duration_m"]
        start = (p.get("year", 1) - 1) * 12 + p["sow_month"] - 1
        for k in range(dur):
            occ[(start + k) % cycle] = 1
    return occ.reshape(-1, 12).mean(axis=0)


def _level(value: float, cuts: tuple[float, float, float]) -> int:
    a, b, c = cuts
    return 0 if value < a else 1 if value < b else 2 if value < c else 3


def risk_calendar(climate: Climate, sat: pd.DataFrame, current: list[dict], crops: dict,
                  stress_prob: list[float] | None) -> list[dict]:
    """Rows of 12 cells: level 0 (none) .. 3 (high) with a short explanation each."""
    c = climate.clim
    rows = []

    def row(key, label, source, values, cuts, fmt, invert=False):
        cells = []
        for m in range(12):
            v = float(values[m]) if values[m] is not None and not pd.isna(values[m]) else None
            if v is None:
                cells.append({"level": None, "value": None, "text": "no data"})
                continue
            lvl = _level(-v if invert else v, cuts)
            cells.append({"level": lvl, "value": round(v, 3), "text": fmt(v)})
        rows.append({"key": key, "label": label, "source": source, "cells": cells})

    row("dry", "Too dry to grow (rain vs. ET)", "NASA POWER rain + FAO-56 ET₀", c["ratio"].to_numpy(),
        (-1.0, -0.75, -0.5), lambda v: f"rain covers {v * 100:.0f}% of crop water demand", invert=True)
    row("dryspell", "Chance of a 10-day dry spell", "NASA POWER daily rain", c["dry_spell_prob"].to_numpy(),
        (0.2, 0.4, 0.65), lambda v: f"{v * 100:.0f}% of years")
    row("heat", "Heat stress (days >35°C)", "NASA POWER Tmax", c["heat_days"].to_numpy(),
        (1, 4, 10), lambda v: f"{v:.1f} days/month")
    if c["frost_days"].sum() >= 1:
        row("frost", "Frost risk (nights ≤0°C)", "NASA POWER Tmin", c["frost_days"].to_numpy(),
            (0.5, 3, 10), lambda v: f"{v:.1f} frost nights")
    row("storm", "Heavy-rain / erosion days", "NASA POWER daily rain (top 5%)", c["heavy_days"].to_numpy(),
        (0.3, 0.8, 1.5), lambda v: f"{v:.1f} heavy-rain days")
    if sat is not None and "smap_rootzone" in sat and sat["smap_rootzone"].notna().sum() >= 24:
        sm = sat["smap_rootzone"].groupby(sat.index.month).mean().reindex(range(1, 13)).to_numpy()
        lo, hi = np.nanmin(sm), np.nanmax(sm)
        rel = (sm - lo) / (hi - lo + 1e-9)
        row("soilmoist", "Dry soil (SMAP root zone)", "NASA SMAP L4 (9 km)", rel, (-0.75, -0.5, -0.25),
            lambda v: f"{v * 100:.0f}% of the wettest month", invert=True)
    elif "gwetroot" in c:
        row("soilmoist", "Dry soil (model soil wetness)", "NASA POWER GWETROOT (MERRA-2)", c["gwetroot"].to_numpy(),
            (-0.6, -0.45, -0.35), lambda v: f"wetness {v:.2f}", invert=True)
    bare = bare_months_from_ndvi(sat)
    if bare:
        nd = np.array(bare["ndvi_clim"])
        row("bare", "Field looks bare (NDVI)", "MODIS NDVI (250 m)", nd,
            (-bare["threshold"] - 0.08, -bare["threshold"] - 0.04, -bare["threshold"]),
            lambda v: f"NDVI {v:.2f}", invert=True)
    if stress_prob is not None:
        row("stress", "Crop stress seen from space", "AI model on MODIS NDVI anomalies", np.array(stress_prob),
            (0.1, 0.2, 0.35), lambda v: f"stress in {v * 100:.0f}% of years")
    cov = rotation_coverage(current, crops)
    row("uncovered", "Your rotation leaves soil bare", "Your current rotation", 1 - cov, (0.01, 0.4, 0.75),
        lambda v: "bare" if v > 0.75 else ("bare some years" if v > 0.01 else "crop growing"))
    return rows
