"""SRTM elevation and slope (OPTIONAL tier). Needs EARTHDATA_TOKEN.

Product: SRTMGL1 v003 (NASA Shuttle Radar Topography Mission, 1 arc-second, ~30 m),
two 1 x 1 degree tiles (~11 MB each) from the LP DAAC cloud archive.

Outputs
  data/processed/rasters/elevation_m.tif, slope_pct.tif   (30 m UTM grid of the pilot box)
  data/processed/field_terrain.parquet                    (per-field elevation and slope)
"""
from __future__ import annotations

import math
import zipfile

import numpy as np
import pandas as pd
import rasterio
from affine import Affine
from rasterio.warp import Resampling, reproject

from .common import PILOT, PROCESSED, RAW, load_fields, run_source, sanity_range, write_status
from .earthdata import download
from .s06_landsat import target_grid
from .zonal import coverage_weights, weighted_mean

SOURCE, TITLE, TIER = "srtm", "SRTM 1 arc-second elevation (SRTMGL1 v003)", "OPTIONAL"
BASE = "https://data.lpdaac.earthdatacloud.nasa.gov/lp-prod-protected/SRTMGL1.003"


def tile_names(bbox) -> list[str]:
    w, s, e, n = bbox
    names = []
    for lat in range(math.floor(s), math.floor(n) + 1):
        for lon in range(math.floor(w), math.floor(e) + 1):
            names.append(f"{'N' if lat >= 0 else 'S'}{abs(lat):02d}{'E' if lon >= 0 else 'W'}{abs(lon):03d}")
    return names


def read_tile(name: str) -> tuple[np.ndarray, Affine]:
    zpath = RAW / "srtm" / f"{name}.SRTMGL1.hgt.zip"
    zpath.parent.mkdir(parents=True, exist_ok=True)
    if not zpath.exists():
        download(f"{BASE}/{name}.SRTMGL1.hgt/{name}.SRTMGL1.hgt.zip", zpath)
    with zipfile.ZipFile(zpath) as zf:
        raw = zf.read(zf.namelist()[0])
    arr = np.frombuffer(raw, dtype=">i2").reshape(3601, 3601).astype("float32")
    arr[arr == -32768] = np.nan
    lat0 = int(name[1:3]) * (1 if name[0] == "N" else -1)
    lon0 = int(name[4:7]) * (1 if name[3] == "E" else -1)
    step = 1.0 / 3600.0
    # samples are at grid nodes: pixel centres from lon0 to lon0+1, lat0+1 down to lat0
    transform = Affine(step, 0, lon0 - step / 2, 0, -step, lat0 + 1 + step / 2)
    return arr, transform


def slope_percent(elev: np.ndarray, cell: float = 30.0) -> np.ndarray:
    """Slope in percent from a 3x3 Horn kernel (the usual GIS slope)."""
    z = np.pad(elev, 1, mode="edge")
    dzdx = ((z[:-2, 2:] + 2 * z[1:-1, 2:] + z[2:, 2:]) - (z[:-2, :-2] + 2 * z[1:-1, :-2] + z[2:, :-2])) / (8 * cell)
    dzdy = ((z[2:, :-2] + 2 * z[2:, 1:-1] + z[2:, 2:]) - (z[:-2, :-2] + 2 * z[:-2, 1:-1] + z[:-2, 2:])) / (8 * cell)
    return np.sqrt(dzdx ** 2 + dzdy ** 2) * 100.0


def main() -> None:
    fields = load_fields()
    transform, shape, _ = target_grid()
    elev = np.full(shape, np.nan, dtype="float32")
    tiles = tile_names(PILOT["bbox"])
    for name in tiles:
        arr, src_tr = read_tile(name)
        part = np.full(shape, np.nan, dtype="float32")
        reproject(arr, part, src_transform=src_tr, src_crs="EPSG:4326", dst_transform=transform,
                  dst_crs=f"EPSG:{PILOT['utm_epsg']}", resampling=Resampling.bilinear,
                  src_nodata=np.nan, dst_nodata=np.nan)
        elev = np.where(np.isfinite(elev), elev, part)
    # Radar elevation carries a few metres of pixel noise, which on flat valley floor would
    # read as 2-4 % "slope". Smooth over ~150 m before taking the gradient.
    from scipy import ndimage
    smooth = ndimage.gaussian_filter(np.nan_to_num(elev, nan=float(np.nanmean(elev))), sigma=2.5)
    slope = slope_percent(smooth)
    slope_raw = slope_percent(elev)

    out_dir = PROCESSED / "rasters"
    out_dir.mkdir(parents=True, exist_ok=True)
    prof = dict(driver="GTiff", height=shape[0], width=shape[1], count=1, dtype="float32",
                crs=f"EPSG:{PILOT['utm_epsg']}", transform=transform, nodata=np.nan,
                compress="deflate", tiled=True)
    with rasterio.open(out_dir / "elevation_m.tif", "w", **prof) as dst:
        dst.write(elev, 1)
    with rasterio.open(out_dir / "slope_pct.tif", "w", **prof) as dst:
        dst.write(slope.astype("float32"), 1)

    futm = fields.to_crs(PILOT["utm_epsg"])
    rows = []
    for _, f in futm.iterrows():
        w = coverage_weights(f.geometry, transform, shape, supersample=5)
        m_elev, _ = weighted_mean(elev, w)
        m_slope, _ = weighted_mean(slope, w)
        inside = slope[w > 0.5]
        rr, cc = np.nonzero(w > 0.5)
        z = elev[rr, cc]
        okz = np.isfinite(z)
        # overall tilt of the field: least-squares plane through every pixel (noise averages out)
        A = np.c_[cc[okz] * 30.0, rr[okz] * 30.0, np.ones(okz.sum())]
        coef, *_ = np.linalg.lstsq(A, z[okz], rcond=None)
        plane = float(np.hypot(coef[0], coef[1]) * 100.0)
        m_raw, _ = weighted_mean(slope_raw, w)
        rows.append({"field_id": f["field_id"], "elevation_m": round(m_elev, 1),
                     "slope_pct_plane": round(plane, 2),
                     "slope_pct_mean": round(m_slope, 2),
                     "slope_pct_p90": round(float(np.nanpercentile(inside, 90)), 2),
                     "slope_pct_max": round(float(np.nanmax(inside)), 2),
                     "slope_pct_raw_pixel_mean": round(m_raw, 2),
                     "relief_m": round(float(np.nanpercentile(smooth[rr, cc], 98) - np.nanpercentile(smooth[rr, cc], 2)), 1)})
    df = pd.DataFrame(rows)
    df.to_parquet(PROCESSED / "field_terrain.parquet", index=False)

    checks = [sanity_range(df["elevation_m"], 1500, 2400, "field elevation m"),
              sanity_range(df["slope_pct_plane"], 0, 8, "field tilt % (plane fit)"),
              sanity_range(df["slope_pct_mean"], 0, 15, "field mean slope % (smoothed)"),
              sanity_range(elev[np.isfinite(elev)], 1500, 3300, "pilot-box elevation m")]
    ok = all(c["passed"] for c in checks)
    write_status(
        SOURCE, status="ok" if ok else "partial", title=TITLE, tier=TIER,
        fetched=f"tiles {', '.join(tiles)}; resampled (bilinear) to the 30 m analysis grid; slope by "
                "Horn's 3x3 method on a ~150 m smoothed surface, plus a plane fit per field",
        resolution="1 arc-second (~30 m); acquired February 2000 (static)",
        date_range="2000-02-11 to 2000-02-22",
        credit="NASA JPL (2013). NASA Shuttle Radar Topography Mission Global 1 arc second. "
               "NASA EOSDIS Land Processes DAAC.",
        access="LP DAAC cloud archive (data.lpdaac.earthdatacloud.nasa.gov), Earthdata bearer token",
        message=f"elevation {df['elevation_m'].min():.0f}-{df['elevation_m'].max():.0f} m, field tilt "
                f"{df['slope_pct_plane'].min():.1f}-{df['slope_pct_plane'].max():.1f} % (plane fit; raw-pixel "
                f"slope reads {df['slope_pct_raw_pixel_mean'].mean():.1f} % because of radar noise); sanity "
                f"{'passed' if ok else 'CHECK'}",
        sanity={"checks": checks, "crs": f"EPSG:{PILOT['utm_epsg']}"},
        outputs=["rasters/elevation_m.tif", "rasters/slope_pct.tif", "field_terrain.parquet"],
        notes="Radar elevation has a few metres of vertical noise: taken pixel by pixel it reads as "
              "2-4 % slope on flat ground. The app uses each field's overall tilt (plane fit), which "
              "averages that noise out. The survey predates any land levelling done since 2000.",
    )


if __name__ == "__main__":
    run_source(SOURCE, TITLE, TIER, main)
