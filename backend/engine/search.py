"""Generate candidate rotations with a diversity-preserving beam search.

We walk through the 24-month cycle from one sowing opportunity to the next. At each opportunity we
either sow one of the crops that fits that month, or wait. Partial rotations are pruned by several
weightings at once (water, soil, income, farmer, neutral) so the final pool stays diverse. Every
complete rotation is then scored once on all criteria; choosing a strategy for any set of farmer
priorities is just a weighted sum over that pool (instant re-ranking when sliders move).
"""
from __future__ import annotations

import bisect

from backend.config import CYCLE_MONTHS
from backend.engine.scoring import COMPANION_SHARE, INTERCROPS, MAIN_SHARE, Context, score_rotation, total_score


def candidate_crops(ctx: Context, sow_month: int, climate_type: str, constraints: dict,
                    min_fit: float = 0.5, per_month: int = 9) -> list[str]:
    avoid = set(constraints.get("avoid", []))
    # crops marked hand_ok=false need machinery to sow/harvest at field scale;
    # hand tools AND animal traction both exclude them
    hand_only = constraints.get("equipment", "hand") in ("hand", "animal")
    scored = []
    for cid, crop in ctx.crops.items():
        if cid in avoid:
            continue
        if hand_only and not crop["hand_ok"]:
            continue
        f = ctx.fitter.fit(cid, sow_month)
        if f.fit >= min_fit or (cid == ctx.staple and f.fit >= 0.35):
            scored.append((f.fit, cid, crop["group"]))
    scored.sort(reverse=True)
    chosen, groups = [], {}
    for fit, cid, group in scored:          # keep variety: at most 3 per crop group
        if groups.get(group, 0) >= 3 and cid != ctx.staple:
            continue
        chosen.append(cid)
        groups[group] = groups.get(group, 0) + 1
        if len(chosen) >= per_month:
            break
    # the farmer's staple is always an option when it can grow at all
    if ctx.staple and ctx.staple not in chosen and any(o[1] == ctx.staple for o in scored):
        chosen.append(ctx.staple)
    return chosen


def companions_for(ctx: Context, cid: str, month: int, constraints: dict, k: int = 2) -> list[str]:
    """Best-fitting intercrop partners for a main crop sown in this month."""
    avoid = set(constraints.get("avoid", []))
    hand_only = constraints.get("equipment", "hand") in ("hand", "animal")
    out = []
    for comp in INTERCROPS.get(cid, []):
        if comp not in ctx.crops or comp in avoid or (hand_only and not ctx.crops[comp]["hand_ok"]):
            continue
        f = ctx.fitter.fit(comp, month).fit
        if f >= 0.45:
            out.append((f, comp))
    return [c for _, c in sorted(out, reverse=True)[:k]]


def beam_search(ctx: Context, sowing_months: list[int], climate_type: str, constraints: dict,
                weight_sets: list[dict], beam: int = 160, max_plantings: int = 6) -> list[list[dict]]:
    """State = tuple of (crop, start, duration, companion_or_None). Intercrops share the same slot."""
    L = ctx.cycle
    ops = sorted({(m - 1) + 12 * y for m in sowing_months for y in range(L // 12)})
    cands = {m: candidate_crops(ctx, m, climate_type, constraints) for m in set(sowing_months)}
    comps = {(c, m): companions_for(ctx, c, m, constraints) for m in set(sowing_months) for c in cands[m]}
    K = len(ops)
    levels: dict[int, list[tuple]] = {0: [()]}
    finals: list[tuple] = []

    def to_plantings(state):
        out = []
        for c, s, d, comp in state:
            base = {"crop": c, "start": s, "duration_m": d, "year": s // 12 + 1, "sow_month": s % 12 + 1}
            if comp:
                out.append({**base, "share": MAIN_SHARE, "companion": comp})
                out.append({"crop": comp, "start": s, "duration_m": ctx.crops[comp]["duration_m"], "year": s // 12 + 1,
                            "sow_month": s % 12 + 1, "share": COMPANION_SHARE, "intercrop_with": c})
            else:
                out.append({**base, "share": 1.0})
        return out

    for j in range(K + 1):
        states = list(dict.fromkeys(levels.pop(j, [])))
        if not states:
            continue
        if j == K:
            finals.extend(states)
            break
        if len(states) > beam:
            per = max(1, beam // len(weight_sets))
            keep = set()
            scored = [(st, score_rotation(to_plantings(st), ctx)) for st in states]
            for w in weight_sets:
                ranked = sorted(scored, key=lambda x: -total_score(x[1]["scores"], w, x[1]["numbers"]))
                keep.update(st for st, _ in ranked[:per])
            states = list(keep)
        o = ops[j]
        m = o % 12 + 1
        for st in states:
            levels.setdefault(j + 1, []).append(st)          # wait / leave fallow
            if len(st) >= max_plantings:
                continue
            first_start = st[0][1] if st else o
            for cid in cands.get(m, []):
                d = ctx.crops[cid]["duration_m"]
                if st and st[-1][0] == cid and cid != ctx.staple:
                    continue                                 # suggestions never repeat a crop back-to-back
                for comp in [None] + comps.get((cid, m), []):
                    end = o + max(d, ctx.crops[comp]["duration_m"] if comp else 0)
                    if end > first_start + L:                # would overlap next cycle's first crop
                        continue
                    new = st + ((cid, o, d, comp),)
                    nj = bisect.bisect_left(ops, end)
                    levels.setdefault(min(nj, K), []).append(new)
    unique = list(dict.fromkeys(finals))
    return [to_plantings(st) for st in unique if st]

