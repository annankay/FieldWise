from__future__ import annotations

import numpy as np
import pandas as pd

SIGMA = 4.903e-9

def _sat_vp(t):
    return 0.6108 * np.exp(17.27 * t / (t + 237.3))

def extraterrestrial_radiation(lat_deg: float, doy) -> np.ndarray:
    phi = np.radians(lat_deg)
    doy = np.asarray(doy, dtype=float)
    dr = 1 + 0.033 * np.cos(2 * np.pi * doy / 365)
    delta = 0.409 * np.sin(2 * np.pi * doy / 365 - 1.39)
    ws = np.arccos(np.clip(-np.tan(phi) * np.tan(delta), -1, 1))
    return 24 * 60 / np.pi * 0.0820 * dr * (
        ws * np.sin(phi) * np.sin(delta) + np.cos(phi) * np.cos(delta) * np.sin(ws))

def penman_monteith(df: pd.DataFrame, lat: float, elev: float) -> pd.Series:
    """Daily FAO-56 ET0 (mm/day). Needs tmax, tmin, rh, wind, rad (MJ/m²/day)."""
    tmax, tmin = df["tmax"].to_numpy(float), df["tmin"].to_numpy(float)
    tmean = (tmax + tmin) / 2
    rh = np.clip(df["rh"].to_numpy(float), 5, 100)
    u2 = np.clip(df["wind"].to_numpy(float), 0.3, 15)
    rs = df["rad"].to_numpy(float)
    doy = df.index.dayofyear.to_numpy()
    
    delta = 4098 * _sat_vp(tmean) / (tmean + 237.3) ** 2
    pressure = 101.3 * ((293 - 0.0065 * elev) / 293) ** 5.26
    gamma = 0.000665 * pressure
    es = (_sat_vp(tmax) + _sat_vp(tmin)) / 2
    ea = rh / 100 * es
    ra = extraterrestrial_radiation(lat, doy)
    rso = (0.75 + 2e-5 * elev) * ra
    rs = np.where(np.isnan(rs), 0.5 * ra, rs)  
    rns = 0.77 * rs
    ratio = np.clip(np.divide(rs, rso, out=np.ones_like(rs), where=rso > 0), 0.3, 1.0)
    rnl = SIGMA * ((tmax + 273.16) ** 4 + (tmin + 273.16) ** 4) / 2 * (0.34 - 0.14 * np.sqrt(ea)) * (1.35 * ratio - 0.35)
    rn = rns - rnl
    et0 = (0.408 * delta * rn + gamma * 900 / (tmean + 273) * u2 * (es - ea)) / (delta + gamma * (1 + 0.34 * u2))
    return pd.Series(np.clip(et0, 0, 15), index=df.index, name="et0")

