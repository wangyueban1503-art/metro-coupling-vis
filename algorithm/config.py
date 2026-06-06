"""Global configuration for the algorithm module."""
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parent.parent          # project root = data/
RAW_DIR = ROOT_DIR / "raw"                                 # data/raw/   (raw TIF, CSV, OSM PBF)
ALG_DIR  = ROOT_DIR / "algorithm"
# Generated intermediate JSON (metro_network, road_network, city_year_index)
GEN_DATA_DIR = ALG_DIR / "data"
# Processed outputs
OUTPUT_DIR = ALG_DIR / "output"
PROCESSED_DIR = OUTPUT_DIR / "processed"
FRONTEND_DIR   = OUTPUT_DIR / "frontend_data"

# For backward compat, DATA_DIR now points to GEN_DATA_DIR (where data_loader looks)
DATA_DIR = GEN_DATA_DIR

for d in (OUTPUT_DIR, PROCESSED_DIR, FRONTEND_DIR):
    d.mkdir(parents=True, exist_ok=True)

WGS84 = "EPSG:4326"
METRIC_CRS = "EPSG:3857"
STATION_RADIUS_M = 1260

ALPHA = 0.5
BETA = 0.5
EPS = 1e-12

U1_FIELDS = [
    "road_density",
    "walk_accessibility",
    "metro_line_density",
    "station_count",
    "line_count",
]
U2_FIELDS = [
    "population_density",
    "poi_density",
    "poi_diversity",
    "gdp_density",
]

LEVEL_BINS = [
    (0.0, 0.2, "极度失调"),
    (0.2, 0.4, "中度失调"),
    (0.4, 0.6, "勉强协调"),
    (0.6, 0.8, "良好协调"),
    (0.8, 1.0 + 1e-9, "优质协调"),
]


def classify_level(d: float) -> str:
    if d is None or d != d:  # NaN check
        return "未知"
    for lo, hi, name in LEVEL_BINS:
        if lo <= d < hi:
            return name
    return "优质协调" if d >= 1.0 else "未知"
