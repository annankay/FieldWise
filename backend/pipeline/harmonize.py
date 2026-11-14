from __future__ import annotations

import numpy as np
import pandas as pd

from backend.pipeline.features import Climate


def unified_monthly(climate: Climate, sat: pd.DataFrame) -> pd.DataFrame:
    m = climate.monthly[["rain", "et0", "tmax", "tmin", "heat_days", "frost_days", "gwetroot"]].copy()
    idx = pd.PeriodIndex([pd.Period(year=y, month=mo, freq="M") for y, mo in m.index], freq="M")
    m.index = idx
    if sat is not None and not sat.empty:
        m = m.join(sat, how="left")
    return m
def _pearson(a: pd.Series, b: pd.Series) -> float | None:
    ok = a.notna() & b.notna()
    if ok.sum() < 12:
        return None
    return float(np.corrcoef(a[ok], b[ok])[0, 1])


def agreement(unified: pd.DataFrame) -> dict:
    """How well independent sources agree. Disagreement = lower confidence."""
    out = {}
    if "gpm_rain" in unified and unified["gpm_rain"].notna().sum() >= 12:
        ok = unified["gpm_rain"].notna()
        r = _pearson(unified["rain"], unified["gpm_rain"])
        bias = float((unified.loc[ok, "gpm_rain"].sum() - unified.loc[ok, "rain"].sum()) /
                     max(unified.loc[ok, "rain"].sum(), 1) * 100)
        out["rain"] = {"pair": "NASA POWER (model+gauges) vs GPM IMERG (satellite)", "r": round(r, 3) if r else None,
                       "bias_pct": round(bias, 1),
                       "verdict": "good" if (r or 0) > 0.85 and abs(bias) < 15 else "fair" if (r or 0) > 0.7 else "poor"}
    if "smap_rootzone" in unified and unified["smap_rootzone"].notna().sum() >= 12:
        r = _pearson(unified["gwetroot"], unified["smap_rootzone"])
        out["soil_moisture"] = {"pair": "POWER GWETROOT (model) vs SMAP L4 (satellite-assimilated)",
                                "r": round(r, 3) if r else None,
                                "verdict": "good" if (r or 0) > 0.8 else "fair" if (r or 0) > 0.6 else "poor"}
    if "et_modis" in unified and unified["et_modis"].notna().sum() >= 12:
        r = _pearson(unified["et0"], unified["et_modis"])
        out["et"] = {"pair": "Reference ET₀ (weather) vs MODIS actual ET", "r": round(r, 3) if r else None,
                     "note": "Actual ET is lower than ET₀ when soil is dry; a weak match is expected in dry seasons."}
    return out

def chart_series(unified: pd.DataFrame) -> dict:
    """Monthly climatologies and long time series, ready for the charts."""
    by_m = unified.groupby(unified.index.month)
    clim = {}
    for col in unified.columns:
        s = by_m[col].mean().reindex(range(1, 13))
        if s.notna().sum() >= 6:
            clim[col] = [None if pd.isna(v) else round(float(v), 3) for v in s.to_numpy()]
    long = {}
    for col in ("grace_lwe", "ndvi", "smap_rootzone", "gpm_rain", "rain"):
        if col in unified and unified[col].notna().sum() >= 24:
            s = unified[col].dropna()
            long[col] = {"t": [str(p) for p in s.index], "v": [round(float(v), 3) for v in s.to_numpy()]}
    return {"climatology": clim, "long": long}
  
