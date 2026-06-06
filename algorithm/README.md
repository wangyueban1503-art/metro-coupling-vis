# Algorithm Pipeline

This folder contains the processing pipeline for the metro and urban coupling
visualization system.

## Main Entry Points

```bash
# Full network station-area and coupling pipeline
python -m algorithm.batch_isochrone --force

# One city and selected years
python -m algorithm.batch_isochrone --cities 440300 --years 2023 --force

# Legacy single city/year runner
python -m algorithm.run_all --city 440300 --year 2023 --method isochrone
```

For the current frontend, prefer `batch_isochrone.py`. It builds each city's
road graph once, computes station catchments once, then exports all requested
years.

## Data Inputs

The algorithms read normalized files from `algorithm/data/`.

Required:

- `city_metadata.json`
- `metro_network.json`
- `road_network_{cityCode}.json`
- `population_{cityName}_{year}.geojson`

Optional but supported:

- `gdp_{cityName}_{year}.geojson`
- POI GeoJSON files, if available

Raw source files live outside this folder in `raw/`.

## Processing Steps

1. Load metro stations and lines from `metro_network.json`.
2. Load the complete city road network from `road_network_{cityCode}.json`.
3. Build a road graph and compute 15-minute walking network station areas.
4. Calculate spatial indicators for every station area.
5. Normalize indicators and compute entropy weights.
6. Calculate U1, U2, coupling degree C, development index T, and coordination D.
7. Export frontend-ready JSON files.

## Station-Area Definition

The current station area is not a circular buffer. It is an irregular network
service area:

- start from the metro station,
- connect to nearby road-network nodes,
- run Dijkstra search within the 1260m walking budget,
- buffer reachable road centerlines,
- merge the reachable corridor into one station-area polygon.

`walk_accessibility` is calculated as:

```text
station area polygon area / theoretical 1260m walking circle area
```

## Important Modules

- `data_loader.py`: loads normalized metro, road, population, GDP and POI data.
- `station_area_network.py`: current network station-area algorithm.
- `spatial_indicators.py`: calculates road, metro, population, GDP and POI indicators.
- `entropy_weight.py`: entropy weighting and U1/U2 scoring.
- `coupling_model.py`: C/T/D coupling coordination model.
- `export_result.py`: writes frontend JSON outputs.
- `batch_isochrone.py`: recommended batch runner.
- `preprocess_raw.py`: raw-data preprocessing helper.

## Outputs

Intermediate outputs:

```text
algorithm/output/processed/
```

Frontend outputs:

```text
algorithm/output/frontend_data/
```

The batch runner syncs these frontend outputs into `frontend/`:

- `station_areas_{city}_{year}.json`
- `station_coupling_{city}_{year}.json`
- `summary_{city}_{year}.json`
- `entropy_weights_{city}_{year}.json`
- `city_year_index.json`
- `city_timeline.json`

## Coupling Model

U1 fields:

- `road_density`
- `walk_accessibility`
- `metro_line_density`
- `station_count`
- `line_count`

U2 fields:

- `population_density`
- `poi_density`
- `poi_diversity`
- `gdp_density`

Coordination:

```text
C = 2 * sqrt(U1 * U2) / (U1 + U2)
T = 0.5 * U1 + 0.5 * U2
D = sqrt(C * T)
```

