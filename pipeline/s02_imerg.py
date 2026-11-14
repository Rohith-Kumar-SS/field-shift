"""GPM IMERG daily precipitation (MUST tier). Needs EARTHDATA_TOKEN **and** the GES DISC
data-use agreement accepted on the Earthdata account that issued the token.

Product: GPM_3IMERGDF v07 (IMERG Final Run, daily, 0.1 degree, mm/day).

Small clips only: each daily file is ~28 MB of global data. Instead of downloading it we
open it remotely (HTTP range requests) and read only the HDF5 chunk that holds the
valley's four 0.1-degree cells.

Outputs
  data/raw/imerg/imerg_<year>.parquet          (cache, one file per year)
  data/processed/imerg_cell_daily.parquet      daily precipitation + IMERG's own random error
  data/processed/field_imerg_cell.json         which cell each field falls in

If the account has not accepted the agreement, GES DISC answers HTTP 403 "EULA Acceptance
Failure". The script records that with the exact approval link and writes NO data: the app
then shows rainfall from NASA POWER, labelled as such, and marks IMERG as pending.
"""
from __future__ import annotations

import json
import math
from concurrent.futures import ThreadPoolExecutor, as_completed

import numpy as np
import pandas as pd
import requests

from .common import PILOT, PROCESSED, RAW, SourceError, load_fields, run_source, sanity_range, write_status
from .earthdata import list_granules, session

SOURCE, TITLE, TIER = "gpm_imerg", "GPM IMERG Final Run daily precipitation (GPM_3IMERGDF v07)", "MUST"
SHORT_NAME = "GPM_3IMERGDF"
START, END = "2001-01-01", "2025-12-31"
APPROVE_HELP = ("Sign in at https://urs.earthdata.nasa.gov with the account that issued "
                "EARTHDATA_TOKEN, then open {url} and approve 'NASA GESDISC DATA ARCHIVE' "
                "(Applications > Authorized Apps > Approve More Applications). No new token is "
                "needed. Then run `python -m pipeline.s02_imerg` and `python -m pipeline.s20_indicators`.")
DEFAULT_APPROVE_URL = "https://urs.earthdata.nasa.gov/approve_app?client_id=e2WVk8Pw6weeLUKZYOxvTQ"


def collection_id() -> str:
    r = requests.get("https://cmr.earthdata.nasa.gov/search/collections.umm_json",
                     params={"short_name": SHORT_NAME, "page_size": 20}, timeout=120)
    r.raise_for_status()
    items = r.json().get("items", [])
    if not items:
        raise SourceError(f"{SHORT_NAME} not found in NASA CMR")
    return max(items, key=lambda it: it["umm"]["Version"])["meta"]["concept-id"]


def cell_window(bbox) -> tuple[int, int, int, int]:
    """IMERG 0.1-degree index range (lon index from -180, lat index from -90)."""
    w, s, e, n = bbox
    i0, i1 = math.floor((w + 180) / 0.1), math.floor((e + 180) / 0.1)
    j0, j1 = math.floor((s + 90) / 0.1), math.floor((n + 90) / 0.1)
    return i0, i1, j0, j1


def resolve(url: str) -> str:
    """Follow NASA's redirects to the time-limited download link (no body is downloaded)."""
    for _ in range(6):
        r = session().get(url, timeout=120, allow_redirects=False, stream=True)
        try:
            if r.status_code in (301, 302, 303, 307, 308):
                url = r.headers["Location"]
                host = requests.utils.urlparse(url).hostname or ""
                if not host.endswith(".nasa.gov"):
                    return url
                continue
            if r.status_code in (401, 403):
                link = DEFAULT_APPROVE_URL
                try:
                    link = r.json().get("resolution_url") or link
                    reason = r.json().get("error_description", "not authorised")
                except ValueError:
                    reason = "not authorised"
                raise SourceError(f"GES DISC refused the download: HTTP {r.status_code} ({reason})",
                                  action=APPROVE_HELP.format(url=link))
            if r.status_code == 200:
                return url
            raise SourceError(f"GES DISC HTTP {r.status_code} while resolving a daily file")
        finally:
            r.close()
    raise SourceError("Too many redirects resolving a GES DISC download link")


def read_day(gran: dict, win) -> list[dict]:
    import fsspec
    import h5py

    i0, i1, j0, j1 = win
    signed = resolve(gran["https"])
    fs = fsspec.filesystem("https")
    with fs.open(signed, block_size=256 * 1024, cache_type="blockcache") as fh:
        with h5py.File(fh, "r") as h5:
            grp = h5["Grid"] if "Grid" in h5 else h5
            p = np.asarray(grp["precipitation"][0, i0:i1 + 1, j0:j1 + 1], dtype="float64")
            err = np.asarray(grp["randomError"][0, i0:i1 + 1, j0:j1 + 1], dtype="float64")
            lon = np.asarray(grp["lon"][i0:i1 + 1], dtype="float64")
            lat = np.asarray(grp["lat"][j0:j1 + 1], dtype="float64")
    p[p < 0] = np.nan
    err[err < 0] = np.nan
    day = gran["start"][:10]
    return [{"date": day, "lon_idx": i0 + a, "lat_idx": j0 + b, "lon": round(float(lon[a]), 2),
             "lat": round(float(lat[b]), 2), "precip_mm": p[a, b], "random_error_mm": err[a, b]}
            for a in range(p.shape[0]) for b in range(p.shape[1])]


def fetch_all(workers: int = 12) -> tuple[pd.DataFrame, list[str]]:
    cid = collection_id()
    win = cell_window(PILOT["bbox"])
    out_dir = RAW / "imerg"
    out_dir.mkdir(parents=True, exist_ok=True)
    frames, failed = [], []
    probed = False
    for year in range(int(START[:4]), int(END[:4]) + 1):
        cache = out_dir / f"imerg_{year}.parquet"
        if cache.exists():
            frames.append(pd.read_parquet(cache))
            continue
        grans = {g["start"][:10]: g for g in
                 list_granules(cid, f"{year}-01-01T00:00:00Z,{year}-12-31T23:59:59Z") if g["https"]}
        if not grans:
            continue
        if not probed:      # one request first: fail fast (and clearly) if access is not approved
            first = next(iter(grans.values()))
            read_day(first, win)
            probed = True
        rows, year_failed = [], []
        with ThreadPoolExecutor(max_workers=workers) as ex:
            futs = {ex.submit(read_day, g, win): d for d, g in grans.items()}
            for fut in as_completed(futs):
                try:
                    rows.extend(fut.result())
                except SourceError as exc:
                    if exc.action:
                        raise
                    year_failed.append(futs[fut])
                except Exception:  # noqa: BLE001
                    year_failed.append(futs[fut])
        df = pd.DataFrame(rows)
        print(f"  imerg {year}: {len(grans)} daily files, {len(year_failed)} failed", flush=True)
        failed += year_failed
        if not df.empty and len(year_failed) <= 0.02 * len(grans):
            df.to_parquet(cache, index=False)
        frames.append(df)
    frames = [f for f in frames if not f.empty]
    return (pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()), failed


def main() -> None:
    fields = load_fields()
    data, failed = fetch_all()
    if data.empty:
        raise SourceError("IMERG returned no data for the pilot valley")
    data["date"] = pd.to_datetime(data["date"])
    data["cell_id"] = "G" + data["lon_idx"].astype(str) + "_" + data["lat_idx"].astype(str)
    data = data.sort_values(["cell_id", "date"])
    data.to_parquet(PROCESSED / "imerg_cell_daily.parquet", index=False)

    mapping = {}
    for _, f in fields.iterrows():
        c = f.geometry.centroid
        mapping[f["field_id"]] = f"G{math.floor((c.x + 180) / 0.1)}_{math.floor((c.y + 90) / 0.1)}"
    (PROCESSED / "field_imerg_cell.json").write_text(json.dumps(mapping, indent=2), encoding="utf-8")

    annual = data.groupby(["cell_id", data["date"].dt.year])["precip_mm"].sum()
    checks = [sanity_range(data["precip_mm"].dropna(), 0, 200, "daily precipitation mm"),
              sanity_range(annual[annual.index.get_level_values(1) < 2025], 80, 700, "annual total mm")]
    ok = all(c["passed"] for c in checks) and set(mapping.values()) <= set(data["cell_id"])
    write_status(
        SOURCE, status="ok" if (ok and len(failed) < 60) else "partial", title=TITLE, tier=TIER,
        fetched=f"{data['date'].nunique():,} daily files, {data['cell_id'].nunique()} cells of 0.1 degree "
                "over the valley (precipitation and randomError)",
        resolution="0.1 degree (~9 x 11 km here); daily accumulation from half-hourly estimates",
        date_range=f"{data['date'].min():%Y-%m-%d} to {data['date'].max():%Y-%m-%d}",
        credit="Huffman, G. J. et al. (2023). GPM IMERG Final Precipitation L3 1 day 0.1 degree x 0.1 "
               "degree V07. NASA Goddard Earth Sciences Data and Information Services Center (GES DISC).",
        access="GES DISC archive (data.gesdisc.earthdata.nasa.gov), remote HDF5 range reads, "
               "Earthdata bearer token",
        message=f"{data['date'].nunique():,} days; {len(failed)} daily files failed; "
                f"sanity {'passed' if ok else 'CHECK'}",
        sanity={"checks": checks, "grid": "0.1 degree lon/lat", "failed_days": failed[:30]},
        outputs=["imerg_cell_daily.parquet", "field_imerg_cell.json"],
        notes="A satellite estimate calibrated to monthly gauge totals, not a rain gauge: it can "
              "miss or misplace small summer thunderstorms and struggles with snowfall over "
              "mountains. One cell covers many fields.",
    )


if __name__ == "__main__":
    run_source(SOURCE, TITLE, TIER, main)
