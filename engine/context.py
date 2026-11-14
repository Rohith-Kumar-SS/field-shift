"""Fuse every data source into (a) the context the scoring engine needs and (b) the
evidence panels the app shows. Used by the pipeline for the pilot fields and by the
backend for a field the user draws, so both follow exactly the same rules.
"""
from __future__ import annotations

import math
from typing import Any

import numpy as np
import pandas as pd

from .agromet import monthly_zscore, theil_sen_trend
from .climate import MONTHS, Scenario, field_precip, prepare_daily, summarise
from .history import interpret_history
from .scoring import hazard_weights

LOW_COVER_NDVI = 0.25
SOIL_KEYS = ["muname", "surface_texture", "om_pct_0_30", "clay_pct_0_30", "sand_pct_0_30", "silt_pct_0_30",
             "ph_0_30", "ec_dsm_0_30", "sar_0_30", "ksat_um_s_0_30", "kwfact_surface",
             "wind_erodibility_group", "wind_erodibility_index", "aws_0_100cm_cm", "drainage_class",
             "hydrologic_group", "dominant_mapunit_share", "n_mapunits", "caco3_pct_0_30",
             "bulk_density_0_30", "irrigated_capability_class", "soil_coverage_fraction"]


def clean(obj: Any) -> Any:
    """Make a structure JSON-safe: numpy -> python, NaN/inf -> None, timestamps -> ISO."""
    if isinstance(obj, dict):
        return {str(k): clean(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple, set)):
        return [clean(v) for v in obj]
    if isinstance(obj, pd.DataFrame):
        return clean(obj.to_dict("records"))
    if isinstance(obj, (pd.Timestamp,)):
        return obj.strftime("%Y-%m-%d")
    if isinstance(obj, (np.integer,)):
        return int(obj)
    if isinstance(obj, (np.floating, float)):
        v = float(obj)
        return None if (math.isnan(v) or math.isinf(v)) else v
    if isinstance(obj, (np.bool_,)):
        return bool(obj)
    if isinstance(obj, np.ndarray):
        return clean(obj.tolist())
    return obj


# ---------------------------------------------------------------------------
# Landsat greenness
# ---------------------------------------------------------------------------
def landsat_monthly(obs: pd.DataFrame) -> pd.DataFrame:
    """Monthly mean NDVI from clear, snow-free field observations."""
    if obs is None or obs.empty:
        return pd.DataFrame(columns=["year", "month", "ndvi", "n", "snow_share"])
    o = obs.assign(year=obs["date"].dt.year, month=obs["date"].dt.month)
    o["snowy"] = o["snow_frac"] >= 0.5
    snow = o.groupby(["year", "month"])["snowy"].mean().rename("snow_share")
    free = o[o["snow_frac"] < 0.2]
    m = free.groupby(["year", "month"]).agg(ndvi=("ndvi", "mean"), n=("ndvi", "size"))
    return m.join(snow, how="outer").reset_index()


def peak_ndvi_by_year(obs: pd.DataFrame) -> dict[int, float]:
    """90th percentile of clear, snow-free NDVI in May-September, per year."""
    if obs is None or obs.empty:
        return {}
    o = obs[(obs["snow_frac"] < 0.2) & obs["date"].dt.month.between(5, 9)]
    out = {}
    for year, g in o.groupby(o["date"].dt.year):
        if len(g) >= 3:
            out[int(year)] = float(g["ndvi"].quantile(0.9))
    return out


def low_cover_calendar(monthly: pd.DataFrame) -> dict:
    """For each month: share of years with little green cover, and share with snow."""
    out = {}
    for m in MONTHS:
        sub = monthly[monthly["month"] == m]
        with_data = sub.dropna(subset=["ndvi"])
        out[m] = {
            "low_cover_share": round(float((with_data["ndvi"] < LOW_COVER_NDVI).mean()), 2) if len(with_data) else None,
            "snow_share": round(float(sub["snow_share"].fillna(0).mean()), 2) if len(sub) else None,
            "ndvi_mean": round(float(with_data["ndvi"].mean()), 3) if len(with_data) else None,
            "years": int(len(with_data)),
        }
    return out


# ---------------------------------------------------------------------------
# OpenET: anchor the textbook water demand to this field's own record
# ---------------------------------------------------------------------------
def water_calibration(openet: pd.DataFrame | None, history: list[dict], prep: pd.DataFrame, kb: dict) -> dict:
    """Median of (OpenET May-Sep ET) / (alfalfa Kc x reference ET) over this field's alfalfa years."""
    if openet is None or openet.empty:
        return {"available": False, "factor": 1.0, "reason": "No OpenET record for this field."}
    kc = kb["crops"]["alfalfa"]["kc"]
    et0 = prep.groupby(["year", "month"])["et0"].sum()
    o = openet.assign(year=openet["date"].dt.year, month=openet["date"].dt.month)
    rows = []
    for rec in history:
        if rec["crop"] != "alfalfa" or rec["doubtful"]:
            continue
        g = o[(o["year"] == rec["year"]) & o["month"].between(5, 9)]
        if len(g) < 5 or g.get("repeated_value", pd.Series(False, index=g.index)).any():
            continue
        model = sum(kc.get(m, 0.0) * float(et0.get((rec["year"], m), np.nan)) for m in range(5, 10))
        if not np.isfinite(model) or model <= 0:
            continue
        rows.append({"year": rec["year"], "openet_mm": round(float(g["et_mm"].sum())),
                     "textbook_mm": round(model), "ratio": round(float(g["et_mm"].sum()) / model, 3)})
    if len(rows) < 2:
        return {"available": False, "factor": 1.0, "years": [r["year"] for r in rows], "rows": rows,
                "reason": "Fewer than two clean alfalfa years with OpenET data on this field."}
    raw = float(np.median([r["ratio"] for r in rows]))
    return {"available": True, "factor": round(float(np.clip(raw, 0.6, 1.15)), 3), "raw_ratio": round(raw, 3),
            "years": [r["year"] for r in rows], "rows": rows,
            "explanation": "OpenET's satellite estimate of ET in this field's alfalfa years, divided by the "
                           "textbook full-irrigation figure (FAO-56 crop coefficient x NASA POWER reference ET). "
                           "The same factor is applied to every strategy."}


# ---------------------------------------------------------------------------
# Groundwater near the field
# ---------------------------------------------------------------------------
def groundwater_near(lon: float, lat: float, wells: pd.DataFrame | None, levels: pd.DataFrame | None,
                     radius_km: float = 12.0) -> dict:
    if wells is None or len(wells) == 0 or levels is None:
        return {"available": False}
    w = wells.copy()
    k = 111.32
    w["dist_km"] = np.hypot((w["lon"] - lon) * k * math.cos(math.radians(lat)), (w["lat"] - lat) * k)
    near = w[w["dist_km"] <= radius_km]
    trend = near[near["trend_m_per_decade_since_1990"].notna()]
    series = []
    for _, r in trend.sort_values("dist_km").head(4).iterrows():
        g = levels[(levels["site_id"] == r["site_id"]) & levels["static"]]
        ann = g.groupby("year")["depth_m"].median().reset_index()
        series.append({"site_id": r["site_id"], "dist_km": round(float(r["dist_km"]), 1),
                       "trend_m_per_decade": r["trend_m_per_decade_since_1990"],
                       "trend_direction": r["trend_direction"], "p_value": r["trend_p_value"],
                       "first_year": int(r["first_year"]), "last_year": int(r["last_year"]),
                       "points": [{"year": int(y), "depth_m": round(float(d), 2)}
                                  for y, d in zip(ann["year"], ann["depth_m"])]})
    out = {"available": len(trend) > 0, "radius_km": radius_km, "n_wells": int(len(near)),
           "n_wells_trend": int(len(trend)),
           "n_deepening": int(((trend["trend_m_per_decade_since_1990"] > 0)
                               & (trend["trend_p_value"] < 0.05)).sum()),
           "n_rising": int(((trend["trend_m_per_decade_since_1990"] < 0)
                            & (trend["trend_p_value"] < 0.05)).sum()),
           "median_m_per_decade": (round(float(trend["trend_m_per_decade_since_1990"].median()), 2)
                                   if len(trend) else None),
           "wells": series}
    return out


# ---------------------------------------------------------------------------
# Main builder
# ---------------------------------------------------------------------------
def build(meta: dict, kb: dict, *, power_daily: pd.DataFrame, grid_elevation_m: float,
          soil: dict | None, terrain: dict | None, cdl_rows: list[dict],
          landsat_obs: pd.DataFrame | None = None, landsat_month: pd.DataFrame | None = None,
          modis: pd.DataFrame | None = None, openet: pd.DataFrame | None = None,
          openet_valley: pd.DataFrame | None = None, smap: pd.DataFrame | None = None,
          imerg: pd.DataFrame | None = None, wells: pd.DataFrame | None = None,
          levels: pd.DataFrame | None = None, bias: dict | None = None) -> tuple[dict, dict]:
    """Return (context, evidence) for one field. Missing sources are recorded, never invented."""
    elev = float((terrain or {}).get("elevation_m") or meta.get("elevation_m") or grid_elevation_m)
    slope = (terrain or {}).get("slope_pct_plane")
    precip_override = field_precip(power_daily, imerg, bias)
    prep = prepare_daily(power_daily, meta["lat"], elev, grid_elevation_m, Scenario(), precip=precip_override,
                         bias=bias)
    clim = summarise(prep)
    annual = clim["annual"]

    # ---- greenness -------------------------------------------------------
    if landsat_month is None:
        landsat_month = landsat_monthly(landsat_obs) if landsat_obs is not None else pd.DataFrame(
            columns=["year", "month", "ndvi", "n", "snow_share"])
    peaks = peak_ndvi_by_year(landsat_obs) if landsat_obs is not None and len(landsat_obs) else {
        int(y): float(g["ndvi"].quantile(0.9)) for y, g in
        landsat_month[landsat_month["month"].between(5, 9)].dropna(subset=["ndvi"]).groupby("year") if len(g) >= 3}
    modis_peak = []
    if modis is not None and not modis.empty:
        mm = modis[modis["date"].dt.month.between(6, 9)]
        modis_peak = [{"year": int(y), "ndvi": round(float(v), 3)}
                      for y, v in mm.groupby(mm["date"].dt.year)["ndvi"].max().items()]
        for r in modis_peak:      # MODIS fills the greenness check before Landsat coverage starts
            peaks.setdefault(r["year"], None)
    # MODIS reads lower than Landsat on a pivot, so it is not used to second-guess the crop map
    peak_for_history = {y: v for y, v in peaks.items() if v is not None}
    history = interpret_history(cdl_rows, peak_for_history, kb)
    recent = history[-8:]
    calendar = low_cover_calendar(landsat_month)

    # ---- water -----------------------------------------------------------
    calib = water_calibration(openet, history, prep, kb)
    soil_ctx = {k: (soil or {}).get(k) for k in SOIL_KEYS} if soil else {}
    hazard = hazard_weights(clim, soil_ctx, slope if slope is not None else 0.3)
    peak_months = hazard["peak_months"]
    lc = [calendar[m]["low_cover_share"] for m in peak_months if calendar[m]["low_cover_share"] is not None]

    # A trend must not straddle a change of data source. When IMERG supplies the rain, the
    # years before its record starts come from NASA POWER, so rain-based trends use the
    # IMERG years only.
    rain_start = None
    if precip_override is not None and imerg is not None and len(imerg):
        rain_start = int(pd.to_datetime(imerg["date"]).dt.year.min())

    def trend_of(key: str) -> dict:
        a = annual
        if rain_start is not None and key in ("precip", "heavy_rain_days", "water_balance"):
            a = annual[annual["year"] >= rain_start]
        t = theil_sen_trend(a["year"], a[key])
        t["from_year"] = int(a["year"].min()) if len(a) else None
        return t

    trends = {k: trend_of(k) for k in
              ("tmean", "precip", "et0", "days_over_32", "frost_free_days", "water_balance",
               "heavy_rain_days", "gs_tmean")}
    gw = groundwater_near(meta["lon"], meta["lat"], wells, levels)

    sources = {
        "power": True, "gridmet": bool(bias), "imerg": precip_override is not None, "smap": smap is not None and not smap.empty,
        "ssurgo": bool(soil), "cdl": bool(cdl_rows), "landsat": len(landsat_month.dropna(subset=["ndvi"])) > 0,
        "openet": openet is not None and not openet.empty, "srtm": terrain is not None,
        "modis": bool(modis_peak), "groundwater": bool(gw.get("available")),
    }
    context = {
        **{k: meta[k] for k in ("field_id", "name", "lat", "lon", "area_ha")},
        "is_custom": bool(meta.get("is_custom", False)),
        "elevation_m": round(elev, 1), "slope_pct": slope, "grid_elevation_m": grid_elevation_m,
        "soil": soil_ctx, "history": history, "n_doubtful_years": sum(bool(r["doubtful"]) for r in recent),
        "water_factor": calib["factor"], "water_factor_info": calib,
        "landsat": {"low_cover_share_peak_months": round(float(np.mean(lc)), 2) if lc else None},
        "groundwater": {k: gw.get(k) for k in ("n_wells_trend", "n_deepening", "median_m_per_decade")},
        "trends": {"days_over_32": trends["days_over_32"],
                   "days_over_32_gridmet": (bias or {}).get("check", {}).get("days_over_32_gridmet")},
        "sources": sources,
        "climate_correction": "gridmet" if bias else "lapse",
    }

    # ---- evidence panels -------------------------------------------------
    ev: dict[str, Any] = {"field_id": meta["field_id"]}
    ev["climate"] = {
        "annual": annual.round(2), "trends": trends,
        "normals": {k: clim[k] for k in ("et0_month", "precip_month", "tmax_month", "tmin_month",
                                         "wind_month", "windy_days_month", "heavy_rain_days_month",
                                         "frost_days_month")}
                   | {"hot_days_32_month": clim["heat_days_month"][32],
                      "hot_days_35_month": clim["heat_days_month"][35]},
        "summary": {"et0_annual": clim["et0_annual"], "precip_annual": clim["precip_annual"],
                    "frost_free_median": clim["frost_free_median"], "frost_free_p20": clim["frost_free_p20"],
                    "last_spring_frost_median_doy": clim["last_spring_frost_median_doy"],
                    "first_fall_frost_median_doy": clim["first_fall_frost_median_doy"],
                    "hot_days_32": round(sum(clim["heat_days_month"][32].values()), 1),
                    "baseline": clim["baseline"]},
        "correction": ({"method": "gridmet", "tmin_delta": bias["tmin_delta"], "tmax_delta": bias["tmax_delta"],
                        "precip_ratio": bias["precip_ratio"], "check": bias.get("check", {})} if bias else
                       {"method": "lapse", "shift_c": round(0.0065 * (grid_elevation_m - elev), 2)}),
        "rain_source": (("GPM IMERG satellite rainfall" + (", scaled month by month to gridMET" if (bias or {}).get("imerg_precip_ratio") else "")
                         + " (corrected NASA POWER before 2001 and where IMERG has no file)") if sources["imerg"]
                        else "NASA POWER" + (", corrected month by month to gridMET" if bias else "")),
        "imerg": sources["imerg"],
    }

    water: dict[str, Any] = {"calibration": calib, "hazard": {k: v for k, v in hazard.items() if k != "weights"}}
    et0_ym = prep.groupby(["year", "month"])["et0"].sum()
    p_ym = prep.groupby(["year", "month"])["precip"].sum()
    if sources["openet"]:
        o = openet.sort_values("date")
        water["openet_monthly"] = [
            {"date": d.strftime("%Y-%m"), "et": round(float(e), 1),
             "et_min": None if pd.isna(lo) else round(float(lo), 1),
             "et_max": None if pd.isna(hi) else round(float(hi), 1), "flagged": bool(fl),
             "et0_power": round(float(et0_ym.get((d.year, d.month), np.nan)), 1)}
            for d, e, lo, hi, fl in zip(o["date"], o["et_mm"], o["et_min_mm"], o["et_max_mm"],
                                        o.get("repeated_value", pd.Series(False, index=o.index)))]
        oy = o.assign(year=o["date"].dt.year, gs=o["date"].dt.month.between(4, 10))
        water["openet_annual"] = [
            {"year": int(y), "et_mm": round(float(g["et_mm"].sum())),
             "growing_season_et_mm": round(float(g.loc[g["gs"], "et_mm"].sum())),
             "growing_season_min_mm": round(float(g.loc[g["gs"], "et_min_mm"].sum())),
             "growing_season_max_mm": round(float(g.loc[g["gs"], "et_max_mm"].sum()))}
            for y, g in oy.groupby("year")]
        water["openet_trend"] = theil_sen_trend([r["year"] for r in water["openet_annual"]],
                                                [r["growing_season_et_mm"] for r in water["openet_annual"]])
    norm = []
    ov = None if openet_valley is None or openet_valley.empty else openet_valley.assign(
        month=openet_valley["date"].dt.month)
    oclim = None if not sources["openet"] else openet.assign(month=openet["date"].dt.month)
    for m in MONTHS:
        row = {"month": m, "et0_power": clim["et0_month"][m], "precip": clim["precip_month"][m],
               "balance": round(clim["precip_month"][m] - clim["et0_month"][m], 1)}
        if ov is not None:
            row["eto_gridmet"] = round(float(ov.loc[ov["month"] == m, "eto_mm"].mean()), 1)
            row["precip_gridmet"] = round(float(ov.loc[ov["month"] == m, "pr_mm"].mean()), 1)
        if oclim is not None:
            sel = oclim[(oclim["month"] == m) & ~oclim.get("repeated_value", False)]
            row["et_openet"] = round(float(sel["et_mm"].mean()), 1) if len(sel) else None
        norm.append(row)
    water["monthly_normals"] = norm
    imerg_year = {}
    if imerg is not None and len(imerg):
        iy = imerg.assign(year=pd.to_datetime(imerg["date"]).dt.year).groupby("year")["precip_mm"].agg(["sum", "count"])
        imerg_year = {int(y): round(float(r["sum"])) for y, r in iy.iterrows() if r["count"] >= 360}
    if ov is not None:
        yr = ov.assign(year=ov["date"].dt.year).groupby("year")[["eto_mm", "pr_mm"]].sum()
        water["source_comparison"] = [
            {"year": int(y), "et0_power": round(float(et0_ym.loc[y].sum())) if y in et0_ym.index.get_level_values(0) else None,
             "eto_gridmet": round(float(r["eto_mm"])),
             "precip_power": round(float(p_ym.loc[y].sum())) if y in p_ym.index.get_level_values(0) else None,
             "precip_gridmet": round(float(r["pr_mm"])),
             "precip_imerg_raw": imerg_year.get(int(y))} for y, r in yr.iterrows()]
    ev["water"] = water

    if sources["smap"]:
        s = smap.sort_values(["year", "month"])
        ev["soil_moisture"] = {
            "cell_id": s["cell_id"].iloc[0],
            "monthly": [{"date": f"{int(y)}-{int(m):02d}", "sm": None if pd.isna(v) else round(float(v), 3),
                         "z": None if pd.isna(z) else round(float(z), 2), "n_days": int(n)}
                        for y, m, v, z, n in zip(s["year"], s["month"], s["sm_mean"], s["sm_anomaly_z"], s["n_days"])],
            "clim": {int(m): round(float(v), 3) for m, v in s.groupby("month")["sm_mean"].mean().items()},
            "share_recommended_quality": round(float(s["share_recommended"].mean()), 2),
        }

    gm = landsat_month.sort_values(["year", "month"])
    z = monthly_zscore(gm["ndvi"], gm["month"]) if len(gm) else []
    ev["greenness"] = {
        "monthly": [{"date": f"{int(y)}-{int(m):02d}", "ndvi": None if pd.isna(v) else round(float(v), 3),
                     "n": 0 if pd.isna(n) else int(n), "z": None if pd.isna(zz) else round(float(zz), 2),
                     "snow_share": None if pd.isna(sn) else round(float(sn), 2)}
                    for y, m, v, n, zz, sn in zip(gm["year"], gm["month"], gm["ndvi"], gm["n"], z, gm["snow_share"])],
        "calendar": calendar, "peak_by_year": {y: (None if v is None else round(v, 3)) for y, v in sorted(peaks.items())},
        "modis_peak": modis_peak,
        "modis_trend": theil_sen_trend([r["year"] for r in modis_peak], [r["ndvi"] for r in modis_peak]) if modis_peak else None,
    }
    ev["history"] = history
    ev["soil"] = {**soil_ctx, "mapunits": (soil or {}).get("mapunits")} if soil else None
    ev["terrain"] = terrain
    ev["groundwater"] = gw

    # ---- when is the field bare, when does the crop look vulnerable ------
    sm_clim = ev.get("soil_moisture", {}).get("clim", {})
    sm_max = max(sm_clim.values()) if sm_clim else None
    gap = {m: max(clim["et0_month"][m] - clim["precip_month"][m], 0.0) for m in MONTHS}
    gap_max = max(gap.values()) or 1.0
    dips = {}
    if len(gm):
        gz = gm.assign(z=z)
        for m in MONTHS:
            sub = gz[(gz["month"] == m)].dropna(subset=["z"])
            dips[m] = float((sub["z"] <= -1.0).mean()) if len(sub) >= 4 else None
    vul = []
    for m in range(4, 11):
        comp = {"heat": min(clim["heat_days_month"][32][m] / 10.0, 1.0),
                "frost": min(clim["frost_days_month"][m] / 10.0, 1.0) if m in (5, 6, 7, 8, 9) else 0.0,
                "water_gap": gap[m] / gap_max,
                "greenness_dips": dips.get(m),
                "dry_soil": (1.0 - sm_clim[m] / sm_max) if (sm_max and m in sm_clim) else None}
        vals = [v for v in comp.values() if v is not None]
        vul.append({"month": m, **{k: (None if v is None else round(v, 2)) for k, v in comp.items()},
                    "index": round(float(np.mean(vals)), 2)})
    top = sorted(vul, key=lambda r: -r["index"])[:2]
    ev["vulnerability"] = {"months": vul, "most_vulnerable": sorted(r["month"] for r in top),
                           "method": "Each part is scaled 0-1 and averaged: hot days (>32 °C, 10 days = 1), "
                                     "frost days in May-September (10 days = 1), the gap between reference ET "
                                     "and rain, how often greenness fell well below its own normal, and how "
                                     "dry the SMAP soil-moisture pixel normally is."}
    bare = [m for m in MONTHS if (calendar[m]["low_cover_share"] or 0) >= 0.5]
    ev["bare"] = {"months_usually_low_cover": bare, "threshold_ndvi": LOW_COVER_NDVI,
                  "risk_months": peak_months,
                  "note": "Low green cover is not always bare soil: dormant alfalfa and stubble still "
                          "protect the surface but look brown from space, and snow hides the ground."}
    return clean(context), clean(ev)
