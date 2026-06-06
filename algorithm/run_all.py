"""Pipeline driver.

Usage:
    python -m algorithm.run_all --inspect
    python -m algorithm.run_all --run-all
    python -m algorithm.run_all --city 440300 --year 2020
"""
from __future__ import annotations

import argparse
import logging
import sys
from typing import List, Tuple

from . import (
    coupling_model,
    data_inspect,
    data_loader,
    entropy_weight,
    export_result,
    spatial_indicators,
    station_area,
    station_area_network,
)
from .config import FRONTEND_DIR


def run_city_year(city: str, year: int, method: str = "buffer") -> bool:
    logging.info("=== %s / %s (method=%s) ===", city, year, method)
    try:
        if method == "isochrone":
            fc = station_area_network.build_isochrone_areas(city, year)
            station_area_network.save_isochrone_areas(city, year, fc)
        else:
            fc = station_area.build_station_areas(city, year)
            station_area.save_station_areas(city, year, fc)
        if not fc.get("features"):
            logging.warning("No station areas produced for %s/%s — exporting empty result", city, year)
            export_result.export_all(city, year, [], fc, {"U1_weights": {}, "U2_weights": {}})
            return False

        rows = spatial_indicators.compute_indicators(city, year, fc)
        # If isochrone, overwrite walk_accessibility with real value from area_fc
        if method == "isochrone":
            wa = {f["properties"]["station_id"]: f["properties"].get("walk_accessibility", 1.0)
                  for f in fc["features"]}
            for r in rows:
                if r["station_id"] in wa:
                    r["walk_accessibility"] = wa[r["station_id"]]
        spatial_indicators.save_indicators(city, year, rows)

        rows_u, weights = entropy_weight.run_entropy(rows)
        rows_ctd = coupling_model.apply_coupling(rows_u)
        export_result.export_all(city, year, rows_ctd, fc, weights)
        logging.info("done %s/%s -> %d stations", city, year, len(rows_ctd))
        return True
    except Exception:
        logging.exception("Pipeline failed for %s/%s", city, year)
        return False


def collect_targets(city: str = None, year: int = None) -> List[Tuple[str, int]]:
    metadata = data_loader.load_city_metadata()
    cities = [city] if city else list(metadata.keys())
    targets = []
    for c in cities:
        years = data_loader.list_population_years(c)
        if year:
            if years and year in years:
                targets.append((c, year))
            elif years:
                # nearest
                nearest = min(years, key=lambda y: abs(y - year))
                logging.info("city %s: requested year %s not in dataset, using %s", c, year, nearest)
                targets.append((c, nearest))
            else:
                # still attempt with the requested year (population will be NaN)
                targets.append((c, year))
        else:
            if not years:
                logging.info("city %s has no population_geojson; using metro_start_year only", c)
                meta = metadata.get(c, {})
                yr = meta.get("year_range", [2020, 2020])[1]
                targets.append((c, yr))
            else:
                # default: most-recent year per city
                targets.append((c, max(years)))
    return targets


def main(argv=None):
    parser = argparse.ArgumentParser(description="Metro-TOD coupling pipeline")
    parser.add_argument("--inspect", action="store_true")
    parser.add_argument("--run-all", action="store_true")
    parser.add_argument("--city", type=str, default=None)
    parser.add_argument("--year", type=int, default=None)
    parser.add_argument("--years", type=str, default=None, help="comma list, e.g. 2018,2020,2023")
    parser.add_argument("--method", type=str, default="buffer", choices=["buffer", "isochrone"],
                        help="站域生成方法：buffer=1260m 欧氏缓冲区 / isochrone=15min 路网等时圈")
    parser.add_argument("--verbose", "-v", action="store_true")
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    if args.inspect:
        recs = data_inspect.inspect()
        data_inspect.write_inventory(recs)
        print(f"Inspected {len(recs)} files. See algorithm/output/processed/data_inventory.{{csv,json}}.")
        if not (args.run_all or args.city):
            return 0

    if args.run_all:
        targets = collect_targets(args.city, args.year)
    elif args.city:
        if args.years:
            targets = [(args.city, int(y)) for y in args.years.split(",") if y.strip()]
        elif args.year:
            targets = [(args.city, args.year)]
        else:
            targets = collect_targets(args.city, None)
    else:
        if not args.inspect:
            parser.print_help()
            return 1
        return 0

    ok = 0
    for c, y in targets:
        if run_city_year(c, y, method=args.method):
            ok += 1
    print(f"Pipeline finished: {ok}/{len(targets)} city-year combos succeeded.")
    print(f"Frontend data is in: {FRONTEND_DIR}")
    return 0 if ok else 2


if __name__ == "__main__":
    sys.exit(main())
