"""Raw data -> algorithm GEN_DATA_DIR JSON converter.

Usage:
    python preprocess_raw.py

Produces algorithm/data/metro_network.json
           algorithm/data/road_network_{city}.json
           algorithm/data/city_year_index.json
           algorithm/data/gdp_{city}_{year}.geojson  (1km grid, via interpolation)
           algorithm/data/poi_{city}_{year}.geojson
           algorithm/data/population_{city}_{year}.geojson (from TIF -> points)
"""
from __future__ import annotations

import json
import logging
import math
import os
import re
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

try:
    from .metro_opening_years import get_opening_year, get_station_opening_year
    from .metro_line_colors import get_line_color
except ImportError:  # pragma: no cover - support running as a script
    from metro_opening_years import get_opening_year, get_station_opening_year
    from metro_line_colors import get_line_color

logger = logging.getLogger(__name__)

# ── Paths ────────────────────────────────────────────────────────────────────
# Script: algorithm/preprocess_raw.py
# RAW = data/raw/   (source data)
# OUT = algorithm/data/  (generated JSON for data_loader.py)
_ROOT = Path(__file__).resolve().parent          # algorithm/
RAW   = _ROOT.parent / "raw"                    # data/raw/
OUT   = _ROOT / "data"                           # algorithm/data/
OUT.mkdir(parents=True, exist_ok=True)

# ── City map ────────────────────────────────────────────────────────────────
CITY_MAP = {
    "上海市": ("310000", "上海"),
    "北京市": ("110000", "北京"),
    "广州市": ("440100", "广州"),
    "成都市": ("510100", "成都"),
    "杭州市": ("330100", "杭州"),
    "深圳市": ("440300", "深圳"),
}

# City bounding boxes (approx) for filtering
CITY_BOUNDS = {
    "上海市": (120.85, 30.65, 122.15, 31.90),
    "北京市": (115.40, 39.45, 117.50, 41.05),
    "广州市": (112.75, 22.40, 114.30, 23.95),
    "成都市": (102.90, 29.90, 104.80, 31.40),
    "杭州市": (118.80, 29.90, 120.70, 30.70),
    "深圳市": (113.70, 22.35, 114.60, 22.90),
}


# ── Metro stations / lines ───────────────────────────────────────────────────
def _parse_station_csv(csv_path: Path, city_code: str, city_cn: str) -> list[dict]:
    df = pd.read_csv(csv_path)
    df.columns = df.columns.str.strip()
    raw_stations = []
    seen = set()
    for _, row in df.iterrows():
        geom = str(row.get("geometry", "")).strip()
        if "," not in geom:
            continue
        lat_s, lon_s = geom.split(",", 1)
        lat, lon = float(lat_s.strip()), float(lon_s.strip())
        name = str(row.get("sname", "")).strip()
        line_raw = str(row.get("rname", "")).strip()
        m = re.search(r"地铁(\d+号线?|[\u4e00-\u9fa5]+线?)", line_raw)
        base_line = m.group(0) if m else line_raw
        # line_name: "杭州市" -> "杭州", then + base_line -> "杭州地铁1号线"
        line_name = f"{city_cn[:-1]}{base_line}"
        key = f"{name}_{lat:.5f}_{lon:.5f}"
        if key in seen:
            continue
        seen.add(key)
        open_year = get_station_opening_year(name, line_name, city_code) or None
        raw_stations.append({
            "station_name": name,
            "line_name": line_name,
            "lon": lon,
            "lat": lat,
            "open_year": open_year,
        })

    # The raw station CSV is line-stop based: transfer stations appear once per
    # line, often with slightly different coordinates. The visual analysis unit
    # is the physical station catchment, so aggregate by station name.
    grouped: dict[str, list[dict]] = {}
    for s in raw_stations:
        grouped.setdefault(s["station_name"], []).append(s)

    stations = []
    for name, rows in grouped.items():
        lon = sum(r["lon"] for r in rows) / len(rows)
        lat = sum(r["lat"] for r in rows) / len(rows)
        line_names = sorted({r["line_name"] for r in rows if r.get("line_name")})
        years = [r["open_year"] for r in rows if r.get("open_year")]
        open_year = min(years) if years else None
        station_id = f"{name}_{lat:.5f}_{lon:.5f}"
        stations.append({
            "station_id": station_id,
            "station_name": name,
            "line_name": " / ".join(line_names),
            "line_names": line_names,
            "lon": lon,
            "lat": lat,
            "open_year": open_year,
        })
    return stations


def _parse_line_csv(csv_path: Path, city_code: str, city_cn: str) -> list[dict]:
    if not csv_path or not csv_path.exists():
        return []
    df = pd.read_csv(csv_path)
    df.columns = df.columns.str.strip()
    lines = []
    for _, row in df.iterrows():
        geom_str = str(row.get("geometry", "")).strip()
        if not geom_str:
            continue
        coords = []
        for pt in geom_str.split(";"):
            pt = pt.strip()
            if "," in pt:
                parts = pt.split(",")
                if len(parts) == 2:
                    try:
                        lat, lon = float(parts[0].strip()), float(parts[1].strip())
                        coords.append([lon, lat])   # GeoJSON: [lon, lat]
                    except ValueError:
                        pass
        if len(coords) < 2:
            continue
        line_raw = str(row.get("rname", "")).strip()
        m = re.search(r"地铁(\d+号线?|[\u4e00-\u9fa5]+线?)", line_raw)
        base_line = m.group(0) if m else line_raw
        # line_name: "杭州市" -> "杭州", then + base_line -> "杭州地铁1号线"
        line_name = f"{city_cn[:-1]}{base_line}"
        open_year = get_opening_year(line_name, city_code) or None
        lines.append({
            "id": line_name,
            "name": line_name,
            "coordinates": coords,
            "open_year": open_year,
            "color": get_line_color(line_name, city_code),
        })
    return lines


# ── Raster (TIF) helpers ────────────────────────────────────────────────────
def _clip_to_bounds(arr, transform, nodata, bounds):
    """Mask array to bbox (minx, miny, maxx, maxy) in WGS84."""
    import rasterio
    from rasterio.mask import mask
    minx, miny, maxx, maxy = bounds
    geom = [{"type": "Polygon", "coordinates": [[
        [minx, miny], [maxx, miny], [maxx, maxy], [minx, maxy], [minx, miny]
    ]]}]
    masked, _ = mask(rasterio.open("N/A"), geom, transform=transform, nodata=nodata, invert=False)
    return masked


def tif_to_point_features(
    tif_path: Path,
    value_key: str,
    bounds: tuple | None = None,
    nodata_default: float = -2147483647.0,
) -> list[dict]:
    """Sample every valid pixel in the TIF and emit GeoJSON points."""
    import rasterio

    features = []
    with rasterio.open(tif_path) as ds:
        data = ds.read(1)
        nodata = ds.nodata if ds.nodata is not None else nodata_default
        h, w = data.shape

        for i in range(h):
            for j in range(w):
                val = data[i, j]
                if val == nodata or np.isnan(val):
                    continue
                cx, cy = ds.xy(i, j)  # pixel corner (anchor point)
                if bounds:
                    minx, miny, maxx, maxy = bounds
                    if not (minx <= cx <= maxx and miny <= cy <= maxy):
                        continue
                features.append({
                    "type": "Feature",
                    "geometry": {"type": "Point", "coordinates": [float(cx), float(cy)]},
                    "properties": {value_key: float(val)},
                })
    return features


def interpolate_gdp_array(target_year: int, gdp_dir: Path, city_cn: str, nodata=-2147483647.0) -> tuple:
    """Return (data_array_wgs84, out_transform_wgs84) for target_year.
    Reprojects from source CRS to EPSG:4326 at 0.01 deg (~1km) resolution,
    then linearly interpolates between available base years.
    """
    import rasterio
    from rasterio.warp import reproject, Resampling

    base_years = [2000, 2005, 2010, 2015, 2019, 2020]

    def load_raw(year):
        tif_path = gdp_dir / str(year) / f"{city_cn}_{year}.tif"
        with rasterio.open(tif_path) as ds:
            return ds.read(1), ds.transform, ds.crs, ds.nodata or nodata

    available = [y for y in base_years if (gdp_dir / str(y) / f"{city_cn}_{y}.tif").exists()]
    if not available:
        raise FileNotFoundError(f"No GDP data for {city_cn}")

    # Define common WGS84 output grid for this city
    wgs84_bounds = CITY_BOUNDS.get(city_cn, (120.8, 29.5, 122.5, 32.0))
    res = 0.01
    common_h = max(1, int(round((wgs84_bounds[3] - wgs84_bounds[1]) / res)))
    common_w = max(1, int(round((wgs84_bounds[2] - wgs84_bounds[0]) / res)))
    common_tfm = rasterio.transform.from_origin(wgs84_bounds[0], wgs84_bounds[3], res, res)

    def to_wgs84(year):
        arr, src_tfm, src_crs, src_nodata = load_raw(year)
        out = np.full((common_h, common_w), nodata, dtype=np.float64)
        reproject(
            source=arr.astype(np.float64), destination=out,
            src_transform=src_tfm, src_crs=src_crs,
            dst_transform=common_tfm, dst_crs="EPSG:4326",
            resampling=Resampling.nearest,
        )
        # Mark invalid pixels
        out[out < 0] = nodata
        return out

    if target_year in available:
        return to_wgs84(target_year), common_tfm

    lo = max([y for y in available if y < target_year], default=None)
    hi = min([y for y in available if y > target_year], default=None)

    if lo is None and hi:
        arr = to_wgs84(hi)
    elif hi is None and lo:
        arr = to_wgs84(lo)
    elif lo is None:
        raise FileNotFoundError(f"No GDP data for {city_cn}")
    else:
        base_arr = to_wgs84(lo)
        hi_arr = to_wgs84(hi)
        t = (target_year - lo) / (hi - lo)
        arr = np.where((base_arr == nodata) | (hi_arr == nodata), nodata,
                       base_arr + t * (hi_arr - base_arr))
    return arr, common_tfm


def process_gdp_geojson(city_cn: str, year: int, out_dir: Path):
    """Generate GDP point GeoJSON at ~1km grid (WGS84), interpolating if needed."""
    import rasterio
    gdp_dir = RAW / "urban" / "GDP"

    try:
        data, tfm = interpolate_gdp_array(year, gdp_dir, city_cn)
    except FileNotFoundError as e:
        logger.warning("GDP error for %s/%s: %s", city_cn, year, e)
        return None

    features = []
    nodata = -2147483647.0
    h, w = data.shape
    step = max(1, min(h, w) // 50)

    for i in range(0, h, step):
        for j in range(0, w, step):
            val = data[i, j]
            if val == nodata or np.isnan(val):
                continue
            cx, cy = tfm * (j + 0.5, i + 0.5)
            features.append({
                "type": "Feature",
                "geometry": {"type": "Point", "coordinates": [float(cx), float(cy)]},
                "properties": {"gdp": float(val)},
            })

    fc = {"type": "FeatureCollection", "features": features}
    out = out_dir / f"gdp_{city_cn}_{year}.geojson"
    with open(out, "w", encoding="utf-8") as f:
        json.dump(fc, f)
    logger.info("GDP %s/%s -> %s (%d pts)", city_cn, year, out.name, len(features))
    return out


def process_population_geojson(city_cn: str, year: int, out_dir: Path):
    """Convert population TIF to ~1km grid point GeoJSON."""
    import rasterio
    pop_dir = RAW / "urban" / "population" / city_cn
    tif_path = pop_dir / f"{city_cn}_{year}.tif"
    if not tif_path.exists():
        logger.warning("Population TIF not found: %s", tif_path)
        return None
    bounds = CITY_BOUNDS.get(city_cn)
    features = tif_to_point_features(tif_path, "population", bounds=bounds)
    fc = {"type": "FeatureCollection", "features": features}
    out = out_dir / f"population_{city_cn}_{year}.geojson"
    with open(out, "w", encoding="utf-8") as f:
        json.dump(fc, f)
    logger.info("Pop %s/%s -> %s (%d pts)", city_cn, year, out.name, len(features))
    return out


def process_poi_geojson(city_cn: str, year: int, out_dir: Path):
    """Read POI shapefile and convert to point GeoJSON."""
    import geopandas as gpd
    from shapely.geometry import Point

    poi_dir = RAW / "urban" / "POI" / str(year)
    shp_files = list(poi_dir.glob("*OSM.shp"))
    if not shp_files:
        logger.warning("No POI shapefile for %s/%s", city_cn, year)
        return None
    try:
        gdf = gpd.read_file(shp_files[0])
        if gdf.crs and gdf.crs.to_string() != "EPSG:4326":
            gdf = gdf.to_crs("EPSG:4326")
    except Exception as e:
        logger.warning("POI read failed for %s/%s: %s", city_cn, year, e)
        return None

    bounds = CITY_BOUNDS.get(city_cn)
    features = []
    for _, row in gdf.iterrows():
        geom = row.geometry
        if geom is None or geom.is_empty:
            continue
        if isinstance(geom, Point):
            cx, cy = geom.x, geom.y
        else:
            cx, cy = geom.centroid.x, geom.centroid.y
        if bounds:
            bx = bounds
            if not (bx[0] <= cx <= bx[2] and bx[1] <= cy <= bx[3]):
                continue
        ftype = str(row.get("fclass", row.get("type", "")))[:50]
        features.append({
            "type": "Feature",
            "geometry": {"type": "Point", "coordinates": [float(cx), float(cy)]},
            "properties": {"poi_type": ftype},
        })

    fc = {"type": "FeatureCollection", "features": features}
    out = out_dir / f"poi_{city_cn}_{year}.geojson"
    with open(out, "w", encoding="utf-8") as f:
        json.dump(fc, f)
    logger.info("POI %s/%s -> %s (%d pts)", city_cn, year, out.name, len(features))
    return out


# ── Road from OSM PBF ───────────────────────────────────────────────────────
def process_road_network(city_cn: str, code: str) -> Path | None:
    """Extract road network for city from OSM PBF using osmium or fallback."""
    import subprocess, zipfile, tempfile, shutil

    pbf = RAW / "transport" / "china-latest.osm.pbf"
    if not pbf.exists():
        logger.warning("OSM PBF not found: %s", pbf)
        return None

    out_path = OUT / f"road_network_{code}.json"
    if out_path.exists():
        logger.info("Road network for %s already exists, skipping", city_cn)
        return out_path

    bounds = CITY_BOUNDS.get(city_cn)
    bbox = ",".join(str(x) for x in bounds) if bounds else None

    try:
        # Try osmium tool first
        tmp_out = OUT / f"_road_tmp_{code}.geojson"
        cmd = [
            "osmium", "export",
            "-o", str(tmp_out),
            "--geometry-types=linestring",
        ]
        if bbox:
            cmd.extend(["-b", bbox])
        cmd.append(str(pbf))
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
        if result.returncode == 0 and tmp_out.exists():
            with open(tmp_out, "r", encoding="utf-8") as f:
                data = json.load(f)
            os.remove(tmp_out)
            # Convert to our format
            fc = {"type": "FeatureCollection", "features": data.get("features", [])}
            with open(out_path, "w", encoding="utf-8") as f:
                json.dump(fc, f)
            logger.info("Road network %s: %d features", city_cn, len(fc["features"]))
            return out_path
    except Exception as e:
        logger.warning("osmium failed for %s: %s, trying fallback", city_cn, e)

    # Fallback: skip road network, will use buffer-based fallback
    logger.warning("Road network skipped for %s (no osmium)", city_cn)
    return None


# ── Main ─────────────────────────────────────────────────────────────────────
def main():
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")

    # ── 1. Metro network JSON ─────────────────────────────────────────────────
    logger.info("=== Building metro_network.json ===")
    metro_base = RAW / "transport" / "Metro station&line"
    metro_net = {}
    for city_cn, (code, _) in CITY_MAP.items():
        city_path = metro_base / city_cn
        station_files = list(city_path.glob("*地铁站点*wgs84.csv"))
        line_files = list(city_path.glob("*地铁线路*wgs84.csv"))
        if not station_files:
            logger.warning("No station CSV for %s", city_cn)
            continue
        stations = _parse_station_csv(station_files[0], code, city_cn)
        lines = _parse_line_csv(line_files[0], code, city_cn) if line_files else []
        metro_net[code] = {"stations": stations, "lines": lines}
        logger.info("%s (%s): %d stations, %d lines", city_cn, code, len(stations), len(lines))

    out_metro = OUT / "metro_network.json"
    with open(out_metro, "w", encoding="utf-8") as f:
        json.dump(metro_net, f, ensure_ascii=False)
    print(f"metro_network.json -> {out_metro} ({len(metro_net)} cities)")

    # ── 2. Road networks ──────────────────────────────────────────────────────
    logger.info("=== Extracting road networks ===")
    for city_cn, (code, _) in CITY_MAP.items():
        process_road_network(city_cn, code)

    # ── 3. City-year index ────────────────────────────────────────────────────
    idx = {}
    pop_dir = RAW / "urban" / "population"
    for city_cn, (code, _) in CITY_MAP.items():
        pd_dir = pop_dir / city_cn
        if not pd_dir.exists():
            continue
        years = []
        for f in os.listdir(pd_dir):
            if f.endswith(".tif") and "_" in f:
                try:
                    yr = int(f.split("_")[1].replace(".tif", ""))
                    if 2000 <= yr <= 2023:
                        years.append(yr)
                except ValueError:
                    pass
        years = sorted(years)
        if years:
            idx[code] = years
    idx_out = OUT / "city_year_index.json"
    with open(idx_out, "w", encoding="utf-8") as f:
        json.dump(idx, f, ensure_ascii=False, indent=2)
    print(f"city_year_index.json -> {idx_out}")
    for c, ys in idx.items():
        print(f"  {c}: {min(ys)}-{max(ys)} ({len(ys)} years)")

    # ── 4. GDP: 2000-2023 via linear interpolation (every year) ───────────────
    logger.info("=== Processing GDP (interpolating 2000-2023) ===")
    for city_cn, (code, _) in CITY_MAP.items():
        for year in range(2000, 2024):
            out_gdp = OUT / f"gdp_{city_cn}_{year}.geojson"
            if out_gdp.exists():
                continue
            process_gdp_geojson(city_cn, year, OUT)

    # ── 5. Population: existing TIF years ────────────────────────────────────
    logger.info("=== Processing Population GeoJSON ===")
    for city_cn, (code, _) in CITY_MAP.items():
        for year in range(2000, 2024):
            out_pop = OUT / f"population_{city_cn}_{year}.geojson"
            if out_pop.exists():
                continue
            process_population_geojson(city_cn, year, OUT)

    # ── 6. POI: 2014-2023 (available years) ───────────────────────────────────
    logger.info("=== Processing POI GeoJSON ===")
    poi_years = list(range(2014, 2024))
    for city_cn, (code, _) in CITY_MAP.items():
        for year in poi_years:
            out_poi = OUT / f"poi_{city_cn}_{year}.geojson"
            if out_poi.exists():
                continue
            process_poi_geojson(city_cn, year, OUT)

    print("\nPreprocessing complete.")
    print(f"Output directory: {OUT}")


if __name__ == "__main__":
    main()
