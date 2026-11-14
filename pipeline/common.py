"""Shared helpers for the Field Shift data pipeline.

Secrets policy: credentials are read from `.env` with python-dotenv and are only ever
placed in the request header of the service they belong to. Nothing in this module
prints, logs or writes a credential value.
"""
from __future__ import annotations

import hashlib
import json
import os
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import requests
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]
RAW = ROOT / "data" / "raw"
PROCESSED = ROOT / "data" / "processed"
STATUS_DIR = PROCESSED / "_status"
OVERLAYS = PROCESSED / "overlays"

load_dotenv(ROOT / ".env")

# ---------------------------------------------------------------------------
# Pilot region: Diamond Valley, Eureka County, Nevada (irrigated alfalfa pivots)
# ---------------------------------------------------------------------------
PILOT = {
    "id": "diamond_valley_nv",
    "name": "Diamond Valley, Eureka County, Nevada",
    # west, south, east, north (WGS84). Covers the irrigated southern valley floor.
    "bbox": [-116.08, 39.58, -115.88, 39.80],
    "centroid": [-115.98, 39.69],
    "utm_epsg": 32611,  # UTM zone 11N
    "timezone": "America/Los_Angeles",
}

# Analysis windows
CLIMATE_START, CLIMATE_END = 1991, 2025          # NASA POWER long record (trends)
FIELD_EO_START, FIELD_EO_END = 2018, 2025        # field-scale satellite record
CDL_START, CDL_END = 2008, 2025                  # crop history
GROWING_MONTHS = [4, 5, 6, 7, 8, 9, 10]          # April-October


class SourceError(RuntimeError):
    """A data source could not be fetched. `action` tells the user what to do."""

    def __init__(self, message: str, action: str = ""):
        super().__init__(message)
        self.action = action


def ensure_dirs() -> None:
    for d in (RAW, PROCESSED, STATUS_DIR, OVERLAYS):
        d.mkdir(parents=True, exist_ok=True)


def env(name: str) -> str:
    """Return a credential from the environment, or raise without echoing anything."""
    val = os.environ.get(name, "").strip()
    if not val:
        raise SourceError(
            f"{name} is not set",
            action=f"Add {name} to the .env file in the project root (see .env.example).",
        )
    return val


def earthdata_headers() -> dict[str, str]:
    return {"Authorization": f"Bearer {env('EARTHDATA_TOKEN')}"}


def earthdata_session() -> requests.Session:
    """Session that sends the Earthdata bearer token ONLY to NASA Earthdata hosts.

    `requests` drops the Authorization header on cross-host redirects, which is what we
    want for third-party hosts, but NASA DAAC downloads legitimately redirect between
    *.earthdata.nasa.gov / *.nasa.gov hosts, so we re-attach it for those only.
    """
    token = env("EARTHDATA_TOKEN")

    class _S(requests.Session):
        def rebuild_auth(self, prepared_request, response):  # noqa: D401
            super().rebuild_auth(prepared_request, response)
            host = requests.utils.urlparse(prepared_request.url).hostname or ""
            if host.endswith(".nasa.gov") or host.endswith(".earthdatacloud.nasa.gov"):
                prepared_request.headers["Authorization"] = f"Bearer {token}"
            else:
                prepared_request.headers.pop("Authorization", None)

    s = _S()
    s.headers["Authorization"] = f"Bearer {token}"
    s.headers["User-Agent"] = "field-shift-pipeline/1.0"
    return s


def cache_path(source: str, key: str, suffix: str = ".json") -> Path:
    """Deterministic cache file for a request key (never contains secrets)."""
    digest = hashlib.sha1(key.encode("utf-8")).hexdigest()[:16]
    d = RAW / source
    d.mkdir(parents=True, exist_ok=True)
    return d / f"{digest}{suffix}"


def cached_get(
    source: str,
    url: str,
    params: dict[str, Any] | None = None,
    *,
    session: requests.Session | None = None,
    suffix: str = ".json",
    timeout: int = 120,
    retries: int = 4,
    binary: bool = False,
    key_extra: str = "",
) -> Path:
    """GET with an on-disk cache in data/raw/<source>/. Returns the cached file path."""
    key = url + "?" + json.dumps(params or {}, sort_keys=True) + key_extra
    path = cache_path(source, key, suffix)
    if path.exists() and path.stat().st_size > 0:
        return path
    sess = session or requests
    last: Exception | None = None
    for attempt in range(retries):
        try:
            r = sess.get(url, params=params, timeout=timeout)
            if r.status_code in (401, 403):
                raise SourceError(
                    f"{source}: HTTP {r.status_code} (not authorised) for {url.split('?')[0]}",
                    action="Check the credential and the account approvals for this service.",
                )
            if r.status_code == 404:
                raise FileNotFoundError(f"{source}: 404 for {url}")
            r.raise_for_status()
            tmp = path.with_suffix(path.suffix + ".part")
            tmp.write_bytes(r.content) if binary else tmp.write_text(r.text, encoding="utf-8")
            tmp.replace(path)
            return path
        except (SourceError, FileNotFoundError):
            raise
        except Exception as exc:  # network hiccup: back off and retry
            last = exc
            time.sleep(2 * (attempt + 1))
    raise SourceError(f"{source}: request failed after {retries} tries: {type(last).__name__}: {last}")


def write_status(
    source: str,
    *,
    status: str,
    title: str,
    fetched: str = "",
    resolution: str = "",
    date_range: str = "",
    credit: str = "",
    access: str = "",
    message: str = "",
    action_needed: str = "",
    sanity: dict[str, Any] | None = None,
    outputs: list[str] | None = None,
    is_demo_data: bool = False,
    tier: str = "",
    notes: str = "",
) -> None:
    """Record what happened for one source. DATA_LOG.md and the UI are built from these."""
    ensure_dirs()
    rec = {
        "source": source,
        "title": title,
        "tier": tier,
        "status": status,  # ok | partial | failed | skipped
        "fetched": fetched,
        "resolution": resolution,
        "date_range": date_range,
        "credit": credit,
        "access": access,
        "message": message,
        "action_needed": action_needed,
        "sanity": sanity or {},
        "outputs": outputs or [],
        "is_demo_data": is_demo_data,
        "notes": notes,
        "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
    }
    (STATUS_DIR / f"{source}.json").write_text(json.dumps(rec, indent=2), encoding="utf-8")
    flag = {"ok": "OK ", "partial": "PART", "failed": "FAIL", "skipped": "SKIP"}.get(status, status)
    print(f"[{flag}] {title}: {message}")
    if action_needed:
        print(f"       action needed: {action_needed}")


def sanity_range(values, lo: float, hi: float, name: str) -> dict[str, Any]:
    """Plausibility check: finite share, min/max and whether all values sit in [lo, hi]."""
    import numpy as np

    arr = np.asarray(list(values), dtype="float64")
    finite = arr[np.isfinite(arr)]
    out: dict[str, Any] = {
        "variable": name,
        "n": int(arr.size),
        "n_finite": int(finite.size),
        "all_nan": bool(finite.size == 0),
        "expected_range": [lo, hi],
    }
    if finite.size:
        out.update(
            min=round(float(finite.min()), 4),
            max=round(float(finite.max()), 4),
            mean=round(float(finite.mean()), 4),
            in_range=bool(finite.min() >= lo and finite.max() <= hi),
        )
    else:
        out["in_range"] = False
    out["passed"] = bool(out["in_range"] and not out["all_nan"])
    return out


def load_fields():
    """Pilot field polygons (EPSG:4326) written by pipeline/00_fields.py."""
    import geopandas as gpd

    path = PROCESSED / "fields.geojson"
    if not path.exists():
        raise SourceError("fields.geojson missing", action="Run pipeline/s00_fields.py first.")
    return gpd.read_file(path)


def run_source(source: str, title: str, tier: str, fn) -> bool:
    """Run one source's main(); on failure record it and keep the pipeline going."""
    ensure_dirs()
    try:
        fn()
        return True
    except SourceError as exc:
        write_status(source, status="failed", title=title, tier=tier, message=str(exc),
                     action_needed=exc.action)
    except Exception as exc:  # unexpected: record, do not crash run_all
        write_status(source, status="failed", title=title, tier=tier,
                     message=f"{type(exc).__name__}: {exc}")
    return False
