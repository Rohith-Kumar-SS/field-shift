"""The compact per-field weather file the static site ships, and how to read it back.

One file per field: 30 years (the 1996-2025 baseline) of locally corrected daily weather as
little-endian 16-bit integers, variable after variable:

    tmax, tmin, tdew_raw (degC x 100) | wind (m/s x 100) | rs (MJ/m2/day x 100) | precip (mm x 50)

The browser decodes it with an Int16Array; decode() below does the same in Python so the
reference engine can be run on exactly the numbers the browser sees (tests/test_parity.py).
"""
from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

from .climate import BASELINE

VARS = ["tmax", "tmin", "tdew_raw", "wind", "rs", "precip"]
SCALE = {"tmax": 100, "tmin": 100, "tdew_raw": 100, "wind": 100, "rs": 100, "precip": 50}
START = f"{BASELINE[0]}-01-01"


def encode(base: pd.DataFrame) -> tuple[bytes, dict]:
    """base_frame() output -> (bytes, description). Only the baseline years are kept."""
    b = base[(base["date"].dt.year >= BASELINE[0]) & (base["date"].dt.year <= BASELINE[1])].reset_index(drop=True)
    expected = pd.date_range(START, f"{BASELINE[1]}-12-31", freq="D")
    if len(b) != len(expected) or not (b["date"].to_numpy() == expected.to_numpy()).all():
        raise ValueError("daily weather is not a gap-free 1996-2025 record")
    parts = []
    for v in VARS:
        a = np.rint(b[v].to_numpy(float) * SCALE[v])
        if not np.isfinite(a).all() or np.abs(a).max() > 32767:
            raise ValueError(f"{v}: values do not fit the 16-bit weather file")
        parts.append(a.astype("<i2"))
    return np.concatenate(parts).tobytes(), {"start": START, "n": int(len(b)), "vars": VARS,
                                             "scale": [SCALE[v] for v in VARS]}


def decode(path: str | Path, start: str = START) -> pd.DataFrame:
    """Read a weather file back into the frame apply_scenario() expects."""
    raw = np.frombuffer(Path(path).read_bytes(), dtype="<i2")
    n = raw.size // len(VARS)
    out = pd.DataFrame({"date": pd.date_range(start, periods=n, freq="D")})
    for i, v in enumerate(VARS):
        out[v] = raw[i * n:(i + 1) * n].astype("float64") / SCALE[v]
    return out
