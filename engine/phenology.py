"""Cropping pattern from a greenness time series, for places with no crop-type map.

A crop season shows up as a rise and fall in NDVI. Counting the peaks in each year gives
the number of crops grown; the month of each peak says which season it was. This cannot
name the crop: the farmer does that. It can say "two green seasons a year, peaking in
August and February", which is enough to check the rotation the farmer selects.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

MIN_PEAK = 0.40          # a crop canopy, not weeds or stubble
MIN_PROMINENCE = 0.12    # the season must rise clearly above what came before and after
MIN_GAP_DAYS = 64        # two peaks closer than this are one season


def smooth_series(dates: pd.Series, ndvi: pd.Series) -> pd.Series:
    """Regular 16-day series: gaps filled by interpolation, then a light 3-point smooth."""
    s = pd.Series(np.asarray(ndvi, dtype="float64"), index=pd.to_datetime(dates)).sort_index()
    s = s[~s.index.duplicated()].dropna()
    if s.empty:
        return s
    grid = pd.date_range(s.index.min(), s.index.max(), freq="16D")
    u = s.reindex(s.index.union(grid)).interpolate("time", limit=6).reindex(grid)
    return u.rolling(3, center=True, min_periods=1).mean()


def find_seasons(series: pd.Series) -> list[dict]:
    """Peaks that qualify as crop seasons: [{date, year, month, ndvi, prominence}]."""
    v = series.to_numpy()
    idx = series.index
    out: list[dict] = []
    for i in range(1, len(v) - 1):
        if not np.isfinite(v[i]) or v[i] < MIN_PEAK or not (v[i] >= v[i - 1] and v[i] > v[i + 1]):
            continue
        left = v[max(0, i - 8):i]
        right = v[i + 1:i + 9]
        if not (np.isfinite(left).any() and np.isfinite(right).any()):
            continue
        prom = v[i] - max(np.nanmin(left), np.nanmin(right))
        if prom < MIN_PROMINENCE:
            continue
        rec = {"date": idx[i], "year": int(idx[i].year), "month": int(idx[i].month),
               "ndvi": round(float(v[i]), 3), "prominence": round(float(prom), 3)}
        if out and (idx[i] - out[-1]["date"]).days < MIN_GAP_DAYS:
            if rec["ndvi"] > out[-1]["ndvi"]:
                out[-1] = rec
            continue
        out.append(rec)
    return out


def yearly_pattern(dates, ndvi, first_year: int | None = None) -> dict:
    """Seasons per year and the usual peak months.

    Returns {"years": [{year, n_seasons, peak_months, peak_ndvi}], "median_seasons", "usual_peak_months",
    "n_years"}; a year needs at least 12 usable composites to be counted.
    """
    raw = pd.Series(np.asarray(ndvi, dtype="float64"), index=pd.to_datetime(dates)).dropna()
    series = smooth_series(dates, ndvi)
    seasons = find_seasons(series)
    usable = raw.groupby(raw.index.year).size()
    years = []
    for year in sorted(set(series.index.year)):
        if first_year and year < first_year:
            continue
        if usable.get(year, 0) < 12:
            continue
        ss = [s for s in seasons if s["year"] == year]
        years.append({"year": int(year), "n_seasons": len(ss), "peak_months": [s["month"] for s in ss],
                      "peak_ndvi": round(max((s["ndvi"] for s in ss), default=float(series[series.index.year == year].max())), 3)})
    counts = [y["n_seasons"] for y in years]
    months = pd.Series([m for y in years for m in y["peak_months"]], dtype="int64")
    usual = [int(m) for m, c in months.value_counts().items() if c >= max(2, 0.3 * len(years))] if len(months) else []
    return {"years": years, "median_seasons": float(np.median(counts)) if counts else None,
            "usual_peak_months": sorted(usual), "n_years": len(years)}


def history_from_pattern(pattern: dict, n_last: int = 18) -> list[dict]:
    """A year-by-year record in the same shape as the crop-map history, for the app."""
    names = {0: "No crop seen", 1: "One crop", 2: "Two crops", 3: "Three crops"}
    out = []
    for y in pattern["years"][-n_last:]:
        n = y["n_seasons"]
        mon = ", ".join(pd.Timestamp(2001, m, 1).strftime("%b") for m in y["peak_months"])
        out.append({"year": y["year"], "crop": "fallow" if n == 0 else f"seasons_{min(n, 3)}",
                    "label": names.get(min(n, 3), "Three crops"), "n_seasons": n, "peak_months": y["peak_months"],
                    "peak_ndvi": y["peak_ndvi"], "doubtful": False, "kind": "phenology",
                    "cdl_name": "", "share": None,
                    "note": (f"Greenness peaked in {mon}." if mon else "No clear green season in the satellite record.")})
    return out
