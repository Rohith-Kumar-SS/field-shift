"""Shared fixtures: a small synthetic weather record and field context.

The synthetic data exists only so the unit tests run without the downloaded datasets. It
is never written to data/ and never shown in the app.
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from engine.knowledge import load_kb  # noqa: E402


@pytest.fixture(scope="session")
def kb() -> dict:
    return load_kb()


@pytest.fixture(scope="session")
def daily() -> pd.DataFrame:
    """Thirty years of smooth, cold-desert-like daily weather (deterministic)."""
    dates = pd.date_range("1996-01-01", "2025-12-31", freq="D")
    doy = dates.dayofyear.to_numpy()
    season = np.cos(2 * np.pi * (doy - 200) / 365.25)          # +1 in mid-July
    rng = np.random.default_rng(7)
    noise = rng.normal(0, 2.0, len(dates))
    tmax = 16.0 + 15.0 * season + noise
    tmin = -1.5 + 9.5 * season + noise * 0.6
    return pd.DataFrame({
        "date": dates, "T2M_MAX": tmax, "T2M_MIN": tmin, "T2M": (tmax + tmin) / 2,
        "T2MDEW": tmin - 4.0, "WS2M": 2.6 + 1.4 * np.cos(2 * np.pi * (doy - 90) / 365.25) + rng.normal(0, 0.9, len(dates)),
        "ALLSKY_SFC_SW_DWN": 16.0 + 11.0 * np.cos(2 * np.pi * (doy - 172) / 365.25),
        "PRECTOTCORR": np.where(rng.random(len(dates)) < 0.12, rng.gamma(1.2, 4.5, len(dates)), 0.0),
    })


def make_history(crops: list[str], start: int = 2018) -> list[dict]:
    return [{"year": start + i, "cdl_code": 36, "cdl_name": "Alfalfa", "share": 0.95, "peak_ndvi": 0.85,
             "doubtful": False, "note": "", "crop": c, "label": c} for i, c in enumerate(crops)]


@pytest.fixture()
def ctx(daily) -> dict:
    return {
        "field_id": "T-01", "name": "Test field", "lat": 39.7, "lon": -116.0, "area_ha": 50.0,
        "elevation_m": 1800.0, "slope_pct": 0.3, "is_custom": False,
        "soil": {"om_pct_0_30": 1.2, "ec_dsm_0_30": 1.0, "ph_0_30": 8.0, "sar_0_30": 1.5,
                 "surface_texture": "Fine sandy loam", "wind_erodibility_group": "3",
                 "wind_erodibility_index": 86.0, "kwfact_surface": 0.3},
        "history": make_history(["alfalfa_est"] + ["alfalfa"] * 7),
        "n_doubtful_years": 0, "water_factor": 1.0, "water_factor_info": {"available": False},
        "landsat": {"low_cover_share_peak_months": 0.4},
        "groundwater": {"n_wells_trend": 4, "n_deepening": 3, "median_m_per_decade": 3.0},
        "trends": {"days_over_32": {"significant": False}},
        "sources": {"power": True, "openet": True, "landsat": True, "ssurgo": True, "cdl": True,
                    "smap": True, "imerg": False},
        "climate_correction": "lapse",
        "power": {"daily": daily, "grid_elevation_m": 1800.0},
    }
