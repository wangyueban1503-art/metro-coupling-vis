"""Run pipeline for every city and every year that exists in city_timeline,
then refresh city_timeline aggregate at the end. Slow but exhaustive.
"""
from __future__ import annotations

import json
import logging
import sys

from . import run_all, city_timeline_aggregate
from .config import DATA_DIR


def main():
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s: %(message)s")
    timeline = json.loads((DATA_DIR / "city_timeline.json").read_text(encoding="utf-8"))
    targets = []
    for city, info in timeline.items():
        years = sorted({t["year"] for t in info.get("timeline", []) if t.get("year")})
        for y in years:
            targets.append((city, y))
    logging.info("Total city-year combos: %s", len(targets))
    ok = 0
    for i, (c, y) in enumerate(targets, 1):
        logging.info("[%s/%s] %s/%s", i, len(targets), c, y)
        if run_all.run_city_year(c, y):
            ok += 1
    logging.info("Done: %s/%s", ok, len(targets))
    city_timeline_aggregate.build_city_timeline()


if __name__ == "__main__":
    sys.exit(main() or 0)
