"""Builds the comparison: the farmer's current rotation + 3-4 suggested strategies."""
from __future__ import annotations

from backend.engine.scoring import CRITERIA, Context, normalize_plantings, score_rotation, total_score
from backend.engine.search import beam_search

ARCHETYPES = [
    {"id": "best_match", "name": "Best match for your priorities",
     "tagline": "The rotation that scores highest on the goals you set.", "weights": None},
    {"id": "soil_builder", "name": "Soil builder",
     "tagline": "Legumes, cover and deep roots to rebuild nitrogen, carbon and structure.",
     "weights": {"nitrogen": 4, "organic_matter": 4, "erosion": 3, "infiltration": 3, "pest_break": 2,
                 "climate_fit": 2, "water": 1, "income": 1, "forage": 0.5}},
    {"id": "water_saver", "name": "Water saver",
     "tagline": "Drought-tolerant crops timed to the rains, lowest irrigation need.",
     "weights": {"water": 5, "climate_fit": 3, "infiltration": 2, "erosion": 1.5, "income": 1.5, "nitrogen": 1,
                 "organic_matter": 1, "pest_break": 1, "forage": 0.5}},
    {"id": "income_diversifier", "name": "Income diversifier",
     "tagline": "Adds a higher-value or second cash crop while breaking pest cycles.",
     "weights": {"income": 5, "climate_fit": 2.5, "pest_break": 2, "water": 1, "nitrogen": 1,
                 "organic_matter": 0.5, "erosion": 0.5, "forage": 0.5}},
    {"id": "livestock", "name": "Crop-livestock mix",
     "tagline": "Food plus feed: forage legumes and dual-purpose crops.",
     "weights": {"forage": 5, "nitrogen": 2, "climate_fit": 2, "erosion": 1.5, "income": 1,
                 "organic_matter": 1, "water": 1, "pest_break": 1}},
]


def _norm(w: dict) -> dict:
    s = sum(max(0, w.get(k, 0)) for k in CRITERIA) or 1
    return {k: max(0, w.get(k, 0)) / s for k in CRITERIA}


def blend(archetype_w: dict | None, farmer_w: dict) -> dict:
    if archetype_w is None:
        return _norm(farmer_w)
    a, f = _norm(archetype_w), _norm(farmer_w)
    return {k: 0.7 * a[k] + 0.3 * f[k] for k in CRITERIA}


def signature(plantings: list[dict]) -> tuple:
    return tuple((p["crop"], p["start"], p.get("companion")) for p in sorted(plantings, key=lambda q: q["start"])
                 if not p.get("intercrop_with"))


def same_crops(a: list[dict], b: list[dict]) -> bool:
    """Same crops in the same years (sowing a month earlier or later is not a different rotation)."""
    key = lambda pl: sorted((p["crop"], p["year"], p.get("companion") or "") for p in pl if not p.get("intercrop_with"))  # noqa: E731
    return key(a) == key(b)


def similarity(a: list[dict], b: list[dict]) -> float:
    sa = {(p["crop"], p["sow_month"]) for p in a}
    sb = {(p["crop"], p["sow_month"]) for p in b}
    return len(sa & sb) / max(1, len(sa | sb))


def describe(plantings: list[dict], crops: dict) -> str:
    from backend.pipeline.features import MONTH_NAMES
    parts = [f"Y{p['year']} {MONTH_NAMES[p['sow_month'] - 1]}: {crops[p['crop']]['name']}"
             + (f" + {crops[p['companion']]['name']}" if p.get("companion") else "")
             for p in plantings if not p.get("intercrop_with")]
    return " → ".join(parts) if parts else "Fallow"


def calendar_strip(plantings: list[dict], cycle: int) -> list[str | None]:
    cal: list[str | None] = [None] * cycle
    for p in sorted(plantings, key=lambda q: "intercrop_with" in q):     # main crops first
        for k in range(p["duration_m"]):
            i = (p["start"] + k) % cycle
            if cal[i] is None or not p.get("intercrop_with"):
                cal[i] = p["crop"]
    return cal


def is_productive(cid: str, ctx: Context, farmer_w: dict) -> bool:
    crop = ctx.crops[cid]
    if crop["group"] == "cover":
        return False
    if crop["group"] == "forage":
        return farmer_w.get("forage", 0) >= 3
    return ctx.market_value(cid) >= 0.35 or cid == ctx.staple


def feeds_every_year(plantings: list[dict], ctx: Context, farmer_w: dict) -> bool:
    years = range(1, ctx.cycle // 12 + 1)
    return all(any(p["year"] == y and is_productive(p["crop"], ctx, farmer_w) for p in plantings) for y in years)


def evaluate(plantings: list[dict], ctx: Context, weights: dict) -> dict:
    res = score_rotation(plantings, ctx)
    res["total"] = total_score(res["scores"], weights, res["numbers"])
    return res


def build_strategies(current_raw: list[dict], ctx: Context, farmer_w: dict, sowing_months: list[int],
                     climate_type: str, constraints: dict, n_suggestions: int = 4) -> dict:
    crops = ctx.crops
    current = normalize_plantings(current_raw, crops)
    weight_sets = [blend(a["weights"], farmer_w) for a in ARCHETYPES] + [_norm({k: 1 for k in CRITERIA})]
    # keep partial plans that produce food/income alive in the search, so the final pool has
    # enough rotations that feed the family every year
    weight_sets.append(_norm({"income": 5, "climate_fit": 3, "water": 1}))
    pool = beam_search(ctx, sowing_months, climate_type, constraints, weight_sets)
    evaluated = [(pl, score_rotation(pl, ctx)) for pl in pool]
    best_fit = max((r["scores"]["climate_fit"] for _, r in evaluated), default=0)
    bar = min(55.0, 0.85 * best_fit)   # drop rotations that clearly fight the climate
    scored = [(pl, r) for pl, r in evaluated if r["scores"]["climate_fit"] >= bar]
    # farmers need food, feed or income every year: each year of the cycle must have a productive crop
    productive = [(pl, r) for pl, r in scored if feeds_every_year(pl, ctx, farmer_w)]
    if productive:
        scored = productive

    cur_eval = evaluate(current, ctx, _norm(farmer_w))
    chosen: list[dict] = []
    used_sigs = {signature(current)}
    # first pass keeps options clearly different from each other; later passes relax that when the
    # climate or the farmer's limits leave few possible rotations
    for max_sim in (0.6, 0.8, 0.95):
        for arch in ARCHETYPES:
            if len(chosen) >= n_suggestions:
                break
            if any(c["id"] == arch["id"] for c in chosen):
                continue
            if arch["id"] == "livestock" and farmer_w.get("forage", 0) < 2:
                continue  # only offer the livestock mix when feed matters to this farmer
            w = blend(arch["weights"], farmer_w)
            ranked = sorted(scored, key=lambda x: -total_score(x[1]["scores"], w, x[1]["numbers"]))
            for pl, r in ranked:
                sig = signature(pl)
                if sig in used_sigs:
                    continue
                if any(similarity(pl, c["plantings"]) > max_sim for c in chosen):
                    continue
                if similarity(pl, current) > 0.85 or same_crops(pl, current):
                    continue
                if any(same_crops(pl, c["plantings"]) for c in chosen):
                    continue
                used_sigs.add(sig)
                chosen.append({"id": arch["id"], "name": arch["name"], "tagline": arch["tagline"],
                               "plantings": pl, "eval": r, "arch_weights": w})
                break
        if len(chosen) >= 3:
            break

    def pack(sid, name, tagline, plantings, r, is_current=False):
        return {
            "id": sid, "name": name, "tagline": tagline, "is_current": is_current,
            "plantings": [{**p, "name": crops[p["crop"]]["name"], "group": crops[p["crop"]]["group"]}
                          for p in plantings],
            "sequence": describe(plantings, crops),
            "scores": r["scores"], "numbers": r["numbers"], "coverage": r["coverage"], "fits": r["fits"],
            "total": total_score(r["scores"], _norm(farmer_w), r["numbers"]),
            "calendar": calendar_strip(plantings, ctx.cycle),
        }

    out = [pack("current", "Your current rotation", "What you grow today, scored the same way.",
                current, cur_eval, True)]
    for c in chosen:
        out.append(pack(c["id"], c["name"], c["tagline"], c["plantings"], c["eval"]))
    best = max(out[1:], key=lambda s: s["total"], default=None)
    for s in out:
        s["recommended"] = best is not None and s["id"] == best["id"]
        s["delta_vs_current"] = {k: round(s["scores"][k] - out[0]["scores"][k], 1) for k in CRITERIA}
    return {"strategies": out, "pool_size": len(pool), "weights": _norm(farmer_w)}
