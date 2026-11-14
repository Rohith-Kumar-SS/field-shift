"""USDA NASS Cropland Data Layer (MUST tier). No key needed.

Primary route: USDA CroplandCROS image service (the successor to CropScape).
Fallback: the CropScape GetCDLFile web service.

Downloads one small clip per year for the pilot box, then computes the area share of
each crop class inside every field. Output: data/processed/field_cdl.parquet
"""
from __future__ import annotations

import json
import re
from pathlib import Path

import pandas as pd
import rasterio
import requests
from pyproj import Transformer

from .common import (CDL_END, CDL_START, PILOT, PROCESSED, RAW, SourceError, load_fields,
                     run_source, sanity_range, write_status)
from .zonal import coverage_weights, weighted_fractions

SOURCE, TITLE, TIER = "usda_cdl", "USDA NASS Cropland Data Layer (CDL)", "MUST"
CROS = "https://pdi.scinet.usda.gov/image/rest/services/CDL_WM/ImageServer"
SERVICE = "https://nassgeodata.gmu.edu/axis2/services/CDLService/GetCDLFile"

CDL_NAMES = {
    0: "Background", 1: "Corn", 2: "Cotton", 3: "Rice", 4: "Sorghum", 5: "Soybeans", 6: "Sunflower",
    10: "Peanuts", 11: "Tobacco", 12: "Sweet Corn", 13: "Pop or Orn Corn", 14: "Mint", 21: "Barley",
    22: "Durum Wheat", 23: "Spring Wheat", 24: "Winter Wheat", 25: "Other Small Grains",
    26: "Dbl Crop WinWht/Soybeans", 27: "Rye", 28: "Oats", 29: "Millet", 30: "Speltz", 31: "Canola",
    32: "Flaxseed", 33: "Safflower", 34: "Rape Seed", 35: "Mustard", 36: "Alfalfa",
    37: "Other Hay/Non Alfalfa", 38: "Camelina", 39: "Buckwheat", 41: "Sugarbeets", 42: "Dry Beans",
    43: "Potatoes", 44: "Other Crops", 45: "Sugarcane", 46: "Sweet Potatoes",
    47: "Misc Vegs & Fruits", 48: "Watermelons", 49: "Onions", 50: "Cucumbers", 51: "Chick Peas",
    52: "Lentils", 53: "Peas", 54: "Tomatoes", 55: "Caneberries", 56: "Hops", 57: "Herbs",
    58: "Clover/Wildflowers", 59: "Sod/Grass Seed", 60: "Switchgrass", 61: "Fallow/Idle Cropland",
    63: "Forest", 64: "Shrubland", 65: "Barren", 66: "Cherries", 67: "Peaches", 68: "Apples",
    69: "Grapes", 70: "Christmas Trees", 71: "Other Tree Crops", 72: "Citrus", 74: "Pecans",
    75: "Almonds", 76: "Walnuts", 77: "Pears", 81: "Clouds/No Data", 82: "Developed", 83: "Water",
    87: "Wetlands", 88: "Nonag/Undefined", 92: "Aquaculture", 111: "Open Water",
    112: "Perennial Ice/Snow", 121: "Developed/Open Space", 122: "Developed/Low Intensity",
    123: "Developed/Med Intensity", 124: "Developed/High Intensity", 131: "Barren",
    141: "Deciduous Forest", 142: "Evergreen Forest", 143: "Mixed Forest", 152: "Shrubland",
    176: "Grassland/Pasture", 190: "Woody Wetlands", 195: "Herbaceous Wetlands", 204: "Pistachios",
    205: "Triticale", 206: "Carrots", 207: "Asparagus", 208: "Garlic", 209: "Cantaloupes",
    219: "Greens", 221: "Strawberries", 222: "Squash", 224: "Vetch", 225: "Dbl Crop WinWht/Corn",
    226: "Dbl Crop Oats/Corn", 227: "Lettuce", 228: "Dbl Crop Triticale/Corn", 229: "Pumpkins",
    236: "Dbl Crop WinWht/Sorghum", 237: "Dbl Crop Barley/Corn", 243: "Cabbage", 246: "Radishes",
    247: "Turnips", 254: "Dbl Crop Barley/Soybeans",
}


def albers_bbox(bbox) -> tuple[float, float, float, float]:
    """Pilot box in EPSG:5070 (CONUS Albers), the CRS CropScape expects."""
    w, s, e, n = bbox
    tr = Transformer.from_crs(4326, 5070, always_xy=True)
    xs, ys = tr.transform([w, e, w, e], [s, s, n, n])
    return min(xs), min(ys), max(xs), max(ys)


def mercator_bbox(bbox) -> tuple[float, float, float, float]:
    w, s, e, n = bbox
    tr = Transformer.from_crs(4326, 3857, always_xy=True)
    x0, y0 = tr.transform(w, s)
    x1, y1 = tr.transform(e, n)
    return x0, y0, x1, y1


def cros_catalog() -> dict[int, dict]:
    """Year -> {objectid, native pixel size} from the CroplandCROS mosaic catalogue."""
    r = requests.get(CROS + "/query", params={"where": "1=1", "outFields": "OBJECTID,Name,Year,LowPS",
                                              "returnGeometry": "false", "f": "json"}, timeout=120)
    r.raise_for_status()
    out: dict[int, dict] = {}
    for f in r.json().get("features", []):
        a = f["attributes"]
        year, ps = int(a["Year"]), float(a["LowPS"])
        if year not in out or ps < out[year]["native_m"]:
            out[year] = {"objectid": a["OBJECTID"], "native_m": ps, "name": a["Name"]}
    return out


def download_year_cros(year: int, entry: dict) -> Path:
    """Clip one CDL year from USDA CroplandCROS (ArcGIS ImageServer), nearest-neighbour."""
    out = RAW / "cdl" / f"CDL_{year}_{PILOT['id']}_cros.tif"
    out.parent.mkdir(parents=True, exist_ok=True)
    if out.exists() and out.stat().st_size > 1000:
        return out
    x0, y0, x1, y1 = mercator_bbox(PILOT["bbox"])
    px = 30.0  # Web-Mercator metres (~23 m on the ground at 39.7 N): never coarser than the 30 m source
    width, height = int(round((x1 - x0) / px)), int(round((y1 - y0) / px))
    params = {
        "bbox": f"{x0},{y0},{x1},{y1}", "bboxSR": 3857, "imageSR": 3857, "size": f"{width},{height}",
        "format": "tiff", "pixelType": "U8", "interpolation": "RSP_NearestNeighbor",
        "mosaicRule": json.dumps({"mosaicMethod": "esriMosaicLockRaster",
                                  "lockRasterIds": [entry["objectid"]]}),
        "f": "image",
    }
    r = requests.get(CROS + "/exportImage", params=params, timeout=300)
    if r.status_code != 200 or "tiff" not in r.headers.get("content-type", ""):
        raise SourceError(f"CroplandCROS export failed for {year}: HTTP {r.status_code} {r.text[:120]}")
    out.write_bytes(r.content)
    return out


def download_year_cropscape(year: int) -> "Path | None":
    """Fallback: the older CropScape clip service (native EPSG:5070 grid)."""
    out = RAW / "cdl" / f"CDL_{year}_{PILOT['id']}_cropscape.tif"
    out.parent.mkdir(parents=True, exist_ok=True)
    if out.exists() and out.stat().st_size > 1000:
        return out
    ab = albers_bbox(PILOT["bbox"])
    r = requests.get(SERVICE, params={"year": year, "bbox": ",".join(f"{v:.0f}" for v in ab)}, timeout=90)
    if r.status_code != 200:
        raise SourceError(f"CropScape HTTP {r.status_code} for {year}")
    m = re.search(r"<returnURL>(.*?)</returnURL>", r.text)
    if not m:
        return None
    tif = requests.get(m.group(1), timeout=300)
    tif.raise_for_status()
    out.write_bytes(tif.content)
    return out


def download_all() -> tuple[dict[int, Path], list[str], dict[int, float], str]:
    """Fetch every year. Returns (year -> file, missing notes, native pixel size, route used)."""
    paths: dict[int, Path] = {}
    missing: list[str] = []
    native: dict[int, float] = {}
    route = "USDA CroplandCROS image service"
    try:
        catalog = cros_catalog()
    except Exception as exc:  # noqa: BLE001
        catalog = {}
        route = f"CropScape (CroplandCROS catalogue unavailable: {type(exc).__name__})"
    for year in range(CDL_START, CDL_END + 1):
        try:
            if year in catalog:
                paths[year] = download_year_cros(year, catalog[year])
                native[year] = catalog[year]["native_m"]
            else:
                p = download_year_cropscape(year)
                if p is None:
                    missing.append(f"{year} (not published)")
                else:
                    paths[year] = p
                    native[year] = 30.0
        except (requests.RequestException, SourceError) as exc:
            missing.append(f"{year} ({type(exc).__name__})")
    return paths, missing, native, route


def field_fractions(fields, paths: dict[int, Path]) -> pd.DataFrame:
    """Area share of each CDL class inside each field, for every year."""
    rows = []
    for year, path in sorted(paths.items()):
        with rasterio.open(path) as src:
            data = src.read(1)
            fproj = fields.to_crs(src.crs)
            for _, f in fproj.iterrows():
                w = coverage_weights(f.geometry, src.transform, data.shape, supersample=3)
                fr = weighted_fractions(data, w)
                if not fr:
                    continue
                top = sorted(fr.items(), key=lambda kv: -kv[1])
                code, share = top[0]
                rows.append({
                    "field_id": f["field_id"], "year": year, "cdl_code": int(code),
                    "cdl_name": CDL_NAMES.get(int(code), f"Class {code}"),
                    "share": round(float(share), 3),
                    "top_classes": json.dumps([
                        {"code": int(c), "name": CDL_NAMES.get(int(c), f"Class {c}"),
                         "share": round(float(s), 3)} for c, s in top[:4]]),
                })
    return pd.DataFrame(rows)


def main() -> None:
    fields = load_fields()
    paths, years_missing, native, route = download_all()
    if not paths:
        raise SourceError(
            "No CDL rasters could be fetched for the pilot box",
            action="USDA CroplandCROS (pdi.scinet.usda.gov) and CropScape (nassgeodata.gmu.edu) were "
                   "both unreachable; re-run `python -m pipeline.s05_cdl` later. Files already "
                   "downloaded are cached, so only missing years are retried.")
    df = field_fractions(fields, paths)
    df.to_parquet(PROCESSED / "field_cdl.parquet", index=False)
    years_ok = sorted(paths)
    with rasterio.open(paths[years_ok[-1]]) as src:
        crs_txt = str(src.crs)

    checks = [sanity_range(df["share"], 0.2, 1.0, "dominant-class share of field"),
              sanity_range(df["cdl_code"], 1, 254, "CDL class code")]
    complete = len(years_ok) == (CDL_END - CDL_START + 1)
    ok = all(c["passed"] for c in checks)
    fine = ", ".join(str(y) for y, r in sorted(native.items()) if r < 30)
    write_status(
        SOURCE, status="ok" if (ok and complete) else "partial", title=TITLE, tier=TIER,
        fetched=f"{len(years_ok)} annual clips ({min(years_ok)}-{max(years_ok)}) for the pilot box; "
                f"{len(df)} field-year crop labels",
        resolution=f"Source 30 m ({'10 m for ' + fine if fine else 'all years'}); clipped with "
                   "nearest-neighbour sampling to a 30 m Web-Mercator grid; annual",
        date_range=f"{min(years_ok)} to {max(years_ok)}",
        credit="USDA National Agricultural Statistics Service Cropland Data Layer. Published "
               "crop-specific data layer, USDA-NASS, Washington, DC. Public domain.",
        access=f"{route}: {CROS}/exportImage (CropScape GetCDLFile kept as a fallback; it timed "
               "out when this pipeline was built)",
        message=f"{len(years_ok)} years fetched"
                + (f"; missing: {', '.join(years_missing)}" if years_missing else "")
                + f"; sanity {'passed' if ok else 'CHECK'}",
        sanity={"checks": checks, "crs": f"{crs_txt} (read from file)",
                "mean_dominant_share": round(float(df["share"].mean()), 3)},
        outputs=["field_cdl.parquet"],
        notes="A satellite-derived classification, not a ground record: individual field-years "
              "can be mislabelled (alfalfa vs other hay is a common confusion). The app shows the "
              "share of the field that carried the label and asks the farmer to correct it.",
    )


if __name__ == "__main__":
    run_source(SOURCE, TITLE, TIER, main)
