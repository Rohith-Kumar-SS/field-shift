"""Minimal OpenET API client with an on-disk cache.

The free tier allows 100 requests a month, so every successful response is cached in
data/raw/openet/ and never requested twice. The API key is sent only to openet-api.org.
"""
from __future__ import annotations

import gzip
import io
import json
import zipfile
from typing import Any

import requests

from .common import SourceError, cache_path, env

BASE = "https://openet-api.org"


def _decode(content: bytes) -> Any:
    """Responses may be plain JSON, gzip, or a zip archive holding one JSON file."""
    if content[:2] == b"\x1f\x8b":
        content = gzip.decompress(content)
    elif content[:2] == b"PK":
        with zipfile.ZipFile(io.BytesIO(content)) as zf:
            content = zf.read(zf.namelist()[0])
    return json.loads(content.decode("utf-8"))


def openet_post(path: str, body: dict, timeout: int = 600) -> Any:
    cache = cache_path("openet", path + json.dumps(body, sort_keys=True), ".json")
    if cache.exists() and cache.stat().st_size > 0:
        return json.loads(cache.read_text(encoding="utf-8"))
    r = requests.post(BASE + path, json=body, headers={"Authorization": env("OPENET_API_KEY")},
                      timeout=timeout)
    if r.status_code in (401, 403):
        raise SourceError(f"OpenET refused the request (HTTP {r.status_code}) for {path}",
                          action="Check OPENET_API_KEY in .env (https://account.etdata.org).")
    if r.status_code == 429 or "quota" in r.text[:300].lower():
        raise SourceError(f"OpenET quota or rate limit reached for {path}: {r.text[:200]}",
                          action="The free tier allows 100 requests a month; wait until the 1st "
                                 "(UTC) or use a higher tier. Cached responses are reused.")
    if r.status_code != 200:
        raise SourceError(f"OpenET HTTP {r.status_code} for {path}: {r.text[:300]}")
    data = _decode(r.content)
    cache.write_text(json.dumps(data), encoding="utf-8")
    return data


def account_limits() -> dict:
    """Quota information only (no identifying fields)."""
    r = requests.get(BASE + "/account/status", headers={"Authorization": env("OPENET_API_KEY")},
                     timeout=60)
    if r.status_code != 200:
        return {}
    keep = ("Tier", "Monthly Requests", "Max Area Acres", "Max Polygons", "Max Field IDS")
    return {k: v for k, v in r.json().items() if k in keep}
