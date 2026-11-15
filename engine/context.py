"""Fuse every data source into (a) the context the scoring engine needs and (b) the
evidence panels the app shows, for one field. The same function serves every region;
sources that do not exist somewhere are recorded as missing, never invented.
"""
from __future__ import annotations

import math
from typing import Any

import numpy as np
import pandas as pd

from .agromet import monthly_zscore, theil_sen_trend
from .climate import MONTHS, Scenario, field_precip, prepare_daily, summarise_for
from .history import interpret_history
from .phenology import history_from_pattern, yearly_pattern
from .scoring import hazard_weights

LOW_COVER_NDVI = 0.25
SOIL_KEYS = ["muname", "surface_texture", "om_pct_0_30", "clay_pct_0_30", "sand_pct_0_30", "silt_pct_0_30",
             "ph_0_30", "ec_dsm_0_30", "sar_0_30", "ksat_um_s_0_30", "kwfact_surface",
             "wind_erodibility_group", "wind_erodibility_index", "aws_0_100cm_cm", "drainage_class",
             "hydrologic_group", "dominant_mapunit_share", "n_mapunits", "caco3_pct_0_30",
             "bulk_density_0_30", "irrigated_capability_class", "soil_coverage_fraction",
             "cec_cmol_kg_0_30", "nitrogen_g_kg_0_30", "derived"]


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


def peak_ndvi_by_year(obs: pd.DataFrame, months: tuple[int, int] = (5, 9)) -> dict[int, float]:
    """90th percentile of clear, snow-free NDVI in the main season, per year."""
    if obs is None or obs.empty:
        return {}
    o = obs[(obs["snow_frac"] < 0.2) & obs["date"].dt.month.between(*months)]
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


def flood_calendar(obs: pd.DataFrame | None) -> dict | None:
    """Share of clear observations per month that look flooded (water index above greenness).

    The paddy-transplanting signal of Xiao et al. (2005): LSWI + 0.05 >= NDVI. A hint that
    rice is grown, not a crop map.
    """
    if obs is None or obs.empty or "lswi" not in obs.columns or obs["lswi"].notna().sum() < 20:
        return None
    o = obs.dropna(subset=["lswi"]).assign(month=lambda d: d["date"].dt.month, year=lambda d: d["date"].dt.year)
    o["flooded"] = (o["lswi"] + 0.05 >= o["ndvi"]) & (o["ndvi"] < 0.55)
    by_month = {int(m): round(float(g["flooded"].mean()), 2) for m, g in o.groupby("month")}
    yearly = o.groupby("year")["flooded"].any()
    top = sorted(by_month, key=lambda m: -by_month[m])[:2]
    return {"share_by_month": by_month, "years_with_signal": int(yearly.sum()), "years": int(len(yearly)),
            "peak_months": sorted(m for m in top if by_month[m] >= 0.3)}


# ---------------------------------------------------------------------------
# Anchor the textbook water demand to the field's own satellite record (crop-map regions)
# ---------------------------------------------------------------------------
def water_calibration(et: pd.DataFrame | None, history: list[dict], prep: pd.DataFrame, kb: dict) -> dict:
    """Median of (satellite May-Sep ET) / (alfalfa Kc x reference ET) over this field's alfalfa years."""
    if et is None or et.empty:
        return {"available": False, "factor": 1.0, "reason": "No satellite water-use record for this field."}
    kc = kb["crops"]["alfalfa"]["kc"]
    et0 = prep.groupby(["year", "month"])["et0"].sum()
    o = et.assign(year=et["date"].dt.year, month=et["date"].dt.month)
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
                "reason": "Fewer than two clean alfalfa years with satellite water-use data on this field."}
    raw = float(np.median([r["ratio"] for r in rows]))
    return {"available": True, "factor": round(float(np.clip(raw, 0.6, 1.15)), 3), "raw_ratio": round(raw, 3),
            "years": [r["year"] for r in rows], "rows": rows,
            "explanation": "OpenET's satellite estimate of ET in this field's alfalfa years, divided by the "
                           "textbook full-irrigation figure (FAO-56 crop coefficient x NASA POWER reference ET). "
                           "The same factor is applied to every strategy."}


# ---------------------------------------------------------------------------
# Long-term water: wells where they exist, GRACE where they do not
# ---------------------------------------------------------------------------
def groundwater_near(lon: float, lat: float, wells: pd.DataFrame | None, levels: pd.DataFrame | None,
                     radius_km: float = 12.0) -> dict:
    if wells is None or len(wells) == 0 or levels is None:
        return {"available": False, "kind": "wells"}
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
    return {"available": len(trend) > 0, "kind": "wells", "radius_km": radius_km, "n_wells": int(len(near)),
            "n_wells_trend": int(len(trend)),
            "n_deepening": int(((trend["trend_m_per_decade_since_1990"] > 0) & (trend["trend_p_value"] < 0.05)).sum()),
            "n_rising": int(((trend["trend_m_per_decade_since_1990"] < 0) & (trend["trend_p_value"] < 0.05)).sum()),
            "median_m_per_decade": (round(float(trend["trend_m_per_decade_since_1990"].median()), 2)
                                    if len(trend) else None),
            "wells": series}


def grace_summary(grace: pd.DataFrame | None) -> dict:
    if grace is None or grace.empty:
        return {"available": False, "kind": "grace"}
    g = grace.sort_values("date")
    ann = g.groupby(g["date"].dt.year)["lwe_cm"].agg(["mean", "size"])
    ann = ann[ann["size"] >= 6]
    tr = theil_sen_trend(ann.index, ann["mean"].values)
    per_year = None if tr["slope_per_decade"] is None else round(tr["slope_per_decade"] / 10.0, 2)
    return {"available": True, "kind": "grace", "trend_cm_per_year": per_year, "significant": tr["significant"],
            "p_value": tr["p_value"], "direction": tr["direction"],
            "from_year": int(ann.index.min()), "to_year": int(ann.index.max()),
            "monthly": [{"date": d.strftime("%Y-%m"), "lwe_cm": round(float(v), 2),
                         "unc_cm": None if pd.isna(u) else round(float(u), 2)}
                        for d, v, u in zip(g["date"], g["lwe_cm"], g["uncertainty_cm"])],
            "annual": [{"year": int(y), "lwe_cm": round(float(v), 2)} for y, v in ann["mean"].items()]}


# ---------------------------------------------------------------------------
# Main builder
# ---------------------------------------------------------------------------
def build(meta: dict, kb: dict, *, power_daily: pd.DataFrame, grid_elevation_m: float,
          soil: dict | None, terrain: dict | None, cdl_rows: list[dict] | None = None,
          landsat_obs: pd.DataFrame | None = None, landsat_month: pd.DataFrame | None = None,
          modis: pd.DataFrame | None = None, et: pd.DataFrame | None = None,
          et_valley: pd.DataFrame | None = None, smap: pd.DataFrame | None = None,
          imerg: pd.DataFrame | None = None, wells: pd.DataFrame | None = None,
          levels: pd.DataFrame | None = None, grace: pd.DataFrame | None = None,
          ground_daily: pd.DataFrame | None = None, bias: dict | None = None,
          growing_months: list[int] | None = None) -> tuple[dict, dict]:
    """Return (context, evidence) for one field. Missing sources are recorded, never invented."""
    st = kb["settings"]
    from_history = st["existing"] == "from_history"
    growing = growing_months or list(range(4, 11))
    elev = float((terrain or {}).get("elevation_m") or meta.get("elevation_m") or grid_elevation_m)
    slope = (terrain or {}).get("slope_pct_plane")
    precip_override = field_precip(power_daily, imerg, bias)
    prep = prepare_daily(power_daily, meta["lat"], elev, grid_elevation_m, Scenario(), precip=precip_override,
                         bias=bias)
    clim = summarise_for(prep, kb)
    annual = clim["annual"]
    hot_c = int(st["hot_day_c"])

    # ---- greenness and what grew ---------------------------------------
    if landsat_month is None:
        landsat_month = landsat_monthly(landsat_obs) if landsat_obs is not None else pd.DataFrame(
            columns=["year", "month", "ndvi", "n", "snow_share"])
    has_obs = landsat_obs is not None and len(landsat_obs)
    season = (5, 9) if from_history else (1, 12)
    peaks: dict[int, float | None] = peak_ndvi_by_year(landsat_obs, season) if has_obs else {
        int(y): float(g["ndvi"].quantile(0.9)) for y, g in
        landsat_month[landsat_month["month"].between(*season)].dropna(subset=["ndvi"]).groupby("year") if len(g) >= 3}
    modis_peak = []
    if modis is not None and not modis.empty:
        mm = modis[modis["date"].dt.month.between(6, 9)] if from_history else modis
        modis_peak = [{"year": int(y), "ndvi": round(float(v), 3)}
                      for y, v in mm.groupby(mm["date"].dt.year)["ndvi"].max().items()]
    peak_for_history = {y: v for y, v in peaks.items() if v is not None}
    phenology = None
    if from_history:
        history = interpret_history(cdl_rows or [], peak_for_history, kb)
    else:
        # no crop map: count green seasons instead (MODIS for the long record, Landsat otherwise)
        if modis is not None and len(modis) >= 60:
            pattern, pheno_src = yearly_pattern(modis["date"], modis["ndvi"]), "MODIS 250 m, 16-day"
        else:
            lm = landsat_month.dropna(subset=["ndvi"])
            dates = pd.to_datetime(dict(year=lm["year"], month=lm["month"], day=15)) if len(lm) else []
            pattern, pheno_src = yearly_pattern(dates, lm["ndvi"] if len(lm) else []), "Landsat monthly means"
        history = history_from_pattern(pattern)
        phenology = {"median_seasons": pattern["median_seasons"], "usual_peak_months": pattern["usual_peak_months"],
                     "n_years": pattern["n_years"], "source": pheno_src}
    recent = history[-8:]
    calendar = low_cover_calendar(landsat_month)
    flood = flood_calendar(landsat_obs) if has_obs else None

    # ---- water ------------------------------------------------------------
    has_et = et is not None and not et.empty
    et_source = (str(et["source"].iloc[0]) if has_et and "source" in et.columns else "OpenET ensemble (Landsat, 30 m)")
    if from_history:
        calib = water_calibration(et, history, prep, kb)
    else:
        calib = {"available": False, "factor": 1.0,
                 "reason": "The crop grown each year is not known from a map here, so the textbook estimate "
                           "is not scaled to the satellite record. The two are shown side by side instead."}
    soil_ctx = {k: (soil or {}).get(k) for k in SOIL_KEYS} if soil else {}
    soil_source = "soilgrids" if "SoilGrids" in str((soil or {}).get("muname", "")) else "ssurgo"
    hazard = hazard_weights(clim, soil_ctx, slope if slope is not None else 0.3)
    peak_months = hazard["peak_months"]
    lc = [calendar[m]["low_cover_share"] for m in peak_months if calendar[m]["low_cover_share"] is not None]

    # ---- trends: never across a change of data source -----------------------
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

    trends = {k: trend_of(k) for k in ("tmean", "precip", "et0", "hot_days", "frost_free_days", "water_balance",
                                       "heavy_rain_days", "gs_tmean")}
    gw = groundwater_near(meta["lon"], meta["lat"], wells, levels) if wells is not None else grace_summary(grace)

    correction = "lapse"
    if bias:
        correction = ("gridmet" if "ground_cell" not in bias else
                      "imd" if bias.get("temperature_method") == "imd" else "imd_rain")
    sources = {
        "power": True, "ground": bool(bias), "imerg": precip_override is not None,
        "smap": smap is not None and not smap.empty, "soil": bool(soil), "history": bool(history),
        "landsat": len(landsat_month.dropna(subset=["ndvi"])) > 0, "et": has_et, "srtm": terrain is not None,
        "modis": bool(modis_peak), "groundwater": bool(gw.get("available")),
    }
    gw_ctx = ({"kind": "wells", **{k: gw.get(k) for k in ("n_wells_trend", "n_deepening", "median_m_per_decade")}}
              if gw.get("kind") == "wells" else
              {"kind": "grace", **{k: gw.get(k) for k in ("trend_cm_per_year", "significant", "from_year")}})
    context = {
        **{k: meta[k] for k in ("field_id", "name", "lat", "lon", "area_ha")},
        "is_custom": bool(meta.get("is_custom", False)),
        "elevation_m": round(elev, 1), "slope_pct": slope, "grid_elevation_m": grid_elevation_m,
        "soil": soil_ctx, "soil_source": soil_source, "history": history, "phenology": phenology,
        "n_doubtful_years": sum(bool(r["doubtful"]) for r in recent),
        "water_factor": calib["factor"], "water_factor_info": calib,
        "landsat": {"low_cover_share_peak_months": round(float(np.mean(lc)), 2) if lc else None},
        "groundwater": gw_ctx,
        "trends": {"hot_days": trends["hot_days"],
                   "hot_days_ground": (bias or {}).get("check", {}).get("days_over_32_gridmet")},
        "ground_label": (bias or {}).get("label"),
        "sources": sources, "climate_correction": correction,
    }

    # ---- evidence panels -------------------------------------------------
    ground_label = (bias or {}).get("label") or ("gridMET (4 km, station-informed)" if correction == "gridmet" else None)
    rain_source = ("GPM IMERG satellite rainfall" + (f", scaled month by month to {ground_label}" if (bias or {}).get("imerg_precip_ratio") else "")
                   + " (corrected NASA POWER before 2001 and where IMERG has no file)") if sources["imerg"] else (
        "NASA POWER" + (f", corrected month by month to {ground_label}" if bias else ""))
    p_month = clim["precip_month"]
    p_total = sum(p_month.values()) or 1.0
    ev: dict[str, Any] = {"field_id": meta["field_id"]}
    ev["climate"] = {
        "annual": annual.round(2), "trends": trends,
        "normals": {k: clim[k] for k in ("et0_month", "precip_month", "tmax_month", "tmin_month",
                                         "wind_month", "windy_days_month", "heavy_rain_days_month",
                                         "frost_days_month", "hot_days_month")},
        "summary": {"et0_annual": clim["et0_annual"], "precip_annual": clim["precip_annual"],
                    "frost_free_median": clim["frost_free_median"], "frost_free_p20": clim["frost_free_p20"],
                    "last_spring_frost_median_doy": clim["last_spring_frost_median_doy"],
                    "first_fall_frost_median_doy": clim["first_fall_frost_median_doy"],
                    "hot_days": round(sum(clim["hot_days_month"].values()), 1), "hot_day_c": hot_c,
                    "heavy_rain_mm": clim["heavy_rain_mm"],
                    "heavy_rain_days": round(sum(clim["heavy_rain_days_month"].values()), 1),
                    "wettest_months": sorted(sorted(MONTHS, key=lambda m: -p_month[m])[:3]),
                    "wettest_share": round(sum(sorted(p_month.values(), reverse=True)[:3]) / p_total, 2),
                    "baseline": clim["baseline"]},
        "correction": ({"method": correction, "label": ground_label, "tmin_delta": bias["tmin_delta"],
                        "tmax_delta": bias["tmax_delta"], "precip_ratio": bias["precip_ratio"],
                        "check": bias.get("check", {})} if bias else
                       {"method": "lapse", "shift_c": round(0.0065 * (grid_elevation_m - elev), 2)}),
        "rain_source": rain_source, "imerg": sources["imerg"], "ground_label": ground_label,
    }

    water: dict[str, Any] = {"calibration": calib, "hazard": {k: v for k, v in hazard.items() if k != "weights"},
                             "et_source": et_source if has_et else None}
    et0_ym = prep.groupby(["year", "month"])["et0"].sum()
    p_ym = prep.groupby(["year", "month"])["precip"].sum()
    if has_et:
        o = et.sort_values("date")
        flagged = o["repeated_value"] if "repeated_value" in o.columns else pd.Series(False, index=o.index)
        water["et_monthly"] = [
            {"date": d.strftime("%Y-%m"), "et": round(float(e), 1),
             "et_min": None if pd.isna(lo) else round(float(lo), 1),
             "et_max": None if pd.isna(hi) else round(float(hi), 1), "flagged": bool(fl),
             "et0_power": round(float(et0_ym.get((d.year, d.month), np.nan)), 1)}
            for d, e, lo, hi, fl in zip(o["date"], o["et_mm"], o["et_min_mm"], o["et_max_mm"], flagged)]
        oy = o.assign(year=o["date"].dt.year, gs=o["date"].dt.month.isin(growing))
        water["et_annual"] = [
            {"year": int(y), "et_mm": round(float(g["et_mm"].sum())), "months": int(len(g)),
             "growing_season_et_mm": round(float(g.loc[g["gs"], "et_mm"].sum()))}
            for y, g in oy.groupby("year")]
        full_years = [r for r in water["et_annual"] if r["months"] == 12]
        water["et_trend"] = theil_sen_trend([r["year"] for r in full_years], [r["et_mm"] for r in full_years])
    ov = None if et_valley is None or et_valley.empty else et_valley.assign(month=et_valley["date"].dt.month)
    oclim = None if not has_et else et.assign(month=et["date"].dt.month)
    norm = []
    for m in MONTHS:
        row = {"month": m, "et0_power": clim["et0_month"][m], "precip": clim["precip_month"][m],
               "balance": round(clim["precip_month"][m] - clim["et0_month"][m], 1)}
        if ov is not None:
            row["eto_ground"] = round(float(ov.loc[ov["month"] == m, "eto_mm"].mean()), 1)
        if oclim is not None:
            sel = oclim[oclim["month"] == m]
            if "repeated_value" in sel.columns:
                sel = sel[~sel["repeated_value"].astype(bool)]
            row["et_actual"] = round(float(sel["et_mm"].mean()), 1) if len(sel) else None
        norm.append(row)
    water["monthly_normals"] = norm

    imerg_year = {}
    if imerg is not None and len(imerg):
        iy = imerg.assign(year=pd.to_datetime(imerg["date"]).dt.year).groupby("year")["precip_mm"].agg(["sum", "count"])
        imerg_year = {int(y): round(float(r["sum"])) for y, r in iy.iterrows() if r["count"] >= 360}
    ground_year, eto_year = {}, {}
    if ov is not None:
        yr = ov.assign(year=ov["date"].dt.year).groupby("year")[["eto_mm", "pr_mm"]].sum()
        ground_year = {int(y): round(float(r["pr_mm"])) for y, r in yr.iterrows()}
        eto_year = {int(y): round(float(r["eto_mm"])) for y, r in yr.iterrows()}
    elif ground_daily is not None and len(ground_daily):
        gy = ground_daily.assign(year=ground_daily["date"].dt.year).groupby("year")["precip_mm"].agg(["sum", "count"])
        ground_year = {int(y): round(float(r["sum"])) for y, r in gy.iterrows() if r["count"] >= 360}
    years_cmp = sorted(y for y in (set(ground_year) | set(imerg_year)) if y >= 2016)
    p_years = set(p_ym.index.get_level_values(0))
    water["source_comparison"] = [
        {"year": y, "precip_used": round(float(p_ym.loc[y].sum())) if y in p_years else None,
         "precip_imerg_raw": imerg_year.get(y), "precip_ground": ground_year.get(y),
         "et0_power": round(float(et0_ym.loc[y].sum())) if y in p_years else None, "eto_ground": eto_year.get(y)}
        for y in years_cmp]
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
        "flood": flood, "phenology": phenology,
    }
    ev["history"] = history
    ev["history_kind"] = "crop_map" if from_history else "seasons"
    ev["soil"] = {**soil_ctx, "source": soil_source, "mapunits": (soil or {}).get("mapunits")} if soil else None
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
    frosty = sum(clim["frost_days_month"].values()) >= 5
    vul = []
    for m in growing:
        comp = {"heat": min(clim["hot_days_month"][m] / 10.0, 1.0),
                "frost": (min(clim["frost_days_month"][m] / 10.0, 1.0) if m in (5, 6, 7, 8, 9) else 0.0) if frosty else None,
                "water_gap": gap[m] / gap_max,
                "greenness_dips": dips.get(m),
                "dry_soil": (1.0 - sm_clim[m] / sm_max) if (sm_max and m in sm_clim) else None}
        vals = [v for v in comp.values() if v is not None]
        vul.append({"month": m, **{k: (None if v is None else round(v, 2)) for k, v in comp.items()},
                    "index": round(float(np.mean(vals)), 2)})
    top = sorted(vul, key=lambda r: -r["index"])[:2]
    ev["vulnerability"] = {"months": vul, "most_vulnerable": sorted(r["month"] for r in top),
                           "method": f"Each part is scaled 0-1 and averaged: hot days (>{hot_c} °C, 10 days = 1), "
                                     + ("frost days in May-September (10 days = 1), " if frosty else "")
                                     + "the gap between reference ET and rain, how often greenness fell well below "
                                       "its own normal, and how dry the SMAP soil-moisture pixel normally is."}
    bare = [m for m in MONTHS if (calendar[m]["low_cover_share"] or 0) >= 0.5]
    ev["bare"] = {"months_usually_low_cover": bare, "threshold_ndvi": LOW_COVER_NDVI,
                  "risk_months": peak_months,
                  "note": "Low green cover is not always bare soil: dormant crops and stubble still "
                          "protect the surface but look brown from space, and snow or floodwater hides the ground."}
    return clean(context), clean(ev)
