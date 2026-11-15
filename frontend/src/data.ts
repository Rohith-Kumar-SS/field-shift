// Loads the static data files (frontend/public/data, written by pipeline/s40_export.py).
// There is no server: everything the app shows comes from these files and is scored in the browser.

import { decodeWeather, type Weather, type WeatherMeta } from "./engine/climate";
import type { Dict, Kb } from "./engine/knowledge";
import type { FieldContext } from "./engine/scoring";

export type { Dict } from "./engine/knowledge";
export type { Constraints } from "./engine/scoring";
export type { Scenario } from "./engine/climate";

const BASE = `${import.meta.env.BASE_URL}data/`;

export interface RegionInfo {
  id: string;
  name: string;
  short: string;
  country: string;
  tagline: string;
  bbox: [number, number, number, number];
  centroid: [number, number];
  field_unit: string;
  imperial: boolean;
  landmark: string;
  n_fields: number;
  stats: Dict;
}

export interface OverlayLayer {
  id: string;
  group: string;
  year?: number;
  file: string;
  label: string;
}

export interface SourceStatus {
  source: string;
  title: string;
  tier: string;
  status: "ok" | "partial" | "failed" | "skipped";
  resolution: string;
  date_range: string;
  credit: string;
  message: string;
  action_needed: string;
  is_demo_data: boolean;
  notes: string;
}

export interface RegionData {
  id: string;
  region: Dict; // the pilot config: name, bbox, imperial, has_frost, hot_day_c, ...
  stats: Dict;
  sources: SourceStatus[];
  any_demo_data: boolean;
  groundwater: Dict | null;
  overlays: { corners: [number, number][]; layers: OverlayLayer[]; legends: Dict<Dict>; groups: string[] };
  extras: Dict<string>;
  atlas: { file: string; bytes: number; step_m: number } | null;
  weather: WeatherMeta;
  scenario: { rain_pct: { min: number; max: number; step: number }; temp_c: { min: number; max: number; step: number } };
  kb: Kb;
  fields: GeoJSON.FeatureCollection;
  context: GeoJSON.FeatureCollection | null;
  wells: GeoJSON.FeatureCollection | null;
  base: string; // URL prefix of this region's files
}

export interface FieldData {
  context: FieldContext;
  evidence: Dict;
  weather: Weather;
}

export interface Glossary {
  terms: { id: string; term: string; plain: string; text: string }[];
  disclaimer: string;
  limits: string[];
}

async function getJson<T>(url: string): Promise<T> {
  const res = await fetch(url);
  if (!res.ok) throw new Error(`${res.status} while loading ${url.replace(BASE, "")}`);
  return res.json() as Promise<T>;
}

const cache = new Map<string, Promise<any>>();
const once = <T,>(key: string, load: () => Promise<T>): Promise<T> => {
  if (!cache.has(key)) cache.set(key, load().catch((e) => { cache.delete(key); throw e; }));
  return cache.get(key)!;
};

export const loadRegions = () => once("regions", () => getJson<RegionInfo[]>(`${BASE}regions.json`));
export const loadGlossary = () => once("glossary", () => getJson<Glossary>(`${BASE}glossary.json`));

export const loadRegion = (id: string) =>
  once(`region:${id}`, async (): Promise<RegionData> => {
    const base = `${BASE}${id}/`;
    const [info, kb, fields] = await Promise.all([getJson<Dict>(`${base}region.json`), getJson<Kb>(`${base}kb.json`), getJson<GeoJSON.FeatureCollection>(`${base}fields.geojson`)]);
    const extra = (k: string) => (info.extras?.[k] ? getJson<GeoJSON.FeatureCollection>(`${base}${info.extras[k]}`).catch(() => null) : Promise.resolve(null));
    const [context, wells] = await Promise.all([extra("context"), extra("wells")]);
    return { ...(info as any), id, kb, fields, context, wells, base };
  });

export const loadField = (region: RegionData, fieldId: string) =>
  once(`field:${region.id}:${fieldId}`, async (): Promise<FieldData> => {
    const [doc, buf] = await Promise.all([
      getJson<{ context: FieldContext; evidence: Dict }>(`${region.base}fields/${fieldId}.json`),
      fetch(`${region.base}weather/${fieldId}.bin`).then((r) => {
        if (!r.ok) throw new Error(`${r.status} while loading the weather record`);
        return r.arrayBuffer();
      }),
    ]);
    return { context: doc.context, evidence: doc.evidence, weather: decodeWeather(buf, region.weather) };
  });

export const loadSoilUnits = (region: RegionData) =>
  once(`soil:${region.id}`, () => (region.extras.soil_units ? getJson<GeoJSON.FeatureCollection>(`${region.base}${region.extras.soil_units}`) : Promise.resolve(null)));

// ---------------------------------------------------------------------------
// Shared formatting and colours
// ---------------------------------------------------------------------------
export const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];

// Categorical series colours, fixed order. Validated with the dataviz palette checker
// (lightness band, chroma, colour-vision-deficiency separation, contrast >= 3:1).
export const SERIES = ["#0072B2", "#D55E00", "#009E73", "#B07C00", "#B0508E"];

// Plant groups in the rotation ring. Always shown with a text label as well.
export const GROUP_COLOR: Dict<string> = {
  legume: "#009E73",
  "cool-season grass": "#0072B2",
  "cool-season cereal": "#0072B2",
  "warm-season grass": "#B07C00",
  "warm-season cereal": "#B07C00",
  broadleaf: "#B0508E",
  "flooded rice": "#56B4E9",
  "cover mix": "#56B4E9",
  none: "#B9C2BE",
  unknown: "#7C8A86",
};
const GROUP_ORDER = ["legume", "flooded rice", "cool-season grass", "cool-season cereal", "warm-season grass", "warm-season cereal", "broadleaf", "cover mix", "none", "unknown"];
const GROUP_NAME: Dict<string> = { none: "Idle or fallow", unknown: "Crop uncertain", "cover mix": "Cover crop mix" };

/** Legend entries for the plant groups present, named with the region's own crops. */
export function groupLegend(kb: Kb, groups: string[]): { group: string; label: string; color: string }[] {
  return GROUP_ORDER.filter((g) => groups.includes(g)).map((g) => {
    const crops = Object.values(kb.crops).filter((c) => c.group === g && !String(c.short).includes("(")).map((c) => String(c.short).toLowerCase());
    const name = GROUP_NAME[g] ?? g[0].toUpperCase() + g.slice(1);
    const eg = g in GROUP_NAME || !crops.length ? "" : `: ${crops.slice(0, 2).join(", ")}`;
    return { group: g, label: name + eg, color: GROUP_COLOR[g] ?? GROUP_COLOR.unknown };
  });
}

// Crop seasons seen per year (regions without a crop map): one hue, light to dark.
export const SEASON_COLOR = ["#B9C2BE", "#A9D9BF", "#4DAE84", "#0E6B4A"];

export const mmToIn = (mm: number) => mm / 25.4;
export const haToAc = (ha: number) => ha * 2.47105;
export const fmt = (v: number | null | undefined, digits = 0) =>
  v === null || v === undefined || Number.isNaN(v) ? "–" : v.toLocaleString("en-US", { maximumFractionDigits: digits, minimumFractionDigits: digits });
export const doyToDate = (doy: number) => {
  const d = new Date(2023, 0, Math.round(doy));
  return `${d.getDate()} ${MONTHS[d.getMonth()]}`;
};
export const monthList = (ms: number[]) => ms.map((m) => MONTHS[m - 1]).join(", ");

/** "640 mm" or, where farmers think in inches, "640 mm (25.2 in)". */
export const mm = (v: number | null | undefined, imperial: boolean) => (v === null || v === undefined ? "–" : imperial ? `${fmt(v)} mm (${fmt(mmToIn(v), 1)} in)` : `${fmt(v)} mm`);

export const fieldNumber = (id: string) => String(id).replace(/^[A-Z]+-0?/, "");
