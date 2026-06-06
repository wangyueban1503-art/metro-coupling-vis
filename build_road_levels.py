"""Build zoom-level road layers for smooth Leaflet rendering.

Analytical station-area calculation uses the full road network directly. These
files are display-only:

- low: city-scale skeleton
- mid: denser city network
- high: complete road network, rounded and grouped for fewer Leaflet objects
"""
from __future__ import annotations

import json
import math
import shutil
from collections import defaultdict
from pathlib import Path


ROOT = Path(__file__).resolve().parent
SRC_DIR = ROOT / "algorithm" / "data"
OUT_ROOT = ROOT / "frontend" / "road_levels"

COORD_DECIMALS = 5
CHUNK_SIZE = 4000

LEVELS = {
    "low": {"target": 15000, "major": 4000, "grid_scale": 40, "max_per_grid": 18},
    "mid": {"target": 70000, "major": 15000, "grid_scale": 70, "max_per_grid": 55},
}


def rounded_coords(coords):
    result = []
    last = None
    for point in coords:
        rounded = [round(float(point[0]), COORD_DECIMALS), round(float(point[1]), COORD_DECIMALS)]
        if rounded != last:
            result.append(rounded)
            last = rounded
    return result if len(result) >= 2 else []


def road_length(coords):
    total = 0.0
    for i in range(1, len(coords)):
        lon1, lat1 = coords[i - 1]
        lon2, lat2 = coords[i]
        total += math.hypot(lon2 - lon1, lat2 - lat1)
    return total


def centroid(coords):
    return (
        sum(p[0] for p in coords) / len(coords),
        sum(p[1] for p in coords) / len(coords),
    )


def iter_lines(geometry):
    gtype = geometry.get("type")
    coords = geometry.get("coordinates") or []
    if gtype == "LineString":
        yield coords
    elif gtype == "MultiLineString":
        yield from coords


def collect_items(path: Path):
    data = json.loads(path.read_text(encoding="utf-8"))
    items = []
    for feature in data.get("features", []):
        for coords in iter_lines(feature.get("geometry") or {}):
            coords = rounded_coords(coords)
            if not coords:
                continue
            length = road_length(coords)
            cx, cy = centroid(coords)
            items.append({"length": length, "centroid": (cx, cy), "coords": coords})
    items.sort(key=lambda item: item["length"], reverse=True)
    return items


def make_balanced_level(items, spec):
    target = min(spec["target"], len(items))
    selected = items[: min(spec["major"], target)]
    selected_ids = {id(item) for item in selected}
    by_grid = defaultdict(list)
    for item in items[spec["major"]:]:
        cx, cy = item["centroid"]
        key = (int(cx * spec["grid_scale"]), int(cy * spec["grid_scale"]))
        by_grid[key].append(item)

    for grid_items in by_grid.values():
        grid_items.sort(key=lambda item: item["length"], reverse=True)
        for item in grid_items[: spec["max_per_grid"]]:
            if id(item) in selected_ids:
                continue
            selected.append(item)
            selected_ids.add(id(item))
            if len(selected) >= target:
                break
        if len(selected) >= target:
            break

    if len(selected) < target:
        for item in items:
            if id(item) in selected_ids:
                continue
            selected.append(item)
            selected_ids.add(id(item))
            if len(selected) >= target:
                break
    return selected


def to_feature_collection(lines):
    features = []
    for i in range(0, len(lines), CHUNK_SIZE):
        chunk = [item["coords"] for item in lines[i : i + CHUNK_SIZE]]
        features.append({
            "type": "Feature",
            "geometry": {"type": "MultiLineString", "coordinates": chunk},
            "properties": {},
        })
    return {"type": "FeatureCollection", "features": features}


def write_level(out_dir: Path, level: str, lines):
    payload = to_feature_collection(lines)
    out = out_dir / f"roads_{level}.json"
    out.write_text(json.dumps(payload, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    return out.stat().st_size


def export_city(path: Path):
    city = path.stem.replace("road_network_", "")
    out_dir = OUT_ROOT / city
    if out_dir.exists():
        shutil.rmtree(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    items = collect_items(path)
    stats = {}
    for level, spec in LEVELS.items():
        lines = make_balanced_level(items, spec)
        stats[level] = {"lines": len(lines), "bytes": write_level(out_dir, level, lines)}

    stats["high"] = {"lines": len(items), "bytes": write_level(out_dir, "high", items)}
    manifest = {
        "city": city,
        "coordDecimals": COORD_DECIMALS,
        "chunkSize": CHUNK_SIZE,
        "levels": stats,
    }
    (out_dir / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    return stats


def main():
    OUT_ROOT.mkdir(parents=True, exist_ok=True)
    for path in sorted(SRC_DIR.glob("road_network_*.json")):
        stats = export_city(path)
        summary = ", ".join(f"{k}:{v['lines']} lines/{v['bytes']/1024/1024:.1f}MB" for k, v in stats.items())
        print(f"{path.name} -> {summary}")


if __name__ == "__main__":
    main()
