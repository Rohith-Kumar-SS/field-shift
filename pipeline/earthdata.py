"""NASA Earthdata helpers: CMR granule listing (public) + cloud OPeNDAP subsetting (token).

Small clips only: instead of downloading whole global files (hundreds of MB each) we ask
NASA's cloud OPeNDAP service (Hyrax, DAP4) for just the handful of grid cells over the
pilot valley. The bearer token is sent only to *.nasa.gov hosts (see common.earthdata_session).
"""
from __future__ import annotations

import threading
import time
from typing import Iterator

import requests

from .common import SourceError, earthdata_session

CMR = "https://cmr.earthdata.nasa.gov/search/granules.umm_json"
_local = threading.local()


def session() -> requests.Session:
    """One authenticated session per worker thread."""
    if not hasattr(_local, "s"):
        _local.s = earthdata_session()
    return _local.s


def list_granules(concept_id: str, temporal: str, bbox: str | None = None) -> Iterator[dict]:
    """Yield {name, start, opendap, https} for every granule of a collection (public CMR)."""
    params = {"collection_concept_id": concept_id, "temporal": temporal, "page_size": 2000,
              "sort_key": "start_date"}
    if bbox:
        params["bounding_box"] = bbox
    headers: dict[str, str] = {}
    while True:
        r = requests.get(CMR, params=params, headers=headers, timeout=120)
        r.raise_for_status()
        items = r.json().get("items", [])
        for it in items:
            u = it["umm"]
            rec = {"name": u["GranuleUR"], "opendap": None, "https": None,
                   "start": u.get("TemporalExtent", {}).get("RangeDateTime", {}).get("BeginningDateTime")}
            for link in u.get("RelatedUrls", []):
                url = link.get("URL", "")
                if link.get("Subtype") == "OPENDAP DATA" or "opendap.earthdata.nasa.gov" in url:
                    rec["opendap"] = url
                elif link.get("Type") == "GET DATA" and url.startswith("https") and not rec["https"]:
                    rec["https"] = url
            yield rec
        after = r.headers.get("CMR-Search-After")
        if not items or not after:
            return
        headers = {"CMR-Search-After": after}


def opendap_subset(opendap_url: str, constraint: str, retries: int = 5, timeout: int = 180) -> bytes:
    """Fetch a DAP4 subset as NetCDF-4 bytes. `constraint` is a dap4.ce expression."""
    url = f"{opendap_url}.dap.nc4"
    last = ""
    for attempt in range(retries):
        try:
            r = session().get(url, params={"dap4.ce": constraint}, timeout=timeout)
        except requests.RequestException as exc:
            last = f"{type(exc).__name__}"
            time.sleep(2 + 3 * attempt)
            continue
        if r.status_code == 200 and r.content[:4] in (b"\x89HDF", b"CDF\x01", b"CDF\x02"):
            return r.content
        if r.status_code in (401, 403):
            raise SourceError(
                f"Earthdata refused the request (HTTP {r.status_code}) at {url.split('/granules/')[0]}",
                action="Log in at https://urs.earthdata.nasa.gov with the account that issued the "
                       "token, open Applications > Authorized Apps > Approve More Applications and "
                       "approve the DAAC apps (GES DISC, NSIDC DAAC, LP DAAC). If the token has "
                       "expired, generate a new one and update EARTHDATA_TOKEN in .env.")
        if r.status_code == 404:
            raise FileNotFoundError(url)
        last = f"HTTP {r.status_code}"
        time.sleep(2 + 3 * attempt)
    raise SourceError(f"OPeNDAP subset failed after {retries} tries ({last}): {url}")


def read_nc(content: bytes):
    """Open NetCDF-4 bytes in memory."""
    import netCDF4

    return netCDF4.Dataset("inmem.nc", memory=content)


def download(url: str, dest, retries: int = 4, timeout: int = 600) -> None:
    """Download a whole (small) granule with the bearer token."""
    last = ""
    for attempt in range(retries):
        try:
            with session().get(url, timeout=timeout, stream=True) as r:
                if r.status_code in (401, 403):
                    raise SourceError(
                        f"Earthdata refused the download (HTTP {r.status_code}): {url.split('?')[0]}",
                        action="Approve the DAAC application for the Earthdata account that issued "
                               "the token (Applications > Authorized Apps), or refresh the token.")
                r.raise_for_status()
                tmp = dest.with_suffix(dest.suffix + ".part")
                with open(tmp, "wb") as fh:
                    for chunk in r.iter_content(1 << 20):
                        fh.write(chunk)
                tmp.replace(dest)
                return
        except SourceError:
            raise
        except Exception as exc:  # noqa: BLE001
            last = f"{type(exc).__name__}: {exc}"
            time.sleep(3 * (attempt + 1))
    raise SourceError(f"Download failed after {retries} tries ({last}): {url.split('?')[0]}")
