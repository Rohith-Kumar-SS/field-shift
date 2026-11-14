"""Harmonise every source to field x month and build the files the app reads.

Outputs (all in data/processed/)
  field_context/<id>.json    what the scoring engine needs for a field
  field_evidence/<id>.json   chart data for the evidence panels
  fields_summary.json        one line of headline indicators per field (map colouring)
  valley.json                valley-wide context (groundwater, grid cells, source status)
  rasters/cdl_<year>.tif     crop-map clips copied next to the other rasters (drawn fields)
"""
from __future__ import annotations

import json
import shutil

import geopandas as gpd
import numpy as np
import pandas as pd

from engine import context as ctxmod
from engine.climate import Scenario
from engine.knowledge import load_kb
from engine.scoring import score_field

from .common import PILOT, PROCESSED, RAW, STATUS_DIR, load_fields, run_source, write_status

SOURCE, TITLE, TIER = "indicators", "Field x month harmonisation and indicators", "MUST"


def _read(name: str):
    p = PROCESSED / name
    if not p.exists():
        return None
    return pd.read_parquet(p) if name.endswith(".parquet") else json.loads(p.read_text(encoding="utf-8"))


def load_all() -> dict:
    d = {"fields": load_fields(), "power": _read("power_daily.parquet"), "cells": _read("power_cells.json"),
         "soil": _read("field_soil.parquet"), "terrain": _read("field_terrain.parquet"),
         "cdl": _read("field_cdl.parquet"), "landsat": _read("landsat_field_obs.parquet"),
         "modis": _read("modis_field_ndvi.parquet"), "openet": _read("openet_field_monthly.parquet"),
         "openet_valley": _read("openet_valley_monthly.parquet"), "smap": _read("smap_cell_monthly.parquet"),
         "smap_map": _read("field_smap_cell.json"), "imerg": _read("imerg_cell_daily.parquet"),
         "imerg_map": _read("field_imerg_cell.json"), "levels": _read("groundwater_levels.parquet"),
         "bias": _read("power_bias.json") or {}}
    wells_path = PROCESSED / "groundwater_wells.geojson"
    if wells_path.exists():
        w = gpd.read_file(wells_path)
        w["lon"], w["lat"] = w.geometry.x, w.geometry.y
        d["wells"] = pd.DataFrame(w.drop(columns="geometry"))
    else:
        d["wells"] = None
    return d


def field_inputs(f, d: dict) -> dict:
    """Slice every table down to one field (or its grid cell)."""
    fid = f["field_id"]
    sub = lambda df: None if df is None else df[df["field_id"] == fid]   # noqa: E731
    cell = d["cells"]["field_to_cell"][fid]
    power = d["power"][d["power"]["cell_id"] == cell]
    soil = sub(d["soil"])
    terr = sub(d["terrain"])
    cdl = sub(d["cdl"])
    smap = None
    if d["smap"] is not None and d["smap_map"] and d["smap_map"].get(fid):
        smap = d["smap"][d["smap"]["cell_id"] == d["smap_map"][fid]]
    imerg = None
    if d["imerg"] is not None and d["imerg_map"] and d["imerg_map"].get(fid):
        imerg = d["imerg"][d["imerg"]["cell_id"] == d["imerg_map"][fid]]
    return dict(
        power_daily=power, grid_elevation_m=d["cells"]["cells"][cell]["grid_elevation_m"],
        soil=None if soil is None or soil.empty else soil.iloc[0].to_dict(),
        terrain=None if terr is None or terr.empty else terr.iloc[0].drop("field_id").to_dict(),
        cdl_rows=[] if cdl is None else cdl[["year", "cdl_code", "cdl_name", "share"]].to_dict("records"),
        landsat_obs=sub(d["landsat"]), modis=sub(d["modis"]), openet=sub(d["openet"]),
        openet_valley=d["openet_valley"], smap=smap, imerg=imerg, wells=d["wells"], levels=d["levels"],
        bias=d["bias"].get(fid))


def main() -> None:
    kb = load_kb()
    d = load_all()
    (PROCESSED / "field_context").mkdir(exist_ok=True)
    (PROCESSED / "field_evidence").mkdir(exist_ok=True)
    summary, checks = [], []
    for _, f in d["fields"].iterrows():
        meta = {"field_id": f["field_id"], "name": f["name"], "lat": float(f["lat"]), "lon": float(f["lon"]),
                "area_ha": float(f["area_ha"])}
        inp = field_inputs(f, d)
        ctx, ev = ctxmod.build(meta, kb, **inp)
        (PROCESSED / "field_context" / f"{f['field_id']}.json").write_text(json.dumps(ctx), encoding="utf-8")
        (PROCESSED / "field_evidence" / f"{f['field_id']}.json").write_text(json.dumps(ev), encoding="utf-8")

        # default-priority scoring: a smoke test of the whole chain and the map's headline numbers
        run_ctx = {**ctx, "power": {"daily": inp["power_daily"], "grid_elevation_m": inp["grid_elevation_m"],
                                    "bias": inp["bias"]}}
        res = score_field(run_ctx, kb, None, None, Scenario())
        existing = next(s for s in res["strategies"] if s["is_existing"])
        oa = ev["water"].get("openet_annual") or []
        recent_et = [r["growing_season_et_mm"] for r in oa if r["year"] >= 2021]
        hist = ctx["history"][-8:]
        summary.append({
            "field_id": f["field_id"], "name": f["name"], "area_ha": float(f["area_ha"]),
            "lon": float(f["lon"]), "lat": float(f["lat"]),
            "crop_latest": hist[-1]["label"], "crop_latest_year": hist[-1]["year"],
            "alfalfa_years_of_8": sum(r["crop"] in ("alfalfa", "alfalfa_est") for r in hist),
            "doubtful_years": ctx["n_doubtful_years"],
            "openet_gs_et_mm": round(float(np.mean(recent_et))) if recent_et else None,
            "irrigation_need_mm": existing["water"]["irrigation_mm"],
            "peak_ndvi_latest": (list(ev["greenness"]["peak_by_year"].values()) or [None])[-1],
            "low_cover_months": len(ev["bare"]["months_usually_low_cover"]),
            "om_pct": ctx["soil"].get("om_pct_0_30"), "ec_dsm": ctx["soil"].get("ec_dsm_0_30"),
            "ph": ctx["soil"].get("ph_0_30"), "texture": ctx["soil"].get("surface_texture"),
            "wind_erodibility_index": ctx["soil"].get("wind_erodibility_index"),
            "wind_erodibility_group": ctx["soil"].get("wind_erodibility_group"),
            "water_factor": ctx["water_factor"], "elevation_m": ctx["elevation_m"],
            "most_vulnerable_months": ev["vulnerability"]["most_vulnerable"],
            "top_strategy_default": res["ranking"][0], "sources": ctx["sources"],
        })
        checks.append(all(0.0 <= s["total"] <= 1.0 for s in res["strategies"]))
    (PROCESSED / "fields_summary.json").write_text(json.dumps(ctxmod.clean(summary), indent=1), encoding="utf-8")

    # valley-level context
    statuses = [json.loads(p.read_text(encoding="utf-8")) for p in sorted(STATUS_DIR.glob("*.json"))]
    wells = d["wells"]
    long_rec = None if wells is None else wells[wells["trend_m_per_decade_since_1990"].notna()]
    valley = {
        "pilot": PILOT,
        "power_cells": d["cells"]["cells"],
        "groundwater": None if long_rec is None else {
            "n_wells": int(len(wells)), "n_wells_long_record": int(len(long_rec)),
            "n_deepening": int(((long_rec["trend_m_per_decade_since_1990"] > 0) & (long_rec["trend_p_value"] < 0.05)).sum()),
            "n_rising": int(((long_rec["trend_m_per_decade_since_1990"] < 0) & (long_rec["trend_p_value"] < 0.05)).sum()),
            "median_m_per_decade": round(float(long_rec["trend_m_per_decade_since_1990"].median()), 2)},
        "sources": [{k: s.get(k) for k in ("source", "title", "tier", "status", "resolution", "date_range",
                                           "credit", "message", "action_needed", "is_demo_data", "notes")}
                    for s in statuses if s["source"] != SOURCE],
        "any_demo_data": any(s.get("is_demo_data") for s in statuses),
    }
    (PROCESSED / "valley.json").write_text(json.dumps(ctxmod.clean(valley), indent=1), encoding="utf-8")

    # crop-map clips next to the other rasters, so a drawn field can read its own crop history
    rdir = PROCESSED / "rasters"
    rdir.mkdir(exist_ok=True)
    for p in sorted((RAW / "cdl").glob("CDL_*_cros.tif")) + sorted((RAW / "cdl").glob("CDL_*_cropscape.tif")):
        year = p.name.split("_")[1]
        shutil.copyfile(p, rdir / f"cdl_{year}.tif")

    ok = all(checks) and len(summary) == len(d["fields"])
    missing = sorted({k for s in summary for k, v in s["sources"].items() if not v})
    write_status(
        SOURCE, status="ok" if ok else "partial", title=TITLE, tier=TIER,
        fetched=f"{len(summary)} fields x every source -> context, evidence and summary JSON",
        resolution="field polygon x month (plus annual and growing-season summaries)",
        date_range="see individual sources",
        credit="Derived by this project.", access="pipeline/s20_indicators.py + engine/context.py",
        message=f"{len(summary)} fields harmonised; default-priority scoring ran for all; "
                f"sources not available: {', '.join(missing) or 'none'}",
        sanity={"all_scores_within_0_1": bool(all(checks)), "passed": bool(ok)},
        outputs=["field_context/*.json", "field_evidence/*.json", "fields_summary.json", "valley.json"],
    )


if __name__ == "__main__":
    run_source(SOURCE, TITLE, TIER, main)
