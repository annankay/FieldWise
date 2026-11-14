"""Read/write the per-field data store.

Each field lives in <CACHE_DIR>/<field_id>/ with:
    meta.json         field info, data status of every layer, where it came from
    daily.csv         NASA POWER daily weather
    monthly_sat.csv   monthly satellite layers (GPM, SMAP, MODIS, GRACE, Landsat, ECOSTRESS)
    soil.json         topsoil (SoilGrids, or the farmer's own soil test)
    dem.json          SRTM elevation grid around the field
    extras.json       Landsat 30 m field map, GEDI biomass, pending ECOSTRESS task
Writes are atomic (temp file + rename) so a crash never leaves a half-written field.
"""
from __future__ import annotations

import json
import os
import re
import tempfile
import threading
from pathlib import Path

import pandas as pd

from backend.config import CACHE_DIR

SATELLITE_COLUMNS = ["gpm_rain", "smap_surface", "smap_rootzone", "ndvi", "et_modis", "grace_lwe",
                     "landsat_ndvi", "eco_et", "eco_esi"]
_ID_RE = re.compile(r"^[a-z0-9][a-z0-9-]{1,63}$")
_locks: dict[str, threading.Lock] = {}
_locks_guard = threading.Lock()


def slugify(text: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")
    return slug[:40] or "field"


def valid_id(site_id: str) -> bool:
    return bool(_ID_RE.match(site_id or ""))


def lock(site_id: str) -> threading.Lock:
    with _locks_guard:
        return _locks.setdefault(site_id, threading.Lock())


def site_dir(site_id: str) -> Path:
    if not valid_id(site_id):
        raise ValueError("invalid field id")
    return CACHE_DIR / site_id


def exists(site_id: str) -> bool:
    if not valid_id(site_id):
        return False
    d = CACHE_DIR / site_id
    return (d / "meta.json").exists() and (d / "daily.csv").exists()


def _atomic_write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=".tmp-")
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        f.write(text)
    os.replace(tmp, path)


def _sat_frame(sat: pd.DataFrame | None) -> pd.DataFrame:
    sat = pd.DataFrame(columns=SATELLITE_COLUMNS) if sat is None else sat.copy()
    for col in SATELLITE_COLUMNS:
        if col not in sat.columns:
            sat[col] = float("nan")
    return sat[SATELLITE_COLUMNS]


def save(site_id: str, meta: dict, daily: pd.DataFrame, monthly_sat: pd.DataFrame | None,
         soil: dict | None, dem: dict | None, extras: dict | None = None) -> Path:
    d = site_dir(site_id)
    _atomic_write(d / "daily.csv", daily.round(3).to_csv(index_label="date"))
    _atomic_write(d / "monthly_sat.csv", _sat_frame(monthly_sat).round(4).to_csv(index_label="month"))
    _atomic_write(d / "soil.json", json.dumps(soil or {}, indent=2))
    _atomic_write(d / "dem.json", json.dumps(dem or {}))
    _atomic_write(d / "extras.json", json.dumps(extras or {}, default=str))
    _atomic_write(d / "meta.json", json.dumps(meta, indent=2, default=str))   # last: marks the field complete
    return d


def update(site_id: str, meta: dict | None = None, sat: pd.DataFrame | None = None, soil: dict | None = None,
           dem: dict | None = None, extras: dict | None = None) -> None:
    """Merge new pieces into an existing field (used while satellite layers arrive one by one)."""
    d = site_dir(site_id)
    if sat is not None:
        old = load_sat(site_id)
        merged = old.combine_first(sat) if not old.empty else sat
        for col in sat.columns:                      # new values win
            merged[col] = sat[col].reindex(merged.index).combine_first(merged[col])
        _atomic_write(d / "monthly_sat.csv", _sat_frame(merged.sort_index()).round(4).to_csv(index_label="month"))
    if soil is not None:
        _atomic_write(d / "soil.json", json.dumps(soil, indent=2))
    if dem is not None:
        _atomic_write(d / "dem.json", json.dumps(dem))
    if extras is not None:
        cur = _read_json(d / "extras.json")
        cur.update(extras)
        _atomic_write(d / "extras.json", json.dumps(cur, default=str))
    if meta is not None:
        cur = _read_json(d / "meta.json")
        layers = {**cur.get("layers", {}), **meta.get("layers", {})}
        cur.update(meta)
        cur["layers"] = layers
        _atomic_write(d / "meta.json", json.dumps(cur, indent=2, default=str))


def _read_json(path: Path) -> dict:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def load_sat(site_id: str) -> pd.DataFrame:
    p = site_dir(site_id) / "monthly_sat.csv"
    if not p.exists():
        return pd.DataFrame(columns=SATELLITE_COLUMNS)
    sat = pd.read_csv(p, index_col="month")
    sat.index = pd.PeriodIndex(sat.index, freq="M")
    for col in SATELLITE_COLUMNS:
        if col not in sat.columns:
            sat[col] = float("nan")
    return sat


def read_meta(site_id: str) -> dict:
    return _read_json(site_dir(site_id) / "meta.json")


def load(site_id: str) -> dict:
    if not exists(site_id):
        raise FileNotFoundError(f"No data for field '{site_id}'")
    d = site_dir(site_id)
    daily = pd.read_csv(d / "daily.csv", parse_dates=["date"], index_col="date")
    return {"meta": _read_json(d / "meta.json"), "daily": daily, "sat": load_sat(site_id),
            "soil": _read_json(d / "soil.json"), "dem": _read_json(d / "dem.json"),
            "extras": _read_json(d / "extras.json")}


def list_cached() -> list[dict]:
    out = []
    for meta_file in sorted(CACHE_DIR.glob("*/meta.json")):
        meta = _read_json(meta_file)
        if meta.get("id"):
            out.append(meta)
    return out
