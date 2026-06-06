"""15-min walking isochrone station areas based on road network (method 2).

Reference: 算法数学建模.md  路网服务区分析
  S_actual = { v | d_shortest(v0, v) ≤ T · V_walk }
  T = 15 min, V_walk = 1.4 m/s  →  budget ≈ 1260 m (network distance)

Implementation
--------------
1. Build an undirected graph from data/road_network_{city}.json (FeatureCollection
   of LineStrings). Nodes are deduplicated by rounding (lon, lat) to ~1.1 m.
   Edges = consecutive vertex pairs in each LineString, weight = haversine meters.
2. Spatial grid index of node coordinates (degree cells) for nearest-node lookup
   and bbox prefiltering.
3. For each station: locate nearest node, run Dijkstra capped at `budget_m`.
4. Polygon = convex hull of reachable node coordinates (in WGS84). If too few
   reachable nodes, fall back to 1260 m circle.
5. walk_accessibility = isochrone_area_m2 / circle_area_m2  (real value, ≤ 1).

Pure Python — no networkx / osmnx required. Slower than osmnx but works
out-of-the-box with the data already in data/.
"""
from __future__ import annotations

import heapq
import json
import logging
import math
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from . import data_loader as dl
from .config import PROCESSED_DIR, STATION_RADIUS_M, WGS84

logger = logging.getLogger(__name__)

NODE_PRECISION = 4            # rounding decimals -> ~10 m, enough for 15-min catchment topology
BUDGET_M = STATION_RADIUS_M   # 1260 m network distance
GRID_DEG = 0.01               # ~1.1 km grid cells for spatial index
ROAD_BUFFER_M = 45.0          # service strip width around reachable streets
MAX_SEGMENTS_PER_AREA = 5000


def _haversine_m(lon1, lat1, lon2, lat2) -> float:
    R = 6371000.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = math.radians(lat2 - lat1)
    dl = math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * R * math.asin(math.sqrt(a))


def _key(lon, lat):
    return (round(lon, NODE_PRECISION), round(lat, NODE_PRECISION))


def _cell(lon, lat):
    return (int(lon // GRID_DEG), int(lat // GRID_DEG))


def build_graph(city_code: str) -> Optional[Dict[str, Any]]:
    road_fc = dl.load_road_network(city_code)
    if not road_fc:
        return None
    adj: Dict[Tuple[float, float], List[Tuple[Tuple[float, float], float]]] = {}
    grid: Dict[Tuple[int, int], List[Tuple[float, float]]] = {}
    edges: List[Tuple[Tuple[float, float], Tuple[float, float], float]] = []
    edge_grid: Dict[Tuple[int, int], List[Tuple[Tuple[float, float], Tuple[float, float], float]]] = {}

    def add_node(k):
        if k not in adj:
            adj[k] = []
            grid.setdefault(_cell(*k), []).append(k)

    feats = road_fc.get("features", [])
    for f in feats:
        g = f.get("geometry") or {}
        t = g.get("type")
        coords_list = []
        if t == "LineString":
            coords_list = [g.get("coordinates") or []]
        elif t == "MultiLineString":
            coords_list = g.get("coordinates") or []
        else:
            continue
        for cs in coords_list:
            if len(cs) < 2:
                continue
            prev = _key(cs[0][0], cs[0][1])
            add_node(prev)
            for i in range(1, len(cs)):
                cur = _key(cs[i][0], cs[i][1])
                if cur == prev:
                    continue
                add_node(cur)
                w = _haversine_m(prev[0], prev[1], cur[0], cur[1])
                if w > 0:
                    adj[prev].append((cur, w))
                    adj[cur].append((prev, w))
                    edge = (prev, cur, w)
                    edges.append(edge)
                    mx = (prev[0] + cur[0]) / 2
                    my = (prev[1] + cur[1]) / 2
                    edge_grid.setdefault(_cell(mx, my), []).append(edge)
                prev = cur
    logger.info("road graph %s: %d nodes, %d features", city_code, len(adj), len(feats))
    return {"adj": adj, "grid": grid, "edges": edges, "edge_grid": edge_grid}


def nearest_node(graph: Dict[str, Any], lon: float, lat: float, max_search_m: float = 800.0):
    """Return the nearest graph node within max_search_m, or None."""
    grid = graph["grid"]
    # Expand search ring outward until found or limit hit
    cx, cy = _cell(lon, lat)
    best = None
    best_d = float("inf")
    # max_search_m to degree budget
    deg_budget = max(GRID_DEG, max_search_m / 111000.0 + GRID_DEG)
    radius = max(1, int(deg_budget / GRID_DEG) + 1)
    for dx in range(-radius, radius + 1):
        for dy in range(-radius, radius + 1):
            for n in grid.get((cx + dx, cy + dy), ()):
                d = _haversine_m(lon, lat, n[0], n[1])
                if d < best_d:
                    best_d = d
                    best = n
    if best is None or best_d > max_search_m:
        return None
    return best


def nearby_nodes(
    graph: Dict[str, Any],
    lon: float,
    lat: float,
    max_search_m: float = 220.0,
    limit: int = 16,
) -> List[Tuple[Tuple[float, float], float]]:
    """Return nearby graph entry nodes with station-to-network walking cost."""
    grid = graph["grid"]
    cx, cy = _cell(lon, lat)
    deg_budget = max(GRID_DEG, max_search_m / 111000.0 + GRID_DEG)
    radius = max(1, int(deg_budget / GRID_DEG) + 1)
    found: List[Tuple[Tuple[float, float], float]] = []
    seen = set()
    for dx in range(-radius, radius + 1):
        for dy in range(-radius, radius + 1):
            for n in grid.get((cx + dx, cy + dy), ()):
                if n in seen:
                    continue
                seen.add(n)
                d = _haversine_m(lon, lat, n[0], n[1])
                if d <= max_search_m:
                    found.append((n, d))
    found.sort(key=lambda item: item[1])
    return found[:limit]


def dijkstra_distances(graph: Dict[str, Any], start, budget_m: float) -> Dict[Tuple[float, float], float]:
    """Return node -> distance for nodes reachable within budget_m network distance."""
    adj = graph["adj"]
    if start not in adj:
        return {}
    dist = {start: 0.0}
    pq = [(0.0, start)]
    while pq:
        d, u = heapq.heappop(pq)
        if d > dist[u]:
            continue
        if d > budget_m:
            continue
        for v, w in adj[u]:
            nd = d + w
            if nd <= budget_m and nd < dist.get(v, float("inf")):
                dist[v] = nd
                heapq.heappush(pq, (nd, v))
    return dist


def dijkstra_multi_source(
    graph: Dict[str, Any],
    starts: List[Tuple[Tuple[float, float], float]],
    budget_m: float,
) -> Dict[Tuple[float, float], float]:
    """Dijkstra from multiple station access nodes.

    The initial distance is the station-to-road walking distance, so the total
    service area still respects the 15-minute walking budget.
    """
    adj = graph["adj"]
    dist: Dict[Tuple[float, float], float] = {}
    pq = []
    for start, entry_cost in starts:
        if start not in adj or entry_cost > budget_m:
            continue
        if entry_cost < dist.get(start, float("inf")):
            dist[start] = entry_cost
            heapq.heappush(pq, (entry_cost, start))
    while pq:
        d, u = heapq.heappop(pq)
        if d > dist[u] or d > budget_m:
            continue
        for v, w in adj[u]:
            nd = d + w
            if nd <= budget_m and nd < dist.get(v, float("inf")):
                dist[v] = nd
                heapq.heappush(pq, (nd, v))
    return dist


def dijkstra_isochrone(graph: Dict[str, Any], start, budget_m: float) -> List[Tuple[float, float]]:
    """Return all node coords reachable within budget_m network distance."""
    dist = dijkstra_distances(graph, start, budget_m)
    return list(dist.keys())


def _convex_hull(points: List[Tuple[float, float]]) -> List[Tuple[float, float]]:
    """Andrew monotone chain. Input/output in (x, y)."""
    pts = sorted(set(points))
    if len(pts) <= 1:
        return pts
    def cross(o, a, b):
        return (a[0] - o[0]) * (b[1] - o[1]) - (a[1] - o[1]) * (b[0] - o[0])
    lower = []
    for p in pts:
        while len(lower) >= 2 and cross(lower[-2], lower[-1], p) <= 0:
            lower.pop()
        lower.append(p)
    upper = []
    for p in reversed(pts):
        while len(upper) >= 2 and cross(upper[-2], upper[-1], p) <= 0:
            upper.pop()
        upper.append(p)
    return lower[:-1] + upper[:-1]


def _polygon_area_m2(ring_wgs84: List[Tuple[float, float]]) -> float:
    """Geodesic-ish polygon area via equirectangular projection at centroid."""
    if len(ring_wgs84) < 3:
        return 0.0
    cy = sum(p[1] for p in ring_wgs84) / len(ring_wgs84)
    mlon = 111320.0 * math.cos(math.radians(cy))
    mlat = 111320.0
    s = 0.0
    n = len(ring_wgs84)
    for i in range(n):
        x1 = ring_wgs84[i][0] * mlon
        y1 = ring_wgs84[i][1] * mlat
        x2 = ring_wgs84[(i + 1) % n][0] * mlon
        y2 = ring_wgs84[(i + 1) % n][1] * mlat
        s += x1 * y2 - x2 * y1
    return abs(s) / 2.0


def _fallback_circle(lon, lat, r) -> List[List[float]]:
    m_lat = 111320.0
    m_lon = 111320.0 * max(math.cos(math.radians(lat)), 1e-6)
    out = []
    for i in range(64):
        a = 2 * math.pi * i / 64
        out.append([lon + math.cos(a) * r / m_lon, lat + math.sin(a) * r / m_lat])
    out.append(out[0])
    return out


def build_station_feature_from_graph(
    city_code: str,
    year: int,
    station: Dict[str, Any],
    graph: Dict[str, Any],
    budget_m: float = BUDGET_M,
) -> Tuple[Dict[str, Any], bool]:
    """Build one station catchment from an already-built road graph."""
    circle_area = math.pi * budget_m * budget_m
    lon, lat = station["lon"], station["lat"]
    starts = nearby_nodes(graph, lon, lat, max_search_m=260.0, limit=24)
    start = starts[0][0] if starts else nearest_node(graph, lon, lat, max_search_m=1500)
    fallback = False
    if starts:
        distances = dijkstra_multi_source(graph, starts, budget_m)
    elif start is not None:
        distances = dijkstra_distances(graph, start, budget_m)
    else:
        distances = {}

    nodes = list(distances.keys())
    if len(nodes) < 3:
        corridor, area_m2 = _local_road_corridor_polygon(graph, lon, lat, budget_m)
        if corridor is not None and area_m2 > 0:
            geom = json.loads(json.dumps(corridor.__geo_interface__))
            ring = geom.get("coordinates", [[]])[0] if geom.get("type") == "Polygon" else []
            walk_acc = min(1.0, area_m2 / circle_area) if circle_area > 0 else 0.0
            method = "local_corridor_fallback_1260m"
        else:
            ring = _fallback_circle(lon, lat, budget_m)
            area_m2 = circle_area
            walk_acc = 1.0
            method = "buffer_fallback"
            fallback = True
    else:
        corridor, area_m2 = _network_corridor_polygon(graph, distances, lon, lat)
        if corridor is not None and area_m2 > 0:
            geom = json.loads(json.dumps(corridor.__geo_interface__))
            ring = geom.get("coordinates", [[]])[0] if geom.get("type") == "Polygon" else []
            walk_acc = min(1.0, area_m2 / circle_area) if circle_area > 0 else 0.0
            method = "network_corridor_1260m"
        else:
            hull = _convex_hull(nodes)
            if hull[0] != hull[-1]:
                hull.append(hull[0])
            ring = [list(p) for p in hull]
            area_m2 = _polygon_area_m2(hull)
            walk_acc = min(1.0, area_m2 / circle_area) if circle_area > 0 else 0.0
            method = "network_isochrone_1260m"

    return {
        "type": "Feature",
        "geometry": {"type": "Polygon", "coordinates": [ring]},
        "properties": {
            "city": city_code,
            "year": year,
            "station_id": station["station_id"],
            "station_name": station["station_name"],
            "line_name": station.get("line_name"),
            "method": method,
            "radius_m": budget_m,
            "area_m2": area_m2,
            "walk_accessibility": walk_acc,
        },
    }, fallback


def precompute_station_features(
    city_code: str,
    graph: Optional[Dict[str, Any]] = None,
    budget_m: float = BUDGET_M,
) -> Dict[str, Dict[str, Any]]:
    """Compute road-network station areas once per station for batch export."""
    stations = dl.load_stations(city_code)
    if not stations:
        return {}
    graph = graph or build_graph(city_code)
    if not graph:
        return {}

    cache: Dict[str, Dict[str, Any]] = {}
    fallbacks = 0
    for station in stations:
        feature, fallback = build_station_feature_from_graph(city_code, 0, station, graph, budget_m)
        if fallback:
            fallbacks += 1
        cache[str(station["station_id"])] = feature
    logger.info("precomputed isochrone %s: %d stations, %d fallbacks", city_code, len(cache), fallbacks)
    return cache


def feature_collection_from_precomputed(
    city_code: str,
    year: int,
    precomputed: Dict[str, Dict[str, Any]],
    budget_m: float = BUDGET_M,
) -> Dict[str, Any]:
    stations = [
        s for s in dl.load_stations(city_code)
        if s.get("open_year") and s["open_year"] <= year
    ]
    features: List[Dict[str, Any]] = []
    for station in stations:
        feature = precomputed.get(str(station["station_id"]))
        if not feature:
            continue
        copied = json.loads(json.dumps(feature, ensure_ascii=False))
        copied["properties"]["year"] = year
        features.append(copied)

    return {
        "type": "FeatureCollection",
        "cityCode": city_code,
        "year": year,
        "walkRadiusMeters": budget_m,
        "method": "network_isochrone_1260m",
        "features": features,
    }


def _network_corridor_polygon(
    graph: Dict[str, Any],
    distances: Dict[Tuple[float, float], float],
    station_lon: float,
    station_lat: float,
):
    """Build an irregular station area from reachable road segments.

    Instead of a circular buffer or a convex hull, this buffers reachable road
    centerlines. The resulting polygon follows local street topology, matching
    the station-area interpretation of a 15-minute walking service zone.
    """
    try:
        from shapely.geometry import MultiLineString, Point
        from shapely.ops import transform
        from pyproj import Transformer
    except Exception:
        return None, 0.0

    reachable = set(distances)
    segments = []
    to_m = Transformer.from_crs(WGS84, "EPSG:3857", always_xy=True).transform
    to_wgs = Transformer.from_crs("EPSG:3857", WGS84, always_xy=True).transform

    edge_grid = graph.get("edge_grid") or {}
    cx, cy = _cell(station_lon, station_lat)
    deg_budget = (BUDGET_M + ROAD_BUFFER_M * 4) / 111000.0 + GRID_DEG
    radius = max(1, int(deg_budget / GRID_DEG) + 1)
    local_edges = []
    if edge_grid:
        for dx in range(-radius, radius + 1):
            for dy in range(-radius, radius + 1):
                local_edges.extend(edge_grid.get((cx + dx, cy + dy), ()))
    else:
        local_edges = graph.get("edges", [])

    for a, b, _ in local_edges:
        if a in reachable and b in reachable:
            mx = (a[0] + b[0]) / 2
            my = (a[1] + b[1]) / 2
            euclidean_m = _haversine_m(station_lon, station_lat, mx, my)
            if euclidean_m <= BUDGET_M + ROAD_BUFFER_M * 3:
                segments.append((euclidean_m, [a, b]))

    if not segments:
        return None, 0.0
    segments.sort(key=lambda item: item[0])
    segment_coords = [coords for _, coords in segments[:MAX_SEGMENTS_PER_AREA]]

    station_geom = transform(to_m, Point(station_lon, station_lat)).buffer(ROAD_BUFFER_M)
    merged = transform(to_m, MultiLineString(segment_coords)).buffer(
        ROAD_BUFFER_M,
        cap_style=2,
        join_style=2,
    ).union(station_geom)
    if merged.is_empty:
        return None, 0.0

    merged = merged.buffer(0)
    if merged.geom_type == "MultiPolygon":
        merged = max(merged.geoms, key=lambda g: g.area)
    merged = merged.simplify(8.0, preserve_topology=True)
    area_m2 = float(merged.area)
    return transform(to_wgs, merged), area_m2


def _local_road_corridor_polygon(
    graph: Dict[str, Any],
    station_lon: float,
    station_lat: float,
    budget_m: float = BUDGET_M,
):
    """Irregular fallback from nearby road geometry when topology is broken.

    Some compressed road basemap segments are spatially near a station but not
    topologically connected, which makes network Dijkstra degenerate to one
    short dead-end. This fallback still follows the station-area definition's
    road service-zone intent by buffering only nearby road centerlines instead
    of falling back to a featureless circle.
    """
    try:
        from shapely.geometry import MultiLineString, Point
        from shapely.ops import transform
        from pyproj import Transformer
    except Exception:
        return None, 0.0

    edge_grid = graph.get("edge_grid") or {}
    cx, cy = _cell(station_lon, station_lat)
    deg_budget = (budget_m + ROAD_BUFFER_M * 2) / 111000.0 + GRID_DEG
    radius = max(1, int(deg_budget / GRID_DEG) + 1)
    local_edges = []
    for dx in range(-radius, radius + 1):
        for dy in range(-radius, radius + 1):
            local_edges.extend(edge_grid.get((cx + dx, cy + dy), ()))

    segments = []
    for a, b, _ in local_edges:
        mx = (a[0] + b[0]) / 2
        my = (a[1] + b[1]) / 2
        euclidean_m = _haversine_m(station_lon, station_lat, mx, my)
        if euclidean_m <= budget_m:
            segments.append((euclidean_m, [a, b]))

    if not segments:
        return None, 0.0
    segments.sort(key=lambda item: item[0])
    segment_coords = [coords for _, coords in segments[:MAX_SEGMENTS_PER_AREA]]

    to_m = Transformer.from_crs(WGS84, "EPSG:3857", always_xy=True).transform
    to_wgs = Transformer.from_crs("EPSG:3857", WGS84, always_xy=True).transform
    station_geom = transform(to_m, Point(station_lon, station_lat)).buffer(ROAD_BUFFER_M)
    merged = transform(to_m, MultiLineString(segment_coords)).buffer(
        ROAD_BUFFER_M,
        cap_style=2,
        join_style=2,
    ).union(station_geom)
    if merged.is_empty:
        return None, 0.0
    merged = merged.buffer(0)
    if merged.geom_type == "MultiPolygon":
        road_polys = [g for g in merged.geoms if g.area > station_geom.area * 1.5]
        merged = max(road_polys or merged.geoms, key=lambda g: g.area)
    merged = merged.simplify(8.0, preserve_topology=True)
    return transform(to_wgs, merged), float(merged.area)


def build_isochrone_areas(city_code: str, year: int, budget_m: float = BUDGET_M) -> Dict[str, Any]:
    stations = dl.load_stations(city_code)
    if not stations:
        return {"type": "FeatureCollection", "features": []}
    stations = [s for s in stations if s.get("open_year") and s["open_year"] <= year]

    graph = build_graph(city_code)
    if not graph:
        logger.warning("No road graph for %s — falling back to buffer", city_code)
        from .station_area import build_station_areas
        fc = build_station_areas(city_code, year)
        fc["method"] = "buffer_1260m_fallback"
        return fc

    circle_area = math.pi * budget_m * budget_m
    features: List[Dict[str, Any]] = []
    fallbacks = 0
    for s in stations:
        lon, lat = s["lon"], s["lat"]
        start = nearest_node(graph, lon, lat, max_search_m=1500)
        if start is None:
            ring = _fallback_circle(lon, lat, budget_m)
            area_m2 = circle_area
            walk_acc = 1.0
            method = "buffer_fallback"
            fallbacks += 1
        else:
            distances = dijkstra_distances(graph, start, budget_m)
            nodes = list(distances.keys())
            if len(nodes) < 3:
                ring = _fallback_circle(lon, lat, budget_m)
                area_m2 = circle_area
                walk_acc = 1.0
                method = "buffer_fallback"
                fallbacks += 1
            else:
                corridor, area_m2 = _network_corridor_polygon(graph, distances, lon, lat)
                if corridor is not None and area_m2 > 0:
                    geom = json.loads(json.dumps(corridor.__geo_interface__))
                    ring = geom.get("coordinates", [[]])[0] if geom.get("type") == "Polygon" else []
                    walk_acc = min(1.0, area_m2 / circle_area) if circle_area > 0 else 0.0
                    method = "network_corridor_1260m"
                else:
                    hull = _convex_hull(nodes)
                    # close ring
                    if hull[0] != hull[-1]:
                        hull.append(hull[0])
                    ring = [list(p) for p in hull]
                    area_m2 = _polygon_area_m2(hull)
                    walk_acc = min(1.0, area_m2 / circle_area) if circle_area > 0 else 0.0
                    method = "network_isochrone_1260m"

        features.append({
            "type": "Feature",
            "geometry": {"type": "Polygon", "coordinates": [ring]},
            "properties": {
                "city": city_code,
                "year": year,
                "station_id": s["station_id"],
                "station_name": s["station_name"],
                "line_name": s.get("line_name"),
                "method": method,
                "radius_m": budget_m,
                "area_m2": area_m2,
                "walk_accessibility": walk_acc,
            },
        })

    logger.info("isochrone %s/%s: %d stations, %d fallbacks", city_code, year, len(features), fallbacks)
    return {
        "type": "FeatureCollection",
        "cityCode": city_code,
        "year": year,
        "walkRadiusMeters": budget_m,
        "method": "network_isochrone_1260m",
        "features": features,
    }


def save_isochrone_areas(city_code: str, year: int, fc: Dict[str, Any]) -> Path:
    out = PROCESSED_DIR / f"station_area_iso_{city_code}_{year}.geojson"
    out.write_text(json.dumps(fc, ensure_ascii=False), encoding="utf-8")
    return out
