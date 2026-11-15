"""Harmonise every source to field x month and build the per-field files for one region.

Outputs (all in data/processed/<region>/)
  field_context/<id>.json    what the scoring engine needs for a field
  field_evidence/<id>.json   chart data for the evidence panels
  fields_summary.json        one line of headline indicators per field (map colouring)
  valley.json                region-wide context (grid cells, long-term water, source status)
  rasters/cdl_<year>.tif     crop-map clips next to the other rasters (regions that have one)
"""
from __future__ import annotations

import json
import shutil

import geopandas as gpd
import numpy as np
import pandas as pd

from engine import context as ctxmod
from engine.climate import Scenario, field_precip
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
         "modis": _read("modis_field_ndvi.parquet"),
         "et": _read("openet_field_monthly.parquet") if (PROCESSED / "openet_field_monthly.parquet").exists()
         else _read("et_field_monthly.parquet"),
         "et_valley": _read("openet_valley_monthly.parquet"), "smap": _read("smap_cell_monthly.parquet"),
         "smap_map": _read("field_smap_cell.json"), "imerg": _read("imerg_cell_daily.parquet"),
         "imerg_map": _read("field_imerg_cell.json"), "levels": _read("groundwater_levels.parquet"),
         "grace": _read("grace_monthly.parquet"), "bias": _read("power_bias.json") or {},
         "ground": _read("ground_daily.parquet") if (PROCESSED / "ground_daily.parquet").exists()
         else _read("gridmet_daily.parquet")}
    wells_path = PROCESSED / "groundwater_wells.geojson"
    if wells_path.exists():
        w = gpd.read_file(wells_path)
        w["lon"], w["lat"] = w.geometry.x, w.geometry.y
        d["wells"] = pd.DataFrame(w.drop(columns="geometry"))
    else:
        d["wells"] = None
    return d


def imerg_correction(d: dict) -> None:
    """Monthly ratio that scales IMERG to the ground-informed rainfall normals, per field.

    Same delta method as for NASA POWER: ratio = ground monthly normal / IMERG monthly normal
    over the days both cover. IMERG keeps its own day-to-day and year-to-year pattern.
    """
    grid = d["ground"]
    if d["imerg"] is None or grid is None or not d["imerg_map"] or not d["bias"]:
        return
    changed = False
    for fid, rec in d["bias"].items():
        im = d["imerg"][d["imerg"]["cell_id"] == d["imerg_map"].get(fid)]
        g = grid[grid["cell_id"] == (rec.get("ground_cell") or rec.get("gridmet_cell"))]
        if im.empty or g.empty:
            continue
        j = pd.merge(im[["date", "precip_mm"]], g[["date", "precip_mm"]], on="date", suffixes=("_imerg", "_grid")).dropna()
        m = j.groupby(j["date"].dt.month)[["precip_mm_imerg", "precip_mm_grid"]].mean()
        # months with almost no rain give meaningless ratios: leave them at 1
        rec["imerg_precip_ratio"] = {
            int(k): (round(float(np.clip(r["precip_mm_grid"] / r["precip_mm_imerg"], 0.3, 3.0)), 3)
                     if (r["precip_mm_imerg"] > 0.2 and r["precip_mm_grid"] > 0.2) else 1.0) for k, r in m.iterrows()}
        years = j["date"].dt.year.nunique()
        rec.setdefault("check", {}).update(
            annual_precip_imerg_raw_mm=round(float(j["precip_mm_imerg"].sum() / years)),
            annual_precip_ground_same_days_mm=round(float(j["precip_mm_grid"].sum() / years)),
            imerg_days=int(len(j)))
        changed = True
    if changed:
        (PROCESSED / "power_bias.json").write_text(json.dumps(d["bias"], indent=1), encoding="utf-8")


def field_inputs(f, d: dict) -> dict:
    """Slice every table down to one field (or its grid cell)."""
    fid = f["field_id"]
    sub = lambda df: None if df is None else df[df["field_id"] == fid]   # noqa: E731
    cell = d["cells"]["field_to_cell"][fid]
    soil, terr, cdl = sub(d["soil"]), sub(d["terrain"]), sub(d["cdl"])
    smap = imerg = ground = None
    if d["smap"] is not None and d["smap_map"] and d["smap_map"].get(fid):
        smap = d["smap"][d["smap"]["cell_id"] == d["smap_map"][fid]]
    if d["imerg"] is not None and d["imerg_map"] and d["imerg_map"].get(fid):
        imerg = d["imerg"][d["imerg"]["cell_id"] == d["imerg_map"][fid]]
    bias = d["bias"].get(fid)
    if d["ground"] is not None and bias:
        ground = d["ground"][d["ground"]["cell_id"] == (bias.get("ground_cell") or bias.get("gridmet_cell"))]
    return dict(
        power_daily=d["power"][d["power"]["cell_id"] == cell],
        grid_elevation_m=d["cells"]["cells"][cell]["grid_elevation_m"],
        soil=None if soil is None or soil.empty else soil.iloc[0].to_dict(),
        terrain=None if terr is None or terr.empty else terr.iloc[0].drop("field_id").to_dict(),
        cdl_rows=[] if cdl is None else cdl[["year", "cdl_code", "cdl_name", "share"]].to_dict("records"),
        landsat_obs=sub(d["landsat"]), modis=sub(d["modis"]), et=sub(d["et"]), et_valley=d["et_valley"],
        smap=smap, imerg=imerg, wells=d["wells"], levels=d["levels"], grace=d["grace"],
        ground_daily=ground, bias=bias, growing_months=PILOT["growing_months"])


def main() -> None:
    kb = load_kb(PILOT["kb"])
    d = load_all()
    imerg_correction(d)
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
                                    "bias": inp["bias"],
                                    "precip_override": field_precip(inp["power_daily"], inp["imerg"], inp["bias"])}}
        res = score_field(run_ctx, kb, None, None, Scenario())
        existing = next(s for s in res["strategies"] if s["is_existing"])
        oa = [r for r in (ev["water"].get("et_annual") or []) if r["months"] == 12 and r["year"] >= 2021]
        hist = ctx["history"][-8:]
        summary.append({
            "field_id": f["field_id"], "name": f["name"], "area_ha": float(f["area_ha"]),
            "lon": float(f["lon"]), "lat": float(f["lat"]),
            "crop_latest": hist[-1]["label"] if hist else None,
            "crop_latest_year": hist[-1]["year"] if hist else None,
            "doubtful_years": ctx["n_doubtful_years"],
            "seasons_per_year": (ctx.get("phenology") or {}).get("median_seasons"),
            "et_annual_mm": round(float(np.mean([r["et_mm"] for r in oa]))) if oa else None,
            "irrigation_need_mm": existing["water"]["irrigation_mm"],
            "peak_ndvi_latest": (list(ev["greenness"]["peak_by_year"].values()) or [None])[-1],
            "low_cover_months": len(ev["bare"]["months_usually_low_cover"]),
            "om_pct": ctx["soil"].get("om_pct_0_30"), "ec_dsm": ctx["soil"].get("ec_dsm_0_30"),
            "ph": ctx["soil"].get("ph_0_30"), "clay_pct": ctx["soil"].get("clay_pct_0_30"),
            "texture": ctx["soil"].get("surface_texture"),
            "wind_erodibility_index": ctx["soil"].get("wind_erodibility_index"),
            "water_factor": ctx["water_factor"], "elevation_m": ctx["elevation_m"],
            "most_vulnerable_months": ev["vulnerability"]["most_vulnerable"],
            "top_strategy_default": res["ranking"][0], "sources": ctx["sources"],
        })
        checks.append(all(0.0 <= s["total"] <= 1.0 for s in res["strategies"]))
    (PROCESSED / "fields_summary.json").write_text(json.dumps(ctxmod.clean(summary), indent=1), encoding="utf-8")

    statuses = [json.loads(p.read_text(encoding="utf-8")) for p in sorted(STATUS_DIR.glob("*.json"))]
    wells = d["wells"]
    long_rec = None if wells is None else wells[wells["trend_m_per_decade_since_1990"].notna()]
    valley = {
        "pilot": {k: v for k, v in PILOT.items() if k != "steps"},
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

    rdir = PROCESSED / "rasters"
    rdir.mkdir(exist_ok=True)
    for p in sorted((RAW / "cdl").glob("CDL_*_cros.tif")) + sorted((RAW / "cdl").glob("CDL_*_cropscape.tif")):
        shutil.copyfile(p, rdir / f"cdl_{p.name.split('_')[1]}.tif")

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
