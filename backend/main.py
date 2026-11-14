"""Field Shift API. Reads only local, precomputed files in data/processed.

    uvicorn backend.main:app --port 8360
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import geopandas as gpd
import pandas as pd
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from engine.climate import Scenario
from engine.knowledge import load_kb
from engine.scoring import DEFAULT_CONSTRAINTS, climate_for, score_field

from .custom import CustomFieldError, build_custom

ROOT = Path(__file__).resolve().parents[1]
PROCESSED = ROOT / "data" / "processed"
DIST = ROOT / "frontend" / "dist"

app = FastAPI(title="Field Shift: Rotation Scenario Explorer", version="1.0")
app.add_middleware(CORSMiddleware, allow_origins=["http://localhost:5180", "http://127.0.0.1:5180"],
                   allow_methods=["*"], allow_headers=["*"])

STORE: dict[str, Any] = {}


def _json(name: str, default=None):
    p = PROCESSED / name
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else default


def _parquet(name: str):
    p = PROCESSED / name
    return pd.read_parquet(p) if p.exists() else None


def store() -> dict[str, Any]:
    """Load everything once. Raises a clear error if the pipeline has not been run."""
    if STORE:
        return STORE
    if not (PROCESSED / "fields.geojson").exists() or not (PROCESSED / "fields_summary.json").exists():
        raise HTTPException(503, "No processed data found. Run `python tasks.py data` first.")
    STORE.update(
        kb=load_kb(), glossary=json.loads((ROOT / "knowledge" / "glossary.json").read_text(encoding="utf-8")),
        fields=json.loads((PROCESSED / "fields.geojson").read_text(encoding="utf-8")),
        context_fields=_json("fields_context.geojson", {"type": "FeatureCollection", "features": []}),
        summary=_json("fields_summary.json", []), valley=_json("valley.json", {}),
        power=_parquet("power_daily.parquet"), cells=_json("power_cells.json"),
        bias=_json("power_bias.json", {}), smap=_parquet("smap_cell_monthly.parquet"),
        openet_valley=_parquet("openet_valley_monthly.parquet"), levels=_parquet("groundwater_levels.parquet"),
        overlays=_json("overlays/manifest.json", {"layers": [], "legends": {}, "corners": []}),
        contexts={}, evidence={}, clim_base={}, custom_features={},
    )
    wells_path = PROCESSED / "groundwater_wells.geojson"
    if wells_path.exists():
        w = gpd.read_file(wells_path)
        w["lon"], w["lat"] = w.geometry.x, w.geometry.y
        STORE["wells"] = pd.DataFrame(w.drop(columns="geometry"))
        STORE["wells_geojson"] = json.loads(wells_path.read_text(encoding="utf-8"))
    else:
        STORE["wells"], STORE["wells_geojson"] = None, {"type": "FeatureCollection", "features": []}
    by_id = {s["field_id"]: s for s in STORE["summary"]}
    for f in STORE["fields"]["features"]:
        f["properties"].update(by_id.get(f["properties"]["field_id"], {}))
    return STORE


def get_context(field_id: str) -> dict:
    s = store()
    if field_id not in s["contexts"]:
        p = PROCESSED / "field_context" / f"{field_id}.json"
        if not p.exists():
            raise HTTPException(404, f"Unknown field '{field_id}'.")
        ctx = json.loads(p.read_text(encoding="utf-8"))
        cell = s["cells"]["field_to_cell"][field_id]
        ctx["power"] = {"daily": s["power"][s["power"]["cell_id"] == cell],
                        "grid_elevation_m": ctx["grid_elevation_m"], "bias": s["bias"].get(field_id)}
        s["contexts"][field_id] = ctx
    return s["contexts"][field_id]


# ---------------------------------------------------------------------------
# Models
# ---------------------------------------------------------------------------
class ScenarioIn(BaseModel):
    rain_pct: float = Field(0, ge=-50, le=50)
    temp_c: float = Field(0, ge=-2, le=5)


class ConstraintsIn(BaseModel):
    water_supply_pct: float = Field(100, ge=20, le=150)
    equipment: list[str] = Field(default_factory=lambda: list(DEFAULT_CONSTRAINTS["equipment"]))
    market: str = Field("some", pattern="^(established_only|some|open)$")


class ScoreIn(BaseModel):
    field_id: str
    weights: dict[str, float] = Field(default_factory=dict)
    constraints: ConstraintsIn = Field(default_factory=ConstraintsIn)
    scenario: ScenarioIn = Field(default_factory=ScenarioIn)


class CustomIn(BaseModel):
    geometry: dict
    name: str = Field("My drawn field", max_length=60)


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------
@app.get("/api/health")
def health():
    s = store()
    return {"status": "ok", "fields": len(s["summary"]), "any_demo_data": bool(s["valley"].get("any_demo_data"))}


@app.get("/api/meta")
def meta():
    s = store()
    kb = s["kb"]
    return {
        "pilot": s["valley"].get("pilot"),
        "criteria": [{"id": cid, **{k: c[k] for k in ("label", "plain", "default_weight", "basis")}}
                     for cid, c in kb["criteria"].items()],
        "constraints": {
            "defaults": DEFAULT_CONSTRAINTS,
            "equipment": [{"id": "hay", "label": "Hay equipment (swather, baler)"},
                          {"id": "drill", "label": "Grain drill or seeder"},
                          {"id": "combine", "label": "Combine (or custom harvester)"}],
            "market": [{"id": "established_only", "label": "Only crops with buyers I already have"},
                       {"id": "some", "label": "Open to some new buyers"},
                       {"id": "open", "label": "Willing to develop new markets"}],
        },
        "scenario": {"rain_pct": {"min": -40, "max": 40, "step": 5}, "temp_c": {"min": 0, "max": 4, "step": 0.5}},
        "glossary": s["glossary"], "sources": s["valley"].get("sources", []),
        "any_demo_data": bool(s["valley"].get("any_demo_data")),
        "groundwater": s["valley"].get("groundwater"),
        "overlays": s["overlays"],
        "crops": [{"id": cid, "label": c["label"], "short": c["short"], "group": c["group"]}
                  for cid, c in kb["crops"].items()],
    }


@app.get("/api/fields")
def fields():
    s = store()
    return {"pilot": s["fields"], "context": s["context_fields"], "wells": s["wells_geojson"],
            "smap_cells": _json("smap_cells.geojson", {"type": "FeatureCollection", "features": []})}


@app.get("/api/soil-mapunits")
def soil_mapunits():
    p = PROCESSED / "soil_mapunits.geojson"
    if not p.exists():
        raise HTTPException(404, "Soil map units have not been processed.")
    return FileResponse(p, media_type="application/geo+json")


@app.get("/api/fields/{field_id}/evidence")
def evidence(field_id: str):
    s = store()
    if field_id in s["evidence"]:
        return s["evidence"][field_id]
    p = PROCESSED / "field_evidence" / f"{field_id}.json"
    if not p.exists():
        raise HTTPException(404, f"Unknown field '{field_id}'.")
    return json.loads(p.read_text(encoding="utf-8"))


@app.post("/api/score")
def score(body: ScoreIn):
    s = store()
    ctx = get_context(body.field_id)
    if body.field_id not in s["clim_base"]:
        s["clim_base"][body.field_id] = climate_for(ctx, Scenario())
    known = set(s["kb"]["criteria"])
    weights = {k: v for k, v in body.weights.items() if k in known}
    return score_field(ctx, s["kb"], weights, body.constraints.model_dump(),
                       Scenario(rain_pct=body.scenario.rain_pct, temp_c=body.scenario.temp_c),
                       clim_base=s["clim_base"][body.field_id])


@app.post("/api/custom-field")
def custom_field(body: CustomIn):
    s = store()
    try:
        feature, ctx, ev = build_custom(body.geometry, body.name.strip(), s)
    except CustomFieldError as exc:
        raise HTTPException(422, str(exc)) from exc
    fid = feature["properties"]["field_id"]
    cell = s["cells"]["field_to_cell"][ctx["nearest_pilot_field"]]
    ctx["power"] = {"daily": s["power"][s["power"]["cell_id"] == cell],
                    "grid_elevation_m": ctx["grid_elevation_m"],
                    "bias": s["bias"].get(ctx["nearest_pilot_field"])}
    s["contexts"][fid], s["evidence"][fid], s["custom_features"][fid] = ctx, ev, feature
    return {"feature": feature, "evidence": ev}


@app.get("/api/knowledge")
def knowledge():
    kb = store()["kb"]
    return {"references": kb["references"], "region_note": kb["region_note"],
            "crops": {cid: {k: c[k] for k in ("label", "short", "family", "group", "months", "kc", "cover",
                                              "traits", "why")} for cid, c in kb["crops"].items()},
            "strategies": {sid: {k: v for k, v in st.items()} for sid, st in kb["strategies"].items()}}


@app.exception_handler(HTTPException)
async def http_error(_, exc: HTTPException):
    return JSONResponse(status_code=exc.status_code, content={"detail": exc.detail})


if (PROCESSED / "overlays").exists():
    app.mount("/overlays", StaticFiles(directory=PROCESSED / "overlays"), name="overlays")
if DIST.exists():            # production: the API also serves the built frontend
    app.mount("/", StaticFiles(directory=DIST, html=True), name="site")
