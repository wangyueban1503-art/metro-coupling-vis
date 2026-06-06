"""Station-area generation: 1260m walking buffer (per algorithm spec).

Implementation notes:
  - Primary path: geopandas + shapely (CRS-aware, produces real metric buffers).
  - Fallback path: equirectangular projection around each station (good enough
    for 1.26 km radii at all latitudes the data covers), used when geopandas is
    not installed.  The output schema is identical so downstream code does not
    need to branch.
"""
from __future__ import annotations

import json
import logging
import math
from pathlib import Path
from typing import Any, Dict, List

from . import data_loader as dl
from .config import METRIC_CRS, PROCESSED_DIR, STATION_RADIUS_M, WGS84

logger = logging.getLogger(__name__)


def _buffer_polygon_wgs84(lon: float, lat: float, radius_m: float, n: int = 64) -> List[List[float]]:
    """Approximate a metric buffer as a regular polygon in WGS84."""
    # Local equirectangular: 1 deg lat ≈ 111320 m, 1 deg lon ≈ 111320*cos(lat) m
    m_per_deg_lat = 111320.0
    m_per_deg_lon = 111320.0 * math.cos(math.radians(lat))
    if m_per_deg_lon < 1e-6:
        m_per_deg_lon = 1e-6
    coords = []
    for i in range(n):
        ang = 2 * math.pi * i / n
        dx = math.cos(ang) * radius_m
        dy = math.sin(ang) * radius_m
        coords.append([lon + dx / m_per_deg_lon, lat + dy / m_per_deg_lat])
    coords.append(coords[0])
    return coords


def build_station_areas(city_code: str, year: int) -> Dict[str, Any]:
    stations = dl.load_stations(city_code)
    if not stations:
        logger.warning("No stations for %s", city_code)
        return {"type": "FeatureCollection", "features": []}

    # filter by open_year if available
    filtered = [s for s in stations if s.get("open_year") and s["open_year"] <= year]

    features: List[Dict[str, Any]] = []

    if dl.HAS_GPD:
        import geopandas as gpd
        from shapely.geometry import Point
        gdf = gpd.GeoDataFrame(
            filtered,
            geometry=[Point(s["lon"], s["lat"]) for s in filtered],
            crs=WGS84,
        )
        gdf_m = gdf.to_crs(METRIC_CRS)
        gdf_m["geometry"] = gdf_m.geometry.buffer(STATION_RADIUS_M)
        gdf_m["area_m2"] = gdf_m.geometry.area
        gdf_w = gdf_m.to_crs(WGS84)
        for _, row in gdf_w.iterrows():
            geom = row.geometry
            if geom is None or geom.is_empty:
                continue
            if not geom.is_valid:
                geom = geom.buffer(0)
            features.append({
                "type": "Feature",
                "geometry": json.loads(json.dumps(geom.__geo_interface__)),
                "properties": {
                    "city": city_code,
                    "year": year,
                    "station_id": row["station_id"],
                    "station_name": row["station_name"],
                    "line_name": row.get("line_name"),
                    "method": "buffer_1260m",
                    "radius_m": STATION_RADIUS_M,
                    "area_m2": float(row["area_m2"]),
                },
            })
    else:
        # Fallback: polygon approximation, area computed analytically (pi r^2)
        area = math.pi * STATION_RADIUS_M ** 2
        for s in filtered:
            poly = _buffer_polygon_wgs84(s["lon"], s["lat"], STATION_RADIUS_M)
            features.append({
                "type": "Feature",
                "geometry": {"type": "Polygon", "coordinates": [poly]},
                "properties": {
                    "city": city_code,
                    "year": year,
                    "station_id": s["station_id"],
                    "station_name": s["station_name"],
                    "line_name": s.get("line_name"),
                    "method": "buffer_1260m",
                    "radius_m": STATION_RADIUS_M,
                    "area_m2": area,
                },
            })

    fc = {
        "type": "FeatureCollection",
        "cityCode": city_code,
        "year": year,
        "walkRadiusMeters": STATION_RADIUS_M,
        "method": "buffer_1260m",
        "features": features,
    }
    return fc


def save_station_areas(city_code: str, year: int, fc: Dict[str, Any]) -> Path:
    out = PROCESSED_DIR / f"station_area_{city_code}_{year}.geojson"
    with open(out, "w", encoding="utf-8") as f:
        json.dump(fc, f, ensure_ascii=False)
    return out
