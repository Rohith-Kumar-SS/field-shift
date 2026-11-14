"""USDA NASS Cropland Data Layer via the CropScape web service (MUST tier). No key needed.

Downloads one small clip per year for the pilot box, then computes the area share of
each crop class inside every field. Output: data/processed/field_cdl.parquet
"""
from __future__ import annotations

import json
import re

import numpy as np
import pandas as pd
import rasterio
import requests
from pyproj import Transformer

from .common import (CDL_END, CDL_START, PILOT, PROCESSED, RAW, SourceError, load_fields,
                     run_source, sanity_range, write_status)
from .zonal import coverage_weights, weighted_fractions

SOURCE, TITLE, TIER = "usda_cdl", "USDA NASS Cropland Data Layer (CDL)", "MUST"
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


def download_year(year: int, ab) -> "Path | None":
    out = RAW / "cdl" / f"CDL_{year}_{PILOT['id']}.tif"
    out.parent.mkdir(parents=True, exist_ok=True)
    if out.exists() and out.stat().st_size > 1000:
        return out
    params = {"year": year, "bbox": ",".join(f"{v:.0f}" for v in ab)}
    r = requests.get(SERVICE, params=params, timeout=180)
    if r.status_code != 200:
        raise SourceError(f"CropScape HTTP {r.status_code} for {year}: {r.text[:160]}")
    m = re.search(r"<returnURL>(.*?)</returnURL>", r.text)
    if not m:
        return None  # year not published for this area
    tif = requests.get(m.group(1), timeout=300)
    tif.raise_for_status()
    out.write_bytes(tif.content)
    return out


def main() -> None:
    fields = load_fields()
    ab = albers_bbox(PILOT["bbox"])
    rows, years_ok, years_missing, res = [], [], [], {}
    for year in range(CDL_START, CDL_END + 1):
        try:
            path = download_year(year, ab)
        except (requests.RequestException, SourceError) as exc:
            years_missing.append(f"{year} ({type(exc).__name__})")
            continue
        if path is None:
            years_missing.append(f"{year} (not published)")
            continue
        with rasterio.open(path) as src:
            data = src.read(1)
            res[year] = round(abs(src.transform.a), 1)
            f5070 = fields.to_crs(src.crs)
            for _, f in f5070.iterrows():
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
        years_ok.append(year)
    if not rows:
        raise SourceError(
            "CropScape returned no CDL rasters for the pilot box",
            action="CropScape (nassgeodata.gmu.edu) may be down; re-run `python -m pipeline.s05_cdl` "
                   "later. Raw files are cached, so only missing years are retried.")
    df = pd.DataFrame(rows)
    df.to_parquet(PROCESSED / "field_cdl.parquet", index=False)

    checks = [sanity_range(df["share"], 0.2, 1.0, "dominant-class share of field"),
              sanity_range(df["cdl_code"], 1, 254, "CDL class code")]
    complete = len(years_ok) == (CDL_END - CDL_START + 1)
    ok = all(c["passed"] for c in checks)
    write_status(
        SOURCE, status="ok" if (ok and complete) else "partial", title=TITLE, tier=TIER,
        fetched=f"{len(years_ok)} annual clips ({min(years_ok)}-{max(years_ok)}) for the pilot box; "
                f"{len(df)} field-year crop labels",
        resolution="30 m (10 m from 2024); annual. Pixel sizes read from the files: "
                   + ", ".join(f"{y}: {r} m" for y, r in sorted(res.items()) if y in (min(res), max(res))),
        date_range=f"{min(years_ok)} to {max(years_ok)}",
        credit="USDA National Agricultural Statistics Service Cropland Data Layer. Published "
               "crop-specific data layer, USDA-NASS, Washington, DC. Public domain.",
        access="CropScape web service https://nassgeodata.gmu.edu/axis2/services/CDLService/GetCDLFile",
        message=f"{len(years_ok)} years fetched"
                + (f"; missing: {', '.join(years_missing)}" if years_missing else "")
                + f"; sanity {'passed' if ok else 'CHECK'}",
        sanity={"checks": checks, "crs": "EPSG:5070 (read from file)",
                "mean_dominant_share": round(float(df["share"].mean()), 3)},
        outputs=["field_cdl.parquet"],
        notes="A satellite-derived classification, not a ground record: individual field-years "
              "can be mislabelled (alfalfa vs other hay is a common confusion). The app shows the "
              "share of the field that carried the label and asks the farmer to correct it.",
    )


if __name__ == "__main__":
    run_source(SOURCE, TITLE, TIER, main)
