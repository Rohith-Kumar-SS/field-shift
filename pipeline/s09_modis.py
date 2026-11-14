"""MODIS/Terra vegetation index, 250 m, 16-day (OPTIONAL tier). No key needed.

Product: MOD13Q1 v061 NDVI from the ORNL DAAC MODIS subset web service. Landsat gives
the field-scale picture for 2018-2025; MODIS adds a 25-year record (2001-2025) so the
app can show whether peak greenness on a field has changed over the long term.

Outputs
  data/raw/modis/*.json                       one response per 10 composites (cached)
  data/processed/modis_field_ndvi.parquet     per-field NDVI for every 16-day composite
"""
from __future__ import annotations

import json
from concurrent.futures import ThreadPoolExecutor

import numpy as np
import pandas as pd
import requests
from affine import Affine

from .common import (CLIMATE_END, PILOT, PROCESSED, SourceError, cache_path, load_fields, run_source,
                     sanity_range, write_status)
from .zonal import coverage_weights, weighted_mean

SOURCE, TITLE, TIER = "modis", "MODIS/Terra NDVI 250 m (MOD13Q1 v061)", "OPTIONAL"
API = "https://modis.ornl.gov/rst/api/v1/MOD13Q1/subset"
SINUSOIDAL = "+proj=sinu +lon_0=0 +x_0=0 +y_0=0 +R=6371007.181 +units=m +no_defs"
START_YEAR = 2001
KM_NS, KM_EW = 9, 14         # half-height / half-width (km). Wide in x: the sinusoidal grid is sheared here,
                             # so a rectangle in grid space is a parallelogram on the ground
CHUNKS = [("001", "145"), ("161", "305"), ("321", "353")]   # <= 10 composites per request


def fetch_chunk(year: int, d0: str, d1: str) -> dict | None:
    params = {"latitude": PILOT["centroid"][1], "longitude": PILOT["centroid"][0],
              "startDate": f"A{year}{d0}", "endDate": f"A{year}{d1}",
              "kmAboveBelow": KM_NS, "kmLeftRight": KM_EW, "band": "250m_16_days_NDVI"}
    path = cache_path(SOURCE, API + json.dumps(params, sort_keys=True), ".json")
    if path.exists() and path.stat().st_size > 0:
        return json.loads(path.read_text(encoding="utf-8"))
    for attempt in range(4):
        try:
            r = requests.get(API, params=params, headers={"Accept": "application/json"}, timeout=300)
            if r.status_code == 200:
                js = r.json()
                path.write_text(json.dumps(js), encoding="utf-8")
                return js
            if r.status_code == 404:
                return None
        except requests.RequestException:
            pass
    return None


def main() -> None:
    fields = load_fields()
    jobs = [(y, a, b) for y in range(START_YEAR, CLIMATE_END + 1) for a, b in CHUNKS]
    with ThreadPoolExecutor(max_workers=4) as ex:
        results = list(ex.map(lambda j: fetch_chunk(*j), jobs))
    good = [r for r in results if r and r.get("subset")]
    if not good:
        raise SourceError("ORNL DAAC MODIS subset service returned no data",
                          action="Service may be busy; re-run `python -m pipeline.s09_modis` "
                                 "(responses already received are cached).")
    first = good[0]
    nrows, ncols, cs = int(first["nrows"]), int(first["ncols"]), float(first["cellsize"])
    transform = Affine(cs, 0, float(first["xllcorner"]), 0, -cs, float(first["yllcorner"]) + nrows * cs)
    fsin = fields.to_crs(SINUSOIDAL)
    weights = {f["field_id"]: coverage_weights(f.geometry, transform, (nrows, ncols), supersample=10)
               for _, f in fsin.iterrows()}
    scale = float(first.get("scale") or 0.0001)
    rows = []
    for js in good:
        if int(js["nrows"]) != nrows or int(js["ncols"]) != ncols:
            continue
        for sub in js["subset"]:
            a = np.array(sub["data"], dtype="float64").reshape(nrows, ncols)
            a[(a < -2000) | (a > 10000)] = np.nan       # fill value is -3000
            a *= scale
            for fid, w in weights.items():
                v, frac = weighted_mean(a, w)
                if frac >= 0.8:
                    rows.append({"field_id": fid, "date": pd.Timestamp(sub["calendar_date"]),
                                 "ndvi": round(v, 4)})
    df = pd.DataFrame(rows).drop_duplicates(["field_id", "date"]).sort_values(["field_id", "date"])
    df.to_parquet(PROCESSED / "modis_field_ndvi.parquet", index=False)

    npix = {fid: round(float(w.sum()), 1) for fid, w in weights.items()}
    checks = [sanity_range(df["ndvi"], -0.2, 1.0, "field NDVI"),
              sanity_range(df.groupby("field_id").size(), 400, 700, "composites per field")]
    ok = all(c["passed"] for c in checks)
    missing = len(jobs) - len(good)
    write_status(
        SOURCE, status="ok" if (ok and missing == 0) else "partial", title=TITLE, tier=TIER,
        fetched=f"{len(good)}/{len(jobs)} requests ({nrows} x {ncols} pixels around the pilot centre), "
                f"{df['date'].nunique()} composites",
        resolution="231.7 m (MODIS sinusoidal grid); 16-day maximum-value composites",
        date_range=f"{df['date'].min():%Y-%m-%d} to {df['date'].max():%Y-%m-%d}",
        credit="Didan, K. (2021). MODIS/Terra Vegetation Indices 16-Day L3 Global 250m SIN Grid V061. "
               "NASA EOSDIS LP DAAC. Subsets from ORNL DAAC (2018), MODIS and VIIRS Land Products "
               "Global Subsetting and Visualization Tool.",
        access="ORNL DAAC REST API https://modis.ornl.gov/rst/api/v1/MOD13Q1/subset (no key)",
        message=f"{len(df):,} field-composites, {df['date'].nunique()} dates; "
                f"{missing} request(s) missing; sanity {'passed' if ok else 'CHECK'}",
        sanity={"checks": checks, "crs": "MODIS sinusoidal",
                "modis_pixels_per_field": npix},
        outputs=["modis_field_ndvi.parquet"],
        notes="A 50 ha pivot holds only ~9 MODIS pixels and its edge pixels mix in desert, so MODIS "
              "NDVI reads lower than Landsat. The pixel-reliability band was not fetched (it would "
              "double the requests to a slow service); the app therefore uses only each year's "
              "peak-season maximum, which is robust to cloud and snow.",
    )


if __name__ == "__main__":
    run_source(SOURCE, TITLE, TIER, main)
