from __future__ import annotations

import math

import numpy as np
import pandas as pd
from scipy import stats

from backend.pipeline.features import DRY_DAY_MM, Climate


def mann_kendall(values, times=None) -> dict:
    """Return Sen's slope (per unit time), Kendall tau and two-sided p-value."""
    y = np.asarray(values, dtype=float)
    t = np.arange(len(y), dtype=float) if times is None else np.asarray(times, dtype=float)
    mask = ~np.isnan(y)
    y, t = y[mask], t[mask]
    n = len(y)
    if n < 8:
        return {"slope": float("nan"), "tau": float("nan"), "p": float("nan"), "n": n}
    s = 0.0
    slopes = []
    for i in range(n - 1):
        dy = y[i + 1:] - y[i]
        dt = t[i + 1:] - t[i]
        s += np.sign(dy).sum()
        ok = dt != 0
        slopes.append(dy[ok] / dt[ok])
    slopes = np.concatenate(slopes)
    _, counts = np.unique(y, return_counts=True)
    var_s = (n * (n - 1) * (2 * n + 5) - np.sum(counts * (counts - 1) * (2 * counts + 5))) / 18.0
    z = 0.0 if s == 0 else (s - np.sign(s)) / math.sqrt(var_s)
    p = 2 * (1 - stats.norm.cdf(abs(z)))
    tau = s / (0.5 * n * (n - 1))
    return {"slope": float(np.median(slopes)), "tau": float(tau), "p": float(p), "n": int(n)}

def detect_onset(daily: pd.DataFrame, search_start_doy: int) -> pd.Series:
    """Rainy-season onset per year (day of year).

    Agronomic definition (after Sivakumar 1988): first day after `search_start_doy` when 3-day rain
    totals >= 20 mm and no dry spell of 10+ days follows within the next 30 days. NaN if never met.
    """
    out = {}
    for year, d in daily.groupby(daily.index.year):
        rain = d["rain"].to_numpy()
        doy = d.index.dayofyear.to_numpy()
        three = np.convolve(rain, np.ones(3), mode="full")[2:len(rain) + 2]
        onset = np.nan
        for i in np.where((doy >= search_start_doy) & (three >= 20))[0]:
            window = rain[i + 3:i + 33]
            if len(window) < 30:
                break
            run = best = 0
            for r in window:
                run = run + 1 if r < DRY_DAY_MM else 0
                best = max(best, run)
            if best < 10:
                onset = float(doy[i])
                break
        out[year] = onset
    return pd.Series(out, name="onset_doy")


def annual_series(climate: Climate, sat: pd.DataFrame, onset_search_doy: int | None) -> pd.DataFrame:
    m = climate.monthly
    yearly = m.groupby(level="year").agg(rain=("rain", "sum"), tmax=("tmax", "mean"), tmin=("tmin", "mean"),
                                         heat_days=("heat_days", "sum"), frost_days=("frost_days", "sum"),
                                         heavy_days=("heavy_days", "sum"), et0=("et0", "sum"))
    if onset_search_doy is not None:
        yearly["onset_doy"] = detect_onset(climate.daily, onset_search_doy)
    if sat is not None and not sat.empty:
        s = sat.copy()
        s["year"] = s.index.year
        g = s.groupby("year")
        for col in ("ndvi", "smap_rootzone", "grace_lwe"):
            if col in s and s[col].notna().sum() > 24:
                counts = g[col].count()
                vals = g[col].mean().where(counts >= 9)  # need most of the year
                yearly[col] = vals
    return yearly


TREND_SPECS = [
    # column, label, unit, per (decade/year), good direction (+1 good if increasing, -1 bad if increasing, 0 neutral)
    ("tmax", "Daytime temperature", "°C", "decade", -1),
    ("heat_days", "Very hot days (>35°C)", "days", "decade", -1),
    ("frost_days", "Frost days", "days", "decade", 0),
    ("rain", "Annual rainfall", "mm", "decade", +1),
    ("heavy_days", "Heavy-rain days", "days", "decade", -1),
    ("onset_doy", "Rainy-season start", "days", "decade", -1),
    ("ndvi", "Vegetation greenness (NDVI)", "", "decade", +1),
    ("smap_rootzone", "Root-zone soil moisture (SMAP)", "m³/m³", "decade", +1),
    ("grace_lwe", "Total water storage (GRACE)", "cm", "year", +1),
]


def trend_cards(yearly: pd.DataFrame, source_of: dict) -> list[dict]:
    cards = []
    for col, label, unit, per, good in TREND_SPECS:
        if col not in yearly or yearly[col].notna().sum() < 8:
            continue
        series = yearly[col]
        if col == "frost_days" and series.mean() < 0.5:
            continue  # no frost climate
        res = mann_kendall(series.to_numpy(), series.index.to_numpy())
        scale = 10 if per == "decade" else 1
        slope = res["slope"] * scale
        sig = res["p"] < 0.05
        direction = "up" if slope > 0 else "down" if slope < 0 else "flat"
        unit_txt = f" {unit}" if unit else ""
        if not sig:
            text = f"{label}: no clear trend"
        elif col == "onset_doy":
            text = f"The rains start about {abs(slope):.0f} days {'later' if slope > 0 else 'earlier'} each decade"
        else:
            text = f"{label} {'rising' if slope > 0 else 'falling'} by {abs(slope):.2g}{unit_txt} per {per}"
        concern = (good == -1 and slope > 0) or (good == +1 and slope < 0)
        first, last = series.dropna().index.min(), series.dropna().index.max()
        cards.append({
            "key": col, "label": label, "unit": unit, "per": per, "slope": round(slope, 3),
            "p_value": round(res["p"], 4), "significant": bool(sig), "direction": direction,
            "concern": bool(concern and sig), "text": text, "period": f"{first}-{last}",
            "mean": round(float(series.mean()), 2), "source": source_of.get(col, "NASA POWER"),
            "series": [{"year": int(y), "value": None if pd.isna(v) else round(float(v), 3)}
                       for y, v in series.items()],
        })
    return cards
