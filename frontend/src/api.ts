// Thin client for the Field Shift API. All data comes from local, precomputed files.

export type Dict<T = any> = Record<string, T>;

export interface Criterion {
  id: string;
  label: string;
  plain: string;
  default_weight: number;
  basis: string;
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

export interface Meta {
  pilot: { id: string; name: string; bbox: [number, number, number, number]; centroid: [number, number] };
  criteria: Criterion[];
  constraints: {
    defaults: Constraints;
    equipment: { id: string; label: string }[];
    market: { id: string; label: string }[];
  };
  scenario: { rain_pct: { min: number; max: number; step: number }; temp_c: { min: number; max: number; step: number } };
  glossary: { terms: { id: string; term: string; plain: string; text: string }[]; disclaimer: string; limits: string[] };
  sources: SourceStatus[];
  any_demo_data: boolean;
  groundwater: Dict | null;
  overlays: { corners: [number, number][]; layers: OverlayLayer[]; legends: Dict };
  crops: { id: string; label: string; short: string; group: string }[];
}

export interface OverlayLayer {
  id: string;
  group: string;
  year?: number;
  file: string;
  label: string;
}

export interface Constraints {
  water_supply_pct: number;
  equipment: string[];
  market: string;
}

export interface Scenario {
  rain_pct: number;
  temp_c: number;
}

export interface CriterionDetail {
  score: number;
  weight: number;
  contribution: number;
  label: string;
  formula: string;
  headline: string;
  confidence: "high" | "medium" | "low";
  note: string;
  panel: string;
  inputs: { label: string; value: any; unit: string; source: string }[];
}

export interface SequenceYear {
  year: number;
  calendar_year: number | null;
  label: string;
  entries: { crop: string; label: string; group: string; months: number[] }[];
}

export interface Strategy {
  id: string;
  name: string;
  short: string;
  summary: string;
  is_existing: boolean;
  total: number;
  rank: number;
  scores: Dict<number>;
  criteria: Dict<CriterionDetail>;
  water: Dict;
  pest: Dict;
  sequence: SequenceYear[];
  cover_calendar: Dict<number>[];
  why: { text: string; panel: string }[];
  benefits: string[];
  risks: string[];
  info_gaps: string[];
  verify: string[];
  confidence: { level: "high" | "medium" | "low"; score: number; reasons: string[] };
  assumptions?: string[];
}

export interface ScoreResult {
  field_id: string;
  weights: Dict<number>;
  constraints: Constraints;
  water_supply_mm: number;
  full_alfalfa_irrigation_mm: number;
  scenario: Scenario & { is_baseline: boolean };
  statement: string;
  disclaimer: string;
  strategies: Strategy[];
  ranking: string[];
  hazard: Dict;
  climate: Dict;
  climate_baseline: Dict;
}

export interface FieldsPayload {
  pilot: GeoJSON.FeatureCollection;
  context: GeoJSON.FeatureCollection;
  wells: GeoJSON.FeatureCollection;
  smap_cells: GeoJSON.FeatureCollection;
}

async function request<T>(url: string, init?: RequestInit): Promise<T> {
  const res = await fetch(url, init);
  if (!res.ok) {
    let detail = `${res.status} ${res.statusText}`;
    try {
      const body = await res.json();
      if (body?.detail) detail = typeof body.detail === "string" ? body.detail : JSON.stringify(body.detail);
    } catch {
      /* keep the status text */
    }
    throw new Error(detail);
  }
  return res.json() as Promise<T>;
}

const post = <T,>(url: string, body: unknown) =>
  request<T>(url, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });

export const api = {
  meta: () => request<Meta>("/api/meta"),
  fields: () => request<FieldsPayload>("/api/fields"),
  soilUnits: () => request<GeoJSON.FeatureCollection>("/api/soil-mapunits"),
  evidence: (id: string) => request<Dict>(`/api/fields/${encodeURIComponent(id)}/evidence`),
  knowledge: () => request<Dict>("/api/knowledge"),
  score: (field_id: string, weights: Dict<number>, constraints: Constraints, scenario: Scenario) =>
    post<ScoreResult>("/api/score", { field_id, weights, constraints, scenario }),
  customField: (geometry: GeoJSON.Polygon, name: string) =>
    post<{ feature: GeoJSON.Feature; evidence: Dict }>("/api/custom-field", { geometry, name }),
};

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
  "warm-season grass": "#B07C00",
  broadleaf: "#B0508E",
  "cover mix": "#56B4E9",
  none: "#B9C2BE",
  unknown: "#7C8A86",
};

export const GROUP_LABEL: Dict<string> = {
  legume: "Legume (alfalfa)",
  "cool-season grass": "Cool-season grass or cereal",
  "warm-season grass": "Warm-season grass",
  broadleaf: "Broadleaf (safflower)",
  "cover mix": "Cover crop mix",
  none: "Idle, not irrigated",
  unknown: "Crop uncertain",
};

export const mmToIn = (mm: number) => mm / 25.4;
export const fmt = (v: number | null | undefined, digits = 0) =>
  v === null || v === undefined || Number.isNaN(v) ? "–" : v.toLocaleString("en-US", { maximumFractionDigits: digits, minimumFractionDigits: digits });
export const haToAc = (ha: number) => ha * 2.47105;
export const doyToDate = (doy: number) => {
  const d = new Date(2023, 0, Math.round(doy));
  return `${d.getDate()} ${MONTHS[d.getMonth()]}`;
};
