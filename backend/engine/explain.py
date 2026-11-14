"""Turns scores into farmer-readable reasons, evidence, benefits, risks, gaps and confidence.

Every sentence is generated from numbers we computed, and each evidence line names the dataset it
came from, so a farmer, an extension officer or a judge can trace any claim back to its source.
Output has two layers: full detail (expert view) and a short "farmer" summary (farmer view).
"""
from __future__ import annotations

from backend.engine.scoring import CRITERIA
from backend.i18n import criterion, join, month_name, months_text, t


def crop_name(crops: dict, cid: str, lang: str) -> str:
    c = crops[cid]
    return c.get("names", {}).get(lang) or c["name"].split(" (")[0]


def _crop_list(ids, crops, lang) -> str:
    return join(lang, [crop_name(crops, c, lang) for c in dict.fromkeys(ids)])


def _bare_calendar_months(coverage: list[float]) -> list[int]:
    """Calendar months that are bare in BOTH years of the cycle."""
    return [m + 1 for m in range(12) if coverage[m] < 0.15 and coverage[m + 12] < 0.15]


def describe(plantings: list[dict], crops: dict, lang: str) -> str:
    parts = [f"{t(lang, 'year_short')}{p['year']} {month_name(lang, p['sow_month'])}: {crop_name(crops, p['crop'], lang)}"
             + (f" + {crop_name(crops, p['companion'], lang)}" if p.get("companion") else "")
             for p in plantings if not p.get("intercrop_with")]
    return " → ".join(parts) if parts else t(lang, "fallow")


def explain(strategy: dict, current: dict, facts: dict, crops: dict, robustness: dict | None,
            prefs: dict | None = None, lang: str = "en") -> dict:
    prefs = prefs or {}
    s, c = strategy["scores"], current["scores"]
    num, cnum = strategy["numbers"], current["numbers"]
    delta = {k: s[k] - c[k] for k in CRITERIA}
    crop_ids = [p["crop"] for p in strategy["plantings"]]
    uniq = list(dict.fromkeys(crop_ids))
    current_ids = {p["crop"] for p in current["plantings"]}
    new_crops = [cid for cid in uniq if cid not in current_ids]
    legumes = [cid for cid in uniq if crops[cid]["n_fix"] > 0]
    deep = [cid for cid in uniq if crops[cid]["root_depth"] >= 1.5]
    drought = [cid for cid in uniq if crops[cid]["drought_tol"] >= 0.75]
    covers = [cid for cid in uniq if crops[cid]["group"] in ("cover", "forage")]
    soil = facts.get("soil", {})
    L = lambda key: criterion(lang, key)  # noqa: E731

    why, evidence, benefits, risks, gaps, ask = [], [], [], [], [], []

    def ev(key, source, **kw):
        evidence.append({"claim": t(lang, key, **kw), "source": source})

    if strategy.get("is_current"):
        why.append(t(lang, "cur_start"))
        for k in sorted(CRITERIA, key=lambda k: s[k])[:2]:
            why.append(t(lang, "weakest", label=L(k), score=round(s[k])))
        bare_now = _bare_calendar_months(strategy["coverage"])
        if bare_now:
            ev("ev_bare_rot", "Your rotation", months=months_text(lang, bare_now))
        if facts.get("bare_ndvi_months"):
            ev("ev_bare_sat", facts.get("bare_source", "MODIS NDVI"), months=months_text(lang, facts["bare_ndvi_months"]))
        if facts.get("esi_dry_months"):
            ev("ev_esi", "ECOSTRESS ESI (70 m)", months=months_text(lang, facts["esi_dry_months"]))
        if cnum["same_family_run"] >= 3 and current["plantings"]:
            risks.append(t(lang, "risk_same_family", n=cnum["same_family_run"],
                           pests=crops[current["plantings"][0]["crop"]]["pests"]))
        if cnum["n_fixed_kg_yr"] == 0 and cnum["n_demand_kg_yr"] > 0:
            risks.append(t(lang, "risk_no_n", n=cnum["n_demand_kg_yr"]))
    else:
        gains = sorted((k for k in CRITERIA if delta[k] >= 8), key=lambda k: -delta[k])
        for k in gains[:4]:
            if k == "erosion":
                bare_now = _bare_calendar_months(current["coverage"])
                bare_new = _bare_calendar_months(strategy["coverage"])
                filled = [m for m in bare_now if m not in bare_new]
                txt = t(lang, "why_erosion")
                if filled:
                    txt += t(lang, "why_erosion_fill", months=months_text(lang, filled))
                if facts.get("heavy_months"):
                    txt += t(lang, "why_storm_months", months=months_text(lang, facts["heavy_months"]))
                why.append(txt + ".")
                ev("ev_heavy", "NASA POWER daily rainfall", n=round(facts.get("heavy_days_per_year", 0)),
                   mm=round(facts.get("heavy_thr", 0)))
                if facts.get("slope_pct") is not None:
                    ev("ev_slope", "SRTM 30 m elevation", slope=f"{facts['slope_pct']:.1f}",
                       share=round((facts.get("high_erosion_share") or 0) * 100))
            elif k == "nitrogen" and legumes:
                why.append(t(lang, "why_nitrogen", crops=_crop_list(legumes, crops, lang), n=num["n_fixed_kg_yr"]))
                ev("ev_ntable", "FAO ECOCROP / crop table")
                if soil.get("soc") is not None:
                    ev("ev_soc", soil.get("source", "SoilGrids"), soc=soil["soc"],
                       level=t(lang, "low") if soil["soc"] < 10 else t(lang, "moderate"))
            elif k == "organic_matter":
                parts = []
                if covers:
                    parts.append(t(lang, "why_om_cover", crops=_crop_list(covers, crops, lang)))
                if deep:
                    parts.append(t(lang, "why_om_deep", crops=_crop_list(deep, crops, lang)))
                why.append(("; ".join(parts) or t(lang, "why_om_generic")) + ".")
                g = facts.get("gedi")
                if g and g.get("available") and g.get("mean"):
                    ev("ev_gedi", "GEDI L4A lidar biomass", km=round(g.get("radius_km", 5)), mean=round(g["mean"]))
            elif k == "infiltration":
                why.append(t(lang, "why_infil"))
            elif k == "pest_break":
                why.append(t(lang, "why_pest", new=num["families"], old=cnum["families"]))
            elif k == "water":
                why.append(t(lang, "why_water", new=num["rain_met_pct"], old=cnum["rain_met_pct"],
                             mm=num["irrigation_need_mm_yr"]))
                ev("ev_et0", "NASA POWER temperature, humidity, wind, sunshine")
                if drought:
                    why.append(t(lang, "why_drought", crops=_crop_list(drought, crops, lang)))
            elif k == "income":
                why.append(t(lang, "why_income"))
            elif k == "forage":
                why.append(t(lang, "why_forage"))
            elif k == "climate_fit":
                why.append(t(lang, "why_climate"))
        inter = [p for p in strategy["plantings"] if p.get("companion")]
        if inter:
            pairs = join(lang, list(dict.fromkeys(f"{crop_name(crops, p['crop'], lang)} + {crop_name(crops, p['companion'], lang)}" for p in inter)))
            why.append(t(lang, "why_intercrop", pairs=pairs))
            if any(p["companion"] == "desmodium" for p in inter):
                why.append(t(lang, "why_pushpull"))
        if not why:
            why.append(strategy.get("tagline", ""))
        if facts.get("dry_months"):
            ev("ev_dry_months", "NASA POWER rain vs FAO-56 ET₀", months=months_text(lang, facts["dry_months"]))
        if facts.get("heat_months"):
            ev("ev_heat_months", "NASA POWER daily maximum temperature", months=months_text(lang, facts["heat_months"]))
        if facts.get("esi_dry_months"):
            ev("ev_esi", "ECOSTRESS ESI (70 m)", months=months_text(lang, facts["esi_dry_months"]))

        if num["bare_months_yr"] < cnum["bare_months_yr"] - 0.4:
            benefits.append(t(lang, "benefit_bare", old=round(cnum["bare_months_yr"]), new=round(num["bare_months_yr"])))
        if num["n_fixed_kg_yr"] > cnum["n_fixed_kg_yr"]:
            benefits.append(t(lang, "benefit_n", n=num["n_fixed_kg_yr"]))
        if num["irrigation_need_mm_yr"] < cnum["irrigation_need_mm_yr"] - 10:
            benefits.append(t(lang, "benefit_water", old=cnum["irrigation_need_mm_yr"], new=num["irrigation_need_mm_yr"]))
        if num["families"] > cnum["families"]:
            benefits.append(t(lang, "benefit_fam", old=cnum["families"], new=num["families"]))
        for k in sorted(CRITERIA, key=lambda k: -delta[k])[:2]:
            if delta[k] > 5:
                benefits.append(t(lang, "benefit_score", label=L(k).capitalize(), old=round(c[k]), new=round(s[k])))
        if not benefits:
            benefits.append(t(lang, "benefit_none"))

        for k in [k for k in CRITERIA if delta[k] <= -8]:
            risks.append(t(lang, "risk_lower", label=L(k), old=round(c[k]), new=round(s[k])))
        for p, f in zip(strategy["plantings"], strategy["fits"]):
            when = t(lang, "when", crop=crop_name(crops, p["crop"], lang), month=month_name(lang, p["sow_month"]),
                     year=p["year"])
            if f["heat"] < 0.75:
                risks.append(t(lang, "risk_heat", when=when, days=round(f["heat_days"])))
            if f["water"] < 0.7:
                risks.append(t(lang, "risk_water", when=when, mm=round(f["deficit_mm"])))
            if f["frost"] < 0.8:
                risks.append(t(lang, "risk_frost", when=when, days=round(f["frost_days"])))
            if f["waterlog"] < 0.85:
                risks.append(t(lang, "risk_waterlog", when=when))
        no_market = [cid for cid in uniq if prefs.get("market", {}).get(cid) == "no"]
        if no_market:
            risks.append(t(lang, "risk_no_market", crops=_crop_list(no_market, crops, lang)))
        if new_crops:
            risks.append(t(lang, "risk_new", crops=_crop_list(new_crops, crops, lang)))
            for cid in new_crops[:3]:
                risks.append(t(lang, "risk_pests", crop=crop_name(crops, cid, lang), pests=crops[cid]["pests"]))
        if any(crops[cid]["group"] == "forage" and crops[cid]["duration_m"] >= 12 for cid in uniq):
            risks.append(t(lang, "risk_perennial"))
        if "heat_days" in facts.get("trend_concern_keys", []):
            hot = [p["crop"] for p, f in zip(strategy["plantings"], strategy["fits"]) if f["heat"] < 0.9]
            if hot:
                risks.append(t(lang, "risk_heat_trend", crops=_crop_list(hot, crops, lang)))
        if "onset_doy" in facts.get("trend_concern_keys", []):
            risks.append(t(lang, "risk_onset_trend"))

    # water the farmer actually has
    cap = prefs.get("water_mm")
    if cap is not None and num["irrigation_need_mm_yr"] > cap + 30 and prefs.get("irrigation", 0) > 0:
        risks.append(t(lang, "risk_irrigation", mm=num["irrigation_need_mm_yr"]))

    if robustness and robustness.get("by_type"):
        ok = [x for x in robustness["by_type"] if x["climate_fit"] >= 60]
        robustness["summary"] = t(lang, "robust_summary", ok=len(ok), n=len(robustness["by_type"]))
        worst = min(robustness["by_type"], key=lambda x: x["climate_fit"])
        if worst["climate_fit"] < 60:
            risks.append(t(lang, "risk_weak_year", name=worst["name"], pct=round(worst["share"] * 100),
                           fit=round(worst["climate_fit"])))

    if (facts.get("events") or {}).get("events"):
        evs = facts["events"]
        ev("ev_events", "NASA EONET", n=len(evs["events"]), km=evs["radius_km"], years=evs["years"],
           title=evs["events"][0]["title"])
    if facts.get("soil_from_test"):
        ev("ev_soiltest", "Your soil test")
    if facts.get("lapse"):
        lp = facts["lapse"]
        ev("ev_lapse", "SRTM 30 m + NASA POWER", shift=f"{lp['shift_c']:+.1f}", field=lp["field_m"], grid=lp["grid_m"])

    # ---- information gaps (always shown) ----
    layers = facts.get("layers", {})
    if facts.get("data_mode") == "demo":
        gaps.append(t(lang, "gap_demo"))
    if facts.get("no_rainfed_season"):
        gaps.append(t(lang, "gap_norain"))
    gaps.append(t(lang, "gap_power"))
    gaps.append(t(lang, "gap_smap") if layers.get("smap", {}).get("available") else t(lang, "gap_nosmap"))
    if layers.get("grace", {}).get("available"):
        gaps.append(t(lang, "gap_grace"))
    if layers.get("ecostress", {}).get("status") in ("queued", "pending", "processing"):
        gaps.append(t(lang, "gap_eco_pending"))
    gaps.append(t(lang, "gap_traits"))
    gaps.append(t(lang, "gap_pests"))
    if not facts.get("soil_from_test"):
        gaps.append(t(lang, "gap_soilmodel"))

    ask.append(t(lang, "ask_dates"))
    if new_crops:
        ask.append(t(lang, "ask_seed", crops=_crop_list(new_crops, crops, lang)))
    unsure = [cid for cid in uniq if prefs.get("market", {}).get(cid) in (None, "unsure")]
    if unsure and not strategy.get("is_current"):
        ask.append(t(lang, "ask_market", crops=_crop_list(unsure[:3], crops, lang)))
    if legumes:
        ask.append(t(lang, "ask_inoculant"))
    if not facts.get("soil_from_test"):
        ask.append(t(lang, "ask_soiltest"))

    # ---- confidence ----
    points, reasons = 3.0, []
    agree = facts.get("rain_agreement")
    if agree and agree.get("verdict") == "poor":
        points -= 1
        reasons.append(t(lang, "c_disagree"))
    elif agree and agree.get("verdict") == "good":
        reasons.append(t(lang, "c_agree"))
    if facts.get("record_years", 0) < 20:
        points -= 0.5
        reasons.append(t(lang, "c_short"))
    if len(new_crops) >= 2:
        points -= 0.75
        reasons.append(t(lang, "c_new_n", n=len(new_crops)))
    elif len(new_crops) == 1:
        points -= 0.25
    if strategy["fits"] and min(f["fit"] for f in strategy["fits"]) < 0.6:
        points -= 0.75
        reasons.append(t(lang, "c_limit"))
    if robustness and robustness.get("by_type") and min(x["climate_fit"] for x in robustness["by_type"]) < 55:
        points -= 0.5
        reasons.append(t(lang, "c_sensitive"))
    if not (layers.get("ndvi", {}).get("available") or layers.get("landsat", {}).get("available")):
        points -= 0.25
        reasons.append(t(lang, "c_nondvi"))
    if facts.get("soil_from_test"):
        points += 0.25
        reasons.append(t(lang, "c_soiltest"))
    if facts.get("esi_agrees"):
        points += 0.25
        reasons.append(t(lang, "c_eco"))
    if facts.get("data_mode") == "demo":
        reasons.insert(0, t(lang, "c_demo"))
    level = "high" if points >= 2.5 else "medium" if points >= 1.5 else "low"

    if strategy.get("is_current"):
        summary = t(lang, "summary_current")
    else:
        best = [k for k in sorted(CRITERIA, key=lambda k: -delta[k])[:2] if delta[k] > 0]
        summary = t(lang, "summary", seq=strategy["sequence"], gains=join(lang, [L(k) for k in best]) or t(lang, "balance"),
                    watch=risks[0] if risks else t(lang, "summary_nothing"))

    if strategy.get("is_current"):
        farmer = {"good": [], "watch": (why[1:3] + risks)[:3], "ask": ask[:3]}
    else:
        farmer = {"good": benefits[:3], "watch": risks[:3], "ask": ask[:3]}
    return {"why": why, "evidence": evidence, "benefits": benefits, "risks": risks[:8], "gaps": gaps,
            "ask_expert": ask, "confidence": {"level": level, "points": round(points, 2), "reasons": reasons},
            "summary": summary, "new_crops": new_crops, "farmer": farmer}
