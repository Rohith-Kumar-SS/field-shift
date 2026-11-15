"""Write everything the browser needs as static files: frontend/public/data/<region>/.

The app is a static site (GitHub Pages): there is no server to ask. So this step ships,
per region,

  region.json            the region, its sources and their status, map layers, long-term water
  kb.json                the knowledge base (crops, rotations, criteria, references)
  fields.geojson         field outlines with their headline indicators
  fields/<id>.json       context (what the scoring needs) + evidence (chart data) per field
  weather/<id>.bin       30 years of locally corrected daily weather per field (engine/static_data.py)
  overlays/*.webp        map layers
  atlas.json + .bin      a ~140 m grid of soil, terrain, greenness and crop-map values, so a field
                         the farmer draws can be described in the browser from real data
  context / wells / smap_cells / soil_units .geojson   extra map layers where they exist

and data/regions.json listing the regions. Nothing here is new data: it is a repackaging of
data/processed, so the provenance in DATA_LOG.md applies unchanged.
"""
from __future__ import annotations

import json
import shutil
from datetime import datetime, timezone

import geopandas as gpd
import numpy as np
import pandas as pd
import rasterio
from PIL import Image
from rasterio.features import rasterize
from rasterio.transform import from_origin
from rasterio.warp import Resampling, reproject

from engine import static_data
from engine.climate import base_frame, field_precip
from engine.context import clean
from engine.knowledge import load_kb

from .common import FIELD_EO_END, FIELD_EO_START, OVERLAYS, PILOT, PROCESSED, ROOT, run_source, write_status
from .regions import REGIONS
from .s20_indicators import field_inputs, load_all

SOURCE, TITLE, TIER = "export", "Static files for the web app", "MUST"
OUT_ROOT = ROOT / "frontend" / "public" / "data"
ATLAS_STEP = 0.00125            # degrees: about 140 m north-south
SOIL_LAYERS = [("om_pct_0_30", 100), ("clay_pct_0_30", 10), ("sand_pct_0_30", 10), ("silt_pct_0_30", 10),
               ("ph_0_30", 100), ("ec_dsm_0_30", 100), ("sar_0_30", 100), ("wind_erodibility_index", 1),
               ("kwfact_surface", 1000)]


def round_coords(obj, nd: int = 6):
    if isinstance(obj, float):
        return round(obj, nd)
    if isinstance(obj, list):
        return [round_coords(v, nd) for v in obj]
    return obj


def geojson_of(gdf: gpd.GeoDataFrame, nd: int = 6) -> dict:
    fc = json.loads(gdf.to_json())
    for f in fc["features"]:
        f["geometry"]["coordinates"] = round_coords(f["geometry"]["coordinates"], nd)
        f.pop("id", None)
    return fc


def dump(path, obj, indent=None) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(clean(obj), indent=indent, separators=None if indent else (",", ":")),
                    encoding="utf-8")


# ---------------------------------------------------------------------------
# Atlas: gridded values for fields drawn in the browser
# ---------------------------------------------------------------------------
class Atlas:
    def __init__(self) -> None:
        w, s, e, n = PILOT["bbox"]
        self.west, self.north = w, n
        self.nx, self.ny = int(round((e - w) / ATLAS_STEP)), int(round((n - s) / ATLAS_STEP))
        self.transform = from_origin(w, n, ATLAS_STEP, ATLAS_STEP)
        self.layers: list[dict] = []
        self.chunks: list[bytes] = []
        self.offset = 0

    def warp(self, arr: np.ndarray, tr, crs, how=Resampling.average) -> np.ndarray:
        out = np.full((self.ny, self.nx), np.nan, dtype="float32")
        reproject(arr.astype("float32"), out, src_transform=tr, src_crs=crs, dst_transform=self.transform,
                  dst_crs="EPSG:4326", resampling=how, src_nodata=np.nan, dst_nodata=np.nan)
        return out

    def warp_classes(self, arr: np.ndarray, tr, crs) -> np.ndarray:
        out = np.full((self.ny, self.nx), 255, dtype="uint8")
        reproject(arr.astype("uint8"), out, src_transform=tr, src_crs=crs, dst_transform=self.transform,
                  dst_crs="EPSG:4326", resampling=Resampling.mode, dst_nodata=255)
        return out

    def _add(self, lid: str, kind: str, data: bytes, **extra) -> None:
        self.layers.append({"id": lid, "type": kind, "offset": self.offset, **extra})
        self.chunks.append(data)
        self.offset += len(data)

    def add_i16(self, lid: str, arr: np.ndarray, scale: float) -> None:
        a = np.rint(arr.astype("float64") * scale)
        a = np.where(np.isfinite(a), np.clip(a, -32767, 32767), -32768).astype("<i2")
        if self.offset % 2:                         # keep 16-bit layers on even offsets
            self.chunks.append(b"\x00")
            self.offset += 1
        self._add(lid, "i16", a.tobytes(), scale=scale, nodata=-32768)

    def add_u8(self, lid: str, stack: list[np.ndarray], scale: float | None = None, **extra) -> None:
        """One or more 8-bit layers stored back to back (`count` of them)."""
        parts = []
        for arr in stack:
            if scale is None:
                parts.append(arr.astype("uint8").tobytes())
            else:
                a = np.rint(arr.astype("float64") * scale)
                parts.append(np.where(np.isfinite(a), np.clip(a, 0, 254), 255).astype("uint8").tobytes())
        self._add(lid, "u8", b"".join(parts), count=len(stack), nodata=255,
                  **({"scale": scale} if scale else {}), **extra)

    def meta(self) -> dict:
        return {"west": self.west, "north": self.north, "step": ATLAS_STEP, "nx": self.nx, "ny": self.ny,
                "layers": self.layers, "bytes": self.offset}


def atlas_soil_survey(at: Atlas) -> tuple[list[dict], str] | None:
    """USA: soil-survey map units rasterised onto the atlas grid."""
    mu_path, props_path = PROCESSED / "soil_mapunits.geojson", PROCESSED / "soil_mapunit_props.parquet"
    if not (mu_path.exists() and props_path.exists()):
        return None
    mu = gpd.read_file(mu_path)[["mukey", "geometry"]]
    props = pd.read_parquet(props_path).set_index("mukey")
    props.index = props.index.astype(str)
    keys = [k for k in mu["mukey"].astype(str).unique() if k in props.index][:254]
    idx = {k: i for i, k in enumerate(keys)}
    shapes = [(g, idx[str(k)]) for g, k in zip(mu.geometry, mu["mukey"]) if str(k) in idx]
    grid = rasterize(shapes, out_shape=(at.ny, at.nx), transform=at.transform, fill=255, dtype="uint8")
    for col, scale in SOIL_LAYERS:
        if col not in props.columns:
            continue
        lut = np.full(256, np.nan)
        lut[:len(keys)] = [props.loc[k, col] for k in keys]
        at.add_i16(col, lut[grid], scale)
    at.add_u8("soil_class", [grid])
    text = lambda v: None if pd.isna(v) else str(v)     # noqa: E731
    classes = [{"muname": text(props.loc[k, "muname"]), "surface_texture": text(props.loc[k, "surface_texture"]),
                "wind_erodibility_group": text(props.loc[k, "wind_erodibility_group"]),
                "drainage_class": text(props.loc[k, "drainage_class"]),
                "hydrologic_group": text(props.loc[k, "hydrologic_group"])} for k in keys]
    return classes, "ssurgo"


def atlas_soil_grids(at: Atlas) -> tuple[list[dict], str] | None:
    """Elsewhere: SoilGrids rasters; texture class, K factor and wind erodibility derived per cell."""
    from .s04_soilgrids import WEG, epic_k, texture_class

    rdir = PROCESSED / "rasters"
    cols = ["clay_pct_0_30", "sand_pct_0_30", "silt_pct_0_30", "soc_pct_0_30", "ph_0_30"]
    if not all((rdir / f"soil_{c}.tif").exists() for c in cols):
        return None
    g = {}
    for c in cols:
        with rasterio.open(rdir / f"soil_{c}.tif") as src:
            g[c] = at.warp(src.read(1), src.transform, src.crs, Resampling.bilinear)
    g["om_pct_0_30"] = g["soc_pct_0_30"] * 1.724
    names: list[str] = []
    cls = np.full((at.ny, at.nx), 255, dtype="uint8")
    wei = np.full((at.ny, at.nx), np.nan, dtype="float32")
    kw = np.full((at.ny, at.nx), np.nan, dtype="float32")
    for r in range(at.ny):
        for c in range(at.nx):
            sand, silt, clay, oc = (float(g[k][r, c]) for k in ("sand_pct_0_30", "silt_pct_0_30", "clay_pct_0_30", "soc_pct_0_30"))
            if not all(map(np.isfinite, (sand, silt, clay, oc))):
                continue
            tex = texture_class(sand, silt, clay)
            if tex not in names:
                names.append(tex)
            cls[r, c] = names.index(tex)
            wei[r, c] = WEG.get(tex, ("5", 56))[1]
            kw[r, c] = epic_k(sand, silt, clay, oc)
    g["wind_erodibility_index"], g["kwfact_surface"] = wei, kw
    for col, scale in SOIL_LAYERS:
        if col in g:
            at.add_i16(col, g[col], scale)
    at.add_u8("soil_class", [cls])
    classes = [{"muname": "SoilGrids 250 m cell (global model)", "surface_texture": t.capitalize(),
                "wind_erodibility_group": WEG.get(t, ("5", 56))[0], "drainage_class": None,
                "hydrologic_group": None} for t in names]
    return classes, "soilgrids"


def build_atlas(rdir) -> dict | None:
    at = Atlas()
    src_dir = PROCESSED / "rasters"
    for name, scale in (("elevation_m", 10), ("slope_pct", 100)):
        p = src_dir / f"{name}.tif"
        if not p.exists():
            return None
        with rasterio.open(p) as src:
            at.add_i16(name, at.warp(src.read(1), src.transform, src.crs), scale)

    soil = atlas_soil_survey(at) or atlas_soil_grids(at)
    if soil is None:
        return None
    classes, soil_source = soil

    years, stack = [], []
    for year in range(FIELD_EO_START, FIELD_EO_END + 1):
        p = src_dir / f"ndvi_monthly_{year}.tif"
        if not p.exists():
            continue
        with rasterio.open(p) as src:
            data = src.read().astype("float32")
            data[data == src.nodata] = np.nan
            for b in range(12):
                stack.append(np.clip(at.warp(data[b] / 10000.0, src.transform, src.crs), 0.0, 1.0))
        years.append(year)
    if not years:
        return None
    at.add_u8("ndvi", stack, scale=250, years=years, per_year=12)

    cdl_years, cdl_stack, cdl_names = [], [], {}
    for p in sorted(src_dir.glob("cdl_*.tif")):
        with rasterio.open(p) as src:
            cdl_stack.append(at.warp_classes(src.read(1), src.transform, src.crs))
        cdl_years.append(int(p.stem.split("_")[-1]))
    if cdl_years:
        at.add_u8("cdl", cdl_stack, years=cdl_years, per_year=1)
        fc = pd.read_parquet(PROCESSED / "field_cdl.parquet")
        for _, r in fc.iterrows():
            cdl_names[int(r["cdl_code"])] = r["cdl_name"]
            for t in json.loads(r["top_classes"]) if isinstance(r.get("top_classes"), str) else []:
                cdl_names[int(t["code"])] = t["name"]
    cf = src_dir / "cropland_fraction.tif"
    if cf.exists():
        with rasterio.open(cf) as src:
            at.add_u8("cropland", [at.warp(src.read(1), src.transform, src.crs)], scale=250)

    (rdir / "atlas.bin").write_bytes(b"".join(at.chunks))
    meta = {**at.meta(), "soil_classes": classes, "soil_source": soil_source, "cdl_names": cdl_names,
            "file": "atlas.bin"}
    dump(rdir / "atlas.json", meta)
    return {"file": "atlas.json", "bytes": at.offset, "step_m": round(ATLAS_STEP * 111320)}


# ---------------------------------------------------------------------------
def export_overlays(rdir) -> dict:
    src = OVERLAYS / "manifest.json"
    if not src.exists():
        return {"corners": [], "layers": [], "legends": {}, "groups": []}
    manifest = json.loads(src.read_text(encoding="utf-8"))
    odir = rdir / "overlays"
    if odir.exists():
        shutil.rmtree(odir)
    odir.mkdir(parents=True)
    for layer in manifest["layers"]:
        img = Image.open(OVERLAYS / layer["file"]).convert("RGBA")
        name = layer["file"].rsplit(".", 1)[0] + ".webp"
        classes = manifest["legends"].get(layer["group"], {}).get("type") == "classes"
        if classes:
            img.save(odir / name, "WEBP", lossless=True, method=6)
        else:
            img.save(odir / name, "WEBP", quality=82, method=6, alpha_quality=100, exact=False)
        layer["file"] = name
    return manifest


def region_stats(summary: list[dict], evidence: dict[str, dict], contexts: dict[str, dict]) -> dict:
    mean = lambda vals: round(float(np.mean(vals))) if vals else None     # noqa: E731
    s = [e["climate"]["summary"] for e in evidence.values()]
    gw = next(iter(contexts.values())).get("groundwater") or {}
    normals = [e["climate"]["normals"] for e in evidence.values()]
    by_month = lambda key: [round(float(np.mean([n[key][str(m)] for n in normals])), 1) for m in range(1, 13)]   # noqa: E731
    return {"precip_month": by_month("precip_month"), "et0_month": by_month("et0_month"),
            "precip_annual": mean([x["precip_annual"] for x in s]), "et0_annual": mean([x["et0_annual"] for x in s]),
            "hot_days": mean([x["hot_days"] for x in s]), "hot_day_c": s[0]["hot_day_c"],
            "irrigation_need_mm": mean([x["irrigation_need_mm"] for x in summary if x.get("irrigation_need_mm")]),
            "groundwater": gw}


def main() -> None:
    rid = PILOT["id"]
    rdir = OUT_ROOT / rid
    for sub in ("fields", "weather"):
        if (rdir / sub).exists():
            shutil.rmtree(rdir / sub)
        (rdir / sub).mkdir(parents=True)
    kb = load_kb(PILOT["kb"])
    dump(rdir / "kb.json", kb)
    shutil.copyfile(ROOT / "knowledge" / "glossary.json", OUT_ROOT / "glossary.json")

    d = load_all()
    summary = {s["field_id"]: s for s in json.loads((PROCESSED / "fields_summary.json").read_text(encoding="utf-8"))}
    fields = d["fields"]
    weather_meta, contexts, evidence = None, {}, {}
    for _, f in fields.iterrows():
        fid = f["field_id"]
        ctx = json.loads((PROCESSED / "field_context" / f"{fid}.json").read_text(encoding="utf-8"))
        ev = json.loads((PROCESSED / "field_evidence" / f"{fid}.json").read_text(encoding="utf-8"))
        inp = field_inputs(f, d)
        base = base_frame(inp["power_daily"], ctx["elevation_m"], inp["grid_elevation_m"],
                          precip=field_precip(inp["power_daily"], inp["imerg"], inp["bias"]), bias=inp["bias"])
        blob, weather_meta = static_data.encode(base)
        (rdir / "weather" / f"{fid}.bin").write_bytes(blob)
        dump(rdir / "fields" / f"{fid}.json", {"context": ctx, "evidence": ev})
        contexts[fid], evidence[fid] = ctx, ev

    fc = geojson_of(fields)
    for feat in fc["features"]:
        feat["properties"].update(summary.get(feat["properties"]["field_id"], {}))
    dump(rdir / "fields.geojson", fc)

    extras = {}
    for key, name, nd in (("context", "fields_context.geojson", 5), ("wells", "groundwater_wells.geojson", 5),
                          ("smap_cells", "smap_cells.geojson", 5), ("soil_units", "soil_mapunits.geojson", 5)):
        p = PROCESSED / name
        if p.exists():
            g = gpd.read_file(p)
            if len(g):
                dump(rdir / f"{key}.geojson", geojson_of(g, nd))
                extras[key] = f"{key}.geojson"

    overlays = export_overlays(rdir)
    atlas = build_atlas(rdir)
    valley = json.loads((PROCESSED / "valley.json").read_text(encoding="utf-8"))
    region = {k: v for k, v in PILOT.items() if k != "steps"}
    stats = region_stats(list(summary.values()), evidence, contexts)
    dump(rdir / "region.json", {
        "region": region, "stats": stats,
        "sources": [s for s in valley.get("sources", []) if s["source"] not in ("overlays", "export", "datalog")],
        "any_demo_data": bool(valley.get("any_demo_data")), "groundwater": valley.get("groundwater"),
        "overlays": overlays, "extras": extras, "atlas": atlas, "weather": weather_meta,
        "scenario": {"rain_pct": {"min": -40, "max": 40, "step": 5}, "temp_c": {"min": 0, "max": 4, "step": 0.5}},
        "generated": datetime.now(timezone.utc).strftime("%Y-%m-%d"),
    })

    # the list of regions the switcher shows (only regions that have been exported)
    listing = []
    for other, cfg in REGIONS.items():
        rp = OUT_ROOT / other / "region.json"
        if not rp.exists():
            continue
        info = json.loads(rp.read_text(encoding="utf-8"))
        n = len(json.loads((OUT_ROOT / other / "fields.geojson").read_text(encoding="utf-8"))["features"])
        listing.append({**{k: cfg[k] for k in ("id", "name", "short", "country", "tagline", "bbox", "centroid",
                                               "field_unit", "imperial", "landmark")},
                        "n_fields": n, "stats": info["stats"]})
    dump(OUT_ROOT / "regions.json", listing, indent=1)

    size = sum(p.stat().st_size for p in rdir.rglob("*") if p.is_file())
    write_status(SOURCE, status="ok", title=TITLE, tier=TIER,
                 fetched=f"{len(contexts)} fields, {len(overlays['layers'])} map layers"
                         + (", atlas for drawn fields" if atlas else ""),
                 resolution="as the sources", credit="Repackaged from data/processed by this project.",
                 access="pipeline/s40_export.py",
                 message=f"{len(contexts)} fields exported to frontend/public/data/{rid} ({size / 1e6:.1f} MB)",
                 sanity={"passed": True, "bytes": size}, outputs=[f"frontend/public/data/{rid}/"])


if __name__ == "__main__":
    run_source(SOURCE, TITLE, TIER, main)
