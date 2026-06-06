"""Lightweight FastAPI service exposing the algorithm outputs.

Run:
    uvicorn algorithm.mini_server:app --host 0.0.0.0 --port 8000 --reload
"""
from __future__ import annotations

import json
import logging
from pathlib import Path

from .config import FRONTEND_DIR

logger = logging.getLogger(__name__)

try:
    from fastapi import FastAPI, HTTPException, Query
    from fastapi.middleware.cors import CORSMiddleware
    from fastapi.responses import JSONResponse, FileResponse
except Exception as exc:
    raise SystemExit(
        "FastAPI not installed. Run: pip install fastapi uvicorn"
    ) from exc

app = FastAPI(title="Metro-TOD Coupling Mini API", version="0.3.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)


def _read_json(path: Path):
    if not path.exists():
        raise HTTPException(status_code=404, detail=f"File not found: {path.name}")
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


@app.get("/api/health")
def health():
    return {"status": "ok"}


@app.get("/api/coupling-result")
def coupling_result(city: str = Query(...), year: int = Query(...)):
    p = FRONTEND_DIR / f"station_coupling_{city}_{year}.json"
    return _read_json(p)


@app.get("/api/station-area")
def station_area(city: str = Query(...), year: int = Query(None)):
    if year is not None:
        p = FRONTEND_DIR / f"station_areas_{city}_{year}.json"
        if p.exists():
            return _read_json(p)
    p = FRONTEND_DIR / f"station_areas_{city}.json"
    return _read_json(p)


@app.get("/api/summary")
def summary(city: str = Query(...), year: int = Query(...)):
    return _read_json(FRONTEND_DIR / f"summary_{city}_{year}.json")


@app.get("/api/station-detail")
def station_detail(station_id: str = Query(...), city: str = Query(...), year: int = Query(...)):
    data = _read_json(FRONTEND_DIR / f"station_coupling_{city}_{year}.json")
    for s in data.get("stations", []):
        if str(s.get("station_id")) == str(station_id) or s.get("stationName") == station_id:
            return s
    raise HTTPException(status_code=404, detail=f"station {station_id} not found")


@app.get("/api/entropy-weights")
def entropy_weights(city: str = Query(...), year: int = Query(...)):
    return _read_json(FRONTEND_DIR / f"entropy_weights_{city}_{year}.json")


@app.get("/api/city-year-index")
def city_year_index():
    return _read_json(FRONTEND_DIR / "city_year_index.json")
