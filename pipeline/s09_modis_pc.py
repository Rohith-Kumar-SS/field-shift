"""MODIS/Terra NDVI 250 m, 16-day (MOD13Q1 v061) through Microsoft Planetary Computer.

Same NASA product as pipeline/s09_modis.py, different route (the ORNL subset service was
returning errors when the India pilots were built). Reads only the pilot-box window of the
NDVI and pixel-reliability layers of every composite, 2001-2025.

Where no crop map exists, this 25-year record is what tells us how many crops a year a
block grows and when its green seasons peak.

Output: data/processed/<region>/modis_field_ndvi.parquet  (field_id, date, ndvi)
"""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor

import numpy as np
import pandas as pd
import rasterio
from rasterio.warp import transform_bounds
from rasterio.windows import from_bounds

from .common import CLIMATE_END, PILOT, PROCESSED, RAW, SourceError, load_fields, run_source, sanity_range, write_status
from .zonal import coverage_weights, weighted_mean

SOURCE, TITLE, TIER = "modis", "MODIS/Terra NDVI 250 m (MOD13Q1 v061)", "OPTIONAL"
STAC = "https://planetarycomputer.microsoft.com/api/stac/v1"
START_YEAR = 2001


def read_item(item):
    """(date, ndvi array, transform, crs) for one composite; pilot-box window; cached."""
    import planetary_computer

    day = item.properties.get("start_datetime", item.id)[:10]
    cache = RAW / "modis_pc" / f"{item.id}.npz"
    cache.parent.mkdir(parents=True, exist_ok=True)
    if cache.exists():
        z = np.load(cache, allow_pickle=True)
        return day, z["ndvi"], rasterio.Affine(*z["t"]), str(z["crs"])
    out = {}
    for key in ("250m_16_days_NDVI", "250m_16_days_pixel_reliability"):
        with rasterio.open(planetary_computer.sign(item.assets[key].href)) as src:
            b = transform_bounds("EPSG:4326", src.crs, *PILOT["bbox"])
            pad = 600
            win = from_bounds(b[0] - pad, b[1] - pad, b[2] + pad, b[3] + pad, transform=src.transform).round_offsets().round_lengths()
            out[key] = src.read(1, window=win)
            t, crs = src.window_transform(win), src.crs.to_wkt()
    ndvi = out["250m_16_days_NDVI"].astype("float32") * 0.0001
    rel = out["250m_16_days_pixel_reliability"]
    ndvi[(rel > 1) | (ndvi < -0.2)] = np.nan       # keep "good" and "marginal"; drop snow, cloud, fill
    np.savez_compressed(cache, ndvi=ndvi, t=np.array(t[:6]), crs=np.array(crs))
    return day, ndvi, t, crs


def main() -> None:
    import pystac_client

    fields = load_fields()
    cat = pystac_client.Client.open(STAC)
    items = []
    for year in range(START_YEAR, CLIMATE_END + 1):
        found = cat.search(collections=["modis-13Q1-061"], bbox=PILOT["bbox"],
                           datetime=f"{year}-01-01/{year}-12-31").items()
        items += [i for i in found if i.id.startswith("MOD13Q1")]
    if not items:
        raise SourceError("No MOD13Q1 composites found on Planetary Computer for the pilot box")
    by_day = {}
    for it in items:                                   # one tile per date is enough for a small box
        by_day.setdefault(it.properties.get("start_datetime", it.id)[:10], it)

    def safe(it):
        try:
            return read_item(it)
        except Exception:  # noqa: BLE001 - a failed composite is skipped and counted
            return None

    with ThreadPoolExecutor(max_workers=8) as ex:
        results = list(ex.map(safe, by_day.values()))
    good = [r for r in results if r is not None]
    weights, rows = {}, []
    for day, ndvi, t, crs in good:
        key = (tuple(t[:6]), ndvi.shape)
        if key not in weights:
            fp = fields.to_crs(crs)
            weights[key] = {f["field_id"]: coverage_weights(f.geometry, t, ndvi.shape, supersample=20)
                            for _, f in fp.iterrows()}
        for fid, w in weights[key].items():
            v, frac = weighted_mean(ndvi, w)
            if frac >= 0.6:
                rows.append({"field_id": fid, "date": pd.Timestamp(day), "ndvi": round(v, 4)})
    df = pd.DataFrame(rows).drop_duplicates(["field_id", "date"]).sort_values(["field_id", "date"])
    df.to_parquet(PROCESSED / "modis_field_ndvi.parquet", index=False)

    per = df.groupby("field_id").size()
    checks = [sanity_range(df["ndvi"], -0.2, 1.0, "field NDVI"),
              sanity_range(per, 250, 700, "usable composites per field")]
    ok = all(c["passed"] for c in checks)
    failed = len(by_day) - len(good)
    write_status(
        SOURCE, status="ok" if (ok and failed < 15) else "partial", title=TITLE, tier=TIER,
        fetched=f"{len(good)} of {len(by_day)} composites; NDVI masked with the pixel-reliability layer",
        resolution="231.7 m (MODIS sinusoidal grid); 16-day composites",
        date_range=f"{df['date'].min():%Y-%m-%d} to {df['date'].max():%Y-%m-%d}",
        credit="Didan, K. (2021). MODIS/Terra Vegetation Indices 16-Day L3 Global 250m SIN Grid V061. "
               "NASA EOSDIS LP DAAC. Accessed through Microsoft Planetary Computer.",
        access=f"STAC {STAC} (collection modis-13Q1-061), windowed COG reads",
        message=f"{len(df):,} field-composites, median {int(per.median())} usable per field; "
                f"{failed} composites failed; sanity {'passed' if ok else 'CHECK'}",
        sanity={"checks": checks, "crs": "MODIS sinusoidal"},
        outputs=["modis_field_ndvi.parquet"],
        notes="A 300 m block holds only one or two MODIS pixels, so this record describes the block and "
              "its neighbours together. Monsoon cloud removes many composites between June and September.",
    )


if __name__ == "__main__":
    run_source(SOURCE, TITLE, TIER, main)
