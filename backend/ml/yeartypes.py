"""Unsupervised 'year types': cluster past seasons by how they behaved (k-means).

Farmers think in kinds of years ("the rains came late", "a hot dry year"). Clustering 35 years of
NASA POWER data into a few year types lets us test every rotation against each kind of year and
check whether bad kinds of year are becoming more common.
"""
from __future__ import annotations

import numpy as np
import pandas as pd
from sklearn.cluster import KMeans
from sklearn.metrics import silhouette_score
from sklearn.preprocessing import StandardScaler

from backend.pipeline.features import Climate

FEATURE_LABELS = {
    "rain": ("Wet", "Dry"),
    "onset_doy": ("Late-start", "Early-start"),
    "dry_spell": ("Patchy-rain", None),
    "heat_days": ("Hot", "Mild"),
    "frost_days": ("Frosty", None),
    "spring_rain": ("Wet-spring", "Dry-spring"),
}


def annual_features(climate: Climate, window_months: list[int], onset: pd.Series | None,
                    climate_type: str) -> pd.DataFrame:
    m = climate.monthly
    years = m.index.get_level_values("year")
    months = m.index.get_level_values("month")
    feats = pd.DataFrame(index=sorted(set(years)))
    feats["rain"] = m.groupby(level="year")["rain"].sum()
    feats["heat_days"] = m.groupby(level="year")["heat_days"].sum()
    in_window = m[np.isin(months, window_months)] if window_months else m
    feats["dry_spell"] = in_window.groupby(level="year")["dry_spell"].max()
    if climate_type == "tropical" and onset is not None and onset.notna().sum() > len(onset) * 0.7:
        feats["onset_doy"] = onset.reindex(feats.index).fillna(onset.median())
    else:
        spring = m[np.isin(months, [3, 4, 5])]
        feats["spring_rain"] = spring.groupby(level="year")["rain"].sum()
        if m["frost_days"].sum() > 0:
            feats["frost_days"] = m.groupby(level="year")["frost_days"].sum()
    return feats.dropna()


def cluster_years(feats: pd.DataFrame, k_range=(2, 3, 4), seed: int = 0) -> dict:
    X = StandardScaler().fit_transform(feats.to_numpy())
    best = None
    for k in k_range:
        if len(feats) <= k * 3:
            continue
        km = KMeans(n_clusters=k, n_init=20, random_state=seed).fit(X)
        sil = silhouette_score(X, km.labels_)
        # prefer 3 types when scores are close (easier to explain to farmers)
        adj = sil + (0.03 if k == 3 else 0)
        if best is None or adj > best[0]:
            best = (adj, k, km, sil)
    if best is None:
        return {"types": [], "k": 0}
    _, k, km, sil = best
    labels = km.labels_
    z = pd.DataFrame(X, index=feats.index, columns=feats.columns)
    years = feats.index.to_numpy()
    mid = np.median(years)
    types = []
    for c in range(k):
        mask = labels == c
        zc = z[mask].mean()
        words = []
        for col, val in zc.abs().sort_values(ascending=False).items():
            if val < 0.45 or len(words) == 2:
                break
            hi_word, lo_word = FEATURE_LABELS.get(col, (col, None))
            word = hi_word if zc[col] > 0 else lo_word
            if word:
                words.append(word)
        name = (" & ".join(words) + " year") if words else "Typical year"
        early = int(((years < mid) & mask).sum())
        late = int(((years >= mid) & mask).sum())
        types.append({
            "id": int(c), "name": name, "years": [int(y) for y in years[mask]],
            "share": round(float(mask.mean()), 3),
            "early_count": early, "late_count": late,
            "becoming": "more common" if late >= early + 2 else "less common" if early >= late + 2 else "stable",
            "means": {col: round(float(feats.loc[mask, col].mean()), 1) for col in feats.columns},
        })
    types.sort(key=lambda t: -t["share"])
    return {"types": types, "k": k, "silhouette": round(float(sil), 3), "features": list(feats.columns),
            "overall_means": {col: round(float(feats[col].mean()), 1) for col in feats.columns}}

