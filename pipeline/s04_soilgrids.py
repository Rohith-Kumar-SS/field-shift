"""SoilGrids 2.0 soil properties (ISRIC) for regions without a national soil survey service.

A global 250 m machine-learning map of soil properties, not a field survey. Six properties
at three depths are clipped for the pilot box through ISRIC's WCS, combined to 0-30 cm,
and averaged over each field or block.

Derived (and labelled as derived in the app):
  texture class        USDA texture triangle from sand/silt/clay
  K factor             EPIC equation (Williams 1995) from texture and organic carbon
  wind erodibility     NRCS wind-erodibility group for that texture class

Outputs: data/processed/<region>/field_soil.parquet, rasters/soil_<property>.tif
"""
from __future__ import annotations

import io
import json
import math

import numpy as np
import pandas as pd
import rasterio
import requests

from .common import PILOT, PROCESSED, SourceError, cache_path, load_fields, run_source, sanity_range, write_status
from .zonal import coverage_weights, weighted_mean

SOURCE, TITLE, TIER = "soilgrids", "SoilGrids 2.0 soil properties (ISRIC, 250 m)", "MUST"
WCS = "https://maps.isric.org/mapserv"
DEPTHS = [("0-5cm", 5), ("5-15cm", 10), ("15-30cm", 15)]
# property -> (output column, factor to conventional units)
PROPS = {"clay": ("clay_pct_0_30", 0.1), "sand": ("sand_pct_0_30", 0.1), "silt": ("silt_pct_0_30", 0.1),
         "soc": ("soc_pct_0_30", 0.01), "phh2o": ("ph_0_30", 0.1), "bdod": ("bulk_density_0_30", 0.01),
         "cec": ("cec_cmol_kg_0_30", 0.1), "nitrogen": ("nitrogen_g_kg_0_30", 0.01)}
WEG = {"sand": ("1", 220), "loamy sand": ("2", 134), "sandy loam": ("3", 86), "clay": ("4", 86),
       "silty clay": ("4", 86), "loam": ("5", 56), "sandy clay loam": ("5", 56), "sandy clay": ("5", 56),
       "silt loam": ("6", 48), "clay loam": ("6", 48), "silty clay loam": ("7", 38), "silt": ("7", 38)}


def fetch(prop: str, depth: str) -> tuple[np.ndarray, rasterio.Affine]:
    w, s, e, n = PILOT["bbox"]
    pad = 0.01
    url = (f"{WCS}?map=/map/{prop}.map&SERVICE=WCS&VERSION=2.0.1&REQUEST=GetCoverage"
           f"&COVERAGEID={prop}_{depth}_mean&FORMAT=image/tiff"
           f"&SUBSET=X({w - pad},{e + pad})&SUBSET=Y({s - pad},{n + pad})"
           "&SUBSETTINGCRS=http://www.opengis.net/def/crs/EPSG/0/4326"
           "&OUTPUTCRS=http://www.opengis.net/def/crs/EPSG/0/4326")
    path = cache_path(SOURCE, url, ".tif")
    if not (path.exists() and path.stat().st_size > 500):
        for _ in range(4):
            try:
                r = requests.get(url, timeout=180)
                if r.status_code == 200 and r.content[:2] in (b"II", b"MM"):
                    path.write_bytes(r.content)
                    break
            except requests.RequestException:
                pass
        else:
            raise SourceError(f"SoilGrids WCS did not return {prop} {depth}",
                              action="ISRIC's map server may be busy; re-run `python tasks.py data soilgrids`.")
    with rasterio.open(path) as src:
        a = src.read(1).astype("float32")
        a[a <= 0] = np.nan
        return a, src.transform


def texture_class(sand: float, silt: float, clay: float) -> str:
    """USDA soil texture triangle."""
    if not all(map(math.isfinite, (sand, silt, clay))):
        return "unknown"
    if silt + 1.5 * clay < 15:
        return "sand"
    if silt + 2 * clay < 30:
        return "loamy sand"
    if (7 <= clay < 20 and sand > 52 and silt + 2 * clay >= 30) or (clay < 7 and silt < 50 and silt + 2 * clay >= 30):
        return "sandy loam"
    if 7 <= clay < 27 and 28 <= silt < 50 and sand <= 52:
        return "loam"
    if (silt >= 50 and 12 <= clay < 27) or (50 <= silt < 80 and clay < 12):
        return "silt loam"
    if silt >= 80 and clay < 12:
        return "silt"
    if 20 <= clay < 35 and silt < 28 and sand > 45:
        return "sandy clay loam"
    if 27 <= clay < 40 and 20 < sand <= 45:
        return "clay loam"
    if 27 <= clay < 40 and sand <= 20:
        return "silty clay loam"
    if clay >= 35 and sand > 45:
        return "sandy clay"
    if clay >= 40 and silt >= 40:
        return "silty clay"
    if clay >= 40:
        return "clay"
    return "loam"


def epic_k(sand: float, silt: float, clay: float, oc: float) -> float:
    """Soil erodibility K (US customary units) from the EPIC equation (Williams 1995)."""
    sn = 1 - sand / 100.0
    f_csand = 0.2 + 0.3 * math.exp(-0.256 * sand * (1 - silt / 100.0))
    f_clsi = (silt / (clay + silt)) ** 0.3
    f_orgc = 1 - 0.25 * oc / (oc + math.exp(3.72 - 2.95 * oc))
    f_hisand = 1 - 0.7 * sn / (sn + math.exp(-5.51 + 22.9 * sn))
    return f_csand * f_clsi * f_orgc * f_hisand


def main() -> None:
    fields = load_fields()
    rdir = PROCESSED / "rasters"
    rdir.mkdir(parents=True, exist_ok=True)
    grids, transform = {}, None
    for prop, (col, factor) in PROPS.items():
        acc = None
        for depth, thick in DEPTHS:
            a, transform = fetch(prop, depth)
            acc = a * thick if acc is None else acc + a * thick
        grids[col] = acc / 30.0 * factor
        with rasterio.open(rdir / f"soil_{col}.tif", "w", driver="GTiff", height=acc.shape[0], width=acc.shape[1],
                           count=1, dtype="float32", crs="EPSG:4326", transform=transform, nodata=np.nan,
                           compress="deflate") as dst:
            dst.write(grids[col].astype("float32"), 1)
    grids["om_pct_0_30"] = grids["soc_pct_0_30"] * 1.724      # van Bemmelen factor

    rows = []
    for _, f in fields.iterrows():
        shape = next(iter(grids.values())).shape
        w = coverage_weights(f.geometry, transform, shape, supersample=20)
        rec = {"field_id": f["field_id"]}
        for col, g in grids.items():
            rec[col] = round(weighted_mean(g, w)[0], 3)
        tex = texture_class(rec["sand_pct_0_30"], rec["silt_pct_0_30"], rec["clay_pct_0_30"])
        group, index = WEG.get(tex, ("5", 56))
        rec.update(
            surface_texture=tex.capitalize(), muname="SoilGrids 250 m cell (global model)",
            kwfact_surface=round(epic_k(rec["sand_pct_0_30"], rec["silt_pct_0_30"], rec["clay_pct_0_30"],
                                        rec["soc_pct_0_30"]), 3),
            wind_erodibility_group=group, wind_erodibility_index=float(index),
            ec_dsm_0_30=None, sar_0_30=None, aws_0_100cm_cm=None, drainage_class=None, hydrologic_group=None,
            soil_coverage_fraction=1.0, n_mapunits=1, dominant_mapunit_share=1.0,
            mapunits=json.dumps([]), derived="texture class, K factor and wind erodibility are derived from "
                                             "the mapped sand, silt, clay and organic carbon")
        rows.append(rec)
    df = pd.DataFrame(rows)
    df.to_parquet(PROCESSED / "field_soil.parquet", index=False)

    checks = [sanity_range(df["clay_pct_0_30"], 1, 80, "clay % (0-30 cm)"),
              sanity_range(df["sand_pct_0_30"], 1, 98, "sand % (0-30 cm)"),
              sanity_range(df["om_pct_0_30"], 0.1, 15, "organic matter % (0-30 cm)"),
              sanity_range(df["ph_0_30"], 4, 10.5, "pH (0-30 cm)"),
              sanity_range(df["kwfact_surface"], 0.02, 0.69, "K factor (derived)")]
    ok = all(c["passed"] for c in checks)
    write_status(
        SOURCE, status="ok" if ok else "partial", title=TITLE, tier=TIER,
        fetched=f"{len(PROPS)} properties x {len(DEPTHS)} depths for the pilot box; combined to 0-30 cm",
        resolution="250 m global grid (model prediction)", date_range="SoilGrids 2.0 (2020 release, static)",
        credit="Poggio, L. et al. (2021). SoilGrids 2.0: producing soil information for the globe with "
               "quantified spatial uncertainty. SOIL 7: 217-240. ISRIC World Soil Information, CC BY 4.0.",
        access=f"WCS {WCS} (one small GeoTIFF per property and depth)",
        message=f"soil table for {len(df)} fields; textures: {', '.join(sorted(set(df['surface_texture'])))}; "
                f"sanity {'passed' if ok else 'CHECK'}",
        sanity={"checks": checks, "crs": "EPSG:4326"},
        outputs=["field_soil.parquet", "rasters/soil_*.tif"],
        notes="A global statistical model trained on soil profiles, far less detailed than a local survey: "
              "it cannot see one field's history. Salinity and sodicity are NOT mapped, although both matter "
              "in parts of Punjab and the Cauvery delta. A soil-health-card test is the real measurement.",
    )


if __name__ == "__main__":
    run_source(SOURCE, TITLE, TIER, main)
