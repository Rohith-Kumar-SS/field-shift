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
    return load_kb("diamond_valley_nv")


@pytest.fixture(scope="session")
def kb_pb() -> dict:
    return load_kb("punjab_sangrur")


@pytest.fixture(scope="session")
def kb_tn() -> dict:
    return load_kb("cauvery_delta_tn")


@pytest.fixture(scope="session")
def daily_monsoon() -> pd.DataFrame:
    """Twenty-five years of hot, monsoon-plain-like daily weather (deterministic)."""
    dates = pd.date_range("2001-01-01", "2025-12-31", freq="D")
    doy = dates.dayofyear.to_numpy()
    season = np.cos(2 * np.pi * (doy - 165) / 365.25)          # +1 in mid-June
    rng = np.random.default_rng(11)
    noise = rng.normal(0, 1.5, len(dates))
    tmax = 31.0 + 9.5 * season + noise
    tmin = 17.0 + 10.0 * season + noise * 0.6
    wet = (doy > 175) & (doy < 265)                             # July to mid-September
    rain = np.where(rng.random(len(dates)) < np.where(wet, 0.35, 0.04), rng.gamma(1.1, 16.0, len(dates)), 0.0)
    return pd.DataFrame({
        "date": dates, "T2M_MAX": tmax, "T2M_MIN": tmin, "T2M": (tmax + tmin) / 2,
        "T2MDEW": tmin - np.where(wet, 1.5, 7.0), "WS2M": 1.8 + rng.normal(0, 0.5, len(dates)).clip(-1.2, 3),
        "ALLSKY_SFC_SW_DWN": 18.0 + 6.0 * np.cos(2 * np.pi * (doy - 150) / 365.25) - np.where(wet, 3.0, 0.0),
        "PRECTOTCORR": rain,
    })


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
        "groundwater": {"kind": "wells", "n_wells_trend": 4, "n_deepening": 3, "median_m_per_decade": 3.0},
        "trends": {"hot_days": {"significant": False}},
        "sources": {"power": True, "ground": False, "et": True, "landsat": True, "soil": True, "history": True,
                    "smap": True, "imerg": False, "srtm": True, "modis": True, "groundwater": True},
        "soil_source": "ssurgo", "climate_correction": "lapse",
        "power": {"daily": daily, "grid_elevation_m": 1800.0},
    }


@pytest.fixture()
def ctx_india(daily_monsoon) -> dict:
    """A 9 ha sample plot on the Punjab plain: no crop map, SoilGrids soil, GRACE water trend."""
    return {
        "field_id": "PB-T1", "name": "Test plot", "lat": 30.28, "lon": 75.68, "area_ha": 9.0,
        "elevation_m": 232.0, "slope_pct": 0.1, "is_custom": False,
        "soil": {"om_pct_0_30": 0.8, "ec_dsm_0_30": None, "ph_0_30": 7.9, "sar_0_30": None,
                 "surface_texture": "Loam", "wind_erodibility_group": "5",
                 "wind_erodibility_index": 56.0, "kwfact_surface": 0.32, "clay_pct_0_30": 22.0},
        "history": [{"year": y, "crop": "seasons_2", "label": "Two crops", "n_seasons": 2, "peak_months": [2, 8],
                     "peak_ndvi": 0.8, "doubtful": False, "kind": "phenology", "note": ""} for y in range(2016, 2026)],
        "phenology": {"median_seasons": 2.0, "usual_peak_months": [2, 8], "n_years": 10},
        "n_doubtful_years": 0, "water_factor": 1.0, "water_factor_info": {"available": False},
        "landsat": {"low_cover_share_peak_months": 0.1},
        "groundwater": {"kind": "grace", "trend_cm_per_year": -3.8, "significant": True, "from_year": 2002},
        "trends": {"hot_days": {"significant": False}},
        "sources": {"power": True, "ground": True, "et": True, "landsat": True, "soil": True, "history": True,
                    "smap": True, "imerg": True, "srtm": True, "modis": True, "groundwater": True},
        "soil_source": "soilgrids", "climate_correction": "imd",
        "power": {"daily": daily_monsoon, "grid_elevation_m": 232.0},
    }
