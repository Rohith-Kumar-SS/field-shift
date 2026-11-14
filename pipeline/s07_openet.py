"""OpenET field-scale evapotranspiration (STRONG tier). Needs OPENET_API_KEY.

For every pilot field: monthly actual ET from the six-model OpenET ensemble, plus the
ensemble's own spread (lowest and highest model after outlier removal). For the valley:
monthly reference ET and precipitation from gridMET (4 km, station-informed).

Quota care: the free tier allows 100 requests a month. This script makes
3 x (number of fields) + 2 requests once; every response is cached and never repeated.

Outputs
  data/processed/openet_field_monthly.parquet   field_id, date, et_mm, et_min_mm, et_max_mm
  data/processed/openet_valley_monthly.parquet  date, eto_mm, pr_mm (gridMET at the pilot centre)
"""
from __future__ import annotations

import pandas as pd

from .common import PILOT, PROCESSED, SourceError, load_fields, run_source, sanity_range, write_status
from .openet import account_limits, openet_post

SOURCE, TITLE, TIER = "openet", "OpenET ensemble evapotranspiration (field scale)", "STRONG"
START, END = "2016-01-01", "2025-12-31"
FIELD_VARS = {"ET": "et_mm", "et_mad_min": "et_min_mm", "et_mad_max": "et_max_mm"}
POINT_VARS = {"ETo": "eto_mm", "PR": "pr_mm"}


def _series(res, name: str) -> pd.Series:
    df = pd.DataFrame(res)
    if df.empty or "time" not in df.columns:
        return pd.Series(dtype="float64", name=name)
    val = [c for c in df.columns if c != "time"][0]
    s = pd.Series(pd.to_numeric(df[val], errors="coerce").values,
                  index=pd.to_datetime(df["time"]), name=name)
    return s


def field_request(geom, variable: str):
    coords = [round(v, 6) for xy in list(geom.exterior.coords)[:-1] for v in xy[:2]]
    return openet_post("/raster/timeseries/polygon", {
        "date_range": [START, END], "interval": "monthly", "geometry": coords,
        "model": "Ensemble", "variable": variable, "reference_et": "gridMET",
        "reducer": "mean", "units": "mm", "file_format": "JSON"})


def point_request(variable: str):
    return openet_post("/raster/timeseries/point", {
        "date_range": [START, END], "interval": "monthly", "geometry": PILOT["centroid"],
        "model": "Ensemble", "variable": variable, "reference_et": "gridMET",
        "units": "mm", "file_format": "JSON"})


def main() -> None:
    fields = load_fields()
    frames, problems = [], []
    for _, f in fields.iterrows():
        cols = {}
        for var, col in FIELD_VARS.items():
            try:
                cols[col] = _series(field_request(f.geometry, var), col)
            except SourceError as exc:
                if "quota" in str(exc).lower() or exc.action:
                    problems.append(f"{f['field_id']} {var}: {exc}")
                    if "quota" in str(exc).lower():
                        break
                else:
                    problems.append(f"{f['field_id']} {var}: {str(exc)[:120]}")
        if "et_mm" in cols:
            df = pd.concat(cols.values(), axis=1).reset_index().rename(columns={"index": "date", "time": "date"})
            df.insert(0, "field_id", f["field_id"])
            frames.append(df)
    if not frames:
        raise SourceError("OpenET returned no field time series: " + "; ".join(problems[:3]),
                          action="Check OPENET_API_KEY and the monthly quota (python -m pipeline.check_access).")
    out = pd.concat(frames, ignore_index=True)
    for col in FIELD_VARS.values():
        if col not in out.columns:
            out[col] = float("nan")
    # OpenET repeats one value across months it could not resolve (seen in winter): flag them
    out = out.sort_values(["field_id", "date"])
    same = out.groupby("field_id")["et_mm"].diff().abs() < 1e-6
    out["repeated_value"] = same | same.groupby(out["field_id"]).shift(-1, fill_value=False)
    out.to_parquet(PROCESSED / "openet_field_monthly.parquet", index=False)

    valley = {}
    for var, col in POINT_VARS.items():
        try:
            valley[col] = _series(point_request(var), col)
        except SourceError as exc:
            problems.append(f"valley {var}: {str(exc)[:120]}")
    if valley:
        v = pd.concat(valley.values(), axis=1).reset_index().rename(columns={"index": "date", "time": "date"})
        v.to_parquet(PROCESSED / "openet_valley_monthly.parquet", index=False)

    annual = out.groupby(["field_id", out["date"].dt.year])["et_mm"].sum()
    grow = out[out["date"].dt.month.isin([5, 6, 7, 8, 9]) & (out["et_mm"] > 20)]
    spread = (grow["et_max_mm"] - grow["et_min_mm"]) / grow["et_mm"]     # growing season only
    checks = [sanity_range(out["et_mm"], 0, 320, "monthly ET mm"),
              sanity_range(annual, 50, 1500, "annual ET mm (idle pivots can be very low)")]
    if valley.get("eto_mm") is not None:
        checks.append(sanity_range(valley["eto_mm"], 5, 330, "monthly gridMET reference ET mm"))
    ok = all(c["passed"] for c in checks) and out["field_id"].nunique() == len(fields)
    limits = account_limits()
    write_status(
        SOURCE, status="ok" if (ok and not problems) else "partial", title=TITLE, tier=TIER,
        fetched=f"monthly ensemble ET, ensemble minimum and maximum for {out['field_id'].nunique()} fields; "
                f"gridMET reference ET and precipitation at the pilot centre. Quota now: "
                f"{limits.get('Monthly Requests', 'unknown')}",
        resolution="30 m (Landsat thermal driven), aggregated to the field polygon; monthly",
        date_range=f"{out['date'].min():%Y-%m} to {out['date'].max():%Y-%m}",
        credit="OpenET (Melton et al. 2022, JAWRA). Ensemble of ALEXI/DisALEXI, eeMETRIC, geeSEBAL, "
               "PT-JPL, SIMS and SSEBop, built on Landsat and gridMET. CC BY 4.0.",
        access="OpenET API https://openet-api.org/raster/timeseries/polygon and /point",
        message=f"{len(out):,} field-months for {out['field_id'].nunique()} fields; May-Sep model spread "
                f"(max - min) is a median {spread.median() * 100:.0f} % of ET; {int(out['repeated_value'].sum())} repeated-value "
                f"months flagged; sanity {'passed' if ok else 'CHECK'}"
                + (f"; problems: {'; '.join(problems[:3])}" if problems else ""),
        sanity={"checks": checks, "median_growing_season_model_spread_fraction": round(float(spread.median()), 3),
                "repeated_value_months": int(out["repeated_value"].sum())},
        outputs=["openet_field_monthly.parquet", "openet_valley_monthly.parquet"],
        notes="A model estimate of water actually evaporated and transpired, not a flow-meter "
              "reading. The newest six months can still be revised. Winter values are the least "
              "reliable (snow, few clear images) and some are repeated across months; those are "
              "flagged and left out of seasonal statistics. The field-boundary and field-ID "
              "endpoints (/geodatabase/...) returned HTTP 400 for every request, so polygons "
              "detected by this project are sent to the raster endpoint instead.",
    )


if __name__ == "__main__":
    run_source(SOURCE, TITLE, TIER, main)
