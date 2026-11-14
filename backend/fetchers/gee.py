"""Google Earth Engine extraction of NASA satellite layers for one field.

Every layer is aggregated server-side to MONTHLY means (or sums) over a buffer around the field,
so we only download a few hundred numbers instead of terabytes. Each layer is optional: if one
fails (quota, collection renamed, no data) the others still work and the app shows the gap.

Setup (one time):
    pip install earthengine-api
    earthengine authenticate
    set GEE_PROJECT=<your-cloud-project-id> in .env
"""
from __future__ import annotations

import calendar
from typing import Callable

import numpy as np
import pandas as pd

try:
    import ee  # type: ignore
except ImportError:  # the app still runs in POWER-only mode
    ee = None

# Collection ids are tried in order (newest first) because GEE versions datasets over time.
LAYERS = {
    "smap": {
        "ids": ["NASA/SMAP/SPL4SMGP/008", "NASA/SMAP/SPL4SMGP/007"],
        "bands": {"sm_surface": "smap_surface", "sm_rootzone": "smap_rootzone"},
        "start": "2015-04-01", "scale": 11000, "agg": "mean", "factor": 1.0,
        "label": "SMAP L4 soil moisture", "resolution": "9 km", "units": "m³/m³",
    },
    "ndvi": {
        "ids": ["MODIS/061/MOD13Q1", "MODIS/006/MOD13Q1"],
        "bands": {"NDVI": "ndvi"},
        "start": "2000-03-01", "scale": 250, "agg": "mean", "factor": 0.0001,
        "label": "MODIS MOD13Q1 NDVI", "resolution": "250 m, 16-day", "units": "index",
    },
    "gpm": {
        "ids": ["NASA/GPM_L3/IMERG_MONTHLY_V07", "NASA/GPM_L3/IMERG_MONTHLY_V06"],
        "bands": {"precipitation": "gpm_rain"},
        "start": "2001-01-01", "scale": 11000, "agg": "mean", "factor": 1.0,  # mm/hr -> converted below
        "label": "GPM IMERG monthly precipitation", "resolution": "0.1° (~11 km)", "units": "mm/month",
    },
    "et": {
        "ids": ["MODIS/061/MOD16A2", "MODIS/006/MOD16A2"],
        "bands": {"ET": "et_modis"},
        "start": "2001-01-01", "scale": 500, "agg": "sum", "factor": 0.1,
        "label": "MODIS MOD16 evapotranspiration", "resolution": "500 m, 8-day", "units": "mm/month",
    },
    "grace": {
        "ids": ["NASA/GRACE/MASS_GRIDS_V04/MASCON_CRI", "NASA/GRACE/MASS_GRIDS_V03/MASCON_CRI",
                "NASA/GRACE/MASS_GRIDS/MASCON_CRI"],
        "bands": {"lwe_thickness": "grace_lwe"},
        "start": "2002-04-01", "scale": 50000, "agg": "mean", "factor": 1.0,
        "label": "GRACE/GRACE-FO JPL mascon water storage", "resolution": "~300 km (0.5° grid)", "units": "cm",
    },
}

SRTM_ID = "USGS/SRTMGL1_003"


def available() -> bool:
    return ee is not None


_initialized = False


def initialize(project: str, service_account: str = "", key_file: str = "") -> None:
    """Personal login (earthengine authenticate) on a laptop; a service account on a server."""
    global _initialized
    if _initialized:
        return
    if ee is None:
        raise RuntimeError("earthengine-api is not installed (pip install earthengine-api)")
    if not project:
        raise RuntimeError("Set GEE_PROJECT in .env to your Google Cloud project id")
    if service_account and key_file:
        credentials = ee.ServiceAccountCredentials(service_account, key_file)
        ee.Initialize(credentials, project=project)
    else:
        ee.Initialize(project=project)
    _initialized = True


def _first_existing(ids: list[str]) -> str:
    for cid in ids:
        try:
            ee.ImageCollection(cid).limit(1).size().getInfo()
            return cid
        except Exception:  # noqa: BLE001 - GEE raises generic EEException
            continue
    raise RuntimeError(f"None of these collections are reachable: {ids}")


def _monthly_values(collection_id: str | None, band: str, start: str, end: str, geom, scale: int,
                    agg: str, chunk_years: int = 3, ic=None) -> pd.Series:
    """Monthly mean/sum of one band averaged over geom. Chunked to stay under GEE limits."""
    ic = (ic if ic is not None else ee.ImageCollection(collection_id)).select([band])
    months = pd.period_range(start=start, end=end, freq="M")
    values: dict[str, float] = {}
    chunk = chunk_years * 12
    for i in range(0, len(months), chunk):
        block = months[i:i + chunk]
        first = ee.Date(block[0].start_time.strftime("%Y-%m-%d"))

        def per_month(k, first=first):
            s = first.advance(k, "month")
            e = s.advance(1, "month")
            col = ic.filterDate(s, e)
            composite = col.sum() if agg == "sum" else col.mean()
            img = ee.Image(ee.Algorithms.If(col.size().gt(0), composite,
                                            ee.Image.constant(0).rename(band).updateMask(0)))
            val = img.reduceRegion(reducer=ee.Reducer.mean(), geometry=geom, scale=scale,
                                   maxPixels=1e9, bestEffort=True).get(band)
            return ee.Feature(None, {"month": s.format("YYYY-MM"), "value": val})

        fc = ee.FeatureCollection(ee.List.sequence(0, len(block) - 1).map(per_month))
        for feat in fc.getInfo()["features"]:
            props = feat["properties"]
            values[props["month"]] = props.get("value")
    s = pd.Series(values, dtype="float64")
    s.index = pd.PeriodIndex(s.index, freq="M")
    return s


def fetch_satellite_layers(lat: float, lon: float, end_year: int, buffer_m: int = 2500,
                           log: Callable[[str], None] = print,
                           only: list[str] | None = None) -> tuple[pd.DataFrame, dict]:
    """Return monthly dataframe of satellite layers (all, or just `only`) + per-layer metadata."""
    point = ee.Geometry.Point([lon, lat])
    geom = point.buffer(buffer_m)
    end = f"{end_year}-12-01"
    frames: dict[str, pd.Series] = {}
    layer_meta: dict[str, dict] = {}
    for key, cfg in LAYERS.items():
        if only and key not in only:
            continue
        try:
            cid = _first_existing(cfg["ids"])
            for band, col in cfg["bands"].items():
                log(f"  GEE {cfg['label']} [{band}] from {cid} ...")
                # GRACE pixels are huge: sample at the point instead of the small buffer.
                region = point.buffer(30000) if key == "grace" else geom
                s = _monthly_values(cid, band, cfg["start"], end, region, cfg["scale"], cfg["agg"])
                s = s * cfg["factor"]
                if key == "gpm":  # mm/hr monthly mean rate -> mm/month
                    days = np.array([calendar.monthrange(p.year, p.month)[1] for p in s.index])
                    s = s * 24 * days
                frames[col] = s
            layer_meta[key] = {"available": True, "collection": cid, "label": cfg["label"],
                               "resolution": cfg["resolution"], "units": cfg["units"],
                               "period": f"{cfg['start'][:4]}-{end_year}"}
        except Exception as err:  # noqa: BLE001
            log(f"  ! {cfg['label']} unavailable: {err}")
            layer_meta[key] = {"available": False, "label": cfg["label"], "error": str(err)[:200],
                               "resolution": cfg["resolution"]}
    df = pd.DataFrame(frames).sort_index() if frames else pd.DataFrame()
    return df, layer_meta


def fetch_dem_grid(lat: float, lon: float, cells: int = 25, cell_m: int = 30) -> dict:
    """SRTM 30 m elevation grid (cells x cells) centred on the field."""
    half = cells * cell_m / 2
    point = ee.Geometry.Point([lon, lat])
    region = point.buffer(half).bounds()
    img = ee.Image(SRTM_ID).select("elevation").reproject(crs="EPSG:3857", scale=cell_m)
    arr = img.sampleRectangle(region=region, defaultValue=0).get("elevation").getInfo()
    grid = np.array(arr, dtype=float)
    # trim / pad to exactly cells x cells
    grid = grid[:cells, :cells]
    if grid.shape != (cells, cells):
        grid = np.pad(grid, ((0, cells - grid.shape[0]), (0, cells - grid.shape[1])), mode="edge")
    return {"cells": cells, "cell_m": cell_m, "elev": grid.round(1).tolist(),
            "source": "SRTM GL1 v3 (30 m)"}


# ---------------------------------------------------------------- Landsat 8/9 (30 m field-scale greenness)
LANDSAT_IDS = ["LANDSAT/LC08/C02/T1_L2", "LANDSAT/LC09/C02/T1_L2"]


def _landsat_ndvi_collection():
    def prep(img):
        qa = img.select("QA_PIXEL")
        clear = qa.bitwiseAnd(1 << 3).eq(0).And(qa.bitwiseAnd(1 << 4).eq(0))   # no cloud, no shadow
        sr = img.select(["SR_B4", "SR_B5"]).multiply(0.0000275).add(-0.2)
        ndvi = sr.normalizedDifference(["SR_B5", "SR_B4"]).rename("ndvi")
        return ndvi.updateMask(clear).copyProperties(img, ["system:time_start"])
    merged = ee.ImageCollection(LANDSAT_IDS[0]).merge(ee.ImageCollection(LANDSAT_IDS[1]))
    return merged.map(prep)


def fetch_landsat(lat: float, lon: float, end_year: int, cells: int = 25, cell_m: int = 30,
                  log: Callable[[str], None] = print) -> tuple[pd.Series, dict | None, dict]:
    """Monthly field NDVI (300 m around the pin) since 2013 + a 30 m greenness map of the last growing season."""
    point = ee.Geometry.Point([lon, lat])
    ic = _landsat_ndvi_collection()
    log("  GEE Landsat 8/9 NDVI (30 m) monthly ...")
    series = _monthly_values(None, "ndvi", "2013-04-01", f"{end_year}-12-01", point.buffer(300), 30, "mean", ic=ic)
    grid = None
    try:
        last = series.dropna()
        if len(last) >= 12:
            recent = last[last.index >= last.index.max() - 11]
            peak = recent.idxmax()
            start = (peak - 1).start_time.strftime("%Y-%m-%d")
            stop = (peak + 2).start_time.strftime("%Y-%m-%d")
            half = cells * cell_m / 2
            region = point.buffer(half).bounds()
            img = ic.filterDate(start, stop).median().unmask(-1).reproject(crs="EPSG:3857", scale=cell_m)
            arr = img.sampleRectangle(region=region, defaultValue=-1).get("ndvi").getInfo()
            g = np.array(arr, dtype=float)[:cells, :cells]
            g[g < -0.5] = np.nan
            grid = {"cells": int(g.shape[0]), "values": np.round(g, 3).tolist(),
                    "period": f"{start[:7]} to {stop[:7]}", "source": "Landsat 8/9 Collection 2 L2 (30 m)"}
    except Exception as err:  # noqa: BLE001
        log(f"  ! Landsat field map unavailable: {err}")
    meta = {"available": series.notna().sum() > 12, "label": "Landsat 8/9 NDVI", "resolution": "30 m",
            "units": "index", "period": f"2013-{end_year}", "collection": ", ".join(LANDSAT_IDS)}
    return series, grid, meta


# ---------------------------------------------------------------- GEDI biomass (lidar, 25 m footprints)
GEDI_IDS = ["LARSE/GEDI/GEDI04_A_002_MONTHLY"]


def fetch_gedi_biomass(lat: float, lon: float, radius_m: int = 5000) -> dict:
    """Mean above-ground biomass density (Mg/ha) of GEDI footprints within radius of the field."""
    cid = _first_existing(GEDI_IDS)
    region = ee.Geometry.Point([lon, lat]).buffer(radius_m)
    img = ee.ImageCollection(cid).select("agbd").mean()
    stats = img.reduceRegion(reducer=ee.Reducer.mean().combine(ee.Reducer.count(), sharedInputs=True)
                             .combine(ee.Reducer.percentile([25, 75]), sharedInputs=True),
                             geometry=region, scale=25, maxPixels=1e9, bestEffort=True).getInfo()
    return {"available": bool(stats.get("agbd_count")), "label": "GEDI L4A above-ground biomass",
            "resolution": "25 m footprints", "units": "Mg/ha", "collection": cid,
            "mean": stats.get("agbd_mean"), "p25": stats.get("agbd_p25"), "p75": stats.get("agbd_p75"),
            "footprints": stats.get("agbd_count"), "radius_km": radius_m / 1000}
