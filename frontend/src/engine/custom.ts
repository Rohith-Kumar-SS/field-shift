// A field the farmer draws: described in the browser from the region's "atlas", a ~140 m grid
// of real values (soil, terrain, monthly Landsat greenness, crop map) written by
// pipeline/s40_export.py. Weather, soil moisture and the long-term water record are coarse
// grids anyway, so they are taken from the nearest pilot field and said to be so.
// Nothing is estimated for sources that were prepared only for the pilot fields.

import type { FieldData, RegionData } from "../data";
import { interpretHistory, type CdlRow, type Dict } from "./knowledge";
import { MONTHS, mean, median, pyRound, quantile } from "./num";
import type { FieldContext } from "./scoring";

const MIN_HA = 2;
const MAX_HA = 400;
const LOW_COVER_NDVI = 0.25;

export interface Atlas {
  meta: Dict;
  buf: ArrayBuffer;
}

const atlasCache = new Map<string, Promise<Atlas>>();
export function loadAtlas(region: RegionData): Promise<Atlas> {
  if (!region.atlas) return Promise.reject(new Error("Drawing your own field is not available for this region yet."));
  if (!atlasCache.has(region.id)) {
    atlasCache.set(region.id, (async () => {
      const meta = await fetch(`${region.base}${region.atlas!.file}`).then((r) => r.json());
      const buf = await fetch(`${region.base}${meta.file}`).then((r) => r.arrayBuffer());
      return { meta, buf };
    })());
  }
  return atlasCache.get(region.id)!;
}

type Ring = [number, number][];

function inside(lon: number, lat: number, ring: Ring): boolean {
  let hit = false;
  for (let i = 0, j = ring.length - 1; i < ring.length; j = i++) {
    const [xi, yi] = ring[i], [xj, yj] = ring[j];
    if (yi > lat !== yj > lat && lon < ((xj - xi) * (lat - yi)) / (yj - yi) + xi) hit = !hit;
  }
  return hit;
}

function areaHa(ring: Ring): number {
  const lat0 = mean(ring.map((p) => p[1]));
  const kx = 111320 * Math.cos((lat0 * Math.PI) / 180), ky = 110540;
  let a = 0;
  for (let i = 0, j = ring.length - 1; i < ring.length; j = i++) a += ring[j][0] * kx * (ring[i][1] * ky) - ring[i][0] * kx * (ring[j][1] * ky);
  return Math.abs(a) / 2 / 1e4;
}

/** Crop seasons in one year of monthly greenness: peaks of at least 0.40 that stand 0.12 above the dips beside them. */
function seasonsIn(year: (number | null)[]): number[] {
  const v = year.map((x, i) => {
    if (x !== null) return x;
    const a = year[(i + 11) % 12], b = year[(i + 1) % 12]; // a one-month gap is bridged
    return a !== null && b !== null ? (a + b) / 2 : null;
  });
  const peaks: number[] = [];
  for (let m = 0; m < 12; m++) {
    const x = v[m];
    if (x === null || x < 0.4) continue;
    const prev = v[(m + 11) % 12], next = v[(m + 1) % 12];
    if (prev === null || next === null || !(x >= prev && x > next)) continue;
    const around = [-3, -2, -1, 1, 2, 3].map((d) => v[(m + d + 12) % 12]).filter((q): q is number => q !== null);
    const left = Math.min(...[-3, -2, -1].map((d) => v[(m + d + 12) % 12] ?? 1)), right = Math.min(...[1, 2, 3].map((d) => v[(m + d + 12) % 12] ?? 1));
    if (!around.length || x - Math.max(left, right) < 0.12) continue;
    if (peaks.length && m - peaks[peaks.length - 1] < 3) continue;
    peaks.push(m);
  }
  return peaks.map((m) => m + 1);
}

export async function buildCustomField(region: RegionData, atlas: Atlas, polygon: GeoJSON.Polygon, donors: { id: string; lon: number; lat: number; name: string }[],
                                 loadDonor: (id: string) => Promise<FieldData>): Promise<{ feature: GeoJSON.Feature; data: FieldData }> {
  const ring = (polygon.coordinates[0] ?? []).slice(0, -1) as Ring;
  if (ring.length < 3) throw new Error("Please draw a single closed shape with at least three corners.");
  const [w, s, e, n] = region.region.bbox as number[];
  if (ring.some(([x, y]) => x < w || x > e || y < s || y > n)) throw new Error("The field must lie inside the pilot area (the dashed box): data were prepared for that area only.");
  const area = areaHa(ring);
  if (area < MIN_HA || area > MAX_HA) throw new Error(`The shape covers ${area.toFixed(1)} ha; please draw between ${MIN_HA} and ${MAX_HA} ha.`);
  const lon = mean(ring.map((p) => p[0])), lat = mean(ring.map((p) => p[1]));

  // --- atlas cells under the shape ------------------------------------------
  const { meta, buf } = atlas;
  const { nx, ny, step, west, north } = meta as { nx: number; ny: number; step: number; west: number; north: number };
  const cells: number[] = [];
  const c0 = Math.max(0, Math.floor((Math.min(...ring.map((p) => p[0])) - west) / step)), c1 = Math.min(nx - 1, Math.floor((Math.max(...ring.map((p) => p[0])) - west) / step));
  const r0 = Math.max(0, Math.floor((north - Math.max(...ring.map((p) => p[1]))) / step)), r1 = Math.min(ny - 1, Math.floor((north - Math.min(...ring.map((p) => p[1]))) / step));
  for (let r = r0; r <= r1; r++) for (let c = c0; c <= c1; c++) if (inside(west + (c + 0.5) * step, north - (r + 0.5) * step, ring)) cells.push(r * nx + c);
  if (!cells.length) cells.push(Math.min(ny - 1, Math.max(0, Math.floor((north - lat) / step))) * nx + Math.min(nx - 1, Math.max(0, Math.floor((lon - west) / step))));

  const layer = (id: string) => (meta.layers as Dict[]).find((l) => l.id === id);
  const i16Mean = (id: string): number | null => {
    const l = layer(id);
    if (!l) return null;
    const a = new Int16Array(buf, l.offset, nx * ny);
    const vals = cells.map((k) => a[k]).filter((v) => v !== l.nodata).map((v) => v / l.scale);
    return vals.length ? mean(vals) : null;
  };
  const u8 = (id: string, index: number) => {
    const l = layer(id)!;
    return new Uint8Array(buf, l.offset + index * nx * ny, nx * ny);
  };
  const mode = (a: Uint8Array): [number, number] | null => {
    const count = new Map<number, number>();
    let total = 0;
    for (const k of cells) if (a[k] !== 255) { count.set(a[k], (count.get(a[k]) ?? 0) + 1); total++; }
    if (!total) return null;
    const [code, n] = [...count.entries()].sort((x, y) => y[1] - x[1])[0];
    return [code, n / total];
  };
  const r3 = (v: number | null, d = 3) => (v === null ? null : pyRound(v, d));

  // --- soil and terrain ------------------------------------------------------
  const cls = layer("soil_class") ? mode(u8("soil_class", 0)) : null;
  const sc: Dict = cls ? (meta.soil_classes as Dict[])[cls[0]] ?? {} : {};
  const om = i16Mean("om_pct_0_30");
  const soil: Dict | null = om === null && !cls ? null : {
    muname: sc.muname ?? null, surface_texture: sc.surface_texture ?? null, om_pct_0_30: r3(om), clay_pct_0_30: r3(i16Mean("clay_pct_0_30")),
    sand_pct_0_30: r3(i16Mean("sand_pct_0_30")), silt_pct_0_30: r3(i16Mean("silt_pct_0_30")), ph_0_30: r3(i16Mean("ph_0_30")),
    ec_dsm_0_30: r3(i16Mean("ec_dsm_0_30")), sar_0_30: r3(i16Mean("sar_0_30")), kwfact_surface: r3(i16Mean("kwfact_surface")),
    wind_erodibility_group: sc.wind_erodibility_group ?? null, wind_erodibility_index: r3(i16Mean("wind_erodibility_index"), 0),
    drainage_class: sc.drainage_class ?? null, hydrologic_group: sc.hydrologic_group ?? null, dominant_mapunit_share: cls ? pyRound(cls[1], 2) : null,
    aws_0_100cm_cm: null, nitrogen_g_kg_0_30: null,
    derived: meta.soil_source === "soilgrids" ? "texture class, K factor and wind erodibility are derived from the mapped sand, silt, clay and organic carbon" : null,
  };
  const elevation = i16Mean("elevation_m");
  const slope = i16Mean("slope_pct");

  // --- greenness, month by month --------------------------------------------
  const nd = layer("ndvi");
  const years: number[] = nd?.years ?? [];
  const series: Record<number, (number | null)[]> = {};
  years.forEach((y, yi) => {
    series[y] = MONTHS.map((m) => {
      const a = u8("ndvi", yi * 12 + (m - 1));
      const vals = cells.map((k) => a[k]).filter((v) => v !== 255).map((v) => v / nd!.scale);
      return vals.length >= 0.6 * cells.length ? mean(vals) : null;
    });
  });
  const monthly = years.flatMap((y) => MONTHS.map((m) => ({ date: `${y}-${String(m).padStart(2, "0")}`, ndvi: r3(series[y][m - 1]), n: series[y][m - 1] === null ? 0 : 1, z: null, snow_share: null })));
  const calendar: Dict<Dict> = {};
  for (const m of MONTHS) {
    const vals = years.map((y) => series[y][m - 1]).filter((v): v is number => v !== null);
    calendar[m] = { low_cover_share: vals.length ? pyRound(vals.filter((v) => v < LOW_COVER_NDVI).length / vals.length, 2) : null, snow_share: null, ndvi_mean: vals.length ? pyRound(mean(vals), 3) : null, years: vals.length };
  }
  const fromHistory = region.kb.settings.existing === "from_history";
  const season = fromHistory ? [5, 6, 7, 8, 9] : MONTHS;
  const peaks: Record<number, number> = {};
  for (const y of years) {
    const vals = season.map((m) => series[y][m - 1]).filter((v): v is number => v !== null);
    if (vals.length >= 3) peaks[y] = quantile(vals, 0.9);
  }

  // --- what grew --------------------------------------------------------------
  let history: Dict[] = [];
  let phenology: Dict | null = null;
  if (fromHistory && layer("cdl")) {
    const names: Dict<string> = meta.cdl_names ?? {};
    const rows: CdlRow[] = [];
    (layer("cdl")!.years as number[]).forEach((y, i) => {
      const m = mode(u8("cdl", i));
      if (m) rows.push({ year: y, cdl_code: m[0], cdl_name: names[m[0]] ?? `Class ${m[0]}`, share: pyRound(m[1], 3) });
    });
    history = interpretHistory(rows, peaks, region.kb);
  } else if (!fromHistory) {
    const label = ["No crop seen", "One crop", "Two crops", "Three crops"];
    const counted = years.filter((y) => series[y].filter((v) => v !== null).length >= 8);
    history = counted.map((y) => {
      const pm = seasonsIn(series[y]);
      const k = Math.min(pm.length, 3);
      return { year: y, crop: k === 0 ? "fallow" : `seasons_${k}`, label: label[k], n_seasons: pm.length, peak_months: pm, peak_ndvi: r3(peaks[y] ?? null), doubtful: false, kind: "phenology", cdl_name: "", share: null,
        note: pm.length ? `Greenness peaked in ${pm.map((m) => ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"][m - 1]).join(", ")}.` : "No clear green season in the satellite record." };
    });
    if (history.length) {
      const all = history.flatMap((h) => h.peak_months as number[]);
      const usual = MONTHS.filter((m) => all.filter((x) => x === m).length >= Math.max(2, 0.3 * history.length));
      phenology = { median_seasons: median(history.map((h) => h.n_seasons)), usual_peak_months: usual, n_years: history.length, source: "Landsat monthly means, 30 m" };
    }
  }

  // --- everything coarse comes from the nearest pilot field ------------------
  const k = Math.cos((lat * Math.PI) / 180);
  const donor = [...donors].sort((a, b) => Math.hypot((a.lon - lon) * k, a.lat - lat) - Math.hypot((b.lon - lon) * k, b.lat - lat))[0];
  const km = Math.hypot((donor.lon - lon) * k, donor.lat - lat) * 111.3;
  return loadDonor(donor.id).then((d) => {
    const id = "CUSTOM-" + Math.random().toString(16).slice(2, 8).toUpperCase();
    const risk: number[] = d.evidence?.bare?.risk_months ?? [];
    const lc = risk.map((m) => calendar[m]?.low_cover_share).filter((v): v is number => v !== null && v !== undefined);
    const recent = history.slice(-8);
    const sources = { ...d.context.sources, et: false, modis: false, soil: Boolean(soil), history: history.length > 0, landsat: monthly.some((r) => r.ndvi !== null) };
    const reason = "No satellite water-use record for a drawn field.";
    const context: FieldContext = {
      ...d.context, field_id: id, name: "My drawn field", lat, lon, area_ha: pyRound(area, 1), is_custom: true,
      elevation_m: elevation !== null ? pyRound(elevation, 1) : d.context.elevation_m, slope_pct: slope !== null ? pyRound(slope, 2) : d.context.slope_pct,
      soil: soil ?? {}, soil_source: meta.soil_source, history, phenology, n_doubtful_years: recent.filter((r) => r.doubtful).length,
      water_factor: 1.0, water_factor_info: { available: false, factor: 1.0, reason }, landsat: { low_cover_share_peak_months: lc.length ? pyRound(mean(lc), 2) : null },
      sources, nearest_pilot_field: donor.id,
    };
    const dw = d.evidence.water ?? {};
    const evidence: Dict = {
      ...d.evidence, field_id: id,
      custom_note: `Drawn by hand. Soil, slope, greenness${fromHistory ? " and crop history" : ""} are read from a ${region.atlas!.step_m} m grid under your shape. Weather, soil moisture and the long-term water record come from ${donor.name}, ${km.toFixed(1)} km away. Satellite water use and the 25-year MODIS record are prepared only for the pilot fields, so they are missing here and confidence is lower.`,
      soil: soil ? { ...soil, source: meta.soil_source, mapunits: null } : null,
      terrain: { elevation_m: context.elevation_m, slope_pct_plane: context.slope_pct },
      greenness: { monthly, calendar, peak_by_year: Object.fromEntries(Object.entries(peaks).map(([y, v]) => [y, pyRound(v, 3)])), modis_peak: [], modis_trend: null, flood: null, phenology },
      history, history_kind: fromHistory ? "crop_map" : "seasons",
      water: { ...dw, et_monthly: [], et_annual: [], et_source: null, et_trend: null, calibration: { available: false, factor: 1.0, reason },
        monthly_normals: (dw.monthly_normals ?? []).map((r: Dict) => { const { et_actual: _drop, ...rest } = r; return rest; }) },
      bare: { ...(d.evidence.bare ?? {}), months_usually_low_cover: MONTHS.filter((m) => (calendar[m]?.low_cover_share ?? 0) >= 0.5) },
    };
    const feature: GeoJSON.Feature = {
      type: "Feature", geometry: polygon,
      properties: { field_id: id, name: context.name, lat, lon, area_ha: context.area_ha, is_custom: true, boundary_source: "Drawn by you on the map, not a surveyed boundary", is_demo_data: false,
        crop_latest: history.length ? history[history.length - 1].label : null, sources },
    };
    return { feature, data: { context, evidence, weather: d.weather } };
  });
}
