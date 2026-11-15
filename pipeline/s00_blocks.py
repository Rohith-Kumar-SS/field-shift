"""Sample farm blocks for regions without field-boundary or crop-type maps (India).

Fields here average about one hectare, too small to outline reliably from 30 m imagery,
and no public map gives their boundaries. So the unit of analysis is a 300 m x 300 m
block of farmland (9 ha, 100 Landsat pixels): a neighbourhood of fields, not one owner's
plot. Blocks are placed where the ESA WorldCover 10 m map shows at least 92 % cropland,
and twelve are chosen to spread across the pilot box. Users can drop a pin or draw their
own field anywhere in the box.

Outputs
  data/processed/<region>/fields.geojson, fields_context.geojson (empty)
  data/processed/<region>/rasters/cropland_fraction.tif, landcover.tif  (30 m analysis grid)
"""
from __future__ import annotations

import json

import geopandas as gpd
import numpy as np
import rasterio
from rasterio.warp import Resampling, reproject
from rasterio.windows import from_bounds
from shapely.geometry import box

from .common import PILOT, PROCESSED, SourceError, run_source, write_status
from .s06_landsat import target_grid

SOURCE, TITLE, TIER = "fields", "Sample farm blocks (from ESA WorldCover cropland)", "MUST"
BLOCK_PX = 10            # 10 x 30 m = 300 m
N_BLOCKS = 12
MIN_CROPLAND = 0.92
STAC = "https://planetarycomputer.microsoft.com/api/stac/v1"


def worldcover() -> tuple[np.ndarray, np.ndarray, str]:
    """(cropland fraction, dominant class) on the 30 m analysis grid, plus the product id."""
    import planetary_computer
    import pystac_client

    transform, shape, _ = target_grid()
    items = list(pystac_client.Client.open(STAC).search(collections=["esa-worldcover"], bbox=PILOT["bbox"]).items())
    if not items:
        raise SourceError("No ESA WorldCover tile found for the pilot box")
    year = max(i.properties.get("start_datetime", "")[:4] for i in items)
    frac = np.zeros(shape, dtype="float32")
    cls = np.zeros(shape, dtype="uint8")
    w, s, e, n = PILOT["bbox"]
    pad = 0.01
    for it in [i for i in items if i.properties.get("start_datetime", "")[:4] == year]:
        with rasterio.open(planetary_computer.sign(it.assets["map"].href)) as src:
            win = from_bounds(w - pad, s - pad, e + pad, n + pad, transform=src.transform)
            data = src.read(1, window=win, boundless=True, fill_value=0)
            wt = src.window_transform(win)
            part = np.zeros(shape, dtype="float32")
            reproject((data == 40).astype("float32"), part, src_transform=wt, src_crs=src.crs,
                      dst_transform=transform, dst_crs=f"EPSG:{PILOT['utm_epsg']}", resampling=Resampling.average)
            pc = np.zeros(shape, dtype="uint8")
            reproject(data, pc, src_transform=wt, src_crs=src.crs, dst_transform=transform,
                      dst_crs=f"EPSG:{PILOT['utm_epsg']}", resampling=Resampling.mode)
        frac = np.maximum(frac, part)
        cls = np.where(cls == 0, pc, cls)
    return frac, cls, f"ESA WorldCover 10 m {year}"


def main() -> None:
    transform, shape, _ = target_grid()
    frac, cls, product = worldcover()
    rdir = PROCESSED / "rasters"
    rdir.mkdir(parents=True, exist_ok=True)
    prof = dict(driver="GTiff", height=shape[0], width=shape[1], count=1, crs=f"EPSG:{PILOT['utm_epsg']}",
                transform=transform, compress="deflate", tiled=True)
    with rasterio.open(rdir / "cropland_fraction.tif", "w", dtype="float32", **prof) as dst:
        dst.write(frac, 1)
    with rasterio.open(rdir / "landcover.tif", "w", dtype="uint8", nodata=0, **prof) as dst:
        dst.write(cls, 1)

    cands = []
    h, w = shape
    for r in range(BLOCK_PX, h - 2 * BLOCK_PX, BLOCK_PX):
        for c in range(BLOCK_PX, w - 2 * BLOCK_PX, BLOCK_PX):
            f = float(frac[r:r + BLOCK_PX, c:c + BLOCK_PX].mean())
            if f >= MIN_CROPLAND:
                cands.append((r, c, f))
    if len(cands) < N_BLOCKS:
        raise SourceError(f"Only {len(cands)} blocks with at least {MIN_CROPLAND:.0%} cropland in the pilot box")
    pts = np.array([(c + BLOCK_PX / 2, r + BLOCK_PX / 2) for r, c, _ in cands], dtype="float64")
    centre = np.array([w / 2, h / 2])
    chosen = [int(np.argmin(((pts - centre) ** 2).sum(axis=1)))]
    while len(chosen) < N_BLOCKS:                      # farthest-point sampling: spread them out
        d = np.min(((pts[:, None, :] - pts[chosen][None, :, :]) ** 2).sum(axis=2), axis=1)
        chosen.append(int(np.argmax(d)))

    recs = []
    for i in chosen:
        r, c, f = cands[i]
        x0, y1 = transform * (c, r)
        x1, y0 = transform * (c + BLOCK_PX, r + BLOCK_PX)
        recs.append({"cropland_share": round(f, 2), "geometry": box(x0, y0, x1, y1)})
    gdf = gpd.GeoDataFrame(recs, crs=f"EPSG:{PILOT['utm_epsg']}")
    cen = gpd.GeoSeries(gdf.geometry.centroid, crs=gdf.crs).to_crs(4326)
    gdf["lat"], gdf["lon"] = cen.y.round(5).values, cen.x.round(5).values
    gdf = gdf.sort_values(["lat", "lon"], ascending=[False, True]).reset_index(drop=True)
    gdf["field_id"] = [f"{PILOT['prefix']}-{i + 1:02d}" for i in range(len(gdf))]
    gdf["name"] = [f"Sample plot {i + 1}" for i in range(len(gdf))]
    gdf["area_ha"] = 9.0
    gdf["area_acres"] = 22.0
    gdf["shape_type"] = "300 m farm block"
    gdf["boundary_source"] = (f"A 300 m x 300 m block of farmland chosen from the {product} cropland map: "
                              "a neighbourhood of small fields, not one owner's plot")
    gdf["is_demo_data"] = False
    gdf.to_crs(4326).to_file(PROCESSED / "fields.geojson", driver="GeoJSON")
    (PROCESSED / "fields_context.geojson").write_text(
        json.dumps({"type": "FeatureCollection", "features": []}), encoding="utf-8")

    share = float((frac >= 0.5).mean())
    write_status(
        SOURCE, status="ok", title=TITLE, tier=TIER,
        fetched=f"{product}: {share:.0%} of the pilot box is cropland; {len(cands)} candidate blocks, "
                f"{len(gdf)} chosen to spread across the box",
        resolution="10 m land cover, averaged to the 30 m analysis grid; blocks are 300 m x 300 m (9 ha)",
        date_range=product[-4:],
        credit="Zanaga, D. et al. ESA WorldCover 10 m v200 (2022), CC BY 4.0. Accessed through Microsoft "
               "Planetary Computer.",
        access="STAC collection esa-worldcover, windowed COG read",
        message=f"{len(gdf)} sample blocks, cropland share {gdf['cropland_share'].min():.0%}-"
                f"{gdf['cropland_share'].max():.0%}",
        sanity={"crs": "EPSG:4326", "n_candidates": len(cands), "cropland_share_of_box": round(share, 3),
                "passed": True},
        outputs=["fields.geojson", "rasters/cropland_fraction.tif", "rasters/landcover.tif"],
        notes="No public map gives field boundaries or yearly crop types here, and fields average about "
              "one hectare. A block summarises the fields inside it; draw your own field for a closer look.",
    )


if __name__ == "__main__":
    run_source(SOURCE, TITLE, TIER, main)
