"""NASA POWER daily agro-meteorology (MUST tier). No key needed.

Fetches one daily series per NASA POWER grid cell that contains a pilot field
(meteorology is on the MERRA-2 0.5 x 0.625 degree grid, so every field in a valley
normally shares a cell). Output: data/processed/power_daily.parquet
"""
from __future__ import annotations

import json

import numpy as np
import pandas as pd

from .common import (CLIMATE_END, CLIMATE_START, PROCESSED, SourceError, cached_get,
                     load_fields, run_source, sanity_range, write_status)

SOURCE, TITLE, TIER = "nasa_power", "NASA POWER daily agroclimatology", "MUST"
URL = "https://power.larc.nasa.gov/api/temporal/daily/point"
PARAMS = ["T2M", "T2M_MAX", "T2M_MIN", "T2MDEW", "RH2M", "WS2M", "ALLSKY_SFC_SW_DWN",
          "PRECTOTCORR", "GWETTOP", "GWETROOT", "PS"]


def power_cell(lon: float, lat: float) -> tuple[float, float]:
    """Centre of the MERRA-2 cell (0.625 deg lon x 0.5 deg lat) containing a point."""
    return round(round(lon / 0.625) * 0.625, 4), round(round(lat / 0.5) * 0.5, 4)


def fetch_cell(lon: float, lat: float) -> tuple[pd.DataFrame, dict]:
    path = cached_get(SOURCE, URL, {
        "parameters": ",".join(PARAMS), "community": "AG",
        "longitude": round(lon, 4), "latitude": round(lat, 4),
        "start": f"{CLIMATE_START}0101", "end": f"{CLIMATE_END}1231", "format": "JSON",
    }, timeout=300)
    js = json.loads(path.read_text(encoding="utf-8"))
    if "properties" not in js:
        raise SourceError(f"NASA POWER returned no data: {str(js)[:200]}")
    par = js["properties"]["parameter"]
    df = pd.DataFrame(par)
    df.index = pd.to_datetime(df.index, format="%Y%m%d")
    df = df.replace(-999.0, np.nan).sort_index()
    df.index.name = "date"
    meta = {"grid_elevation_m": float(js["geometry"]["coordinates"][2]),
            "units": {k: v.get("units") for k, v in js.get("parameters", {}).items()}}
    return df.reset_index(), meta


def main() -> None:
    fields = load_fields()
    cells: dict[str, dict] = {}
    frames = []
    mapping = {}
    for _, f in fields.iterrows():
        c = f.geometry.centroid
        clon, clat = power_cell(c.x, c.y)
        cid = f"P{clon:+.3f}_{clat:+.2f}"
        mapping[f["field_id"]] = cid
        if cid in cells:
            continue
        df, meta = fetch_cell(c.x, c.y)
        df.insert(0, "cell_id", cid)
        frames.append(df)
        cells[cid] = {"cell_lon": clon, "cell_lat": clat, "query_lon": round(c.x, 4),
                      "query_lat": round(c.y, 4), **meta}
    daily = pd.concat(frames, ignore_index=True)
    daily.to_parquet(PROCESSED / "power_daily.parquet", index=False)
    (PROCESSED / "power_cells.json").write_text(
        json.dumps({"cells": cells, "field_to_cell": mapping}, indent=2), encoding="utf-8")

    checks = [
        sanity_range(daily["T2M_MAX"], -35, 52, "T2M_MAX degC"),
        sanity_range(daily["T2M_MIN"], -45, 40, "T2M_MIN degC"),
        sanity_range(daily["PRECTOTCORR"], 0, 400, "PRECTOTCORR mm/day"),
        sanity_range(daily["ALLSKY_SFC_SW_DWN"], 0, 40, "ALLSKY_SFC_SW_DWN MJ/m2/day"),
        sanity_range(daily["WS2M"], 0, 25, "WS2M m/s"),
    ]
    missing = {p: round(float(daily[p].isna().mean()) * 100, 2) for p in PARAMS}
    ok = all(c["passed"] for c in checks)
    write_status(
        SOURCE, status="ok" if ok else "partial", title=TITLE, tier=TIER,
        fetched=f"{len(cells)} grid cell(s), {len(daily):,} daily rows, parameters: {', '.join(PARAMS)}",
        resolution="0.5 x 0.625 degree (MERRA-2 meteorology), 1 x 1 degree (CERES solar); daily",
        date_range=f"{daily['date'].min():%Y-%m-%d} to {daily['date'].max():%Y-%m-%d}",
        credit="NASA Langley Research Center (LaRC) POWER Project, funded through the NASA "
               "Earth Science/Applied Science Program. Public domain.",
        access="REST API https://power.larc.nasa.gov/api/temporal/daily/point (no key)",
        message=f"{len(daily):,} daily rows for {len(cells)} cell(s); sanity {'passed' if ok else 'CHECK'}",
        sanity={"checks": checks, "percent_missing": missing,
                "grid_elevation_m": {k: v["grid_elevation_m"] for k, v in cells.items()}},
        outputs=["power_daily.parquet", "power_cells.json"],
        notes="Gridded reanalysis, not an on-farm weather station. Temperatures are later "
              "adjusted from the grid-cell mean elevation to each field's elevation with a "
              "standard 6.5 degC/km lapse rate (documented in engine/agromet.py).",
    )


if __name__ == "__main__":
    run_source(SOURCE, TITLE, TIER, main)
