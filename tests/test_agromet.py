"""Agro-meteorology: checked against the worked examples in FAO-56 and simple known cases."""
import numpy as np
import pytest

from engine import agromet as am


def test_et0_matches_fao56_example_18():
    # FAO-56 Example 18 (Brussels, 6 July): Tmax 21.5, Tmin 12.3, ea 1.409 kPa, u2 2.078 m/s,
    # Rs 22.07 MJ/m2/day, 50.8 N, 100 m  ->  ET0 = 3.9 mm/day
    ea = 1.409
    tdew = (116.91 + 237.3 * np.log(ea)) / (16.78 - np.log(ea))
    et0 = float(am.et0_fao56([21.5], [12.3], [tdew], [2.078], [22.07], 50.8, 100.0, [187])[0])
    assert et0 == pytest.approx(3.88, abs=0.1)


def test_extraterrestrial_radiation_matches_fao56_example_8():
    # FAO-56 Example 8: 20 S on 3 September (day 246) -> Ra = 32.2 MJ/m2/day
    assert float(am.extraterrestrial_radiation(-20.0, 246)) == pytest.approx(32.2, abs=0.2)


def test_et0_rises_with_temperature_and_is_never_negative():
    cool = am.et0_fao56([20], [5], [2], [2], [20], 39.7, 1800, [180])[0]
    warm = am.et0_fao56([23], [8], [2], [2], [20], 39.7, 1800, [180])[0]
    assert warm > cool > 0
    assert am.et0_fao56([-10], [-20], [-22], [1], [3], 39.7, 1800, [10])[0] >= 0


def test_effective_precip_is_bounded():
    p = np.array([0.0, 5.0, 20.0, 60.0, 150.0])
    etc = np.array([120.0, 120.0, 120.0, 120.0, 40.0])
    pe = am.effective_precip_usda(p, etc)
    assert (pe >= 0).all() and (pe <= p + 1e-9).all() and (pe <= etc + 1e-9).all()
    assert pe[0] == 0 and pe[2] > pe[1]            # more rain, more usable rain
    assert pe[4] == pytest.approx(40.0)            # cannot exceed what the crop uses


def test_frost_dates_and_frost_free_days():
    doy = np.arange(1, 366)
    tmin = np.where((doy > 150) & (doy < 250), 5.0, -3.0)
    last, first, days = am.frost_dates(doy, tmin, 0.0)
    assert (last, first, days) == (150, 250, 99)
    # a year with no frost at all uses the year boundaries
    assert am.frost_dates(doy, np.full(365, 4.0))[2] == 364


def test_growing_degree_days_caps_and_base():
    assert am.growing_degree_days([40.0], [20.0], base_c=5, cap_c=30) == pytest.approx(20.0)
    assert am.growing_degree_days([3.0], [-5.0]) == 0.0


def test_trend_detects_direction_and_refuses_noise():
    years = np.arange(1991, 2026)
    up = am.theil_sen_trend(years, 10 + 0.5 * (years - 1991) + np.sin(years))
    assert up["direction"] == "increasing" and up["significant"]
    assert up["slope_per_decade"] == pytest.approx(5.0, abs=0.6)
    rng = np.random.default_rng(1)
    flat = am.theil_sen_trend(years, rng.normal(0, 1, len(years)))
    assert flat["direction"] == "no clear trend"
    assert am.theil_sen_trend([2020, 2021], [1, 2])["direction"] == "not enough data"


def test_monthly_zscore_is_relative_to_its_own_month():
    months = np.tile(np.arange(1, 13), 6)
    values = np.tile(np.linspace(0.05, 0.25, 12), 6).astype(float)
    values[5] += 0.10                      # one wet June
    z = am.monthly_zscore(values, months)
    assert z[5] > 1.5
    assert np.isnan(z[0])                  # January never varies: no meaningful anomaly
    assert np.isnan(am.monthly_zscore([0.1, 0.2], [1, 1])).all()   # too few years


def test_lapse_adjustment_warms_when_moving_downhill():
    assert am.lapse_adjust(10.0, 2025.0, 1800.0) == pytest.approx(10.0 + 0.0065 * 225)
