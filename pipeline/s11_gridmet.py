"""gridMET daily temperature and precipitation (OPTIONAL tier, ground-informed). No key needed.

Why it is here: NASA POWER's weather comes from a ~50 km reanalysis cell whose average
elevation is 2,025 m and which cannot see cold air pooling on a valley floor at 1,800 m.
gridMET (Abatzoglou 2013) blends PRISM's station-and-terrain climatology with NLDAS-2 at
4 km, and is the weather dataset behind OpenET. We use it for one thing: a month-by-month
bias correction of NASA POWER's Tmax, Tmin and precipitation at each field
("delta method": add the difference of the monthly normals for temperature, multiply by
the ratio of the monthly normals for precipitation). NASA POWER still supplies every
daily value, plus radiation, humidity and wind.

Outputs
  data/processed/gridmet_daily.parquet   daily tmax, tmin, precip per 4 km cell
  data/processed/power_bias.json         per field: monthly corrections and what they changed
"""
from __future__ import annotations

import json
import re
from datetime import date

import numpy as np
import pandas as pd
import requests

from .common import (CLIMATE_END, CLIMATE_START, PROCESSED, SourceError, cache_path, load_fields,
                     run_source, sanity_range, write_status)

SOURCE, TITLE, TIER = "gridmet", "gridMET daily temperature and precipitation (4 km)", "OPTIONAL"
BASE = "http://thredds.northwestknowledge.net:8080/thredds/dodsC/agg_met_{var}_1979_CurrentYear_CONUS.nc"
VARS = {"tmmx": ("daily_maximum_temperature", "tmax_c"), "tmmn": ("daily_minimum_temperature", "tmin_c"),
        "pr": ("precipitation_amount", "precip_mm")}
LAT0, LON0, STEP = 49.4, -124.7666666333333, 1.0 / 24.0     # grid origin (cell centres)
DAY0 = date(1979, 1, 1)


def cell_index(lon: float, lat: float) -> tuple[int, int]:
    return int(round((LAT0 - lat) / STEP)), int(round((lon - LON0) / STEP))


def packing(var: str) -> tuple[float, float, float]:
    """scale_factor, add_offset and fill value, read from the dataset's own metadata.

    They differ between variables (Tmax is packed with a different offset from Tmin), so
    they are never assumed.
    """
    url = BASE.format(var=var) + ".das"
    path = cache_path(SOURCE, url, ".txt")
    if path.exists() and path.stat().st_size > 0:
        text = path.read_text(encoding="utf-8")
    else:
        r = requests.get(url, timeout=120)
        if r.status_code != 200:
            raise SourceError(f"gridMET metadata request failed (HTTP {r.status_code})")
        text = r.text
        path.write_text(text, encoding="utf-8")
    block = text.split(VARS[var][0] + " {", 1)[1].split("}", 1)[0]

    def attr(name: str, default: float | None = None) -> float:
        m = re.search(rf"{name}\s+(-?[\d.eE+-]+)", block)
        if not m:
            if default is None:
                raise SourceError(f"gridMET metadata for {var} has no {name}")
            return default
        return float(m.group(1))

    return attr("scale_factor"), attr("add_offset", 0.0), attr("_FillValue", 32767.0)


def fetch_cell(var: str, i: int, j: int) -> np.ndarray:
    name = VARS[var][0]
    t0 = (date(CLIMATE_START, 1, 1) - DAY0).days
    t1 = (date(CLIMATE_END, 12, 31) - DAY0).days
    url = BASE.format(var=var) + f".ascii?{name}.{name}[{t0}:{t1}][{i}:{i}][{j}:{j}]"
    path = cache_path(SOURCE, url, ".txt")
    if path.exists() and path.stat().st_size > 0:
        text = path.read_text(encoding="utf-8")
    else:
        last = ""
        for _ in range(4):
            try:
                r = requests.get(url, timeout=300)
                if r.status_code == 200 and "Error {" not in r.text[:200]:
                    text = r.text
                    path.write_text(text, encoding="utf-8")
                    break
                last = f"HTTP {r.status_code}"
            except requests.RequestException as exc:
                last = type(exc).__name__
        else:
            raise SourceError(f"gridMET OPeNDAP request failed ({last})",
                              action="The University of Idaho THREDDS server may be down; re-run "
                                     "`python -m pipeline.s11_gridmet` later. Without it the app falls "
                                     "back to a plain elevation (lapse-rate) adjustment and says so.")
    vals = [int(m.group(1)) for m in re.finditer(r"^\[\d+\]\[\d+\], (-?\d+)\s*$", text, re.M)]
    if len(vals) != t1 - t0 + 1:
        raise SourceError(f"gridMET returned {len(vals)} values, expected {t1 - t0 + 1}")
    a = np.array(vals, dtype="float64")
    scale, offset, fill = packing(var)
    a[a == fill] = np.nan
    a = a * scale + offset                       # unpack with the file's own attributes
    return a if var == "pr" else a - 273.15      # mm, or Kelvin -> degC


def main() -> None:
    fields = load_fields()
    power = pd.read_parquet(PROCESSED / "power_daily.parquet")
    cells_meta = json.loads((PROCESSED / "power_cells.json").read_text(encoding="utf-8"))
    dates = pd.date_range(f"{CLIMATE_START}-01-01", f"{CLIMATE_END}-12-31", freq="D")
    frames, field_cell = [], {}
    done: dict[tuple[int, int], pd.DataFrame] = {}
    for _, f in fields.iterrows():
        i, j = cell_index(float(f["lon"]), float(f["lat"]))
        field_cell[f["field_id"]] = f"M{i}_{j}"
        if (i, j) in done:
            continue
        df = pd.DataFrame({"date": dates, "cell_id": f"M{i}_{j}"})
        for var, (_, col) in VARS.items():
            df[col] = fetch_cell(var, i, j)
        df["lat"], df["lon"] = LAT0 - i * STEP, LON0 + j * STEP
        done[(i, j)] = df
        frames.append(df)
    daily = pd.concat(frames, ignore_index=True)
    daily.to_parquet(PROCESSED / "gridmet_daily.parquet", index=False)

    from engine.agromet import frost_dates, theil_sen_trend
    bias = {}
    for fid, gcell in field_cell.items():
        g = daily[daily["cell_id"] == gcell].set_index("date")
        pcell = cells_meta["field_to_cell"][fid]
        p = power[power["cell_id"] == pcell].set_index("date").reindex(g.index)
        month = g.index.month
        rec = {"gridmet_cell": gcell, "tmax_delta": {}, "tmin_delta": {}, "precip_ratio": {}}
        for m in range(1, 13):
            sel = month == m
            rec["tmax_delta"][m] = round(float(g.loc[sel, "tmax_c"].mean() - p.loc[sel, "T2M_MAX"].mean()), 2)
            rec["tmin_delta"][m] = round(float(g.loc[sel, "tmin_c"].mean() - p.loc[sel, "T2M_MIN"].mean()), 2)
            pp, gp = p.loc[sel, "PRECTOTCORR"].mean(), g.loc[sel, "precip_mm"].mean()
            rec["precip_ratio"][m] = round(float(np.clip(gp / pp, 0.3, 3.0)), 3) if pp > 0 else 1.0
        # what the correction changes, for the data log and the "satellite vs ground" explainer
        def ff(tmin: pd.Series) -> float:
            vals = [frost_dates(list(s.index.dayofyear), list(s.values), 0.0)[2]
                    for y, s in tmin.groupby(tmin.index.year) if 1996 <= y <= 2025]
            return float(np.median(vals))
        corrected_tmin = p["T2M_MIN"] + pd.Series(month, index=g.index).map(rec["tmin_delta"])
        corrected_tmax = p["T2M_MAX"] + pd.Series(month, index=g.index).map(rec["tmax_delta"])

        def hot_trend(tmax: pd.Series) -> dict:
            n = (tmax > 32).groupby(tmax.index.year).sum()
            t = theil_sen_trend(n.index, n.values)
            return {"mean_days": round(float(n.mean()), 1), "per_decade": t["slope_per_decade"],
                    "p_value": t["p_value"]}
        grid_elev = cells_meta["cells"][pcell]["grid_elevation_m"]
        rec["check"] = {
            "frost_free_days_power_raw": ff(p["T2M_MIN"]),
            "frost_free_days_power_corrected": ff(corrected_tmin),
            "frost_free_days_gridmet": ff(g["tmin_c"]),
            "annual_precip_power_mm": round(float(p["PRECTOTCORR"].groupby(p.index.year).sum().mean())),
            "annual_precip_gridmet_mm": round(float(g["precip_mm"].groupby(g.index.year).sum().mean())),
            "mean_tmin_delta_c": round(float(np.mean(list(rec["tmin_delta"].values()))), 2),
            "mean_tmax_delta_c": round(float(np.mean(list(rec["tmax_delta"].values()))), 2),
            "power_grid_elevation_m": grid_elev,
            "days_over_32_power_corrected": hot_trend(corrected_tmax),
            "days_over_32_gridmet": hot_trend(g["tmax_c"]),
        }
        bias[fid] = rec
    (PROCESSED / "power_bias.json").write_text(json.dumps(bias, indent=1), encoding="utf-8")

    first = next(iter(bias.values()))["check"]
    checks = [sanity_range(daily["tmax_c"], -30, 48, "tmax degC"),
              sanity_range(daily["tmin_c"], -45, 30, "tmin degC"),
              sanity_range(daily["precip_mm"], 0, 120, "daily precipitation mm")]
    ok = all(c["passed"] for c in checks)
    write_status(
        SOURCE, status="ok" if ok else "partial", title=TITLE, tier=TIER,
        fetched=f"daily Tmax, Tmin and precipitation for {len(done)} cells of 4 km under the pilot fields",
        resolution="1/24 degree (~4 km); daily",
        date_range=f"{CLIMATE_START}-01-01 to {CLIMATE_END}-12-31",
        credit="Abatzoglou, J. T. (2013). Development of gridded surface meteorological data for "
               "ecological applications and modelling. Int. J. Climatol. 33: 121-131. Public domain (CC0).",
        access="OPeNDAP, University of Idaho / Northwest Knowledge Network THREDDS "
               "(thredds.northwestknowledge.net)",
        message=f"{len(done)} cells; NASA POWER nights are {abs(first['mean_tmin_delta_c']):.1f} degC too "
                f"{'warm' if first['mean_tmin_delta_c'] < 0 else 'cold'} for the valley floor: frost-free "
                f"season {first['frost_free_days_power_raw']:.0f} days raw -> "
                f"{first['frost_free_days_power_corrected']:.0f} corrected (gridMET itself: "
                f"{first['frost_free_days_gridmet']:.0f}); annual rain {first['annual_precip_power_mm']} mm "
                f"-> {first['annual_precip_gridmet_mm']} mm; sanity {'passed' if ok else 'CHECK'}",
        sanity={"checks": checks, "example_field_check": first},
        outputs=["gridmet_daily.parquet", "power_bias.json"],
        notes="Used only to bias-correct NASA POWER (monthly delta method). Still a 4 km grid: the "
              "coldest hollows frost earlier and later than it shows.",
    )


if __name__ == "__main__":
    run_source(SOURCE, TITLE, TIER, main)
