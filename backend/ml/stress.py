"""Vegetation-stress model: which weather patterns make crops look stressed from space?

Target  : monthly MODIS NDVI anomaly (z-score vs. that calendar month's normal).
Features: rainfall anomalies (this month and 1-2 months before ), heat days, temperature and ET₀
          anomalies, soil-moisture anomaly (SMAP or POWER), and seasonality.
We compare a transparent linear model with two three ensembles ona time-ordered split (train on
early years , test on later years ) and keep the best. Permutation importance explains drivers.
"""
from __future__ import annotations

import numpy as np
import pandas as pd
from scipy import stats
from sklearn.ensemble import GradientBoostingRegressor, HistGradientBoostingRegressor, RandomForestRegressor
from sklearn.inspection import permutation_importance
from sklearn.linear_model import RidgeCV
from sklearn.metrics import mean_absolute_error, r2_score

from backend.pipeline.features import Climate

DRIVER_LABELS = {
    "rain_z": "Rain this month", "rain_z_lag1": "Rain last month", "rain_z_lag2": "Rain 2 months ago",
    "heat_days": "Very hot days", "tmax_z": "Daytime temperature", "et0_z": "Evaporative demand (ET₀)",
    "sm_z": "Soil moisture", "msin": "Season (timing)", "mcos": "Season (timing)",
}
STRESS_Z = -1.0
# Physics guardrails: more rain / soil moisture can never make crops look MORE stressed,
# more heat / evaporative demand can never make them look LESS stressed.
MONOTONIC = {"rain_z": 1, "rain_z_lag1": 1, "rain_z_lag2": 1, "sm_z": 1,
             "tmax_z": -1, "et0_z": -1, "heat_days": -1}


def _z_by_month(s: pd.Series, ref: pd.DataFrame | None = None) -> tuple[pd.Series, pd.DataFrame]:
    month = s.index.month
    if ref is None:
        ref = s.groupby(month).agg(["mean", "std"])
    mu = ref["mean"].reindex(month).to_numpy()
    sd = ref["std"].reindex(month).to_numpy()
    return pd.Series((s.to_numpy() - mu) / np.where(sd > 1e-9, sd, 1), index=s.index), ref


class StressModel:
    def __init__(self):
        self.model = None
        self.refs: dict = {}
        self.features: list[str] = []
        self.resid_sd = 1.0
        self.report: dict = {}

    def _frame(self, climate: Climate, sat: pd.DataFrame, fit_refs: bool) -> pd.DataFrame:
        m = climate.monthly.copy()
        m.index = pd.PeriodIndex([pd.Period(year=y, month=mo, freq="M") for y, mo in m.index], freq="M")
        df = pd.DataFrame(index=m.index)
        for col in ("rain", "tmax", "et0"):
            z, ref = _z_by_month(m[col], None if fit_refs else self.refs[col])
            if fit_refs:
                self.refs[col] = ref
            df[f"{col}_z"] = z
        df["rain_z_lag1"] = df["rain_z"].shift(1)
        df["rain_z_lag2"] = df["rain_z"].shift(2)
        df["heat_days"] = m["heat_days"]
        if fit_refs:
            has_smap = sat is not None and "smap_rootzone" in sat and sat["smap_rootzone"].notna().sum() > 36
            self.sm_source = "smap" if has_smap else "gwetroot" if "gwetroot" in m else None
        # soil-moisture anomaly: POWER model wetness for the full record, replaced by SMAP satellite
        # anomalies where SMAP exists (2015+). Anomalies (not raw values) make the two comparable.
        sm_z = None
        if "gwetroot" in m and m["gwetroot"].notna().sum() > 36:
            sm_z, ref = _z_by_month(m["gwetroot"], None if fit_refs else self.refs.get("gw"))
            if fit_refs:
                self.refs["gw"] = ref
        if getattr(self, "sm_source", None) == "smap":
            smap = sat["smap_rootzone"].reindex(df.index).dropna()
            z_s, ref = _z_by_month(smap, None if fit_refs else self.refs.get("smap"))
            if fit_refs:
                self.refs["smap"] = ref
            z_s = z_s.reindex(df.index)
            sm_z = z_s if sm_z is None else z_s.fillna(sm_z)
        if sm_z is not None:
            df["sm_z"] = sm_z
        df["msin"] = np.sin(2 * np.pi * df.index.month / 12)
        df["mcos"] = np.cos(2 * np.pi * df.index.month / 12)
        return df

    def fit(self, climate: Climate, sat: pd.DataFrame) -> dict | None:
        if sat is None or "ndvi" not in sat or sat["ndvi"].notna().sum() < 60:
            return None
        X = self._frame(climate, sat, fit_refs=True)
        y, self.refs["ndvi"] = _z_by_month(sat["ndvi"].dropna())
        data = X.join(y.rename("target"), how="inner").dropna()
        if "sm_z" in data and data["sm_z"].isna().all():
            data = data.drop(columns="sm_z")
        self.features = [c for c in data.columns if c != "target"]
        split = int(len(data) * 0.7)
        tr, te = data.iloc[:split], data.iloc[split:]
        candidates = {
            "Linear (ridge) baseline": RidgeCV(alphas=np.logspace(-2, 2, 9)),
            "Random forest": RandomForestRegressor(n_estimators=250, min_samples_leaf=5, random_state=0, n_jobs=-1),
            "Gradient boosting": GradientBoostingRegressor(n_estimators=250, max_depth=3, learning_rate=0.05,
                                                           subsample=0.8, random_state=0),
        }
        candidates["Physics-guided boosting (monotonic)"] = HistGradientBoostingRegressor(
            max_iter=200, max_depth=3, learning_rate=0.05, min_samples_leaf=10, random_state=0,
            monotonic_cst=[MONOTONIC.get(f, 0) for f in self.features])
        results = []
        for name, model in candidates.items():
            model.fit(tr[self.features], tr["target"])
            pred = model.predict(te[self.features])
            results.append({"model": name, "r2": round(float(r2_score(te["target"], pred)), 3),
                            "mae": round(float(mean_absolute_error(te["target"], pred)), 3), "_m": model})
        best = max(results, key=lambda r: r["r2"])
        guided = next(r for r in results if r["model"].startswith("Physics"))
        # What-if scenarios push the weather outside the past range, so we use the physics-guided model
        # unless it is clearly worse (> 0.1 R²) than the best unconstrained one.
        if guided["r2"] >= best["r2"] - 0.1:
            best = guided
        self.model = best["_m"]
        resid = te["target"] - self.model.predict(te[self.features])
        self.resid_sd = float(max(resid.std(), 0.3))
        pi = permutation_importance(self.model, te[self.features], te["target"], n_repeats=10, random_state=0)
        drivers = {}
        for f, v in zip(self.features, pi.importances_mean):
            label = DRIVER_LABELS.get(f, f)
            drivers[label] = drivers.get(label, 0) + max(0.0, float(v))
        tot = sum(drivers.values()) or 1
        drivers = sorted(({"driver": k, "importance": round(v / tot, 3)} for k, v in drivers.items()),
                         key=lambda d: -d["importance"])
        # direction of effect for the top weather drivers (sign of correlation with NDVI anomaly)
        signs = {}
        for f in self.features:
            if f in ("msin", "mcos"):
                continue
            with np.errstate(invalid="ignore", divide="ignore"):
                r = np.nan_to_num(np.corrcoef(data[f], data["target"])[0, 1])
            signs[DRIVER_LABELS.get(f, f)] = "more → greener" if r > 0.05 else "more → more stress" if r < -0.05 else "weak"
        for d in drivers:
            d["effect"] = signs.get(d["driver"], "")
        observed = data["target"].groupby(data.index.month).apply(lambda s: float((s < STRESS_Z).mean()))
        self.report = {
            "models": [{k: v for k, v in r.items() if k != "_m"} for r in results],
            "chosen": best["model"], "train_period": f"{tr.index.min()}–{tr.index.max()}",
            "test_period": f"{te.index.min()}–{te.index.max()}", "n_samples": int(len(data)),
            "drivers": drivers,
            "observed_stress_prob": [round(float(observed.get(m, 0)), 3) for m in range(1, 13)],
            "note": "Skill is measured on later years the model never saw. R² near 0 means weather explains "
                    "little of the greenness swings (management, pests, cloud contamination also matter). "
                    "The physics-guided model is preferred for what-if scenarios because its rain and heat "
                    "effects always point the physically sensible way.",
        }
        self._baseline_months = data.index
        return self.report

    def stress_probability(self, climate: Climate, sat: pd.DataFrame) -> list[float] | None:
        """Predicted chance per calendar month that vegetation looks stressed (NDVI z < -1)."""
        if self.model is None:
            return None
        X = self._frame(climate, sat, fit_refs=False)
        X = X.reindex(columns=self.features).dropna()
        if X.empty:
            return None
        pred = self.model.predict(X)
        p = stats.norm.cdf((STRESS_Z - pred) / self.resid_sd)
        prob = pd.Series(p, index=X.index).groupby(X.index.month).mean()
        return [round(float(prob.get(m, 0)), 3) for m in range(1, 13)]
