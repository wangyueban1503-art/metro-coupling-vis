"""Data inventory / inspection utility.

Walks the data/ directory and produces:
  algorithm/output/processed/data_inventory.csv
  algorithm/output/processed/data_inventory.json

For very large files we only sample (the first record / a few features) to
avoid loading multi-GB JSON into memory.
"""
from __future__ import annotations

import csv
import json
import logging
import os
from pathlib import Path
from typing import Any, Dict, List

from .config import DATA_DIR, PROCESSED_DIR

logger = logging.getLogger(__name__)

SUPPORTED_EXTS = {".csv", ".json", ".geojson", ".shp", ".tif", ".tiff", ".xml"}
LON_LAT_KEYS = {"lon", "lng", "longitude", "经度", "lat", "latitude", "纬度"}
POP_KEYS = {"population", "pop", "人口", "人口数"}
GDP_KEYS = {"gdp", "经济"}
POI_KEYS = {"poi_type", "category", "类别", "类型", "poi_name"}


def _sample_json(path: Path) -> Dict[str, Any]:
    info: Dict[str, Any] = {
        "columns": [],
        "row_count": None,
        "crs": None,
        "geometry_type": None,
        "has_city": False,
        "has_year": False,
        "has_station_id": False,
        "has_station_name": False,
        "has_line_name": False,
        "has_lon_lat": False,
        "has_population_field": False,
        "has_gdp_field": False,
        "has_poi_field": False,
    }
    try:
        size_mb = path.stat().st_size / (1024 * 1024)
        # Heuristic: only read big JSONs via streaming-ish prefix read
        if size_mb > 200:
            with open(path, "r", encoding="utf-8") as f:
                head = f.read(20000)
            info["columns"] = ["<too-large-to-parse-fully>"]
            return info
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except Exception as exc:
        logger.warning("Failed to read %s: %s", path, exc)
        info["columns"] = ["<read-error>"]
        return info

    if isinstance(data, dict) and data.get("type") == "FeatureCollection":
        feats = data.get("features") or []
        info["row_count"] = len(feats)
        if feats:
            sample = feats[0]
            geom = sample.get("geometry") or {}
            info["geometry_type"] = geom.get("type")
            props = sample.get("properties") or {}
            cols = list(props.keys())
            info["columns"] = cols
            lower = {c.lower() for c in cols}
            info["has_city"] = "city" in lower or "城市" in cols or "cityCode" in cols
            info["has_year"] = "year" in lower or "年份" in cols
            info["has_station_id"] = any(k in cols for k in ["station_id", "id", "stationId"])
            info["has_station_name"] = any(k in cols for k in ["station_name", "name", "stationName", "站点名称"])
            info["has_line_name"] = any(k in cols for k in ["line", "line_name", "lineId", "线路"])
            info["has_population_field"] = any(c in POP_KEYS for c in lower)
            info["has_gdp_field"] = any(c in GDP_KEYS for c in lower)
            info["has_poi_field"] = any(c in POI_KEYS for c in lower)
        info["crs"] = "EPSG:4326"
    elif isinstance(data, dict):
        info["columns"] = list(data.keys())[:50]
        info["row_count"] = len(data)
    elif isinstance(data, list):
        info["row_count"] = len(data)
        if data and isinstance(data[0], dict):
            info["columns"] = list(data[0].keys())
    return info


def inspect(data_dir: Path = DATA_DIR) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    for root, _, files in os.walk(data_dir):
        for name in files:
            ext = Path(name).suffix.lower()
            if ext not in SUPPORTED_EXTS:
                continue
            p = Path(root) / name
            size_mb = round(p.stat().st_size / (1024 * 1024), 4)
            rec = {
                "file_path": str(p.relative_to(data_dir.parent)) if data_dir.parent in p.parents else str(p),
                "file_name": name,
                "file_type": ext.lstrip("."),
                "file_size_mb": size_mb,
                "columns": [],
                "row_count": None,
                "crs": None,
                "geometry_type": None,
                "has_city": False,
                "has_year": False,
                "has_station_id": False,
                "has_station_name": False,
                "has_line_name": False,
                "has_lon_lat": False,
                "has_population_field": False,
                "has_gdp_field": False,
                "has_poi_field": False,
            }
            if ext in {".json", ".geojson"}:
                rec.update(_sample_json(p))
            elif ext == ".csv":
                try:
                    with open(p, "r", encoding="utf-8", errors="ignore") as f:
                        reader = csv.reader(f)
                        header = next(reader, [])
                        rec["columns"] = header
                        # count up to 100k rows
                        rec["row_count"] = sum(1 for _ in reader)
                except Exception as exc:
                    logger.warning("CSV read failed %s: %s", p, exc)
            else:
                rec["columns"] = ["<not-parsed>"]
            out.append(rec)
    return out


def write_inventory(records: List[Dict[str, Any]]):
    csv_path = PROCESSED_DIR / "data_inventory.csv"
    json_path = PROCESSED_DIR / "data_inventory.json"
    if records:
        cols = list(records[0].keys())
        with open(csv_path, "w", encoding="utf-8", newline="") as f:
            w = csv.DictWriter(f, fieldnames=cols)
            w.writeheader()
            for r in records:
                row = dict(r)
                row["columns"] = "|".join(map(str, row.get("columns") or []))
                w.writerow(row)
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(records, f, ensure_ascii=False, indent=2)
    return csv_path, json_path


def main():
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    recs = inspect()
    csv_p, json_p = write_inventory(recs)
    print(f"[data_inspect] {len(recs)} files indexed")
    print(f"  -> {csv_p}")
    print(f"  -> {json_p}")


if __name__ == "__main__":
    main()
