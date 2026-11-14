"""USGS groundwater levels (OPTIONAL tier, ground-based). No key needed.

Long-term water trend, measured in wells rather than from space: depth to groundwater
(USGS parameter 72019) for every well in and around the pilot valley, from the USGS
Water Data API. This is the ground truth that satellites cannot give at field scale
(GRACE sees ~300 km blobs), and it is what the "long-term water trend" panel shows.

Outputs
  data/processed/groundwater_levels.parquet   every measurement
  data/processed/groundwater_wells.geojson    wells with record length and trend
"""
from __future__ import annotations

import json

import geopandas as gpd
import numpy as np
import pandas as pd
import requests
from shapely.geometry import Point

from .common import PILOT, PROCESSED, SourceError, cache_path, run_source, sanity_range, write_status

SOURCE, TITLE, TIER = "usgs_nwis", "USGS groundwater levels (depth to water)", "OPTIONAL"
API = "https://api.waterdata.usgs.gov/ogcapi/v0/collections/field-measurements/items"
FT_TO_M = 0.3048
MARGIN = 0.12   # degrees around the pilot box: wells just outside still describe the aquifer


def fetch_all(bbox: str) -> list[dict]:
    key = API + bbox + "72019"
    path = cache_path(SOURCE, key, ".json")
    if path.exists() and path.stat().st_size > 0:
        return json.loads(path.read_text(encoding="utf-8"))
    feats: list[dict] = []
    url, params = API, {"f": "json", "bbox": bbox, "parameter_code": "72019", "limit": 10000}
    for _ in range(60):
        r = requests.get(url, params=params, timeout=300)
        if r.status_code == 429:
            raise SourceError("USGS Water Data API rate limit reached",
                              action="Wait an hour and re-run `python -m pipeline.s10_nwis`, or add a "
                                     "free API key from https://api.waterdata.usgs.gov/signup.")
        if r.status_code != 200:
            raise SourceError(f"USGS Water Data API HTTP {r.status_code}: {r.text[:160]}")
        js = r.json()
        feats.extend(js.get("features", []))
        nxt = [l["href"] for l in js.get("links", []) if l.get("rel") == "next"]
        if not nxt or not js.get("features"):
            break
        url, params = nxt[0], None
    path.write_text(json.dumps(feats), encoding="utf-8")
    return feats


def main() -> None:
    from engine.agromet import theil_sen_trend

    w, s, e, n = PILOT["bbox"]
    bbox = f"{w - MARGIN:.2f},{s - MARGIN:.2f},{e + MARGIN:.2f},{n + MARGIN:.2f}"
    feats = fetch_all(bbox)
    if not feats:
        raise SourceError("No USGS groundwater-level measurements found near the pilot valley")
    rows = []
    for f in feats:
        p = f["properties"]
        try:
            val = float(p["value"])
        except (TypeError, ValueError):
            continue
        if p.get("unit_of_measure") != "ft" or not f.get("geometry"):
            continue
        lon, lat = f["geometry"]["coordinates"][:2]
        rows.append({"site_id": p["monitoring_location_id"], "time": p["time"], "depth_ft": val,
                     "depth_m": val * FT_TO_M, "lon": lon, "lat": lat,
                     "approval": p.get("approval_status"),
                     "qualifier": ",".join(p.get("qualifier") or [])})
    df = pd.DataFrame(rows)
    df["time"] = pd.to_datetime(df["time"], utc=True, errors="coerce").dt.tz_localize(None)
    df = df.dropna(subset=["time"])
    # measurements taken while the well (or a neighbour) was pumping are not the resting level
    df["static"] = ~df["qualifier"].str.contains("Pump|Recently|Nearby", case=False, na=False)
    df["year"] = df["time"].dt.year
    df = df.sort_values(["site_id", "time"])
    df.to_parquet(PROCESSED / "groundwater_levels.parquet", index=False)

    wells = []
    for sid, g in df[df["static"]].groupby("site_id"):
        annual = g.groupby("year")["depth_m"].median()
        recent = annual[annual.index >= 1990]
        tr = theil_sen_trend(recent.index, recent.values) if len(recent) >= 8 else None
        inside = (w <= g["lon"].iloc[0] <= e) and (s <= g["lat"].iloc[0] <= n)
        wells.append({
            "site_id": sid, "n_measurements": int(len(g)), "first_year": int(annual.index.min()),
            "last_year": int(annual.index.max()), "n_years": int(len(annual)),
            "depth_m_first": round(float(annual.iloc[0]), 2),
            "depth_m_last": round(float(annual.iloc[-1]), 2),
            "change_m": round(float(annual.iloc[-1] - annual.iloc[0]), 2),
            "trend_m_per_decade_since_1990": tr["slope_per_decade"] if tr else None,
            "trend_p_value": tr["p_value"] if tr else None,
            "trend_direction": tr["direction"] if tr else "not enough data",
            "inside_pilot_box": bool(inside),
            "geometry": Point(g["lon"].iloc[0], g["lat"].iloc[0]),
        })
    wg = gpd.GeoDataFrame(wells, crs="EPSG:4326")
    wg.to_file(PROCESSED / "groundwater_wells.geojson", driver="GeoJSON")

    long_rec = wg[wg["trend_m_per_decade_since_1990"].notna()]
    checks = [sanity_range(df["depth_m"], -5, 250, "depth to water m"),
              sanity_range(df["year"], 1900, 2026, "measurement year")]
    ok = all(c["passed"] for c in checks) and len(long_rec) >= 3
    deepening = int((long_rec["trend_m_per_decade_since_1990"] > 0).sum())
    write_status(
        SOURCE, status="ok" if ok else "partial", title=TITLE, tier=TIER,
        fetched=f"{len(df):,} depth-to-water measurements at {df['site_id'].nunique()} wells within "
                f"{MARGIN} degrees of the pilot box; {len(long_rec)} wells have 8+ years since 1990",
        resolution="Point measurements at wells; typically one or two visits a year",
        date_range=f"{df['time'].min():%Y-%m-%d} to {df['time'].max():%Y-%m-%d}",
        credit="U.S. Geological Survey, National Water Information System (USGS Water Data for the "
               "Nation). Public domain.",
        access="USGS Water Data API https://api.waterdata.usgs.gov/ogcapi/v0/collections/field-measurements",
        message=f"{df['site_id'].nunique()} wells, {len(df):,} measurements; of {len(long_rec)} wells with "
                f"long records, {deepening} show the water table getting deeper since 1990; sanity "
                f"{'passed' if ok else 'CHECK'}",
        sanity={"checks": checks, "crs": "EPSG:4326",
                "median_trend_m_per_decade": (round(float(long_rec["trend_m_per_decade_since_1990"].median()), 2)
                                              if len(long_rec) else None)},
        outputs=["groundwater_levels.parquet", "groundwater_wells.geojson"],
        notes="Depth below land surface: a larger number means a deeper water table. Readings "
              "flagged as taken during or just after pumping are excluded from trends. A well a "
              "few kilometres from a field describes the aquifer, not that field's own well.",
    )


if __name__ == "__main__":
    run_source(SOURCE, TITLE, TIER, main)
