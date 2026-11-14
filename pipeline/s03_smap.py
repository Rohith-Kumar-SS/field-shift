"""SMAP soil moisture (MUST tier). Needs EARTHDATA_TOKEN.

Product: SPL3SMP_E - SMAP Enhanced L3 Radiometer Global Daily 9 km EASE-Grid Soil
Moisture (morning 6 am and evening 6 pm overpasses). Route: NASA cloud OPeNDAP (NSIDC
DAAC), requesting only the handful of 9 km cells over the pilot valley from each daily
file instead of downloading ~300 MB global files.

Outputs
  data/raw/smap/smap_<year>.parquet            every retrieval for the valley cells
  data/processed/smap_cell_monthly.parquet     monthly mean + anomaly (z-score) per cell
  data/processed/smap_cells.geojson            cell footprints (for the map)
  data/processed/field_smap_cell.json          which cell each field falls in
"""
from __future__ import annotations

import json
from concurrent.futures import ThreadPoolExecutor, as_completed

import geopandas as gpd
import numpy as np
import pandas as pd
import requests
from pyproj import Transformer
from shapely.geometry import Polygon

from .common import PILOT, PROCESSED, RAW, SourceError, load_fields, run_source, sanity_range, write_status
from .earthdata import list_granules, opendap_subset, read_nc

SOURCE, TITLE, TIER = "smap", "SMAP enhanced L3 soil moisture (SPL3SMP_E, 9 km)", "MUST"
SHORT_NAME = "SPL3SMP_E"
START, END = "2015-03-31", "2025-12-31"
# EASE-Grid 2.0 global 9 km (1624 rows x 3856 columns), EPSG:6933
CELL, X0, Y0 = 9008.055210146, -17367530.445161372, 7314540.830638504
AM, PM = "/Soil_Moisture_Retrieval_Data_AM/", "/Soil_Moisture_Retrieval_Data_PM/"


def collection_id() -> tuple[str, str]:
    r = requests.get("https://cmr.earthdata.nasa.gov/search/collections.umm_json",
                     params={"short_name": SHORT_NAME, "page_size": 20}, timeout=120)
    r.raise_for_status()
    items = r.json().get("items", [])
    if not items:
        raise SourceError(f"{SHORT_NAME} not found in NASA CMR")
    best = max(items, key=lambda it: it["umm"]["Version"])
    return best["meta"]["concept-id"], best["umm"]["Version"]


def ease_window(bbox) -> tuple[int, int, int, int]:
    """EASE-Grid 2.0 row/column range covering a lon/lat box."""
    w, s, e, n = bbox
    tr = Transformer.from_crs(4326, 6933, always_xy=True)
    xs, ys = tr.transform([w, e], [s, n])
    c0, c1 = int((xs[0] - X0) // CELL), int((xs[1] - X0) // CELL)
    r0, r1 = int((Y0 - ys[1]) // CELL), int((Y0 - ys[0]) // CELL)
    return r0, r1, c0, c1


def cell_polygon(row: int, col: int) -> Polygon:
    tr = Transformer.from_crs(6933, 4326, always_xy=True)
    x0, x1 = X0 + col * CELL, X0 + (col + 1) * CELL
    y1, y0 = Y0 - row * CELL, Y0 - (row + 1) * CELL
    xs, ys = tr.transform([x0, x1, x1, x0], [y0, y0, y1, y1])
    return Polygon(zip(xs, ys))


def fetch_day(gran: dict, win) -> list[dict]:
    r0, r1, c0, c1 = win
    sl = f"[{r0}:{r1}][{c0}:{c1}]"
    ce = ";".join([AM + v + sl for v in ("soil_moisture", "retrieval_qual_flag", "soil_moisture_error",
                                         "vegetation_water_content", "surface_temperature")]
                  + [PM + v + sl for v in ("soil_moisture_pm", "retrieval_qual_flag_pm")])
    ds = read_nc(opendap_subset(gran["opendap"], ce))
    try:
        ga, gp = ds["Soil_Moisture_Retrieval_Data_AM"], ds["Soil_Moisture_Retrieval_Data_PM"]
        get = lambda g, v: np.ma.filled(g[v][:], np.nan).astype("float64")  # noqa: E731
        sm_am, q_am = get(ga, "soil_moisture"), get(ga, "retrieval_qual_flag")
        err, vwc, ts = get(ga, "soil_moisture_error"), get(ga, "vegetation_water_content"), get(ga, "surface_temperature")
        sm_pm, q_pm = get(gp, "soil_moisture_pm"), get(gp, "retrieval_qual_flag_pm")
    finally:
        ds.close()
    day = gran["start"][:10]
    rows = []
    for i in range(sm_am.shape[0]):
        for j in range(sm_am.shape[1]):
            rows.append({"date": day, "row": r0 + i, "col": c0 + j,
                         "sm_am": sm_am[i, j], "qual_am": q_am[i, j], "sm_pm": sm_pm[i, j],
                         "qual_pm": q_pm[i, j], "sm_error": err[i, j], "vwc": vwc[i, j],
                         "surface_temp_k": ts[i, j]})
    return rows


def fetch_all(workers: int = 10) -> tuple[pd.DataFrame, list[str], str]:
    cid, version = collection_id()
    win = ease_window(PILOT["bbox"])
    out_dir = RAW / "smap"
    out_dir.mkdir(parents=True, exist_ok=True)
    frames, failed = [], []
    for year in range(int(START[:4]), int(END[:4]) + 1):
        cache = out_dir / f"smap_{year}.parquet"
        if cache.exists():
            frames.append(pd.read_parquet(cache))
            continue
        t0 = max(f"{year}-01-01", START)
        t1 = min(f"{year}-12-31", END)
        grans = {}
        for g in list_granules(cid, f"{t0}T00:00:00Z,{t1}T23:59:59Z"):
            if g["opendap"]:
                grans[g["start"][:10]] = g      # keep the last (latest) granule per day
        rows, year_failed = [], []
        with ThreadPoolExecutor(max_workers=workers) as ex:
            futs = {ex.submit(fetch_day, g, win): d for d, g in grans.items()}
            for fut in as_completed(futs):
                try:
                    rows.extend(fut.result())
                except SourceError as exc:
                    if exc.action:      # authorisation problem: stop, it will not fix itself
                        raise
                    year_failed.append(futs[fut])
                except Exception:  # noqa: BLE001
                    year_failed.append(futs[fut])
        df = pd.DataFrame(rows)
        print(f"  smap {year}: {len(grans)} daily files, {len(year_failed)} failed", flush=True)
        failed += year_failed
        if not df.empty and len(year_failed) <= 0.02 * max(len(grans), 1):
            df.to_parquet(cache, index=False)   # cache only (near-)complete years
        frames.append(df)
    data = pd.concat([f for f in frames if not f.empty], ignore_index=True)
    return data, failed, version


def tidy(raw: pd.DataFrame) -> pd.DataFrame:
    """One row per cell-day: mean of the successful morning/evening retrievals."""
    df = raw.copy()
    df["date"] = pd.to_datetime(df["date"])
    for c in ("sm_am", "sm_pm", "sm_error", "vwc", "surface_temp_k"):
        df.loc[~np.isfinite(df[c]) | (df[c] < 0), c] = np.nan
    df.loc[df["sm_am"] > 0.6, "sm_am"] = np.nan
    df.loc[df["sm_pm"] > 0.6, "sm_pm"] = np.nan
    df["sm"] = df[["sm_am", "sm_pm"]].mean(axis=1, skipna=True)
    # bit 0 of retrieval_qual_flag = 0 means "recommended quality"
    rec_am = df["sm_am"].notna() & ((df["qual_am"].fillna(1).astype("int64") & 1) == 0)
    rec_pm = df["sm_pm"].notna() & ((df["qual_pm"].fillna(1).astype("int64") & 1) == 0)
    df["recommended"] = rec_am | rec_pm
    return df.dropna(subset=["sm"])


def monthly(df: pd.DataFrame) -> pd.DataFrame:
    from engine.agromet import monthly_zscore

    df = df.assign(year=df["date"].dt.year, month=df["date"].dt.month)
    g = df.groupby(["row", "col", "year", "month"])
    out = g.agg(sm_mean=("sm", "mean"), n_days=("sm", "size"),
                share_recommended=("recommended", "mean"),
                sm_error=("sm_error", "mean"), vwc=("vwc", "mean")).reset_index()
    out.loc[out["n_days"] < 5, "sm_mean"] = np.nan     # too few retrievals to call it a month
    parts = []
    for _, cell in out.groupby(["row", "col"]):
        cell = cell.sort_values(["year", "month"]).copy()
        cell["sm_anomaly_z"] = monthly_zscore(cell["sm_mean"], cell["month"])
        clim = cell.groupby("month")["sm_mean"].transform("mean")
        cell["sm_clim"] = clim
        cell["sm_pct_of_normal"] = cell["sm_mean"] / clim * 100
        parts.append(cell)
    out = pd.concat(parts, ignore_index=True)
    out["cell_id"] = "S" + out["row"].astype(str) + "_" + out["col"].astype(str)
    return out


def main() -> None:
    fields = load_fields()
    raw, failed, version = fetch_all()
    if raw.empty:
        raise SourceError("SMAP returned no data for the pilot valley")
    daily = tidy(raw)
    mon = monthly(daily)
    mon.to_parquet(PROCESSED / "smap_cell_monthly.parquet", index=False)

    cells = sorted({(int(r), int(c)) for r, c in zip(mon["row"], mon["col"])})
    cgdf = gpd.GeoDataFrame(
        {"cell_id": [f"S{r}_{c}" for r, c in cells]},
        geometry=[cell_polygon(r, c) for r, c in cells], crs="EPSG:4326")
    cgdf.to_file(PROCESSED / "smap_cells.geojson", driver="GeoJSON")
    mapping = {}
    for _, f in fields.iterrows():
        hit = cgdf[cgdf.contains(f.geometry.centroid)]
        mapping[f["field_id"]] = hit.iloc[0]["cell_id"] if len(hit) else None
    (PROCESSED / "field_smap_cell.json").write_text(json.dumps(mapping, indent=2), encoding="utf-8")

    checks = [sanity_range(daily["sm"], 0.0, 0.6, "soil moisture m3/m3"),
              sanity_range(mon["sm_anomaly_z"].dropna(), -5, 5, "monthly anomaly z-score"),
              sanity_range(mon["n_days"], 1, 31, "retrieval days per month")]
    ok = all(c["passed"] for c in checks) and all(mapping.values())
    days = daily["date"].dt.normalize().nunique()
    write_status(
        SOURCE, status="ok" if (ok and len(failed) < 40) else "partial", title=TITLE, tier=TIER,
        fetched=f"version {version}: {days:,} days with retrievals, {len(cells)} cells of 9 km over the "
                f"valley, morning + evening overpasses",
        resolution="9 km EASE-Grid 2.0 (interpolated from ~33 km radiometer footprints); "
                   "a retrieval every 2-3 days",
        date_range=f"{daily['date'].min():%Y-%m-%d} to {daily['date'].max():%Y-%m-%d}",
        credit="O'Neill, P. E. et al. SMAP Enhanced L3 Radiometer Global and Polar Grid Daily 9 km "
               "EASE-Grid Soil Moisture. NASA National Snow and Ice Data Center DAAC, Boulder, Colorado.",
        access="NASA cloud OPeNDAP (opendap.earthdata.nasa.gov), spatial subset per daily file, "
               "Earthdata bearer token",
        message=f"{days:,} retrieval days, {len(mon):,} cell-months; {len(failed)} daily files failed; "
                f"sanity {'passed' if ok else 'CHECK'}",
        sanity={"checks": checks, "grid": "EASE-Grid 2.0 (EPSG:6933)",
                "share_recommended_quality": round(float(daily["recommended"].mean()), 3),
                "failed_days": failed[:30]},
        outputs=["smap_cell_monthly.parquet", "smap_cells.geojson", "field_smap_cell.json"],
        notes="Top ~5 cm of soil only, and each 9 km cell is mostly desert shrubland with the "
              "irrigated pivots mixed in: it shows whether the valley is wetter or drier than "
              "usual, not the moisture under one pivot. Anomaly z = (month mean - that calendar "
              "month's 2015-2025 mean) / standard deviation; months with under 5 retrieval days "
              "are left blank.",
    )


if __name__ == "__main__":
    run_source(SOURCE, TITLE, TIER, main)
