"""SSURGO soils via USDA Soil Data Access (MUST tier). No key needed.

1. Map-unit polygons clipped to the pilot box  -> data/processed/soil_mapunits.geojson
2. Component + horizon attributes per map unit  -> data/processed/soil_mapunit_props.parquet
3. Area-weighted soil properties per field      -> data/processed/field_soil.parquet
"""
from __future__ import annotations

import json

import geopandas as gpd
import numpy as np
import pandas as pd
import requests
from shapely import wkt as shapely_wkt
from shapely.geometry import box

from .common import (PILOT, PROCESSED, SourceError, cache_path, load_fields, run_source,
                     sanity_range, write_status)

SOURCE, TITLE, TIER = "ssurgo", "USDA NRCS SSURGO soils (Soil Data Access)", "MUST"
SDA_URL = "https://sdmdataaccess.sc.egov.usda.gov/Tabular/post.rest"


def sda_query(sql: str, tag: str) -> pd.DataFrame:
    """Run a Soil Data Access SQL query (cached on disk)."""
    path = cache_path(SOURCE, tag + sql, ".json")
    if path.exists() and path.stat().st_size > 0:
        js = json.loads(path.read_text(encoding="utf-8"))
    else:
        r = requests.post(SDA_URL, data={"query": sql, "format": "JSON+COLUMNNAME"}, timeout=300)
        if r.status_code != 200:
            raise SourceError(f"Soil Data Access HTTP {r.status_code}: {r.text[:200]}")
        js = r.json()
        path.write_text(json.dumps(js), encoding="utf-8")
    rows = js.get("Table", [])
    if not rows:
        return pd.DataFrame()
    return pd.DataFrame(rows[1:], columns=rows[0])


def fetch_mapunit_polygons(bbox) -> gpd.GeoDataFrame:
    w, s, e, n = bbox
    aoi = f"POLYGON(({w} {s},{e} {s},{e} {n},{w} {n},{w} {s}))"
    sql = f"""
~DeclareGeometry(@aoi)~
select @aoi = geometry::STPolyFromText('{aoi}', 4326)
~DeclareIdGeomTable(@clipped)~
~GetClippedMapunits(@aoi,polygon,geo,@clipped)~
select id as mukey, geom.STAsText() as wkt from @clipped
"""
    df = sda_query(sql, "mupolygons")
    if df.empty:
        raise SourceError("Soil Data Access returned no map-unit polygons for the pilot box",
                          action="Check SSURGO coverage for the area in Web Soil Survey.")
    geoms = [shapely_wkt.loads(t) for t in df["wkt"]]
    gdf = gpd.GeoDataFrame({"mukey": df["mukey"].astype(str)}, geometry=geoms, crs="EPSG:4326")
    gdf["geometry"] = gdf.geometry.buffer(0)
    return gdf.dissolve(by="mukey", as_index=False)


def fetch_properties(mukeys: list[str]) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    keys = ",".join(f"'{k}'" for k in mukeys)
    mu = sda_query(f"""
select mu.mukey, mu.musym, mu.muname, l.areasymbol, l.areaname,
       ma.aws0100wta, ma.drclassdcd, ma.hydgrpdcd, ma.slopegradwta, ma.niccdcd, ma.iccdcd,
       ma.brockdepmin, ma.wtdepannmin, ma.flodfreqdcd
from mapunit mu
join legend l on l.lkey = mu.lkey
left join muaggatt ma on ma.mukey = mu.mukey
where mu.mukey in ({keys})""", "muaggatt")
    comp = sda_query(f"""
select c.mukey, c.cokey, c.compname, c.comppct_r, c.majcompflag, c.compkind, c.drainagecl,
       c.hydgrp, c.slope_r, c.wei, c.weg, c.taxorder, c.irrcapcl, c.nirrcapcl, c.tfact
from component c where c.mukey in ({keys})""", "component")
    hz = sda_query(f"""
select c.mukey, c.cokey, ch.chkey, ch.hzname, ch.hzdept_r, ch.hzdepb_r, ch.sandtotal_r,
       ch.silttotal_r, ch.claytotal_r, ch.om_r, ch.awc_r, ch.ksat_r, ch.kwfact, ch.kffact,
       ch.ph1to1h2o_r, ch.ec_r, ch.sar_r, ch.caco3_r, ch.dbthirdbar_r,
       (select top 1 tg.texdesc from chtexturegrp tg
         where tg.chkey = ch.chkey and tg.rvindicator = 'Yes') as texture
from component c join chorizon ch on ch.cokey = c.cokey
where c.mukey in ({keys})""", "chorizon")
    return mu, comp, hz


def _num(df: pd.DataFrame, cols: list[str]) -> pd.DataFrame:
    for c in cols:
        if c in df.columns:
            df[c] = pd.to_numeric(df[c], errors="coerce")
    return df


def depth_weighted(h: pd.DataFrame, col: str, top: float, bottom: float) -> float:
    """Thickness-weighted mean of a horizon property between two depths (cm)."""
    t = h["hzdept_r"].clip(lower=top)
    b = h["hzdepb_r"].clip(upper=bottom)
    thick = (b - t).clip(lower=0)
    ok = thick.gt(0) & h[col].notna()
    if not ok.any():
        return float("nan")
    return float((h.loc[ok, col] * thick[ok]).sum() / thick[ok].sum())


def summarise_mapunits(mu: pd.DataFrame, comp: pd.DataFrame, hz: pd.DataFrame) -> pd.DataFrame:
    """One row per map unit: component-percent-weighted 0-30 cm properties + dominant traits."""
    mu = _num(mu, ["aws0100wta", "slopegradwta", "brockdepmin", "wtdepannmin"])
    comp = _num(comp, ["comppct_r", "slope_r", "wei", "tfact"])
    hz = _num(hz, ["hzdept_r", "hzdepb_r", "sandtotal_r", "silttotal_r", "claytotal_r", "om_r",
                   "awc_r", "ksat_r", "kwfact", "kffact", "ph1to1h2o_r", "ec_r", "sar_r",
                   "caco3_r", "dbthirdbar_r"])
    rows = []
    for mukey, cgrp in comp.groupby("mukey"):
        cgrp = cgrp.sort_values("comppct_r", ascending=False)
        dom = cgrp.iloc[0]
        acc: dict[str, list[tuple[float, float]]] = {}
        surf_tex, surf_k = None, float("nan")
        for _, c in cgrp.iterrows():
            h = hz[hz["cokey"] == c["cokey"]].sort_values("hzdept_r")
            if h.empty or not np.isfinite(c["comppct_r"]):
                continue
            for col, key in [("om_r", "om_pct_0_30"), ("claytotal_r", "clay_pct_0_30"),
                             ("sandtotal_r", "sand_pct_0_30"), ("silttotal_r", "silt_pct_0_30"),
                             ("ph1to1h2o_r", "ph_0_30"), ("ec_r", "ec_dsm_0_30"),
                             ("sar_r", "sar_0_30"), ("ksat_r", "ksat_um_s_0_30"),
                             ("dbthirdbar_r", "bulk_density_0_30"),
                             ("caco3_r", "caco3_pct_0_30")]:
                v = depth_weighted(h, col, 0, 30)
                if np.isfinite(v):
                    acc.setdefault(key, []).append((v, c["comppct_r"]))
            # mineral-surface erodibility: first horizon that has a K factor
            hk = h[h["kwfact"].notna()]
            if not hk.empty:
                acc.setdefault("kwfact_surface", []).append((float(hk.iloc[0]["kwfact"]), c["comppct_r"]))
            if c["cokey"] == dom["cokey"]:
                surf_tex = h.iloc[0]["texture"]
                surf_k = float(hk.iloc[0]["kwfact"]) if not hk.empty else float("nan")
        rec = {"mukey": str(mukey), "dominant_component": dom["compname"],
               "dominant_pct": dom["comppct_r"], "drainage_class": dom["drainagecl"],
               "hydrologic_group": dom["hydgrp"], "wind_erodibility_group": str(dom["weg"] or ""),
               "wind_erodibility_index": dom["wei"], "t_factor": dom["tfact"],
               "taxonomic_order": dom["taxorder"], "irrigated_capability_class": dom["irrcapcl"],
               "surface_texture": surf_tex, "kwfact_dominant": surf_k,
               "component_slope_pct": dom["slope_r"]}
        for key, pairs in acc.items():
            vals, wts = zip(*pairs)
            rec[key] = float(np.average(vals, weights=wts))
        rows.append(rec)
    props = pd.DataFrame(rows)
    mu["mukey"] = mu["mukey"].astype(str)
    out = mu.merge(props, on="mukey", how="left")
    out = out.rename(columns={"aws0100wta": "aws_0_100cm_cm", "slopegradwta": "mapunit_slope_pct",
                              "wtdepannmin": "water_table_depth_cm",
                              "brockdepmin": "bedrock_depth_cm", "flodfreqdcd": "flooding_frequency"})
    return out


NUMERIC_FIELD_COLS = ["om_pct_0_30", "clay_pct_0_30", "sand_pct_0_30", "silt_pct_0_30", "ph_0_30",
                      "ec_dsm_0_30", "sar_0_30", "ksat_um_s_0_30", "bulk_density_0_30",
                      "caco3_pct_0_30", "kwfact_surface", "aws_0_100cm_cm", "mapunit_slope_pct",
                      "wind_erodibility_index", "t_factor"]
CATEGORICAL_FIELD_COLS = ["muname", "musym", "surface_texture", "drainage_class", "hydrologic_group",
                          "wind_erodibility_group", "dominant_component", "taxonomic_order",
                          "irrigated_capability_class"]


def field_soil_table(fields: gpd.GeoDataFrame, mupoly: gpd.GeoDataFrame, props: pd.DataFrame) -> pd.DataFrame:
    """Area-weighted soil properties for each field (dominant map unit for categories)."""
    utm = PILOT["utm_epsg"]
    f = fields.to_crs(utm)[["field_id", "geometry"]]
    m = mupoly.to_crs(utm)
    inter = gpd.overlay(f, m, how="intersection", keep_geom_type=True)
    inter["area_m2"] = inter.geometry.area
    inter = inter.merge(props, on="mukey", how="left")
    rows = []
    for fid, g in inter.groupby("field_id"):
        total = g["area_m2"].sum()
        field_area = float(f.loc[f["field_id"] == fid, "geometry"].area.iloc[0])
        rec: dict = {"field_id": fid, "soil_coverage_fraction": round(float(total / field_area), 3),
                     "n_mapunits": int(g["mukey"].nunique())}
        for col in NUMERIC_FIELD_COLS:
            v = pd.to_numeric(g[col], errors="coerce")
            ok = v.notna()
            rec[col] = float(np.average(v[ok], weights=g.loc[ok, "area_m2"])) if ok.any() else float("nan")
        by_mu = g.groupby("mukey")["area_m2"].sum().sort_values(ascending=False)
        dom = g[g["mukey"] == by_mu.index[0]].iloc[0]
        rec["dominant_mukey"] = by_mu.index[0]
        rec["dominant_mapunit_share"] = round(float(by_mu.iloc[0] / total), 3)
        for col in CATEGORICAL_FIELD_COLS:
            rec[col] = dom[col]
        rec["mapunits"] = json.dumps([
            {"mukey": k, "share": round(float(a / total), 3),
             "name": str(g[g["mukey"] == k]["muname"].iloc[0])} for k, a in by_mu.items()])
        rows.append(rec)
    return pd.DataFrame(rows)


def main() -> None:
    fields = load_fields()
    mupoly = fetch_mapunit_polygons(PILOT["bbox"])
    mu, comp, hz = fetch_properties(sorted(mupoly["mukey"].unique()))
    props = summarise_mapunits(mu, comp, hz)
    props.to_parquet(PROCESSED / "soil_mapunit_props.parquet", index=False)

    layer = mupoly.merge(props[["mukey", "musym", "muname", "surface_texture", "drainage_class",
                                "hydrologic_group", "om_pct_0_30", "kwfact_surface",
                                "wind_erodibility_group", "aws_0_100cm_cm", "ec_dsm_0_30"]],
                         on="mukey", how="left")
    layer["geometry"] = layer.geometry.simplify(0.00005, preserve_topology=True)
    layer = layer.clip(box(*PILOT["bbox"]))
    layer.to_file(PROCESSED / "soil_mapunits.geojson", driver="GeoJSON")

    fsoil = field_soil_table(fields, mupoly, props)
    fsoil.to_parquet(PROCESSED / "field_soil.parquet", index=False)

    checks = [
        sanity_range(fsoil["om_pct_0_30"], 0, 20, "organic matter % (0-30 cm)"),
        sanity_range(fsoil["clay_pct_0_30"], 0, 70, "clay % (0-30 cm)"),
        sanity_range(fsoil["ph_0_30"], 4, 10.5, "pH (0-30 cm)"),
        sanity_range(fsoil["kwfact_surface"], 0.02, 0.69, "K factor (whole soil)"),
        sanity_range(fsoil["aws_0_100cm_cm"], 0, 40, "available water storage 0-100 cm (cm)"),
        sanity_range(fsoil["soil_coverage_fraction"], 0.9, 1.01, "share of field with soil data"),
    ]
    ok = all(c["passed"] for c in checks) and len(fsoil) == len(fields)
    areas = sorted(set(mu["areasymbol"].astype(str) + " - " + mu["areaname"].astype(str)))
    write_status(
        SOURCE, status="ok" if ok else "partial", title=TITLE, tier=TIER,
        fetched=f"{len(mupoly)} map units ({len(comp)} components, {len(hz)} horizons) in the pilot "
                f"box; soil survey area(s): {'; '.join(areas)}",
        resolution="Vector map units, nominal survey scale 1:24,000 (Order 2-3)",
        date_range="Current published SSURGO snapshot (static)",
        credit="Soil Survey Staff, USDA Natural Resources Conservation Service. Soil Survey "
               "Geographic (SSURGO) Database. Public domain.",
        access="Soil Data Access web service https://sdmdataaccess.sc.egov.usda.gov/Tabular/post.rest",
        message=f"{len(mupoly)} map units; soil table for {len(fsoil)}/{len(fields)} fields; "
                f"sanity {'passed' if ok else 'CHECK'}",
        sanity={"checks": checks, "crs": "EPSG:4326"},
        outputs=["soil_mapunits.geojson", "soil_mapunit_props.parquet", "field_soil.parquet"],
        notes="Map units are polygons with representative values, not measurements of every "
              "square metre. Values are component-percent weighted (0-30 cm, thickness weighted) "
              "and then area weighted over the field.",
    )


if __name__ == "__main__":
    run_source(SOURCE, TITLE, TIER, main)
