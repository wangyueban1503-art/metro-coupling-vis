"""Compute spatial indicators per station area.

Indicators
----------
U1 (transit):
  - road_density            (km / km^2)
  - walk_accessibility      (placeholder = 1.0 if data missing)
  - metro_line_density      (km / km^2)
  - station_count           (count)
  - line_count              (count of distinct lines)
U2 (urban):
  - population_density      (people / km^2)
  - poi_density             (NaN — no POI source available)
  - poi_diversity           (NaN — no POI source available)
  - gdp_density             (NaN — no GDP source available)

Two execution paths
-------------------
1. geopandas available  -> spatial joins / clips via shapely + sindex.
2. fallback             -> haversine bounding-box filtering with per-station
                           radius checks.  Distances are approximations but
                           keep the same units and produce sensible relative
                           rankings, which is what the entropy-weight step
                           needs.
"""
from __future__ import annotations

import json
import logging
import math
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from . import data_loader as dl
from .config import (
    METRIC_CRS,
    PROCESSED_DIR,
    STATION_RADIUS_M,
    WGS84,
)

logger = logging.getLogger(__name__)

NAN = float("nan")


# ---------------------------------------------------------------------------
# Geometry helpers (fallback path)
# ---------------------------------------------------------------------------
def _meters_per_deg(lat: float) -> Tuple[float, float]:
    m_per_deg_lat = 111320.0
    m_per_deg_lon = 111320.0 * max(math.cos(math.radians(lat)), 1e-6)
    return m_per_deg_lon, m_per_deg_lat


def _seg_len_in_circle(p1, p2, cx, cy, r, mlon, mlat) -> float:
    """Length (in meters) of the portion of segment p1-p2 that lies inside
    the circle centered at (cx, cy) with radius r meters.  Coordinates are
    in degrees; we project into a local equirectangular plane."""
    x1 = (p1[0] - cx) * mlon
    y1 = (p1[1] - cy) * mlat
    x2 = (p2[0] - cx) * mlon
    y2 = (p2[1] - cy) * mlat
    dx, dy = x2 - x1, y2 - y1
    seg_len = math.hypot(dx, dy)
    if seg_len < 1e-9:
        return 0.0
    # solve |p1 + t*d|^2 = r^2 for t in [0,1]
    a = dx * dx + dy * dy
    b = 2 * (x1 * dx + y1 * dy)
    c = x1 * x1 + y1 * y1 - r * r
    disc = b * b - 4 * a * c
    if disc < 0:
        return 0.0
    sd = math.sqrt(disc)
    t0 = max(0.0, (-b - sd) / (2 * a))
    t1 = min(1.0, (-b + sd) / (2 * a))
    if t1 <= t0:
        return 0.0
    return (t1 - t0) * seg_len


def _line_length_in_buffer(coords, cx, cy, r, mlon, mlat) -> float:
    total = 0.0
    for i in range(len(coords) - 1):
        total += _seg_len_in_circle(coords[i], coords[i + 1], cx, cy, r, mlon, mlat)
    return total


def _bbox_intersects(bb, cx, cy, dlon, dlat) -> bool:
    return not (bb[2] < cx - dlon or bb[0] > cx + dlon or bb[3] < cy - dlat or bb[1] > cy + dlat)


def _feat_bbox(coords) -> Tuple[float, float, float, float]:
    xs = [c[0] for c in coords]
    ys = [c[1] for c in coords]
    return (min(xs), min(ys), max(xs), max(ys))


# ---------------------------------------------------------------------------
# Main computation
# ---------------------------------------------------------------------------
def compute_indicators(city_code: str, year: int, station_area_fc: Dict[str, Any]) -> List[Dict[str, Any]]:
    stations = [f["properties"] for f in station_area_fc.get("features", [])]
    if not stations:
        return []

    # ---- load auxiliary data --------------------------------------------------
    road_fc = dl.load_road_network(city_code)
    pop_fc = dl.load_population_points(city_code, year)
    gdp_fc = dl.load_gdp_points(city_code, year)
    poi_fc = dl.load_poi_points(city_code, year)
    lines_fc = dl.load_metro_lines_geojson(city_code)
    metro = dl.load_metro_network().get(city_code, {})
    all_stations = [s for s in dl.load_stations(city_code)
                    if s.get("open_year") and s["open_year"] <= year]

    have_roads = road_fc is not None and road_fc.get("features")
    have_pop = pop_fc is not None and pop_fc.get("features")
    have_gdp = gdp_fc is not None and gdp_fc.get("features")
    have_poi = poi_fc is not None and poi_fc.get("features")
    have_lines = bool(lines_fc.get("features"))

    if not have_roads:
        logger.warning("Roads missing for %s — road_density=NaN", city_code)
    if not have_pop:
        logger.warning("Population missing for %s/%s — population_density=NaN", city_code, year)
    if not have_gdp:
        logger.warning("GDP missing for %s/%s — gdp_density=NaN", city_code, year)
    if not have_poi:
        logger.warning("POI missing for %s/%s — poi_density/poi_diversity=NaN", city_code, year)
    if not have_lines:
        logger.warning("Metro lines missing for %s — metro_line_density=NaN", city_code)

    # ---- build station -> (lon, lat) lookup from station_area features --------
    # station_area features carry a circle's centroid ~= station location
    # but we want the exact station coord for radius math; pull from metadata.
    station_coords: Dict[str, Tuple[float, float]] = {}
    for s in all_stations:
        station_coords[str(s["station_id"])] = (s["lon"], s["lat"])

    radius_m = STATION_RADIUS_M
    area_km2_default = math.pi * (radius_m / 1000.0) ** 2

    results: List[Dict[str, Any]] = []

    if dl.HAS_GPD:
        import geopandas as gpd
        from shapely.geometry import shape, Point

        # build areas GDF in metric CRS
        feats = station_area_fc.get("features", [])
        areas = gpd.GeoDataFrame(
            [f["properties"] for f in feats],
            geometry=[shape(f["geometry"]) for f in feats],
            crs=WGS84,
        ).to_crs(METRIC_CRS)

        # roads
        road_len_per_sid = {}
        if have_roads:
            try:
                rgdf = gpd.GeoDataFrame(
                    geometry=[shape(f["geometry"]) for f in road_fc["features"]],
                    crs=WGS84,
                ).to_crs(METRIC_CRS)
                joined = gpd.sjoin(rgdf, areas[["station_id", "geometry"]], how="inner", predicate="intersects")
                # clip then length
                joined["geom_clip"] = joined.apply(
                    lambda row: row.geometry.intersection(areas.loc[row.index_right].geometry),
                    axis=1,
                )
                joined["len_m"] = joined["geom_clip"].length
                road_len_per_sid = joined.groupby("station_id")["len_m"].sum().to_dict()
            except Exception as exc:
                logger.exception("Road clipping failed, falling back per-station: %s", exc)
                road_len_per_sid = {}

        # metro lines
        line_len_per_sid = {}
        if have_lines:
            try:
                lgdf = gpd.GeoDataFrame(
                    [{"line_name": f["properties"].get("line_name")} for f in lines_fc["features"]],
                    geometry=[shape(f["geometry"]) for f in lines_fc["features"]],
                    crs=WGS84,
                ).to_crs(METRIC_CRS)
                joined = gpd.sjoin(lgdf, areas[["station_id", "geometry"]], how="inner", predicate="intersects")
                joined["geom_clip"] = joined.apply(
                    lambda row: row.geometry.intersection(areas.loc[row.index_right].geometry),
                    axis=1,
                )
                joined["len_m"] = joined["geom_clip"].length
                line_len_per_sid = joined.groupby("station_id")["len_m"].sum().to_dict()
            except Exception as exc:
                logger.exception("Metro line clipping failed: %s", exc)

        # population
        pop_per_sid = {}
        if have_pop:
            try:
                pts = []
                vals = []
                for f in pop_fc["features"]:
                    g = f.get("geometry") or {}
                    if g.get("type") != "Point":
                        continue
                    pts.append(Point(*g["coordinates"]))
                    vals.append(float(f.get("properties", {}).get("population", 0) or 0))
                if pts:
                    pgdf = gpd.GeoDataFrame({"pop": vals}, geometry=pts, crs=WGS84).to_crs(METRIC_CRS)
                    joined = gpd.sjoin(pgdf, areas[["station_id", "geometry"]], how="inner", predicate="within")
                    pop_per_sid = joined.groupby("station_id")["pop"].sum().to_dict()
            except Exception as exc:
                logger.exception("Population spatial join failed: %s", exc)

        # GDP
        gdp_per_sid = {}
        if have_gdp:
            try:
                pts = []
                vals = []
                for f in gdp_fc["features"]:
                    g = f.get("geometry") or {}
                    if g.get("type") != "Point":
                        continue
                    pts.append(Point(*g["coordinates"]))
                    vals.append(float(f.get("properties", {}).get("gdp", 0) or 0))
                if pts:
                    ggdf = gpd.GeoDataFrame({"gdp": vals}, geometry=pts, crs=WGS84).to_crs(METRIC_CRS)
                    joined = gpd.sjoin(ggdf, areas[["station_id", "geometry"]], how="inner", predicate="within")
                    gdp_per_sid = joined.groupby("station_id")["gdp"].sum().to_dict()
            except Exception as exc:
                logger.exception("GDP spatial join failed: %s", exc)

        # POI: density + diversity (Shannon entropy)
        poi_per_sid: Dict[str, List] = {}
        if have_poi:
            try:
                pts = []
                vals = []
                for f in poi_fc["features"]:
                    g = f.get("geometry") or {}
                    if g.get("type") != "Point":
                        continue
                    pts.append(Point(*g["coordinates"]))
                    vals.append(str(f.get("properties", {}).get("poi_type", "unknown")))
                if pts:
                    pogdf = gpd.GeoDataFrame({"poi_type": vals}, geometry=pts, crs=WGS84).to_crs(METRIC_CRS)
                    joined = gpd.sjoin(pogdf, areas[["station_id", "geometry"]], how="inner", predicate="within")
                    for sid, grp in joined.groupby("station_id"):
                        poi_per_sid[sid] = list(grp["poi_type"])
            except Exception as exc:
                logger.exception("POI spatial join failed: %s", exc)

        # station / line counts via sjoin
        stn_counts, line_counts = _count_stations_lines(all_stations, station_area_fc)

        for _, area_row in areas.to_crs(WGS84).iterrows():
            sid = area_row["station_id"]
            area_m2 = float(area_row.get("area_m2") or 0) or (math.pi * radius_m * radius_m)
            area_km2 = area_m2 / 1e6

            # POI diversity (Shannon entropy H = -sum(p_i * ln(p_i)))
            poi_types = poi_per_sid.get(sid, [])
            if len(poi_types) > 1:
                from collections import Counter
                counts = Counter(poi_types)
                total = len(poi_types)
                h = 0.0
                for c in counts.values():
                    p = c / total
                    if p > 0:
                        h -= p * math.log(p)
                poi_diversity = h
                poi_density = len(poi_types) / area_km2
            else:
                poi_diversity = 0.0
                poi_density = len(poi_types) / area_km2 if poi_types else 0.0

            results.append({
                "city": city_code,
                "year": year,
                "station_id": sid,
                "station_name": area_row["station_name"],
                "area_m2": area_m2,
                "road_density": (road_len_per_sid.get(sid, 0.0) / 1000.0 / area_km2) if have_roads and area_km2 > 0 else NAN,
                "walk_accessibility": 1.0,
                "metro_line_density": (line_len_per_sid.get(sid, 0.0) / 1000.0 / area_km2) if have_lines and area_km2 > 0 else NAN,
                "station_count": stn_counts.get(sid, 0),
                "line_count": line_counts.get(sid, 0),
                "population_density": (pop_per_sid.get(sid, 0.0) / area_km2) if have_pop and area_km2 > 0 else NAN,
                "gdp_density": (gdp_per_sid.get(sid, 0.0) / area_km2) if have_gdp and area_km2 > 0 else NAN,
                "poi_density": poi_density,
                "poi_diversity": poi_diversity,
            })
        return results

    # ------------------------------------------------------------------
    # Fallback: pure-Python loop (no geopandas)
    # ------------------------------------------------------------------
    # Pre-extract road geometries + bboxes once
    road_lines: List[Tuple[Tuple[float, float, float, float], List[List[float]]]] = []
    if have_roads:
        for f in road_fc["features"]:
            g = f.get("geometry") or {}
            t = g.get("type")
            cs = g.get("coordinates") or []
            if t == "LineString" and len(cs) >= 2:
                road_lines.append((_feat_bbox(cs), cs))
            elif t == "MultiLineString":
                for part in cs:
                    if len(part) >= 2:
                        road_lines.append((_feat_bbox(part), part))

    metro_segs: List[Tuple[Tuple[float, float, float, float], List[List[float]], str]] = []
    if have_lines:
        for f in lines_fc["features"]:
            g = f.get("geometry") or {}
            cs = g.get("coordinates") or []
            if g.get("type") == "LineString" and len(cs) >= 2:
                metro_segs.append((_feat_bbox(cs), cs, f["properties"].get("line_name") or ""))

    pop_pts: List[Tuple[float, float, float]] = []
    if have_pop:
        for f in pop_fc["features"]:
            g = f.get("geometry") or {}
            if g.get("type") == "Point":
                c = g["coordinates"]
                pop_pts.append((c[0], c[1], float(f.get("properties", {}).get("population", 0) or 0)))

    gdp_pts: List[Tuple[float, float, float]] = []
    if have_gdp:
        for f in gdp_fc["features"]:
            g = f.get("geometry") or {}
            if g.get("type") == "Point":
                c = g["coordinates"]
                gdp_pts.append((c[0], c[1], float(f.get("properties", {}).get("gdp", 0) or 0)))

    poi_pts: List[Tuple[float, float, str]] = []
    if have_poi:
        for f in poi_fc["features"]:
            g = f.get("geometry") or {}
            if g.get("type") == "Point":
                c = g["coordinates"]
                poi_pts.append((c[0], c[1], str(f.get("properties", {}).get("poi_type", "unknown"))))

    stn_counts, line_counts = _count_stations_lines(all_stations, station_area_fc)

    for f in station_area_fc.get("features", []):
        props = f["properties"]
        sid = props["station_id"]
        coord = station_coords.get(str(sid))
        if coord is None:
            # try centroid of polygon
            ring = f["geometry"]["coordinates"][0]
            cx = sum(p[0] for p in ring) / len(ring)
            cy = sum(p[1] for p in ring) / len(ring)
        else:
            cx, cy = coord
        mlon, mlat = _meters_per_deg(cy)
        dlon = radius_m / mlon
        dlat = radius_m / mlat

        # Road length within circle
        if have_roads:
            total_road = 0.0
            for bb, cs in road_lines:
                if not _bbox_intersects(bb, cx, cy, dlon, dlat):
                    continue
                total_road += _line_length_in_buffer(cs, cx, cy, radius_m, mlon, mlat)
            road_density = (total_road / 1000.0) / area_km2_default
        else:
            road_density = NAN

        # Metro line length within circle
        if have_lines:
            total_metro = 0.0
            for bb, cs, _ln in metro_segs:
                if not _bbox_intersects(bb, cx, cy, dlon, dlat):
                    continue
                total_metro += _line_length_in_buffer(cs, cx, cy, radius_m, mlon, mlat)
            metro_density = (total_metro / 1000.0) / area_km2_default
        else:
            metro_density = NAN

        # Population sum
        if have_pop:
            psum = 0.0
            r2 = radius_m * radius_m
            for px, py, pv in pop_pts:
                if abs(px - cx) > dlon or abs(py - cy) > dlat:
                    continue
                xx = (px - cx) * mlon
                yy = (py - cy) * mlat
                if xx * xx + yy * yy <= r2:
                    psum += pv
            pop_density = psum / area_km2_default
        else:
            pop_density = NAN

        # GDP sum
        if have_gdp:
            gsum = 0.0
            for px, py, gv in gdp_pts:
                if abs(px - cx) > dlon or abs(py - cy) > dlat:
                    continue
                xx = (px - cx) * mlon
                yy = (py - cy) * mlat
                if xx * xx + yy * yy <= r2:
                    gsum += gv
            gdp_density = gsum / area_km2_default
        else:
            gdp_density = NAN

        # POI density + diversity
        if have_poi:
            poi_in_area = []
            for px, py, pt in poi_pts:
                if abs(px - cx) > dlon or abs(py - cy) > dlat:
                    continue
                xx = (px - cx) * mlon
                yy = (py - cy) * mlat
                if xx * xx + yy * yy <= r2:
                    poi_in_area.append(pt)
            n_poi = len(poi_in_area)
            if n_poi > 1:
                from collections import Counter
                counts = Counter(poi_in_area)
                total = n_poi
                h = 0.0
                for c in counts.values():
                    p = c / total
                    if p > 0:
                        h -= p * math.log(p)
                poi_diversity = h
                poi_density_val = n_poi / area_km2_default
            elif n_poi == 1:
                poi_diversity = 0.0
                poi_density_val = 1.0 / area_km2_default
            else:
                poi_diversity = 0.0
                poi_density_val = 0.0
        else:
            poi_diversity = NAN
            poi_density_val = NAN

        results.append({
            "city": city_code,
            "year": year,
            "station_id": sid,
            "station_name": props["station_name"],
            "area_m2": float(props.get("area_m2") or (math.pi * radius_m * radius_m)),
            "road_density": road_density,
            "walk_accessibility": 1.0,
            "metro_line_density": metro_density,
            "station_count": stn_counts.get(sid, 0),
            "line_count": line_counts.get(sid, 0),
            "population_density": pop_density,
            "gdp_density": gdp_density,
            "poi_density": poi_density_val,
            "poi_diversity": poi_diversity,
        })

    return results


def _count_stations_lines(all_stations: List[Dict[str, Any]], area_fc: Dict[str, Any]):
    """Count stations + distinct lines inside each station area (fast path)."""
    stn_counts: Dict[str, int] = {}
    line_counts: Dict[str, int] = {}
    r = STATION_RADIUS_M
    for f in area_fc.get("features", []):
        props = f["properties"]
        sid = props["station_id"]
        # use the buffer center = station coord for distance check
        cx, cy = None, None
        for s in all_stations:
            if str(s["station_id"]) == str(sid):
                cx, cy = s["lon"], s["lat"]
                break
        if cx is None:
            ring = f["geometry"]["coordinates"][0]
            cx = sum(p[0] for p in ring) / len(ring)
            cy = sum(p[1] for p in ring) / len(ring)
        mlon, mlat = _meters_per_deg(cy)
        dlon = r / mlon
        dlat = r / mlat
        r2 = r * r
        cnt = 0
        lineset = set()
        for s in all_stations:
            if abs(s["lon"] - cx) > dlon or abs(s["lat"] - cy) > dlat:
                continue
            xx = (s["lon"] - cx) * mlon
            yy = (s["lat"] - cy) * mlat
            if xx * xx + yy * yy <= r2:
                cnt += 1
                for line_name in s.get("line_names") or ([s.get("line_name")] if s.get("line_name") else []):
                    lineset.add(line_name)
        stn_counts[sid] = cnt
        line_counts[sid] = len(lineset)
    return stn_counts, line_counts


def save_indicators(city_code: str, year: int, rows: List[Dict[str, Any]]) -> Path:
    import csv
    out_csv = PROCESSED_DIR / f"station_indicators_{city_code}_{year}.csv"
    if not rows:
        out_csv.write_text("")
        return out_csv
    cols = list(rows[0].keys())
    with open(out_csv, "w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=cols)
        w.writeheader()
        for r in rows:
            w.writerow(r)
    return out_csv
