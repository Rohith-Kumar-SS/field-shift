"""Data-processing functions: zonal statistics, grids, crop-history interpretation."""
import numpy as np
import pandas as pd
import pytest
from affine import Affine
from shapely.geometry import box

from engine.context import clean, landsat_monthly, low_cover_calendar, peak_ndvi_by_year, water_calibration
from engine.history import existing_rotation, interpret_history
from pipeline.s03_smap import ease_window
from pipeline.s06_landsat import target_grid
from pipeline.s08_srtm import slope_percent, tile_names
from pipeline.s11_gridmet import cell_index
from pipeline.zonal import coverage_weights, grid_cell_weights, weighted_fractions, weighted_mean

T = Affine(10, 0, 0, 0, -10, 40)        # 4 x 4 grid of 10 m cells, origin top-left (0, 40)


def test_coverage_weights_are_area_fractions():
    w = coverage_weights(box(5, 15, 25, 35), T, (4, 4), supersample=10)
    assert w.sum() * 100 == pytest.approx(400.0)        # polygon area in m2
    assert w[1, 1] == pytest.approx(1.0)                # fully inside
    assert w[0, 0] == pytest.approx(0.25)               # corner cell: quarter covered
    assert w[3, 3] == 0.0


def test_weighted_mean_is_area_weighted_and_ignores_nan():
    w = coverage_weights(box(0, 20, 20, 40), T, (4, 4), supersample=5)
    vals = np.zeros((4, 4))
    vals[0, 0], vals[0, 1], vals[1, 0], vals[1, 1] = 1.0, 2.0, 3.0, np.nan
    mean, frac = weighted_mean(vals, w)
    assert mean == pytest.approx(2.0) and frac == pytest.approx(0.75)
    assert np.isnan(weighted_mean(vals, w, min_valid_fraction=0.9)[0])
    assert np.isnan(weighted_mean(vals, np.zeros((4, 4)))[0])


def test_weighted_fractions_sum_to_one():
    w = coverage_weights(box(0, 0, 40, 40), T, (4, 4), supersample=2)
    classes = np.array([[36] * 4, [36] * 4, [36] * 4, [24] * 4])
    fr = weighted_fractions(classes, w)
    assert fr == {24: pytest.approx(0.25), 36: pytest.approx(0.75)}


def test_grid_cell_weights_handles_ascending_latitudes():
    lons, lats = np.array([-116.05, -115.95]), np.array([39.65, 39.75])       # ascending
    w = grid_cell_weights(box(-116.02, 39.72, -116.01, 39.73), lons, lats)
    assert w.shape == (2, 2) and w[1, 0] > 0 and w[0, 0] == 0 and w[1, 1] == 0


def test_landsat_grid_is_aligned_to_30_m_pixel_edges():
    transform, shape, bounds = target_grid()
    assert (transform.c - 15) % 30 == 0 and (transform.f - 15) % 30 == 0
    assert shape[0] > 300 and shape[1] > 300
    assert bounds[2] - bounds[0] == shape[1] * 30


def test_index_helpers():
    assert tile_names([-116.08, 39.62, -115.95, 39.75]) == ["N39W117", "N39W116"]
    r0, r1, c0, c1 = ease_window([-116.08, 39.62, -115.95, 39.75])
    assert 0 < r0 <= r1 < 1624 and 0 < c0 <= c1 < 3856
    i, j = cell_index(-116.0, 39.7)
    assert 0 < i < 585 and 0 < j < 1386


def test_slope_of_a_tilted_plane():
    cols = np.tile(np.arange(20) * 30.0, (20, 1))
    plane = 1800 + 0.02 * cols                        # 2 % tilt to the east
    assert slope_percent(plane)[5:15, 5:15].mean() == pytest.approx(2.0, abs=0.01)


# ---------------------------------------------------------------------------
# Crop history
# ---------------------------------------------------------------------------
def _row(year, code, name, share=0.95):
    return {"year": year, "cdl_code": code, "cdl_name": name, "share": share}


def test_history_cross_checks_the_crop_map_with_greenness(kb):
    rows = [_row(2019, 152, "Shrubland"), _row(2020, 36, "Alfalfa"), _row(2021, 142, "Evergreen Forest"),
            _row(2022, 36, "Alfalfa"), _row(2023, 36, "Alfalfa", share=0.4), _row(2024, 37, "Other Hay/Non Alfalfa")]
    peaks = {2019: 0.18, 2020: 0.85, 2021: 0.88, 2022: 0.86, 2023: 0.86, 2024: 0.8}
    h = {r["year"]: r for r in interpret_history(rows, peaks, kb)}
    assert h[2019]["crop"] == "fallow" and not h[2019]["doubtful"]        # brown + non-crop: consistent
    assert h[2020]["crop"] == "alfalfa_est"                               # alfalfa after an idle year
    assert h[2021]["crop"] == "alfalfa" and h[2021]["doubtful"]           # "forest" on a green pivot
    assert "probably wrong" in h[2021]["note"]
    assert h[2023]["doubtful"]                                            # only 40 % of the field
    assert h[2024]["crop"] == "grass_hay" and h[2024]["doubtful"]


def test_history_flags_a_crop_label_on_a_brown_field(kb):
    h = interpret_history([_row(2024, 36, "Alfalfa")], {2024: 0.2}, kb)
    assert h[0]["doubtful"] and "stayed brown" in h[0]["note"]


def test_existing_rotation_states_its_assumption(kb):
    hist = interpret_history([_row(y, 36, "Alfalfa") for y in range(2018, 2026)],
                             {y: 0.85 for y in range(2018, 2026)}, kb)
    rot = existing_rotation(hist, kb)
    assert rot["is_existing"] and len(rot["years"]) == 8
    assert rot["years"][0][0]["crop"] == "alfalfa_est"
    assert rot["assumptions"] and "re-sown" in rot["assumptions"][0]
    assert "alfalfa in 8 of 8 years" in rot["summary"]


# ---------------------------------------------------------------------------
# Landsat summaries and OpenET anchoring
# ---------------------------------------------------------------------------
def _obs():
    dates = pd.date_range("2022-01-10", "2023-12-25", freq="16D")
    ndvi = np.where(dates.month.isin([5, 6, 7, 8, 9]), 0.8, 0.15)
    snow = np.where(dates.month.isin([1, 12]), 0.9, 0.0)
    return pd.DataFrame({"date": dates, "ndvi": ndvi, "snow_frac": snow})


def test_landsat_summaries():
    obs = _obs()
    monthly = landsat_monthly(obs)
    cal = low_cover_calendar(monthly)
    assert cal[7]["low_cover_share"] == 0.0 and cal[3]["low_cover_share"] == 1.0
    assert cal[1]["snow_share"] == 1.0 and cal[1]["low_cover_share"] is None     # snow is not "bare"
    peaks = peak_ndvi_by_year(obs)
    assert peaks[2022] == pytest.approx(0.8) and peaks[2023] == pytest.approx(0.8)


def test_water_calibration_needs_clean_alfalfa_years(kb):
    prep = pd.DataFrame({"year": np.repeat([2022, 2023], 12), "month": np.tile(np.arange(1, 13), 2),
                         "et0": np.tile([20, 35, 70, 110, 160, 200, 230, 200, 140, 80, 35, 20], 2).astype(float)})
    kc = kb["crops"]["alfalfa"]["kc"]
    full = sum(kc[m] * e for m, e in zip(range(5, 10), [160, 200, 230, 200, 140]))
    dates = pd.to_datetime([f"{y}-{m:02d}-01" for y in (2022, 2023) for m in range(1, 13)])
    openet = pd.DataFrame({"date": dates, "et_mm": np.tile(np.array(
        [10, 15, 30, 50, 0.8 * 0.9 * 160, 0.8 * 0.95 * 200, 0.8 * 0.95 * 230, 0.8 * 0.95 * 200,
         0.8 * 0.9 * 140, 40, 15, 10]), 2), "repeated_value": False})
    hist = [{"year": 2022, "crop": "alfalfa", "doubtful": False}, {"year": 2023, "crop": "alfalfa", "doubtful": False}]
    cal = water_calibration(openet, hist, prep, kb)
    assert cal["available"] and cal["factor"] == pytest.approx(0.8, abs=0.01)
    assert cal["rows"][0]["textbook_mm"] == round(full)
    one_year = water_calibration(openet, hist[:1], prep, kb)
    assert not one_year["available"] and one_year["factor"] == 1.0
    assert not water_calibration(None, hist, prep, kb)["available"]


def test_clean_makes_everything_json_safe():
    out = clean({"a": np.float64("nan"), "b": np.int64(3), "c": [np.float32(1.5), float("inf")],
                 "d": pd.Timestamp("2024-05-01"), 5: np.bool_(True)})
    assert out == {"a": None, "b": 3, "c": [1.5, None], "d": "2024-05-01", "5": True}


def test_field_precip_uses_imerg_where_it_exists_and_corrected_power_elsewhere():
    from engine.climate import field_precip, prepare_daily

    power = pd.DataFrame({"date": pd.date_range("2000-12-30", "2001-01-03"), "PRECTOTCORR": 2.0})
    imerg = pd.DataFrame({"date": pd.to_datetime(["2001-01-01", "2001-01-02"]), "precip_mm": [10.0, 0.0]})
    bias = {"precip_ratio": {m: 0.5 for m in range(1, 13)}, "imerg_precip_ratio": {str(m): 0.8 for m in range(1, 13)},
            "tmax_delta": {m: 0.0 for m in range(1, 13)}, "tmin_delta": {m: 0.0 for m in range(1, 13)}}
    s = field_precip(power, imerg, bias)
    assert s.loc["2000-12-31"] == pytest.approx(1.0)        # no IMERG yet: NASA POWER x its correction
    assert s.loc["2001-01-01"] == pytest.approx(8.0)        # IMERG x its own correction
    assert s.loc["2001-01-02"] == 0.0                       # a dry IMERG day stays dry
    assert s.loc["2001-01-03"] == pytest.approx(1.0)
    raw = field_precip(power, imerg, None)
    assert raw.loc["2001-01-01"] == 10.0 and raw.loc["2000-12-30"] == 2.0
    assert field_precip(power, None, bias) is None and field_precip(power, imerg.iloc[:0], bias) is None

    # and the series reaches the daily frame unchanged (no second correction on top)
    full = power.assign(T2M_MAX=20.0, T2M_MIN=5.0, T2MDEW=2.0, WS2M=2.0, ALLSKY_SFC_SW_DWN=10.0)
    prep = prepare_daily(full, 39.7, 1800, 1800, precip=s, bias=bias)
    assert prep["precip"].tolist() == pytest.approx(s.tolist())
