"""Transparent rotation scoring: rule-based agronomy + weighted multi-criteria analysis.

    Score(strategy) = sum_i  w_i * s_i(strategy)          (weights normalised to 1)

Each criterion score s_i is between 0 and 1 and comes back with the formula, the inputs
that produced it, their sources and a confidence level, so that every number shown in
the app can be traced. Nothing here predicts yield, and nothing here says "plant X".
"""
from __future__ import annotations

from typing import Any

import numpy as np

from .agromet import effective_precip_usda
from .climate import MONTHS, Scenario, heat_days_in, prepare_daily, season_fit, summarise
from .history import existing_rotation
from .knowledge import entry_months, fill_residue, year_profiles

CONF_VALUE = {"high": 1.0, "medium": 0.6, "low": 0.3}
MONTH_NAMES = ["", "Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]
ALFALFA = ("alfalfa", "alfalfa_est")
MARKET_FACTOR = {
    "established": {"established_only": 1.0, "some": 1.0, "open": 1.0},
    "niche": {"established_only": 0.5, "some": 0.8, "open": 1.0},
    "uncertain": {"established_only": 0.2, "some": 0.5, "open": 0.8},
}
# days above a crop heat limit, within its season, at which its heat score reaches zero
HEAT_DAYS_FULL = 45.0
DEFAULT_CONSTRAINTS = {"water_supply_pct": 100, "equipment": ["hay", "drill"], "market": "some"}


def clamp(v: float, lo: float = 0.0, hi: float = 1.0) -> float:
    return float(max(lo, min(hi, v)))


def normalise_weights(weights: dict[str, float], kb: dict) -> dict[str, float]:
    """Slider values -> weights that sum to 1. All-zero sliders fall back to the defaults."""
    crit = list(kb["criteria"])
    raw = {c: max(float(weights.get(c, 0.0)), 0.0) for c in crit}
    total = sum(raw.values())
    if total <= 0:
        raw = {c: float(kb["criteria"][c]["default_weight"]) for c in crit}
        total = sum(raw.values())
    return {c: raw[c] / total for c in crit}


# ---------------------------------------------------------------------------
# Building blocks per rotation year
# ---------------------------------------------------------------------------
def season_fraction(entry: dict, kb: dict) -> float:
    """Share of a crop's own growing season that this entry covers (0-1)."""
    crop = kb["crops"][entry["crop"]]
    months = set(entry_months(entry, kb))
    active = set(crop["kc"])
    if not active:
        return len(months) / 12.0
    return len(months & active) / len(active)


def is_planting(entry: dict, kb: dict) -> bool:
    """An entry is a sowing if the crop needs sowing and does not start the year in the ground."""
    crop = kb["crops"][entry["crop"]]
    return crop["traits"]["plantings"] > 0 and min(entry_months(entry, kb)) > 1


def water_year(year: list[dict], kb: dict, clim: dict, factor: float) -> dict:
    """Crop water demand, effective rain and net irrigation need for one rotation year (mm)."""
    kc, _ = year_profiles(year, kb)
    etc = {m: kc[m] * clim["et0_month"][m] * factor for m in MONTHS}
    active = [m for m in MONTHS if kc[m] > 0]
    pe = {m: 0.0 for m in MONTHS}
    if active:
        vals = effective_precip_usda([clim["precip_month"][m] for m in active], [etc[m] for m in active])
        pe.update({m: float(v) for m, v in zip(active, vals)})
    nir = {m: max(etc[m] - pe[m], 0.0) for m in MONTHS}
    ky_num = ky_den = 0.0
    for m in active:
        best = max((e for e in year if m in entry_months(e, kb)),
                   key=lambda e: kb["crops"][e["crop"]]["kc"].get(m, 0.0))
        ky_num += kb["crops"][best["crop"]]["traits"]["ky"] * etc[m]
        ky_den += etc[m]
    return {"etc": sum(etc.values()), "pe": sum(pe.values()), "nir": sum(nir.values()),
            "etc_month": etc, "nir_month": nir, "ky": (ky_num / ky_den) if ky_den else 0.0,
            "peak_share": (nir[7] + nir[8]) / sum(nir.values()) if sum(nir.values()) > 0 else 0.0}


def hazard_weights(clim: dict, soil: dict, slope_pct: float) -> dict:
    """When is this field's soil most at risk? Monthly weights (sum 1) from wind and heavy rain.

    Wind: days a year with daily-mean wind >= 4.5 m/s at 2 m, scaled by the soil's wind
    erodibility index (NRCS). Rain: days with >= 10 mm, scaled by slope and the K factor.
    """
    wei = soil.get("wind_erodibility_index")
    wei = 86.0 if wei is None or not np.isfinite(wei) else float(wei)
    kw = soil.get("kwfact_surface")
    kw = 0.3 if kw is None or not np.isfinite(kw) else float(kw)
    wind_w = clamp(wei / 134.0, 0.15, 1.6)
    rain_w = clamp(slope_pct / 2.0, 0.05, 1.5) * clamp(kw / 0.30, 0.3, 1.6)
    wd, hr = clim["windy_days_month"], clim["heavy_rain_days_month"]
    wsum, hsum = sum(wd.values()), sum(hr.values())
    raw = {}
    for m in MONTHS:
        w = wind_w * (wd[m] / wsum) if wsum > 0 else 0.0
        r = rain_w * (hr[m] / hsum) if hsum > 0 else 0.0
        raw[m] = w + r
    total = sum(raw.values()) or 1.0
    weights = {m: raw[m] / total for m in MONTHS}
    wind_share = (wind_w / (wind_w + rain_w)) if hsum > 0 else 1.0
    level = "high" if wei >= 134 else "moderate" if wei >= 86 else "low"
    top = sorted(MONTHS, key=lambda m: -weights[m])[:3]
    return {"weights": weights, "wind_share": round(wind_share, 2), "wind_level": level,
            "wind_erodibility_index": wei, "k_factor": kw, "peak_months": sorted(top),
            "windy_days_year": round(wsum, 1), "heavy_rain_days_year": round(hsum, 1)}


def pest_metrics(years: list[list[dict]], kb: dict) -> dict:
    """Break between alfalfa stands, plant-group diversity and longest stand (cyclic)."""
    n = len(years)
    is_alf = [any(e["crop"] in ALFALFA for e in y) for y in years]
    groups: set[str] = set()
    for y in years:
        for e in y:
            g = kb["crops"][e["crop"]]["group"]
            if g == "cover mix":
                groups.update({"cool-season grass", "legume"})
            elif g not in ("none", "unknown"):
                groups.add(g)

    def runs(flags: list[bool], target: bool) -> list[int]:
        if all(f == target for f in flags):
            return [len(flags)]
        if not any(f == target for f in flags):
            return []
        start = next(i for i, f in enumerate(flags) if f != target)
        seq = flags[start:] + flags[:start]
        out, cur = [], 0
        for f in seq:
            if f == target:
                cur += 1
            elif cur:
                out.append(cur)
                cur = 0
        if cur:
            out.append(cur)
        return out

    alf_runs, gap_runs = runs(is_alf, True), runs(is_alf, False)
    if not any(is_alf):
        gap, longest, break_score, age_score = n, 0, 1.0, 1.0
    else:
        gap = min(gap_runs) if gap_runs else 0
        longest = max(alf_runs)
        break_score = 0.0 if gap == 0 else 0.6 if gap == 1 else 1.0
        age_score = clamp(1.0 - (longest - 5) / 5.0)
    diversity = clamp((len(groups) - 1) / 3.0)
    return {"gap_years": gap, "longest_stand": longest, "groups": sorted(groups),
            "break_score": break_score, "diversity_score": round(diversity, 3),
            "age_score": round(age_score, 3),
            "score": round(0.45 * break_score + 0.35 * diversity + 0.20 * age_score, 4)}


def nitrogen_year(i: int, years: list[list[dict]], kb: dict) -> float:
    year = years[i]
    crops = {e["crop"] for e in year}
    if crops & set(ALFALFA):
        return max(kb["crops"][c]["traits"]["n_score"] for c in crops & set(ALFALFA))
    prev, prev2 = years[i - 1], years[i - 2]
    had = lambda y: any(e["crop"] in ALFALFA for e in y)  # noqa: E731
    carry = 0.6 if had(prev) else 0.3 if had(prev2) else 0.0
    legume_cover = max((kb["crops"][e["crop"]]["traits"]["n_score"] * season_fraction(e, kb)
                        for e in year), default=0.0)
    return clamp(carry + legume_cover)


# ---------------------------------------------------------------------------
# One strategy
# ---------------------------------------------------------------------------
def water_score(irrigation_mm: float, alfalfa_mm: float) -> float:
    """0 = as thirsty as full-season alfalfa on this field; 1 = half of that, or less.

    score = 2 x (1 - irrigation need / full-alfalfa irrigation need), limited to 0-1.
    Rotations rarely save more than half, so the scale is stretched over the range that
    actually separates them; the millimetres are always shown next to the score.
    """
    if alfalfa_mm <= 0:
        return 0.0
    return clamp(2.0 * (1.0 - irrigation_mm / alfalfa_mm))


def evaluate_strategy(strategy: dict, ctx: dict, kb: dict, clim: dict, clim_base: dict,
                      constraints: dict, supply_mm: float, hazard: dict, alfalfa_mm: float) -> dict:
    years = strategy["years"]
    n = len(years)
    factor = ctx.get("water_factor", 1.0)
    equipment = set(constraints.get("equipment", []))
    market = constraints.get("market", "some")
    ffd = clim["frost_free_days"]

    wy = [water_year(y, kb, clim, factor) for y in years]
    covers = fill_residue([year_profiles(y, kb)[1] for y in years])
    nir_mean = float(np.mean([w["nir"] for w in wy]))
    etc_mean = float(np.mean([w["etc"] for w in wy]))
    pe_mean = float(np.mean([w["pe"] for w in wy]))
    ref = clim_base["et0_annual"]

    cover_year = [sum(hazard["weights"][m] * covers[i][m] for m in MONTHS) for i in range(n)]
    n_year = [nitrogen_year(i, years, kb) for i in range(n)]
    om_year, income_year, res_year, feas_year, short_years = [], [], [], [], 0
    crop_notes: dict[str, dict] = {}
    for i, year in enumerate(years):
        plantings = sum(is_planting(e, kb) for e in year)
        om = value = 0.0
        res_num = res_den = 0.0
        feas_parts = []
        seen: set[str] = set()
        for e in year:
            crop = kb["crops"][e["crop"]]
            t = crop["traits"]
            frac = season_fraction(e, kb)
            om += t["om_score"] * frac
            mf = MARKET_FACTOR.get(str(t["market"]).split(" ")[0], {}).get(market, 1.0)
            value += t["value_score"] * frac * mf
            if e["crop"] != "fallow" and frac > 0:
                months = [m for m in entry_months(e, kb) if m in crop["kc"]]
                hd = heat_days_in(months, t["heat_limit_c"], clim)
                heat_ok = 1.0 - clamp(hd / HEAT_DAYS_FULL)
                res_num += frac * (0.5 * t["drought_tolerance"] + 0.5 * heat_ok)
                res_den += frac
            if e["crop"] not in seen:
                seen.add(e["crop"])
                fit = season_fit(ffd, int(t["frost_free_days_needed"]))
                need = list(t["equipment"])
                eq = (sum(x in equipment for x in need) / len(need)) if need else 1.0
                base = 0.8 if e["crop"] == "fallow" else (
                    0.45 * fit + 0.30 * eq + 0.25 * (1.0 - t["establishment_risk"]))
                feas_parts.append(base)
                crop_notes[e["crop"]] = {
                    "crop": e["crop"], "label": crop["short"], "season_fit": fit,
                    "frost_free_days_needed": int(t["frost_free_days_needed"]),
                    "equipment_needed": need, "equipment_missing": [x for x in need if x not in equipment],
                    "market": t["market"], "salt_threshold_ds_m": t.get("salt_threshold_ds_m"),
                    "heat_limit_c": t["heat_limit_c"]}
        om_year.append(clamp(om - 0.08 * plantings))
        # water shortage -> yield (FAO-33): 1 - Ya/Ym = Ky * (1 - ETa/ETm)
        w = wy[i]
        rel_yield = 1.0
        if w["etc"] > 0 and w["nir"] > supply_mm:
            eta = w["pe"] + supply_mm
            rel_yield = clamp(1.0 - w["ky"] * (1.0 - eta / w["etc"]))
            short_years += 1
        income_year.append(clamp(value) * rel_yield)
        res_year.append(res_num / res_den if res_den else 0.5)
        feas_year.append(clamp(float(np.mean(feas_parts)) - 0.05 * max(plantings - 1, 0)))

    pest = pest_metrics(years, kb)
    scores = {
        "water": water_score(nir_mean, alfalfa_mm),
        "cover": float(np.mean(cover_year)),
        "nitrogen": float(np.mean(n_year)),
        "organic_matter": float(np.mean(om_year)),
        "pest_break": pest["score"],
        "income": float(np.mean(income_year)),
        "resilience": float(np.mean(res_year)),
        "feasibility": float(np.mean(feas_year)),
    }
    return {
        "id": strategy["id"], "name": strategy["name"], "short": strategy["short"],
        "summary": strategy["summary"], "is_existing": bool(strategy.get("is_existing")),
        "tags": strategy.get("tags", []),
        "scores": {k: round(v, 4) for k, v in scores.items()},
        "water": {"etc_mm": round(etc_mean), "effective_rain_mm": round(pe_mean),
                  "irrigation_mm": round(nir_mean), "reference_et_mm": round(ref),
                  "full_alfalfa_mm": round(alfalfa_mm),
                  "saving_vs_alfalfa_pct": round(100.0 * (1.0 - nir_mean / alfalfa_mm)) if alfalfa_mm else 0,
                  "by_year": [{"etc_mm": round(w["etc"]), "irrigation_mm": round(w["nir"]),
                               "effective_rain_mm": round(w["pe"]),
                               "july_august_share": round(w["peak_share"], 2)} for w in wy],
                  "peak_year_mm": round(max(w["nir"] for w in wy)),
                  "years_short_of_supply": short_years, "n_years": n},
        "pest": pest,
        "by_year": {"cover": [round(v, 3) for v in cover_year], "nitrogen": [round(v, 3) for v in n_year],
                    "organic_matter": [round(v, 3) for v in om_year],
                    "income": [round(v, 3) for v in income_year],
                    "resilience": [round(v, 3) for v in res_year],
                    "feasibility": [round(v, 3) for v in feas_year]},
        "cover_calendar": covers,
        "crop_notes": list(crop_notes.values()),
        "sequence": describe_sequence(strategy, kb),
    }


def describe_sequence(strategy: dict, kb: dict) -> list[dict]:
    out = []
    labels = strategy.get("year_labels")
    for i, year in enumerate(strategy["years"]):
        seen, entries = set(), []
        for e in year:
            crop = kb["crops"][e["crop"]]
            months = entry_months(e, kb)
            entries.append({"crop": e["crop"], "label": crop["short"], "group": crop["group"],
                            "months": months})
            seen.add(e["crop"])
        out.append({"year": i + 1, "calendar_year": labels[i] if labels else None, "entries": entries,
                    "label": " + ".join(dict.fromkeys(x["label"] for x in entries))})
    return out


# ---------------------------------------------------------------------------
# Explanations
# ---------------------------------------------------------------------------
def criterion_detail(cid: str, res: dict, ctx: dict, kb: dict, clim: dict, hazard: dict,
                     existing: dict | None, constraints: dict, supply_mm: float) -> dict:
    """Formula, inputs and confidence behind one criterion score."""
    s = res["scores"][cid]
    src = ctx.get("sources", {})
    rain_src = ("GPM IMERG scaled to gridMET" if src.get("imerg")
                else "NASA POWER corrected to gridMET (IMERG pending)")
    crops_used = {e["crop"] for y in res["sequence"] for e in y["entries"]}
    local = ("corrected month by month to gridMET (4 km)" if ctx.get("climate_correction") == "gridmet"
             else "shifted to field elevation (lapse rate)")
    if cid == "water":
        w = res["water"]
        inputs = [
            {"label": "Crop water demand (rotation average)", "value": w["etc_mm"], "unit": "mm/yr",
             "source": "FAO-56 crop coefficients x reference ET from NASA POWER"},
            {"label": "Rain the crops can use", "value": w["effective_rain_mm"], "unit": "mm/yr",
             "source": f"{rain_src}, USDA-SCS effective-rain method"},
            {"label": "Irrigation need (rotation average)", "value": w["irrigation_mm"], "unit": "mm/yr",
             "source": "demand minus usable rain"},
            {"label": "Full-season alfalfa on this field would need", "value": w["full_alfalfa_mm"],
             "unit": "mm/yr", "source": "same method, established alfalfa every year"},
            {"label": "Reference ET at this field", "value": w["reference_et_mm"], "unit": "mm/yr",
             "source": f"NASA POWER ({local}), FAO-56 Penman-Monteith, 1996-2025"},
        ]
        if ctx.get("water_factor_info", {}).get("available"):
            f = ctx["water_factor_info"]
            inputs.append({"label": "Adjustment to this field's own record", "value": round(ctx["water_factor"], 2),
                           "unit": "x", "source": f"OpenET, alfalfa years {f['years'][0]}-{f['years'][-1]}: "
                                                  "measured-from-space ET divided by the textbook figure"})
        conf = "medium"
        note = ("Model-based: gridded weather and textbook crop coefficients."
                + (" Anchored to OpenET satellite ET for this field." if ctx.get("water_factor_info", {}).get("available")
                   else " No OpenET record for this field, so nothing anchors it."))
        if "teff" in crops_used or "safflower" in crops_used:
            note += " Water use of teff and safflower here is poorly documented."
        if not ctx.get("water_factor_info", {}).get("available"):
            conf = "low"
        formula = ("score = 2 x (1 - irrigation need / full-alfalfa irrigation need), limited to 0-1: "
                   "0 = as thirsty as alfalfa, 1 = half the water or less")
        headline = f"Needs about {w['irrigation_mm']} mm of irrigation a year"
        if existing and not res["is_existing"]:
            diff = w["irrigation_mm"] - existing["water"]["irrigation_mm"]
            pct = 100.0 * diff / existing["water"]["irrigation_mm"] if existing["water"]["irrigation_mm"] else 0
            headline += f" ({abs(pct):.0f} % {'less' if diff < 0 else 'more'} than the existing rotation)"
        return dict(score=s, formula=formula, headline=headline, inputs=inputs, confidence=conf, note=note,
                    panel="water")
    if cid == "cover":
        cal = res["cover_calendar"]
        avg = {m: float(np.mean([c[m] for c in cal])) for m in MONTHS}
        peak = hazard["peak_months"]
        inputs = [
            {"label": "Months when this soil is most at risk",
             "value": ", ".join(MONTH_NAMES[m] for m in peak), "unit": "",
             "source": "windy days and heavy-rain days from NASA POWER, weighted by soil and slope"},
            {"label": "Average cover in those months", "value": round(float(np.mean([avg[m] for m in peak])) * 100),
             "unit": "%", "source": "crop calendar in the knowledge base"},
            {"label": "Soil wind-erodibility index", "value": round(hazard["wind_erodibility_index"]),
             "unit": "t/ac/yr", "source": "SSURGO (USDA NRCS)"},
            {"label": "Field tilt", "value": ctx.get("slope_pct"), "unit": "%", "source": "SRTM plane fit"},
        ]
        return dict(score=s, formula="score = sum over months of (risk weight x share of soil covered)",
                    headline=f"Soil covered {s * 100:.0f} % of the time that matters",
                    inputs=inputs, confidence="medium", panel="cover",
                    note="Cover comes from a crop calendar, not from watching this rotation on your field. "
                         "On this nearly flat ground, wind is the main erosion risk.")
    if cid == "nitrogen":
        leg = sum(any(e["crop"] in ALFALFA for e in y["entries"]) for y in res["sequence"])
        return dict(score=s, formula="legume year = 1; first year after alfalfa = 0.6; second = 0.3; legume cover crop adds up to 0.5",
                    headline=f"Legumes in {leg} of {len(res['sequence'])} years",
                    inputs=[{"label": "Years with alfalfa", "value": leg, "unit": f"of {len(res['sequence'])}",
                             "source": "rotation definition"},
                            {"label": "Typical nitrogen credit after alfalfa", "value": "80-170", "unit": "kg N/ha",
                             "source": "SARE; UC ANR 3512"}],
                    confidence="medium", panel="history",
                    note="A well-established principle, but the real credit depends on stand, soil and "
                         "management. A soil test is the only measurement.")
    if cid == "organic_matter":
        om = ctx.get("soil", {}).get("om_pct_0_30")
        return dict(score=s, formula="sum of each crop's root-and-residue class, minus 0.08 per sowing (tillage)",
                    headline="Root and residue inputs: " + ("high" if s >= 0.7 else "moderate" if s >= 0.5 else "low"),
                    inputs=[{"label": "Soil organic matter today (0-30 cm)",
                             "value": None if om is None else round(om, 1), "unit": "%", "source": "SSURGO (USDA NRCS)"},
                            {"label": "Sowings per rotation",
                             "value": sum(1 for y in res["sequence"] for e in y["entries"] if min(e["months"]) > 1
                                          and kb["crops"][e["crop"]]["traits"]["plantings"] > 0),
                             "unit": "", "source": "rotation definition"}],
                    confidence="low", panel="soil",
                    note="Class scores only. Organic matter changes over many years and cannot be seen "
                         "from space; satellites do not measure it.")
    if cid == "pest_break":
        p = res["pest"]
        return dict(score=s, formula="0.45 x break between alfalfa stands + 0.35 x plant-group diversity + 0.20 x stand-age score",
                    headline=(f"{p['gap_years']}-year break between alfalfa stands" if p["longest_stand"]
                              else "No alfalfa in the rotation"),
                    inputs=[{"label": "Years out of alfalfa between stands", "value": p["gap_years"], "unit": "years",
                             "source": "rotation definition; Extension guidance asks for at least 1"},
                            {"label": "Plant groups in the rotation", "value": ", ".join(p["groups"]) or "none",
                             "unit": "", "source": "knowledge base"},
                            {"label": "Longest alfalfa stand", "value": p["longest_stand"], "unit": "years",
                             "source": "rotation definition"}],
                    confidence="medium" if not res["is_existing"] or ctx.get("n_doubtful_years", 0) <= 2 else "low",
                    panel="history",
                    note="Counts breaks and plant families; it knows nothing about which pests or "
                         "diseases are actually in your field.")
    if cid == "income":
        w = res["water"]
        inputs = [{"label": "Forage value relative to established alfalfa", "value": round(s * 100), "unit": "%",
                   "source": "class scores in the knowledge base (no prices)"},
                  {"label": "Your market setting", "value": constraints.get("market", "some"), "unit": "",
                   "source": "your input"},
                  {"label": "Years needing more water than your supply", "value": w["years_short_of_supply"],
                   "unit": f"of {w['n_years']}", "source": f"your supply setting ({round(supply_mm)} mm/yr)"}]
        return dict(score=s, formula="sum of crop value classes x market factor, reduced by water shortage (FAO-33 yield response)",
                    headline=f"About {s * 100:.0f} % of the value of well-watered alfalfa",
                    inputs=inputs, confidence="low", panel="water",
                    note="No local prices, yields or costs are in this tool. Treat this as a rough ordering "
                         "and replace it with your own budget.")
    if cid == "resilience":
        hot = round(sum(clim["heat_days_month"][32].values()), 1)
        return dict(score=s, formula="per crop: 0.5 x drought-tolerance class + 0.5 x (1 - days above its heat limit in its season / 45)",
                    headline="Copes with heat and short water: " + ("well" if s >= 0.7 else "moderately" if s >= 0.55 else "poorly"),
                    inputs=[{"label": "Days a year above 32 °C", "value": hot, "unit": "days",
                             "source": f"NASA POWER, {local}"},
                            {"label": "Crops' own heat limits", "value": ", ".join(
                                f"{c['label']} {c['heat_limit_c']} °C" for c in res["crop_notes"] if c["crop"] != "fallow"),
                             "unit": "", "source": "knowledge base"}],
                    confidence="medium", panel="climate",
                    note="Heat days come from a ~50 km NASA weather grid corrected to local conditions, "
                         "not from a station in the field.")
    # feasibility
    worst = min((c for c in res["crop_notes"] if c["frost_free_days_needed"] > 0),
                key=lambda c: c["season_fit"], default=None)
    inputs = [{"label": "Frost-free season (median)", "value": round(clim["frost_free_median"]), "unit": "days",
               "source": f"NASA POWER, {local}, 1996-2025"},
              {"label": "Your equipment", "value": ", ".join(constraints.get("equipment", [])) or "none", "unit": "",
               "source": "your input"}]
    if worst:
        inputs.append({"label": f"Years long enough for {worst['label'].lower()}",
                       "value": round(worst["season_fit"] * 100), "unit": "%",
                       "source": f"needs about {worst['frost_free_days_needed']} frost-free days"})
    return dict(score=s, formula="per crop: 0.45 x season fit + 0.30 x equipment you have + 0.25 x (1 - establishment risk); -0.05 per extra sowing in a year",
                headline="Fits your season and equipment: " + ("well" if s >= 0.75 else "partly" if s >= 0.55 else "poorly"),
                inputs=inputs, confidence="medium", panel="climate",
                note="Frost dates depend heavily on local cold-air pooling. Even after correction to a 4 km "
                     "grid, the coldest hollows frost earlier and later than shown: check your own records.")


def field_conditions(ctx: dict, kb: dict, clim: dict, hazard: dict, existing: dict) -> dict:
    """Facts about this field that the 'why suggested' rules look at."""
    soil = ctx.get("soil", {})
    hist = ctx.get("history", [])
    run = best = 0
    for r in hist:
        run = run + 1 if r["crop"] in ALFALFA else 0
        best = max(best, run)
    gw = ctx.get("groundwater", {})
    return {
        "irrigation_mm": existing["water"]["irrigation_mm"],
        "usable_rain_mm": existing["water"]["effective_rain_mm"],
        "precip_annual": clim["precip_annual"], "et0_annual": clim["et0_annual"],
        "alfalfa_run": best, "current_run": run,
        "groups": existing["pest"]["groups"],
        "om": soil.get("om_pct_0_30"), "ec": soil.get("ec_dsm_0_30"), "ph": soil.get("ph_0_30"),
        "sar": soil.get("sar_0_30"), "texture": soil.get("surface_texture"),
        "weg": soil.get("wind_erodibility_group"), "wind_level": hazard["wind_level"],
        "peak_months": hazard["peak_months"], "windy_days": hazard["windy_days_year"],
        "low_cover": ctx.get("landsat", {}).get("low_cover_share_peak_months"),
        "gw_wells": gw.get("n_wells_trend"), "gw_deepening": gw.get("n_deepening"),
        "gw_rate": gw.get("median_m_per_decade"),
        "hot_days": round(sum(clim["heat_days_month"][32].values()), 1),
        "hot_trend": ctx.get("trends", {}).get("days_over_32", {}),
        "hot_trend_ground": ctx.get("trends", {}).get("days_over_32_gridmet") or {},
        "frost_free": clim["frost_free_median"],
    }


def why_suggested(res: dict, cond: dict, existing: dict, constraints: dict) -> list[dict]:
    """Rule-based reasons, each tied to a number from this field and to an evidence panel."""
    tags, out = set(res["tags"]), []
    w, ew = res["water"], existing["water"]
    if "reduces_water" in tags and ew["irrigation_mm"] > 0:
        saved = ew["irrigation_mm"] - w["irrigation_mm"]
        if saved > 15:
            txt = (f"The existing rotation needs about {ew['irrigation_mm']} mm of irrigation a year here, "
                   f"while rain supplies only about {ew['effective_rain_mm']} mm of what the crop uses. "
                   f"This rotation needs about {saved} mm a year less.")
            out.append({"text": txt, "panel": "water"})
    if "reduces_water" in tags and cond.get("gw_wells"):
        if cond["gw_deepening"] and cond["gw_deepening"] >= cond["gw_wells"] / 2:
            out.append({"text": f"{cond['gw_deepening']} of {cond['gw_wells']} nearby USGS wells with long records "
                                f"show the water table getting deeper since 1990 (median "
                                f"{abs(cond['gw_rate']):.1f} m per decade).", "panel": "groundwater"})
    if "adds_break" in tags and cond["alfalfa_run"] >= 5:
        out.append({"text": f"The crop map shows alfalfa for {cond['alfalfa_run']} years running. Stands usually "
                            f"thin with age, and Extension guidance asks for at least a year in another crop "
                            f"before re-sowing; this rotation gives {res['pest']['gap_years']}.", "panel": "history"})
    if tags & {"new_grass_families", "new_broadleaf_family"} and len(cond["groups"]) <= 1:
        out.append({"text": "The existing rotation uses one plant group ("
                            + (cond["groups"][0] if cond["groups"] else "none") + "); this one uses "
                            + f"{len(res['pest']['groups'])}: " + ", ".join(res["pest"]["groups"]) + ".",
                    "panel": "history"})
    if "adds_cover" in tags and cond["wind_level"] in ("moderate", "high"):
        months = ", ".join(MONTH_NAMES[m] for m in cond["peak_months"])
        gain = res["scores"]["cover"] - existing["scores"]["cover"]
        txt = (f"The soil here ({(cond['texture'] or 'soil').lower()}, wind-erodibility group {cond['weg']}) "
               f"is {cond['wind_level']}ly prone to blowing, and {months} are the riskiest months.")
        txt += (" This rotation keeps more of the soil covered then." if gain > 0.01 else
                " Check the cover calendar: the seeding years leave it exposed in spring.")
        out.append({"text": txt, "panel": "cover"})
    if "builds_om" in tags and cond["om"] is not None and cond["om"] < 1.5:
        out.append({"text": f"The soil survey puts organic matter at about {cond['om']:.1f} % in the top 30 cm, "
                            "which is low. This rotation returns more roots and residue to the soil.",
                    "panel": "soil"})
    if "salt_tolerant_break" in tags and cond["ec"] is not None and cond["ec"] >= 2.0:
        out.append({"text": f"The soil survey shows salinity around {cond['ec']:.1f} dS/m; alfalfa starts losing "
                            "yield above 2.0, while barley and triticale tolerate two to four times that.",
                    "panel": "soil"})
    if "deep_roots" in tags:
        out.append({"text": "A taproot crop can reach moisture below the root zone of the cereals and "
                            "grasses, and comes from a plant family the field has not seen.", "panel": "soil"})
    if "familiar_equipment" in tags:
        eq = constraints.get("equipment", [])
        if "combine" not in eq:
            out.append({"text": "It needs only the hay equipment and drill you said you have.", "panel": "climate"})
    if "keeps_forage" in tags and res["scores"]["income"] >= existing["scores"]["income"] - 0.12:
        out.append({"text": "It keeps most of the forage value of the existing rotation "
                            f"({res['scores']['income'] * 100:.0f} % vs {existing['scores']['income'] * 100:.0f} % "
                            "of well-watered alfalfa).", "panel": "water"})
    if cond["hot_trend"].get("significant") and cond["hot_trend"].get("slope_per_decade", 0) > 0 \
            and res["scores"]["resilience"] > existing["scores"]["resilience"] + 0.02:
        a = cond["hot_trend"]["slope_per_decade"]
        g = cond["hot_trend_ground"]
        if g.get("per_decade") is not None and (g.get("p_value") or 1) < 0.05 and g["per_decade"] > 0:
            lo, hi = sorted((a, g["per_decade"]))
            rate = f"about +{lo:.0f} to +{hi:.0f} days per decade since 1991, depending on the dataset"
        else:
            rate = (f"about +{a:.0f} days per decade since 1991 in NASA POWER; the ground-informed "
                    "gridMET record does not confirm a clear trend")
        out.append({"text": f"Days above 32 °C have been increasing ({rate}); this rotation leans on crops "
                            "that cope better with heat.", "panel": "climate"})
    if not out:
        out.append({"text": "It is included so that you can see how a different mix of crops trades off "
                            "against the existing rotation on this field.", "panel": "history"})
    return out


def dynamic_flags(res: dict, ctx: dict, cond: dict, constraints: dict, supply_mm: float) -> tuple[list[str], list[str]]:
    """Field-specific risks and information gaps on top of the knowledge-base lists."""
    risks, gaps = [], []
    src = ctx.get("sources", {})
    for c in res["crop_notes"]:
        if c["frost_free_days_needed"] > 0 and c["season_fit"] < 0.8:
            risks.append(f"{c['label']} needs about {c['frost_free_days_needed']} frost-free days; this field had "
                         f"that many in only {c['season_fit'] * 100:.0f} % of the last 30 years "
                         f"(median {cond['frost_free']:.0f} days).")
        if c["equipment_missing"]:
            risks.append(f"{c['label']} needs equipment you did not tick: {', '.join(c['equipment_missing'])}.")
        thr = c.get("salt_threshold_ds_m")
        both_alfalfa = c["crop"] == "alfalfa_est" and any(x["crop"] == "alfalfa" for x in res["crop_notes"])
        if thr and cond["ec"] is not None and cond["ec"] > thr and not both_alfalfa:
            risks.append(f"Soil-survey salinity ({cond['ec']:.1f} dS/m) is above the level where "
                         f"{c['label'].lower()} starts losing yield ({thr} dS/m).")
        if str(c["market"]).startswith(("niche", "uncertain")) and constraints.get("market") == "established_only":
            risks.append(f"{c['label']} has a {str(c['market']).split(' ')[0]} market and you asked for established markets only.")
    w = res["water"]
    if w["years_short_of_supply"]:
        risks.append(f"In {w['years_short_of_supply']} of {w['n_years']} years it needs more irrigation than the "
                     f"{round(supply_mm)} mm you said you can count on (peak year {w['peak_year_mm']} mm).")
    if cond["ph"] is not None and cond["ph"] >= 8.5:
        risks.append(f"Soil-survey pH is about {cond['ph']:.1f} (strongly alkaline), which can hinder seedling "
                     "establishment and nutrient uptake.")
    if not src.get("imerg"):
        gaps.append("Rainfall is NASA POWER's ~50 km grid corrected to gridMET; the GPM IMERG satellite "
                    "record is not loaded yet.")
    if not src.get("openet"):
        gaps.append("No OpenET record for this field, so water figures are textbook estimates only.")
    if res["is_existing"] and ctx.get("n_doubtful_years"):
        gaps.append(f"{ctx['n_doubtful_years']} year(s) of the crop history are doubtful: the crop map and the "
                    "greenness record disagree.")
    gaps.append("Soil moisture comes from 9 km satellite pixels and soil properties from survey map units: "
                "neither is a measurement in this field.")
    return risks, gaps


def confidence_for(res: dict, details: dict, weights: dict, ctx: dict) -> dict:
    score = sum(weights[c] * CONF_VALUE[details[c]["confidence"]] for c in weights)
    reasons = []
    src = ctx.get("sources", {})
    missing = [k for k in ("openet", "landsat", "ssurgo", "cdl", "smap") if not src.get(k)]
    if missing:
        score -= 0.05 * len(missing)
        reasons.append("Missing for this field: " + ", ".join(missing) + ".")
    if not src.get("imerg"):
        reasons.append("Rainfall from the corrected NASA POWER grid (IMERG pending).")
    if ctx.get("is_custom"):
        score -= 0.05
        reasons.append("Field drawn by hand: boundary and crop history are less certain.")
    top = sorted(weights, key=lambda c: -weights[c])[:3]
    low = [c for c in top if details[c]["confidence"] == "low"]
    if low:
        reasons.append("Your heaviest priorities include ones scored from general crop tables rather than "
                       "data from this field (" + ", ".join(low).replace("_", " ") + ").")
    else:
        reasons.append("Your heaviest priorities are scored mainly from satellite and weather data for this field.")
    level = "high" if score >= 0.72 else "medium" if score >= 0.5 else "low"
    return {"level": level, "score": round(clamp(score), 2), "reasons": reasons}


# ---------------------------------------------------------------------------
# Top level
# ---------------------------------------------------------------------------
def climate_for(ctx: dict, scenario: Scenario) -> dict:
    p = ctx["power"]
    prep = prepare_daily(p["daily"], ctx["lat"], ctx["elevation_m"], p["grid_elevation_m"], scenario,
                         precip=p.get("precip_override"), bias=p.get("bias"))
    return summarise(prep)


def score_field(ctx: dict, kb: dict, weights: dict | None = None, constraints: dict | None = None,
                scenario: Scenario | None = None, clim_base: dict | None = None) -> dict[str, Any]:
    scenario = (scenario or Scenario()).clamp()
    constraints = {**DEFAULT_CONSTRAINTS, **(constraints or {})}
    w = normalise_weights(weights or {}, kb)
    clim_base = clim_base or climate_for(ctx, Scenario())
    is_base = scenario.rain_pct == 0 and scenario.temp_c == 0
    clim = clim_base if is_base else climate_for(ctx, scenario)
    slope = ctx.get("slope_pct") or 0.3
    hazard = hazard_weights(clim, ctx.get("soil", {}), slope)

    # water the farmer can count on, as a share of what full alfalfa needs here today
    full = water_year([{"crop": "alfalfa"}], kb, clim_base, ctx.get("water_factor", 1.0))["nir"]
    supply_mm = full * float(np.clip(constraints.get("water_supply_pct", 100), 20, 150)) / 100.0

    strategies = [existing_rotation(ctx["history"], kb)]
    for sid, s in kb["strategies"].items():
        strategies.append({**s, "id": sid})
    alfalfa_mm = water_year([{"crop": "alfalfa"}], kb, clim, ctx.get("water_factor", 1.0))["nir"]
    results = [evaluate_strategy(s, ctx, kb, clim, clim_base, constraints, supply_mm, hazard, alfalfa_mm)
               for s in strategies]
    existing = results[0]
    existing["assumptions"] = strategies[0].get("assumptions", [])
    cond = field_conditions(ctx, kb, clim, hazard, existing)

    for res, strat in zip(results, strategies):
        details = {c: criterion_detail(c, res, ctx, kb, clim, hazard, existing, constraints, supply_mm)
                   for c in kb["criteria"]}
        total = sum(w[c] * res["scores"][c] for c in w)
        for c in details:
            details[c].update(weight=round(w[c], 4), contribution=round(w[c] * res["scores"][c], 4),
                              label=kb["criteria"][c]["label"])
        risks, gaps = dynamic_flags(res, ctx, cond, constraints, supply_mm)
        static = kb["existing_strategy"] if res["is_existing"] else strat
        res.update(
            total=round(total, 4), criteria=details,
            why=([{"text": "This is the rotation the field has followed, shown as the baseline to "
                           "compare against.", "panel": "history"}] if res["is_existing"]
                 else why_suggested(res, cond, existing, constraints)),
            benefits=list(static["benefits"]), risks=risks + list(static["risks"]),
            info_gaps=gaps + list(static["info_gaps"]),
            verify=list(static["verify"]) + list(kb["always_verify"]),
            confidence=confidence_for(res, details, w, ctx),
        )
        res.pop("tags", None)

    order = sorted(results, key=lambda r: -r["total"])
    for rank, r in enumerate(order, 1):
        r["rank"] = rank
    best = order[0]
    # only priorities the farmer actually weighted can be named as reasons
    active = [c for c in kb["criteria"] if w[c] > 0.001]
    lead = {c: best["scores"][c] - float(np.mean([r["scores"][c] for r in results])) for c in active}
    ranked = sorted(active, key=lambda c: -w[c] * lead[c])
    name = lambda c: f"\"{kb['criteria'][c]['label']}\""  # noqa: E731
    strong = [name(c) for c in ranked[:2] if lead[c] > 0] or [name(ranked[0])]
    close = len(order) > 1 and (best["total"] - order[1]["total"]) < 0.02
    statement = (f"Under your priorities, \"{best['short']}\" scores highest ({best['total'] * 100:.0f} out of 100), "
                 f"mainly on {' and '.join(strong)}.")
    weakest = min(active, key=lambda c: lead[c])
    if len(active) >= 3 and lead[weakest] < 0:
        statement += f" It scores below the others on {name(weakest)}."
    if close:
        statement += f" \"{order[1]['short']}\" is within two points, so treat them as a tie."
    return {
        "field_id": ctx["field_id"],
        "weights": {c: round(v, 4) for c, v in w.items()},
        "constraints": constraints, "water_supply_mm": round(supply_mm),
        "full_alfalfa_irrigation_mm": round(full),
        "scenario": {"rain_pct": scenario.rain_pct, "temp_c": scenario.temp_c, "is_baseline": is_base},
        "statement": statement,
        "disclaimer": "This compares options; it does not tell you what to plant. It supports, and does "
                      "not replace, your own judgment and local agricultural expertise.",
        "strategies": results,
        "ranking": [r["id"] for r in order],
        "hazard": {k: v for k, v in hazard.items() if k != "weights"} | {
            "weights": {m: round(v, 4) for m, v in hazard["weights"].items()}},
        "climate": {k: clim[k] for k in ("et0_month", "precip_month", "tmax_month", "tmin_month",
                                         "windy_days_month", "heavy_rain_days_month", "et0_annual",
                                         "precip_annual", "frost_free_median", "frost_free_p20",
                                         "last_spring_frost_median_doy", "first_fall_frost_median_doy")}
                   | {"hot_days_32": round(sum(clim["heat_days_month"][32].values()), 1),
                      "hot_days_35": round(sum(clim["heat_days_month"][35].values()), 1)},
        "climate_baseline": {"et0_annual": clim_base["et0_annual"], "precip_annual": clim_base["precip_annual"],
                             "frost_free_median": clim_base["frost_free_median"],
                             "hot_days_32": round(sum(clim_base["heat_days_month"][32].values()), 1)},
    }
