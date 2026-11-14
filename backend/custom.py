"""Evidence for a field the user draws, computed from the local processed rasters only.

No network calls: everything comes from data/processed. Sources that exist only for the
precomputed pilot fields (OpenET, MODIS) are reported as missing, never estimated.
"""
from __future__ import annotations

import json
import math
import uuid
from pathlib import Path

import geopandas as gpd
import numpy as np
import pandas as pd
import rasterio
from shapely.geometry import box, shape

from engine import context as ctxmod
from pipeline.common import PILOT, PROCESSED
from pipeline.s04_ssurgo import field_soil_table
from pipeline.s05_cdl import field_fractions
from pipeline.zonal import coverage_weights, weighted_mean

MIN_HA, MAX_HA = 2.0, 400.0


class CustomFieldError(ValueError):
    pass


def validate(geojson: dict) -> gpd.GeoDataFrame:
    try:
        geom = shape(geojson)
    except Exception as exc:  # noqa: BLE001
        raise CustomFieldError("That shape could not be read as a polygon.") from exc
    if geom.geom_type != "Polygon" or geom.is_empty:
        raise CustomFieldError("Please draw a single closed shape.")
    if not geom.is_valid:
        geom = geom.buffer(0)
    if geom.is_empty or geom.geom_type != "Polygon":
        raise CustomFieldError("The outline crosses itself. Please redraw it.")
    if not box(*PILOT["bbox"]).contains(geom):
        raise CustomFieldError("The field must lie inside the pilot area (the dashed box): data were "
                               "prepared for that area only.")
    gdf = gpd.GeoDataFrame({"field_id": ["CUSTOM"]}, geometry=[geom], crs="EPSG:4326")
    area = float(gdf.to_crs(PILOT["utm_epsg"]).area.iloc[0]) / 1e4
    if not (MIN_HA <= area <= MAX_HA):
        raise CustomFieldError(f"The shape covers {area:.1f} ha; please draw between {MIN_HA:.0f} and "
                               f"{MAX_HA:.0f} ha (5 to 990 acres).")
    gdf["area_ha"] = area
    return gdf


def terrain_for(gdf: gpd.GeoDataFrame) -> dict | None:
    ep, sp = PROCESSED / "rasters" / "elevation_m.tif", PROCESSED / "rasters" / "slope_pct.tif"
    if not ep.exists():
        return None
    with rasterio.open(ep) as src:
        elev = src.read(1)
        g = gdf.to_crs(src.crs).geometry.iloc[0]
        w = coverage_weights(g, src.transform, elev.shape, supersample=5)
    rr, cc = np.nonzero(w > 0.5)
    if rr.size < 4:
        return None
    z = elev[rr, cc]
    ok = np.isfinite(z)
    A = np.c_[cc[ok] * 30.0, rr[ok] * 30.0, np.ones(ok.sum())]
    coef, *_ = np.linalg.lstsq(A, z[ok], rcond=None)
    out = {"elevation_m": round(weighted_mean(elev, w)[0], 1),
           "slope_pct_plane": round(float(np.hypot(coef[0], coef[1]) * 100.0), 2)}
    if sp.exists():
        with rasterio.open(sp) as src:
            out["slope_pct_mean"] = round(weighted_mean(src.read(1), w)[0], 2)
    return out


def landsat_monthly_for(gdf: gpd.GeoDataFrame) -> pd.DataFrame:
    rows = []
    weights = None
    for path in sorted((PROCESSED / "rasters").glob("ndvi_monthly_*.tif")):
        year = int(path.stem.split("_")[-1])
        with rasterio.open(path) as src:
            if weights is None:
                g = gdf.to_crs(src.crs).geometry.iloc[0]
                weights = coverage_weights(g, src.transform, (src.height, src.width), supersample=5)
            stack = src.read().astype("float32")
            stack[stack == src.nodata] = np.nan
        for m in range(12):
            v, frac = weighted_mean(stack[m] / 10000.0, weights, min_valid_fraction=0.6)
            rows.append({"year": year, "month": m + 1, "ndvi": v, "n": 1 if np.isfinite(v) else 0,
                         "snow_share": np.nan})
    return pd.DataFrame(rows)


def build_custom(geojson: dict, name: str, store: dict) -> tuple[dict, dict, dict]:
    """Return (feature, context, evidence) for a drawn polygon."""
    gdf = validate(geojson)
    fid = "CUSTOM-" + uuid.uuid4().hex[:6].upper()
    gdf["field_id"] = fid
    c = gdf.to_crs(PILOT["utm_epsg"]).geometry.centroid
    cen = gpd.GeoSeries(c, crs=PILOT["utm_epsg"]).to_crs(4326).iloc[0]
    meta = {"field_id": fid, "name": name or "My drawn field", "lat": float(cen.y), "lon": float(cen.x),
            "area_ha": round(float(gdf["area_ha"].iloc[0]), 1), "is_custom": True}

    # soil: intersect with the survey map units
    soil = None
    mu_path = PROCESSED / "soil_mapunits.geojson"
    props_path = PROCESSED / "soil_mapunit_props.parquet"
    if mu_path.exists() and props_path.exists():
        mupoly = store.setdefault("mupoly", gpd.read_file(mu_path)[["mukey", "geometry"]])
        props = store.setdefault("muprops", pd.read_parquet(props_path))
        table = field_soil_table(gdf[["field_id", "geometry"]], mupoly, props)
        if len(table):
            soil = table.iloc[0].to_dict()

    cdl_paths = {int(p.stem.split("_")[-1]): p for p in (PROCESSED / "rasters").glob("cdl_*.tif")}
    cdl = field_fractions(gdf, cdl_paths) if cdl_paths else pd.DataFrame()
    cdl_rows = cdl[["year", "cdl_code", "cdl_name", "share"]].to_dict("records") if len(cdl) else []

    # nearest pilot field supplies the weather-grid cell and the local temperature correction
    summary = store["summary"]
    near = min(summary, key=lambda s: math.hypot((s["lon"] - meta["lon"]) * math.cos(math.radians(meta["lat"])),
                                                 s["lat"] - meta["lat"]))
    cell = store["cells"]["field_to_cell"][near["field_id"]]
    power = store["power"][store["power"]["cell_id"] == cell]
    smap = None
    cells_path = PROCESSED / "smap_cells.geojson"
    if store.get("smap") is not None and cells_path.exists():
        sc = store.setdefault("smap_cells", gpd.read_file(cells_path))
        hit = sc[sc.contains(cen)]
        if len(hit):
            smap = store["smap"][store["smap"]["cell_id"] == hit.iloc[0]["cell_id"]]

    # IMERG: the 0.1-degree cell under the field's centre, if that cell was downloaded
    imerg_cell = f"G{math.floor((meta['lon'] + 180) / 0.1)}_{math.floor((meta['lat'] + 90) / 0.1)}"
    imerg = None
    if store.get("imerg") is not None:
        rows = store["imerg"][store["imerg"]["cell_id"] == imerg_cell]
        imerg = rows if len(rows) else None

    ctx, ev = ctxmod.build(
        meta, store["kb"], power_daily=power,
        grid_elevation_m=store["cells"]["cells"][cell]["grid_elevation_m"],
        soil=soil, terrain=terrain_for(gdf), cdl_rows=cdl_rows,
        landsat_month=landsat_monthly_for(gdf), modis=None, openet=None,
        openet_valley=store.get("openet_valley"), smap=smap, imerg=imerg,
        wells=store.get("wells"), levels=store.get("levels"), bias=store["bias"].get(near["field_id"]))
    ctx["nearest_pilot_field"] = near["field_id"]
    ctx["imerg_cell"] = imerg_cell if imerg is not None else None
    ev["custom_note"] = ("Drawn by hand. Greenness comes from monthly Landsat composites, soil from the "
                         "survey map units under the shape, and weather from the same grid cell as "
                         f"{near['name']}. OpenET water use and the 25-year MODIS record are prepared "
                         "only for the pilot fields, so they are missing here and confidence is lower.")
    feature = {"type": "Feature", "geometry": json.loads(gdf.to_json())["features"][0]["geometry"],
               "properties": {**meta, "boundary_source": "Drawn by the user", "is_demo_data": False,
                              "crop_latest": ctx["history"][-1]["label"] if ctx["history"] else None,
                              "sources": ctx["sources"]}}
    return feature, ctx, ev
