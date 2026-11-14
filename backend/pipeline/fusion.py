from __future__ import annotations

import io

import numpy as np
import pandas as pd


def parse_gauge_csv(text: str) -> pd.Series:
    """CSV with columns date,rain_mm (daily or monthly). Returns monthly totals."""
    df = pd.read_csv(io.StringIO(text))
    cols = {c.lower().strip(): c for c in df.columns}
    date_col = cols.get("date") or list(df.columns)[0]
    rain_col = cols.get("rain_mm") or cols.get("rain") or list(df.columns)[1]
    s = pd.Series(pd.to_numeric(df[rain_col], errors="coerce").to_numpy(),
                  index=pd.to_datetime(df[date_col], errors="coerce"))
    s = s[s.index.notna()].dropna()
    if s.empty:
        raise ValueError("No valid rows. Expected columns: date, rain_mm")
    # daily data -> monthly totals; monthly data stays as is
    monthly = s.resample("MS").sum(min_count=1) if s.index.to_series().diff().dt.days.median() < 20 else s
    monthly.index = monthly.index.to_period("M")
    return monthly.groupby(level=0).sum()

def fuse_rain(nasa_monthly: pd.Series, gauge_monthly: pd.Series) -> dict:
    both = pd.concat({"nasa": nasa_monthly, "gauge": gauge_monthly}, axis=1).dropna()
    if len(both) < 12:
        raise ValueError(f"Need at least 12 overlapping months, found {len(both)}")
    factors = {}
    for m in range(1, 13):
        sub = both[both.index.month == m]
        if len(sub) and sub["nasa"].sum() > 5:
            factors[m] = float(np.clip(sub["gauge"].sum() / sub["nasa"].sum(), 0.4, 2.5))
        else:
            factors[m] = 1.0
    corrected = nasa_monthly * np.array([factors[p.month] for p in nasa_monthly.index])
    ov = both.index
    rmse_before = float(np.sqrt(((both["nasa"] - both["gauge"]) ** 2).mean()))
    rmse_after = float(np.sqrt(((corrected.loc[ov] - both["gauge"]) ** 2).mean()))
    return {
        "overlap_months": int(len(both)),
        "bias_before_pct": round(float((both["nasa"].sum() - both["gauge"].sum()) / both["gauge"].sum() * 100), 1),
        "rmse_before_mm": round(rmse_before, 1), "rmse_after_mm": round(rmse_after, 1),
        "corr": round(float(np.corrcoef(both["nasa"], both["gauge"])[0, 1]), 3),
        "monthly_factors": {str(k): round(v, 3) for k, v in factors.items()},
        "corrected_annual_mm": round(float(corrected.groupby(corrected.index.year).sum().mean()), 0),
        "nasa_annual_mm": round(float(nasa_monthly.groupby(nasa_monthly.index.year).sum().mean()), 0),
    }

