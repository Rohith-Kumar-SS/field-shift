"""Scoring engine: knowledge base, criteria, MCDA arithmetic, constraints, scenarios, wording."""
import copy
import json

import pytest

from engine.climate import Scenario, prepare_daily, season_fit, summarise, summarise_for
from engine.knowledge import fill_residue, load_kb, regions, validate, year_profiles
from engine.scoring import (hazard_weights, normalise_weights, pest_metrics, score_field, season_fraction,
                            water_score, water_year)
from tests.conftest import make_history


def by_id(result: dict) -> dict:
    return {s["id"]: s for s in result["strategies"]}


# ---------------------------------------------------------------------------
# Knowledge base
# ---------------------------------------------------------------------------
def test_knowledge_base_is_valid_and_documented(kb):
    assert validate(kb) == []
    for cid, crop in kb["crops"].items():
        assert crop["why"], f"{cid} has no sources or rationales"
        assert "kc" in crop["why"]
    assert sum(c["default_weight"] for c in kb["criteria"].values()) == 100
    assert len(kb["strategies"]) >= 2          # plus the existing rotation = at least three compared


def test_validate_reports_problems(kb):
    bad = copy.deepcopy({k: v for k, v in kb.items()})
    bad["crops"]["teff"]["kc"][7] = 2.5
    del bad["crops"]["teff"]["traits"]["ky"]
    bad["strategies"]["cereal_teff_break"]["years"][0][0]["crop"] = "unobtainium"
    msgs = " | ".join(validate(bad))
    assert "Kc 7" in msgs and "missing trait 'ky'" in msgs and "unknown crop" in msgs


def test_year_profile_takes_the_larger_crop_and_residue_fills_gaps(kb):
    year = [{"crop": "winter_cereal_forage", "months": [1, 2, 3, 4, 5, 6]}, {"crop": "teff", "months": [6, 7, 8, 9]}]
    kc, cover = year_profiles(year, kb)
    assert kc[6] == max(kb["crops"]["winter_cereal_forage"]["kc"][6], kb["crops"]["teff"]["kc"][6])
    assert kc[11] == 0 and cover[11] == 0
    filled = fill_residue([cover])[0]
    assert 0.1 <= filled[10] < cover[9] and filled[12] >= 0.1       # stubble decays but never vanishes


def test_season_fraction(kb):
    assert season_fraction({"crop": "alfalfa"}, kb) == 1.0
    assert season_fraction({"crop": "winter_cereal_forage", "months": [9, 10, 11, 12]}, kb) == pytest.approx(0.4)
    assert season_fraction({"crop": "fallow"}, kb) == 1.0


# ---------------------------------------------------------------------------
# Criteria
# ---------------------------------------------------------------------------
def test_weights_normalise_and_fall_back_to_defaults(kb):
    w = normalise_weights({"water": 3, "income": 1}, kb)
    assert sum(w.values()) == pytest.approx(1.0) and w["water"] == pytest.approx(0.75) and w["cover"] == 0
    d = normalise_weights({}, kb)
    assert d["water"] == pytest.approx(0.30) and sum(d.values()) == pytest.approx(1.0)
    assert normalise_weights({"water": -5}, kb) == d            # negative sliders are ignored


def test_water_score_scale():
    assert water_score(700, 700) == 0.0
    assert water_score(525, 700) == pytest.approx(0.5)
    assert water_score(350, 700) == 1.0 and water_score(100, 700) == 1.0
    assert water_score(800, 700) == 0.0 and water_score(100, 0) == 0.0


def test_water_year_balance(kb, daily):
    clim = summarise(prepare_daily(daily, 39.7, 1800, 1800))
    alf = water_year([{"crop": "alfalfa"}], kb, clim, 1.0)
    teff = water_year([{"crop": "teff"}], kb, clim, 1.0)
    idle = water_year([{"crop": "fallow"}], kb, clim, 1.0)
    assert alf["nir"] == pytest.approx(alf["etc"] - alf["pe"], abs=1.0)
    assert 0 < teff["nir"] < alf["nir"] and idle["nir"] == 0
    assert water_year([{"crop": "alfalfa"}], kb, clim, 0.8)["etc"] == pytest.approx(0.8 * alf["etc"])
    assert alf["ky"] == pytest.approx(1.1)


def test_pest_metrics(kb):
    cont = pest_metrics([[{"crop": "alfalfa"}]] * 8, kb)
    assert cont["gap_years"] == 0 and cont["break_score"] == 0 and cont["longest_stand"] == 8
    rot = pest_metrics(kb["strategies"]["cereal_teff_break"]["years"], kb)
    assert rot["gap_years"] == 2 and rot["break_score"] == 1.0 and rot["longest_stand"] == 5
    assert set(rot["groups"]) == {"legume", "cool-season grass", "warm-season grass"}
    assert rot["score"] > cont["score"]
    one = pest_metrics(kb["strategies"]["short_stand_grain"]["years"], kb)
    assert one["gap_years"] == 1 and one["break_score"] == 0.6
    none = pest_metrics([[{"crop": "spring_grain"}], [{"crop": "teff"}]], kb)
    assert none["longest_stand"] == 0 and none["break_score"] == 1.0


def test_hazard_weights_sum_to_one_and_follow_the_soil(kb, daily):
    clim = summarise(prepare_daily(daily, 39.7, 1800, 1800))
    sandy = hazard_weights(clim, {"wind_erodibility_index": 134, "kwfact_surface": 0.2}, 0.2)
    tight = hazard_weights(clim, {"wind_erodibility_index": 38, "kwfact_surface": 0.4}, 3.0)
    assert sum(sandy["weights"].values()) == pytest.approx(1.0)
    assert sandy["wind_level"] == "high" and tight["wind_level"] == "low"
    assert sandy["wind_share"] > tight["wind_share"]


def test_season_fit():
    assert season_fit([80, 90, 100, 110], 95) == 0.5
    assert season_fit([80, 90], 0) == 1.0 and season_fit([], 75) == 0.0


# ---------------------------------------------------------------------------
# Whole-field scoring
# ---------------------------------------------------------------------------
def test_score_field_compares_existing_plus_alternatives(ctx, kb):
    res = score_field(ctx, kb)
    assert len(res["strategies"]) >= 3
    assert sum(s["is_existing"] for s in res["strategies"]) == 1
    assert sorted(s["rank"] for s in res["strategies"]) == list(range(1, len(res["strategies"]) + 1))
    assert sum(res["weights"].values()) == pytest.approx(1.0, abs=1e-3)
    for s in res["strategies"]:
        assert 0 <= s["total"] <= 1
        assert s["total"] == pytest.approx(sum(c["contribution"] for c in s["criteria"].values()), abs=1e-3)
        for cid, c in s["criteria"].items():
            assert 0 <= c["score"] <= 1, cid
            assert c["formula"] and c["inputs"] and c["confidence"] in ("high", "medium", "low")
            assert all(i.get("source") for i in c["inputs"]), f"{cid}: every input needs a source"
        assert s["why"] and s["benefits"] and s["risks"] and s["info_gaps"] and s["verify"]
        assert s["confidence"]["level"] in ("high", "medium", "low") and s["confidence"]["reasons"]
    json.dumps(res)             # the API response must be serialisable as it is


def test_priorities_change_the_ranking(ctx, kb):
    water = score_field(ctx, kb, {"water": 100})
    income = score_field(ctx, kb, {"income": 100})
    w, i = by_id(water), by_id(income)
    assert water["ranking"][0] == min(w, key=lambda k: w[k]["water"]["irrigation_mm"])
    assert income["ranking"][0] == "existing"
    assert water["ranking"][0] != income["ranking"][0]
    assert w["water_saver"]["water"]["irrigation_mm"] < w["existing"]["water"]["irrigation_mm"]


def test_water_supply_constraint_cuts_income_most_for_thirsty_rotations(ctx, kb):
    full = by_id(score_field(ctx, kb, None, {"water_supply_pct": 100}))
    short = by_id(score_field(ctx, kb, None, {"water_supply_pct": 60}))
    for sid in full:
        assert short[sid]["scores"]["income"] <= full[sid]["scores"]["income"] + 1e-9
        assert short[sid]["scores"]["water"] == full[sid]["scores"]["water"]      # demand is unchanged
    drop = lambda sid: full[sid]["scores"]["income"] - short[sid]["scores"]["income"]  # noqa: E731
    assert drop("existing") > drop("water_saver") > 0
    assert short["existing"]["water"]["years_short_of_supply"] == 8
    assert any("more irrigation than" in r for r in short["existing"]["risks"])


def test_equipment_and_market_constraints_show_up(ctx, kb):
    base = by_id(score_field(ctx, kb, None, {"equipment": ["hay", "drill", "combine"], "market": "open"}))
    tight = by_id(score_field(ctx, kb, None, {"equipment": ["hay"], "market": "established_only"}))
    assert tight["safflower_cover"]["scores"]["feasibility"] < base["safflower_cover"]["scores"]["feasibility"]
    assert tight["safflower_cover"]["scores"]["income"] < base["safflower_cover"]["scores"]["income"]
    assert any("combine" in r for r in tight["safflower_cover"]["risks"])
    assert any("established markets only" in r for r in tight["cereal_teff_break"]["risks"])
    assert tight["existing"]["scores"]["income"] == base["existing"]["scores"]["income"]


def test_scenario_sliders_rescore(ctx, kb):
    base = score_field(ctx, kb)
    hot = score_field(ctx, kb, scenario=Scenario(rain_pct=-30, temp_c=3))
    b, h = by_id(base), by_id(hot)
    assert base["scenario"]["is_baseline"] and not hot["scenario"]["is_baseline"]
    assert hot["climate"]["et0_annual"] > base["climate"]["et0_annual"]
    assert hot["climate"]["precip_annual"] < base["climate"]["precip_annual"]
    assert hot["climate"]["frost_free_median"] > base["climate"]["frost_free_median"]
    for sid in b:
        assert h[sid]["water"]["irrigation_mm"] > b[sid]["water"]["irrigation_mm"]
        assert h[sid]["scores"]["resilience"] <= b[sid]["scores"]["resilience"] + 1e-9
    assert h["existing"]["scores"]["income"] < b["existing"]["scores"]["income"]   # same supply, more need
    assert Scenario(rain_pct=999, temp_c=99).clamp() == Scenario(rain_pct=50, temp_c=5)


def test_salinity_flag_uses_soil_data(ctx, kb):
    salty = copy.deepcopy({k: v for k, v in ctx.items() if k != "power"})
    salty["power"] = ctx["power"]
    salty["soil"]["ec_dsm_0_30"] = 3.2
    res = by_id(score_field(salty, kb))
    assert any("salinity" in r.lower() and "alfalfa" in r.lower() for r in res["existing"]["risks"])
    assert any("salinity" in w["text"].lower() for w in res["short_stand_grain"]["why"])


def test_missing_data_lowers_confidence_and_is_named(ctx, kb):
    full = by_id(score_field(ctx, kb))["existing"]["confidence"]
    bare = copy.deepcopy({k: v for k, v in ctx.items() if k != "power"})
    bare["power"] = ctx["power"]
    bare["sources"].update(et=False, landsat=False, smap=False)
    bare["is_custom"] = True
    res = by_id(score_field(bare, kb))["existing"]
    assert res["confidence"]["score"] < full["score"]
    assert any("Missing for this field" in r for r in res["confidence"]["reasons"])
    assert any("No satellite water-use record" in g for g in res["info_gaps"])
    assert res["criteria"]["water"]["confidence"] == "low"


def test_observed_history_drives_the_existing_rotation(ctx, kb):
    mixed = copy.deepcopy({k: v for k, v in ctx.items() if k != "power"})
    mixed["power"] = ctx["power"]
    mixed["history"] = make_history(["fallow", "fallow", "alfalfa_est", "alfalfa", "alfalfa", "spring_grain",
                                     "alfalfa_est", "alfalfa"])
    a, b = by_id(score_field(ctx, kb))["existing"], by_id(score_field(mixed, kb))["existing"]
    assert b["water"]["irrigation_mm"] < a["water"]["irrigation_mm"]
    assert b["scores"]["pest_break"] > a["scores"]["pest_break"]
    assert len(b["sequence"]) == 8 and b["sequence"][0]["calendar_year"] == 2018


def test_the_tool_never_tells_the_farmer_what_to_plant(ctx, kb):
    res = score_field(ctx, kb)
    text = json.dumps(res).lower()
    for phrase in ("you should plant", "we recommend planting", "plant crop", "you must", "best crop is"):
        assert phrase not in text
    assert res["statement"].startswith("Under your priorities")
    assert "does not replace" in res["disclaimer"]


# ---------------------------------------------------------------------------
# Other regions: annual cropping, chosen (not observed) existing rotation
# ---------------------------------------------------------------------------
def test_every_region_has_a_valid_knowledge_base():
    assert set(regions()) >= {"diamond_valley_nv", "punjab_sangrur", "cauvery_delta_tn"}
    for rid in regions():
        k = load_kb(rid)
        assert validate(k) == [], rid
        assert sum(c["default_weight"] for c in k["criteria"].values()) == 100
        assert len(k["strategies"]) + (1 if k["settings"]["existing"] == "from_history" else 0) >= 3
        if k["settings"]["existing"] == "choose":
            options = [s for s in k["strategies"].values() if s.get("existing_option")]
            assert len(options) >= 2 and k["settings"]["existing_default"] in k["strategies"]
            assert k["strategies"][k["settings"]["existing_default"]].get("existing_option")


def test_chosen_rotation_becomes_the_existing_one(ctx_india, kb_pb):
    res = score_field(ctx_india, kb_pb)
    s = by_id(res)
    assert res["existing"]["mode"] == "choose" and res["existing"]["chosen"] == "rice_wheat"
    assert s["rice_wheat"]["is_existing"] and sum(x["is_existing"] for x in res["strategies"]) == 1
    assert len(res["strategies"]) >= 3
    other = by_id(score_field(ctx_india, kb_pb, existing_id="cotton_wheat"))
    assert other["cotton_wheat"]["is_existing"] and not other["rice_wheat"]["is_existing"]
    # the reference for the water score is fixed by the region, not by the farmer's choice
    assert other["rice_wheat"]["water"]["irrigation_mm"] == s["rice_wheat"]["water"]["irrigation_mm"]
    for x in res["strategies"]:
        assert 0 <= x["total"] <= 1 and x["why"] and x["risks"] and x["verify"] and x["info_gaps"]
    json.dumps(res)


def test_rice_wheat_is_the_thirstiest_and_legume_breaks_score_on_pests(ctx_india, kb_pb):
    s = by_id(score_field(ctx_india, kb_pb, {"water": 100}))
    assert s["rice_wheat"]["water"]["irrigation_mm"] > s["maize_wheat_moong"]["water"]["irrigation_mm"]
    assert s["rice_wheat"]["scores"]["water"] == pytest.approx(0.0, abs=0.02)   # it is the reference
    assert s["maize_wheat_moong"]["rank"] < s["rice_wheat"]["rank"]
    assert s["rice_wheat_moong"]["scores"]["nitrogen"] > s["rice_wheat"]["scores"]["nitrogen"]
    assert s["maize_wheat_moong"]["scores"]["pest_break"] > s["rice_wheat"]["scores"]["pest_break"]
    assert any("groundwater" in w["text"].lower() or "water stor" in w["text"].lower()
               for w in s["maize_wheat_moong"]["why"])


def test_annual_pest_model(kb_pb):
    mono = pest_metrics(kb_pb["strategies"]["rice_wheat"]["years"], kb_pb)
    div = pest_metrics(kb_pb["strategies"]["maize_wheat_moong"]["years"], kb_pb)
    assert mono["model"] == "annual" and mono["crops_per_year"] == 2
    assert div["crops_per_year"] == 3 and len(div["groups"]) > len(mono["groups"])
    assert 0 <= mono["score"] < div["score"] <= 1


def test_heat_threshold_follows_the_region(daily_monsoon, kb_pb, kb):
    prep = prepare_daily(daily_monsoon, 30.3, 232, 232)
    pb, nv = summarise_for(prep, kb_pb), summarise_for(prep, kb)
    assert pb["hot_day_c"] == 40 and nv["hot_day_c"] == 32
    assert 0 < pb["hot_days"] < nv["hot_days"]
    assert pb["heavy_rain_mm"] == 50 and pb["frost_free_median"] >= 300


def test_cauvery_rotations_score(ctx_india, kb_tn):
    ctx = {**ctx_india, "lat": 10.9, "lon": 79.3, "elevation_m": 20.0, "climate_correction": "imd",
           "phenology": {"median_seasons": 3.0, "usual_peak_months": [2, 8, 12], "n_years": 10}}
    res = score_field(ctx, kb_tn)
    s = by_id(res)
    assert res["existing"]["chosen"] == "kuruvai_thaladi_pulse" and len(s) >= 4
    # one green season a year seen from space -> the single-rice rotation becomes the starting point
    one = score_field({**ctx, "phenology": {"median_seasons": 1.0, "usual_peak_months": [12], "n_years": 10}}, kb_tn)
    assert one["existing"]["chosen"] == "samba_pulse" and "1 green season" in one["existing"]["assumptions"][0]
    # the farmer's own choice always wins, and a mismatch with the satellite record is pointed out
    own = score_field({**ctx, "phenology": {"median_seasons": 1.0, "usual_peak_months": [12], "n_years": 10}},
                      kb_tn, existing_id="kuruvai_thaladi_pulse")
    assert own["existing"]["chosen"] == "kuruvai_thaladi_pulse" and "Check that it matches" in own["existing"]["assumptions"][0]
    assert s["samba_pulse"]["water"]["irrigation_mm"] < s["kuruvai_thaladi_pulse"]["water"]["irrigation_mm"]
    text = json.dumps(res).lower()
    for phrase in ("you should plant", "we recommend planting", "plant crop", "you must", "best crop is"):
        assert phrase not in text
