"""FAO WaPOR v3 actual evapotranspiration (for regions outside OpenET's coverage).

Product: WaPOR v3 Level 1 monthly "Actual EvapoTranspiration and Interception" (AETI),
about 300 m, global, from the ETLook model driven by satellite data. Small clips only:
each monthly global file is a cloud-optimised GeoTIFF, and only the pilot-box window is
read over HTTP.

Output: data/processed/<region>/et_field_monthly.parquet  (field_id, date, et_mm, source)
"""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor

import numpy as np
import pandas as pd
import rasterio
from rasterio.windows import from_bounds

from .common import FIELD_EO_END, FIELD_EO_START, PILOT, PROCESSED, RAW, SourceError, load_fields, run_source, sanity_range, write_status
from .zonal import coverage_weights, weighted_mean

SOURCE, TITLE, TIER = "wapor", "FAO WaPOR v3 actual evapotranspiration (300 m)", "STRONG"
BASE = ("https://storage.googleapis.com/fao-gismgr-wapor-3-data/DATA/WAPOR-3/MAPSET/L1-AETI-M/"
        "WAPOR-3.L1-AETI-M.{y}-{m:02d}.tif")


def read_month(y: int, m: int):
    """Pilot-box window of one month, cached as a small npz. Returns (array mm/month, transform) or None."""
    cache = RAW / "wapor" / f"{y}-{m:02d}.npz"
    cache.parent.mkdir(parents=True, exist_ok=True)
    if cache.exists():
        z = np.load(cache)
        return (None if "missing" in z.files else (z["a"], rasterio.Affine(*z["t"])))
    w, s, e, n = PILOT["bbox"]
    pad = 0.01
    for _ in range(3):
        try:
            with rasterio.open("/vsicurl/" + BASE.format(y=y, m=m)) as src:
                win = from_bounds(w - pad, s - pad, e + pad, n + pad, transform=src.transform).round_offsets().round_lengths()
                a = src.read(1, window=win).astype("float32")
                a[a == src.nodata] = np.nan
                a *= float(src.scales[0] or 1.0)
                t = src.window_transform(win)
            np.savez_compressed(cache, a=a, t=np.array(t[:6]))
            return a, t
        except rasterio.errors.RasterioIOError as exc:
            if "404" in str(exc) or "does not exist" in str(exc):
                np.savez_compressed(cache.with_name(cache.stem + "_missing.npz"), missing=np.array([1]))
                return None
    return None


def main() -> None:
    fields = load_fields()
    months = [(y, m) for y in range(FIELD_EO_START, FIELD_EO_END + 1) for m in range(1, 13)]
    with ThreadPoolExecutor(max_workers=6) as ex:
        results = list(ex.map(lambda ym: read_month(*ym), months))
    rows, weights = [], None
    for (y, m), res in zip(months, results):
        if res is None:
            continue
        a, t = res
        if weights is None:
            weights = {f["field_id"]: coverage_weights(f.geometry, t, a.shape, supersample=20) for _, f in fields.iterrows()}
        for fid, w in weights.items():
            v, frac = weighted_mean(a, w)
            if frac >= 0.5:
                rows.append({"field_id": fid, "date": pd.Timestamp(y, m, 1), "et_mm": round(v, 1)})
    if not rows:
        raise SourceError("WaPOR returned no data for the pilot box",
                          action="Check internet access to storage.googleapis.com and re-run "
                                 "`python tasks.py data wapor`.")
    df = pd.DataFrame(rows)
    df["et_min_mm"], df["et_max_mm"], df["repeated_value"] = np.nan, np.nan, False
    df["source"] = "FAO WaPOR v3 (300 m)"
    df.to_parquet(PROCESSED / "et_field_monthly.parquet", index=False)

    annual = df.groupby(["field_id", df["date"].dt.year])["et_mm"].sum()
    full = annual[df.groupby(["field_id", df["date"].dt.year]).size() == 12]
    checks = [sanity_range(df["et_mm"], 0, 320, "monthly ET mm"),
              sanity_range(full, 200, 2000, "annual ET mm")]
    ok = all(c["passed"] for c in checks)
    write_status(
        SOURCE, status="ok" if ok else "partial", title=TITLE, tier=TIER,
        fetched=f"{df['date'].nunique()} monthly maps, pilot-box window; {len(df):,} field-months",
        resolution="~300 m; monthly", date_range=f"{df['date'].min():%Y-%m} to {df['date'].max():%Y-%m}",
        credit="FAO (2023). WaPOR v3: the FAO portal to monitor Water Productivity through Open-access of "
               "Remotely sensed derived data. CC BY 4.0.",
        access="Cloud-optimised GeoTIFFs on Google Cloud Storage (fao-gismgr-wapor-3-data), windowed reads",
        message=f"{df['date'].nunique()} months; mean annual ET {full.mean():.0f} mm; sanity {'passed' if ok else 'CHECK'}",
        sanity={"checks": checks, "crs": "EPSG:4326"},
        outputs=["et_field_monthly.parquet"],
        notes="A model estimate of water evaporated and transpired, not a measurement. One 300 m pixel is "
              "about the size of a sample block and covers several small fields. Unlike OpenET it is a single "
              "model, so no model spread is shown.",
    )


if __name__ == "__main__":
    run_source(SOURCE, TITLE, TIER, main)
