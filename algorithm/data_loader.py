"""Data loader with column-name adaptation for the metro-TOD dataset.

Most files in data/ already follow a known schema, but this module also
tries flexible column-name detection so future CSV/SHP inputs can drop in.

Geometry strategy:
  - Avoid hard dependence on geopandas/shapely so that the module can
    still import in environments where the heavy GIS stack is missing.
    Where geopandas is available we use it; otherwise we fall back to a
    light dict-based representation for stations + lazy parsing of
    GeoJSON via shapely-only helpers.
"""
from __future__ import annotations

import json
import logging
import math
from functools import lru_cache
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

from .config import DATA_DIR, ROOT_DIR, WGS84

logger = logging.getLogger(__name__)

# City code <-> Chinese name mapping
CITY_NAME_TO_CODE = {
    "上海市": "310000", "北京": "110000", "广州市": "440100",
    "成都市": "510100", "杭州市": "330100", "深圳市": "440300",
}
CODE_TO_CITY_NAME = {v: k for k, v in CITY_NAME_TO_CODE.items()}

try:
    import geopandas as gpd
    from shapely.geometry import shape, Point, LineString, Polygon, MultiPolygon
    HAS_GPD = True
except Exception:  # pragma: no cover - environment without geopandas
    gpd = None
    HAS_GPD = False
    try:
        from shapely.geometry import shape, Point, LineString, Polygon, MultiPolygon
    except Exception:
        shape = Point = LineString = Polygon = MultiPolygon = None

STATION_ID_KEYS = ["station_id", "id", "sid", "站点ID", "站点编号", "站点id"]
STATION_NAME_KEYS = ["station_name", "name", "站点名称", "站名", "名称", "stationName"]
CITY_KEYS = ["city", "城市", "city_name", "cityCode"]
YEAR_KEYS = ["year", "年份", "date"]
LON_KEYS = ["lon", "lng", "longitude", "经度"]
LAT_KEYS = ["lat", "latitude", "纬度"]
LINE_KEYS = ["line", "line_name", "线路", "线路名称", "line_id", "lineId"]
POI_TYPE_KEYS = ["poi_type", "type", "category", "类别", "类型"]
POP_KEYS = ["population", "pop", "人口", "人口数", "value"]
GDP_KEYS = ["gdp", "GDP", "经济", "value"]


def _pick(d: Dict, keys: Iterable[str]):
    for k in keys:
        if k in d and d[k] is not None and d[k] != "":
            return d[k]
    return None


def list_city_codes() -> List[str]:
    """Cities for which we have both metro network + at least one population year."""
    metro_path = DATA_DIR / "metro_network.json"
    if not metro_path.exists():
        return []
    with open(metro_path, "r", encoding="utf-8") as f:
        d = json.load(f)
    return list(d.keys())


@lru_cache(maxsize=1)
def load_city_metadata() -> Dict[str, Any]:
    p = DATA_DIR / "city_metadata.json"
    if not p.exists():
        return {}
    with open(p, "r", encoding="utf-8") as f:
        return json.load(f)


@lru_cache(maxsize=1)
def load_metro_network() -> Dict[str, Any]:
    p = DATA_DIR / "metro_network.json"
    with open(p, "r", encoding="utf-8") as f:
        return json.load(f)


def load_stations(city_code: str) -> List[Dict[str, Any]]:
    """Return a list of station dicts with normalized fields."""
    metro = load_metro_network().get(city_code)
    if not metro:
        logger.warning("No metro_network entry for %s", city_code)
        return []
    stations = []
    for s in metro.get("stations", []):
        sid = _pick(s, STATION_ID_KEYS) or s.get("id")
        name = _pick(s, STATION_NAME_KEYS) or s.get("name")
        lon = _pick(s, LON_KEYS)
        lat = _pick(s, LAT_KEYS)
        line = _pick(s, LINE_KEYS) or s.get("line_id")
        if lon is None or lat is None:
            continue
        line_names = s.get("line_names")
        if not line_names:
            line_names = [line] if line else []
        stations.append({
            "city": city_code,
            "station_id": str(sid) if sid is not None else f"{city_code}_{name}",
            "station_name": name,
            "lon": float(lon),
            "lat": float(lat),
            "line_name": line,
            "line_names": line_names,
            "open_year": s.get("open_year"),
        })
    return stations


def load_metro_lines_geojson(city_code: str) -> Dict[str, Any]:
    """Return metro lines as a GeoJSON FeatureCollection (LineString features)."""
    metro = load_metro_network().get(city_code, {})
    feats = []
    for line in metro.get("lines", []):
        coords = line.get("coordinates")
        if not coords or len(coords) < 2:
            continue
        feats.append({
            "type": "Feature",
            "geometry": {"type": "LineString", "coordinates": coords},
            "properties": {
                "line_id": line.get("id"),
                "line_name": line.get("name"),
                "color": line.get("color"),
                "open_year": line.get("open_year", 0),
            },
        })
    return {"type": "FeatureCollection", "features": feats}


@lru_cache(maxsize=8)
def load_road_network(city_code: str) -> Optional[Dict[str, Any]]:
    # Analytical routines must use the complete road network. The frontend has
    # separate tiled road files for display; using those sampled display files
    # here creates broken topology and incorrect station areas.
    p = DATA_DIR / f"road_network_{city_code}.json"
    if not p.exists():
        logger.warning("No road network for %s", city_code)
        return None
    with open(p, "r", encoding="utf-8") as f:
        return json.load(f)


def load_population_points(city_code: str, year: int) -> Optional[Dict[str, Any]]:
    """Load population GeoJSON for city/year.

    New format (preprocessed TIF -> GeoJSON):
      GEN_DATA_DIR / "population_{city_name}_{year}.geojson"

    Old fallback:
      GEN_DATA_DIR / "population_geojson" / {city_code} / {year}.geojson
    """
    import glob as _g

    # 1. Try new format: population_{city_name}_{year}.geojson
    city_name = CODE_TO_CITY_NAME.get(city_code, city_code)
    new_path = DATA_DIR / f"population_{city_name}_{year}.geojson"
    if new_path.exists():
        with open(new_path, "r", encoding="utf-8") as f:
            return json.load(f)

    # 2. Fallback: glob for any population_*_{year}.geojson containing this city
    matches = _g.glob(str(DATA_DIR / f"population_*_{year}.geojson"))
    for m in matches:
        fname = Path(m).stem  # e.g. population_上海市_2023
        if city_name in fname:
            with open(m, "r", encoding="utf-8") as f:
                return json.load(f)

    # 3. Old format
    p = DATA_DIR / "population_geojson" / city_code / f"{year}.geojson"
    if not p.exists():
        folder = DATA_DIR / "population_geojson" / city_code
        if folder.exists():
            years = sorted(int(f.stem) for f in folder.glob("*.geojson") if f.stem.isdigit())
            if years:
                nearest = min(years, key=lambda y: abs(y - year))
                p = folder / f"{nearest}.geojson"
                logger.info("Population for %s/%s not found, using %s", city_code, year, nearest)
            else:
                return None
        else:
            return None
    with open(p, "r", encoding="utf-8") as f:
        return json.load(f)


def list_population_years(city_code: str) -> List[int]:
    import glob as _g
    city_name = CODE_TO_CITY_NAME.get(city_code, city_code)
    years = set()
    for m in _g.glob(str(DATA_DIR / f"population_{city_name}_*.geojson")):
        try:
            years.add(int(Path(m).stem.split("_")[-1]))
        except ValueError:
            pass
    folder = DATA_DIR / "population_geojson" / city_code
    if folder.exists():
        years.update(int(f.stem) for f in folder.glob("*.geojson") if f.stem.isdigit())
    return sorted(years)


def haversine_m(lon1, lat1, lon2, lat2) -> float:
    R = 6371000.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlam = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dlam / 2) ** 2
    return 2 * R * math.asin(math.sqrt(a))


def load_gdp_points(city_code: str, year: int) -> Optional[Dict[str, Any]]:
    """Load GDP point GeoJSON for city/year (interpolated from base years)."""
    city_name = CODE_TO_CITY_NAME.get(city_code, city_code)
    p = DATA_DIR / f"gdp_{city_name}_{year}.geojson"
    if p.exists():
        with open(p, "r", encoding="utf-8") as f:
            return json.load(f)
    # Fallback: try any matching glob
    import glob as _g
    matches = _g.glob(str(DATA_DIR / f"gdp_*_{year}.geojson"))
    for m in matches:
        if city_name in Path(m).stem:
            with open(m, "r", encoding="utf-8") as f:
                return json.load(f)
    return None


def load_poi_points(city_code: str, year: int) -> Optional[Dict[str, Any]]:
    """Load POI point GeoJSON for city/year."""
    city_name = CODE_TO_CITY_NAME.get(city_code, city_code)
    p = DATA_DIR / f"poi_{city_name}_{year}.geojson"
    if p.exists():
        with open(p, "r", encoding="utf-8") as f:
            return json.load(f)
    import glob as _g
    matches = _g.glob(str(DATA_DIR / f"poi_*_{year}.geojson"))
    for m in matches:
        if city_name in Path(m).stem:
            with open(m, "r", encoding="utf-8") as f:
                return json.load(f)
    return None


def list_gdp_years(city_code: str) -> List[int]:
    """List available GDP years for city."""
    import glob as _g
    city_name = CODE_TO_CITY_NAME.get(city_code, city_code)
    matches = _g.glob(str(DATA_DIR / f"gdp_{city_name}_*.geojson"))
    years = []
    for m in matches:
        try:
            yr = int(Path(m).stem.split("_")[-1])
            years.append(yr)
        except ValueError:
            pass
    return sorted(years)
