# Metro Coupling Project Structure

This project has two stable parts:

- `algorithm/`: data processing and coupling calculation pipeline.
- `frontend/`: static visual analytics system opened through a local web server.

The current visual result depends on the files listed as "keep" below. Do not
delete or rename them unless the pipeline is updated at the same time.

## Directory Map

```text
data/
  raw/                         Original source data. Keep.
    transport/                 OSM PBF and metro station/line CSV files.
    urban/                     Population rasters and other urban rasters.

  processed/                   Legacy/intermediate workspace. Keep unless audited.

  algorithm/
    data/                      Normalized source data used by algorithms. Keep.
      metro_network.json
      city_metadata.json
      road_network_{city}.json
      population_{city}_{year}.geojson
      gdp_{city}_{year}.geojson
      poi_*.geojson, if available

    output/
      processed/               Intermediate CSV/GeoJSON outputs.
      frontend_data/           Generated frontend JSON outputs.

    *.py                       Pipeline modules.
    requirements.txt

  frontend/
    index.html                 Main visual system.
    vendor/                    Local frontend dependencies.
    road_levels/{city}/        Current road display layers. Keep.
    station_areas_*.json       Generated station-area polygons. Keep.
    station_coupling_*.json    Generated station-level U1/U2/D data. Keep.
    summary_*.json             Generated city/year summaries. Keep.
    entropy_weights_*.json     Generated entropy weights. Keep.
    population_*.geojson       Population heatmap layer data. Keep.
    metro_network.json         Frontend copy of metro network. Keep.

  build_road_levels.py         Current road display-layer builder.
  extract_roads.py             Road extraction helper.
  gen_timeline.py              Timeline helper.
```

## Removed Legacy Files

The following old display-only road files were removed because the current
frontend no longer references them and they caused confusion while debugging
missing roads:

- `frontend/road_tiles/`
- `frontend/basemap_roads_*.json`
- `build_road_tiles.py`
- `build_frontend_roads.py`

The current road layer is `frontend/road_levels/{city}/roads_high.json`, which
is generated from the complete `algorithm/data/road_network_{city}.json`.

## Current Pipeline

Install dependencies:

```bash
pip install -r algorithm/requirements.txt
```

Run the full station-area and coupling pipeline:

```bash
python -m algorithm.batch_isochrone --force
```

Run a subset:

```bash
python -m algorithm.batch_isochrone --cities 440300 --years 2023 --force
```

Rebuild road display layers after adding or replacing road networks:

```bash
python build_road_levels.py
```

Start the frontend:

```bash
cd frontend
python -m http.server 8080
```

Open:

```text
http://localhost:8080/index.html
```

## Adding A New City

Use this checklist when adding another city.

1. Add raw source files under `raw/`.
   - Population raster: `raw/urban/population/{cityName}/{cityName}_{year}.tif`
   - Metro station/line CSV: `raw/transport/Metro station&line/{cityName}/...`
   - Road source should cover the city, usually from `raw/transport/china-latest.osm.pbf`.

2. Update city metadata and code mappings.
   - `algorithm/data/city_metadata.json`
   - `algorithm/data_loader.py` city name/code mappings if needed.
   - `frontend/index.html` city button list, `cityCoords`, `cityYears`, and optional timeline events.

3. Generate normalized algorithm data.
   - Use or extend `algorithm/preprocess_raw.py`.
   - Confirm these files exist:
     - `algorithm/data/road_network_{cityCode}.json`
     - `algorithm/data/metro_network.json`
     - `algorithm/data/population_{cityName}_{year}.geojson`

4. Run calculations.
   - `python -m algorithm.batch_isochrone --cities {cityCode} --force`

5. Rebuild frontend road levels.
   - `python build_road_levels.py`

6. Verify frontend.
   - Start the local server from `frontend/`.
   - Check station areas, road layer, metro lines, station clicks, dashboard, and timeline.

## Safety Notes

- Do not calculate station areas from frontend road files. Algorithms must use
  `algorithm/data/road_network_{city}.json`.
- Do not delete `frontend/road_levels`; it is the current complete road display
  format.
- Do not delete generated `station_areas_*`, `station_coupling_*`, `summary_*`,
  or `population_*` files unless you are about to regenerate them.
- The station-area definition currently used is a 15-minute walking network
  service area based on complete road networks. Its `walk_accessibility` is:

```text
actual network station-area polygon area / theoretical 1260m walking circle area
```

