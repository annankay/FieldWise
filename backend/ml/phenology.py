"""AI season detection from the satellite greenness record (MODIS, or Landsat when available).

Two approaches are compared, as the challenge asks:
  1. Rule:  a month is "bare" when NDVI is below a fixed threshold.
  2. AI:    a Gaussian mixture model learns, from every month of every year, which greenness levels
            form natural groups (bare / growing / full canopy) for THIS field, without a fixed threshold.
            It also gives a probability, so we can say how sure it is.
Season transitions (green-up and dry-down) come from where greenness rises or falls fastest.
"""
from __future__ import annotations

import numpy as np
import pandas as pd
from sklearn.mixture import GaussianMixture

RULE_THRESHOLD = 0.3


def detect_seasons(sat: pd.DataFrame, column: str = "ndvi") -> dict | None:
    if sat is None or column not in sat or sat[column].notna().sum() < 36:
        return None
    s = sat[column].dropna()
    X = s.to_numpy().reshape(-1, 1)
    # three natural levels (bare / growing / full canopy) when the record is long enough,
    # otherwise two; BIC decides only if the 3-level model is clearly worse
    fits = {k: GaussianMixture(n_components=k, random_state=0, n_init=3).fit(X) for k in (2, 3)}
    bic = {k: m.bic(X) for k, m in fits.items()}
    k = 3 if len(X) >= 60 and bic[3] <= bic[2] + 10 else 2
    gm = fits[k]
    order = np.argsort(gm.means_.ravel())              # lowest mean = bare
    names = ["bare", "growing", "full"] if k == 3 else ["bare", "growing"]
    label_of = {int(c): names[r] for r, c in enumerate(order)}
    proba = gm.predict_proba(X)
    bare_comp = int(order[0])
    bare_p = pd.Series(proba[:, bare_comp], index=s.index)
    months = s.index.month

    ai_bare_prob = bare_p.groupby(months).mean().reindex(range(1, 13)).fillna(0)
    rule_bare_prob = (s < RULE_THRESHOLD).groupby(months).mean().reindex(range(1, 13)).fillna(0)
    ai_bare = [int(m) for m, v in ai_bare_prob.items() if v >= 0.5]
    rule_bare = [int(m) for m, v in rule_bare_prob.items() if v >= 0.5]
    agree = float(((ai_bare_prob >= 0.5) == (rule_bare_prob >= 0.5)).mean())

    clim = s.groupby(months).mean().reindex(range(1, 13))
    diff = np.roll(clim.to_numpy(), -1) - clim.to_numpy()      # change from month m to m+1
    green_up = int(np.nanargmax(diff)) % 12 + 2
    dry_down = int(np.nanargmin(diff)) % 12 + 2
    green_up = (green_up - 1) % 12 + 1
    dry_down = (dry_down - 1) % 12 + 1

    # how certain the AI is per month: mean max-probability of its classification
    certainty = pd.Series(proba.max(axis=1), index=s.index).groupby(months).mean().reindex(range(1, 13))

    # is the bare season getting longer? count AI-bare months per year
    per_year = (bare_p >= 0.5).groupby(s.index.year).sum()
    per_year = per_year[s.groupby(s.index.year).count() >= 10]
    trend = None
    if len(per_year) >= 8:
        slope = np.polyfit(per_year.index.to_numpy(float), per_year.to_numpy(float), 1)[0]
        trend = round(float(slope * 10), 2)

    return {
        "source": column, "components": k,
        "levels": {label_of[int(c)]: round(float(gm.means_.ravel()[c]), 3) for c in range(k)},
        "ai_bare_prob": [round(float(v), 3) for v in ai_bare_prob.to_numpy()],
        "rule_bare_prob": [round(float(v), 3) for v in rule_bare_prob.to_numpy()],
        "ai_bare_months": ai_bare, "rule_bare_months": rule_bare,
        "agreement": round(agree, 3), "rule_threshold": RULE_THRESHOLD,
        "green_up_month": green_up, "dry_down_month": dry_down,
        "certainty": [round(float(v), 3) for v in certainty.fillna(0).to_numpy()],
        "bare_months_trend_per_decade": trend,
        "ndvi_clim": [round(float(v), 3) for v in clim.fillna(0).to_numpy()],
    }
