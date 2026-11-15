"""Run with:  pytest -q   (uses synthetic development data in a temporary folder)"""
from pathlib import Path

import numpy as np
import pandas as pd
import pytest
from fastapi.testclient import TestClient

from backend.api import app
from backend.fetchers import appeears, gibs
from backend.fetchers.power import parse_power_json
from backend.fetchers.soilgrids import parse_soilgrids, texture_class
from backend.pipeline.et0 import penman_monteith
from backend.pipeline.features import effective_rain
from backend.pipeline.trends import mann_kendall

FIX = Path(__file__).parent / "fixtures"
MAIZE4 = [{"crop": "maize", "year": 1, "sow_month": 4}, {"crop": "maize", "year": 1, "sow_month": 9, "duration_m": 3},
          {"crop": "maize", "year": 2, "sow_month": 4}, {"crop": "maize", "year": 2, "sow_month": 9, "duration_m": 3}]


@pytest.fixture(scope="module")
def client():
    with TestClient(app) as c:
        yield c


# ------------------------------------------------------------------ science building blocks
def test_et0_fao56_example():
    # FAO-56 Example 18 (Uccle, 6 July): ET0 ≈ 3.9 mm/day
    df = pd.DataFrame({"tmax": [21.5], "tmin": [12.3], "rh": [68.0], "wind": [2.078], "rad": [22.07]},
                      index=pd.to_datetime(["2001-07-06"]))
    assert 3.4 < penman_monteith(df, lat=50.8, elev=100).iloc[0] < 4.4


def test_effective_rain_rules():
    assert effective_rain([10])[0] == 0
    assert effective_rain([100])[0] == pytest.approx(55)


def test_mann_kendall_detects_trend():
    rng = np.random.default_rng(0)
    res = mann_kendall(np.arange(30) * 0.5 + rng.normal(0, 1, 30))
    assert res["p"] < 0.01 and 0.3 < res["slope"] < 0.7
    assert mann_kendall(rng.normal(0, 1, 30))["p"] > 0.01


# ------------------------------------------------------------------ NASA / external parsers
def test_parse_power_json():
    payload = {"geometry": {"coordinates": [-1.36, 7.38, 231.5]},
               "properties": {"parameter": {
                   "T2M_MAX": {"20240101": 33.1, "20240102": -999.0, "20240103": 34.0},
                   "T2M_MIN": {"20240101": 21.0, "20240102": 21.5, "20240103": 22.0},
                   "PRECTOTCORR": {"20240101": 0.0, "20240102": 12.5, "20240103": 3.0}}}}
    df, info = parse_power_json(payload)
    assert info["elevation_m"] == 231.5
    assert len(df) == 3 and not df["tmax"].isna().any()
    assert df["tmean"].iloc[0] == pytest.approx(27.05)


def test_parse_soilgrids():
    payload = {"properties": {"layers": [
        {"name": "clay", "unit_measure": {"d_factor": 10}, "depths": [
            {"label": "0-5cm", "values": {"mean": 150}}, {"label": "5-15cm", "values": {"mean": 150}},
            {"label": "15-30cm", "values": {"mean": 150}}]},
        {"name": "sand", "unit_measure": {"d_factor": 10}, "depths": [{"label": "0-5cm", "values": {"mean": 650}}]},
        {"name": "phh2o", "unit_measure": {"d_factor": 10}, "depths": [{"label": "0-5cm", "values": {"mean": 58}}]}]}}
    soil = parse_soilgrids(payload)
    assert soil["clay"] == 15 and soil["sand"] == 65 and soil["ph"] == 5.8
    assert texture_class({"clay": 15, "sand": 65, "silt": 20}) == "sandy loam"


def test_gibs_capabilities_pick_themes():
    layers = gibs.parse_capabilities((FIX / "gibs_caps.xml").read_text())
    themes = {t["key"]: t for t in gibs.pick_themes(layers)}
    assert themes["ndvi"]["layer"] == "MODIS_Terra_NDVI_8Day"
    assert themes["ndvi"]["time"]["end"] == "2026-11-01" and themes["ndvi"]["time"]["period"] == "P8D"
    assert themes["soil"]["max_native_zoom"] == 6
    assert themes["truecolor"]["template"].endswith("/GoogleMapsCompatible_Level9/{z}/{y}/{x}.jpg")
    assert "legends" in themes["ndvi"]["legend"]


def test_appeears_csv_parsing():
    csv = ("ID,Latitude,Longitude,Date,ECO_L3T_JET_002_ETdaily,ECO_L4T_ESI_002_ESI\n"
           "field,7.3,-1.3,2021-01-05,1.5,0.4\nfield,7.3,-1.3,2021-01-20,2.5,0.6\n"
           "field,7.3,-1.3,2021-02-03,-9999,0.9\n")
    layers = [{"product": "ECO_L3T_JET.002", "layer": "ETdaily", "column": "eco_et"},
              {"product": "ECO_L4T_ESI.002", "layer": "ESI", "column": "eco_esi"}]
    df = appeears.parse_point_csv(csv, layers)
    assert df.loc[pd.Period("2021-01", "M"), "eco_et"] == pytest.approx(2.0)
    assert df.loc[pd.Period("2021-02", "M"), "eco_esi"] == pytest.approx(0.9)
    assert pd.isna(df.loc[pd.Period("2021-02", "M"), "eco_et"])


# ------------------------------------------------------------------ API end to end
def test_reference_sites_only(client):
    ids = {s["id"] for s in client.get("/api/reference-sites").json()}
    assert ids >= {"ejura", "tamale", "segou", "bahirdar", "nakuru", "lilongwe", "meknes", "fayoum"}
    assert "kansas" not in ids


def test_profile_has_new_layers(client):
    p = client.get("/api/sites/ejura/profile?lang=fr").json()
    keys = [r["key"] for r in p["calendar"]]
    assert "bare" in keys and "esi" in keys
    assert p["phenology"]["components"] in (2, 3) and 0 <= p["phenology"]["agreement"] <= 1
    assert p["field"]["layers"]["greenness"]
    assert p["headline"][0].startswith("Environ")


def test_strategies_end_to_end(client):
    res = client.post("/api/sites/ejura/strategies", json={"current": MAIZE4}).json()
    strategies = res["strategies"]
    assert strategies[0]["is_current"] and len(strategies) >= 4
    for s in strategies:
        assert "infiltration" in s["scores"]
        ex = s["explanation"]
        assert ex["why"] and ex["gaps"] and ex["farmer"]["ask"]
        assert ex["confidence"]["level"] in {"high", "medium", "low"}
        lo, hi = s["robustness"]["range"]
        assert lo <= hi
        assert s["crop_risk"] and len(s["crop_risk"][0]["cells"]) == 24
    best = max(strategies[1:], key=lambda s: s["total"])
    assert best["scores"]["nitrogen"] > strategies[0]["scores"]["nitrogen"]
    assert best["scores"]["pest_break"] > strategies[0]["scores"]["pest_break"]


def test_staple_kept_in_main_season(client):
    res = client.post("/api/sites/ejura/strategies", json={"current": MAIZE4}).json()
    for s in res["strategies"][1:]:
        firsts = [p["sow_month"] for p in s["plantings"] if p["crop"] == "maize"]
        assert any(3 <= m <= 5 for m in firsts), s["sequence"]


def test_unavailable_staple_is_released(client):
    res = client.post("/api/sites/ejura/strategies", json={"current": MAIZE4, "constraints": {"avoid": ["maize"]}}).json()
    assert res["constraints"].get("staple_unavailable")
    for s in res["strategies"][1:]:
        assert all(p["crop"] != "maize" for p in s["plantings"])


@pytest.mark.parametrize("site,zone,staple", [
    ("ejura", "humid", "maize"), ("tamale", "subhumid", "maize"), ("segou", "semiarid", "sorghum"),
    ("bahirdar", "highland", "maize"), ("nakuru", "highland", "maize"), ("meknes", "mediterranean", "wheat"),
    ("fayoum", "arid", None)])
def test_climate_zone_and_default_rotation(site, zone, staple):
    from backend import service
    from backend.engine.crops import CropFitter
    from backend.engine.farming_systems import default_rotation
    s = service.get_site(site)
    assert s.zone["key"] == zone
    g = default_rotation(s.zone, s.windows, CropFitter(s.crops, s.base, s.soil), s.crops)
    assert g["staple"] == staple
    if staple:
        assert {p["year"] for p in g["rotation"]} == {1, 2}


def test_two_rainy_seasons_get_a_second_crop():
    from backend import service
    from backend.engine.crops import CropFitter
    from backend.engine.farming_systems import default_rotation
    s = service.get_site("ejura")
    assert s.zone["bimodal"]
    g = default_rotation(s.zone, s.windows, CropFitter(s.crops, s.base, s.soil), s.crops)
    assert len(g["rotation"]) == 4


def test_cool_season_crops_offered_in_highlands_and_mediterranean(client):
    for site, crop in (("bahirdar", "teff"), ("meknes", "chickpea"), ("meknes", "wheat")):
        p = client.get(f"/api/sites/{site}/profile").json()
        fits = {r["crop"]: r["fit"] for r in p["crop_explorer"]}
        assert fits[crop] >= 0.4, (site, crop, fits[crop])


def test_intercropping_suggested_in_one_season_zone(client):
    res = client.post("/api/sites/segou/strategies", json={}).json()
    best = max(res["strategies"][1:], key=lambda s: s["total"])
    assert any(p.get("companion") for p in best["plantings"])
    assert " + " in best["sequence"]
    assert best["scores"]["nitrogen"] > res["strategies"][0]["scores"]["nitrogen"]
    # intercropped current rotation is accepted in compact form
    r = client.post("/api/sites/segou/score", json={"plan": [{"crop": "millet", "year": 1, "sow_month": 6, "with": "cowpea"},
                                                            {"crop": "millet", "year": 2, "sow_month": 6, "with": "cowpea"}]}).json()
    assert r["plan"]["numbers"]["intercrops"] == 2


def test_desert_needs_irrigation(client):
    p = client.get("/api/sites/fayoum/profile").json()
    assert p["no_rainfed_season"]
    dry = client.post("/api/sites/fayoum/strategies", json={"constraints": {"water": "none"}}).json()
    wet = client.post("/api/sites/fayoum/strategies", json={"constraints": {"water": "full"}}).json()
    assert len(wet["strategies"]) >= 4 and wet["pool_size"] > dry["pool_size"]


def test_lapse_rate_correction_unit():
    import numpy as np
    from backend.service import SiteAnalysis
    obj = SiteAnalysis.__new__(SiteAnalysis)
    obj.dem = {"elev": (np.full((25, 25), 1800.0)).tolist()}
    obj.meta = {"power_elevation_m": 1300, "data_mode": "live"}
    import pandas as pd
    obj.daily = pd.DataFrame({"tmax": [30.0], "tmin": [15.0], "tmean": [22.5]})
    obj.elev = 1300
    lp = obj._lapse_rate_correction()
    assert lp["shift_c"] == pytest.approx(-3.25) and obj.daily["tmax"].iloc[0] == pytest.approx(26.75)


def test_every_year_has_a_productive_crop(client):
    res = client.post("/api/sites/tamale/strategies", json={}).json()
    covers = {"mucuna", "sunn_hemp", "lablab", "cereal_rye", "hairy_vetch"}
    for s in res["strategies"][1:]:
        for y in (1, 2):
            assert any(p["year"] == y and p["crop"] not in covers for p in s["plantings"]), s["sequence"]


def test_market_and_water_inputs_change_results(client):
    base = client.post("/api/sites/tamale/strategies", json={}).json()
    wet = client.post("/api/sites/tamale/strategies", json={"constraints": {"water": "full"}}).json()
    assert wet["strategies"][0]["scores"]["water"] > base["strategies"][0]["scores"]["water"]
    no_cowpea = client.post("/api/sites/tamale/strategies",
                            json={"constraints": {"market": {"cowpea": "no"}}, "priorities": {"income": 5}}).json()
    inc = [p["crop"] for p in no_cowpea["strategies"][1]["plantings"]]
    assert inc.count("cowpea") <= [p["crop"] for p in base["strategies"][1]["plantings"]].count("cowpea") + 1


def test_soil_test_overrides_model(client):
    res = client.post("/api/sites/ejura/strategies", json={"constraints": {"soil_test": {"ph": 4.6}}}).json()
    assert res["soil_used"]["ph"] == 4.6 and res["soil_used"]["source"] == "Farmer's soil test"


def test_score_custom_plan(client):
    body = {"current": MAIZE4, "plan": [{"crop": "maize", "year": 1, "sow_month": 4},
                                        {"crop": "cowpea", "year": 1, "sow_month": 9},
                                        {"crop": "maize", "year": 2, "sow_month": 4},
                                        {"crop": "mucuna", "year": 2, "sow_month": 9}]}
    r = client.post("/api/sites/ejura/score", json=body).json()
    assert r["plan"]["scores"]["nitrogen"] > 0 and r["plan"]["explanation"]["why"]


def test_input_validation(client):
    assert client.post("/api/sites/ejura/strategies", json={"current": [{"crop": "maize", "sow_month": 13}]}).status_code == 422
    assert client.post("/api/sites/ejura/strategies", json={"constraints": {"water": "lots"}}).status_code == 422
    assert client.get("/api/sites/..%2Fetc/profile").status_code == 404
    assert client.post("/api/fields", json={"lat": 120, "lon": 0}).status_code == 422


def test_fetch_rate_limit(client, monkeypatch):
    from backend import api
    monkeypatch.setattr(api.builder, "build_live", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("offline")))
    codes = [client.post("/api/fields", json={"lat": 7, "lon": -1, "name": "t"}).status_code for _ in range(3)]
    assert codes[:2] == [200, 200] and codes[2] == 429


def test_whatif_drier_hotter_hurts(client):
    res = client.post("/api/sites/tamale/strategies", json={}).json()
    body = {"strategies": [{"id": s["id"], "name": s["name"], "plantings": s["plantings"]} for s in res["strategies"]],
            "scenario": {"rain_pct": -25, "temp_c": 2.5}}
    w = client.post("/api/sites/tamale/whatif", json=body).json()
    assert w["climate_change"]["heat_days_yr"][1] > w["climate_change"]["heat_days_yr"][0]
    assert all(r["scenario_scores"]["climate_fit"] <= r["base_scores"]["climate_fit"] + 1 for r in w["rows"])
    if w["stress"]:
        assert sum(w["stress"]["scenario"]) >= sum(w["stress"]["base"])


def test_gauge_fusion(client):
    from backend.config import FRONTEND_DIR
    csv = (FRONTEND_DIR / "sample_rain_gauge.csv").read_bytes()
    r = client.post("/api/sites/ejura/gauge", files={"file": ("g.csv", csv, "text/csv")}).json()
    assert r["overlap_months"] >= 100 and r["rmse_after_mm"] <= r["rmse_before_mm"]


def test_security_headers(client):
    r = client.get("/api/health")
    assert r.headers["x-content-type-options"] == "nosniff"
    assert "default-src 'self'" in r.headers["content-security-policy"]
