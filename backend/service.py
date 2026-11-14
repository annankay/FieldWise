"""Orchestration: loads a field's data once, then answers profile / strategy / score / what-if requests."""
from __future__ import annotations

import logging
import threading
import time
from collections import OrderedDict
from functools import lru_cache

import numpy as np
import pandas as pd

from backend import config
from backend.engine.crops import CropFitter
from backend.engine.explain import crop_name, describe, explain
from backend.engine.farming_systems import climate_zone, default_rotation
from backend.engine.scoring import CRITERIA, DEFAULT_WEIGHTS, Context, compact, normalize_plantings, score_rotation, total_score
from backend.engine.strategies import _norm, build_strategies, calendar_strip
from backend.engine.vulnerability import crop_risk_calendar
from backend.fetchers import builder, cache, eonet
from backend.fetchers.soilgrids import texture_class
from backend.i18n import join, months_text, t, trend_sentence
from backend.ml.phenology import detect_seasons
from backend.ml.stress import StressModel
from backend.ml.yeartypes import annual_features, cluster_years
from backend.pipeline import fieldgrid, harmonize, seasons, trends
from backend.pipeline.features import MONTH_NAMES, apply_scenario, build_climate

log = logging.getLogger("fieldwise")

WATER_LEVELS = {"none": (0.0, 0), "little": (0.25, 100), "some": (0.6, 300), "full": (1.0, 1000)}
MARKET_LEVELS = {"good": 0.95, "low": 0.55, "no": 0.05}


def _scenario_key(sc: dict | None) -> tuple:
    sc = sc or {}
    return (round(float(sc.get("rain_pct", 0)), 1), round(float(sc.get("temp_c", 0)), 2),
            round(float(sc.get("storm_pct", 0)), 1))


def _soil_from_test(base: dict, test: dict | None) -> tuple[dict, bool]:
    if not test:
        return base, False
    soil = dict(base)
    used = False
    for key in ("ph", "soc", "clay", "sand", "silt"):
        v = test.get(key)
        if v is None or v == "":
            continue
        try:
            soil[key] = float(v)
            used = True
        except (TypeError, ValueError):
            continue
    if used:
        soil["source"] = "Farmer's soil test"
        soil["texture"] = texture_class(soil)
    return soil, used


class SiteAnalysis:
    def __init__(self, site_id: str):
        data = cache.load(site_id)
        self.site_id = site_id
        self.meta = data["meta"]
        self.updated = self.meta.get("updated")
        self.daily = data["daily"]
        self.sat = data["sat"]
        self.extras = data.get("extras", {}) or {}
        self.soil = data["soil"] or {}
        self.soil["texture"] = texture_class(self.soil)
        self.dem = data["dem"]
        self.crops = builder.load_crops()
        cfg = {s["id"]: s for s in builder.load_sites_config()}.get(site_id, {})
        self.site_cfg = cfg
        self.market = cfg.get("market", {})
        self.lat, self.lon = self.meta["lat"], self.meta["lon"]
        self.elev = float(self.meta.get("elevation_m") or 0)
        self.lapse = self._lapse_rate_correction()

        self.base = build_climate(self.daily, self.lat, self.elev)
        self.heavy_thr = self.base.heavy_thr
        self.windows = seasons.growing_windows(self.base.clim)
        # the climate is read from this field's own data, not from its latitude
        self.zone = climate_zone(self.base.clim, self.windows)
        self.climate_type = "temperate" if self.zone["key"] == "temperate" else "tropical"
        typical = default_rotation(self.zone, self.windows, CropFitter(self.crops, self.base, self.soil), self.crops)
        self.no_rainfed_season = typical["note"] == "no_rainfed_season"
        self.default_rotation = cfg.get("current_rotation") or typical["rotation"]
        self.default_staple = self.meta.get("staple") or cfg.get("staple") or typical["staple"]
        self.sowing_months = seasons.sowing_opportunities(self.base.clim, self.climate_type)
        self.onset_doy = seasons.onset_search_doy(self.base.clim, self.climate_type)

        self.yearly = trends.annual_series(self.base, self.sat, self.onset_doy)
        window_months = max(self.windows, key=lambda w: w["length"])["months"] if self.windows else []
        onset = self.yearly["onset_doy"] if "onset_doy" in self.yearly else None
        self.year_types = cluster_years(annual_features(self.base, window_months, onset, self.climate_type))

        self.stress = StressModel()
        self.stress_report = self.stress.fit(self.base, self.sat)
        self.unified = harmonize.unified_monthly(self.base, self.sat)
        self.agreement = harmonize.agreement(self.unified)
        self.field = fieldgrid.vulnerability_grid(self.dem, self.lat, self.lon,
                                                  float(self.base.clim["heavy_days"].sum()),
                                                  float(self.base.clim["frost_days"].sum()))
        if self.field and self.extras.get("landsat_grid"):
            g = self.extras["landsat_grid"]
            vals = np.array(g["values"], dtype=float)
            if vals.shape == (self.field["cells"], self.field["cells"]):
                self.field["layers"]["greenness"] = np.round(np.nan_to_num(vals, nan=0), 3).tolist()
                self.field["greenness_period"] = g.get("period")
        # AI season detection: Landsat (30 m) when it has enough history, else MODIS (250 m)
        self.phenology = None
        if self.sat.get("landsat_ndvi") is not None and self.sat["landsat_ndvi"].notna().sum() >= 48:
            self.phenology = detect_seasons(self.sat, "landsat_ndvi")
        if self.phenology is None:
            self.phenology = detect_seasons(self.sat, "ndvi")
        self._climates = {_scenario_key(None): self.base}
        self._type_climates: dict = {}
        self._events = None
        self._events_t = 0.0

    def sowing_months_for(self, prefs: dict) -> list[int]:
        """With irrigation a farmer is not tied to the rains: any month warm enough (and not too hot) opens."""
        months = set(self.sowing_months)
        tmean = self.base.clim["tmean"].to_numpy()
        ok = [m + 1 for m in range(12) if 8 <= tmean[m] <= 32]
        if prefs["irrigation"] >= 0.99 or (self.no_rainfed_season and prefs["irrigation"] > 0):
            months |= set(ok)
        elif prefs["irrigation"] >= 0.5:
            for m in list(self.sowing_months):            # extend each season by a month either side
                months |= {(m - 2) % 12 + 1, m % 12 + 1} & set(ok)
        return sorted(months)

    def _lapse_rate_correction(self) -> dict | None:
        """NASA POWER temperatures describe a ~50 km grid cell at its average height. In hills and
        highlands the field can sit hundreds of metres higher or lower, so we shift temperatures by the
        standard lapse rate (0.65 °C per 100 m) using the SRTM height of the field itself."""
        dem = self.dem or {}
        grid = dem.get("elev")
        if not grid or self.meta.get("data_mode") == "demo":
            return None
        g = np.array(grid, dtype=float)
        field_z = float(np.nanmedian(g[g.shape[0] // 2 - 2: g.shape[0] // 2 + 3, g.shape[1] // 2 - 2: g.shape[1] // 2 + 3]))
        grid_z = float(self.meta.get("power_elevation_m", self.meta.get("elevation_m")) or 0)
        diff = field_z - grid_z
        if abs(diff) < 100 or not np.isfinite(diff):
            return None
        shift = float(np.clip(-0.0065 * diff, -10, 10))
        for col in ("tmax", "tmin", "tmean"):
            if col in self.daily:
                self.daily[col] = self.daily[col] + shift
        self.elev = field_z
        return {"field_m": round(field_z), "grid_m": round(grid_z), "shift_c": round(shift, 2)}

    # ------------------------------------------------------------------ climates
    def climate(self, scenario: dict | None):
        key = _scenario_key(scenario)
        if key not in self._climates:
            if len(self._climates) > 12:
                self._climates = {_scenario_key(None): self.base}
            d = apply_scenario(self.daily, *key)
            self._climates[key] = build_climate(d, self.lat, self.elev, self.heavy_thr, scenario)
        return self._climates[key]

    def type_climate(self, scenario: dict | None, type_id: int):
        key = (_scenario_key(scenario), type_id)
        if key not in self._type_climates:
            ty = next(x for x in self.year_types["types"] if x["id"] == type_id)
            d = apply_scenario(self.daily, *_scenario_key(scenario))
            d = d[d.index.year.isin(ty["years"])]
            self._type_climates[key] = build_climate(d, self.lat, self.elev, self.heavy_thr)
        return self._type_climates[key]

    # ------------------------------------------------------------------ outside events (NASA EONET)
    def events(self) -> dict | None:
        if self.meta.get("data_mode") == "demo":
            return None
        if self._events is not None and time.time() - self._events_t < 6 * 3600:
            return self._events
        try:
            self._events = eonet.nearby_events(self.lat, self.lon, timeout=8)
        except Exception as err:  # noqa: BLE001
            log.info("EONET unavailable: %s", err)
            self._events = None
        self._events_t = time.time()
        return self._events

    # ------------------------------------------------------------------ facts used by explanations
    def esi_months(self) -> list[int]:
        if "eco_esi" not in self.sat or self.sat["eco_esi"].notna().sum() < 12:
            return []
        clim = self.sat["eco_esi"].groupby(self.sat.index.month).mean()
        return [int(m) for m, v in clim.items() if v < 0.6]

    def facts(self, climate, soil: dict, soil_from_test: bool) -> dict:
        c = climate.clim
        eros = c["heavy_days"].to_numpy()
        heavy = [int(m) + 1 for m in np.argsort(-eros)[:3] if eros[m] >= 0.3]
        cards = trends.trend_cards(self.yearly, self._sources())
        ph = self.phenology
        dry_months = [m for m in range(1, 13) if c.loc[m, "ratio"] < 0.5]
        esi = self.esi_months()
        return {
            "site_name": self.meta["name"], "climate_type": self.climate_type,
            "data_mode": self.meta.get("data_mode"), "layers": self.meta.get("layers", {}),
            "heavy_months": heavy, "heavy_days_per_year": float(eros.sum()), "heavy_thr": self.heavy_thr,
            "dry_months": dry_months,
            "heat_months": [m for m in range(1, 13) if c.loc[m, "heat_days"] >= 4],
            "bare_ndvi_months": ph["ai_bare_months"] if ph else None,
            "bare_source": ("Landsat 30 m" if ph and ph["source"] == "landsat_ndvi" else "MODIS 250 m") + " + AI",
            "esi_dry_months": esi, "esi_agrees": bool(esi and set(esi) & set(dry_months)),
            "trend_concern_keys": [cd["key"] for cd in cards if cd["concern"]],
            "slope_pct": self.field["summary"]["mean_slope_pct"] if self.field else None,
            "high_erosion_share": self.field["summary"]["high_erosion_share"] if self.field else None,
            "soil": soil, "soil_from_test": soil_from_test, "rain_agreement": self.agreement.get("rain"),
            "record_years": len(climate.years), "gedi": self.extras.get("gedi"), "events": self.events(),
            "lapse": self.lapse, "no_rainfed_season": self.no_rainfed_season,
        }

    def _sources(self) -> dict:
        return {"ndvi": "MODIS NDVI", "smap_rootzone": "SMAP L4", "grace_lwe": "GRACE/GRACE-FO",
                "onset_doy": "NASA POWER daily rain"}

    # ------------------------------------------------------------------ profile
    def profile(self, scenario: dict | None = None, lang: str = "en") -> dict:
        climate = self.climate(scenario)
        stress_prob = self.stress.stress_probability(climate, self.sat) if self.stress_report else None
        current = normalize_plantings(self.default_rotation, self.crops) if self.default_rotation else []
        calendar = seasons.risk_calendar(climate, self.sat, current, self.crops, stress_prob)
        if self.phenology:   # replace the rule-based bare row with the AI one
            calendar = [r for r in calendar if r["key"] != "bare"]
            p = np.array(self.phenology["ai_bare_prob"])
            calendar.insert(len(calendar) - 1, {
                "key": "bare", "label": "Field looks bare (AI on satellite greenness)",
                "source": ("Landsat 30 m" if self.phenology["source"] == "landsat_ndvi" else "MODIS 250 m") + " + Gaussian mixture",
                "cells": [{"level": int(3 if v >= 0.75 else 2 if v >= 0.5 else 1 if v >= 0.25 else 0),
                           "value": round(float(v), 3), "text": f"bare in {v * 100:.0f}% of years"} for v in p]})
        esi = self.sat.get("eco_esi")
        if esi is not None and esi.notna().sum() >= 12:
            clim = esi.groupby(self.sat.index.month).mean().reindex(range(1, 13))
            calendar.insert(len(calendar) - 1, {
                "key": "esi", "label": "Plants short of water (ECOSTRESS)", "source": "ECOSTRESS ESI 70 m",
                "cells": [{"level": None if pd.isna(v) else int(3 if v < 0.4 else 2 if v < 0.6 else 1 if v < 0.8 else 0),
                           "value": None if pd.isna(v) else round(float(v), 3),
                           "text": "no data" if pd.isna(v) else f"stress index {v:.2f}"} for v in clim.to_numpy()]})
        c = climate.clim
        cards = self._cards(lang)
        charts = harmonize.chart_series(self.unified)
        charts["annual"] = {"years": [int(y) for y in self.yearly.index],
                            "rain": [round(float(v), 1) for v in self.yearly["rain"]],
                            "tmax": [round(float(v), 2) for v in self.yearly["tmax"]],
                            "heat_days": [int(v) for v in self.yearly["heat_days"]]}
        fitter = CropFitter(self.crops, climate, self.soil)
        explorer = fitter.suitability_table(self.climate_type)
        for row in explorer:
            row["local_name"] = crop_name(self.crops, row["crop"], lang)
            row["icon"] = self.crops[row["crop"]].get("icon", "🌱")
        layers = self.meta.get("layers", {})
        return {
            "site": {k: self.meta.get(k) for k in ("id", "name", "lat", "lon", "climate", "farming_system",
                                                     "staple", "data_mode", "data_note", "elevation_m",
                                                     "satellite_status", "updated", "reference")},
            "layers": layers, "soil": self.soil, "headline": self._headline(climate, cards, lang),
            "calendar": calendar, "windows": self.windows, "sowing_months": self.sowing_months, "months": MONTH_NAMES,
            "trends": cards, "charts": charts, "agreement": self.agreement, "year_types": self.year_types,
            "stress": ({**self.stress_report, "predicted_stress_prob": stress_prob} if self.stress_report else None),
            "phenology": self.phenology, "field": self.field, "crop_explorer": explorer,
            "gedi": self.extras.get("gedi"), "events": self.events(),
            "ecostress_status": layers.get("ecostress", {}).get("status"),
            "heavy_thr": round(self.heavy_thr, 1), "default_rotation": self.default_rotation,
            "staple": self.default_staple, "zone": self.zone, "no_rainfed_season": self.no_rainfed_season,
            "lapse": self.lapse,
            "scenario": dict(zip(("rain_pct", "temp_c", "storm_pct"), _scenario_key(scenario))),
            "criteria": CRITERIA, "record": f"{min(climate.years)}–{max(climate.years)}",
            "summary_numbers": {"annual_rain_mm": round(float(c["rain"].sum())),
                                "hot_days_yr": round(float(c["heat_days"].sum())),
                                "frost_days_yr": round(float(c["frost_days"].sum())),
                                "dry_months": int((c["ratio"] < 0.5).sum())},
        }

    def _cards(self, lang: str) -> list[dict]:
        cards = trends.trend_cards(self.yearly, self._sources())
        for cd in cards:
            cd["text"] = trend_sentence(lang, cd)
        return cards

    def _headline(self, climate, cards, lang) -> list[str]:
        c = climate.clim
        win = join(lang, [months_text(lang, [w["start"]]) + "–" + months_text(lang, [w["end"]]) for w in self.windows])
        out = [t(lang, "headline_rain", mm=round(float(c["rain"].sum())), windows=win or t(lang, "headline_none"))]
        concerns = [cd for cd in cards if cd["concern"]]
        if concerns:
            items = "; ".join(cd["text"][0].lower() + cd["text"][1:] for cd in concerns[:3])
            out.append(t(lang, "headline_changing", items=items))
        if self.phenology and self.phenology["ai_bare_months"]:
            out.append(t(lang, "headline_bare", months=months_text(lang, self.phenology["ai_bare_months"])))
        return out

    # ------------------------------------------------------------------ strategies
    def _prefs(self, constraints: dict) -> dict:
        level = constraints.get("water") or ("full" if constraints.get("irrigation") is True else "none")
        frac, mm = WATER_LEVELS.get(level, WATER_LEVELS["none"])
        return {"irrigation": frac, "water_mm": mm, "water_level": level,
                "market": {k: v for k, v in (constraints.get("market") or {}).items() if k in self.crops}}

    def _context(self, climate, constraints: dict, staple: str | None, soil: dict) -> Context:
        prefs = self._prefs(constraints)
        fitter = CropFitter(self.crops, climate, soil, irrigation=prefs["irrigation"])
        c = climate.clim
        erosivity = c["heavy_days"].to_numpy() + c["rain"].to_numpy() / 100
        market = dict(self.market)
        for cid, level in prefs["market"].items():
            if level in MARKET_LEVELS:
                market[cid] = MARKET_LEVELS[level]
        current = constraints.get("_current") or []
        # the staple's MAIN season = its first sowing in each year of the farmer's current rotation
        first: dict[int, int] = {}
        for p in current:
            if p.get("crop") == staple:
                y = int(p.get("year", 1))
                first[y] = min(first.get(y, 13), int(p["sow_month"]))
        months = tuple(sorted(set(first.values())))
        return Context(fitter, self.crops, market, erosivity, staple, bool(constraints.get("keep_staple", True)),
                       staple_months=months)

    def robustness(self, plantings: list[dict], ctx: Context, scenario: dict | None, weights: dict, soil: dict,
                   irrigation: float) -> dict:
        out = []
        for ty in self.year_types.get("types", []):
            cl = self.type_climate(scenario, ty["id"])
            f = CropFitter(self.crops, cl, soil, irrigation=irrigation)
            r = score_rotation(plantings, ctx, fitter=f)
            out.append({"id": ty["id"], "name": ty["name"], "share": ty["share"],
                        "climate_fit": r["scores"]["climate_fit"], "water": r["scores"]["water"],
                        "total": total_score(r["scores"], weights, r["numbers"])})
        totals = [x["total"] for x in out]
        return {"by_type": out, "range": [round(min(totals)), round(max(totals))] if totals else None}

    def _common(self, body: dict):
        scenario = body.get("scenario")
        constraints = {"equipment": "tractor" if self.climate_type == "temperate" else "hand",
                       "keep_staple": True, **(body.get("constraints") or {})}
        staple = constraints.get("staple") or self.default_staple
        if staple and staple in self.crops:
            # a staple the farmer cannot grow (excluded, or needs machinery they don't have) can't be "kept"
            crop = self.crops[staple]
            if staple in constraints.get("avoid", []) or (
                    not crop["hand_ok"] and constraints.get("equipment") in ("hand", "animal")):
                constraints["keep_staple"] = False
                constraints["staple_unavailable"] = True
        weights = {**DEFAULT_WEIGHTS, **(body.get("priorities") or {})}
        soil, from_test = _soil_from_test(self.soil, constraints.get("soil_test"))
        constraints["_current"] = [p for p in (body.get("current") or self.default_rotation) if p.get("crop") in self.crops]
        climate = self.climate(scenario)
        ctx = self._context(climate, constraints, staple, soil)
        return scenario, constraints, staple, weights, soil, from_test, climate, ctx

    def _decorate(self, s: dict, cur: dict, ctx, scenario, weights, soil, prefs, facts, lang, climate):
        plantings = [dict(p) for p in s["plantings"]]
        s["sequence"] = describe(plantings, self.crops, lang)
        s["compact"] = compact(plantings)
        for p in s["plantings"]:
            p["local_name"] = crop_name(self.crops, p["crop"], lang)
            p["icon"] = self.crops[p["crop"]].get("icon", "🌱")
        s["robustness"] = self.robustness(plantings, ctx, scenario, _norm(weights), soil, prefs["irrigation"])
        s["explanation"] = explain(s, cur, facts, self.crops, s["robustness"], prefs, lang)
        s["crop_risk"] = crop_risk_calendar(plantings, self.crops, climate)
        return s

    def strategies(self, body: dict) -> dict:
        lang = body.get("lang", "en")
        scenario, constraints, staple, weights, soil, from_test, climate, ctx = self._common(body)
        prefs = self._prefs(constraints)
        current = [p for p in (body.get("current") or self.default_rotation) if p.get("crop") in self.crops]
        res = build_strategies(current, ctx, weights, self.sowing_months_for(prefs), self.climate_type, constraints)
        facts = self.facts(climate, soil, from_test)
        cur = res["strategies"][0]
        for s in res["strategies"]:
            self._decorate(s, cur, ctx, scenario, weights, soil, prefs, facts, lang, climate)
        res["facts"] = {k: v for k, v in facts.items() if k not in ("layers", "soil", "events", "gedi")}
        res["constraints"] = {k: v for k, v in constraints.items() if not k.startswith("_")}
        res["staple"] = staple
        res["soil_used"] = soil
        return res

    def score(self, body: dict) -> dict:
        """Score one farmer-edited plan against the current rotation (the 'make my own plan' tool)."""
        lang = body.get("lang", "en")
        scenario, constraints, staple, weights, soil, from_test, climate, ctx = self._common(body)
        prefs = self._prefs(constraints)
        nw = _norm(weights)
        plan = normalize_plantings([p for p in body.get("plan", []) if p.get("crop") in self.crops], self.crops)
        current = normalize_plantings([p for p in (body.get("current") or self.default_rotation)
                                       if p.get("crop") in self.crops], self.crops)

        def pack(pl, sid, name, is_current):
            r = score_rotation(pl, ctx)
            cal = calendar_strip(pl, ctx.cycle)
            return {"id": sid, "name": name, "is_current": is_current, "tagline": "",
                    "plantings": [dict(p) for p in pl], "scores": r["scores"], "numbers": r["numbers"],
                    "coverage": r["coverage"], "fits": r["fits"], "calendar": cal,
                    "total": total_score(r["scores"], nw, r["numbers"])}
        cur = pack(current, "current", "Your current rotation", True)
        mine = pack(plan, "custom", "My plan", False)
        mine["delta_vs_current"] = {k: round(mine["scores"][k] - cur["scores"][k], 1) for k in CRITERIA}
        facts = self.facts(climate, soil, from_test)
        self._decorate(mine, cur, ctx, scenario, weights, soil, prefs, facts, lang, climate)
        return {"plan": mine, "current_total": cur["total"]}

    def whatif(self, body: dict) -> dict:
        constraints = {"keep_staple": True, **(body.get("constraints") or {})}
        staple = constraints.get("staple") or self.default_staple
        weights = _norm({**DEFAULT_WEIGHTS, **(body.get("priorities") or {})})
        soil, _ = _soil_from_test(self.soil, constraints.get("soil_test"))
        base_ctx = self._context(self.climate(None), constraints, staple, soil)
        sc = body.get("scenario") or {}
        sc_climate = self.climate(sc)
        sc_ctx = self._context(sc_climate, constraints, staple, soil)
        rows = []
        for s in body.get("strategies", [])[:8]:
            pl = normalize_plantings([p for p in s.get("plantings", []) if p.get("crop") in self.crops], self.crops)
            b = score_rotation(pl, base_ctx)
            n = score_rotation(pl, sc_ctx)
            rows.append({"id": s.get("id"), "name": s.get("name"),
                         "base_total": total_score(b["scores"], weights, b["numbers"]),
                         "scenario_total": total_score(n["scores"], weights, n["numbers"]),
                         "base_scores": b["scores"], "scenario_scores": n["scores"],
                         "base_numbers": b["numbers"], "scenario_numbers": n["numbers"], "fits": n["fits"]})
        for key in ("base_total", "scenario_total"):
            for rank, r in enumerate(sorted(rows, key=lambda r: -r[key]), start=1):
                r[key.replace("total", "rank")] = rank
        b, n = self.base.clim, sc_climate.clim
        climate_change = {
            "annual_rain_mm": [round(float(b["rain"].sum())), round(float(n["rain"].sum()))],
            "annual_et0_mm": [round(float(b["et0"].sum())), round(float(n["et0"].sum()))],
            "heat_days_yr": [round(float(b["heat_days"].sum()), 1), round(float(n["heat_days"].sum()), 1)],
            "frost_days_yr": [round(float(b["frost_days"].sum()), 1), round(float(n["frost_days"].sum()), 1)],
            "dry_months": [int((b["ratio"] < 0.5).sum()), int((n["ratio"] < 0.5).sum())],
            "heavy_days_yr": [round(float(b["heavy_days"].sum()), 1), round(float(n["heavy_days"].sum()), 1)],
        }
        stress = None
        if self.stress_report:
            stress = {"base": self.stress.stress_probability(self.base, self.sat),
                      "scenario": self.stress.stress_probability(sc_climate, self.sat)}
        return {"rows": rows, "climate_change": climate_change, "stress": stress,
                "scenario": dict(zip(("rain_pct", "temp_c", "storm_pct"), _scenario_key(sc))),
                "heat_by_month": {"base": [round(float(v), 2) for v in b["heat_days"]],
                                  "scenario": [round(float(v), 2) for v in n["heat_days"]]},
                "ratio_by_month": {"base": [round(float(v), 2) for v in b["ratio"]],
                                   "scenario": [round(float(v), 2) for v in n["ratio"]]}}

    def fuse_gauge(self, csv_text: str) -> dict:
        from backend.pipeline.fusion import fuse_rain, parse_gauge_csv
        return fuse_rain(self.unified["rain"], parse_gauge_csv(csv_text))


# ---------------------------------------------------------------------- registry (bounded, refreshes on new data)
_sites: OrderedDict[str, SiteAnalysis] = OrderedDict()
_lock = threading.Lock()
_eco_checked: dict[str, float] = {}


def _maybe_refresh_ecostress(site_id: str, meta: dict) -> None:
    status = meta.get("layers", {}).get("ecostress", {}).get("status")
    if status not in ("queued", "pending", "processing") or time.time() - _eco_checked.get(site_id, 0) < 600:
        return
    _eco_checked[site_id] = time.time()

    def run():
        try:
            if builder.refresh_ecostress(site_id, log=log.info):
                forget_site(site_id)
        except Exception as err:  # noqa: BLE001
            log.info("ECOSTRESS refresh failed for %s: %s", site_id, err)
    threading.Thread(target=run, daemon=True).start()


def get_site(site_id: str) -> SiteAnalysis:
    meta = cache.read_meta(site_id)
    if meta.get("data_mode") == "demo" and not config.DEMO_MODE:
        raise FileNotFoundError("development data is disabled")
    _maybe_refresh_ecostress(site_id, meta)
    with _lock:
        s = _sites.get(site_id)
        if s is not None and s.updated == meta.get("updated"):
            _sites.move_to_end(site_id)
            return s
    built = SiteAnalysis(site_id)          # heavy work outside the global lock
    with _lock:
        _sites[site_id] = built
        _sites.move_to_end(site_id)
        while len(_sites) > config.MAX_SITES_IN_MEMORY:
            _sites.popitem(last=False)
    return built


def forget_site(site_id: str) -> None:
    with _lock:
        _sites.pop(site_id, None)


def reference_sites() -> list[dict]:
    """Example fields shown to everyone (only reference sites; farmers' own fields stay private)."""
    builder.ensure_demo_caches()
    cfg = {s["id"]: s for s in builder.load_sites_config()}
    out = []
    for meta in cache.list_cached():
        if meta["id"] not in cfg:
            continue
        if meta.get("data_mode") == "demo" and not config.DEMO_MODE:
            continue
        base = cfg[meta["id"]]
        out.append({"id": meta["id"], "name": meta["name"], "lat": meta["lat"], "lon": meta["lon"],
                    "climate": meta.get("climate"), "data_mode": meta.get("data_mode"),
                    "farming_system": meta.get("farming_system") or base.get("farming_system")})
    return sorted(out, key=lambda s: s["name"])


def site_summary(site_id: str) -> dict:
    meta = cache.read_meta(site_id)
    return {"id": meta.get("id"), "name": meta.get("name"), "lat": meta.get("lat"), "lon": meta.get("lon"),
            "climate": meta.get("climate"), "data_mode": meta.get("data_mode"),
            "satellite_status": meta.get("satellite_status"), "updated": meta.get("updated"),
            "layers": {k: {"status": v.get("status"), "available": v.get("available"), "label": v.get("label")}
                       for k, v in meta.get("layers", {}).items()}}


@lru_cache(maxsize=1)
def crops_public() -> list[dict]:
    from backend.engine.scoring import INTERCROPS
    return [{**c, "companions": INTERCROPS.get(c["id"], [])} for c in builder.load_crops().values()]
