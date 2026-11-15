// Knowledge-base helpers. A port of engine/knowledge.py and engine/history.py.
// The knowledge base itself is data (knowledge/<region>.yaml, shipped as kb.json).

import { MONTHS, MonthMap, fx, monthMap, pyRound } from "./num";

export type Dict<T = any> = Record<string, T>;

export interface Entry {
  crop: string;
  months?: number[];
}
export type RotationYear = Entry[];

export interface KbStrategy {
  id: string;
  name: string;
  short: string;
  summary: string;
  years: RotationYear[];
  tags: string[];
  benefits: string[];
  risks: string[];
  info_gaps: string[];
  verify: string[];
  existing_option?: boolean;
  is_existing?: boolean;
  year_labels?: number[];
  assumptions?: string[];
}

export interface Kb {
  region: string;
  region_note: string;
  crops: Dict<Dict>;
  strategies: Dict<KbStrategy>;
  criteria: Dict<{ label: string; plain: string; default_weight: number; basis: string }>;
  settings: Dict;
  market_factor: Dict<Dict<number>>;
  references: Dict;
  always_verify: string[];
  existing_strategy?: Dict;
  cdl_noncrop_codes?: number[];
  cdl_grass_codes?: number[];
}

export const entryMonths = (e: Entry, kb: Kb): number[] => (e.months && e.months.length ? e.months : (kb.crops[e.crop].months as number[]));

/** Monthly crop coefficient (irrigated crops only) and soil cover for one rotation year. */
export function yearProfiles(year: RotationYear, kb: Kb): [MonthMap, MonthMap] {
  const kc = monthMap(() => 0);
  const cover = monthMap(() => 0);
  for (const e of year) {
    const crop = kb.crops[e.crop];
    for (const m of entryMonths(e, kb)) {
      if (crop.irrigated ?? true) kc[m] = Math.max(kc[m], crop.kc[m] ?? 0);
      cover[m] = Math.max(cover[m], crop.cover[m] ?? 0);
    }
  }
  return [kc, cover];
}

/** Months nobody occupies keep half of the previous month's cover as residue (never < 0.1). */
export function fillResidue(covers: MonthMap[]): MonthMap[] {
  const flat: number[] = [];
  for (const c of covers) for (const m of MONTHS) flat.push(c[m]);
  const n = flat.length;
  const out = [...flat];
  for (let pass = 0; pass < 2; pass++) {
    for (let i = 0; i < n; i++) {
      if (flat[i] <= 0) out[i] = Math.max(0.1, 0.5 * out[(i - 1 + n) % n]);
    }
  }
  return covers.map((_, y) => monthMap((m) => pyRound(out[y * 12 + m - 1], 3)));
}

/** The rotation whose irrigation need is the yardstick for the water score. */
export function referenceYears(kb: Kb): RotationYear[] {
  const ref = kb.settings.water_reference;
  return ref.years ? ref.years : kb.strategies[ref.strategy].years;
}

// ---------------------------------------------------------------------------
// Crop history from the crop map (regions that have one)
// ---------------------------------------------------------------------------
const GREEN = 0.6;
const BROWN = 0.35;

export interface CdlRow {
  year: number;
  cdl_code: number;
  cdl_name: string;
  share: number | null;
}

/** One interpreted record per year, oldest first. Greenness is the second opinion on the crop map. */
export function interpretHistory(rows: CdlRow[], peakNdvi: Record<number, number>, kb: Kb): Dict[] {
  const mapping: Record<number, string> = {};
  for (const [cid, c] of Object.entries(kb.crops)) for (const code of c.cdl_codes ?? []) mapping[Number(code)] = cid;
  const noncrop = new Set(kb.cdl_noncrop_codes ?? []);
  const grass = new Set(kb.cdl_grass_codes ?? []);
  const sorted = [...rows].sort((a, b) => a.year - b.year);
  const out: Dict[] = [];
  for (const r of sorted) {
    const code = Number(r.cdl_code);
    const peak = peakNdvi[r.year];
    const has = peak !== undefined && peak !== null;
    const crop: string | undefined = mapping[code];
    const rec: Dict = { year: r.year, cdl_code: code, cdl_name: r.cdl_name, share: r.share, peak_ndvi: has ? pyRound(peak, 2) : null, doubtful: false, note: "" };
    const p2 = has ? fx(peak, 2) : "";
    if (noncrop.has(code) || crop === "fallow") {
      if (!has) Object.assign(rec, { crop: "fallow", doubtful: true, note: `Crop map says '${r.cdl_name}'; no greenness record to check it.` });
      else if (peak >= GREEN) Object.assign(rec, { crop: null, doubtful: true, note: `Crop map says '${r.cdl_name}', but the field was as green as an irrigated crop (peak NDVI ${p2}). The label is probably wrong.` });
      else if (peak < BROWN) Object.assign(rec, { crop: "fallow", note: `Crop map says '${r.cdl_name}' and the field stayed brown (peak NDVI ${p2}): treated as an idle year.` });
      else Object.assign(rec, { crop: "fallow", doubtful: true, note: `Crop map says '${r.cdl_name}'; greenness was in between (peak NDVI ${p2}). Treated as idle, but please check.` });
    } else if (grass.has(code)) {
      if (has && peak < BROWN) Object.assign(rec, { crop: "fallow", doubtful: true, note: `Crop map says '${r.cdl_name}' but the field stayed brown (peak NDVI ${p2}): treated as idle.` });
      else Object.assign(rec, { crop: "grass_hay", doubtful: true, note: `Crop map says '${r.cdl_name}'. Grass hay and alfalfa are often confused from space: please confirm.` });
    } else if (crop === undefined) {
      Object.assign(rec, { crop: "unknown_irrigated", doubtful: true, note: `'${r.cdl_name}' is not in the crop table; a generic crop is used.` });
    } else {
      rec.crop = crop;
      if (has && peak < BROWN) Object.assign(rec, { doubtful: true, note: `Crop map says '${r.cdl_name}' but the field stayed brown (peak NDVI ${p2}): possibly idle or newly sown.` });
      else if (r.share !== null && r.share !== undefined && r.share < 0.6) Object.assign(rec, { doubtful: true, note: `Only ${fx(r.share * 100, 0)} % of the field carried this label.` });
    }
    out.push(rec);
  }
  // resolve green-but-mislabelled years from their neighbours
  out.forEach((rec, i) => {
    if (rec.crop !== null) return;
    const real = (o: Dict) => o.crop !== null && o.crop !== "fallow";
    const prev = [...out.slice(0, i)].reverse().find(real)?.crop ?? null;
    const next = out.slice(i + 1).find(real)?.crop ?? null;
    rec.crop = prev && prev === next ? prev : prev || next || "unknown_irrigated";
    rec.note += ` Assumed '${kb.crops[rec.crop].short}' from the neighbouring years.`;
  });
  // an alfalfa year that follows a different crop is a seeding year
  out.forEach((rec, i) => {
    if (rec.crop === "alfalfa" && i > 0 && !["alfalfa", "alfalfa_est"].includes(out[i - 1].crop)) rec.crop = "alfalfa_est";
  });
  for (const rec of out) rec.label = kb.crops[rec.crop].short;
  return out;
}

/** The rotation the field has actually followed, as a cycle the engine can score. */
export function existingRotation(history: Dict[], kb: Kb, nYears = 8): KbStrategy {
  const recent = history.slice(-nYears);
  const years: RotationYear[] = recent.map((r) => [{ crop: r.crop }]);
  const assumptions: string[] = [];
  const crops: string[] = recent.map((r) => r.crop);
  const isAlf = (c: string) => c === "alfalfa" || c === "alfalfa_est";
  if (crops.every(isAlf) && !crops.includes("alfalfa_est")) {
    years[0] = [{ crop: "alfalfa_est" }];
    assumptions.push(`The crop map shows alfalfa in all ${recent.length} years. The stand is assumed to be re-sown about every ${recent.length} years straight back into alfalfa; tell us the real stand age if you know it.`);
  }
  const nAlf = crops.filter(isAlf).length;
  const nIdle = crops.filter((c) => c === "fallow").length;
  const others = Array.from(new Set(crops.filter((c) => !isAlf(c) && c !== "fallow").map((c) => kb.crops[c].short as string))).sort();
  const name = nAlf === crops.length ? "Continuous alfalfa (as observed)" : nAlf >= crops.length / 2 ? "Mostly alfalfa, as observed" : "Mixed use, as observed";
  const parts = [`alfalfa in ${nAlf} of ${crops.length} years`];
  if (others.length) parts.push("also " + others.join(", ").toLowerCase());
  if (nIdle) parts.push(`idle in ${nIdle}`);
  return {
    id: "existing", name, short: "Existing rotation",
    summary: `What the satellite record shows for ${recent[0].year}-${recent[recent.length - 1].year}: ` + parts.join("; ") + ".",
    years, year_labels: recent.map((r) => r.year), tags: ["existing"], assumptions,
    is_existing: true, benefits: [], risks: [], info_gaps: [], verify: [],
  };
}
