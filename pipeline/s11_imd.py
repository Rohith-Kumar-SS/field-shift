"""India Meteorological Department gridded rainfall and temperature (ground-based).

IMD's daily grids are interpolated from weather stations: rainfall from several thousand
rain gauges (0.25 degree), maximum and minimum temperature from about 400 stations
(1 degree). Here they play the role gridMET plays in Nevada: the ground-informed reference
that NASA POWER (and GPM IMERG rainfall) are corrected to, month by month.

Why it matters: NASA POWER comes from a global weather model that does not know the plains
are irrigated. Over Punjab its summer afternoons are 3-4 degC hotter than the stations
measure, which would overstate both heat stress and crop water demand.

Method (the delta method, same as for gridMET)
  temperature: delta = IMD monthly normal - NASA POWER monthly normal, added to every day
  rainfall:    ratio = IMD monthly normal / NASA POWER monthly normal, multiplied in

Outputs
  data/processed/<region>/ground_daily.parquet   daily rain (and Tmax/Tmin) for the IMD cells
  data/processed/<region>/power_bias.json        per field: monthly corrections and checks
"""
from __future__ import annotations

import json

import numpy as np
import pandas as pd

from .common import PILOT, PROCESSED, ROOT, SourceError, load_fields, run_source, sanity_range, write_status

SOURCE, TITLE, TIER = "imd", "IMD gridded daily rainfall and temperature (station based)", "OPTIONAL"
LABEL = "IMD weather-station grids (rain 0.25 degree, temperature 1 degree)"
LABEL_RAIN_ONLY = "IMD rain-gauge grid (0.25 degree)"
# 2001 onward: the same years as the IMERG satellite record it is compared with. Each yearly rain
# file is 25 MB for the whole country and the server is slow, so the files are shared by every region.
FIRST, LAST = 2001, 2025
SHARED = ROOT / "data" / "raw" / "_shared" / "imd"
EXT = {"rain": ".grd", "tmax": ".GRD", "tmin": ".GRD"}


def _have(var: str, year: int) -> bool:
    f = SHARED / var / f"{year}{EXT[var]}"
    return f.exists() and f.stat().st_size > (1_000_000 if var == "rain" else 100_000)


def load_imd(var: str = "rain") -> "tuple[object, int]":
    """Download (or reuse) IMD yearly files. Returns (xarray dataset, last year available)."""
    import imdlib as imd

    SHARED.mkdir(parents=True, exist_ok=True)
    last = None
    for year in range(LAST, LAST - 4, -1):          # the newest year is published late
        try:
            if not _have(var, year):
                imd.get_data(var, year, year, fn_format="yearwise", file_dir=str(SHARED))
            if _have(var, year):
                last = year
                break
        except Exception:  # noqa: BLE001
            continue
    if last is None:
        raise SourceError(f"IMD gridded {var} could not be downloaded",
                          action="imdpune.gov.in may be unreachable; re-run `python tasks.py data imd`. "
                                 "Without it the weather is used as downloaded (no ground correction) and the app says so.")
    for y in range(FIRST, last):
        if not _have(var, y):
            imd.get_data(var, y, y, fn_format="yearwise", file_dir=str(SHARED))
    return imd.open_data(var, FIRST, last, "yearwise", str(SHARED)).get_xarray(), last


def nearest_valid(da, lat: float, lon: float, bad_above: float = 90.0):
    """Nearest grid cell that actually holds data (coastal and border cells can be empty)."""
    lats, lons = da["lat"].values, da["lon"].values
    order = sorted(((la - lat) ** 2 + (lo - lon) ** 2, la, lo) for la in lats for lo in lons)
    for dist, la, lo in order[:9]:
        s = da.sel(lat=la, lon=lo).to_series()
        s = s.where((s < bad_above) & (s > -90))
        if s.notna().mean() > 0.9:
            return s, float(la), float(lo)
    return None, None, None


def main() -> None:
    from engine.agromet import LAPSE_RATE

    fields = load_fields()
    ds, last = load_imd("rain")
    temp = {}
    try:
        for var in ("tmax", "tmin"):
            temp[var], _ = load_imd(var)
    except Exception as exc:  # noqa: BLE001  temperature is a bonus: rain alone is still useful
        print(f"  IMD temperature not available ({type(exc).__name__}); using elevation shift only", flush=True)
        temp = {}
    power = pd.read_parquet(PROCESSED / "power_daily.parquet")
    cells_meta = json.loads((PROCESSED / "power_cells.json").read_text(encoding="utf-8"))
    terrain_path = PROCESSED / "field_terrain.parquet"
    terrain = pd.read_parquet(terrain_path).set_index("field_id") if terrain_path.exists() else None
    hot_c = float(PILOT.get("hot_day_c", 40))

    frames, done, bias, tcells = [], {}, {}, {}
    for _, f in fields.iterrows():
        cell = ds["rain"].sel(lat=float(f["lat"]), lon=float(f["lon"]), method="nearest")
        cid = f"I{float(cell['lat']):.2f}_{float(cell['lon']):.2f}"
        if cid not in done:
            s = cell.to_series()
            s[s < 0] = np.nan                       # IMD fill value is -999
            df = pd.DataFrame({"cell_id": cid, "date": pd.to_datetime(s.index), "precip_mm": s.values})
            for var in temp:                        # station temperature for the 1-degree cell around it
                ts, la, lo = nearest_valid(temp[var][var], float(cell["lat"]), float(cell["lon"]))
                if ts is not None:
                    df[f"{var}_c"] = ts.reindex(pd.to_datetime(s.index)).values
                    tcells[cid] = f"{la:.1f}N {lo:.1f}E"
            done[cid] = df
            frames.append(df)
        gdf = done[cid].set_index("date")
        g = gdf["precip_mm"]
        pcell = cells_meta["field_to_cell"][f["field_id"]]
        pw = power[power["cell_id"] == pcell].set_index("date")
        p = pw["PRECTOTCORR"].reindex(g.index)
        month = g.index.month
        ratio = {}
        for m in range(1, 13):
            pp, gp = p[month == m].mean(), g[month == m].mean()
            # dry-season months with almost no rain give meaningless ratios: leave them at 1
            ratio[m] = round(float(np.clip(gp / pp, 0.3, 3.0)), 3) if (pp > 0.2 and gp > 0.2) else 1.0
        grid_elev = cells_meta["cells"][pcell]["grid_elevation_m"]
        elev = float(terrain.loc[f["field_id"], "elevation_m"]) if terrain is not None and f["field_id"] in terrain.index else grid_elev
        shift = round(LAPSE_RATE * (grid_elev - elev), 2)
        check = {"annual_precip_power_mm": round(float(p.groupby(p.index.year).sum().mean())),
                 "annual_precip_ground_mm": round(float(g.groupby(g.index.year).sum().mean())),
                 "power_grid_elevation_m": grid_elev, "field_elevation_m": round(elev, 1)}
        has_temp = "tmax_c" in gdf and "tmin_c" in gdf
        if has_temp:
            dmax, dmin = {}, {}
            pmax, pmin = pw["T2M_MAX"].reindex(g.index), pw["T2M_MIN"].reindex(g.index)
            for m in range(1, 13):
                sel = (month == m) & gdf["tmax_c"].notna().to_numpy() & gdf["tmin_c"].notna().to_numpy()
                dmax[m] = round(float(gdf.loc[sel, "tmax_c"].mean() - pmax[sel].mean()), 2)
                dmin[m] = round(float(gdf.loc[sel, "tmin_c"].mean() - pmin[sel].mean()), 2)
            years = g.index.year.nunique()
            check.update(
                temperature_cell=tcells.get(cid),
                mean_tmax_delta_c=round(float(np.mean(list(dmax.values()))), 2),
                mean_tmin_delta_c=round(float(np.mean(list(dmin.values()))), 2),
                largest_tmax_delta_c=min(dmax.values(), key=lambda v: -abs(v)),
                hot_day_c=hot_c,
                hot_days_power=round(float((pmax > hot_c).sum() / years), 1),
                hot_days_ground=round(float((gdf["tmax_c"] > hot_c).sum() / years), 1))
        else:
            dmax = dmin = {m: shift for m in range(1, 13)}
            check["temperature_shift_c"] = shift
        bias[f["field_id"]] = {
            "ground_cell": cid, "label": LABEL if has_temp else LABEL_RAIN_ONLY,
            "temperature_method": "imd" if has_temp else "lapse",
            "tmax_delta": dict(dmax), "tmin_delta": dict(dmin), "precip_ratio": ratio, "check": check,
        }
    daily = pd.concat(frames, ignore_index=True)
    daily.to_parquet(PROCESSED / "ground_daily.parquet", index=False)
    (PROCESSED / "power_bias.json").write_text(json.dumps(bias, indent=1), encoding="utf-8")

    first = next(iter(bias.values()))["check"]
    annual = daily.groupby(["cell_id", daily["date"].dt.year])["precip_mm"].sum()
    checks = [sanity_range(daily["precip_mm"].dropna(), 0, 600, "daily rainfall mm"),
              sanity_range(annual, 100, 4000, "annual rainfall mm")]
    with_temp = "tmax_c" in daily
    if with_temp:
        checks += [sanity_range(daily["tmax_c"].dropna(), 5, 50, "tmax degC"),
                   sanity_range(daily["tmin_c"].dropna(), -5, 38, "tmin degC")]
    ok = all(c["passed"] for c in checks)
    temp_msg = (f"; NASA POWER afternoons differ from the stations by {first['mean_tmax_delta_c']:+.1f} degC on "
                f"average (largest month {first['largest_tmax_delta_c']:+.1f}): days above {hot_c:.0f} degC "
                f"{first['hot_days_power']:.0f} -> {first['hot_days_ground']:.0f} a year") if with_temp else \
        "; temperature grid not available, elevation shift only"
    write_status(
        SOURCE, status="ok" if ok else "partial", title=TITLE, tier=TIER,
        fetched=f"daily rainfall{' and Tmax/Tmin' if with_temp else ''} {FIRST}-{last} for {len(done)} cell(s) "
                "under the pilot fields",
        resolution="rain 0.25 degree (~27 km); temperature 1 degree (~100 km); daily",
        date_range=f"{FIRST}-01-01 to {last}-12-31",
        credit="Pai, D. S. et al. (2014). Development of a new high spatial resolution (0.25 x 0.25 degree) "
               "long period (1901-2010) daily gridded rainfall data set over India. Mausam 65: 1-18. "
               "Srivastava, A. K., Rajeevan, M. & Kshirsagar, S. R. (2009). Development of a high resolution daily "
               "gridded temperature data set (1969-2005) for the Indian region. Atmospheric Science Letters 10: "
               "249-254. India Meteorological Department, Pune. Read with the imdlib package (Nandi & Patel 2022).",
        access="imdpune.gov.in yearly binary grids via imdlib",
        message=f"{len(done)} cell(s); mean annual rain {first['annual_precip_ground_mm']} mm (NASA POWER: "
                f"{first['annual_precip_power_mm']} mm){temp_msg}; sanity {'passed' if ok else 'CHECK'}",
        sanity={"checks": checks, "example_field_check": first},
        outputs=["ground_daily.parquet", "power_bias.json"],
        notes="Interpolated from stations, so it is ground truth at the stations and an estimate between them. "
              "One rain cell (27 km) or temperature cell (100 km) covers the whole pilot box, so it corrects the "
              "average level of the weather record, not field-to-field differences.",
    )


if __name__ == "__main__":
    run_source(SOURCE, TITLE, TIER, main)
