"""Check that every data source works on YOUR machine before the hackathon.

    python scripts/check_setup.py

Tests: Python packages, NASA POWER (no key), SoilGrids, Google Earth Engine (+ each NASA collection),
and the optional Claude explainer key.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from backend import config  # noqa: E402

OK, FAIL, SKIP = "  [ OK ]", "  [FAIL]", "  [SKIP]"
LAT, LON = 7.385, -1.356  # Ejura demo field


def check_packages() -> None:
    print("Python packages")
    for mod in ("fastapi", "uvicorn", "pandas", "numpy", "scipy", "sklearn", "requests"):
        try:
            __import__(mod)
            print(OK, mod)
        except ImportError:
            print(FAIL, mod, "-> pip install -r requirements.txt")
    try:
        import ee  # noqa: F401
        print(OK, "earthengine-api")
    except ImportError:
        print(SKIP, "earthengine-api not installed (satellite layers disabled)")


def check_power() -> None:
    print("\nNASA POWER")
    from backend.fetchers.power import fetch_power_daily
    try:
        df, info = fetch_power_daily(LAT, LON, 2023, 2023, timeout=90, retries=1)
        print(OK, f"{len(df)} days, mean rain {df['rain'].mean():.1f} mm/day, elevation {info['elevation_m']} m")
    except Exception as err:  # noqa: BLE001
        print(FAIL, err)


def check_soilgrids() -> None:
    print("\nISRIC SoilGrids")
    from backend.fetchers.soilgrids import fetch_soilgrids, texture_class
    try:
        soil = fetch_soilgrids(LAT, LON)
        print(OK, soil, "->", texture_class(soil))
    except Exception as err:  # noqa: BLE001
        print(FAIL, err, "(SoilGrids is sometimes slow or down; the app still works without it)")


def check_gee() -> None:
    print("\nGoogle Earth Engine")
    from backend.fetchers import gee
    if not gee.available():
        print(SKIP, "pip install earthengine-api, then: earthengine authenticate")
        return
    if not config.GEE_PROJECT:
        print(FAIL, "GEE_PROJECT is not set. Copy .env.example to .env and put your Cloud project id in it.")
        return
    try:
        gee.initialize(config.GEE_PROJECT, config.GEE_SERVICE_ACCOUNT, config.GEE_KEY_FILE)
        print(OK, f"initialized with project '{config.GEE_PROJECT}'")
    except Exception as err:  # noqa: BLE001
        print(FAIL, err)
        print("       Fix: run 'earthengine authenticate' and register the project at https://code.earthengine.google.com/register")
        return
    import ee
    for key, cfg in gee.LAYERS.items():
        try:
            cid = gee._first_existing(cfg["ids"])  # noqa: SLF001
            n = ee.ImageCollection(cid).filterDate("2020-01-01", "2020-03-01").size().getInfo()
            print(OK, f"{cfg['label']}: {cid} ({n} images in Jan-Feb 2020)")
        except Exception as err:  # noqa: BLE001
            print(FAIL, cfg["label"], err)
    try:
        dem = gee.fetch_dem_grid(LAT, LON, cells=5)
        print(OK, f"SRTM sample grid {len(dem['elev'])}x{len(dem['elev'][0])}")
    except Exception as err:  # noqa: BLE001
        print(FAIL, "SRTM", err)


def check_extra_nasa() -> None:
    print("\nNASA GIBS (time-machine map), EONET (natural events), AppEEARS (ECOSTRESS)")
    from backend.fetchers import eonet, gibs
    try:
        th = gibs.themes()
        print(OK, "GIBS layers:", ", ".join(f"{x['key']}={x['layer']}" for x in th["themes"]))
    except Exception as err:  # noqa: BLE001
        print(FAIL, "GIBS", err)
    try:
        ev = eonet.nearby_events(LAT, LON)
        print(OK, f"EONET: {len(ev['events'])} events within {ev['radius_km']} km")
    except Exception as err:  # noqa: BLE001
        print(FAIL, "EONET", err)
    if not (config.EARTHDATA_USERNAME and config.EARTHDATA_PASSWORD):
        print(SKIP, "ECOSTRESS: set EARTHDATA_USERNAME and EARTHDATA_PASSWORD in .env")
        return
    try:
        from backend.fetchers.appeears import AppEEARS
        client = AppEEARS(config.EARTHDATA_USERNAME, config.EARTHDATA_PASSWORD)
        print(OK, "AppEEARS login; ECOSTRESS layers:", client.discover_layers())
    except Exception as err:  # noqa: BLE001
        print(FAIL, "AppEEARS", err)


def check_gee_extra() -> None:
    from backend.fetchers import gee
    if not (gee.available() and config.GEE_PROJECT):
        return
    try:
        g = gee.fetch_gedi_biomass(LAT, LON)
        print(OK, f"GEDI biomass: mean {g['mean']} Mg/ha from {g['footprints']} footprints")
    except Exception as err:  # noqa: BLE001
        print(FAIL, "GEDI", err)
    try:
        import ee
        n = gee._landsat_ndvi_collection().filterDate("2023-01-01", "2023-03-01").filterBounds(
            ee.Geometry.Point([LON, LAT])).size().getInfo()
        print(OK, f"Landsat 8/9: {n} scenes over the test field in Jan-Feb 2023")
    except Exception as err:  # noqa: BLE001
        print(FAIL, "Landsat", err)


def check_llm() -> None:
    print("\nClaude plain-language explainer (optional)")
    print(OK if config.ANTHROPIC_API_KEY else SKIP,
          "ANTHROPIC_API_KEY set" if config.ANTHROPIC_API_KEY else "no ANTHROPIC_API_KEY (template summaries will be used)")


if __name__ == "__main__":
    check_packages()
    check_power()
    check_soilgrids()
    check_gee()
    check_gee_extra()
    check_extra_nasa()
    check_llm()
    print("\nDone. Fix any [FAIL] lines, then run:  python scripts/build_cache.py --all")
