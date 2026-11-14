"""Agro-meteorological building blocks (pure functions, unit-tested).

Everything here is a published, transparent method:

* Reference evapotranspiration: FAO Irrigation & Drainage Paper 56 (Allen et al. 1998),
  Penman-Monteith, eq. 6 with the supporting equations 7-39.
* Effective precipitation: USDA-SCS monthly method (NRCS National Engineering Handbook,
  Part 623, Chapter 2, eq. 2-84), 75 mm soil-storage factor.
* Trends: Theil-Sen slope with a Mann-Kendall (Kendall tau) significance test.
"""
from __future__ import annotations

import math
from typing import Iterable

import numpy as np

# Standard environmental lapse rate used to move gridded temperature from the grid
# cell's mean elevation to the field's elevation (degC per metre).
LAPSE_RATE = 0.0065


# ---------------------------------------------------------------------------
# FAO-56 Penman-Monteith reference evapotranspiration
# ---------------------------------------------------------------------------
def sat_vapour_pressure(t_c):
    """Saturation vapour pressure, kPa (FAO-56 eq. 11)."""
    t_c = np.asarray(t_c, dtype="float64")
    return 0.6108 * np.exp(17.27 * t_c / (t_c + 237.3))


def extraterrestrial_radiation(lat_deg: float, doy):
    """Daily extraterrestrial radiation Ra, MJ m-2 day-1 (FAO-56 eq. 21)."""
    doy = np.asarray(doy, dtype="float64")
    phi = math.radians(lat_deg)
    dr = 1 + 0.033 * np.cos(2 * np.pi * doy / 365.0)
    delta = 0.409 * np.sin(2 * np.pi * doy / 365.0 - 1.39)
    ws = np.arccos(np.clip(-np.tan(phi) * np.tan(delta), -1.0, 1.0))
    gsc = 0.0820
    return (24 * 60 / np.pi) * gsc * dr * (
        ws * np.sin(phi) * np.sin(delta) + np.cos(phi) * np.cos(delta) * np.sin(ws)
    )


def et0_fao56(tmax, tmin, tdew, wind2m, rs, lat_deg: float, elev_m: float, doy):
    """Daily grass reference ET (mm/day), FAO-56 Penman-Monteith.

    tmax, tmin, tdew : degC
    wind2m           : wind speed at 2 m, m/s
    rs               : incoming shortwave radiation, MJ m-2 day-1
    """
    tmax = np.asarray(tmax, dtype="float64")
    tmin = np.asarray(tmin, dtype="float64")
    tdew = np.asarray(tdew, dtype="float64")
    u2 = np.asarray(wind2m, dtype="float64")
    rs = np.asarray(rs, dtype="float64")

    tmean = (tmax + tmin) / 2.0
    pressure = 101.3 * ((293.0 - 0.0065 * elev_m) / 293.0) ** 5.26          # eq. 7
    gamma = 0.000665 * pressure                                              # eq. 8
    delta = 4098.0 * sat_vapour_pressure(tmean) / (tmean + 237.3) ** 2       # eq. 13
    es = (sat_vapour_pressure(tmax) + sat_vapour_pressure(tmin)) / 2.0       # eq. 12
    ea = np.minimum(sat_vapour_pressure(tdew), es)                           # eq. 14

    ra = extraterrestrial_radiation(lat_deg, doy)
    rso = (0.75 + 2e-5 * elev_m) * ra                                        # eq. 37
    rns = (1 - 0.23) * rs                                                    # eq. 38
    sigma = 4.903e-9
    rel = np.clip(np.where(rso > 0, rs / np.where(rso > 0, rso, 1.0), 0.0), 0.0, 1.0)
    rnl = (
        sigma
        * ((tmax + 273.16) ** 4 + (tmin + 273.16) ** 4) / 2.0
        * (0.34 - 0.14 * np.sqrt(np.maximum(ea, 0.0)))
        * (1.35 * rel - 0.35)
    )                                                                        # eq. 39
    rn = rns - rnl
    num = 0.408 * delta * rn + gamma * (900.0 / (tmean + 273.0)) * u2 * (es - ea)
    den = delta + gamma * (1 + 0.34 * u2)
    return np.maximum(num / den, 0.0)                                        # eq. 6


# ---------------------------------------------------------------------------
# Effective precipitation (USDA-SCS monthly method)
# ---------------------------------------------------------------------------
def effective_precip_usda(p_mm, etc_mm):
    """Monthly effective precipitation in mm (USDA-SCS, 75 mm storage, SF = 1.0).

    Never more than the rain that fell, and never more than the crop could use.
    """
    p = np.asarray(p_mm, dtype="float64")
    etc = np.asarray(etc_mm, dtype="float64")
    p_in = np.maximum(p, 0.0) / 25.4
    etc_in = np.maximum(etc, 0.0) / 25.4
    pe_in = (0.70917 * np.power(p_in, 0.82416) - 0.11556) * np.power(10.0, 0.02426 * etc_in)
    pe = np.maximum(pe_in, 0.0) * 25.4
    return np.minimum(np.minimum(pe, p), etc)


# ---------------------------------------------------------------------------
# Frost, heat and growing-season indicators (per year, from daily series)
# ---------------------------------------------------------------------------
def frost_dates(doy: Iterable[int], tmin: Iterable[float], threshold_c: float = 0.0,
                midsummer_doy: int = 196):
    """Last spring frost DOY, first autumn frost DOY and frost-free days for one year.

    Returns (last_spring, first_fall, frost_free_days). If no frost occurs on one side
    of midsummer the year boundary (1 or 366) is used.
    """
    doy = np.asarray(list(doy), dtype="int64")
    tmin = np.asarray(list(tmin), dtype="float64")
    frost = tmin <= threshold_c
    spring = doy[(doy < midsummer_doy) & frost]
    fall = doy[(doy >= midsummer_doy) & frost]
    last_spring = int(spring.max()) if spring.size else 1
    first_fall = int(fall.min()) if fall.size else 366
    return last_spring, first_fall, int(max(first_fall - last_spring - 1, 0))


def count_days_above(values, threshold: float) -> int:
    v = np.asarray(list(values), dtype="float64")
    return int(np.nansum(v > threshold))


def count_days_below(values, threshold: float) -> int:
    v = np.asarray(list(values), dtype="float64")
    return int(np.nansum(v < threshold))


def growing_degree_days(tmax, tmin, base_c: float = 5.0, cap_c: float = 30.0) -> float:
    tmax = np.minimum(np.asarray(tmax, dtype="float64"), cap_c)
    tmin = np.maximum(np.asarray(tmin, dtype="float64"), base_c)
    return float(np.nansum(np.maximum((tmax + tmin) / 2.0 - base_c, 0.0)))


# ---------------------------------------------------------------------------
# Statistics
# ---------------------------------------------------------------------------
def theil_sen_trend(years, values) -> dict:
    """Robust linear trend with Mann-Kendall significance.

    Returns slope per decade, p-value, and a plain-language direction that is only
    'increasing'/'decreasing' when p < 0.05 (otherwise 'no clear trend').
    """
    from scipy import stats

    x = np.asarray(list(years), dtype="float64")
    y = np.asarray(list(values), dtype="float64")
    ok = np.isfinite(x) & np.isfinite(y)
    x, y = x[ok], y[ok]
    if x.size < 8 or np.allclose(y, y[0]):
        return {"n": int(x.size), "slope_per_decade": None, "p_value": None,
                "direction": "not enough data", "significant": False}
    slope, intercept, lo, hi = stats.theilslopes(y, x, 0.95)
    tau, p = stats.kendalltau(x, y)
    sig = bool(p < 0.05)
    direction = "no clear trend"
    if sig:
        direction = "increasing" if slope > 0 else "decreasing"
    return {
        "n": int(x.size),
        "slope_per_decade": round(float(slope) * 10, 4),
        "slope_ci95_per_decade": [round(float(lo) * 10, 4), round(float(hi) * 10, 4)],
        "intercept": round(float(intercept), 4),
        "kendall_tau": round(float(tau), 3),
        "p_value": round(float(p), 4),
        "significant": sig,
        "direction": direction,
    }


def monthly_zscore(values, months, min_years: int = 4):
    """Standardised anomaly of each value against its own calendar month.

    z = (x - mean_month) / std_month. Months with fewer than `min_years` values or zero
    spread return NaN rather than a misleading number.
    """
    v = np.asarray(list(values), dtype="float64")
    m = np.asarray(list(months), dtype="int64")
    out = np.full(v.shape, np.nan)
    for month in range(1, 13):
        sel = (m == month) & np.isfinite(v)
        if sel.sum() < min_years:
            continue
        mu, sd = v[sel].mean(), v[sel].std(ddof=1)
        if sd > 0:
            out[sel] = (v[sel] - mu) / sd
    return out


def lapse_adjust(temp_c, grid_elev_m: float, field_elev_m: float):
    """Move a gridded temperature from the grid-cell elevation to the field elevation."""
    return np.asarray(temp_c, dtype="float64") + LAPSE_RATE * (grid_elev_m - field_elev_m)
