"""Batch-generate network station areas and coupling outputs.

This script is intentionally city-batched: it builds each city's road graph
once, computes every station's network catchment once, and then exports
year-filtered FeatureCollections plus refreshed coupling metrics.
"""
from __future__ import annotations

import argparse
import gc
import json
import logging
import shutil
from pathlib import Path
from typing import Dict, Iterable, List

from . import (
    city_timeline_aggregate,
    coupling_model,
    data_loader,
    entropy_weight,
    export_result,
    spatial_indicators,
    station_area_network,
)
from .config import DATA_DIR, FRONTEND_DIR, ROOT_DIR

YEARS = list(range(2000, 2024))
DEFAULT_CITIES = ["110000", "310000", "330100", "440100", "440300", "510100"]


def _parse_csv(value: str | None, default: Iterable[str]) -> List[str]:
    if not value:
        return list(default)
    return [item.strip() for item in value.split(",") if item.strip()]


def _sync_frontend() -> int:
    target = ROOT_DIR / "frontend"
    patterns = [
        "station_areas_*.json",
        "station_coupling_*.json",
        "summary_*.json",
        "entropy_weights_*.json",
        "city_year_index.json",
        "city_timeline.json",
    ]
    copied = 0
    for pattern in patterns:
        for src in FRONTEND_DIR.glob(pattern):
            shutil.copy2(src, target / src.name)
            copied += 1
    return copied


def _export_empty(city: str, year: int):
    fc = {
        "type": "FeatureCollection",
        "cityCode": city,
        "year": year,
        "walkRadiusMeters": station_area_network.BUDGET_M,
        "method": "network_isochrone_1260m",
        "features": [],
    }
    export_result.export_all(city, year, [], fc, {"U1_weights": {}, "U2_weights": {}})


def run_city(city: str, years: Iterable[int], force: bool = False) -> Dict[str, int]:
    years = list(years)
    logging.info("=== city %s: building road graph ===", city)
    graph = station_area_network.build_graph(city)
    if not graph:
        raise RuntimeError(f"No road graph for {city}")

    precomputed = station_area_network.precompute_station_features(city, graph=graph)
    if not precomputed:
        raise RuntimeError(f"No station catchments for {city}")

    stats = {"ok": 0, "empty": 0, "failed": 0, "skipped": 0}
    for year in years:
        out = FRONTEND_DIR / f"station_areas_{city}_{year}.json"
        if out.exists() and not force:
            try:
                payload = json.loads(out.read_text(encoding="utf-8"))
                methods = {f.get("properties", {}).get("method") for f in payload.get("features", [])}
                if payload.get("features") and methods and "buffer_1260m" not in methods:
                    stats["skipped"] += 1
                    logging.info("%s/%s already network-based; skipped", city, year)
                    continue
            except Exception:
                pass

        logging.info("--- %s/%s ---", city, year)
        fc = station_area_network.feature_collection_from_precomputed(city, year, precomputed)
        if not fc.get("features"):
            _export_empty(city, year)
            stats["empty"] += 1
            continue

        try:
            rows = spatial_indicators.compute_indicators(city, year, fc)
            wa = {
                f["properties"]["station_id"]: f["properties"].get("walk_accessibility", 1.0)
                for f in fc["features"]
            }
            for row in rows:
                sid = row.get("station_id")
                if sid in wa:
                    row["walk_accessibility"] = wa[sid]
            spatial_indicators.save_indicators(city, year, rows)
            rows_u, weights = entropy_weight.run_entropy(rows)
            rows_ctd = coupling_model.apply_coupling(rows_u)
            export_result.export_all(city, year, rows_ctd, fc, weights)
            stats["ok"] += 1
            logging.info("%s/%s exported %d station areas", city, year, len(rows_ctd))
        except Exception:
            stats["failed"] += 1
            logging.exception("%s/%s failed", city, year)

    del graph
    del precomputed
    gc.collect()
    return stats


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Batch network station-area generation")
    parser.add_argument("--cities", default=None, help="comma-separated city codes")
    parser.add_argument("--years", default=None, help="comma-separated years")
    parser.add_argument("--force", action="store_true", help="regenerate existing network outputs")
    parser.add_argument("--no-sync", action="store_true", help="do not copy outputs to frontend/")
    parser.add_argument("--verbose", "-v", action="store_true")
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    cities = _parse_csv(args.cities, DEFAULT_CITIES)
    years = [int(y) for y in _parse_csv(args.years, [str(y) for y in YEARS])]

    total = {}
    for city in cities:
        total[city] = run_city(city, years, force=args.force)

    if (DATA_DIR / "city_timeline.json").exists():
        city_timeline_aggregate.build_city_timeline()
    else:
        logging.warning("city_timeline.json not found under %s; skipped timeline aggregation", DATA_DIR)
    if not args.no_sync:
        copied = _sync_frontend()
        logging.info("synced %d frontend files", copied)

    logging.info("batch summary: %s", total)
    print(json.dumps(total, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
