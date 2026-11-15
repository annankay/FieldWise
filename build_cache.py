"""Download REAL NASA data and cache it for the app.

Examples
    python scripts/build_cache.py --all                      # all demo sites with real data
    python scripts/build_cache.py --site ejura               # one demo site
    python scripts/build_cache.py --lat 6.69 --lon -1.62 --name "My farm"
    python scripts/build_cache.py --all --no-gee             # POWER + SoilGrids only (fast, no account)
    python scripts/build_cache.py --refresh                  # collect finished ECOSTRESS requests
    python scripts/build_cache.py --demo                     # DEVELOPMENT ONLY: synthetic test data
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from backend.fetchers import builder  # noqa: E402


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--all", action="store_true", help="all demo sites from backend/data/sites.json")
    ap.add_argument("--site", help="one demo site id (ejura, tamale, kansas)")
    ap.add_argument("--lat", type=float)
    ap.add_argument("--lon", type=float)
    ap.add_argument("--name", default=None)
    ap.add_argument("--no-gee", action="store_true", help="skip Google Earth Engine layers")
    ap.add_argument("--demo", action="store_true", help="development only: synthetic test data")
    ap.add_argument("--refresh", action="store_true", help="collect finished ECOSTRESS requests for all fields")
    args = ap.parse_args()

    if args.refresh:
        from backend.fetchers import cache
        for meta in cache.list_cached():
            try:
                got = builder.refresh_ecostress(meta["id"])
                print(f"{meta['id']}: {'ECOSTRESS added' if got else 'nothing new'}")
            except Exception as err:  # noqa: BLE001
                print(f"{meta['id']}: {err}")
        return

    sites = {s["id"]: s for s in builder.load_sites_config()}
    if args.demo:
        for s in sites.values():
            builder.build_demo(s)
            print(f"demo data written for {s['id']}")
        return
    targets = []
    if args.all:
        targets = list(sites.values())
    elif args.site:
        if args.site not in sites:
            sys.exit(f"Unknown site '{args.site}'. Choose from: {', '.join(sites)}")
        targets = [sites[args.site]]
    if targets:
        for s in targets:
            builder.build_live(s["lat"], s["lon"], s["name"], site_id=s["id"], use_gee=not args.no_gee, base=s)
        return
    if args.lat is None or args.lon is None:
        ap.print_help()
        sys.exit(1)
    name = args.name or f"Field {args.lat:.3f},{args.lon:.3f}"
    builder.build_live(args.lat, args.lon, name, use_gee=not args.no_gee)


if __name__ == "__main__":
    main()
