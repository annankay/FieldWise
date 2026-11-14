from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from backend.pipeline.et0 import compute_et0

MONTH_NAMES = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]
DRY_DAY_MM = 1.0
DRY_SPELL_DAYS = 10


def effective_rain(p) -> np.ndarray:
    """FAO/AGLW monthly effective rainfall: the share of rain that crops can actually use."""
    p = np.asarray(p, dtype=float)
    return np.where(p > 75, 0.8 * p - 25, np.maximum(0.6 * p - 10, 0))


def _longest_dry_run(rain: np.ndarray) -> int:
    best = run = 0
    for r in rain:
        run = run + 1 if r < DRY_DAY_MM else 0
        best = max(best, run)
    return best


@dataclass
class Climate:
    daily: pd.DataFrame
    monthly: pd.DataFrame
    clim: pd.DataFrame
    lat: float
    elev: float
    heavy_thr: float
    scenario: dict = field(default_factory=dict)
    _counts: dict = field(default_factory=dict, repr=False)

    def _count(self, col: str, op: str, thr: float) -> np.ndarray:
        key = (col, op, round(thr, 2))
        if key not in self._counts:
            s = self.daily[col]
            flag = (s > thr) if op == "gt" else (s <= thr)
            per_ym = flag.groupby([self.daily.index.year, self.daily.index.month]).sum()
            self._counts[key] = per_ym.groupby(level=1).mean().reindex(range(1, 13), fill_value=0).to_numpy()
        return self._counts[key]

    def days_above(self, thr: float) -> np.ndarray:
        """Mean number of days per calendar month with Tmax above thr."""
        return self._count("tmax", "gt", thr)

    def days_below(self, thr: float) -> np.ndarray:
        """Mean number of days per calendar month with Tmin at or below thr."""
        return self._count("tmin", "le", thr)

    @property
    def years(self) -> list[int]:
        return sorted(self.daily.index.year.unique().tolist())

  
def apply_scenario(daily: pd.DataFrame, rain_pct: float = 0.0, temp_c: float = 0.0,
                   storm_pct: float = 0.0) -> pd.DataFrame:
    """What-if: scale rainfall, shift temperature, intensify the heaviest 5% of rain days."""
    d = daily.copy()
    if rain_pct:
        d["rain"] = d["rain"] * (1 + rain_pct / 100.0)
    if storm_pct:
        wet = d["rain"] > DRY_DAY_MM
        thr = d.loc[wet, "rain"].quantile(0.95)
        heavy = d["rain"] > thr
        extra = d.loc[heavy, "rain"] * storm_pct / 100.0
        d.loc[heavy, "rain"] += extra
        # keep the annual total roughly constant: take it back from light rain days
        light = wet & ~heavy
        if light.any():
            d.loc[light, "rain"] = np.maximum(0, d.loc[light, "rain"] - extra.sum() / light.sum())
    if temp_c:
        for col in ("tmax", "tmin", "tmean"):
            d[col] = d[col] + temp_c
    return d


def build_climate(daily: pd.DataFrame, lat: float, elev: float, heavy_thr: float | None = None,
                  scenario: dict | None = None) -> Climate:
    d = daily.copy()
    if "tmean" not in d:
        d["tmean"] = (d["tmax"] + d["tmin"]) / 2
    d["et0"] = compute_et0(d, lat, elev)
    wet = d["rain"] > DRY_DAY_MM
    if heavy_thr is None:
        heavy_thr = float(d.loc[wet, "rain"].quantile(0.95)) if wet.any() else 30.0

    grp = d.groupby([d.index.year, d.index.month])
    monthly = pd.DataFrame({
        "rain": grp["rain"].sum(),
        "et0": grp["et0"].sum(),
        "tmax": grp["tmax"].mean(),
        "tmin": grp["tmin"].mean(),
        "tmean": grp["tmean"].mean(),
        "frost_days": grp["tmin"].apply(lambda s: int((s <= 0).sum())),
        "heat_days": grp["tmax"].apply(lambda s: int((s > 35).sum())),
        "heavy_days": grp["rain"].apply(lambda s: int((s > heavy_thr).sum())),
        "dry_spell": grp["rain"].apply(lambda s: _longest_dry_run(s.to_numpy())),
        "gdd10": grp["tmean"].apply(lambda s: float(np.clip(s - 10, 0, None).sum())),
        "gwetroot": grp["gwetroot"].mean() if "gwetroot" in d else np.nan,
    })
    monthly.index.names = ["year", "month"]
    monthly["ratio"] = monthly["rain"] / monthly["et0"].clip(lower=1)

    by_m = monthly.groupby(level="month")
    clim = by_m.mean()
    clim["rain_sd"] = by_m["rain"].std()
    clim["rain_cv"] = clim["rain_sd"] / clim["rain"].clip(lower=1)
    clim["dry_spell_prob"] = by_m["dry_spell"].apply(lambda s: float((s >= DRY_SPELL_DAYS).mean()))
    clim["ratio"] = clim["rain"] / clim["et0"].clip(lower=1)
    clim["peff"] = effective_rain(clim["rain"])
    clim["tmin_p05"] = d.groupby(d.index.month)["tmin"].quantile(0.05)
    clim["tmax_p95"] = d.groupby(d.index.month)["tmax"].quantile(0.95)
    clim = clim.reindex(range(1, 13))
    return Climate(daily=d, monthly=monthly, clim=clim, lat=lat, elev=elev, heavy_thr=heavy_thr,
                   scenario=scenario or {})

def climatology_for_years(climate: Climate, years: list[int]) -> pd.DataFrame:
    """12-month climatology using only a subset of years (used for 'year type' robustness)."""
    m = climate.monthly.loc[climate.monthly.index.get_level_values("year").isin(years)]
    clim = m.groupby(level="month").mean().reindex(range(1, 13))
    clim["ratio"] = clim["rain"] / clim["et0"].clip(lower=1)
    clim["peff"] = effective_rain(clim["rain"])
    return clim
