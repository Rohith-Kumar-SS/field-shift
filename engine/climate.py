"""Field climate summary from the NASA POWER daily record, with scenario adjustments.

The same function serves the precomputed "current conditions" panels and the live
scenario sliders, so what the farmer sees and what the scores use cannot drift apart.

Scenario method (deliberately simple and stated in the UI):
  * temperature change: added to every day's Tmax and Tmin. Dew point is left as
    observed, i.e. the air holds the same water vapour, so warming raises the vapour-
    pressure deficit and with it reference ET. This is a sensitivity test, not a
    climate projection.
  * rainfall change: every day's precipitation is scaled by the same percentage.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

from .agromet import LAPSE_RATE, et0_fao56, frost_dates

BASELINE = (1996, 2025)          # 30-year window for "normal" conditions
HEAT_THRESHOLDS = (30, 32, 35, 36, 38, 40, 42)
WINDY_MS = 4.5                   # daily-mean wind at 2 m; ~6.5 m/s at 10 m, enough to move loose sand
HEAVY_RAIN_MM = 10.0             # heavy for a 250 mm/yr cold desert; monsoon regions set 50 in their settings
MONTHS = list(range(1, 13))


@dataclass(frozen=True)
class Scenario:
    rain_pct: float = 0.0
    temp_c: float = 0.0

    def clamp(self) -> "Scenario":
        return Scenario(rain_pct=float(np.clip(self.rain_pct, -50, 50)),
                        temp_c=float(np.clip(self.temp_c, -2, 5)))


def _monthly_lookup(table: dict, month: np.ndarray) -> np.ndarray:
    """Per-day values from a {month: value} table whose keys may be ints or strings."""
    vals = np.array([float(table.get(str(m), table.get(m, 0.0))) for m in range(1, 13)])
    return vals[month - 1]


def field_precip(power_daily: pd.DataFrame, imerg: pd.DataFrame | None, bias: dict | None) -> pd.Series | None:
    """Daily rainfall for a field: GPM IMERG where it exists, corrected NASA POWER elsewhere.

    Both are scaled month by month to gridMET's normals when a correction table is given
    (`imerg_precip_ratio` for IMERG, `precip_ratio` for NASA POWER), so the series does not
    jump where one source hands over to the other. Returns None when there is no IMERG
    record, in which case prepare_daily uses NASA POWER on its own.
    """
    if imerg is None or len(imerg) == 0:
        return None
    dates = pd.to_datetime(power_daily["date"])
    base = pd.Series(power_daily["PRECTOTCORR"].to_numpy(float), index=dates).sort_index()
    base = base[~base.index.duplicated()]
    month = base.index.month.to_numpy()
    if bias and "precip_ratio" in bias:
        base = base * _monthly_lookup(bias["precip_ratio"], month)
    s = pd.Series(imerg["precip_mm"].to_numpy(float), index=pd.to_datetime(imerg["date"])).sort_index()
    s = s[~s.index.duplicated()].reindex(base.index)
    if bias and "imerg_precip_ratio" in bias:
        s = s * _monthly_lookup(bias["imerg_precip_ratio"], month)
    return s.fillna(base)


def base_frame(daily: pd.DataFrame, field_elev_m: float, grid_elev_m: float,
               precip: pd.Series | None = None, bias: dict | None = None) -> pd.DataFrame:
    """Locally corrected daily weather, before any what-if scenario.

    Columns: date, tmax, tmin, tdew_raw (dew point moved to the field's elevation, not yet
    capped by Tmin), wind, rs, precip. This is exactly what the static site ships per field
    (pipeline/s40_export.py), so the browser and this module start from the same numbers.

    Local correction of the NASA POWER grid cell, in order of preference:
      1. `bias` given: month-by-month delta from a ground-informed grid (gridMET in the USA,
         IMD station grids in India) for Tmax and Tmin, and a monthly ratio for precipitation;
      2. otherwise: a plain 6.5 degC/km lapse-rate shift from the cell's mean elevation.
    """
    d = daily.sort_values("date").reset_index(drop=True)
    adj = LAPSE_RATE * (grid_elev_m - field_elev_m)
    out = pd.DataFrame({"date": pd.to_datetime(d["date"])})
    month = out["date"].dt.month.to_numpy()
    doy = out["date"].dt.dayofyear
    if bias:
        dmax, dmin = _monthly_lookup(bias["tmax_delta"], month), _monthly_lookup(bias["tmin_delta"], month)
    else:
        dmax = dmin = adj
    out["tmax"] = d["T2M_MAX"].to_numpy(float) + dmax
    out["tmin"] = d["T2M_MIN"].to_numpy(float) + dmin
    # dew point: observed humidity, moved to the field elevation with the temperature
    out["tdew_raw"] = d["T2MDEW"].to_numpy(float) + adj
    out["wind"] = d["WS2M"].to_numpy(float)
    rs = d["ALLSKY_SFC_SW_DWN"].to_numpy(float)
    if np.isnan(rs).any():      # fill rare gaps with that calendar day's long-term mean
        clim = pd.Series(rs).groupby(doy).transform("mean").to_numpy()
        rs = np.where(np.isnan(rs), clim, rs)
    out["rs"] = rs
    if precip is None:
        base_p = d["PRECTOTCORR"].to_numpy(float)
        if bias and "precip_ratio" in bias:
            base_p = base_p * _monthly_lookup(bias["precip_ratio"], month)
    else:
        base_p = precip.reindex(out["date"]).to_numpy(float)
    out["precip"] = np.nan_to_num(base_p, nan=0.0)
    return out


def apply_scenario(base: pd.DataFrame, lat: float, field_elev_m: float,
                   scenario: Scenario = Scenario()) -> pd.DataFrame:
    """Scenario-adjusted daily frame with FAO-56 reference ET, from base_frame() output."""
    sc = scenario.clamp()
    out = pd.DataFrame({"date": pd.to_datetime(base["date"]).reset_index(drop=True)})
    out["year"], out["month"], out["doy"] = out["date"].dt.year, out["date"].dt.month, out["date"].dt.dayofyear
    out["tmax"] = base["tmax"].to_numpy(float) + sc.temp_c
    out["tmin"] = base["tmin"].to_numpy(float) + sc.temp_c
    out["tmean"] = (out["tmax"] + out["tmin"]) / 2.0
    out["tdew"] = np.minimum(base["tdew_raw"].to_numpy(float), out["tmin"])
    out["wind"] = base["wind"].to_numpy(float)
    out["rs"] = base["rs"].to_numpy(float)
    out["precip"] = base["precip"].to_numpy(float) * (1.0 + sc.rain_pct / 100.0)
    out["et0"] = et0_fao56(out["tmax"], out["tmin"], out["tdew"], out["wind"], out["rs"],
                           lat, field_elev_m, out["doy"])
    return out


def prepare_daily(daily: pd.DataFrame, lat: float, field_elev_m: float, grid_elev_m: float,
                  scenario: Scenario = Scenario(), precip: pd.Series | None = None,
                  bias: dict | None = None) -> pd.DataFrame:
    """Daily frame with locally corrected, scenario-adjusted weather and FAO-56 reference ET."""
    return apply_scenario(base_frame(daily, field_elev_m, grid_elev_m, precip, bias), lat, field_elev_m, scenario)


def summarise(prep: pd.DataFrame, baseline: tuple[int, int] = BASELINE, heavy_rain_mm: float = HEAVY_RAIN_MM,
              windy_ms: float = WINDY_MS, hot_day_c: float = 32) -> dict:
    """30-year normals and yearly series used by the indicators and the scoring engine."""
    b = prep[(prep["year"] >= baseline[0]) & (prep["year"] <= baseline[1])]
    n_years = b["year"].nunique()
    by_m = b.groupby("month")

    def per_year_mean(mask: pd.Series) -> dict[int, float]:
        counts = b[mask].groupby("month").size() / n_years
        return {m: round(float(counts.get(m, 0.0)), 2) for m in MONTHS}

    monthly_et0 = (b.groupby(["year", "month"])["et0"].sum().groupby("month").mean())
    monthly_p = (b.groupby(["year", "month"])["precip"].sum().groupby("month").mean())
    heat = {thr: per_year_mean(b["tmax"] > thr) for thr in HEAT_THRESHOLDS}

    frost_rows = []
    for year, g in prep.groupby("year"):
        if len(g) < 360:
            continue
        ls, ff, days = frost_dates(g["doy"], g["tmin"], 0.0)
        ls2, ff2, days2 = frost_dates(g["doy"], g["tmin"], -2.2)
        frost_rows.append({"year": int(year), "last_spring_frost_doy": ls, "first_fall_frost_doy": ff,
                           "frost_free_days": days, "killing_frost_free_days": days2,
                           "last_spring_killing_doy": ls2, "first_fall_killing_doy": ff2})
    frost = pd.DataFrame(frost_rows)
    fb = frost[(frost["year"] >= baseline[0]) & (frost["year"] <= baseline[1])]

    annual = prep.groupby("year").agg(
        tmean=("tmean", "mean"), precip=("precip", "sum"), et0=("et0", "sum"),
        days_over_32=("tmax", lambda s: int((s > 32).sum())),
        days_over_35=("tmax", lambda s: int((s > 35).sum())),
        hot_days=("tmax", lambda s: int((s > hot_day_c).sum())),
        heavy_rain_days=("precip", lambda s: int((s >= heavy_rain_mm).sum())),
        max_daily_precip=("precip", "max"), n=("tmax", "size")).reset_index()
    annual = annual[annual["n"] >= 360].drop(columns="n")
    grow = prep[prep["month"].between(4, 10)].groupby("year").agg(
        gs_precip=("precip", "sum"), gs_et0=("et0", "sum"), gs_tmean=("tmean", "mean")).reset_index()
    annual = annual.merge(grow, on="year", how="left").merge(frost, on="year", how="left")
    annual["water_balance"] = annual["precip"] - annual["et0"]

    return {
        "baseline": list(baseline),
        "n_years": int(n_years),
        "et0_month": {m: round(float(monthly_et0.get(m, 0.0)), 1) for m in MONTHS},
        "precip_month": {m: round(float(monthly_p.get(m, 0.0)), 1) for m in MONTHS},
        "tmax_month": {m: round(float(by_m["tmax"].mean().get(m, np.nan)), 1) for m in MONTHS},
        "tmin_month": {m: round(float(by_m["tmin"].mean().get(m, np.nan)), 1) for m in MONTHS},
        "wind_month": {m: round(float(by_m["wind"].mean().get(m, np.nan)), 2) for m in MONTHS},
        "windy_days_month": per_year_mean(b["wind"] >= windy_ms),
        "heavy_rain_days_month": per_year_mean(b["precip"] >= heavy_rain_mm),
        "heavy_rain_mm": heavy_rain_mm, "hot_day_c": hot_day_c,
        "hot_days_month": per_year_mean(b["tmax"] > hot_day_c),
        "hot_days": round(float((b["tmax"] > hot_day_c).sum() / max(n_years, 1)), 1),
        "frost_days_month": per_year_mean(b["tmin"] <= 0.0),
        "heat_days_month": heat,
        "et0_annual": round(float(monthly_et0.sum()), 0),
        "precip_annual": round(float(monthly_p.sum()), 0),
        "frost_free_days": [int(v) for v in fb["frost_free_days"]],
        "frost_free_median": float(fb["frost_free_days"].median()),
        "frost_free_p20": float(fb["frost_free_days"].quantile(0.2)),
        "last_spring_frost_median_doy": float(fb["last_spring_frost_doy"].median()),
        "first_fall_frost_median_doy": float(fb["first_fall_frost_doy"].median()),
        "annual": annual,
    }


def season_fit(frost_free_days: list[int], needed: int) -> float:
    """Share of baseline years whose frost-free season was long enough for a crop."""
    if needed <= 0:
        return 1.0
    if not frost_free_days:
        return 0.0
    arr = np.asarray(frost_free_days, dtype="float64")
    return round(float((arr >= needed).mean()), 3)


def heat_days_in(months: list[int], limit_c: float, summary: dict) -> float:
    """Average number of days a year above a crop's heat limit during its months."""
    thresholds = sorted(summary["heat_days_month"])
    thr = max([t for t in thresholds if t <= limit_c], default=thresholds[0])
    table = summary["heat_days_month"][thr]
    return float(sum(table[m] for m in months))


def summarise_for(prep: pd.DataFrame, kb: dict) -> dict:
    """summarise() with the region's own thresholds (heavy-rain day, windy day, hot day)."""
    st = kb.get("settings", {})
    return summarise(prep, heavy_rain_mm=float(st.get("heavy_rain_mm", HEAVY_RAIN_MM)),
                     windy_ms=float(st.get("windy_ms", WINDY_MS)), hot_day_c=float(st.get("hot_day_c", 32)))
