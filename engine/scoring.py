"""Transparent rotation scoring: rule-based agronomy + weighted multi-criteria analysis.

    Score(strategy) = sum_i  w_i * s_i(strategy)          (weights normalised to 1)

Each criterion score s_i is between 0 and 1 and comes back with the formula, the inputs
that produced it, their sources and a confidence level, so that every number shown in
the app can be traced. Nothing here predicts yield, and nothing here says "plant X".

The same code serves every region; what differs is the knowledge base (crops, rotations,
and a few `settings`: how pest pressure is judged, which rotation is the water yardstick,
and whether the existing rotation is read from a crop map or chosen by the farmer).

The browser runs a TypeScript port of this file (frontend/src/engine). The port is checked
against this reference by tests/test_parity.py.
"""
from __future__ import annotations

from typing import Any

import numpy as np

from .agromet import effective_precip_usda
from .climate import MONTHS, Scenario, apply_scenario, heat_days_in, prepare_daily, season_fit, summarise_for
from .history import existing_rotation
from .knowledge import entry_months, fill_residue, reference_years, year_profiles

CONF_VALUE = {"high": 1.0, "medium": 0.6, "low": 0.3}
MONTH_NAMES = ["", "Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]
GRASS_FAMILY = "Poaceae"


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


def default_constraints(kb: dict) -> dict:
    return {"water_supply_pct": 100, "equipment": list(kb["settings"]["default_equipment"]), "market": "some"}


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
    """Crop water demand, effective rain and net irrigation need for one rotation year (mm).

    Crops marked `irrigated: false` (grown on leftover soil moisture) add nothing here.
    `nir` is what the crops themselves need beyond usable rain. `extra` is the water a paddy
    field takes on top of that to be puddled and kept flooded. `applied` = nir + extra is the
    water that has to be delivered to the field, and is what the water score uses.
    """
    kc, _ = year_profiles(year, kb)
    etc = {m: kc[m] * clim["et0_month"][m] * factor for m in MONTHS}
    active = [m for m in MONTHS if kc[m] > 0]
    pe = {m: 0.0 for m in MONTHS}
    if active:
        vals = effective_precip_usda([clim["precip_month"][m] for m in active], [etc[m] for m in active])
        pe.update({m: float(v) for m, v in zip(active, vals)})
    nir = {m: max(etc[m] - pe[m], 0.0) for m in MONTHS}
    ky_num = ky_den = 0.0
    irrigated = [e for e in year if kb["crops"][e["crop"]].get("irrigated", True)]
    for m in active:
        best = max((e for e in irrigated if m in entry_months(e, kb)),
                   key=lambda e: kb["crops"][e["crop"]]["kc"].get(m, 0.0))
        ky_num += kb["crops"][best["crop"]]["traits"]["ky"] * etc[m]
        ky_den += etc[m]
    extra = sum(float(kb["crops"][e["crop"]]["traits"].get("extra_water_mm", 0) or 0) * season_fraction(e, kb)
                for e in year)
    total = sum(nir.values())
    return {"etc": sum(etc.values()), "pe": sum(pe.values()), "nir": total, "nir_month": nir,
            "ky": (ky_num / ky_den) if ky_den else 0.0, "extra": extra, "applied": total + extra,
            "peak_share": (nir[7] + nir[8]) / total if total > 0 else 0.0,
            "early_share": (nir[6] + nir[7]) / total if total > 0 else 0.0}


def water_score(irrigation_mm: float, reference_mm: float) -> float:
    """0 = as thirsty as the reference rotation on this field; 1 = half of that, or less.

    score = 2 x (1 - irrigation need / reference irrigation need), limited to 0-1.
    Rotations rarely save more than half, so the scale is stretched over the range that
    actually separates them; the millimetres are always shown next to the score.
    """
    if reference_mm <= 0:
        return 0.0
    return clamp(2.0 * (1.0 - irrigation_mm / reference_mm))


def hazard_weights(clim: dict, soil: dict, slope_pct: float) -> dict:
    """When is this field's soil most at risk? Monthly weights (sum 1) from wind and heavy rain.

    Wind: days a year with daily-mean wind above the region's threshold, scaled by the soil's
    wind erodibility index (NRCS). Rain: heavy-rain days, scaled by slope and the K factor.
    """
    wei = soil.get("wind_erodibility_index")
    wei = 86.0 if wei is None or not np.isfinite(wei) else float(wei)
    kw = soil.get("kwfact_surface")
    kw = 0.3 if kw is None or not np.isfinite(kw) else float(kw)
    wind_w = clamp(wei / 134.0, 0.15, 1.6)
    rain_w = clamp(slope_pct / 2.0, 0.05, 1.5) * clamp(kw / 0.30, 0.3, 1.6)
    wd, hr = clim["windy_days_month"], clim["heavy_rain_days_month"]
    wsum, hsum = sum(wd.values()), sum(hr.values())
    if wsum <= 0:
        wind_w = 0.0
    if hsum <= 0:
        rain_w = 0.0
    raw = {}
    for m in MONTHS:
        w = wind_w * (wd[m] / wsum) if wsum > 0 else 0.0
        r = rain_w * (hr[m] / hsum) if hsum > 0 else 0.0
        raw[m] = w + r
    total = sum(raw.values())
    weights = {m: (raw[m] / total if total > 0 else 1.0 / 12.0) for m in MONTHS}
    wind_share = wind_w / (wind_w + rain_w) if (wind_w + rain_w) > 0 else 0.5
    level = "high" if wei >= 134 else "moderate" if wei >= 86 else "low"
    top = sorted(MONTHS, key=lambda m: -weights[m])[:3]
    return {"weights": weights, "wind_share": round(wind_share, 2), "wind_level": level,
            "wind_erodibility_index": wei, "k_factor": kw, "peak_months": sorted(top),
            "windy_days_year": round(wsum, 1), "heavy_rain_days_year": round(hsum, 1),
            "heavy_rain_mm": clim.get("heavy_rain_mm", 10)}


def _runs(flags: list[bool], target: bool) -> list[int]:
    """Lengths of cyclic runs of `target` in a list of flags."""
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


def _groups(years: list[list[dict]], kb: dict) -> set[str]:
    groups: set[str] = set()
    for y in years:
        for e in y:
            g = kb["crops"][e["crop"]]["group"]
            if g == "cover mix":
                groups.update({"cool-season grass", "legume"})
            elif g not in ("none", "unknown"):
                groups.add(g)
    return groups


def pest_metrics(years: list[list[dict]], kb: dict) -> dict:
    """How well the rotation breaks pest, disease and weed cycles.

    stand model (perennial stands such as alfalfa):
        0.45 x break between stands + 0.35 x plant-group diversity + 0.20 x stand-age score
    annual model (two or three crops every year):
        0.35 x plant-group diversity + 0.30 x share of crops that change from one year to the
        next + 0.35 x share of crop hand-overs that are NOT grass-after-grass
    """
    st = kb["settings"]
    groups = _groups(years, kb)
    diversity = clamp((len(groups) - 1) / 3.0)
    n = len(years)
    if st["pest_model"] == "stand":
        stand = set(st["stand_crops"])
        is_stand = [any(e["crop"] in stand for e in y) for y in years]
        stand_runs, gap_runs = _runs(is_stand, True), _runs(is_stand, False)
        if not any(is_stand):
            gap, longest, break_score, age_score = n, 0, 1.0, 1.0
        else:
            gap = min(gap_runs) if gap_runs else 0
            longest = max(stand_runs)
            break_score = 0.0 if gap == 0 else 0.6 if gap == 1 else 1.0
            age_score = clamp(1.0 - (longest - 5) / 5.0)
        return {"model": "stand", "gap_years": gap, "longest_stand": longest, "groups": sorted(groups),
                "break_score": break_score, "diversity_score": round(diversity, 3),
                "age_score": round(age_score, 3),
                "score": round(0.45 * break_score + 0.35 * diversity + 0.20 * age_score, 4)}

    # annual model
    crops_by_year = [[e["crop"] for e in y if e["crop"] != "fallow"] for y in years]
    sets = [list(dict.fromkeys(c)) for c in crops_by_year]
    total = repeated = 0
    for i, crops in enumerate(sets):
        nxt = set(sets[(i + 1) % n])
        total += len(crops)
        repeated += sum(c in nxt for c in crops)
    change = 1.0 - (repeated / total) if total else 1.0
    seq: list[str] = []
    for crops in crops_by_year:
        for c in crops:
            if not seq or seq[-1] != c:
                seq.append(c)
    if len(seq) > 1 and seq[0] == seq[-1]:
        seq.pop()
    pairs = [(seq[i], seq[(i + 1) % len(seq)]) for i in range(len(seq))] if len(seq) > 1 else []
    grass_after_grass = sum(kb["crops"][a]["family"] == GRASS_FAMILY and kb["crops"][b]["family"] == GRASS_FAMILY
                            for a, b in pairs)
    handover = 1.0 - grass_after_grass / len(pairs) if pairs else 0.0
    return {"model": "annual", "groups": sorted(groups), "diversity_score": round(diversity, 3),
            "change_score": round(change, 3), "handover_score": round(handover, 3),
            "grass_after_grass": int(grass_after_grass), "handovers": len(pairs),
            "crops_per_year": round(float(np.mean([len(s) for s in sets])), 2) if sets else 0.0,
            "score": round(0.35 * diversity + 0.30 * change + 0.35 * handover, 4)}


def nitrogen_year(i: int, years: list[list[dict]], kb: dict) -> float:
    """stand model: stand year = its n_score; first year after the stand 0.6; second 0.3; a
    legume cover crop adds up to 0.5.   annual model: sum of each crop's n_score x season share."""
    year = years[i]
    stand = set(kb["settings"]["stand_crops"])
    if kb["settings"]["pest_model"] != "stand":
        return clamp(sum(kb["crops"][e["crop"]]["traits"]["n_score"] * season_fraction(e, kb) for e in year))
    crops = {e["crop"] for e in year}
    if crops & stand:
        return max(kb["crops"][c]["traits"]["n_score"] for c in crops & stand)
    had = lambda y: any(e["crop"] in stand for e in y)  # noqa: E731
    carry = 0.6 if had(years[i - 1]) else 0.3 if had(years[i - 2]) else 0.0
    cover = max((kb["crops"][e["crop"]]["traits"]["n_score"] * season_fraction(e, kb) for e in year), default=0.0)
    return clamp(carry + cover)


# ---------------------------------------------------------------------------
# One strategy
# ---------------------------------------------------------------------------
def evaluate_strategy(strategy: dict, ctx: dict, kb: dict, clim: dict, clim_base: dict,
                      constraints: dict, supply_mm: float, hazard: dict, reference_mm: float) -> dict:
    years = strategy["years"]
    n = len(years)
    factor = ctx.get("water_factor", 1.0)
    equipment = set(constraints.get("equipment", []))
    market = constraints.get("market", "some")
    ffd = clim["frost_free_days"]
    heat_full = float(kb["settings"]["heat_days_full"])

    wy = [water_year(y, kb, clim, factor) for y in years]
    covers = fill_residue([year_profiles(y, kb)[1] for y in years])
    nir_mean = float(np.mean([w["nir"] for w in wy]))
    etc_mean = float(np.mean([w["etc"] for w in wy]))
    pe_mean = float(np.mean([w["pe"] for w in wy]))
    extra_mean = float(np.mean([w["extra"] for w in wy]))
    applied_mean = nir_mean + extra_mean
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
            mclass = str(t["market"]).split(" ")[0]
            mf = kb["market_factor"].get(mclass, {}).get(market, 1.0)
            value += t["value_score"] * frac * mf
            if e["crop"] != "fallow" and frac > 0:
                months = [m for m in entry_months(e, kb) if m in crop["kc"]]
                hd = heat_days_in(months, t["heat_limit_c"], clim)
                heat_ok = 1.0 - clamp(hd / heat_full)
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
                    "market": mclass, "salt_threshold_ds_m": t.get("salt_threshold_ds_m"),
                    "heat_limit_c": t["heat_limit_c"], "n_score": t["n_score"],
                    "n_credit_kg_ha": t.get("n_credit_kg_ha"),
                    "establishment_risk": t["establishment_risk"]}
        om_year.append(clamp(om - 0.08 * plantings))
        # water shortage -> yield (FAO-33): 1 - Ya/Ym = Ky * (1 - ETa/ETm)
        w = wy[i]
        rel_yield = 1.0
        if w["etc"] > 0 and w["applied"] > supply_mm + 0.5:      # half a millimetre: not a rounding accident
            # a shortfall is shared in proportion between the crop's own need and the flooding water
            eta = w["pe"] + w["nir"] * supply_mm / w["applied"]
            rel_yield = clamp(1.0 - w["ky"] * (1.0 - eta / w["etc"]))
            short_years += 1
        income_year.append(clamp(value) * rel_yield)
        res_year.append(res_num / res_den if res_den else 0.5)
        feas_year.append(clamp(float(np.mean(feas_parts)) - 0.05 * max(plantings - 1, 0)))

    pest = pest_metrics(years, kb)
    scores = {
        "water": water_score(applied_mean, reference_mm),
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
        "summary": " ".join(str(strategy["summary"]).split()), "is_existing": bool(strategy.get("is_existing")),
        "tags": strategy.get("tags", []),
        "scores": {k: round(v, 4) for k, v in scores.items()},
        "water": {"etc_mm": round(etc_mean), "effective_rain_mm": round(pe_mean),
                  "irrigation_mm": round(applied_mean), "crop_need_mm": round(nir_mean),
                  "reference_et_mm": round(ref),
                  "reference_mm": round(reference_mm),
                  "saving_vs_reference_pct": round(100.0 * (1.0 - applied_mean / reference_mm)) if reference_mm else 0,
                  "extra_pumping_mm": round(extra_mean),
                  "early_share": round(float(np.mean([w["early_share"] for w in wy])), 2),
                  "by_year": [{"etc_mm": round(w["etc"]), "irrigation_mm": round(w["applied"]),
                               "effective_rain_mm": round(w["pe"]),
                               "july_august_share": round(w["peak_share"], 2)} for w in wy],
                  "peak_year_mm": round(max(w["applied"] for w in wy)),
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
        entries = []
        for e in year:
            crop = kb["crops"][e["crop"]]
            entries.append({"crop": e["crop"], "label": crop["short"], "group": crop["group"],
                            "months": entry_months(e, kb)})
        out.append({"year": i + 1, "calendar_year": labels[i] if labels else None, "entries": entries,
                    "label": " + ".join(dict.fromkeys(x["label"] for x in entries))})
    return out


# ---------------------------------------------------------------------------
# Explanations
# ---------------------------------------------------------------------------
def _local(ctx: dict) -> str:
    kind = ctx.get("climate_correction")
    if kind == "gridmet":
        return "corrected month by month to gridMET (4 km)"
    if kind == "imd":
        return "corrected month by month to India's weather-station grids (IMD)"
    if kind == "imd_rain":
        return "shifted to field elevation; rain scaled to India's rain-gauge grid (IMD)"
    return "shifted to field elevation (lapse rate)"


def _rain_source(ctx: dict) -> str:
    ground = {"gridmet": "gridMET", "imd": "IMD rain gauges",
              "imd_rain": "IMD rain gauges"}.get(ctx.get("climate_correction"))
    if ctx.get("sources", {}).get("imerg"):
        return "GPM IMERG" + (f" scaled to {ground}" if ground else "")
    return "NASA POWER" + (f" corrected to {ground}" if ground else "") + " (IMERG not loaded)"


def _soil_source(ctx: dict, survey: str = "SSURGO (USDA NRCS)") -> str:
    return "SoilGrids (ISRIC, 250 m model)" if ctx.get("soil_source") == "soilgrids" else survey


def criterion_detail(cid: str, res: dict, ctx: dict, kb: dict, clim: dict, hazard: dict,
                     existing: dict | None, constraints: dict, supply_mm: float) -> dict:
    """Formula, inputs and confidence behind one criterion score."""
    s = res["scores"][cid]
    src = ctx.get("sources", {})
    local = _local(ctx)
    ref_label = kb["settings"]["water_reference"]["label"]
    hot_c = int(kb["settings"]["hot_day_c"])
    crops_used = {e["crop"] for y in res["sequence"] for e in y["entries"]}
    if cid == "water":
        w = res["water"]
        anchored = bool(ctx.get("water_factor_info", {}).get("available"))
        inputs = [
            {"label": "Crop water demand (rotation average)", "value": w["etc_mm"], "unit": "mm/yr",
             "source": "FAO-56 crop coefficients x reference ET from NASA POWER"},
            {"label": "Rain the crops can use", "value": w["effective_rain_mm"], "unit": "mm/yr",
             "source": f"{_rain_source(ctx)}, USDA-SCS effective-rain method"},
            {"label": "Irrigation the crops need (rotation average)", "value": w["crop_need_mm"], "unit": "mm/yr",
             "source": "demand minus usable rain"},
            {"label": f"{ref_label[0].upper()}{ref_label[1:]} on this field would need", "value": w["reference_mm"],
             "unit": "mm/yr", "source": "same method; the yardstick for this score"},
            {"label": "Reference ET at this field", "value": w["reference_et_mm"], "unit": "mm/yr",
             "source": f"NASA POWER ({local}), FAO-56 Penman-Monteith, 1996-2025"},
        ]
        if anchored:
            f = ctx["water_factor_info"]
            inputs.append({"label": "Adjustment to this field's own record", "value": round(ctx["water_factor"], 2),
                           "unit": "x", "source": f"OpenET, alfalfa years {f['years'][0]}-{f['years'][-1]}: "
                                                  "measured-from-space ET divided by the textbook figure"})
        if w["extra_pumping_mm"] > 0:
            inputs.insert(3, {"label": "Water to puddle the soil and keep paddy flooded",
                              "value": w["extra_pumping_mm"], "unit": "mm/yr",
                              "source": "knowledge base (typical figure; part of it seeps back to groundwater)"})
            inputs.insert(4, {"label": "Irrigation to deliver to the field", "value": w["irrigation_mm"],
                              "unit": "mm/yr", "source": "crop need plus puddling and flooding water"})
        note = "Model-based: gridded weather and textbook crop coefficients."
        if anchored:
            note += " Anchored to OpenET satellite ET for this field."
            conf = "medium"
        elif src.get("et"):
            note += " A satellite water-use record exists for this spot and is shown as evidence, but the estimate is not scaled to it."
            conf = "medium"
        else:
            note += " No satellite water-use record for this field, so nothing anchors it."
            conf = "low"
        if crops_used & {"teff", "safflower"}:
            note += " Water use of teff and safflower here is poorly documented."
        if w["extra_pumping_mm"] > 0:
            note += (" The flooding figure for paddy is a typical value, not a measurement of this field: sandy "
                     "soils take more, heavy clay less, and part of it seeps back to the groundwater.")
        formula = (f"score = 2 x (1 - irrigation need / {ref_label} irrigation need), limited to 0-1: "
                   f"0 = as thirsty as {ref_label}, 1 = half the water or less")
        headline = f"Needs about {w['irrigation_mm']} mm of irrigation a year"
        if existing and not res["is_existing"] and existing["water"]["irrigation_mm"]:
            diff = w["irrigation_mm"] - existing["water"]["irrigation_mm"]
            pct = 100.0 * diff / existing["water"]["irrigation_mm"]
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
             "source": "windy days and heavy-rain days from the weather record, weighted by soil and slope"},
            {"label": "Average cover in those months", "value": round(float(np.mean([avg[m] for m in peak])) * 100),
             "unit": "%", "source": "crop calendar in the knowledge base"},
            {"label": "Soil wind-erodibility index", "value": round(hazard["wind_erodibility_index"]),
             "unit": "t/ac/yr", "source": _soil_source(ctx).replace("SoilGrids (ISRIC, 250 m model)", "derived from SoilGrids texture (NRCS groups)")},
            {"label": "Field tilt", "value": ctx.get("slope_pct"), "unit": "%", "source": "SRTM plane fit"},
        ]
        main = ("wind is the main erosion risk" if hazard["wind_share"] >= 0.6 else
                "hard rain is the main erosion risk" if hazard["wind_share"] <= 0.4 else
                "wind and hard rain are both erosion risks")
        return dict(score=s, formula="score = sum over months of (risk weight x share of soil covered)",
                    headline=f"Soil covered {s * 100:.0f} % of the time that matters",
                    inputs=inputs, confidence="medium", panel="cover",
                    note="Cover comes from a crop calendar, not from watching this rotation on your field. "
                         f"Here {main}.")
    if cid == "nitrogen":
        legume_crops = sorted({c["label"] for c in res["crop_notes"] if c["n_score"] >= 0.5})
        years_with = sum(any(kb["crops"][e["crop"]]["traits"]["n_score"] >= 0.5 for e in y["entries"])
                         for y in res["sequence"])
        formula = ("legume year = 1; first year after alfalfa = 0.6; second = 0.3; legume cover crop adds up to 0.5"
                   if kb["settings"]["pest_model"] == "stand" else
                   "sum of each crop's nitrogen class x share of its season, limited to 1")
        return dict(score=s, formula=formula,
                    headline=f"Legumes in {years_with} of {len(res['sequence'])} years",
                    inputs=[{"label": "Legumes in the rotation", "value": ", ".join(legume_crops) or "none", "unit": "",
                             "source": "rotation definition"},
                            {"label": "Years with a legume", "value": years_with, "unit": f"of {len(res['sequence'])}",
                             "source": "rotation definition"}],
                    confidence="medium", panel="history",
                    note="A well-established principle, but the real credit depends on the crop stand, soil and "
                         "management. A soil test is the only measurement.")
    if cid == "organic_matter":
        om = ctx.get("soil", {}).get("om_pct_0_30")
        return dict(score=s, formula="sum of each crop's root-and-residue class, minus 0.08 per sowing (tillage)",
                    headline="Root and residue inputs: " + ("high" if s >= 0.7 else "moderate" if s >= 0.5 else "low"),
                    inputs=[{"label": "Soil organic matter today (0-30 cm)",
                             "value": None if om is None else round(om, 1), "unit": "%", "source": _soil_source(ctx)},
                            {"label": "Sowings per rotation",
                             "value": sum(1 for y in res["sequence"] for e in y["entries"] if min(e["months"]) > 1
                                          and kb["crops"][e["crop"]]["traits"]["plantings"] > 0),
                             "unit": "", "source": "rotation definition"}],
                    confidence="low", panel="soil",
                    note="Class scores only. Organic matter changes over many years and cannot be seen "
                         "from space; satellites do not measure it.")
    if cid == "pest_break":
        p = res["pest"]
        if p["model"] == "stand":
            formula = "0.45 x break between alfalfa stands + 0.35 x plant-group diversity + 0.20 x stand-age score"
            headline = (f"{p['gap_years']}-year break between alfalfa stands" if p["longest_stand"]
                        else "No alfalfa in the rotation")
            inputs = [{"label": "Years out of alfalfa between stands", "value": p["gap_years"], "unit": "years",
                       "source": "rotation definition; Extension guidance asks for at least 1"},
                      {"label": "Plant groups in the rotation", "value": ", ".join(p["groups"]) or "none",
                       "unit": "", "source": "knowledge base"},
                      {"label": "Longest alfalfa stand", "value": p["longest_stand"], "unit": "years",
                       "source": "rotation definition"}]
        else:
            formula = ("0.35 x plant-group diversity + 0.30 x share of crops that change from year to year "
                       "+ 0.35 x share of crop hand-overs that are not cereal after cereal")
            headline = (f"{len(p['groups'])} plant group(s); {p['grass_after_grass']} of {p['handovers']} "
                        "hand-overs are cereal after cereal")
            inputs = [{"label": "Plant groups in the rotation", "value": ", ".join(p["groups"]) or "none",
                       "unit": "", "source": "knowledge base"},
                      {"label": "Crops that change from one year to the next", "value": round(p["change_score"] * 100),
                       "unit": "%", "source": "rotation definition"},
                      {"label": "Cereal-after-cereal hand-overs", "value": p["grass_after_grass"],
                       "unit": f"of {p['handovers']}", "source": "rotation definition"}]
        doubtful = res["is_existing"] and ctx.get("n_doubtful_years", 0) > 2
        return dict(score=s, formula=formula, headline=headline, inputs=inputs,
                    confidence="low" if doubtful else "medium", panel="history",
                    note="Counts breaks and plant families; it knows nothing about which pests, diseases or "
                         "weeds are actually in your field.")
    if cid == "income":
        w = res["water"]
        inputs = [{"label": f"Value relative to {ref_label}", "value": round(s * 100), "unit": "%",
                   "source": "class scores in the knowledge base (no prices)"},
                  {"label": "Your market setting", "value": constraints.get("market", "some"), "unit": "",
                   "source": "your input"},
                  {"label": "Years needing more water than your supply", "value": w["years_short_of_supply"],
                   "unit": f"of {w['n_years']}", "source": f"your supply setting ({round(supply_mm)} mm/yr)"}]
        return dict(score=s, formula="sum of crop value classes x market factor, reduced by water shortage (FAO-33 yield response)",
                    headline=f"About {s * 100:.0f} % of the value of well-watered {ref_label}",
                    inputs=inputs, confidence="low", panel="water",
                    note="No local prices, yields or costs are in this tool. Treat this as a rough ordering "
                         "and replace it with your own budget.")
    if cid == "resilience":
        hot = round(sum(clim["hot_days_month"].values()), 1)
        full = int(kb["settings"]["heat_days_full"])
        return dict(score=s, formula=f"per crop: 0.5 x drought-tolerance class + 0.5 x (1 - days above its heat limit in its season / {full})",
                    headline="Copes with heat and short water: " + ("well" if s >= 0.7 else "moderately" if s >= 0.55 else "poorly"),
                    inputs=[{"label": f"Days a year above {hot_c} °C", "value": hot, "unit": "days",
                             "source": f"NASA POWER, {local}"},
                            {"label": "Crops' own heat limits", "value": ", ".join(
                                f"{c['label']} {c['heat_limit_c']} °C" for c in res["crop_notes"] if c["crop"] != "fallow"),
                             "unit": "", "source": "knowledge base"}],
                    confidence="medium", panel="climate",
                    note="Heat days come from a ~50 km NASA weather grid corrected to local conditions, "
                         "not from a station in the field.")
    # feasibility
    frosty = clim["frost_free_median"] < 330
    worst = min((c for c in res["crop_notes"] if c["frost_free_days_needed"] > 0),
                key=lambda c: c["season_fit"], default=None)
    inputs = [{"label": "Your equipment", "value": ", ".join(constraints.get("equipment", [])) or "none", "unit": "",
               "source": "your input"}]
    if frosty:
        inputs.insert(0, {"label": "Frost-free season (median)", "value": round(clim["frost_free_median"]),
                          "unit": "days", "source": f"NASA POWER, {local}, 1996-2025"})
    if worst:
        inputs.append({"label": f"Years long enough for {worst['label'].lower()}",
                       "value": round(worst["season_fit"] * 100), "unit": "%",
                       "source": f"needs about {worst['frost_free_days_needed']} frost-free days"})
    risky = sorted((c for c in res["crop_notes"] if c["crop"] != "fallow"), key=lambda c: -c["establishment_risk"])
    if risky:
        inputs.append({"label": "Hardest crop to establish", "value": risky[0]["label"], "unit": "",
                       "source": f"establishment-risk class {risky[0]['establishment_risk']} in the knowledge base"})
    note = ("Frost dates depend heavily on local cold-air pooling. Even after correction to a 4 km "
            "grid, the coldest hollows frost earlier and later than shown: check your own records." if frosty else
            "Season length is not a limit here; the score reflects your equipment and how hard each crop is to establish.")
    return dict(score=s, formula="per crop: 0.45 x season fit + 0.30 x equipment you have + 0.25 x (1 - establishment risk); -0.05 per extra sowing in a year",
                headline="Fits your season and equipment: " + ("well" if s >= 0.75 else "partly" if s >= 0.55 else "poorly"),
                inputs=inputs, confidence="medium", panel="climate", note=note)


def field_conditions(ctx: dict, kb: dict, clim: dict, hazard: dict, existing: dict) -> dict:
    """Facts about this field that the 'why suggested' rules look at."""
    soil = ctx.get("soil", {})
    stand = set(kb["settings"]["stand_crops"])
    run = best = 0
    for r in ctx.get("history", []):
        run = run + 1 if r.get("crop") in stand else 0
        best = max(best, run)
    return {
        "stand_run": best,
        "groups": existing["pest"]["groups"],
        "om": soil.get("om_pct_0_30"), "ec": soil.get("ec_dsm_0_30"), "ph": soil.get("ph_0_30"),
        "texture": soil.get("surface_texture"), "weg": soil.get("wind_erodibility_group"),
        "wind_level": hazard["wind_level"], "wind_share": hazard["wind_share"],
        "peak_months": hazard["peak_months"], "heavy_rain_days": hazard["heavy_rain_days_year"],
        "heavy_rain_mm": hazard["heavy_rain_mm"],
        "gw": ctx.get("groundwater", {}) or {},
        "hot_trend": ctx.get("trends", {}).get("hot_days") or {},
        "hot_trend_ground": ctx.get("trends", {}).get("hot_days_ground") or {},
        "frost_free": clim["frost_free_median"],
        "hot_c": int(kb["settings"]["hot_day_c"]),
    }


def why_suggested(res: dict, cond: dict, existing: dict, constraints: dict, kb: dict) -> list[dict]:
    """Rule-based reasons, each tied to a number from this field and to an evidence panel."""
    tags, out = set(res["tags"]), []
    w, ew = res["water"], existing["water"]
    ref_label = kb["settings"]["water_reference"]["label"]
    saved = ew["irrigation_mm"] - w["irrigation_mm"]
    if "reduces_water" in tags and saved > 15:
        out.append({"text": f"The existing rotation needs about {ew['irrigation_mm']} mm of irrigation a year here, "
                            f"while rain supplies only about {ew['effective_rain_mm']} mm of what the crops use. "
                            f"This rotation needs about {saved} mm a year less.", "panel": "water"})
    gw = cond["gw"]
    if "reduces_water" in tags and gw.get("kind") == "wells" and gw.get("n_wells_trend"):
        if gw["n_deepening"] and gw["n_deepening"] >= gw["n_wells_trend"] / 2:
            out.append({"text": f"{gw['n_deepening']} of {gw['n_wells_trend']} nearby USGS wells with long records "
                                f"show the water table getting deeper since 1990 (median "
                                f"{abs(gw['median_m_per_decade']):.1f} m per decade).", "panel": "groundwater"})
    if "reduces_water" in tags and gw.get("kind") == "grace" and gw.get("significant") \
            and (gw.get("trend_cm_per_year") or 0) < 0:
        out.append({"text": f"NASA's GRACE satellites show the water stored in and on the ground across this region "
                            f"falling by about {abs(gw['trend_cm_per_year']):.1f} cm a year since {gw.get('from_year', 2002)}. "
                            "That is an area about 300 km across, not your village.", "panel": "groundwater"})
    if "no_puddling" in tags and ew["extra_pumping_mm"] - w["extra_pumping_mm"] >= 100:
        out.append({"text": f"Roughly {ew['extra_pumping_mm'] - w['extra_pumping_mm']} mm of that saving is water paddy "
                            "takes only to be puddled and kept flooded. Part of it seeps back to the groundwater, so "
                            "the gain is mostly in pumping cost and in soil structure that is no longer puddled.",
                    "panel": "water"})
    if "resilient_to_late_water" in tags and ew["early_share"] - w["early_share"] >= 0.08:
        out.append({"text": f"Only about {w['early_share'] * 100:.0f} % of its irrigation need falls in June-July, "
                            f"against {ew['early_share'] * 100:.0f} % for the existing rotation, so a late start to "
                            "canal water matters less.", "panel": "water"})
    if "adds_break" in tags and cond["stand_run"] >= 5:
        out.append({"text": f"The crop map shows alfalfa for {cond['stand_run']} years running. Stands usually "
                            f"thin with age, and Extension guidance asks for at least a year in another crop "
                            f"before re-sowing; this rotation gives {res['pest'].get('gap_years', 0)}.", "panel": "history"})
    if tags & {"new_grass_families", "new_broadleaf_family", "new_family"} \
            and len(res["pest"]["groups"]) > len(cond["groups"]):
        out.append({"text": f"The existing rotation uses {len(cond['groups'])} plant group(s) ("
                            + (", ".join(cond["groups"]) or "none") + f"); this one uses {len(res['pest']['groups'])}: "
                            + ", ".join(res["pest"]["groups"]) + ".", "panel": "history"})
    if "adds_legume" in tags and res["scores"]["nitrogen"] > existing["scores"]["nitrogen"] + 0.1:
        leg = [c for c in res["crop_notes"] if c["n_score"] >= 0.5]
        credit = max((c["n_credit_kg_ha"][1] for c in leg if c.get("n_credit_kg_ha")), default=0)
        txt = "It adds " + " and ".join(c["label"].lower() for c in leg) + (
            ", which fixes its own nitrogen" if len(leg) == 1 else ", which fix their own nitrogen")
        txt += f" and can leave up to about {credit} kg N/ha for the next crop." if credit else "."
        if existing["scores"]["nitrogen"] < 0.05:
            txt = "The existing rotation has no legume. " + txt
        out.append({"text": txt, "panel": "soil"})
    months = ", ".join(MONTH_NAMES[m] for m in cond["peak_months"])
    windy = cond["wind_share"] >= 0.6 and cond["wind_level"] in ("moderate", "high")
    soil_txt = f"The soil here ({(cond['texture'] or 'soil').lower()}, wind-erodibility group {cond['weg']}) " \
               f"is {cond['wind_level']}ly prone to blowing, and {months} are the riskiest months."
    if "adds_cover" in tags and res["scores"]["cover"] > existing["scores"]["cover"] + 0.01:
        if windy:
            txt = soil_txt + " This rotation keeps more of the soil covered then."
        else:
            txt = (f"Hard rain and wind are toughest on this soil in {months} "
                   f"({cond['heavy_rain_days']:.0f} days a year with {cond['heavy_rain_mm']:.0f} mm or more). "
                   "This rotation keeps more of the soil covered then.")
        out.append({"text": txt, "panel": "cover"})
    elif "adds_cover" in tags and windy:
        out.append({"text": soil_txt + " Check the cover calendar: the seeding years leave it exposed in spring.",
                    "panel": "cover"})
    if "builds_om" in tags and cond["om"] is not None and cond["om"] < 1.5 \
            and res["scores"]["organic_matter"] >= existing["scores"]["organic_matter"] - 0.1:
        more = res["scores"]["organic_matter"] > existing["scores"]["organic_matter"]
        out.append({"text": f"The soil map puts organic matter at about {cond['om']:.1f} % in the top 30 cm, "
                            "which is low. This rotation returns more roots and residue to the soil"
                            + (" than the existing one." if more else "."), "panel": "soil"})
    if tags & {"salt_tolerant_break", "salt_tolerant"} and cond["ec"] is not None and cond["ec"] >= 2.0:
        out.append({"text": f"The soil survey shows salinity around {cond['ec']:.1f} dS/m, above the level where "
                            "sensitive crops start losing yield; this rotation includes crops that tolerate "
                            "two to four times that.", "panel": "soil"})
    if "deep_roots" in tags:
        out.append({"text": "A taproot crop can reach moisture below the root zone of the cereals and "
                            "grasses, and comes from a plant family the field has not seen.", "panel": "soil"})
    if "familiar_equipment" in tags and not any(c["equipment_missing"] for c in res["crop_notes"]):
        out.append({"text": "It needs only the equipment you said you have.", "panel": "climate"})
    if tags & {"keeps_forage", "keeps_income"} and res["scores"]["income"] >= existing["scores"]["income"] - 0.12:
        out.append({"text": "It keeps most of the income of the existing rotation "
                            f"({res['scores']['income'] * 100:.0f} % vs {existing['scores']['income'] * 100:.0f} % "
                            f"of well-watered {ref_label}).", "panel": "water"})
    ht = cond["hot_trend"]
    if ht.get("significant") and (ht.get("slope_per_decade") or 0) > 0 \
            and res["scores"]["resilience"] > existing["scores"]["resilience"] + 0.02:
        a = ht["slope_per_decade"]
        g = cond["hot_trend_ground"]
        if g.get("per_decade") is not None and (g.get("p_value") or 1) < 0.05 and g["per_decade"] > 0:
            lo, hi = sorted((a, g["per_decade"]))
            rate = f"about +{lo:.0f} to +{hi:.0f} days per decade since 1991, depending on the dataset"
        else:
            rate = f"about +{a:.0f} days per decade since 1991 in NASA POWER"
        out.append({"text": f"Days above {cond['hot_c']} °C have been increasing ({rate}); this rotation leans on "
                            "crops that cope better with heat.", "panel": "climate"})
    if not out:
        out.append({"text": "It is included so that you can see how a different mix of crops trades off "
                            "against the existing rotation on this field.", "panel": "history"})
    return out


def dynamic_flags(res: dict, ctx: dict, cond: dict, constraints: dict, supply_mm: float,
                  kb: dict) -> tuple[list[str], list[str]]:
    """Field-specific risks and information gaps on top of the knowledge-base lists."""
    risks, gaps = [], []
    src = ctx.get("sources", {})
    crops = {c["crop"] for c in res["crop_notes"]}
    for c in res["crop_notes"]:
        if c["frost_free_days_needed"] > 0 and c["season_fit"] < 0.8:
            risks.append(f"{c['label']} needs about {c['frost_free_days_needed']} frost-free days; this field had "
                         f"that many in only {c['season_fit'] * 100:.0f} % of the last 30 years "
                         f"(median {cond['frost_free']:.0f} days).")
        if c["equipment_missing"]:
            risks.append(f"{c['label']} needs equipment you did not tick: {', '.join(c['equipment_missing'])}.")
        thr = c.get("salt_threshold_ds_m")
        twin = c["crop"].endswith("_est") and c["crop"][:-4] in crops
        if thr and cond["ec"] is not None and cond["ec"] > thr and not twin:
            risks.append(f"Soil-survey salinity ({cond['ec']:.1f} dS/m) is above the level where "
                         f"{c['label'].lower()} starts losing yield ({thr} dS/m).")
        if c["market"] in ("niche", "uncertain") and constraints.get("market") == "established_only":
            risks.append(f"{c['label']} has a {c['market']} market and you asked for established markets only.")
        if c["market"] == "established" and constraints.get("market") == "established_only" \
                and kb["market_factor"]["established"]["established_only"] < 1:
            risks.append(f"{c['label']} is sold at open-market prices without assured buying, and you asked "
                         "for assured buyers only.")
    w = res["water"]
    if w["years_short_of_supply"]:
        risks.append(f"In {w['years_short_of_supply']} of {w['n_years']} years it needs more irrigation than the "
                     f"{round(supply_mm)} mm you said you can count on (peak year {w['peak_year_mm']} mm).")
    if cond["ph"] is not None and cond["ph"] >= 8.5:
        risks.append(f"Soil pH is about {cond['ph']:.1f} (strongly alkaline), which can hinder seedling "
                     "establishment and nutrient uptake.")
    if not src.get("imerg"):
        gaps.append("Rainfall comes from NASA POWER's ~50 km grid; the GPM IMERG satellite record is not loaded.")
    if not src.get("et"):
        gaps.append("No satellite water-use record for this field, so water figures are textbook estimates only.")
    if res["is_existing"] and kb["settings"]["existing"] == "from_history" and ctx.get("n_doubtful_years"):
        gaps.append(f"{ctx['n_doubtful_years']} year(s) of the crop history are doubtful: the crop map and the "
                    "greenness record disagree.")
    if ctx.get("soil_source") == "soilgrids":
        gaps.append("Soil values come from a 250 m global model and soil moisture from 9 km satellite pixels: "
                    "neither is a measurement in this field, and salinity is not mapped at all.")
    else:
        gaps.append("Soil moisture comes from 9 km satellite pixels and soil properties from survey map units: "
                    "neither is a measurement in this field.")
    return risks, gaps


def confidence_for(res: dict, details: dict, weights: dict, ctx: dict) -> dict:
    score = sum(weights[c] * CONF_VALUE[details[c]["confidence"]] for c in weights)
    reasons = []
    src = ctx.get("sources", {})
    names = {"et": "satellite water use", "landsat": "Landsat greenness", "soil": "soil map",
             "history": "crop history", "smap": "soil moisture"}
    missing = [names[k] for k in names if not src.get(k)]
    if missing:
        score -= 0.05 * len(missing)
        reasons.append("Missing for this field: " + ", ".join(missing) + ".")
    if not src.get("imerg"):
        reasons.append("Rainfall from the NASA POWER grid (IMERG not loaded).")
    if ctx.get("is_custom"):
        score -= 0.05
        reasons.append("Field placed by hand: boundary and crop history are less certain.")
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
def climate_for(ctx: dict, scenario: Scenario, kb: dict) -> dict:
    p = ctx["power"]
    if "base" in p:         # already-corrected daily weather (the static site's per-field file)
        prep = apply_scenario(p["base"], ctx["lat"], ctx["elevation_m"], scenario)
    else:
        prep = prepare_daily(p["daily"], ctx["lat"], ctx["elevation_m"], p["grid_elevation_m"], scenario,
                             precip=p.get("precip_override"), bias=p.get("bias"))
    return summarise_for(prep, kb)


def strategies_for(ctx: dict, kb: dict, existing_id: str | None) -> tuple[list[dict], dict]:
    """The rotations to compare, existing first. Returns (strategies, info about the existing one)."""
    st = kb["settings"]
    if st["existing"] == "from_history":
        ex = existing_rotation(ctx["history"], kb)
        return [ex] + [dict(s) for s in kb["strategies"].values()], {"mode": "from_history", "chosen": None,
                                                                     "assumptions": ex.get("assumptions", [])}
    known = existing_id in kb["strategies"]
    seen = (ctx.get("phenology") or {}).get("median_seasons")
    per_year = {sid: pest_metrics(s["years"], kb).get("crops_per_year") for sid, s in kb["strategies"].items()}
    assumptions = []
    if known:
        chosen = existing_id
        if seen is not None and abs(seen - per_year[chosen]) >= 1:
            assumptions.append(f"The satellite record shows about {seen:.0f} green season(s) a year on this spot, but "
                               f"the rotation selected has {per_year[chosen]:.0f} crops a year. Check that it "
                               "matches what is grown here.")
    else:
        # no crop map: start from the usual rotation of the area, unless the number of green seasons the
        # satellites see each year fits another of the common rotations better
        chosen = st["existing_default"]
        options = [sid for sid, s in kb["strategies"].items() if s.get("existing_option")]
        if seen is not None and options:
            best = min(options, key=lambda sid: (abs(per_year[sid] - seen), sid != chosen))
            if abs(per_year[best] - seen) < abs(per_year[chosen] - seen):
                chosen = best
            assumptions.append(f"No crop map exists here. The satellite record shows about {seen:.0f} green "
                               f"season(s) a year on this spot, so \"{kb['strategies'][chosen]['short']}\" is taken "
                               "as what you grow now. Choose your own rotation if it differs.")
        else:
            assumptions.append("No crop map exists here, so the most common rotation of the area is taken as what "
                               "you grow now. Choose your own rotation if it differs.")
    out = [{**kb["strategies"][chosen], "is_existing": True}]
    out += [dict(s) for sid, s in kb["strategies"].items() if sid != chosen]
    return out, {"mode": "choose", "chosen": chosen, "assumptions": assumptions}


def score_field(ctx: dict, kb: dict, weights: dict | None = None, constraints: dict | None = None,
                scenario: Scenario | None = None, clim_base: dict | None = None,
                existing_id: str | None = None) -> dict[str, Any]:
    scenario = (scenario or Scenario()).clamp()
    constraints = {**default_constraints(kb), **(constraints or {})}
    w = normalise_weights(weights or {}, kb)
    clim_base = clim_base or climate_for(ctx, Scenario(), kb)
    is_base = scenario.rain_pct == 0 and scenario.temp_c == 0
    clim = clim_base if is_base else climate_for(ctx, scenario, kb)
    slope = ctx.get("slope_pct") or 0.3
    hazard = hazard_weights(clim, ctx.get("soil", {}), slope)
    factor = ctx.get("water_factor", 1.0)

    # the water yardstick: what the reference rotation needs on this field
    ref_years = reference_years(kb)
    full = float(np.mean([water_year(y, kb, clim_base, factor)["applied"] for y in ref_years]))
    reference_mm = float(np.mean([water_year(y, kb, clim, factor)["applied"] for y in ref_years]))
    supply_mm = full * float(np.clip(constraints.get("water_supply_pct", 100), 20, 150)) / 100.0

    strategies, ex_info = strategies_for(ctx, kb, existing_id)
    results = [evaluate_strategy(s, ctx, kb, clim, clim_base, constraints, supply_mm, hazard, reference_mm)
               for s in strategies]
    existing = results[0]
    existing["assumptions"] = ex_info["assumptions"]
    cond = field_conditions(ctx, kb, clim, hazard, existing)
    generic = kb.get("existing_strategy")

    for res, strat in zip(results, strategies):
        details = {c: criterion_detail(c, res, ctx, kb, clim, hazard, existing, constraints, supply_mm)
                   for c in kb["criteria"]}
        total = sum(w[c] * res["scores"][c] for c in w)
        for c in details:
            details[c].update(weight=round(w[c], 4), contribution=round(w[c] * res["scores"][c], 4),
                              label=kb["criteria"][c]["label"])
        risks, gaps = dynamic_flags(res, ctx, cond, constraints, supply_mm, kb)
        from_history = ex_info["mode"] == "from_history"
        static = generic if (res["is_existing"] and from_history) else strat
        if res["is_existing"]:
            why = [{"text": ("This is the rotation the field has followed, shown as the baseline to compare against."
                             if from_history else
                             "This is the rotation taken as what you do now: the baseline the others are compared with."),
                    "panel": "history"}]
        else:
            why = why_suggested(res, cond, existing, constraints, kb)
        res.update(
            total=round(total, 4), criteria=details, why=why,
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
        "reference_irrigation_mm": round(full), "reference_label": kb["settings"]["water_reference"]["label"],
        "existing": ex_info,
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
                   | {"hot_days": round(sum(clim["hot_days_month"].values()), 1), "hot_day_c": clim["hot_day_c"]},
        "climate_baseline": {"et0_annual": clim_base["et0_annual"], "precip_annual": clim_base["precip_annual"],
                             "frost_free_median": clim_base["frost_free_median"],
                             "hot_days": round(sum(clim_base["hot_days_month"].values()), 1)},
    }
