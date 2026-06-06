"""Export algorithm results in the formats the existing front-end expects.

Mapping to existing front-end fetches (see js/app.js):
  data/station_coupling_{cityCode}_{year}.json   <- station-level results
  data/station_areas_{cityCode}.json             <- station area polygons

We mirror those exact filenames under algorithm/output/frontend_data/, so the
front-end change is a one-line base-path swap (see app.js patch).

The station_coupling_*.json schema is kept backward-compatible:
  - existing keys preserved: stationName, lineId, lat, lon, area_km2,
    D, C, P, I, G, couplingDegree
  - extended keys added: U1, U2, T, level, station_id, road_density,
    walk_accessibility, metro_line_density, station_count, line_count,
    population_density, poi_density, poi_diversity, gdp_density
"""
from __future__ import annotations

import json
import logging
import math
from pathlib import Path
from typing import Any, Dict, List

from . import data_loader as dl
from .config import FRONTEND_DIR, PROCESSED_DIR

logger = logging.getLogger(__name__)


def _safe(v):
    if v is None:
        return None
    try:
        if isinstance(v, float) and math.isnan(v):
            return None
    except Exception:
        pass
    return v


def _round(v, n=4):
    v = _safe(v)
    if v is None or not isinstance(v, (int, float)):
        return v
    try:
        return round(float(v), n)
    except Exception:
        return v


def _compact_geometry(obj: Any, digits: int = 6) -> Any:
    if isinstance(obj, float):
        return round(obj, digits)
    if isinstance(obj, int) or obj is None or isinstance(obj, str):
        return obj
    if isinstance(obj, list):
        return [_compact_geometry(v, digits) for v in obj]
    if isinstance(obj, dict):
        return {k: _compact_geometry(v, digits) for k, v in obj.items()}
    return obj


def _dump_compact(path: Path, payload: Dict[str, Any], *, indent: int = None):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=indent, separators=(",", ":") if indent is None else None)


def export_station_coupling(city_code: str, year: int, rows: List[Dict[str, Any]]) -> Path:
    """Write station_coupling_{city}_{year}.json compatible with existing app.js."""
    stations_out = []
    for r in rows:
        # legacy fields (kept for backward compatibility with existing app.js):
        #   D in legacy data was raw "road density"-like; here we EXTEND meaning:
        #   keep `couplingDegree` for the model's D, but also surface coupling D
        #   under a new key `D` (renamed legacy D -> road_density). The front-end
        #   reads only stationName/lat/lon/couplingDegree, so this is safe.
        stations_out.append({
            "stationName": r.get("station_name"),
            "station_id": r.get("station_id"),
            "lineId": r.get("line_name"),
            "lat": r.get("lat") if r.get("lat") is not None else None,
            "lon": r.get("lon") if r.get("lon") is not None else None,
            "area_km2": _round((r.get("area_m2") or 0) / 1e6, 4),
            # legacy aliases used by current front-end logic
            "D": _round(r.get("D")),
            "C": _round(r.get("C")),
            "T": _round(r.get("T")),
            "U1": _round(r.get("U1")),
            "U2": _round(r.get("U2")),
            "couplingDegree": _round(r.get("D")),
            "level": r.get("level"),
            # raw indicators
            "road_density": _round(r.get("road_density")),
            "walk_accessibility": _round(r.get("walk_accessibility")),
            "metro_line_density": _round(r.get("metro_line_density")),
            "station_count": r.get("station_count"),
            "line_count": r.get("line_count"),
            "population_density": _round(r.get("population_density")),
            "poi_density": _round(r.get("poi_density")),
            "poi_diversity": _round(r.get("poi_diversity")),
            "gdp_density": _round(r.get("gdp_density")),
            # legacy P/I/G kept (best-effort mapping)
            "P": _round(r.get("population_density")),
            "I": _round(r.get("poi_density")),
            "G": _round(r.get("gdp_density")),
        })

    payload = {
        "cityCode": city_code,
        "year": year,
        "stations": stations_out,
    }
    out = FRONTEND_DIR / f"station_coupling_{city_code}_{year}.json"
    _dump_compact(out, payload)
    return out


def export_station_areas(city_code: str, year: int, area_fc: Dict[str, Any], rows: List[Dict[str, Any]]) -> Path:
    """Write station_areas_{city}.json (FeatureCollection) for the current year.

    To keep behavior consistent with the existing data/station_areas_{city}.json,
    we attach the same indicator/coupling fields to each feature's properties.
    """
    by_sid = {str(r.get("station_id")): r for r in rows}
    for f in area_fc.get("features", []):
        sid = str(f["properties"].get("station_id"))
        r = by_sid.get(sid)
        if r:
            f["properties"].update({
                "U1": _round(r.get("U1")),
                "U2": _round(r.get("U2")),
                "C": _round(r.get("C")),
                "T": _round(r.get("T")),
                "D": _round(r.get("D")),
                "level": r.get("level"),
                "road_density": _round(r.get("road_density")),
                "walk_accessibility": _round(r.get("walk_accessibility")),
                "metro_line_density": _round(r.get("metro_line_density")),
                "station_count": r.get("station_count"),
                "line_count": r.get("line_count"),
                "population_density": _round(r.get("population_density")),
                "poi_density": _round(r.get("poi_density")),
                "poi_diversity": _round(r.get("poi_diversity")),
                "gdp_density": _round(r.get("gdp_density")),
            })
    area_fc = _compact_geometry(area_fc)
    out = FRONTEND_DIR / f"station_areas_{city_code}.json"
    _dump_compact(out, area_fc)
    # also year-tagged copy for inspection
    out2 = FRONTEND_DIR / f"station_areas_{city_code}_{year}.json"
    _dump_compact(out2, area_fc)
    return out


def export_summary(city_code: str, year: int, rows: List[Dict[str, Any]]) -> Path:
    if not rows:
        summary = {"city": city_code, "year": year, "station_count": 0}
    else:
        def avg(key):
            xs = [r[key] for r in rows if r.get(key) is not None and not (isinstance(r[key], float) and math.isnan(r[key]))]
            return _round(sum(xs) / len(xs), 4) if xs else None
        levels: Dict[str, int] = {}
        for r in rows:
            lv = r.get("level") or "未知"
            levels[lv] = levels.get(lv, 0) + 1
        sorted_by_d = sorted(rows, key=lambda r: (r.get("D") or 0), reverse=True)
        top_high = [{"station_id": r.get("station_id"), "station_name": r.get("station_name"), "D": _round(r.get("D"))} for r in sorted_by_d[:10]]
        top_low = [{"station_id": r.get("station_id"), "station_name": r.get("station_name"), "D": _round(r.get("D"))} for r in sorted_by_d[::-1][:10]]
        summary = {
            "city": city_code,
            "year": year,
            "station_count": len(rows),
            "average_U1": avg("U1"),
            "average_U2": avg("U2"),
            "average_C": avg("C"),
            "average_T": avg("T"),
            "average_D": avg("D"),
            "level_counts": levels,
            "top10_high_D": top_high,
            "top10_low_D": top_low,
        }
    out = FRONTEND_DIR / f"summary_{city_code}_{year}.json"
    with open(out, "w", encoding="utf-8") as f:
        json.dump(summary, f, ensure_ascii=False, indent=2)
    return out


def export_entropy_weights(city_code: str, year: int, weights: Dict[str, Any]) -> Path:
    out = FRONTEND_DIR / f"entropy_weights_{city_code}_{year}.json"
    with open(out, "w", encoding="utf-8") as f:
        json.dump(weights, f, ensure_ascii=False, indent=2)
    return out


def update_city_year_index(city_code: str, year: int):
    p = FRONTEND_DIR / "city_year_index.json"
    if p.exists():
        with open(p, "r", encoding="utf-8") as f:
            idx = json.load(f)
    else:
        idx = {}
    idx.setdefault(city_code, [])
    if year not in idx[city_code]:
        idx[city_code].append(year)
        idx[city_code].sort()
    with open(p, "w", encoding="utf-8") as f:
        json.dump(idx, f, ensure_ascii=False, indent=2)


def export_all(
    city_code: str,
    year: int,
    rows_with_ctd: List[Dict[str, Any]],
    area_fc: Dict[str, Any],
    weights: Dict[str, Any],
):
    # attach lon/lat into rows (from metro_network) for downstream consumers
    stations = {str(s["station_id"]): s for s in dl.load_stations(city_code)}
    for r in rows_with_ctd:
        s = stations.get(str(r.get("station_id")))
        if s:
            r.setdefault("lon", s["lon"])
            r.setdefault("lat", s["lat"])
            r.setdefault("line_name", s.get("line_name"))
    paths = [
        export_station_coupling(city_code, year, rows_with_ctd),
        export_station_areas(city_code, year, area_fc, rows_with_ctd),
        export_summary(city_code, year, rows_with_ctd),
        export_entropy_weights(city_code, year, weights),
    ]
    update_city_year_index(city_code, year)
    return paths
