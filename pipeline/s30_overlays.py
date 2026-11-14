"""Map overlays for the app (PNG images in Web Mercator + a manifest with their corners).

  ndvi_summer_<year>.png   peak-summer greenness (Landsat), one per year
  cdl_<year>.png           USDA crop map, grouped into a few classes
  low_cover.png            how many months a year (Apr-Oct) the ground had little green cover
  slope.png                slope from SRTM (smoothed)

Colours: sequential layers use the viridis ramp (readable with colour-vision deficiency
and in greyscale); the crop classes use the Okabe-Ito colour-blind-safe palette.
"""
from __future__ import annotations

import json

import numpy as np
import rasterio
from PIL import Image
from pyproj import Transformer
from rasterio.transform import from_bounds
from rasterio.warp import Resampling, reproject

from .common import FIELD_EO_END, FIELD_EO_START, OVERLAYS, PILOT, PROCESSED, run_source, write_status

SOURCE, TITLE, TIER = "overlays", "Map overlays (PNG)", "MUST"
VIRIDIS = np.array([[68, 1, 84], [72, 40, 120], [62, 74, 137], [49, 104, 142], [38, 130, 142],
                    [31, 158, 137], [53, 183, 121], [109, 205, 89], [180, 222, 44], [253, 231, 37]], dtype="float64")
# Okabe-Ito palette
CDL_GROUPS = {
    "alfalfa": {"label": "Alfalfa", "color": [0, 158, 115], "codes": [36]},
    "hay": {"label": "Other hay / pasture", "color": [240, 228, 66], "codes": [37, 176, 59]},
    "grain": {"label": "Small grains", "color": [230, 159, 0], "codes": [21, 22, 23, 24, 25, 27, 28, 205]},
    "other_crop": {"label": "Other crops", "color": [204, 121, 167],
                   "codes": [1, 4, 5, 6, 12, 31, 33, 41, 42, 43, 44, 49, 53, 224]},
    "idle": {"label": "Fallow / idle", "color": [213, 94, 0], "codes": [61]},
    "noncrop": {"label": "Shrubland and other non-crop", "color": [187, 187, 187],
                "codes": [63, 64, 65, 131, 141, 142, 143, 152, 190, 195, 87, 111, 83]},
    "developed": {"label": "Developed", "color": [86, 180, 233], "codes": [82, 121, 122, 123, 124]},
}


def ramp(values: np.ndarray, vmin: float, vmax: float) -> np.ndarray:
    """Map values to RGBA with the viridis ramp; NaN becomes transparent."""
    t = np.clip((values - vmin) / (vmax - vmin), 0, 1)
    idx = t * (len(VIRIDIS) - 1)
    lo = np.floor(np.nan_to_num(idx)).astype(int).clip(0, len(VIRIDIS) - 2)
    frac = (np.nan_to_num(idx) - lo)[..., None]
    rgb = VIRIDIS[lo] * (1 - frac) + VIRIDIS[lo + 1] * frac
    alpha = np.where(np.isfinite(values), 255, 0)
    return np.dstack([rgb, alpha]).astype("uint8")


def mercator_grid(px: float = 25.0):
    w, s, e, n = PILOT["bbox"]
    tr = Transformer.from_crs(4326, 3857, always_xy=True)
    x0, y0 = tr.transform(w, s)
    x1, y1 = tr.transform(e, n)
    width, height = int(round((x1 - x0) / px)), int(round((y1 - y0) / px))
    return from_bounds(x0, y0, x1, y1, width, height), (height, width)


def to_mercator(arr: np.ndarray, src_transform, src_crs, resampling=Resampling.bilinear) -> np.ndarray:
    dst_tr, shape = mercator_grid()
    out = np.full(shape, np.nan, dtype="float32")
    reproject(arr.astype("float32"), out, src_transform=src_transform, src_crs=src_crs,
              dst_transform=dst_tr, dst_crs="EPSG:3857", resampling=resampling,
              src_nodata=np.nan, dst_nodata=np.nan)
    return out


def save(name: str, rgba: np.ndarray) -> str:
    OVERLAYS.mkdir(parents=True, exist_ok=True)
    Image.fromarray(rgba, "RGBA").save(OVERLAYS / name, optimize=True)
    return name


def main() -> None:
    w, s, e, n = PILOT["bbox"]
    corners = [[w, n], [e, n], [e, s], [w, s]]
    layers = []

    # --- Landsat peak-summer NDVI and low-cover months -------------------
    low_sum, low_n = None, 0
    for year in range(FIELD_EO_START, FIELD_EO_END + 1):
        path = PROCESSED / "rasters" / f"ndvi_monthly_{year}.tif"
        if not path.exists():
            continue
        with rasterio.open(path) as src:
            stack = src.read().astype("float32")
            stack[stack == src.nodata] = np.nan
            stack /= 10000.0
            tr, crs = src.transform, src.crs
        import warnings
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", category=RuntimeWarning)
            peak = np.nanmax(stack[5:8], axis=0)                 # June-August
            season = stack[3:10]                                  # April-October
            low = np.nansum(season < 0.25, axis=0).astype("float32")
            valid = np.isfinite(season).sum(axis=0)
        low = np.where(valid >= 5, low * 7.0 / np.maximum(valid, 1), np.nan)
        low_sum = low if low_sum is None else np.nansum(np.stack([low_sum, low]), axis=0)
        low_n += 1
        name = save(f"ndvi_summer_{year}.png", ramp(to_mercator(peak, tr, crs), 0.0, 0.9))
        layers.append({"id": f"ndvi_{year}", "group": "ndvi", "year": year, "file": name,
                       "label": f"Summer greenness {year}"})
    if low_sum is not None and low_n:
        name = save("low_cover.png", ramp(to_mercator(low_sum / low_n, tr, crs), 0.0, 7.0))
        layers.append({"id": "low_cover", "group": "low_cover", "file": name,
                       "label": "Months with little green cover (Apr-Oct)"})

    # --- crop map ----------------------------------------------------------
    lut = np.zeros((256, 4), dtype="uint8")
    for g in CDL_GROUPS.values():
        for code in g["codes"]:
            lut[code] = [*g["color"], 255]
    for year in range(FIELD_EO_START, FIELD_EO_END + 1):
        path = PROCESSED / "rasters" / f"cdl_{year}.tif"
        if not path.exists():
            continue
        with rasterio.open(path) as src:
            data = src.read(1)
            merc = to_mercator(data, src.transform, src.crs, Resampling.nearest)
        codes = np.nan_to_num(merc, nan=0).astype("uint8")
        name = save(f"cdl_{year}.png", lut[codes])
        layers.append({"id": f"cdl_{year}", "group": "cdl", "year": year, "file": name,
                       "label": f"Crop map {year}"})

    # --- slope ---------------------------------------------------------------
    sp = PROCESSED / "rasters" / "slope_pct.tif"
    if sp.exists():
        with rasterio.open(sp) as src:
            name = save("slope.png", ramp(to_mercator(src.read(1), src.transform, src.crs), 0.0, 6.0))
        layers.append({"id": "slope", "group": "slope", "file": name, "label": "Slope"})

    manifest = {
        "corners": corners, "layers": layers,
        "legends": {
            "ndvi": {"type": "ramp", "title": "Peak summer greenness (NDVI)", "min": "0 bare", "max": "0.9 dense",
                     "colors": VIRIDIS.astype(int).tolist(), "source": "Landsat 8/9 (USGS/NASA), 30 m"},
            "low_cover": {"type": "ramp", "title": "Months with little green cover, April-October",
                          "min": "0", "max": "7", "colors": VIRIDIS.astype(int).tolist(),
                          "source": "Landsat 8/9 monthly medians, NDVI below 0.25"},
            "slope": {"type": "ramp", "title": "Slope (%)", "min": "0", "max": "6+",
                      "colors": VIRIDIS.astype(int).tolist(), "source": "SRTM (NASA), smoothed over ~150 m"},
            "cdl": {"type": "classes", "title": "Crop map",
                    "classes": [{"label": g["label"], "color": g["color"]} for g in CDL_GROUPS.values()],
                    "source": "USDA NASS Cropland Data Layer"},
        },
    }
    (OVERLAYS / "manifest.json").write_text(json.dumps(manifest, indent=1), encoding="utf-8")
    write_status(SOURCE, status="ok" if layers else "partial", title=TITLE, tier=TIER,
                 fetched=f"{len(layers)} overlay images", resolution="25 m Web Mercator",
                 credit="Derived by this project from Landsat, CDL and SRTM.",
                 access="pipeline/s30_overlays.py", message=f"{len(layers)} overlays written",
                 sanity={"passed": bool(layers)}, outputs=["overlays/*.png", "overlays/manifest.json"])


if __name__ == "__main__":
    run_source(SOURCE, TITLE, TIER, main)
