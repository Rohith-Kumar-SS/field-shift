"""Landsat 8/9 Collection 2 Level-2 surface reflectance (STRONG tier).

Route: Microsoft Planetary Computer STAC (no key). The same USGS/NASA Landsat C2 L2
scenes are on Google Earth Engine; Planetary Computer is used because Earth Engine was
not authenticated when the pipeline was built.

Small clips only: for every scene we read just the pilot-box window of five bands
straight from the cloud-optimised GeoTIFFs (no whole-scene downloads).

Outputs
  data/raw/landsat/<date>_p<path>.npz            per-acquisition NDVI / bare-soil index / QA
  data/processed/landsat_field_obs.parquet       per-field, per-acquisition statistics
  data/processed/rasters/ndvi_monthly_<year>.tif monthly median NDVI for the whole pilot box
"""
from __future__ import annotations

import os
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date

import numpy as np
import pandas as pd
import rasterio
from affine import Affine
from pyproj import Transformer
from rasterio.windows import from_bounds

from .common import (FIELD_EO_END, FIELD_EO_START, PILOT, PROCESSED, RAW, SourceError, load_fields,
                     run_source, sanity_range, write_status)
from .zonal import coverage_weights, weighted_mean

SOURCE, TITLE, TIER = "landsat", "Landsat 8/9 surface reflectance (NDVI, bare-soil index)", "STRONG"
STAC = "https://planetarycomputer.microsoft.com/api/stac/v1"
BANDS = ["blue", "red", "nir08", "swir16", "qa_pixel"]
NODATA = -32768
MAX_CLOUD = 70  # scene-level cloud cover (%); pixel-level QA masks do the real work

os.environ.setdefault("GDAL_DISABLE_READDIR_ON_OPEN", "EMPTY_DIR")
os.environ.setdefault("CPL_VSIL_CURL_ALLOWED_EXTENSIONS", ".TIF,.tif")
os.environ.setdefault("GDAL_HTTP_MERGE_CONSECUTIVE_RANGES", "YES")
os.environ.setdefault("GDAL_HTTP_MAX_RETRY", "4")
os.environ.setdefault("GDAL_HTTP_RETRY_DELAY", "2")
os.environ.setdefault("VSI_CACHE", "TRUE")


def target_grid() -> tuple[Affine, tuple[int, int], tuple[float, float, float, float]]:
    """30 m UTM grid over the pilot box, aligned to the Landsat pixel grid.

    Landsat UTM pixel centres sit on multiples of 30 m, so pixel edges sit at 15 + 30k.
    """
    w, s, e, n = PILOT["bbox"]
    tr = Transformer.from_crs(4326, PILOT["utm_epsg"], always_xy=True)
    xs, ys = tr.transform([w, e, w, e], [s, s, n, n])
    snap_dn = lambda v: np.floor((v - 15) / 30.0) * 30.0 + 15   # noqa: E731
    snap_up = lambda v: np.ceil((v - 15) / 30.0) * 30.0 + 15    # noqa: E731
    x0, x1 = snap_dn(min(xs)), snap_up(max(xs))
    y0, y1 = snap_dn(min(ys)), snap_up(max(ys))
    width, height = int(round((x1 - x0) / 30)), int(round((y1 - y0) / 30))
    return Affine(30, 0, x0, 0, -30, y1), (height, width), (x0, y0, x1, y1)


def search_items(start: str, end: str, max_cloud: float = MAX_CLOUD) -> list:
    import pystac_client

    cat = pystac_client.Client.open(STAC)
    search = cat.search(
        collections=["landsat-c2-l2"], bbox=PILOT["bbox"], datetime=f"{start}/{end}",
        query={"platform": {"in": ["landsat-8", "landsat-9"]}, "eo:cloud_cover": {"lt": max_cloud}})
    return list(search.items())


def group_items(items) -> dict[tuple[str, str], list]:
    """Group scenes by (acquisition date, WRS path): adjacent rows are one overpass."""
    groups: dict[tuple[str, str], list] = {}
    for it in items:
        key = (it.datetime.strftime("%Y%m%d"), str(it.properties.get("landsat:wrs_path", "000")))
        groups.setdefault(key, []).append(it)
    return groups


def scene_path(key: tuple[str, str]):
    d = RAW / "landsat"
    d.mkdir(parents=True, exist_ok=True)
    return d / f"{key[0]}_p{key[1]}.npz"


def read_group(key, items, transform: Affine, shape, bounds) -> str:
    """Read the pilot-box window of one overpass and cache NDVI/BSI/flags as a small npz."""
    import planetary_computer

    out = scene_path(key)
    if out.exists():
        return "cached"
    h, w = shape
    bands = {b: np.zeros(shape, dtype="uint16") for b in BANDS}
    for it in sorted(items, key=lambda i: i.id):
        if it.properties.get("proj:epsg", it.properties.get("proj:code")) not in (
                PILOT["utm_epsg"], f"EPSG:{PILOT['utm_epsg']}"):
            continue  # scene delivered in a neighbouring UTM zone: skip rather than resample
        if bands["qa_pixel"].all():
            break  # the first row already covers the whole pilot box
        part = {}
        for b in BANDS:
            href = planetary_computer.sign(it.assets[b].href)
            with rasterio.open(href) as src:
                win = from_bounds(*bounds, transform=src.transform).round_offsets().round_lengths()
                part[b] = src.read(1, window=win, boundless=True, fill_value=0)
            if part[b].shape != shape:
                raise SourceError(f"Landsat window {part[b].shape} does not match target grid {shape}")
        fill = (part["qa_pixel"] == 0) | (part["qa_pixel"] & 1 > 0) | (part["red"] == 0)
        need = bands["qa_pixel"] == 0
        take = need & ~fill
        for b in BANDS:
            bands[b][take] = part[b][take]
    qa = bands["qa_pixel"]
    has = qa != 0
    if not has.any():
        np.savez_compressed(out, empty=np.array([1]))
        return "empty"
    cloud = (qa & 0b11110) > 0          # dilated cloud, cirrus, cloud, cloud shadow
    snow = (qa & (1 << 5)) > 0
    water = (qa & (1 << 7)) > 0
    sr = {b: bands[b].astype("float32") * 2.75e-5 - 0.2 for b in ("blue", "red", "nir08", "swir16")}
    good = has & ~cloud & ~water
    for b in sr:
        good &= (sr[b] > 0) & (sr[b] < 1)
    with np.errstate(divide="ignore", invalid="ignore"):
        ndvi = (sr["nir08"] - sr["red"]) / (sr["nir08"] + sr["red"])
        bsi = ((sr["swir16"] + sr["red"]) - (sr["nir08"] + sr["blue"])) / (
            (sr["swir16"] + sr["red"]) + (sr["nir08"] + sr["blue"]))
    def pack(a):
        o = np.full(shape, NODATA, dtype="int16")
        o[good] = np.clip(np.round(a[good] * 10000), -10000, 10000).astype("int16")
        return o
    flags = np.zeros(shape, dtype="uint8")   # 0 no data / cloud, 1 clear, 2 clear + snow
    flags[good] = 1
    flags[good & snow] = 2
    np.savez_compressed(out, ndvi=pack(ndvi), bsi=pack(bsi), flags=flags,
                        platforms=np.array(sorted({i.properties.get("platform", "") for i in items})))
    return "new"


def fetch_scenes(start: str, end: str, max_cloud: float = MAX_CLOUD, workers: int = 8) -> dict:
    """Download (or reuse) every overpass in a date range. Returns {key: path}."""
    transform, shape, bounds = target_grid()
    groups = group_items(search_items(start, end, max_cloud))
    todo = {k: v for k, v in groups.items() if not scene_path(k).exists()}
    errors = []
    if todo:
        with ThreadPoolExecutor(max_workers=workers) as ex:
            futs = {ex.submit(read_group, k, v, transform, shape, bounds): k for k, v in todo.items()}
            for n, fut in enumerate(as_completed(futs), 1):
                try:
                    fut.result()
                except Exception as exc:  # noqa: BLE001 - keep going, report at the end
                    errors.append(f"{futs[fut][0]}: {type(exc).__name__}")
                if n % 50 == 0:
                    print(f"  landsat: {n}/{len(todo)} overpasses read", flush=True)
    return {"keys": sorted(groups), "errors": errors, "new": len(todo)}


def load_scene(key):
    z = np.load(scene_path(key))
    if "empty" in z.files:
        return None
    return z


def cached_keys(start: str | None = None, end: str | None = None) -> list[tuple[str, str]]:
    keys = []
    for p in sorted((RAW / "landsat").glob("*_p*.npz")):
        d, path = p.stem.split("_p")
        if (start is None or d >= start.replace("-", "")) and (end is None or d <= end.replace("-", "")):
            keys.append((d, path))
    return keys


def field_observations(fields) -> pd.DataFrame:
    """Area-weighted NDVI / bare-soil statistics per field for every cached overpass."""
    transform, shape, _ = target_grid()
    futm = fields.to_crs(PILOT["utm_epsg"])
    weights = {f["field_id"]: coverage_weights(f.geometry, transform, shape, supersample=5)
               for _, f in futm.iterrows()}
    slices = {}
    for fid, w in weights.items():
        rows, cols = np.nonzero(w)
        slices[fid] = (slice(rows.min(), rows.max() + 1), slice(cols.min(), cols.max() + 1))
    out = []
    for key in cached_keys(f"{FIELD_EO_START}-01-01", f"{FIELD_EO_END}-12-31"):
        z = load_scene(key)
        if z is None:
            continue
        ndvi, bsi, flags = z["ndvi"], z["bsi"], z["flags"]
        for fid, w in weights.items():
            sl = slices[fid]
            wf, fl = w[sl], flags[sl]
            clear = fl > 0
            n = np.where(clear, ndvi[sl] / 10000.0, np.nan)
            b = np.where(clear, bsi[sl] / 10000.0, np.nan)
            mean_ndvi, frac = weighted_mean(n, wf)
            if frac < 0.6:
                continue  # mostly cloud: do not trust a few pixels
            mean_bsi, _ = weighted_mean(b, wf)
            wsum = wf[clear].sum()
            snow_frac = float(wf[fl == 2].sum() / wsum)
            var = float((wf[clear] * (n[clear] - mean_ndvi) ** 2).sum() / wsum)
            low = float(wf[clear & (n < 0.2)].sum() / wsum)
            out.append({"field_id": fid, "date": pd.Timestamp(key[0]), "wrs_path": key[1],
                        "ndvi": round(mean_ndvi, 4), "bsi": round(mean_bsi, 4),
                        "ndvi_sd": round(var ** 0.5, 4), "valid_frac": round(frac, 3),
                        "snow_frac": round(snow_frac, 3), "low_cover_frac": round(low, 3)})
    return pd.DataFrame(out)


def monthly_composites() -> list[str]:
    """Median NDVI per calendar month for the whole pilot box (snow-free, clear pixels)."""
    transform, shape, _ = target_grid()
    out_dir = PROCESSED / "rasters"
    out_dir.mkdir(parents=True, exist_ok=True)
    written = []
    keys = cached_keys(f"{FIELD_EO_START}-01-01", f"{FIELD_EO_END}-12-31")
    for year in range(FIELD_EO_START, FIELD_EO_END + 1):
        stack = np.full((12, *shape), NODATA, dtype="int16")
        counts = np.zeros((12, *shape), dtype="uint8")
        for month in range(1, 13):
            arrs = []
            for key in keys:
                if key[0][:6] != f"{year}{month:02d}":
                    continue
                z = load_scene(key)
                if z is None:
                    continue
                a = np.where(z["flags"] == 1, z["ndvi"].astype("float32"), np.nan)
                arrs.append(a)
            if not arrs:
                continue
            cube = np.stack(arrs)
            with np.errstate(all="ignore"):
                import warnings
                with warnings.catch_warnings():
                    warnings.simplefilter("ignore", category=RuntimeWarning)
                    med = np.nanmedian(cube, axis=0)
            ok = np.isfinite(med)
            stack[month - 1][ok] = np.round(med[ok]).astype("int16")
            counts[month - 1] = np.isfinite(cube).sum(axis=0).astype("uint8")
        path = out_dir / f"ndvi_monthly_{year}.tif"
        with rasterio.open(path, "w", driver="GTiff", height=shape[0], width=shape[1], count=12,
                           dtype="int16", crs=f"EPSG:{PILOT['utm_epsg']}", transform=transform,
                           nodata=NODATA, compress="deflate", predictor=2, tiled=True) as dst:
            dst.write(stack)
            dst.update_tags(scale="0.0001", units="NDVI x 10000", source="Landsat 8/9 C2 L2",
                            method="monthly median of clear, snow-free observations")
        np.save(out_dir / f"ndvi_monthly_count_{year}.npy", counts)
        written.append(path.name)
    return written


def main() -> None:
    fields = load_fields()
    info = fetch_scenes(f"{FIELD_EO_START}-01-01", f"{FIELD_EO_END}-12-31")
    obs = field_observations(fields)
    if obs.empty:
        raise SourceError("No usable Landsat observations were read for the pilot fields",
                          action="Check internet access to planetarycomputer.microsoft.com and re-run "
                                 "`python -m pipeline.s06_landsat` (scenes already read are cached).")
    obs.to_parquet(PROCESSED / "landsat_field_obs.parquet", index=False)
    rasters = monthly_composites()

    per_field = obs.groupby("field_id").size()
    checks = [sanity_range(obs["ndvi"], -0.2, 1.0, "field-mean NDVI"),
              sanity_range(obs["bsi"], -0.7, 0.7, "field-mean bare-soil index"),
              sanity_range(per_field, 60, 5000, "clear observations per field")]
    ok = all(c["passed"] for c in checks)
    n_scenes = len(cached_keys(f"{FIELD_EO_START}-01-01", f"{FIELD_EO_END}-12-31"))
    write_status(
        SOURCE, status="ok" if (ok and not info["errors"]) else "partial", title=TITLE, tier=TIER,
        fetched=f"{n_scenes} overpasses (scene cloud cover < {MAX_CLOUD} %), pilot-box window of "
                f"bands {', '.join(BANDS)}; {len(obs):,} clear field observations",
        resolution="30 m; about every 8 days from two satellites, more where two orbit paths overlap",
        date_range=f"{obs['date'].min():%Y-%m-%d} to {obs['date'].max():%Y-%m-%d}",
        credit="Landsat 8/9 Collection 2 Level-2 Science Products courtesy of the U.S. Geological "
               "Survey and NASA. Accessed through Microsoft Planetary Computer.",
        access=f"STAC {STAC} (collection landsat-c2-l2), windowed COG reads",
        message=f"{n_scenes} overpasses, {len(obs):,} field observations, median "
                f"{int(per_field.median())} per field; sanity {'passed' if ok else 'CHECK'}"
                + (f"; {len(info['errors'])} overpass(es) failed to read" if info["errors"] else ""),
        sanity={"checks": checks, "crs": f"EPSG:{PILOT['utm_epsg']}", "read_errors": info["errors"][:20]},
        outputs=["landsat_field_obs.parquet"] + [f"rasters/{r}" for r in rasters],
        notes="Pixels flagged cloud, cloud shadow, cirrus or water by the Landsat QA band are "
              "dropped; an observation is kept only if at least 60 % of the field is clear. "
              "Snow-covered observations are kept but flagged, and excluded from greenness "
              "statistics. NDVI shows green cover, not soil health, and saturates in dense alfalfa.",
    )


if __name__ == "__main__":
    run_source(SOURCE, TITLE, TIER, main)
