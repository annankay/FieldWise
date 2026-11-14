"""Builds a field's data store from real NASA sources, in phases so the farmer can start quickly.

  Phase 1 (~20-60 s): NASA POWER 35-year daily weather + SoilGrids  -> field is usable
  Phase 2 (1-4 min):  Earth Engine: GPM, SMAP, MODIS NDVI & ET, GRACE, SRTM, Landsat, GEDI
                      (each layer is saved as soon as it arrives)
  Phase 3 (async):    ECOSTRESS via AppEEARS is queued at NASA and collected later

Synthetic data (build_demo) exists ONLY for development and automated tests; production never shows it.
"""
from __future__ import annotations

import json
import secrets
from datetime import datetime, timezone
from typing import Callable

import numpy as np
import pandas as pd

from backend import config
from backend.fetchers import appeears, cache, gee, power, soilgrids

Progress = Callable[[dict], None]

POWER_LAYER = {"available": True, "label": "NASA POWER daily weather", "resolution": "0.5° x 0.625° (~50 km)",
               "units": "°C, mm, %, m/s, MJ/m²", "period": f"{config.START_YEAR}-{config.END_YEAR}"}
EXTRA_LAYERS = {
    "landsat": {"label": "Landsat 8/9 NDVI", "resolution": "30 m"},
    "gedi": {"label": "GEDI L4A above-ground biomass", "resolution": "25 m footprints"},
    "ecostress": {"label": "ECOSTRESS ET & evaporative stress (ESI)", "resolution": "70 m"},
    "srtm": {"label": "SRTM elevation", "resolution": "30 m"},
    "soil": {"label": "SoilGrids topsoil", "resolution": "250 m"},
}


def load_sites_config() -> list[dict]:
    return json.loads((config.DATA_DIR / "sites.json").read_text(encoding="utf-8"))["sites"]


def load_crops() -> dict:
    data = json.loads((config.DATA_DIR / "crops.json").read_text(encoding="utf-8"))
    return {c["id"]: c for c in data["crops"]}


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def new_field_id() -> str:
    """Unguessable id so one farmer cannot browse another farmer's field."""
    return "f-" + secrets.token_hex(6)


def gee_ready() -> bool:
    return gee.available() and bool(config.GEE_PROJECT)


def _init_gee() -> None:
    gee.initialize(config.GEE_PROJECT, config.GEE_SERVICE_ACCOUNT, config.GEE_KEY_FILE)


def _pending_layers(use_gee: bool) -> dict:
    layers = {}
    for key, cfg in gee.LAYERS.items():
        layers[key] = {"available": False, "status": "pending" if use_gee else "off", "label": cfg["label"],
                       "resolution": cfg["resolution"], "units": cfg["units"]}
    for key in ("landsat", "gedi", "srtm"):
        layers[key] = {"available": False, "status": "pending" if use_gee else "off", **EXTRA_LAYERS[key]}
    eco_on = bool(config.EARTHDATA_USERNAME and config.EARTHDATA_PASSWORD)
    layers["ecostress"] = {"available": False, "status": "pending" if eco_on else "off", **EXTRA_LAYERS["ecostress"]}
    return layers


# ---------------------------------------------------------------------------------------------- live
def build_live(lat: float, lon: float, name: str, site_id: str | None = None, use_gee: bool = True,
               base: dict | None = None, log: Callable[[str], None] = print,
               progress: Progress | None = None) -> str:
    """Fetch REAL data for one field. Returns the field id once phase 1 is saved; continues phases 2-3."""
    site_id = site_id or new_field_id()
    progress = progress or (lambda _e: None)
    use_gee = use_gee and gee_ready()
    with cache.lock(site_id):
        progress({"stage": "weather", "message": "Downloading 35 years of NASA POWER weather"})
        log(f"[{site_id}] NASA POWER daily {config.START_YEAR}-{config.END_YEAR} ...")
        daily, pinfo = power.fetch_power_daily(lat, lon, config.START_YEAR, config.END_YEAR)

        layers = {"power": dict(POWER_LAYER, status="done"), **_pending_layers(use_gee)}
        soil = {}
        progress({"stage": "soil", "message": "Reading soil data"})
        try:
            soil = soilgrids.fetch_soilgrids(lat, lon)
            layers["soil"] = {**EXTRA_LAYERS["soil"], "available": True, "status": "done"}
        except Exception as err:  # noqa: BLE001
            log(f"  ! SoilGrids unavailable: {err}")
            layers["soil"] = {**EXTRA_LAYERS["soil"], "available": False, "status": "failed", "error": str(err)[:160]}

        base = base or {}
        meta = {"id": site_id, "name": name, "lat": lat, "lon": lon,
                "climate": base.get("climate") or ("tropical" if abs(lat) < 23.5 else "temperate"),
                "farming_system": base.get("farming_system", ""), "staple": base.get("staple"),
                "elevation_m": pinfo.get("elevation_m") or 0, "power_elevation_m": pinfo.get("elevation_m") or 0,
                "data_mode": "live",
                "layers": layers, "created": _now(), "updated": _now(),
                "reference": bool(base), "satellite_status": "loading" if use_gee else "off"}
        cache.save(site_id, meta, daily, None, soil, {}, {})
    progress({"stage": "ready", "site_id": site_id, "message": "Weather and soil ready"})

    if use_gee:
        fetch_satellite(site_id, lat, lon, log=log, progress=progress)
    submit_ecostress(site_id, lat, lon, name, log=log)
    cache.update(site_id, meta={"updated": _now()})
    progress({"stage": "done", "site_id": site_id, "message": "All available NASA layers loaded"})
    log(f"[{site_id}] saved to {cache.site_dir(site_id)}")
    return site_id


def fetch_satellite(site_id: str, lat: float, lon: float, log: Callable[[str], None] = print,
                    progress: Progress | None = None) -> None:
    progress = progress or (lambda _e: None)
    try:
        _init_gee()
    except Exception as err:  # noqa: BLE001
        log(f"  ! Earth Engine unavailable: {err}")
        cache.update(site_id, meta={"satellite_status": "failed", "satellite_error": str(err)[:200]})
        return
    steps = list(gee.LAYERS.items())
    total = len(steps) + 3
    done = 0
    for key, cfg in steps:
        done += 1
        progress({"stage": "satellite", "done": done, "total": total, "message": cfg["label"]})
        try:
            df, lmeta = gee.fetch_satellite_layers(lat, lon, config.END_YEAR, log=log, only=[key])
            if not lmeta.get(key, {}).get("available"):
                raise RuntimeError(lmeta.get(key, {}).get("error", "no data"))
            cache.update(site_id, sat=df, meta={"layers": {key: {**lmeta[key], "status": "done"}}})
        except Exception as err:  # noqa: BLE001
            log(f"  ! {cfg['label']} unavailable: {err}")
            cache.update(site_id, meta={"layers": {key: {"available": False, "status": "failed", "label": cfg["label"],
                                                         "resolution": cfg["resolution"], "error": str(err)[:160]}}})
    done += 1
    progress({"stage": "satellite", "done": done, "total": total, "message": "SRTM elevation (30 m)"})
    try:
        dem = gee.fetch_dem_grid(lat, lon, config.FIELD_GRID_CELLS)
        cache.update(site_id, dem=dem, meta={"layers": {"srtm": {**EXTRA_LAYERS["srtm"], "available": True, "status": "done"}}})
    except Exception as err:  # noqa: BLE001
        log(f"  ! SRTM unavailable: {err}")
        cache.update(site_id, meta={"layers": {"srtm": {**EXTRA_LAYERS["srtm"], "available": False, "status": "failed"}}})
    done += 1
    progress({"stage": "satellite", "done": done, "total": total, "message": "Landsat field greenness (30 m)"})
    try:
        series, grid, lmeta = gee.fetch_landsat(lat, lon, config.END_YEAR, config.FIELD_GRID_CELLS, log=log)
        cache.update(site_id, sat=series.to_frame("landsat_ndvi"), extras={"landsat_grid": grid},
                     meta={"layers": {"landsat": {**lmeta, "status": "done"}}})
    except Exception as err:  # noqa: BLE001
        log(f"  ! Landsat unavailable: {err}")
        cache.update(site_id, meta={"layers": {"landsat": {**EXTRA_LAYERS["landsat"], "available": False, "status": "failed"}}})
    done += 1
    progress({"stage": "satellite", "done": done, "total": total, "message": "GEDI biomass"})
    try:
        g = gee.fetch_gedi_biomass(lat, lon)
        cache.update(site_id, extras={"gedi": g}, meta={"layers": {"gedi": {**EXTRA_LAYERS["gedi"],
                                                                              "available": g["available"], "status": "done"}}})
    except Exception as err:  # noqa: BLE001
        log(f"  ! GEDI unavailable: {err}")
        cache.update(site_id, meta={"layers": {"gedi": {**EXTRA_LAYERS["gedi"], "available": False, "status": "failed"}}})
    cache.update(site_id, meta={"satellite_status": "done", "updated": _now()})


# ---------------------------------------------------------------------------------------------- ECOSTRESS
def submit_ecostress(site_id: str, lat: float, lon: float, name: str, log: Callable[[str], None] = print) -> None:
    if not (config.EARTHDATA_USERNAME and config.EARTHDATA_PASSWORD):
        return
    try:
        client = appeears.AppEEARS(config.EARTHDATA_USERNAME, config.EARTHDATA_PASSWORD)
        task = client.submit(lat, lon, name)
        cache.update(site_id, extras={"ecostress_task": task},
                     meta={"layers": {"ecostress": {**EXTRA_LAYERS["ecostress"], "available": False, "status": "queued"}}})
        log(f"  ECOSTRESS request queued at NASA AppEEARS (task {task['task_id']})")
    except Exception as err:  # noqa: BLE001
        log(f"  ! ECOSTRESS request failed: {err}")
        cache.update(site_id, meta={"layers": {"ecostress": {**EXTRA_LAYERS["ecostress"], "available": False,
                                                             "status": "failed", "error": str(err)[:160]}}})


def refresh_ecostress(site_id: str, log: Callable[[str], None] = print) -> bool:
    """Collect a finished ECOSTRESS task. Returns True when new data was stored."""
    extras = cache.load(site_id).get("extras", {})
    task = extras.get("ecostress_task")
    if not task or task.get("status") == "done" or not config.EARTHDATA_USERNAME:
        return False
    client = appeears.AppEEARS(config.EARTHDATA_USERNAME, config.EARTHDATA_PASSWORD, timeout=30)
    status = client.status(task["task_id"])
    if status != "done":
        cache.update(site_id, extras={"ecostress_task": {**task, "status": status}})
        return False
    df = client.download(task["task_id"], task["layers"])
    cache.update(site_id, sat=df if not df.empty else None, extras={"ecostress_task": {**task, "status": "done"}},
                 meta={"layers": {"ecostress": {**EXTRA_LAYERS["ecostress"], "available": not df.empty,
                                                "status": "done", "period": "2018-present"}}})
    log(f"[{site_id}] ECOSTRESS collected: {len(df)} months")
    return not df.empty


# ---------------------------------------------------------------------------------------------- dev only
def build_demo(site: dict) -> None:
    """SYNTHETIC data for development and tests. Never used when FIELDWISE_DEMO is off."""
    from backend.fetchers import synthetic
    crops = load_crops()
    daily, sat, soil, dem = synthetic.build_demo_site(site, crops, config.START_YEAR, config.END_YEAR,
                                                      config.FIELD_GRID_CELLS)
    rng = np.random.default_rng(11)
    n = len(sat)
    sat["landsat_ndvi"] = np.clip(sat["ndvi"] * 1.04 + rng.normal(0, 0.03, n), 0.05, 0.9)
    sat.loc[sat.index < pd.Period("2013-04", "M"), "landsat_ndvi"] = np.nan
    stress = np.clip(sat["smap_rootzone"].fillna(sat["smap_rootzone"].mean()) / 0.35, 0.1, 1.2)
    sat["eco_esi"] = np.clip(stress + rng.normal(0, 0.06, n), 0.05, 1.3)
    sat["eco_et"] = np.clip(sat["et_modis"] / 30 + rng.normal(0, 0.2, n), 0, 8)
    sat.loc[sat.index < pd.Period("2018-08", "M"), ["eco_esi", "eco_et"]] = np.nan
    elev = np.array(dem["elev"])
    rel = elev - elev.mean()
    grid = np.clip(0.55 - rel / (np.ptp(elev) + 1e-6) * 0.25 + rng.normal(0, 0.04, elev.shape), 0.1, 0.85)
    extras = {"landsat_grid": {"cells": elev.shape[0], "values": np.round(grid, 3).tolist(),
                               "period": "demo", "source": "synthetic demo"},
              "gedi": {"available": True, "mean": 38.0 if site["climate"] == "tropical" else 12.0,
                       "p25": 20.0, "p75": 55.0, "footprints": 412, "radius_km": 5, "units": "Mg/ha",
                       "label": "GEDI L4A above-ground biomass"}}
    layers = {"power": {**POWER_LAYER, "label": "Daily weather (POWER-like)", "status": "done"}}
    for key, cfg in gee.LAYERS.items():
        layers[key] = {"available": True, "status": "done", "label": cfg["label"], "resolution": cfg["resolution"],
                       "units": cfg["units"], "period": f"{cfg['start'][:4]}-{config.END_YEAR}"}
    for key in ("landsat", "gedi", "ecostress", "srtm", "soil"):
        layers[key] = {**EXTRA_LAYERS[key], "available": True, "status": "done"}
    meta = {k: site[k] for k in ("id", "name", "lat", "lon", "climate", "farming_system", "staple")}
    meta.update({"elevation_m": site["climatology"]["elev"], "data_mode": "demo",
                 "data_note": "SYNTHETIC development data. Not for decisions.", "layers": layers,
                 "created": _now(), "updated": _now(), "reference": True, "satellite_status": "done"})
    cache.save(site["id"], meta, daily, sat, soil, dem, extras)


def ensure_demo_caches() -> None:
    if not config.DEMO_MODE:
        return
    for site in load_sites_config():
        if site.get("climatology") and not cache.exists(site["id"]):   # only sites with test climatology
            build_demo(site)
