"""GRACE / GRACE-FO terrestrial water storage (regional long-term water trend).

Product: JPL GRACE and GRACE-FO mascon solution RL06.3 v4 with coastal resolution
improvement (monthly liquid-water-equivalent thickness anomaly, cm). Needs EARTHDATA_TOKEN.

Scale warning, repeated in the app: one GRACE mascon is about 300 km across. It says how
much water (groundwater + soil water + surface water) the whole region has gained or lost.
It cannot say anything about one village or one field. That is exactly why it was left out
of the small Nevada valley (where well records exist) and is used here: north-west India's
groundwater loss is a regional signal that GRACE was the first to measure.

Output: data/processed/<region>/grace_monthly.parquet  (date, lwe_cm, uncertainty_cm)
"""
from __future__ import annotations

import re

import numpy as np
import pandas as pd
import requests

from .common import PILOT, PROCESSED, ROOT, SourceError, run_source, sanity_range, write_status
from .earthdata import download, list_granules

SOURCE, TITLE, TIER = "grace", "GRACE / GRACE-FO water storage anomaly (JPL mascons RL06.3)", "OPTIONAL"
SHORT_NAME = "TELLUS_GRAC-GRFO_MASCON_CRI_GRID_RL06.3_V4"


def main() -> None:
    from engine.agromet import theil_sen_trend

    r = requests.get("https://cmr.earthdata.nasa.gov/search/collections.umm_json",
                     params={"short_name": SHORT_NAME}, timeout=120)
    items = r.json().get("items", [])
    if not items:
        raise SourceError(f"{SHORT_NAME} not found in NASA CMR")
    cid = items[0]["meta"]["concept-id"]
    gran = next(iter(list_granules(cid, "2002-01-01T00:00:00Z,2030-01-01T00:00:00Z")), None)
    if gran is None or not gran["https"]:
        raise SourceError("No downloadable GRACE mascon granule found in NASA CMR")

    # One 44 MB file holds the whole globe and every month; NASA's subsetting service does not
    # serve this product, so the file is downloaded once and shared by every region.
    shared = ROOT / "data" / "raw" / "_shared" / "grace"
    shared.mkdir(parents=True, exist_ok=True)
    path = shared / (gran["name"] + ".nc")
    if not path.exists():
        download(gran["https"], path)

    import netCDF4

    lon, lat = PILOT["centroid"]
    ds = netCDF4.Dataset(path)
    try:
        lats, lons = np.asarray(ds["lat"][:]), np.asarray(ds["lon"][:])
        i, j = int(np.argmin(np.abs(lats - lat))), int(np.argmin(np.abs(lons - (lon % 360))))
        t = np.asarray(ds["time"][:], dtype="float64")
        base = pd.Timestamp(re.search(r"since\s+(\d{4}-\d{2}-\d{2})", ds["time"].units).group(1))
        lwe = np.ma.filled(ds["lwe_thickness"][:, i, j], np.nan).astype("float64")
        unc = np.ma.filled(ds["uncertainty"][:, i, j], np.nan).astype("float64")
        cell = (float(lats[i]), float(lons[j]))
    finally:
        ds.close()
    df = pd.DataFrame({"date": [base + pd.Timedelta(days=float(d)) for d in t], "lwe_cm": lwe, "uncertainty_cm": unc})
    df["date"] = df["date"].dt.to_period("M").dt.to_timestamp()
    df = df.dropna(subset=["lwe_cm"]).drop_duplicates("date").sort_values("date")
    df.to_parquet(PROCESSED / "grace_monthly.parquet", index=False)

    annual = df.groupby(df["date"].dt.year)["lwe_cm"].agg(["mean", "size"])
    annual = annual[annual["size"] >= 6]
    tr = theil_sen_trend(annual.index, annual["mean"].values)
    checks = [sanity_range(df["lwe_cm"], -150, 150, "water storage anomaly cm"),
              sanity_range(df["uncertainty_cm"], 0, 60, "uncertainty cm")]
    ok = all(c["passed"] for c in checks)
    per_year = None if tr["slope_per_decade"] is None else round(tr["slope_per_decade"] / 10, 2)
    write_status(
        SOURCE, status="ok" if ok else "partial", title=TITLE, tier=TIER,
        fetched=f"{len(df)} monthly values for the 0.5-degree grid cell at {cell[0]:.2f} N, {cell[1] % 360:.2f} E "
                "(the value of the ~3-degree mascon it belongs to)",
        resolution="~300 km mascon, posted on a 0.5-degree grid; monthly, with gaps (2017-2018 between missions)",
        date_range=f"{df['date'].min():%Y-%m} to {df['date'].max():%Y-%m}",
        credit="Wiese, D. N. et al. (2023). JPL GRACE and GRACE-FO Mascon Ocean, Ice, and Hydrology Equivalent "
               "Water Height CRI Filtered RL06.3Mv04. NASA PO.DAAC.",
        access="PO.DAAC cloud archive, one 44 MB global file downloaded once, Earthdata bearer token",
        message=f"{len(df)} months; trend {per_year} cm of water per year ({tr['direction']}, p={tr['p_value']}); "
                f"sanity {'passed' if ok else 'CHECK'}",
        sanity={"checks": checks, "trend": tr, "trend_cm_per_year": per_year},
        outputs=["grace_monthly.parquet"],
        notes="Total water storage (groundwater + soil moisture + surface water + snow) for a region about "
              "300 km across, relative to the 2004-2009 mean. Not a groundwater level and not a field value. "
              "Gain factors were not applied, so the size of the trend is indicative.",
    )


if __name__ == "__main__":
    run_source(SOURCE, TITLE, TIER, main)
