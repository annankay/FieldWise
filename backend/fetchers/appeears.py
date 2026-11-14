"""ECOSTRESS (70 m plant water stress and evapotranspiration) through NASA AppEEARS.

AppEEARS needs your NASA Earthdata login (EARTHDATA_USERNAME / EARTHDATA_PASSWORD in .env).
A point request is queued at NASA and can take from a few minutes to a few hours, so FieldWise
submits it, stores the task id, and picks the results up later (the app checks each time the field
is opened, or run `python scripts/build_cache.py --refresh`).

API docs: https://appeears.earthdatacloud.nasa.gov/api/
"""
from __future__ import annotations

import io
import re

import pandas as pd
import requests

API = "https://appeears.earthdatacloud.nasa.gov/api/"

# (product prefix, preferred layer patterns, our column name). Product versions are discovered at
# run time from the product list so a new ECOSTRESS collection does not break the app.
WANTED = [
    ("ECO_L3T_JET", [r"^ETdaily$", r"ETdaily", r"^ET"], "eco_et"),       # daily evapotranspiration, mm/day
    ("ECO_L4T_ESI", [r"^ESI$", r"ESI"], "eco_esi"),                       # evaporative stress index, 0-1+
]


class AppEEARS:
    def __init__(self, username: str, password: str, timeout: int = 60):
        if not username or not password:
            raise RuntimeError("Set EARTHDATA_USERNAME and EARTHDATA_PASSWORD in .env for ECOSTRESS")
        self.timeout = timeout
        resp = requests.post(API + "login", auth=(username, password), timeout=timeout)
        resp.raise_for_status()
        self.headers = {"Authorization": f"Bearer {resp.json()['token']}"}

    def _get(self, path: str, **kw):
        resp = requests.get(API + path, headers=self.headers, timeout=self.timeout, **kw)
        resp.raise_for_status()
        return resp

    def discover_layers(self) -> list[dict]:
        products = requests.get(API + "product", timeout=self.timeout).json()
        names = sorted((p["ProductAndVersion"] for p in products), reverse=True)  # newest version first
        out = []
        for prefix, patterns, col in WANTED:
            pv = next((n for n in names if n.startswith(prefix + ".")), None)
            if not pv:
                continue
            layers = requests.get(API + f"product/{pv}", timeout=self.timeout).json()
            for pat in patterns:
                layer = next((name for name in layers if re.search(pat, name)), None)
                if layer:
                    out.append({"product": pv, "layer": layer, "column": col})
                    break
        if not out:
            raise RuntimeError("No ECOSTRESS products found in AppEEARS")
        return out

    def submit(self, lat: float, lon: float, name: str, start: str = "07-01-2018", end: str | None = None) -> dict:
        layers = self.discover_layers()
        end = end or pd.Timestamp.today().strftime("%m-%d-%Y")
        task = {"task_type": "point", "task_name": f"FieldWise {name}"[:60],
                "params": {"dates": [{"startDate": start, "endDate": end}],
                           "layers": [{"product": l["product"], "layer": l["layer"]} for l in layers],
                           "coordinates": [{"latitude": lat, "longitude": lon, "id": "field", "category": "field"}]}}
        resp = requests.post(API + "task", json=task, headers=self.headers, timeout=self.timeout)
        resp.raise_for_status()
        return {"task_id": resp.json()["task_id"], "layers": layers, "status": "pending"}

    def status(self, task_id: str) -> str:
        return self._get(f"task/{task_id}").json().get("status", "unknown")

    def download(self, task_id: str, layers: list[dict]) -> pd.DataFrame:
        bundle = self._get(f"bundle/{task_id}").json()
        csvs = [f for f in bundle.get("files", []) if f.get("file_type") == "csv"]
        frames = []
        for f in csvs:
            text = self._get(f"bundle/{task_id}/{f['file_id']}").text
            frames.append(parse_point_csv(text, layers))
        frames = [f for f in frames if not f.empty]
        if not frames:
            return pd.DataFrame()
        return pd.concat(frames, axis=1).T.groupby(level=0).first().T


def parse_point_csv(text: str, layers: list[dict]) -> pd.DataFrame:
    """AppEEARS point CSV -> monthly means per layer (columns eco_et, eco_esi)."""
    df = pd.read_csv(io.StringIO(text))
    if "Date" not in df.columns:
        return pd.DataFrame()
    df["Date"] = pd.to_datetime(df["Date"], errors="coerce")
    out = {}
    for l in layers:
        cols = [c for c in df.columns if c.endswith("_" + l["layer"]) or c == l["layer"]]
        if not cols:
            continue
        s = pd.to_numeric(df[cols[0]], errors="coerce")
        s.index = df["Date"]
        s = s[(s > -9000) & s.index.notna()].dropna()
        if l["column"] == "eco_esi":
            s = s[(s >= 0) & (s <= 2)]
        if l["column"] == "eco_et":
            s = s[(s >= 0) & (s <= 20)]
        if s.empty:
            continue
        m = s.resample("MS").mean()
        m.index = m.index.to_period("M")
        out[l["column"]] = m
    return pd.DataFrame(out)

