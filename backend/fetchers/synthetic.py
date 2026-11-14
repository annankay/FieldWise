"""Offline DEMO data generator.

Creates statistically realistic (but NOT real) daily weather and monthly satellite layers for the
demo sites, so the whole app can run without internet or accounts. Everything generated here is
labelled "synthetic demo" in the UI. Replace it with real NASA data via scripts/build_cache.py.

The generator deliberately builds in the kinds of signals the real data shows in these regions
(warming trend, later rainy-season onset, heavier downpours, groundwater decline) so the
analysis pipeline has something meaningful to find.
"""
from __future__ import annotations

import zlib

import numpy as np
import pandas as pd

from backend.pipeline.et0 import penman_monteith

MID_MONTH_DOY = np.array([15, 46, 74, 105, 135, 166, 196, 227, 258, 288, 319, 349], dtype=float)
DAYS_IN_MONTH = np.array([31, 28.25, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31])


def _seasonal(monthly: list[float], doy: np.ndarray) -> np.ndarray:
    """Smooth periodic interpolation of 12 monthly values to day of year."""
    x = np.concatenate([MID_MONTH_DOY - 365, MID_MONTH_DOY, MID_MONTH_DOY + 365])
    y = np.tile(np.asarray(monthly, float), 3)
    return np.interp(doy, x, y)


def _ar1(n: int, phi: float, sd: float, rng) -> np.ndarray:
    eps = rng.normal(0, sd * np.sqrt(1 - phi ** 2), n)
    out = np.empty(n)
    out[0] = rng.normal(0, sd)
    for i in range(1, n):
        out[i] = phi * out[i - 1] + eps[i]
    return out


def generate_daily(site: dict, start_year: int, end_year: int, rng) -> pd.DataFrame:
    c = site["climatology"]
    dates = pd.date_range(f"{start_year}-01-01", f"{end_year}-12-31", freq="D")
    n = len(dates)
    doy = dates.dayofyear.to_numpy().astype(float)
    years = dates.year.to_numpy()
    dec = (years - (start_year + end_year) / 2) / 10.0     # decades from mid-record
    dec0 = (years - start_year) / 10.0                      # decades from start

    # ---------- rainfall (Markov-chain occurrence + gamma amounts) ----------
    daily_mean = np.asarray(c["rain"], float) / DAYS_IN_MONTH
    year_ids = years - start_year
    n_years = end_year - start_year + 1
    onset_shift = rng.normal(0, 10, n_years) + c.get("onset_delay_days_per_decade", 0) * (
        (np.arange(n_years) - n_years / 2) / 10)
    # shift applies to the early rainy season only (Feb-Jun) so onset moves but peak stays
    weight = np.clip(np.where(doy < 32, 0, np.where(doy < 60, (doy - 32) / 28,
                     np.where(doy < 150, 1, np.where(doy < 180, (180 - doy) / 30, 0)))), 0, 1)
    eff_doy = doy - onset_shift[year_ids] * weight
    expected = np.clip(_seasonal(daily_mean, eff_doy), 0.02, None)
    annual_mult = np.exp(rng.normal(0, 0.15, n_years))[year_ids] * (1 + c.get("rain_trend_per_decade", 0) * dec)
    expected *= annual_mult

    p = np.clip(0.04 + 0.6 * expected / (expected + 4.0), 0.02, 0.8)
    p11 = np.minimum(0.92, p + 0.3 * (1 - p))
    p01 = np.clip(p * (1 - p11) / (1 - p), 0.005, 0.95)
    wet = np.zeros(n, dtype=bool)
    u = rng.random(n)
    for i in range(1, n):
        wet[i] = u[i] < (p11[i] if wet[i - 1] else p01[i])
    shape = np.clip(0.8 * (1 - c.get("extreme_trend_per_decade", 0) * dec0 * 0.6), 0.35, 1.0)
    scale = expected / p / shape
    rain = np.where(wet, rng.gamma(shape, scale), 0.0)

    # ---------- temperature (seasonal + warming + AR(1) anomalies) ----------
    warm = c.get("warming_per_decade", 0.2) * dec
    sd = c.get("temp_sd", 1.5)
    anom = _ar1(n, 0.75, sd, rng)
    tmax = _seasonal(c["tmax"], doy) + warm + anom - np.where(wet, 1.5, 0)
    tmin = _seasonal(c["tmin"], doy) + warm + 0.7 * anom + _ar1(n, 0.5, sd * 0.4, rng) + np.where(wet, 0.4, 0)
    tmin = np.minimum(tmin, tmax - 2)
    rh = np.clip(_seasonal(c["rh"], doy) + rng.normal(0, 5, n) + np.where(wet, 6, -1), 10, 100)
    wind = np.clip(_seasonal(c["wind"], doy) * np.exp(rng.normal(0, 0.25, n)), 0.3, 12)
    rad = np.clip(_seasonal(c["rad"], doy) * np.where(wet, 0.78, 1.04) * np.exp(rng.normal(0, 0.08, n)), 2, 32)

    df = pd.DataFrame({"tmax": tmax, "tmin": tmin, "tmean": (tmax + tmin) / 2, "rain": rain,
                       "rh": rh, "wind": wind, "rad": rad}, index=dates)
    df.index.name = "date"

    # ---------- simple two-layer bucket model -> POWER-like soil wetness ----------
    et0 = penman_monteith(df, site["lat"], c.get("elev", 200)).to_numpy()
    soil = c.get("soil", {})
    cap = 110 + 1.6 * soil.get("clay", 20) + 0.8 * soil.get("silt", 20)   # mm plant-available
    cap_top = 18.0
    w, wt = cap * 0.5, cap_top * 0.5
    root, top = np.empty(n), np.empty(n)
    aet = np.empty(n)
    for i in range(n):
        wt = min(cap_top, wt + rain[i]) - min(wt, et0[i] * 0.6 * wt / cap_top)
        stress = min(1.0, w / (0.55 * cap))
        a = et0[i] * 0.8 * stress
        w = max(0.0, min(cap, w + rain[i] * 0.85 - a))
        root[i], top[i], aet[i] = w / cap, wt / cap_top, a
    df["gwettop"] = np.clip(0.15 + 0.8 * top + rng.normal(0, 0.03, n), 0.05, 1)
    df["gwetroot"] = np.clip(0.25 + 0.7 * root + rng.normal(0, 0.01, n), 0.05, 1)
    df["_aet"] = aet
    return df


def _presence_curve(site: dict, crops: dict, months: pd.PeriodIndex) -> np.ndarray:
    """Green-canopy fraction 0-1 per month from the site's CURRENT rotation (for synthetic NDVI)."""
    cycle = np.zeros(24)
    for p in site["current_rotation"]:
        crop = crops[p["crop"]]
        dur = p.get("duration_m", crop["duration_m"])
        start = (p["year"] - 1) * 12 + p["sow_month"] - 1
        for k in range(dur):
            frac = (k + 0.5) / dur
            canopy = np.sin(np.pi * min(1.0, frac * 1.15)) if frac < 0.9 else 0.3
            cycle[(start + k) % 24] = max(cycle[(start + k) % 24], canopy)
    idx = ((months.year - months.year.min()) % 2) * 12 + months.month - 1
    return cycle[idx]


def generate_monthly_satellite(site: dict, daily: pd.DataFrame, crops: dict, rng) -> pd.DataFrame:
    c = site["climatology"]
    monthly = daily.resample("MS").agg({"rain": "sum", "gwettop": "mean", "gwetroot": "mean",
                                         "_aet": "sum", "tmax": "mean"})
    monthly.index = monthly.index.to_period("M")
    months = monthly.index
    out = pd.DataFrame(index=months)
    n = len(months)

    # GPM IMERG: satellite estimate, small positive bias and its own noise vs POWER
    out["gpm_rain"] = np.clip(monthly["rain"] * 1.06 * np.exp(rng.normal(0, 0.12, n)), 0, None)
    out.loc[out.index < pd.Period("2001-01", "M"), "gpm_rain"] = np.nan

    # SMAP L4 (from April 2015)
    out["smap_surface"] = np.clip(0.04 + 0.36 * monthly["gwettop"] + rng.normal(0, 0.015, n), 0.02, 0.6)
    out["smap_rootzone"] = np.clip(0.06 + 0.30 * monthly["gwetroot"] + rng.normal(0, 0.008, n), 0.03, 0.55)
    out.loc[out.index < pd.Period("2015-04", "M"), ["smap_surface", "smap_rootzone"]] = np.nan

    # MODIS NDVI: crop canopy x moisture + background vegetation, with heat-stress dips
    presence = _presence_curve(site, crops, months)
    moist = np.clip((monthly["gwetroot"].to_numpy() - 0.3) / 0.6, 0, 1)
    moist_lag = np.concatenate([[moist[0]], moist[:-1]])
    heat = np.clip((monthly["tmax"].to_numpy() - 34) / 6, 0, 1)
    bare = 0.2 if site["climate"] == "temperate" else 0.24
    ndvi = bare + 0.16 * moist_lag + 0.38 * presence * (0.45 + 0.55 * moist_lag) * (1 - 0.35 * heat)
    if site["climate"] == "temperate":
        cold = np.clip((5 - (monthly["tmax"].to_numpy() - 8)) / 10, 0, 0.6)
        ndvi = ndvi * (1 - 0.35 * cold)
    # month-to-month weather anomalies leave a visible fingerprint on greenness
    rain_z = ((monthly["rain"] - monthly.groupby(monthly.index.month)["rain"].transform("mean")) /
              (monthly.groupby(monthly.index.month)["rain"].transform("std") + 1e-6)).to_numpy()
    rain_z_lag = np.concatenate([[0], rain_z[:-1]])
    ndvi = ndvi + 0.03 * np.tanh(rain_z_lag) * (0.3 + presence)
    out["ndvi"] = np.clip(ndvi + rng.normal(0, 0.018, n), 0.05, 0.9)
    out.loc[out.index < pd.Period("2000-03", "M"), "ndvi"] = np.nan

    # MODIS MOD16 ET (from 2001)
    out["et_modis"] = np.clip(monthly["_aet"] * np.exp(rng.normal(0, 0.1, n)), 0, None)
    out.loc[out.index < pd.Period("2001-01", "M"), "et_modis"] = np.nan

    # GRACE/GRACE-FO total water storage anomaly (cm): lagged seasonal cycle + long-term trend + mission gap
    rain_anom = monthly["rain"] - monthly.groupby(monthly.index.month)["rain"].transform("mean")
    storage = rain_anom.rolling(4, min_periods=1).sum().to_numpy() / 25.0
    clim_rain = np.asarray(c["rain"], float)
    seasonal = c.get("grace_amp_cm", 5) * np.interp(
        (months.month.to_numpy() - 2) % 12, np.arange(12), (clim_rain - clim_rain.mean()) / (clim_rain.max() - clim_rain.mean() + 1e-6))
    yrs = months.year.to_numpy() + (months.month.to_numpy() - 0.5) / 12
    trend = c.get("grace_trend_cm_yr", -0.1) * (yrs - 2010)
    out["grace_lwe"] = seasonal + trend + storage + rng.normal(0, 0.8, n)
    out.loc[(out.index < pd.Period("2002-04", "M")) |
            ((out.index >= pd.Period("2017-07", "M")) & (out.index <= pd.Period("2018-05", "M"))), "grace_lwe"] = np.nan
    return out


def generate_dem(site: dict, cells: int, rng) -> dict:
    """Synthetic SRTM-like 30 m elevation grid with a gentle slope, a valley and some hills."""
    c = site["climatology"]
    cell_m = 30
    x = np.arange(cells) * cell_m
    xx, yy = np.meshgrid(x, x)
    slope = c.get("slope_pct", 2.0) / 100
    elev = c.get("elev", 200) + slope * (xx * 0.8 + yy * 0.6)
    for _ in range(4):
        cx, cy = rng.uniform(0, x[-1], 2)
        h = rng.uniform(-1, 1) * slope * 300
        r = rng.uniform(100, 260)
        elev += h * np.exp(-((xx - cx) ** 2 + (yy - cy) ** 2) / (2 * r ** 2))
    # a small drainage line
    valley = np.exp(-((xx - yy * 0.7 - x[-1] * 0.3) ** 2) / (2 * 60 ** 2))
    elev -= valley * slope * 120
    elev += rng.normal(0, 0.15, elev.shape)
    return {"cells": cells, "cell_m": cell_m, "elev": elev.round(2).tolist(), "source": "synthetic demo DEM"}


def build_demo_site(site: dict, crops: dict, start_year: int, end_year: int, cells: int, seed: int = 7):
    rng = np.random.default_rng(seed + zlib.crc32(site["id"].encode()) % 1000)
    daily = generate_daily(site, start_year, end_year, rng)
    sat = generate_monthly_satellite(site, daily, crops, rng)
    daily = daily.drop(columns=["_aet"])
    soil = dict(site["climatology"].get("soil", {}))
    soil.update({"source": "synthetic demo (typical values for the area)", "depth": "0-30 cm"})
    dem = generate_dem(site, cells, rng)
    return daily, sat, soil, dem

