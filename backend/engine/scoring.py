"""Rotation scoring: nine soil-health / resilience / livelihood criteria, each 0-100.

A rotation is a list of plantings on a 24-month (2-year) cycle that repeats:
    {"crop": "cowpea", "year": 1, "sow_month": 9, "duration_m": 3}
Scores are transparent rules (no black box) so every number can be explained to a farmer.
"""
from __future__ import annotations

from dataclasses import dataclass, replace

import numpy as np

from backend.config import CYCLE_MONTHS
from backend.engine.crops import CropFitter

CRITERIA = {
    "water": {"label": "Water fit & saving", "icon": "droplet",
              "about": "Crop water demand (FAO-56 Kc x ET₀) vs. effective rainfall; less irrigation need scores higher."},
    "nitrogen": {"label": "Nitrogen supply", "icon": "leaf",
                 "about": "Nitrogen fixed by legumes vs. nitrogen the cereals and roots remove."},
    "organic_matter": {"label": "Organic matter", "icon": "sprout",
                       "about": "Residue and root biomass returned to the soil (builds carbon and structure)."},
    "erosion": {"label": "Erosion protection", "icon": "shield",
                "about": "How much living cover or residue protects the soil in months with heavy rain."},
    "infiltration": {"label": "Water soaks in", "icon": "roots",
                     "about": "Deep roots, organic matter and cover during storms open the soil so rain soaks in instead of running off."},
    "pest_break": {"label": "Pest & disease break", "icon": "bug",
                   "about": "Switching plant families stops pests and diseases carrying over between seasons."},
    "income": {"label": "Income potential", "icon": "coins",
               "about": "Local market value x expected crop performance (market values need local checking)."},
    "forage": {"label": "Livestock feed", "icon": "cow", "about": "Forage and crop residue usable as animal feed."},
    "climate_fit": {"label": "Climate fit", "icon": "sun",
                    "about": "How well each crop's needs match this field's heat, frost and rain pattern."},
}

DEFAULT_WEIGHTS = {k: 1.0 for k in CRITERIA}


@dataclass
class Context:
    fitter: CropFitter
    crops: dict
    market: dict
    erosivity: np.ndarray      # 12 values: relative storm erosion potential per calendar month
    staple: str | None = None
    keep_staple: bool = False
    cycle: int = CYCLE_MONTHS
    staple_months: tuple = ()   # months the farmer sows the staple today (kept in its usual season)

    def market_value(self, crop_id: str) -> float:
        return float(self.market.get(crop_id, self.crops[crop_id]["market"]))


# Common intercrops in African smallholder farming (main crop -> companions grown in the same field).
# Shares follow typical land-equivalent ratios (~1.3): the main crop keeps most of its density.
INTERCROPS = {
    "maize": ["common_bean", "cowpea", "pigeon_pea", "groundnut", "soybean", "desmodium", "lablab", "mucuna"],
    "sorghum": ["cowpea", "pigeon_pea", "groundnut"],
    "millet": ["cowpea", "groundnut", "bambara"],
    "finger_millet": ["common_bean", "cowpea"],
    "cassava": ["groundnut", "cowpea", "common_bean", "maize"],
    "cotton": ["cowpea"],
    "yam": ["maize", "cowpea"],
}
MAIN_SHARE, COMPANION_SHARE = 0.85, 0.45


def normalize_plantings(plantings: list[dict], crops: dict) -> list[dict]:
    """Accepts compact plantings ({"crop", "year", "sow_month", "with"?}) and expands intercrops into a
    main planting + a companion planting that shares the field."""
    out = []
    for p in plantings:
        crop = crops[p["crop"]]
        dur = int(p.get("duration_m") or crop["duration_m"])
        start = (int(p.get("year", 1)) - 1) * 12 + int(p["sow_month"]) - 1
        base = {"crop": p["crop"], "year": start // 12 + 1, "sow_month": start % 12 + 1, "duration_m": dur, "start": start}
        if p.get("intercrop_with"):                       # already-expanded companion
            out.append({**base, "share": float(p.get("share", COMPANION_SHARE)), "intercrop_with": p["intercrop_with"]})
            continue
        comp = p.get("with")
        if comp and comp in crops and comp != p["crop"]:
            out.append({**base, "share": MAIN_SHARE, "companion": comp})
            out.append({"crop": comp, "year": base["year"], "sow_month": base["sow_month"], "start": start,
                        "duration_m": int(crops[comp]["duration_m"]), "share": COMPANION_SHARE, "intercrop_with": p["crop"]})
        else:
            out.append({**base, "share": float(p.get("share", 1.0))})
    return sorted(out, key=lambda q: (q["start"], "intercrop_with" in q))


def compact(plantings: list[dict]) -> list[dict]:
    """Inverse of normalize_plantings: mains with a 'with' field, companions folded in."""
    out = []
    for p in plantings:
        if p.get("intercrop_with"):
            continue
        q = {"crop": p["crop"], "year": p["year"], "sow_month": p["sow_month"], "duration_m": p["duration_m"]}
        if p.get("companion"):
            q["with"] = p["companion"]
        out.append(q)
    return out


def _mains(plantings: list[dict]) -> list[dict]:
    return [p for p in plantings if not p.get("intercrop_with")]


def coverage_profile(plantings: list[dict], ctx: Context, fits: list) -> np.ndarray:
    L = ctx.cycle
    cov = np.full(L, 0.05)  # bare soil / sparse weeds
    for p, f in zip(plantings, fits):
        crop = ctx.crops[p["crop"]]
        d = p["duration_m"]
        for k in range(d):
            v = crop["cover"] * min(1.0, (k + 1) / 1.5) * (0.6 + 0.4 * f.fit)
            i = (p["start"] + k) % L
            cov[i] = max(cov[i], v)
        # residue left after harvest protects the soil for a while
        for j, share in ((0, 0.5), (1, 0.25)):
            i = (p["start"] + d + j) % L
            cov[i] = max(cov[i], crop["residue"] * share)
    for p in plantings:                      # a companion crop fills the gaps between the main rows
        if p.get("intercrop_with"):
            for k in range(p["duration_m"]):
                i = (p["start"] + k) % L
                cov[i] = min(1.0, cov[i] + 0.12)
    return cov


def _pest_metrics(plantings: list[dict], ctx: Context) -> tuple[int, int]:
    """(longest run of the same plant family in a row among MAIN crops, number of distinct families)."""
    all_fams = {ctx.crops[p["crop"]]["family"] for p in plantings}
    plantings = _mains(plantings)
    if not plantings:
        return 0, 0
    fams = [ctx.crops[p["crop"]]["family"] for p in plantings]
    n = len(plantings)
    # a long bare break (>= 8 months) between plantings interrupts the pest cycle
    breaks = []
    for i, p in enumerate(plantings):
        nxt = plantings[(i + 1) % n]
        end = p["start"] + p["duration_m"]
        gap = (nxt["start"] - end) % ctx.cycle if n > 1 else ctx.cycle - p["duration_m"]
        breaks.append(gap >= 8)
    best = run = 0
    for i in range(2 * n):
        k = i % n
        prev = (k - 1) % n
        if i > 0 and fams[k] == fams[prev] and not breaks[prev]:
            run += 1
        else:
            run = 1
        best = max(best, min(run, n))
    if n == 1:
        best = 1 if breaks[0] else 2
    return best, len(all_fams)


FALLOW_STORAGE_EFF = 0.25   # share of rain during a bare fallow that is stored in the soil (dryland rule of thumb)


def apply_fallow_storage(all_plantings: list[dict], fits: list, ctx: Context, fitter: CropFitter) -> list:
    """A long bare fallow before a crop stores some rain in the soil (why wheat-fallow exists).
    This rotation-level interaction adjusts each MAIN crop's water factor."""
    idx = [i for i, p in enumerate(all_plantings) if not p.get("intercrop_with")]
    plantings = [all_plantings[i] for i in idx]
    main_fits = [fits[i] for i in idx]
    out_all = list(fits)
    for i, f in zip(idx, _fallow(plantings, main_fits, ctx, fitter)):
        out_all[i] = f
    return out_all


def _fallow(plantings: list[dict], fits: list, ctx: Context, fitter: CropFitter) -> list:
    n = len(plantings)
    if n == 0:
        return fits
    rain = fitter.c["rain"].to_numpy()
    out = []
    for i, (p, f) in enumerate(zip(plantings, fits)):
        prev = plantings[i - 1]
        prev_end = prev["start"] + prev["duration_m"]
        gap = (p["start"] - prev_end) % ctx.cycle if n > 1 else ctx.cycle - p["duration_m"]
        if gap < 4 or fitter.irrigation >= 0.99:
            out.append(f)
            continue
        gap_months = [(p["start"] - 1 - k) % 12 for k in range(gap)]
        crop = ctx.crops[p["crop"]]
        room = max(0.0, fitter.root_zone_mm(crop) - f.storage_mm)
        bonus = min(room, FALLOW_STORAGE_EFF * float(rain[gap_months].sum()))
        if bonus <= 1:
            out.append(f)
            continue
        new_def = max(0.0, f.deficit_mm - bonus)
        water = fitter.water_from_deficit(crop, new_def, f.etc_mm, f.dry_pen)
        total = f.fit * water / max(f.water, 1e-6) if f.water > 0 else 0.0
        out.append(replace(f, water=water, fit=min(1.0, total), deficit_mm=new_def,
                           storage_mm=f.storage_mm + bonus))
    return out


def score_rotation(plantings: list[dict], ctx: Context, fitter: CropFitter | None = None) -> dict:
    """Return per-criterion scores (0-100) plus the physical numbers behind them."""
    fitter = fitter or ctx.fitter
    years = ctx.cycle / 12
    plantings = sorted(plantings, key=lambda q: q["start"])
    fits = [fitter.fit(p["crop"], p["sow_month"], p["duration_m"]) for p in plantings]
    fits = apply_fallow_storage(plantings, fits, ctx, fitter)

    share = np.array([p.get("share", 1.0) for p in plantings], float)
    if plantings:
        dur = np.array([p["duration_m"] for p in plantings], float)
        wgt = dur * share
        fit_v = np.array([f.fit for f in fits])
        wfit = np.array([f.water for f in fits])
        etc = sum(f.etc_mm * sh for f, sh in zip(fits, share))
        deficit = sum(f.deficit_mm * sh for f, sh in zip(fits, share))
        rain_met = 1 - deficit / max(etc, 1)
        water = 100 * (0.55 * float((wfit * wgt).sum() / wgt.sum()) + 0.45 * rain_met)
        climate_fit = 100 * float((fit_v * wgt).sum() / wgt.sum())
    else:
        etc = deficit = 0.0
        water, climate_fit, rain_met = 50.0, 0.0, 1.0

    nfix = sum(ctx.crops[p["crop"]]["n_fix"] * f.fit * sh for p, f, sh in zip(plantings, fits, share)) / years
    ndem = sum(ctx.crops[p["crop"]]["n_demand"] * sh for p, sh in zip(plantings, share)) / years
    nitrogen = 100 * float(np.clip(nfix / (0.6 * ndem + 60), 0, 1))

    om = 0.0
    for p, f, sh in zip(plantings, fits, share):
        crop = ctx.crops[p["crop"]]
        om += (crop["residue"] * 0.6 + min(crop["root_depth"], 2.5) / 2.5 * 0.4) * \
            (p["duration_m"] / 4) ** 0.5 * (0.4 + 0.6 * f.fit) * sh
    om /= years
    organic = 100 * float(np.clip(om / 1.5, 0, 1))

    cov = coverage_profile(plantings, ctx, fits)
    eros = np.tile(ctx.erosivity, int(years))
    storm_cover = float((cov * eros).sum() / max(eros.sum(), 1e-9))
    erosion = 100 * storm_cover
    bare_months = float((cov < 0.15).sum() / years)

    # infiltration: root channels (deep roots growing for many months) + organic matter + cover in storms
    root_months = sum(min(ctx.crops[p["crop"]]["root_depth"], 2.0) / 2.0 * p["duration_m"] * (0.5 + 0.5 * f.fit) * min(1.0, sh + 0.3)
                      for p, f, sh in zip(plantings, fits, share)) / ctx.cycle
    infiltration = 100 * float(np.clip(0.4 * min(1.0, root_months / 0.6) + 0.3 * min(1.0, om / 1.5)
                                       + 0.3 * storm_cover, 0, 1))

    max_run, n_fam = _pest_metrics(plantings, ctx)
    if plantings:
        pest = 100 * (0.55 * (1 - np.clip((max_run - 1) / 3, 0, 1)) + 0.45 * np.clip((n_fam - 1) / 2, 0, 1))
    else:
        pest = 50.0

    inc = sum(ctx.market_value(p["crop"]) * f.fit * min(1.3, (p["duration_m"] / 4) ** 0.5) * sh
              for p, f, sh in zip(plantings, fits, share)) / years
    income = 100 * float(np.clip(inc / 1.5, 0, 1))
    fod = sum(ctx.crops[p["crop"]]["forage"] * f.fit * (p["duration_m"] / 4) ** 0.5 * sh
              for p, f, sh in zip(plantings, fits, share)) / years
    forage = 100 * float(np.clip(fod / 1.6, 0, 1))

    staple_years_missing = 0
    staple_missing_cycle = False
    if ctx.keep_staple and ctx.staple:
        def in_season(p):
            if not ctx.staple_months:
                return True
            return any(min((p["sow_month"] - m) % 12, (m - p["sow_month"]) % 12) <= 1 for m in ctx.staple_months)
        for y in range(1, int(years) + 1):
            if not any(p["crop"] == ctx.staple and p["year"] == y and in_season(p) for p in _mains(plantings)):
                staple_years_missing += 1
        staple_missing_cycle = not any(p["crop"] == ctx.staple and in_season(p) for p in _mains(plantings))

    return {
        "scores": {"water": round(water, 1), "nitrogen": round(nitrogen, 1), "organic_matter": round(organic, 1),
                   "erosion": round(erosion, 1), "infiltration": round(infiltration, 1), "pest_break": round(float(pest), 1), "income": round(income, 1),
                   "forage": round(forage, 1), "climate_fit": round(climate_fit, 1)},
        "numbers": {"crop_water_mm_yr": round(etc / years), "irrigation_need_mm_yr": round(deficit / years),
                    "rain_met_pct": round(100 * rain_met), "n_fixed_kg_yr": round(nfix),
                    "n_demand_kg_yr": round(ndem), "bare_months_yr": round(bare_months, 1),
                    "families": n_fam, "same_family_run": max_run,
                    "staple_years_missing": staple_years_missing,
                    "staple_missing_cycle": staple_missing_cycle,
                    "intercrops": sum(1 for p in plantings if p.get("intercrop_with"))},
        "coverage": [round(float(v), 2) for v in cov],
        "fits": [f.as_dict() for f in fits],
    }


def total_score(scores: dict, weights: dict, numbers: dict | None = None) -> float:
    wsum = sum(max(0.0, weights.get(k, 0)) for k in CRITERIA)
    if wsum <= 0:
        weights, wsum = DEFAULT_WEIGHTS, len(CRITERIA)
    total = sum(scores[k] * max(0.0, weights.get(k, 0)) for k in CRITERIA) / wsum
    if numbers:
        # 'keep my staple' = grow it at least once in the 2-year cycle (soft preference for every year)
        total -= 8 * numbers.get("staple_years_missing", 0)
        total -= 25 if numbers.get("staple_missing_cycle") else 0
    return round(float(total), 1)
