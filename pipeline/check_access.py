"""Check that each credential/service works, without ever printing a secret.

    python -m pipeline.check_access
"""
from __future__ import annotations

import json
import os

import requests

from .common import SourceError, earthdata_session, env

REDACT = ("key", "token", "email", "name", "user", "id", "secret")


def _safe(obj):
    """Drop anything that could identify the account or leak a credential."""
    if isinstance(obj, dict):
        return {k: ("<redacted>" if any(w in k.lower() for w in REDACT) else _safe(v))
                for k, v in obj.items()}
    if isinstance(obj, list):
        return [_safe(v) for v in obj][:20]
    return obj


def check_openet() -> None:
    r = requests.get("https://openet-api.org/account/status",
                     headers={"Authorization": env("OPENET_API_KEY")}, timeout=60)
    print("OpenET account/status ->", r.status_code)
    if r.ok:
        try:
            print(json.dumps(_safe(r.json()), indent=2)[:1500])
        except ValueError:
            print("  (non-JSON response, %d bytes)" % len(r.content))


def check_earthdata() -> None:
    s = earthdata_session()
    tests = {
        "CMR (public search)": "https://cmr.earthdata.nasa.gov/search/collections.json?short_name=GPM_3IMERGDF&page_size=1",
        "GES DISC OPeNDAP (IMERG daily)": (
            "https://gpm1.gesdisc.eosdis.nasa.gov/opendap/GPM_L3/GPM_3IMERGDF.07/2023/01/"
            "3B-DAY.MS.MRG.3IMERG.20230101-S000000-E235959.V07B.nc4.dds"
        ),
    }
    for label, url in tests.items():
        try:
            r = s.get(url, timeout=90)
            print(f"Earthdata · {label} -> {r.status_code} ({len(r.content)} bytes)")
        except Exception as exc:  # noqa: BLE001
            print(f"Earthdata · {label} -> ERROR {type(exc).__name__}: {exc}")


def check_gee() -> None:
    try:
        import ee

        ee.Initialize(project=os.environ.get("GEE_PROJECT_ID"))
        print("Earth Engine -> OK")
    except Exception as exc:  # noqa: BLE001
        msg = str(exc).splitlines()[0][:160]
        print(f"Earth Engine -> NOT READY ({type(exc).__name__}: {msg})")
        print("  action: run `earthengine authenticate` in a terminal, then re-run the pipeline.")


def check_public() -> None:
    tests = {
        "NASA POWER": "https://power.larc.nasa.gov/api/temporal/daily/point?parameters=T2M&community=AG&longitude=-115.98&latitude=39.69&start=20240101&end=20240103&format=JSON",
        "USDA Soil Data Access": "https://sdmdataaccess.sc.egov.usda.gov/",
        "CropScape": "https://nassgeodata.gmu.edu/CropScape/",
        "Planetary Computer STAC": "https://planetarycomputer.microsoft.com/api/stac/v1/collections/landsat-c2-l2",
    }
    for label, url in tests.items():
        try:
            r = requests.get(url, timeout=60)
            print(f"{label} -> {r.status_code}")
        except Exception as exc:  # noqa: BLE001
            print(f"{label} -> ERROR {type(exc).__name__}: {str(exc)[:120]}")


def main() -> None:
    for fn in (check_public, check_openet, check_earthdata, check_gee):
        try:
            fn()
        except SourceError as exc:
            print(f"{fn.__name__}: {exc} | action: {exc.action}")
        print("-" * 60)


if __name__ == "__main__":
    main()
