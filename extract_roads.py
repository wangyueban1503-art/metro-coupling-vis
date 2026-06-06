"""Extract road networks for each city using osmium CLI tools.
Steps per city:
  1. osmium extract --bbox  -> city-only PBF (small)
  2. osmium tags-filter w/highway  -> highway ways only
  3. osmium export --geometry-types=linestring -> GeoJSON
  4. Convert to our road_network_{code}.json format

No Python memory issues since each city extract is <50MB.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent  # data/
SRC_PBF = Path("D:/osm_temp.pbf")  # pre-copied from raw/transport/china-latest.osm.pbf
OUT_DIR = ROOT / "algorithm" / "data"
OUT_DIR.mkdir(parents=True, exist_ok=True)

CITY_BOUNDS = {
    "上海市": (120.85, 30.65, 122.15, 31.90),
    "北京市": (115.40, 39.45, 117.50, 41.05),
    "广州市": (112.75, 22.40, 114.30, 23.95),
    "成都市": (102.90, 29.90, 104.80, 31.40),
    "杭州市": (118.80, 29.90, 120.70, 30.70),
    "深圳市": (113.70, 22.35, 114.60, 22.90),
}
CITY_MAP = {
    "上海市": "310000",
    "北京市": "110000",
    "广州市": "440100",
    "成都市": "510100",
    "杭州市": "330100",
    "深圳市": "440300",
}


def run(cmd, check=True):
    """Run a command, return stdout+stderr."""
    print(f"  CMD: {' '.join(cmd)}")
    result = subprocess.run(cmd, capture_output=True, text=True)
    if check and result.returncode != 0:
        print(f"  FAILED: {result.stderr[:500]}")
        raise RuntimeError(f"Command failed: {result.stderr[:500]}")
    return result


def extract_city_roads(city_cn: str, code: str, bounds: tuple):
    """Extract road network for one city."""
    out_path = OUT_DIR / f"road_network_{code}.json"
    if out_path.exists():
        print(f"  {city_cn}: already exists, skipping")
        return

    bbox_str = f"{bounds[0]},{bounds[1]},{bounds[2]},{bounds[3]}"
    tmp_extract = ROOT / f"_tmp_{code}.osm.pbf"
    tmp_hwy = ROOT / f"_tmp_{code}_hwy.osm.pbf"
    tmp_geojson = ROOT / f"_tmp_{code}.geojson"

    try:
        print(f"  {city_cn}: bbox={bbox_str}")
        # Step 1: extract bounding box
        run(["osmium", "extract", "--bbox", bbox_str,
             "-o", str(tmp_extract), str(SRC_PBF)])
        if not tmp_extract.exists():
            raise RuntimeError(f"Extract failed for {city_cn}")

        # Step 2: filter to highway ways
        run(["osmium", "tags-filter", str(tmp_extract),
             "w/highway", "-o", str(tmp_hwy)])
        if not tmp_hwy.exists():
            raise RuntimeError(f"Tag filter failed for {city_cn}")

        # Step 3: export to GeoJSON
        run(["osmium", "export", str(tmp_hwy),
             "--geometry-types=linestring",
             "-o", str(tmp_geojson)])
        if not tmp_geojson.exists():
            raise RuntimeError(f"Export failed for {city_cn}")

        # Step 4: convert to our format (attach highway tag as property)
        with open(tmp_geojson, encoding="utf-8") as f:
            fc = json.load(f)

        # Ensure every feature has highway property
        for f in fc.get("features", []):
            props = f.get("properties") or {}
            # The exported features have osm_id and tags; extract highway from tags
            tags = props.get("tags", {}) or {}
            if isinstance(tags, dict):
                f["properties"] = {
                    "highway": tags.get("highway", "road"),
                    "name": tags.get("name", ""),
                    "ref": tags.get("ref", ""),
                }
            else:
                f["properties"] = {"highway": "road"}

        with open(out_path, "w", encoding="utf-8") as f:
            json.dump(fc, f, ensure_ascii=False)
        print(f"  {city_cn}: {len(fc.get('features', []))} roads -> {out_path.name}")

    finally:
        # Clean up temp files
        for tmp in (tmp_extract, tmp_hwy, tmp_geojson):
            if tmp.exists():
                tmp.unlink()


def main():
    if not SRC_PBF.exists():
        print(f"ERROR: {SRC_PBF} not found. Run preprocess_raw.py first to copy the PBF.")
        sys.exit(1)

    print("Extracting road networks per city:")
    for city_cn, code in CITY_MAP.items():
        bounds = CITY_BOUNDS[city_cn]
        extract_city_roads(city_cn, code, bounds)

    print("\nDone.")


if __name__ == "__main__":
    main()