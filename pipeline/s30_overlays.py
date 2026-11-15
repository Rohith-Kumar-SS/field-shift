"""Map overlays for the app (PNG images in Web Mercator + a manifest with their corners).

  <season>_<year>.png   peak greenness in the region's crop season(s) (Landsat), one per year
  cdl_<year>.png        USDA crop map, grouped into a few classes (USA only)
  landcover.png         ESA WorldCover land cover (regions without a crop map)
  low_cover.png         how many months a year the ground had little green cover
  slope.png             slope from SRTM (smoothed)

Which months make a "season" is set per region in pipeline/regions.py.

Colours: sequential layers use the viridis ramp (readable with colour-vision deficiency
and in greyscale); class maps use the Okabe-Ito colour-blind-safe palette.
"""
from __future__ import annotations

import json
import warnings

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
MONTH = ["", "Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]
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
WORLDCOVER = {
    "cropland": {"label": "Cropland", "color": [230, 159, 0], "codes": [40]},
    "trees": {"label": "Trees", "color": [0, 158, 115], "codes": [10, 95]},
    "grass": {"label": "Grass and shrub", "color": [240, 228, 66], "codes": [20, 30]},
    "built": {"label": "Built-up", "color": [204, 121, 167], "codes": [50]},
    "bare": {"label": "Bare or sparse", "color": [187, 187, 187], "codes": [60, 100]},
    "water": {"label": "Water and wetland", "color": [86, 180, 233], "codes": [80, 90]},
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


def class_layer(path, groups: dict, name: str) -> str:
    lut = np.zeros((256, 4), dtype="uint8")
    for g in groups.values():
        for code in g["codes"]:
            lut[code] = [*g["color"], 255]
    with rasterio.open(path) as src:
        merc = to_mercator(src.read(1), src.transform, src.crs, Resampling.nearest)
    return save(name, lut[np.nan_to_num(merc, nan=0).astype("uint8")])


def month_span(months: list[int]) -> str:
    return MONTH[months[0]] if len(months) == 1 else f"{MONTH[months[0]]}-{MONTH[months[-1]]}"


def main() -> None:
    w, s, e, n = PILOT["bbox"]
    corners = [[w, n], [e, n], [e, s], [w, s]]
    layers, legends = [], {}
    seasons = PILOT.get("greenness_layers") or [{"id": "ndvi", "title": "Summer greenness", "months": [6, 7, 8]}]
    cover_months = PILOT.get("cover_months") or [4, 5, 6, 7, 8, 9, 10]
    for old in OVERLAYS.glob("*.png"):              # layer names changed between versions
        old.unlink()

    # --- Landsat seasonal greenness and low-cover months ---------------------
    low_sum, low_n, tr, crs = None, 0, None, None
    for year in range(FIELD_EO_START, FIELD_EO_END + 1):
        path = PROCESSED / "rasters" / f"ndvi_monthly_{year}.tif"
        if not path.exists():
            continue
        with rasterio.open(path) as src:
            stack = src.read().astype("float32")
            stack[stack == src.nodata] = np.nan
            stack /= 10000.0
            tr, crs = src.transform, src.crs
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", category=RuntimeWarning)
            season = stack[[m - 1 for m in cover_months]]
            low = np.nansum(season < 0.25, axis=0).astype("float32")
            valid = np.isfinite(season).sum(axis=0)
            need = max(3, int(round(0.6 * len(cover_months))))
            low = np.where(valid >= need, low * len(cover_months) / np.maximum(valid, 1), np.nan)
            low_sum = low if low_sum is None else np.nansum(np.stack([low_sum, low]), axis=0)
            low_n += 1
            for sea in seasons:
                peak = np.nanmax(stack[[m - 1 for m in sea["months"]]], axis=0)
                if np.isfinite(peak).mean() < 0.3:          # a cloudy season: no honest picture to show
                    continue
                name = save(f"{sea['id']}_{year}.png", ramp(to_mercator(peak, tr, crs), 0.0, 0.9))
                layers.append({"id": f"{sea['id']}_{year}", "group": sea["id"], "year": year, "file": name,
                               "label": f"{sea['title']} {year}"})
    for sea in seasons:
        legends[sea["id"]] = {"type": "ramp", "title": f"{sea['title']}: peak NDVI", "short": sea["title"],
                              "min": "0 bare", "max": "0.9 dense", "colors": VIRIDIS.astype(int).tolist(),
                              "source": "Landsat 8/9 (USGS/NASA), 30 m"}
    if low_sum is not None and low_n:
        span = "all year" if len(cover_months) == 12 else month_span(cover_months)
        name = save("low_cover.png", ramp(to_mercator(low_sum / low_n, tr, crs), 0.0, float(min(len(cover_months), 7))))
        layers.append({"id": "low_cover", "group": "low_cover", "file": name,
                       "label": f"Months with little green cover ({span})"})
        legends["low_cover"] = {"type": "ramp", "title": f"Months a year with little green cover ({span})",
                                "short": "Bare-looking months", "min": "0", "max": f"{min(len(cover_months), 7)}+",
                                "colors": VIRIDIS.astype(int).tolist(),
                                "source": "Landsat 8/9 monthly medians, NDVI below 0.25"}

    # --- crop map (USA) or land cover (elsewhere) ----------------------------
    n_cdl = 0
    for year in range(FIELD_EO_START, FIELD_EO_END + 1):
        path = PROCESSED / "rasters" / f"cdl_{year}.tif"
        if not path.exists():
            continue
        name = class_layer(path, CDL_GROUPS, f"cdl_{year}.png")
        layers.append({"id": f"cdl_{year}", "group": "cdl", "year": year, "file": name, "label": f"Crop map {year}"})
        n_cdl += 1
    if n_cdl:
        legends["cdl"] = {"type": "classes", "title": "Crop map", "short": "Crop map",
                          "classes": [{"label": g["label"], "color": g["color"]} for g in CDL_GROUPS.values()],
                          "source": "USDA NASS Cropland Data Layer"}
    lc = PROCESSED / "rasters" / "landcover.tif"
    if lc.exists() and not n_cdl:
        name = class_layer(lc, WORLDCOVER, "landcover.png")
        layers.append({"id": "landcover", "group": "landcover", "file": name, "label": "Land cover"})
        legends["landcover"] = {"type": "classes", "title": "Land cover (2021)", "short": "Land cover",
                                "classes": [{"label": g["label"], "color": g["color"]} for g in WORLDCOVER.values()],
                                "source": "ESA WorldCover 10 m (2021). It maps cropland, not which crop."}

    # --- slope ---------------------------------------------------------------
    sp = PROCESSED / "rasters" / "slope_pct.tif"
    if sp.exists():
        with rasterio.open(sp) as src:
            slope = src.read(1)
            top = 6.0 if np.nanpercentile(slope, 98) > 2.0 else 2.0     # flat plains need a finer scale
            name = save("slope.png", ramp(to_mercator(slope, src.transform, src.crs), 0.0, top))
        layers.append({"id": "slope", "group": "slope", "file": name, "label": "Slope"})
        legends["slope"] = {"type": "ramp", "title": "Slope (%)", "short": "Slope", "min": "0", "max": f"{top:.0f}+",
                            "colors": VIRIDIS.astype(int).tolist(), "source": "SRTM (NASA), smoothed over ~150 m"}

    order = [s["id"] for s in seasons] + ["cdl", "landcover", "low_cover", "slope"]
    manifest = {"corners": corners, "layers": layers, "legends": legends,
                "groups": [g for g in order if g in legends]}
    (OVERLAYS / "manifest.json").write_text(json.dumps(manifest, indent=1), encoding="utf-8")
    write_status(SOURCE, status="ok" if layers else "partial", title=TITLE, tier=TIER,
                 fetched=f"{len(layers)} overlay images", resolution="25 m Web Mercator",
                 credit="Derived by this project from Landsat, the crop or land-cover map and SRTM.",
                 access="pipeline/s30_overlays.py", message=f"{len(layers)} overlays written",
                 sanity={"passed": bool(layers)}, outputs=["overlays/*.png", "overlays/manifest.json"])


if __name__ == "__main__":
    run_source(SOURCE, TITLE, TIER, main)
