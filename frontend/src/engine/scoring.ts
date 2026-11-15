// Transparent rotation scoring: rule-based agronomy + weighted multi-criteria analysis.
//
//     Score(strategy) = sum_i  w_i * s_i(strategy)          (weights normalised to 1)
//
// Each criterion score s_i is between 0 and 1 and comes back with the formula, the inputs that
// produced it, their sources and a confidence level. Nothing here predicts yield, and nothing
// here says "plant X".
//
// This is a line-by-line port of engine/scoring.py, which stays the tested reference;
// tests/test_parity.py runs both on the same fields and compares numbers and wording.

import { Clim, Scenario, Weather, clampScenario, climateFor, effectivePrecipUsda, heatDaysIn, seasonFit } from "./climate";
import { Dict, Entry, Kb, KbStrategy, RotationYear, entryMonths, existingRotation, fillResidue, referenceYears, yearProfiles } from "./knowledge";
import { MONTHS, MONTH_NAMES, MonthMap, clamp, fx, isNum, mean, monthMap, pyFloat, pyRound, sum, unique } from "./num";

const CONF_VALUE: Dict<number> = { high: 1.0, medium: 0.6, low: 0.3 };
const GRASS_FAMILY = "Poaceae";

export interface Constraints {
  water_supply_pct: number;
  equipment: string[];
  market: string;
}

export interface FieldContext extends Dict {
  field_id: string;
  name: string;
  lat: number;
  lon: number;
  area_ha: number;
  elevation_m: number;
  slope_pct: number | null;
  soil: Dict;
  history: Dict[];
  sources: Dict<boolean>;
}

export function normaliseWeights(weights: Dict<number>, kb: Kb): Dict<number> {
  const crit = Object.keys(kb.criteria);
  let raw: Dict<number> = {};
  for (const c of crit) raw[c] = Math.max(Number(weights[c] ?? 0) || 0, 0);
  let total = sum(Object.values(raw));
  if (total <= 0) {
    raw = {};
    for (const c of crit) raw[c] = Number(kb.criteria[c].default_weight);
    total = sum(Object.values(raw));
  }
  const out: Dict<number> = {};
  for (const c of crit) out[c] = raw[c] / total;
  return out;
}

export const defaultConstraints = (kb: Kb): Constraints => ({
  water_supply_pct: 100, equipment: [...kb.settings.default_equipment], market: "some",
});

// ---------------------------------------------------------------------------
// Building blocks per rotation year
// ---------------------------------------------------------------------------
/** Share of a crop's own growing season that this entry covers (0-1). */
export function seasonFraction(e: Entry, kb: Kb): number {
  const crop = kb.crops[e.crop];
  const months = new Set(entryMonths(e, kb));
  const active = Object.keys(crop.kc).map(Number);
  if (!active.length) return months.size / 12.0;
  return active.filter((m) => months.has(m)).length / active.length;
}

/** An entry is a sowing if the crop needs sowing and does not start the year in the ground. */
function isPlanting(e: Entry, kb: Kb): boolean {
  return kb.crops[e.crop].traits.plantings > 0 && Math.min(...entryMonths(e, kb)) > 1;
}

interface WaterYear {
  etc: number; pe: number; nir: number; nir_month: MonthMap; ky: number; extra: number; applied: number;
  peak_share: number; early_share: number;
}

/**
 * Crop water demand, effective rain and net irrigation need for one rotation year (mm).
 * `nir` is what the crops need beyond usable rain; `extra` is what a paddy field takes on top
 * to be puddled and kept flooded; `applied` = nir + extra is what the water score uses.
 */
export function waterYear(year: RotationYear, kb: Kb, clim: Clim, factor: number): WaterYear {
  const [kc] = yearProfiles(year, kb);
  const etc = monthMap((m) => kc[m] * clim.et0_month[m] * factor);
  const active = MONTHS.filter((m) => kc[m] > 0);
  const pe = monthMap(() => 0);
  for (const m of active) pe[m] = effectivePrecipUsda(clim.precip_month[m], etc[m]);
  const nir = monthMap((m) => Math.max(etc[m] - pe[m], 0));
  let kyNum = 0, kyDen = 0;
  const irrigated = year.filter((e) => kb.crops[e.crop].irrigated ?? true);
  for (const m of active) {
    let best: Entry | null = null, bestKc = -Infinity;
    for (const e of irrigated) {
      if (!entryMonths(e, kb).includes(m)) continue;
      const v = kb.crops[e.crop].kc[m] ?? 0;
      if (v > bestKc) { best = e; bestKc = v; }
    }
    kyNum += kb.crops[best!.crop].traits.ky * etc[m];
    kyDen += etc[m];
  }
  let extra = 0;
  for (const e of year) extra += Number(kb.crops[e.crop].traits.extra_water_mm || 0) * seasonFraction(e, kb);
  const total = sum(MONTHS.map((m) => nir[m]));
  return {
    etc: sum(MONTHS.map((m) => etc[m])), pe: sum(MONTHS.map((m) => pe[m])), nir: total, nir_month: nir,
    ky: kyDen ? kyNum / kyDen : 0, extra, applied: total + extra,
    peak_share: total > 0 ? (nir[7] + nir[8]) / total : 0, early_share: total > 0 ? (nir[6] + nir[7]) / total : 0,
  };
}

/** 0 = as thirsty as the reference rotation on this field; 1 = half of that, or less. */
export function waterScore(irrigationMm: number, referenceMm: number): number {
  if (referenceMm <= 0) return 0;
  return clamp(2.0 * (1.0 - irrigationMm / referenceMm));
}

/** When is this field's soil most at risk? Monthly weights (sum 1) from wind and heavy rain. */
export function hazardWeights(clim: Clim, soil: Dict, slopePct: number): Dict {
  const wei = isNum(soil.wind_erodibility_index) ? soil.wind_erodibility_index : 86.0;
  const kw = isNum(soil.kwfact_surface) ? soil.kwfact_surface : 0.3;
  let windW = clamp(wei / 134.0, 0.15, 1.6);
  let rainW = clamp(slopePct / 2.0, 0.05, 1.5) * clamp(kw / 0.3, 0.3, 1.6);
  const wd = clim.windy_days_month, hr = clim.heavy_rain_days_month;
  const wsum = sum(MONTHS.map((m) => wd[m])), hsum = sum(MONTHS.map((m) => hr[m]));
  if (wsum <= 0) windW = 0;
  if (hsum <= 0) rainW = 0;
  const raw = monthMap((m) => (wsum > 0 ? windW * (wd[m] / wsum) : 0) + (hsum > 0 ? rainW * (hr[m] / hsum) : 0));
  const total = sum(MONTHS.map((m) => raw[m]));
  const weights = monthMap((m) => (total > 0 ? raw[m] / total : 1.0 / 12.0));
  const windShare = windW + rainW > 0 ? windW / (windW + rainW) : 0.5;
  const level = wei >= 134 ? "high" : wei >= 86 ? "moderate" : "low";
  const top = [...MONTHS].sort((a, b) => weights[b] - weights[a]).slice(0, 3);
  return {
    weights, wind_share: pyRound(windShare, 2), wind_level: level, wind_erodibility_index: wei, k_factor: kw,
    peak_months: top.sort((a, b) => a - b), windy_days_year: pyRound(wsum, 1), heavy_rain_days_year: pyRound(hsum, 1),
    heavy_rain_mm: clim.heavy_rain_mm ?? 10,
  };
}

/** Lengths of cyclic runs of `target` in a list of flags. */
function runs(flags: boolean[], target: boolean): number[] {
  if (flags.every((f) => f === target)) return [flags.length];
  if (!flags.some((f) => f === target)) return [];
  const start = flags.findIndex((f) => f !== target);
  const seq = [...flags.slice(start), ...flags.slice(0, start)];
  const out: number[] = [];
  let cur = 0;
  for (const f of seq) {
    if (f === target) cur += 1;
    else if (cur) { out.push(cur); cur = 0; }
  }
  if (cur) out.push(cur);
  return out;
}

function groupsOf(years: RotationYear[], kb: Kb): string[] {
  const groups = new Set<string>();
  for (const y of years) for (const e of y) {
    const g = kb.crops[e.crop].group as string;
    if (g === "cover mix") { groups.add("cool-season grass"); groups.add("legume"); }
    else if (g !== "none" && g !== "unknown") groups.add(g);
  }
  return Array.from(groups).sort();
}

/** How well the rotation breaks pest, disease and weed cycles (stand model or annual model). */
export function pestMetrics(years: RotationYear[], kb: Kb): Dict {
  const st = kb.settings;
  const groups = groupsOf(years, kb);
  const diversity = clamp((groups.length - 1) / 3.0);
  const n = years.length;
  if (st.pest_model === "stand") {
    const stand = new Set<string>(st.stand_crops);
    const isStand = years.map((y) => y.some((e) => stand.has(e.crop)));
    const standRuns = runs(isStand, true), gapRuns = runs(isStand, false);
    let gap: number, longest: number, breakScore: number, ageScore: number;
    if (!isStand.some(Boolean)) { gap = n; longest = 0; breakScore = 1.0; ageScore = 1.0; }
    else {
      gap = gapRuns.length ? Math.min(...gapRuns) : 0;
      longest = Math.max(...standRuns);
      breakScore = gap === 0 ? 0.0 : gap === 1 ? 0.6 : 1.0;
      ageScore = clamp(1.0 - (longest - 5) / 5.0);
    }
    return {
      model: "stand", gap_years: gap, longest_stand: longest, groups, break_score: breakScore,
      diversity_score: pyRound(diversity, 3), age_score: pyRound(ageScore, 3),
      score: pyRound(0.45 * breakScore + 0.35 * diversity + 0.2 * ageScore, 4),
    };
  }
  // annual model
  const cropsByYear = years.map((y) => y.map((e) => e.crop).filter((c) => c !== "fallow"));
  const sets = cropsByYear.map((c) => unique(c));
  let total = 0, repeated = 0;
  sets.forEach((crops, i) => {
    const nxt = new Set(sets[(i + 1) % n]);
    total += crops.length;
    repeated += crops.filter((c) => nxt.has(c)).length;
  });
  const change = total ? 1.0 - repeated / total : 1.0;
  const seq: string[] = [];
  for (const crops of cropsByYear) for (const c of crops) if (!seq.length || seq[seq.length - 1] !== c) seq.push(c);
  if (seq.length > 1 && seq[0] === seq[seq.length - 1]) seq.pop();
  const pairs: [string, string][] = seq.length > 1 ? seq.map((c, i) => [c, seq[(i + 1) % seq.length]]) : [];
  const grassAfterGrass = pairs.filter(([a, b]) => kb.crops[a].family === GRASS_FAMILY && kb.crops[b].family === GRASS_FAMILY).length;
  const handover = pairs.length ? 1.0 - grassAfterGrass / pairs.length : 0.0;
  return {
    model: "annual", groups, diversity_score: pyRound(diversity, 3), change_score: pyRound(change, 3),
    handover_score: pyRound(handover, 3), grass_after_grass: grassAfterGrass, handovers: pairs.length,
    crops_per_year: sets.length ? pyRound(mean(sets.map((s) => s.length)), 2) : 0.0,
    score: pyRound(0.35 * diversity + 0.3 * change + 0.35 * handover, 4),
  };
}

function nitrogenYear(i: number, years: RotationYear[], kb: Kb): number {
  const year = years[i];
  const stand = new Set<string>(kb.settings.stand_crops);
  const nOf = (e: Entry) => kb.crops[e.crop].traits.n_score * seasonFraction(e, kb);
  if (kb.settings.pest_model !== "stand") return clamp(sum(year.map(nOf)));
  const inStand = unique(year.map((e) => e.crop)).filter((c) => stand.has(c));
  if (inStand.length) return Math.max(...inStand.map((c) => kb.crops[c].traits.n_score as number));
  const n = years.length;
  const had = (y: RotationYear) => y.some((e) => stand.has(e.crop));
  const carry = had(years[(i - 1 + n) % n]) ? 0.6 : had(years[(((i - 2) % n) + n) % n]) ? 0.3 : 0.0;
  const cover = year.length ? Math.max(...year.map(nOf)) : 0.0;
  return clamp(carry + cover);
}

// ---------------------------------------------------------------------------
// One strategy
// ---------------------------------------------------------------------------
function describeSequence(strategy: KbStrategy, kb: Kb): Dict[] {
  const labels = strategy.year_labels;
  return strategy.years.map((year, i) => {
    const entries = year.map((e) => {
      const crop = kb.crops[e.crop];
      return { crop: e.crop, label: crop.short as string, group: crop.group as string, months: entryMonths(e, kb) };
    });
    return { year: i + 1, calendar_year: labels ? labels[i] : null, entries, label: unique(entries.map((x) => x.label)).join(" + ") };
  });
}

function evaluateStrategy(strategy: KbStrategy, ctx: FieldContext, kb: Kb, clim: Clim, climBase: Clim, constraints: Constraints,
                          supplyMm: number, hazard: Dict, referenceMm: number): Dict {
  const years = strategy.years;
  const n = years.length;
  const factor = ctx.water_factor ?? 1.0;
  const equipment = new Set(constraints.equipment ?? []);
  const market = constraints.market ?? "some";
  const ffd = clim.frost_free_days;
  const heatFull = Number(kb.settings.heat_days_full);

  const wy = years.map((y) => waterYear(y, kb, clim, factor));
  const covers = fillResidue(years.map((y) => yearProfiles(y, kb)[1]));
  const nirMean = mean(wy.map((w) => w.nir));
  const etcMean = mean(wy.map((w) => w.etc));
  const peMean = mean(wy.map((w) => w.pe));
  const extraMean = mean(wy.map((w) => w.extra));
  const appliedMean = nirMean + extraMean;
  const ref = climBase.et0_annual;

  const coverYear = years.map((_, i) => sum(MONTHS.map((m) => hazard.weights[m] * covers[i][m])));
  const nYear = years.map((_, i) => nitrogenYear(i, years, kb));
  const omYear: number[] = [], incomeYear: number[] = [], resYear: number[] = [], feasYear: number[] = [];
  let shortYears = 0;
  const cropNotes = new Map<string, Dict>();
  years.forEach((year, i) => {
    const plantings = year.filter((e) => isPlanting(e, kb)).length;
    let om = 0, value = 0, resNum = 0, resDen = 0;
    const feasParts: number[] = [];
    const seen = new Set<string>();
    for (const e of year) {
      const crop = kb.crops[e.crop];
      const t = crop.traits;
      const frac = seasonFraction(e, kb);
      om += t.om_score * frac;
      const mclass = String(t.market).split(" ")[0];
      const mf = kb.market_factor[mclass]?.[market] ?? 1.0;
      value += t.value_score * frac * mf;
      if (e.crop !== "fallow" && frac > 0) {
        const months = entryMonths(e, kb).filter((m) => m in crop.kc);
        const hd = heatDaysIn(months, t.heat_limit_c, clim);
        const heatOk = 1.0 - clamp(hd / heatFull);
        resNum += frac * (0.5 * t.drought_tolerance + 0.5 * heatOk);
        resDen += frac;
      }
      if (!seen.has(e.crop)) {
        seen.add(e.crop);
        const fit = seasonFit(ffd, Math.trunc(t.frost_free_days_needed));
        const need: string[] = [...t.equipment];
        const eq = need.length ? need.filter((x) => equipment.has(x)).length / need.length : 1.0;
        const base = e.crop === "fallow" ? 0.8 : 0.45 * fit + 0.3 * eq + 0.25 * (1.0 - t.establishment_risk);
        feasParts.push(base);
        cropNotes.set(e.crop, {
          crop: e.crop, label: crop.short, season_fit: fit, frost_free_days_needed: Math.trunc(t.frost_free_days_needed),
          equipment_needed: need, equipment_missing: need.filter((x) => !equipment.has(x)), market: mclass,
          salt_threshold_ds_m: t.salt_threshold_ds_m ?? null, heat_limit_c: t.heat_limit_c, n_score: t.n_score,
          n_credit_kg_ha: t.n_credit_kg_ha ?? null, establishment_risk: t.establishment_risk,
        });
      }
    }
    omYear.push(clamp(om - 0.08 * plantings));
    // water shortage -> yield (FAO-33): 1 - Ya/Ym = Ky * (1 - ETa/ETm)
    const w = wy[i];
    let relYield = 1.0;
    if (w.etc > 0 && w.applied > supplyMm + 0.5) {
      // a shortfall is shared in proportion between the crop's own need and the flooding water
      const eta = w.pe + (w.nir * supplyMm) / w.applied;
      relYield = clamp(1.0 - w.ky * (1.0 - eta / w.etc));
      shortYears += 1;
    }
    incomeYear.push(clamp(value) * relYield);
    resYear.push(resDen ? resNum / resDen : 0.5);
    feasYear.push(clamp(mean(feasParts) - 0.05 * Math.max(plantings - 1, 0)));
  });

  const pest = pestMetrics(years, kb);
  const scores: Dict<number> = {
    water: waterScore(appliedMean, referenceMm), cover: mean(coverYear), nitrogen: mean(nYear),
    organic_matter: mean(omYear), pest_break: pest.score, income: mean(incomeYear),
    resilience: mean(resYear), feasibility: mean(feasYear),
  };
  const r3 = (a: number[]) => a.map((v) => pyRound(v, 3));
  const rounded: Dict<number> = {};
  for (const [k, v] of Object.entries(scores)) rounded[k] = pyRound(v, 4);
  return {
    id: strategy.id, name: strategy.name, short: strategy.short,
    summary: String(strategy.summary).split(/\s+/).filter(Boolean).join(" "),
    is_existing: Boolean(strategy.is_existing), tags: strategy.tags ?? [],
    scores: rounded,
    water: {
      etc_mm: pyRound(etcMean), effective_rain_mm: pyRound(peMean), irrigation_mm: pyRound(appliedMean),
      crop_need_mm: pyRound(nirMean), reference_et_mm: pyRound(ref), reference_mm: pyRound(referenceMm),
      saving_vs_reference_pct: referenceMm ? pyRound(100.0 * (1.0 - appliedMean / referenceMm)) : 0,
      extra_pumping_mm: pyRound(extraMean), early_share: pyRound(mean(wy.map((w) => w.early_share)), 2),
      by_year: wy.map((w) => ({ etc_mm: pyRound(w.etc), irrigation_mm: pyRound(w.applied), effective_rain_mm: pyRound(w.pe), july_august_share: pyRound(w.peak_share, 2) })),
      peak_year_mm: pyRound(Math.max(...wy.map((w) => w.applied))), years_short_of_supply: shortYears, n_years: n,
    },
    pest,
    by_year: { cover: r3(coverYear), nitrogen: r3(nYear), organic_matter: r3(omYear), income: r3(incomeYear), resilience: r3(resYear), feasibility: r3(feasYear) },
    cover_calendar: covers, crop_notes: Array.from(cropNotes.values()), sequence: describeSequence(strategy, kb),
  };
}

// ---------------------------------------------------------------------------
// Explanations
// ---------------------------------------------------------------------------
function localText(ctx: FieldContext): string {
  const kind = ctx.climate_correction;
  if (kind === "gridmet") return "corrected month by month to gridMET (4 km)";
  if (kind === "imd") return "corrected month by month to India's weather-station grids (IMD)";
  if (kind === "imd_rain") return "shifted to field elevation; rain scaled to India's rain-gauge grid (IMD)";
  return "shifted to field elevation (lapse rate)";
}

function rainSource(ctx: FieldContext): string {
  const ground = ({ gridmet: "gridMET", imd: "IMD rain gauges", imd_rain: "IMD rain gauges" } as Dict<string>)[ctx.climate_correction];
  if (ctx.sources?.imerg) return "GPM IMERG" + (ground ? ` scaled to ${ground}` : "");
  return "NASA POWER" + (ground ? ` corrected to ${ground}` : "") + " (IMERG not loaded)";
}

const soilSource = (ctx: FieldContext, survey = "SSURGO (USDA NRCS)") => (ctx.soil_source === "soilgrids" ? "SoilGrids (ISRIC, 250 m model)" : survey);

function criterionDetail(cid: string, res: Dict, ctx: FieldContext, kb: Kb, clim: Clim, hazard: Dict, existing: Dict | null,
                         constraints: Constraints, supplyMm: number): Dict {
  const s: number = res.scores[cid];
  const src = ctx.sources ?? {};
  const local = localText(ctx);
  const refLabel: string = kb.settings.water_reference.label;
  const hotC = Math.trunc(kb.settings.hot_day_c);
  const cropsUsed = new Set<string>(res.sequence.flatMap((y: Dict) => y.entries.map((e: Dict) => e.crop)));
  if (cid === "water") {
    const w = res.water;
    const anchored = Boolean(ctx.water_factor_info?.available);
    const inputs: Dict[] = [
      { label: "Crop water demand (rotation average)", value: w.etc_mm, unit: "mm/yr", source: "FAO-56 crop coefficients x reference ET from NASA POWER" },
      { label: "Rain the crops can use", value: w.effective_rain_mm, unit: "mm/yr", source: `${rainSource(ctx)}, USDA-SCS effective-rain method` },
      { label: "Irrigation the crops need (rotation average)", value: w.crop_need_mm, unit: "mm/yr", source: "demand minus usable rain" },
      { label: `${refLabel[0].toUpperCase()}${refLabel.slice(1)} on this field would need`, value: w.reference_mm, unit: "mm/yr", source: "same method; the yardstick for this score" },
      { label: "Reference ET at this field", value: w.reference_et_mm, unit: "mm/yr", source: `NASA POWER (${local}), FAO-56 Penman-Monteith, 1996-2025` },
    ];
    if (anchored) {
      const f = ctx.water_factor_info;
      inputs.push({ label: "Adjustment to this field's own record", value: pyRound(ctx.water_factor, 2), unit: "x",
        source: `OpenET, alfalfa years ${f.years[0]}-${f.years[f.years.length - 1]}: measured-from-space ET divided by the textbook figure` });
    }
    if (w.extra_pumping_mm > 0) {
      inputs.splice(3, 0, { label: "Water to puddle the soil and keep paddy flooded", value: w.extra_pumping_mm, unit: "mm/yr", source: "knowledge base (typical figure; part of it seeps back to groundwater)" });
      inputs.splice(4, 0, { label: "Irrigation to deliver to the field", value: w.irrigation_mm, unit: "mm/yr", source: "crop need plus puddling and flooding water" });
    }
    let note = "Model-based: gridded weather and textbook crop coefficients.";
    let conf: string;
    if (anchored) { note += " Anchored to OpenET satellite ET for this field."; conf = "medium"; }
    else if (src.et) { note += " A satellite water-use record exists for this spot and is shown as evidence, but the estimate is not scaled to it."; conf = "medium"; }
    else { note += " No satellite water-use record for this field, so nothing anchors it."; conf = "low"; }
    if (cropsUsed.has("teff") || cropsUsed.has("safflower")) note += " Water use of teff and safflower here is poorly documented.";
    if (w.extra_pumping_mm > 0) note += " The flooding figure for paddy is a typical value, not a measurement of this field: sandy soils take more, heavy clay less, and part of it seeps back to the groundwater.";
    const formula = `score = 2 x (1 - irrigation need / ${refLabel} irrigation need), limited to 0-1: 0 = as thirsty as ${refLabel}, 1 = half the water or less`;
    let headline = `Needs about ${w.irrigation_mm} mm of irrigation a year`;
    if (existing && !res.is_existing && existing.water.irrigation_mm) {
      const diff = w.irrigation_mm - existing.water.irrigation_mm;
      const pct = (100.0 * diff) / existing.water.irrigation_mm;
      headline += ` (${fx(Math.abs(pct), 0)} % ${diff < 0 ? "less" : "more"} than the existing rotation)`;
    }
    return { score: s, formula, headline, inputs, confidence: conf, note, panel: "water" };
  }
  if (cid === "cover") {
    const cal: MonthMap[] = res.cover_calendar;
    const avg = monthMap((m) => mean(cal.map((c) => c[m])));
    const peak: number[] = hazard.peak_months;
    const inputs = [
      { label: "Months when this soil is most at risk", value: peak.map((m) => MONTH_NAMES[m]).join(", "), unit: "", source: "windy days and heavy-rain days from the weather record, weighted by soil and slope" },
      { label: "Average cover in those months", value: pyRound(mean(peak.map((m) => avg[m])) * 100), unit: "%", source: "crop calendar in the knowledge base" },
      { label: "Soil wind-erodibility index", value: pyRound(hazard.wind_erodibility_index), unit: "t/ac/yr", source: soilSource(ctx).replace("SoilGrids (ISRIC, 250 m model)", "derived from SoilGrids texture (NRCS groups)") },
      { label: "Field tilt", value: ctx.slope_pct ?? null, unit: "%", source: "SRTM plane fit" },
    ];
    const main = hazard.wind_share >= 0.6 ? "wind is the main erosion risk" : hazard.wind_share <= 0.4 ? "hard rain is the main erosion risk" : "wind and hard rain are both erosion risks";
    return { score: s, formula: "score = sum over months of (risk weight x share of soil covered)", headline: `Soil covered ${fx(s * 100, 0)} % of the time that matters`,
      inputs, confidence: "medium", panel: "cover", note: `Cover comes from a crop calendar, not from watching this rotation on your field. Here ${main}.` };
  }
  if (cid === "nitrogen") {
    const legumeCrops = unique<string>(res.crop_notes.filter((c: Dict) => c.n_score >= 0.5).map((c: Dict) => c.label)).sort();
    const yearsWith = res.sequence.filter((y: Dict) => y.entries.some((e: Dict) => kb.crops[e.crop].traits.n_score >= 0.5)).length;
    const formula = kb.settings.pest_model === "stand" ? "legume year = 1; first year after alfalfa = 0.6; second = 0.3; legume cover crop adds up to 0.5" : "sum of each crop's nitrogen class x share of its season, limited to 1";
    return { score: s, formula, headline: `Legumes in ${yearsWith} of ${res.sequence.length} years`,
      inputs: [{ label: "Legumes in the rotation", value: legumeCrops.join(", ") || "none", unit: "", source: "rotation definition" },
        { label: "Years with a legume", value: yearsWith, unit: `of ${res.sequence.length}`, source: "rotation definition" }],
      confidence: "medium", panel: "history",
      note: "A well-established principle, but the real credit depends on the crop stand, soil and management. A soil test is the only measurement." };
  }
  if (cid === "organic_matter") {
    const om = ctx.soil?.om_pct_0_30;
    let sowings = 0;
    for (const y of res.sequence) for (const e of y.entries) if (Math.min(...e.months) > 1 && kb.crops[e.crop].traits.plantings > 0) sowings += 1;
    return { score: s, formula: "sum of each crop's root-and-residue class, minus 0.08 per sowing (tillage)",
      headline: "Root and residue inputs: " + (s >= 0.7 ? "high" : s >= 0.5 ? "moderate" : "low"),
      inputs: [{ label: "Soil organic matter today (0-30 cm)", value: isNum(om) ? pyRound(om, 1) : null, unit: "%", source: soilSource(ctx) },
        { label: "Sowings per rotation", value: sowings, unit: "", source: "rotation definition" }],
      confidence: "low", panel: "soil", note: "Class scores only. Organic matter changes over many years and cannot be seen from space; satellites do not measure it." };
  }
  if (cid === "pest_break") {
    const p = res.pest;
    let formula: string, headline: string, inputs: Dict[];
    if (p.model === "stand") {
      formula = "0.45 x break between alfalfa stands + 0.35 x plant-group diversity + 0.20 x stand-age score";
      headline = p.longest_stand ? `${p.gap_years}-year break between alfalfa stands` : "No alfalfa in the rotation";
      inputs = [{ label: "Years out of alfalfa between stands", value: p.gap_years, unit: "years", source: "rotation definition; Extension guidance asks for at least 1" },
        { label: "Plant groups in the rotation", value: p.groups.join(", ") || "none", unit: "", source: "knowledge base" },
        { label: "Longest alfalfa stand", value: p.longest_stand, unit: "years", source: "rotation definition" }];
    } else {
      formula = "0.35 x plant-group diversity + 0.30 x share of crops that change from year to year + 0.35 x share of crop hand-overs that are not cereal after cereal";
      headline = `${p.groups.length} plant group(s); ${p.grass_after_grass} of ${p.handovers} hand-overs are cereal after cereal`;
      inputs = [{ label: "Plant groups in the rotation", value: p.groups.join(", ") || "none", unit: "", source: "knowledge base" },
        { label: "Crops that change from one year to the next", value: pyRound(p.change_score * 100), unit: "%", source: "rotation definition" },
        { label: "Cereal-after-cereal hand-overs", value: p.grass_after_grass, unit: `of ${p.handovers}`, source: "rotation definition" }];
    }
    const doubtful = res.is_existing && (ctx.n_doubtful_years ?? 0) > 2;
    return { score: s, formula, headline, inputs, confidence: doubtful ? "low" : "medium", panel: "history",
      note: "Counts breaks and plant families; it knows nothing about which pests, diseases or weeds are actually in your field." };
  }
  if (cid === "income") {
    const w = res.water;
    const inputs = [{ label: `Value relative to ${refLabel}`, value: pyRound(s * 100), unit: "%", source: "class scores in the knowledge base (no prices)" },
      { label: "Your market setting", value: constraints.market ?? "some", unit: "", source: "your input" },
      { label: "Years needing more water than your supply", value: w.years_short_of_supply, unit: `of ${w.n_years}`, source: `your supply setting (${pyRound(supplyMm)} mm/yr)` }];
    return { score: s, formula: "sum of crop value classes x market factor, reduced by water shortage (FAO-33 yield response)",
      headline: `About ${fx(s * 100, 0)} % of the value of well-watered ${refLabel}`, inputs, confidence: "low", panel: "water",
      note: "No local prices, yields or costs are in this tool. Treat this as a rough ordering and replace it with your own budget." };
  }
  if (cid === "resilience") {
    const hot = pyRound(sum(MONTHS.map((m) => clim.hot_days_month[m])), 1);
    const full = Math.trunc(kb.settings.heat_days_full);
    return { score: s, formula: `per crop: 0.5 x drought-tolerance class + 0.5 x (1 - days above its heat limit in its season / ${full})`,
      headline: "Copes with heat and short water: " + (s >= 0.7 ? "well" : s >= 0.55 ? "moderately" : "poorly"),
      inputs: [{ label: `Days a year above ${hotC} °C`, value: hot, unit: "days", source: `NASA POWER, ${local}` },
        { label: "Crops' own heat limits", value: res.crop_notes.filter((c: Dict) => c.crop !== "fallow").map((c: Dict) => `${c.label} ${c.heat_limit_c} °C`).join(", "), unit: "", source: "knowledge base" }],
      confidence: "medium", panel: "climate", note: "Heat days come from a ~50 km NASA weather grid corrected to local conditions, not from a station in the field." };
  }
  // feasibility
  const frosty = clim.frost_free_median < 330;
  let worst: Dict | null = null;
  for (const c of res.crop_notes) if (c.frost_free_days_needed > 0 && (worst === null || c.season_fit < worst.season_fit)) worst = c;
  const inputs: Dict[] = [{ label: "Your equipment", value: (constraints.equipment ?? []).join(", ") || "none", unit: "", source: "your input" }];
  if (frosty) inputs.unshift({ label: "Frost-free season (median)", value: pyRound(clim.frost_free_median), unit: "days", source: `NASA POWER, ${local}, 1996-2025` });
  if (worst) inputs.push({ label: `Years long enough for ${String(worst.label).toLowerCase()}`, value: pyRound(worst.season_fit * 100), unit: "%", source: `needs about ${worst.frost_free_days_needed} frost-free days` });
  const risky = res.crop_notes.filter((c: Dict) => c.crop !== "fallow").sort((a: Dict, b: Dict) => b.establishment_risk - a.establishment_risk);
  if (risky.length) inputs.push({ label: "Hardest crop to establish", value: risky[0].label, unit: "", source: `establishment-risk class ${pyFloatish(risky[0].establishment_risk)} in the knowledge base` });
  const note = frosty
    ? "Frost dates depend heavily on local cold-air pooling. Even after correction to a 4 km grid, the coldest hollows frost earlier and later than shown: check your own records."
    : "Season length is not a limit here; the score reflects your equipment and how hard each crop is to establish.";
  return { score: s, formula: "per crop: 0.45 x season fit + 0.30 x equipment you have + 0.25 x (1 - establishment risk); -0.05 per extra sowing in a year",
    headline: "Fits your season and equipment: " + (s >= 0.75 ? "well" : s >= 0.55 ? "partly" : "poorly"), inputs, confidence: "medium", panel: "climate", note };
}

// knowledge-base numbers are written as decimals (0.3, 2.0): print them the way Python does
const pyFloatish = (v: number) => pyFloat(Number(v));

/** Facts about this field that the 'why suggested' rules look at. */
function fieldConditions(ctx: FieldContext, kb: Kb, clim: Clim, hazard: Dict, existing: Dict): Dict {
  const soil = ctx.soil ?? {};
  const stand = new Set<string>(kb.settings.stand_crops);
  let run = 0, best = 0;
  for (const r of ctx.history ?? []) {
    run = stand.has(r.crop) ? run + 1 : 0;
    best = Math.max(best, run);
  }
  const n = (v: unknown) => (isNum(v) ? v : null);
  return {
    stand_run: best, groups: existing.pest.groups, om: n(soil.om_pct_0_30), ec: n(soil.ec_dsm_0_30), ph: n(soil.ph_0_30),
    texture: soil.surface_texture ?? null, weg: soil.wind_erodibility_group ?? null, wind_level: hazard.wind_level,
    wind_share: hazard.wind_share, peak_months: hazard.peak_months, heavy_rain_days: hazard.heavy_rain_days_year,
    heavy_rain_mm: hazard.heavy_rain_mm, gw: ctx.groundwater ?? {}, hot_trend: ctx.trends?.hot_days ?? {},
    hot_trend_ground: ctx.trends?.hot_days_ground ?? {}, frost_free: clim.frost_free_median, hot_c: Math.trunc(kb.settings.hot_day_c),
  };
}

/** Rule-based reasons, each tied to a number from this field and to an evidence panel. */
function whySuggested(res: Dict, cond: Dict, existing: Dict, _constraints: Constraints, kb: Kb): Dict[] {
  const tags = new Set<string>(res.tags);
  const any = (...t: string[]) => t.some((x) => tags.has(x));
  const out: Dict[] = [];
  const w = res.water, ew = existing.water;
  const refLabel: string = kb.settings.water_reference.label;
  const saved = ew.irrigation_mm - w.irrigation_mm;
  if (tags.has("reduces_water") && saved > 15) {
    out.push({ text: `The existing rotation needs about ${ew.irrigation_mm} mm of irrigation a year here, while rain supplies only about ${ew.effective_rain_mm} mm of what the crops use. This rotation needs about ${saved} mm a year less.`, panel: "water" });
  }
  const gw = cond.gw;
  if (tags.has("reduces_water") && gw.kind === "wells" && gw.n_wells_trend) {
    if (gw.n_deepening && gw.n_deepening >= gw.n_wells_trend / 2) {
      out.push({ text: `${gw.n_deepening} of ${gw.n_wells_trend} nearby USGS wells with long records show the water table getting deeper since 1990 (median ${fx(Math.abs(gw.median_m_per_decade), 1)} m per decade).`, panel: "groundwater" });
    }
  }
  if (tags.has("reduces_water") && gw.kind === "grace" && gw.significant && (gw.trend_cm_per_year || 0) < 0) {
    out.push({ text: `NASA's GRACE satellites show the water stored in and on the ground across this region falling by about ${fx(Math.abs(gw.trend_cm_per_year), 1)} cm a year since ${gw.from_year ?? 2002}. That is an area about 300 km across, not your village.`, panel: "groundwater" });
  }
  if (tags.has("no_puddling") && ew.extra_pumping_mm - w.extra_pumping_mm >= 100) {
    out.push({ text: `Roughly ${ew.extra_pumping_mm - w.extra_pumping_mm} mm of that saving is water paddy takes only to be puddled and kept flooded. Part of it seeps back to the groundwater, so the gain is mostly in pumping cost and in soil structure that is no longer puddled.`, panel: "water" });
  }
  if (tags.has("resilient_to_late_water") && ew.early_share - w.early_share >= 0.08) {
    out.push({ text: `Only about ${fx(w.early_share * 100, 0)} % of its irrigation need falls in June-July, against ${fx(ew.early_share * 100, 0)} % for the existing rotation, so a late start to canal water matters less.`, panel: "water" });
  }
  if (tags.has("adds_break") && cond.stand_run >= 5) {
    out.push({ text: `The crop map shows alfalfa for ${cond.stand_run} years running. Stands usually thin with age, and Extension guidance asks for at least a year in another crop before re-sowing; this rotation gives ${res.pest.gap_years ?? 0}.`, panel: "history" });
  }
  if (any("new_grass_families", "new_broadleaf_family", "new_family") && res.pest.groups.length > cond.groups.length) {
    out.push({ text: `The existing rotation uses ${cond.groups.length} plant group(s) (` + (cond.groups.join(", ") || "none") + `); this one uses ${res.pest.groups.length}: ` + res.pest.groups.join(", ") + ".", panel: "history" });
  }
  if (tags.has("adds_legume") && res.scores.nitrogen > existing.scores.nitrogen + 0.1) {
    const leg: Dict[] = res.crop_notes.filter((c: Dict) => c.n_score >= 0.5);
    const credits = leg.filter((c) => c.n_credit_kg_ha).map((c) => c.n_credit_kg_ha[1] as number);
    const credit = credits.length ? Math.max(...credits) : 0;
    let txt = "It adds " + leg.map((c) => String(c.label).toLowerCase()).join(" and ") + (leg.length === 1 ? ", which fixes its own nitrogen" : ", which fix their own nitrogen");
    txt += credit ? ` and can leave up to about ${credit} kg N/ha for the next crop.` : ".";
    if (existing.scores.nitrogen < 0.05) txt = "The existing rotation has no legume. " + txt;
    out.push({ text: txt, panel: "soil" });
  }
  const months = cond.peak_months.map((m: number) => MONTH_NAMES[m]).join(", ");
  const windy = cond.wind_share >= 0.6 && ["moderate", "high"].includes(cond.wind_level);
  const soilTxt = `The soil here (${String(cond.texture || "soil").toLowerCase()}, wind-erodibility group ${pyNone(cond.weg)}) is ${cond.wind_level}ly prone to blowing, and ${months} are the riskiest months.`;
  if (tags.has("adds_cover") && res.scores.cover > existing.scores.cover + 0.01) {
    const txt = windy
      ? soilTxt + " This rotation keeps more of the soil covered then."
      : `Hard rain and wind are toughest on this soil in ${months} (${fx(cond.heavy_rain_days, 0)} days a year with ${fx(cond.heavy_rain_mm, 0)} mm or more). This rotation keeps more of the soil covered then.`;
    out.push({ text: txt, panel: "cover" });
  } else if (tags.has("adds_cover") && windy) {
    out.push({ text: soilTxt + " Check the cover calendar: the seeding years leave it exposed in spring.", panel: "cover" });
  }
  if (tags.has("builds_om") && cond.om !== null && cond.om < 1.5 && res.scores.organic_matter >= existing.scores.organic_matter - 0.1) {
    const more = res.scores.organic_matter > existing.scores.organic_matter;
    out.push({ text: `The soil map puts organic matter at about ${fx(cond.om, 1)} % in the top 30 cm, which is low. This rotation returns more roots and residue to the soil` + (more ? " than the existing one." : "."), panel: "soil" });
  }
  if (any("salt_tolerant_break", "salt_tolerant") && cond.ec !== null && cond.ec >= 2.0) {
    out.push({ text: `The soil survey shows salinity around ${fx(cond.ec, 1)} dS/m, above the level where sensitive crops start losing yield; this rotation includes crops that tolerate two to four times that.`, panel: "soil" });
  }
  if (tags.has("deep_roots")) {
    out.push({ text: "A taproot crop can reach moisture below the root zone of the cereals and grasses, and comes from a plant family the field has not seen.", panel: "soil" });
  }
  if (tags.has("familiar_equipment") && !res.crop_notes.some((c: Dict) => c.equipment_missing.length)) {
    out.push({ text: "It needs only the equipment you said you have.", panel: "climate" });
  }
  if (any("keeps_forage", "keeps_income") && res.scores.income >= existing.scores.income - 0.12) {
    out.push({ text: `It keeps most of the income of the existing rotation (${fx(res.scores.income * 100, 0)} % vs ${fx(existing.scores.income * 100, 0)} % of well-watered ${refLabel}).`, panel: "water" });
  }
  const ht = cond.hot_trend;
  if (ht.significant && (ht.slope_per_decade || 0) > 0 && res.scores.resilience > existing.scores.resilience + 0.02) {
    const a: number = ht.slope_per_decade;
    const g = cond.hot_trend_ground;
    let rate: string;
    if (isNum(g.per_decade) && (g.p_value || 1) < 0.05 && g.per_decade > 0) {
      const [lo, hi] = [a, g.per_decade].sort((x, y) => x - y);
      rate = `about +${fx(lo, 0)} to +${fx(hi, 0)} days per decade since 1991, depending on the dataset`;
    } else rate = `about +${fx(a, 0)} days per decade since 1991 in NASA POWER`;
    out.push({ text: `Days above ${cond.hot_c} °C have been increasing (${rate}); this rotation leans on crops that cope better with heat.`, panel: "climate" });
  }
  if (!out.length) out.push({ text: "It is included so that you can see how a different mix of crops trades off against the existing rotation on this field.", panel: "history" });
  return out;
}

const pyNone = (v: unknown) => (v === null || v === undefined ? "None" : String(v));

/** Field-specific risks and information gaps on top of the knowledge-base lists. */
function dynamicFlags(res: Dict, ctx: FieldContext, cond: Dict, constraints: Constraints, supplyMm: number, kb: Kb): [string[], string[]] {
  const risks: string[] = [], gaps: string[] = [];
  const src = ctx.sources ?? {};
  const crops = new Set<string>(res.crop_notes.map((c: Dict) => c.crop));
  for (const c of res.crop_notes as Dict[]) {
    if (c.frost_free_days_needed > 0 && c.season_fit < 0.8) {
      risks.push(`${c.label} needs about ${c.frost_free_days_needed} frost-free days; this field had that many in only ${fx(c.season_fit * 100, 0)} % of the last 30 years (median ${fx(cond.frost_free, 0)} days).`);
    }
    if (c.equipment_missing.length) risks.push(`${c.label} needs equipment you did not tick: ${c.equipment_missing.join(", ")}.`);
    const thr = c.salt_threshold_ds_m;
    const twin = String(c.crop).endsWith("_est") && crops.has(String(c.crop).slice(0, -4));
    if (thr && cond.ec !== null && cond.ec > thr && !twin) {
      risks.push(`Soil-survey salinity (${fx(cond.ec, 1)} dS/m) is above the level where ${String(c.label).toLowerCase()} starts losing yield (${pyFloat(thr)} dS/m).`);
    }
    if (["niche", "uncertain"].includes(c.market) && constraints.market === "established_only") {
      risks.push(`${c.label} has a ${c.market} market and you asked for established markets only.`);
    }
    if (c.market === "established" && constraints.market === "established_only" && kb.market_factor.established.established_only < 1) {
      risks.push(`${c.label} is sold at open-market prices without assured buying, and you asked for assured buyers only.`);
    }
  }
  const w = res.water;
  if (w.years_short_of_supply) {
    risks.push(`In ${w.years_short_of_supply} of ${w.n_years} years it needs more irrigation than the ${pyRound(supplyMm)} mm you said you can count on (peak year ${w.peak_year_mm} mm).`);
  }
  if (cond.ph !== null && cond.ph >= 8.5) risks.push(`Soil pH is about ${fx(cond.ph, 1)} (strongly alkaline), which can hinder seedling establishment and nutrient uptake.`);
  if (!src.imerg) gaps.push("Rainfall comes from NASA POWER's ~50 km grid; the GPM IMERG satellite record is not loaded.");
  if (!src.et) gaps.push("No satellite water-use record for this field, so water figures are textbook estimates only.");
  if (res.is_existing && kb.settings.existing === "from_history" && ctx.n_doubtful_years) {
    gaps.push(`${ctx.n_doubtful_years} year(s) of the crop history are doubtful: the crop map and the greenness record disagree.`);
  }
  if (ctx.soil_source === "soilgrids") gaps.push("Soil values come from a 250 m global model and soil moisture from 9 km satellite pixels: neither is a measurement in this field, and salinity is not mapped at all.");
  else gaps.push("Soil moisture comes from 9 km satellite pixels and soil properties from survey map units: neither is a measurement in this field.");
  return [risks, gaps];
}

function confidenceFor(_res: Dict, details: Dict<Dict>, weights: Dict<number>, ctx: FieldContext): Dict {
  let score = sum(Object.keys(weights).map((c) => weights[c] * CONF_VALUE[details[c].confidence]));
  const reasons: string[] = [];
  const src = ctx.sources ?? {};
  const names: Dict<string> = { et: "satellite water use", landsat: "Landsat greenness", soil: "soil map", history: "crop history", smap: "soil moisture" };
  const missing = Object.keys(names).filter((k) => !src[k]).map((k) => names[k]);
  if (missing.length) {
    score -= 0.05 * missing.length;
    reasons.push("Missing for this field: " + missing.join(", ") + ".");
  }
  if (!src.imerg) reasons.push("Rainfall from the NASA POWER grid (IMERG not loaded).");
  if (ctx.is_custom) {
    score -= 0.05;
    reasons.push("Field placed by hand: boundary and crop history are less certain.");
  }
  const top = Object.keys(weights).sort((a, b) => weights[b] - weights[a]).slice(0, 3);
  const low = top.filter((c) => details[c].confidence === "low");
  if (low.length) reasons.push("Your heaviest priorities include ones scored from general crop tables rather than data from this field (" + low.join(", ").replace(/_/g, " ") + ").");
  else reasons.push("Your heaviest priorities are scored mainly from satellite and weather data for this field.");
  const level = score >= 0.72 ? "high" : score >= 0.5 ? "medium" : "low";
  return { level, score: pyRound(clamp(score), 2), reasons };
}

// ---------------------------------------------------------------------------
/** The rotations to compare, existing first. */
export function strategiesFor(ctx: FieldContext, kb: Kb, existingId: string | null): [KbStrategy[], Dict] {
  const st = kb.settings;
  if (st.existing === "from_history") {
    const ex = existingRotation(ctx.history, kb);
    return [[ex, ...Object.values(kb.strategies).map((s) => ({ ...s }))], { mode: "from_history", chosen: null, assumptions: ex.assumptions ?? [] }];
  }
  const known = existingId !== null && existingId in kb.strategies;
  const seenRaw = ctx.phenology?.median_seasons;
  const seen: number | null = isNum(seenRaw) ? seenRaw : null;
  const perYear: Dict<number> = {};
  for (const [sid, s] of Object.entries(kb.strategies)) perYear[sid] = pestMetrics(s.years, kb).crops_per_year;
  const assumptions: string[] = [];
  let chosen: string;
  if (known) {
    chosen = existingId!;
    if (seen !== null && Math.abs(seen - perYear[chosen]) >= 1) {
      assumptions.push(`The satellite record shows about ${fx(seen, 0)} green season(s) a year on this spot, but the rotation selected has ${fx(perYear[chosen], 0)} crops a year. Check that it matches what is grown here.`);
    }
  } else {
    // no crop map: start from the usual rotation of the area, unless the number of green seasons the
    // satellites see each year fits another of the common rotations better
    chosen = st.existing_default;
    const options = Object.entries(kb.strategies).filter(([, s]) => s.existing_option).map(([sid]) => sid);
    if (seen !== null && options.length) {
      let best = options[0];
      const key = (sid: string): [number, number] => [Math.abs(perYear[sid] - seen), sid !== chosen ? 1 : 0];
      for (const sid of options) {
        const [a, b] = key(sid), [c, d] = key(best);
        if (a < c || (a === c && b < d)) best = sid;
      }
      if (Math.abs(perYear[best] - seen) < Math.abs(perYear[chosen] - seen)) chosen = best;
      assumptions.push(`No crop map exists here. The satellite record shows about ${fx(seen, 0)} green season(s) a year on this spot, so "${kb.strategies[chosen].short}" is taken as what you grow now. Choose your own rotation if it differs.`);
    } else {
      assumptions.push("No crop map exists here, so the most common rotation of the area is taken as what you grow now. Choose your own rotation if it differs.");
    }
  }
  const out: KbStrategy[] = [{ ...kb.strategies[chosen], is_existing: true }];
  for (const [sid, s] of Object.entries(kb.strategies)) if (sid !== chosen) out.push({ ...s });
  return [out, { mode: "choose", chosen, assumptions }];
}

export interface ScoreInput {
  ctx: FieldContext;
  kb: Kb;
  weather: Weather;
  weights?: Dict<number> | null;
  constraints?: Partial<Constraints> | null;
  scenario?: Scenario | null;
  existingId?: string | null;
  climBase?: Clim | null;
}

export const baselineClimate = (ctx: FieldContext, kb: Kb, weather: Weather) =>
  climateFor(weather, ctx.lat, ctx.elevation_m, { rain_pct: 0, temp_c: 0 }, kb.settings);

export function scoreField(input: ScoreInput): Dict {
  const { ctx, kb, weather } = input;
  const scenario = clampScenario(input.scenario ?? { rain_pct: 0, temp_c: 0 });
  const constraints: Constraints = { ...defaultConstraints(kb), ...(input.constraints ?? {}) };
  const w = normaliseWeights(input.weights ?? {}, kb);
  const climBase = input.climBase ?? baselineClimate(ctx, kb, weather);
  const isBase = scenario.rain_pct === 0 && scenario.temp_c === 0;
  const clim = isBase ? climBase : climateFor(weather, ctx.lat, ctx.elevation_m, scenario, kb.settings);
  const slope = ctx.slope_pct || 0.3;
  const hazard = hazardWeights(clim, ctx.soil ?? {}, slope);
  const factor = ctx.water_factor ?? 1.0;

  // the water yardstick: what the reference rotation needs on this field
  const refYears = referenceYears(kb);
  const full = mean(refYears.map((y) => waterYear(y, kb, climBase, factor).applied));
  const referenceMm = mean(refYears.map((y) => waterYear(y, kb, clim, factor).applied));
  const supplyMm = (full * Math.max(20, Math.min(150, Number(constraints.water_supply_pct ?? 100)))) / 100.0;

  const [strategies, exInfo] = strategiesFor(ctx, kb, input.existingId ?? null);
  const results = strategies.map((s) => evaluateStrategy(s, ctx, kb, clim, climBase, constraints, supplyMm, hazard, referenceMm));
  const existing = results[0];
  existing.assumptions = exInfo.assumptions;
  const cond = fieldConditions(ctx, kb, clim, hazard, existing);
  const generic = kb.existing_strategy;
  const crit = Object.keys(kb.criteria);

  results.forEach((res, i) => {
    const strat = strategies[i];
    const details: Dict<Dict> = {};
    for (const c of crit) details[c] = criterionDetail(c, res, ctx, kb, clim, hazard, existing, constraints, supplyMm);
    const total = sum(crit.map((c) => w[c] * res.scores[c]));
    for (const c of crit) Object.assign(details[c], { weight: pyRound(w[c], 4), contribution: pyRound(w[c] * res.scores[c], 4), label: kb.criteria[c].label });
    const [risks, gaps] = dynamicFlags(res, ctx, cond, constraints, supplyMm, kb);
    const fromHistory = exInfo.mode === "from_history";
    const stat: Dict = res.is_existing && fromHistory ? generic! : strat;
    const why = res.is_existing
      ? [{ text: fromHistory ? "This is the rotation the field has followed, shown as the baseline to compare against." : "This is the rotation taken as what you do now: the baseline the others are compared with.", panel: "history" }]
      : whySuggested(res, cond, existing, constraints, kb);
    Object.assign(res, {
      total: pyRound(total, 4), criteria: details, why, benefits: [...stat.benefits], risks: [...risks, ...stat.risks],
      info_gaps: [...gaps, ...stat.info_gaps], verify: [...stat.verify, ...kb.always_verify],
      confidence: confidenceFor(res, details, w, ctx),
    });
    delete res.tags;
  });

  const order = [...results].sort((a, b) => b.total - a.total);
  order.forEach((r, i) => (r.rank = i + 1));
  const best = order[0];
  // only priorities the farmer actually weighted can be named as reasons
  const active = crit.filter((c) => w[c] > 0.001);
  const lead: Dict<number> = {};
  for (const c of active) lead[c] = best.scores[c] - mean(results.map((r) => r.scores[c]));
  const ranked = [...active].sort((a, b) => w[b] * lead[b] - w[a] * lead[a]);
  const name = (c: string) => `"${kb.criteria[c].label}"`;
  let strong = ranked.slice(0, 2).filter((c) => lead[c] > 0).map(name);
  if (!strong.length) strong = [name(ranked[0])];
  const close = order.length > 1 && best.total - order[1].total < 0.02;
  let statement = `Under your priorities, "${best.short}" scores highest (${fx(best.total * 100, 0)} out of 100), mainly on ${strong.join(" and ")}.`;
  let weakest = active[0];
  for (const c of active) if (lead[c] < lead[weakest]) weakest = c;
  if (active.length >= 3 && lead[weakest] < 0) statement += ` It scores below the others on ${name(weakest)}.`;
  if (close) statement += ` "${order[1].short}" is within two points, so treat them as a tie.`;

  const weightsOut: Dict<number> = {};
  for (const c of crit) weightsOut[c] = pyRound(w[c], 4);
  const { weights: hw, ...hazardRest } = hazard;
  return {
    field_id: ctx.field_id, weights: weightsOut, constraints, water_supply_mm: pyRound(supplyMm),
    reference_irrigation_mm: pyRound(full), reference_label: kb.settings.water_reference.label, existing: exInfo,
    scenario: { rain_pct: scenario.rain_pct, temp_c: scenario.temp_c, is_baseline: isBase },
    statement,
    disclaimer: "This compares options; it does not tell you what to plant. It supports, and does not replace, your own judgment and local agricultural expertise.",
    strategies: results, ranking: order.map((r) => r.id),
    hazard: { ...hazardRest, weights: monthMap((m) => pyRound(hw[m], 4)) },
    climate: {
      et0_month: clim.et0_month, precip_month: clim.precip_month, tmax_month: clim.tmax_month, tmin_month: clim.tmin_month,
      windy_days_month: clim.windy_days_month, heavy_rain_days_month: clim.heavy_rain_days_month, et0_annual: clim.et0_annual,
      precip_annual: clim.precip_annual, frost_free_median: clim.frost_free_median, frost_free_p20: clim.frost_free_p20,
      last_spring_frost_median_doy: clim.last_spring_frost_median_doy, first_fall_frost_median_doy: clim.first_fall_frost_median_doy,
      hot_days: pyRound(sum(MONTHS.map((m) => clim.hot_days_month[m])), 1), hot_day_c: clim.hot_day_c,
    },
    climate_baseline: {
      et0_annual: climBase.et0_annual, precip_annual: climBase.precip_annual, frost_free_median: climBase.frost_free_median,
      hot_days: pyRound(sum(MONTHS.map((m) => climBase.hot_days_month[m])), 1),
    },
  };
}
