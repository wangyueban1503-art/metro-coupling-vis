"""Aggregate per-station algorithm results to a city/year timeline that
matches the schema of data/city_timeline.json.

Strategy
--------
- For each (city, year) entry in data/city_timeline.json, KEEP the original
  metro_score / urban_score (which already encode real year-over-year
  variation derived from cumulative metro mileage + urbanization).
- RECOMPUTE coupling_degree (C), coupling_coordination (D) and the
  development_type label using this algorithm's coupling-coordination model.
- When a per-station summary file exists for that city/year (we actually
  ran the pipeline), also overlay a station-level "algorithm_score" so the
  front-end can show both.
- Output to algorithm/output/frontend_data/city_timeline.json. Front-end
  reads this via algoFetch and falls back to data/ if missing.
"""
from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any, Dict, Optional

from .coupling_model import compute_ctd
from .config import DATA_DIR, FRONTEND_DIR

logger = logging.getLogger(__name__)


def _classify_dev_type(u1: float, u2: float) -> str:
    """Aligns with HTML badge labels."""
    if u1 is None or u2 is None:
        return "未知"
    avg = (u1 + u2) / 2.0
    if avg < 0.2:
        return "低水平磨合型"
    if u1 > u2 + 0.1:
        return "地铁超前型"
    if u2 > u1 + 0.1:
        return "城市化超前型"
    return "同步发展型"


def _load_summary(city: str, year: int) -> Optional[Dict[str, Any]]:
    p = FRONTEND_DIR / f"summary_{city}_{year}.json"
    if not p.exists():
        return None
    return json.loads(p.read_text(encoding="utf-8"))


def build_city_timeline() -> Path:
    base = json.loads((DATA_DIR / "city_timeline.json").read_text(encoding="utf-8"))

    for city, info in base.items():
        for entry in info.get("timeline", []):
            year = entry.get("year")
            u1 = entry.get("metro_score")
            u2 = entry.get("urban_score")
            if u1 is None or u2 is None:
                continue

            # Recompute C / T / D using algorithm's formulas on time-varying U1/U2.
            C, T, D = compute_ctd(float(u1), float(u2))
            entry["coupling_degree"] = round(C, 4)
            entry["coupling_coordination"] = round(D, 4)
            entry["development_type"] = _classify_dev_type(float(u1), float(u2))

            # If we have per-station summary for this exact year, attach it
            summ = _load_summary(city, year)
            if summ is not None:
                entry["algorithm_station_count"] = summ.get("station_count")
                entry["algorithm_average_D"] = summ.get("average_D")
                entry["algorithm_average_U1"] = summ.get("average_U1")
                entry["algorithm_average_U2"] = summ.get("average_U2")
                entry["algorithm_level_counts"] = summ.get("level_counts")

    out = FRONTEND_DIR / "city_timeline.json"
    out.write_text(json.dumps(base, ensure_ascii=False), encoding="utf-8")
    logger.info("city_timeline.json written -> %s", out)
    return out


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    p = build_city_timeline()
    print(f"Aggregated city timeline -> {p}")
