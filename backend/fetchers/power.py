"""NASA POWER (Prediction Of Worldwide Energy Resources) daily point data.

No API key needed. Docs: https://power.larc.nasa.gov/docs/services/api/temporal/daily/
Resolution: ~0.5° x 0.625° (MERRA-2 meteorology, CERES/GEWEX radiation).
"""
from __future__ import annotations

import time

import numpy as np
import pandas as pd
import requests

POWER_URL = "https://power.larc.nasa.gov/api/temporal/daily/point"

# POWER parameter -> our column name
PARAMETERS = {
    "T2M_MAX": "tmax",          # °C daily max air temperature at 2 m
    "T2M_MIN": "tmin",          # °C daily min
    "T2M": "tmean",             # °C daily mean
    "PRECTOTCORR": "rain",      # mm/day bias-corrected precipitation
    "RH2M": "rh",               # % relative humidity
    "WS2M": "wind",             # m/s wind at 2 m
    "ALLSKY_SFC_SW_DWN": "rad", # MJ/m²/day (AG community units) incoming solar
    "GWETTOP": "gwettop",       # 0-1 surface soil wetness (model, 0-5 cm)
    "GWETROOT": "gwetroot",     # 0-1 root-zone soil wetness (model, 0-100 cm)
}

FILL_VALUE = -999.0


def fetch_power_daily(lat: float, lon: float, start_year: int, end_year: int,
                      timeout: int = 180, retries: int = 3) -> tuple[pd.DataFrame, dict]:
    """Download daily weather for one point. Returns (dataframe, info)."""
    params = {
        "parameters": ",".join(PARAMETERS.keys()),
        "community": "AG",
        "longitude": round(lon, 4),
        "latitude": round(lat, 4),
        "start": f"{start_year}0101",
        "end": f"{end_year}1231",
        "format": "JSON",
    }
    last_err: Exception | None = None
    for attempt in range(retries):
        try:
            resp = requests.get(POWER_URL, params=params, timeout=timeout)
            resp.raise_for_status()
            return parse_power_json(resp.json())
        except (requests.RequestException, ValueError) as err:  # network or bad JSON
            last_err = err
            time.sleep(2 * (attempt + 1))
    raise RuntimeError(f"NASA POWER request failed after {retries} tries: {last_err}")


def parse_power_json(payload: dict) -> tuple[pd.DataFrame, dict]:
    """Turn the POWER JSON response into a tidy daily dataframe."""
    param_block = payload["properties"]["parameter"]
    frames = {}
    for power_name, col in PARAMETERS.items():
        series = param_block.get(power_name)
        if series is None:
            continue
        s = pd.Series(series, dtype="float64")
        s.index = pd.to_datetime(s.index, format="%Y%m%d")
        frames[col] = s.where(s > FILL_VALUE + 1)
    df = pd.DataFrame(frames).sort_index()
    df.index.name = "date"
    coords = payload.get("geometry", {}).get("coordinates", [None, None, None])
    info = {
        "elevation_m": coords[2] if len(coords) > 2 else None,
        "source": "NASA POWER daily (AG community)",
        "resolution": "0.5° x 0.625° (~50 km)",
    }
    # Gap-fill short holes so ET0 and features don't break.
    df = df.interpolate(limit=5).ffill().bfill()
    if "tmean" not in df or df["tmean"].isna().all():
        df["tmean"] = (df["tmax"] + df["tmin"]) / 2
    for col in ("gwettop", "gwetroot"):
        if col not in df:
            df[col] = np.nan
    return df, info

