"""Crop suitability: how well a crop fits when sown in a given month at this field.

fit = temperature x frost x heat x water x waterlogging x soil-pH   (each 0-1, explainable)
Inputs are the 12-month climatology built from NASA POWER (+ the soil record).
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from backend.pipeline.features import MONTH_NAMES, Climate


def kc_curve(kc: list[float], duration: int) -> np.ndarray:
    """FAO-56 style crop coefficient per month of the season (initial -> mid -> late)."""
    ini, mid, end = kc
    out = []
    for k in range(duration):
        f = (k + 0.5) / duration
        if f < 0.2:
            v = ini
        elif f < 0.4:
            v = ini + (mid - ini) * (f - 0.2) / 0.2
        elif f < 0.75:
            v = mid
        else:
            v = mid + (end - mid) * (f - 0.75) / 0.25
        out.append(v)
    return np.array(out)


@dataclass
class Fit:
    crop: str
    sow_month: int          # 1-12
    duration: int
    fit: float
    temp: float
    frost: float
    heat: float
    water: float
    waterlog: float
    ph: float
    etc_mm: float           # crop water demand over the season
    deficit_mm: float       # demand not met by effective rain (irrigation need)
    heat_days: float
    frost_days: float
    months: list[int]       # calendar months 1-12 occupied
    limiting: str           # which factor limits most
    storage_mm: float = 0.0  # soil water assumed available at sowing
    dry_pen: float = 0.0     # dry-spell penalty applied to the water factor

    def as_dict(self) -> dict:
        return {k: (round(v, 3) if isinstance(v, float) else v) for k, v in self.__dict__.items()}


class CropFitter:
    def __init__(self, crops: dict, climate: Climate, soil: dict, irrigation: float = 0.0):
        self.crops = crops
        self.climate = climate
        self.c = climate.clim
        self.soil = soil or {}
        # share (0-1) of the crop's dry-season water shortfall the farmer can cover with irrigation
        self.irrigation = float(np.clip(float(irrigation or 0), 0, 1))
        self._cache: dict = {}
        sand = self.soil.get("sand", 40) or 40
        clay = self.soil.get("clay", 20) or 20
        # sandy soils hold less water -> deficits hurt more; clay buffers
        self.soil_water_factor = 1.15 if sand >= 60 else 0.9 if clay >= 35 else 1.0
        # plant-available water per metre of soil (mm/m), rough texture classes
        self.awc_mm_per_m = 80 if sand >= 70 else 110 if sand >= 52 else 150 if clay >= 35 else 170

    def root_zone_mm(self, crop: dict) -> float:
        return self.awc_mm_per_m * min(crop["root_depth"], 1.5)

    def water_from_deficit(self, crop: dict, deficit: float, demand: float, dry_pen: float) -> float:
        """Water factor 0-1. Irrigation covers part of the shortfall (and dry spells)."""
        ratio = deficit * (1 - self.irrigation) / max(demand, 1)
        water = 1 - ratio * (1 - 0.65 * crop["drought_tol"]) * self.soil_water_factor * 1.1 \
            - dry_pen * (1 - self.irrigation)
        return float(np.clip(water, 0, 1))

    def fit(self, crop_id: str, sow_month: int, duration: int | None = None) -> Fit:
        crop = self.crops[crop_id]
        duration = int(duration or crop["duration_m"])
        key = (crop_id, sow_month, duration)
        if key in self._cache:
            return self._cache[key]
        months = [((sow_month - 1 + k) % 12) + 1 for k in range(duration)]
        idx = [m - 1 for m in months]
        c = self.c
        tmean = c["tmean"].to_numpy()[idx]
        tmin_p05 = c["tmin_p05"].to_numpy()[idx]
        lo, hi = crop["t_opt"]

        # temperature
        tvals = []
        for t, tlow in zip(tmean, tmin_p05):
            if lo <= t <= hi:
                tvals.append(1.0)
            elif t < lo:
                if crop.get("overwinter") and tlow > crop["kill_temp"]:
                    tvals.append(0.85)  # dormant but alive
                else:
                    tvals.append(max(0.0, 1 - (lo - t) / 6))
            else:
                tvals.append(max(0.0, 1 - (t - hi) / 5))
        tvals = np.array(tvals)
        temp = float(0.6 * tvals.mean() + 0.4 * tvals.min())
        # an overwintering crop must still have a real growing period
        if crop.get("overwinter") and (tvals >= 0.99).sum() < max(2, duration // 3):
            temp *= 0.6

        # frost
        frost_days = float(self.climate.days_below(crop["kill_temp"])[idx].sum())
        frost = float(np.exp(-frost_days / 3))

        # heat (flowering = middle third of the season weighs most)
        hd = self.climate.days_above(crop["heat_thr"])[idx]
        w = np.array([1.0 if 0.33 <= (k + 0.5) / duration <= 0.75 else 0.3 for k in range(duration)])
        heat_days = float((hd * w).sum())
        heat = float(np.exp(-heat_days / 18))

        # water balance: monthly crop demand vs. effective rain, buffered by soil water stored at sowing
        kc = kc_curve(crop["kc"], duration)
        if crop.get("overwinter"):
            kc = np.where(tmean < lo, np.minimum(kc, 0.4), kc)   # dormant crops use little water
        etc = kc * c["et0"].to_numpy()[idx]
        peff = c["peff"].to_numpy()[idx]
        rain = c["rain"].to_numpy()[idx]
        monthly_deficit = float(np.clip(etc - peff, 0, None).sum())
        demand = float(etc.sum())
        before = [(sow_month - 2 - k) % 12 for k in range(3)]
        fill = float(np.clip(c["ratio"].to_numpy()[before].mean() / 0.8, 0.15, 1.0))
        storage = self.root_zone_mm(crop) * fill
        deficit = max(0.0, monthly_deficit - storage)
        mid = [i for k, i in enumerate(idx) if 0.33 <= (k + 0.5) / duration <= 0.75]
        dry_pen = 0.15 * (1 - crop["drought_tol"]) * float(c["dry_spell_prob"].to_numpy()[mid].mean()) if mid else 0.0
        water = self.water_from_deficit(crop, deficit, demand, dry_pen)
        excess = float(np.clip(rain - 2.2 * etc, 0, None).sum() / max(rain.sum(), 1))
        waterlog = float(np.clip(1 - excess * (1 - crop["waterlog_tol"]) * 0.6, 0.5, 1))

        ph_val = self.soil.get("ph")
        ph = 1.0
        if ph_val:
            plo, phi = crop["ph"]
            if ph_val < plo:
                ph = max(0.6, 1 - (plo - ph_val) * 0.25)
            elif ph_val > phi:
                ph = max(0.6, 1 - (ph_val - phi) * 0.25)

        factors = {"temperature": temp, "frost": frost, "heat": heat, "water": water,
                   "waterlogging": waterlog, "soil pH": ph}
        total = float(np.prod(list(factors.values())))
        limiting = min(factors, key=factors.get)
        out = Fit(crop_id, sow_month, duration, total, temp, frost, heat, water, waterlog, ph,
                  demand, deficit, heat_days, frost_days, months,
                  limiting if factors[limiting] < 0.85 else "none", storage, dry_pen)
        self._cache[key] = out
        return out

    def suitability_table(self, climate_type: str, min_fit: float = 0.0) -> list[dict]:
        """Best sowing month per crop (for the 'crop explorer' table). Every crop is tested against this
        field's own climate: no fixed climate zones, so highland wheat in Ethiopia or chickpea in Morocco
        come out naturally from the data."""
        rows = []
        for cid, crop in self.crops.items():
            fits = [self.fit(cid, m) for m in range(1, 13)]
            best = max(fits, key=lambda f: f.fit)
            if best.fit < min_fit:
                continue
            rows.append({"crop": cid, "name": crop["name"], "group": crop["group"],
                         "best_sow": MONTH_NAMES[best.sow_month - 1], "best_sow_month": best.sow_month,
                         "fit": round(best.fit, 3), "limiting": best.limiting,
                         "by_month": [round(f.fit, 2) for f in fits]})
        return sorted(rows, key=lambda r: -r["fit"])
