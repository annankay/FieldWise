"""Climate zone and a typical starting rotation for ANY field, worked out from its own NASA data.

A farmer who drops a pin anywhere in Africa should not start from an empty plan. We classify the
field's climate (humid, sub-humid, semi-arid, arid, highland, Mediterranean, cold-winter) from 35 years
of POWER weather, then build the most common kind of rotation for that zone: the zone's usual staple
sown at its best month in the main rainy season, every year, with a second-season crop where there are
two rainy seasons. The farmer edits it in step 1 — it is a starting point, not a recommendation.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

ZONES = {
    "humid": {"label": "Humid tropics", "staples": ["maize", "cassava", "rice_upland", "yam"],
              "second": ["maize", "cowpea", "groundnut"]},
    "subhumid": {"label": "Sub-humid savanna", "staples": ["maize", "sorghum", "groundnut"],
                 "second": ["cowpea", "common_bean", "groundnut"]},
    "semiarid": {"label": "Semi-arid (Sahel / dry savanna)", "staples": ["sorghum", "millet", "maize"],
                 "second": ["cowpea"]},
    "arid": {"label": "Arid (irrigation needed)", "staples": ["millet", "sorghum", "wheat"],
             "second": ["cowpea"]},
    "highland": {"label": "Highland & plateau", "staples": ["maize", "wheat", "teff", "barley", "potato"],
                 "second": ["common_bean", "faba_bean", "potato"]},
    "mediterranean": {"label": "Mediterranean (winter rain)", "staples": ["wheat", "barley"],
                      "second": ["chickpea", "faba_bean", "lentil"]},
    "temperate": {"label": "Cold-winter", "staples": ["maize", "wheat_winter", "wheat", "potato"],
                  "second": ["common_bean", "soybean"]},
}


def climate_zone(clim: pd.DataFrame, windows: list[dict]) -> dict:
    rain = clim["rain"].to_numpy()
    tmean = clim["tmean"].to_numpy()
    annual = float(rain.sum())
    coldest = float(tmean.min())
    frost = float(clim["frost_days"].sum())
    # share of rain falling in the cool half of the year (Nov-Apr north / May-Oct south, by temperature)
    cool = np.argsort(tmean)[:6]
    cool_share = float(rain[cool].sum() / max(annual, 1))
    wet_months = int((clim["ratio"].to_numpy() >= 0.5).sum())
    bimodal = len(windows) >= 2 or _two_peaks(rain)
    if coldest < 5 or frost > 20:
        key = "temperate"
    elif cool_share > 0.65 and annual > 200 and coldest < 15:
        key = "mediterranean"
    elif float(tmean.mean()) < 21 and coldest < 19:
        key = "highland"
    elif annual < 350 or wet_months <= 1:
        key = "arid"
    elif annual < 800 or wet_months <= 4:
        key = "semiarid"
    elif annual < 1200 and not bimodal:
        key = "subhumid"
    else:
        key = "humid"
    return {"key": key, "label": ZONES[key]["label"], "annual_rain_mm": round(annual), "coldest_month_c": round(coldest, 1),
            "wet_months": wet_months, "bimodal": bool(bimodal), "cool_season_rain_share": round(cool_share, 2)}


def _two_peaks(rain: np.ndarray) -> bool:
    """Two rainy seasons: two high-rain months at least 3 months apart with a clear dip between them."""
    r = np.asarray(rain, float)
    peaks = [i for i in range(12) if r[i] >= r[i - 1] and r[i] >= r[(i + 1) % 12] and r[i] > 0.5 * r.max()]
    for a in peaks:
        for b in peaks:
            gap = (b - a) % 12
            if 3 <= gap <= 8:
                between = min(r[(a + k) % 12] for k in range(1, gap))
                if between < 0.75 * min(r[a], r[b]):
                    return True
    return False


def default_rotation(zone: dict, windows: list[dict], fitter, crops: dict) -> dict:
    """Typical two-year rotation for this zone; empty when rain alone cannot grow a crop."""
    z = ZONES[zone["key"]]
    if not windows:
        return {"staple": None, "rotation": [], "note": "no_rainfed_season"}
    main = max(windows, key=lambda w: w["length"])
    allowed = set(main["months"])

    def best_in(cid, months):
        fits = [(fitter.fit(cid, m).fit, m) for m in months if cid in crops]
        return max(fits) if fits else (0.0, None)

    def main_season_month(cid):
        """Farmers sow at the START of the main rains: the earliest window month that fits nearly as well
        as the best one (avoids picking a minor-season month just because it scores a little higher)."""
        fits = {m: fitter.fit(cid, m).fit for m in main["months"]}
        best = max(fits.values())
        return best, next(m for m in main["months"] if fits[m] >= best - 0.1)

    staple, sow = None, None
    for cid in z["staples"]:
        if cid not in crops:
            continue
        f, m = main_season_month(cid)
        if f >= 0.45:
            staple, sow = cid, m
            break
    if staple is None:   # whatever cereal or root fits best here
        options = [(best_in(c, allowed), c) for c, v in crops.items() if v["group"] in ("cereal", "root")]
        (f, sow), staple = max(options)
        if f < 0.25:
            return {"staple": None, "rotation": [], "note": "no_rainfed_season"}
    dur = crops[staple]["duration_m"]
    rotation = [{"crop": staple, "year": y, "sow_month": sow} for y in (1, 2)]
    # second rainy season (or the rest of a long one): the zone's usual second crop
    if zone["bimodal"] or main["length"] >= dur + 3:
        end = (sow - 1 + dur) % 12 + 1
        later = [((end - 1 + k) % 12) + 1 for k in range(0, 3)]
        later_ok = [m for m in later if any(m in w["months"] for w in windows)]
        if later_ok:
            for cid in [staple] + z["second"] if staple in ("maize",) and zone["key"] == "humid" else z["second"]:
                f, m2 = best_in(cid, later_ok)
                if f >= 0.45:
                    d2 = crops[cid]["duration_m"]
                    if (m2 - sow) % 12 + d2 <= 12:
                        # a second crop sown "earlier in the calendar" than the staple belongs to the next year
                        yr = (lambda y: y) if m2 > sow else (lambda y: y % 2 + 1)
                        rotation += [{"crop": cid, "year": yr(y), "sow_month": m2, "duration_m": min(d2, 4)} for y in (1, 2)]
                    break
    rotation.sort(key=lambda p: (p["year"], p["sow_month"]))
    return {"staple": staple, "rotation": rotation, "note": None}
