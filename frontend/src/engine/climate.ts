// Field climate from the per-field daily weather file, with what-if scenario adjustments.
// A port of engine/agromet.py and engine/climate.py (FAO-56 Penman-Monteith reference ET,
// frost dates, monthly normals). tests/test_parity.py checks it against the Python reference.

import { MONTHS, MonthMap, median, monthMap, npSum, pyRound, quantile } from "./num";

export const HEAT_THRESHOLDS = [30, 32, 35, 36, 38, 40, 42];

export interface Scenario {
  rain_pct: number;
  temp_c: number;
}

export const clampScenario = (s: Scenario): Scenario => ({
  rain_pct: Math.max(-50, Math.min(50, s.rain_pct)),
  temp_c: Math.max(-2, Math.min(5, s.temp_c)),
});

export interface WeatherMeta {
  start: string;
  n: number;
  vars: string[];
  scale: number[];
}

/** Thirty years of locally corrected daily weather for one field. */
export interface Weather {
  n: number;
  year: Int16Array;
  month: Int8Array;
  doy: Int16Array;
  tmax: Float64Array;
  tmin: Float64Array;
  tdew: Float64Array; // dew point at field elevation, not yet capped by Tmin
  wind: Float64Array;
  rs: Float64Array;
  precip: Float64Array;
}

export function decodeWeather(buf: ArrayBuffer, meta: WeatherMeta): Weather {
  const raw = new Int16Array(buf);
  const n = meta.n;
  if (raw.length !== n * meta.vars.length) throw new Error("Weather file has an unexpected length.");
  const col = (name: string) => {
    const i = meta.vars.indexOf(name);
    const out = new Float64Array(n);
    const s = meta.scale[i];
    for (let k = 0; k < n; k++) out[k] = raw[i * n + k] / s;
    return out;
  };
  const year = new Int16Array(n);
  const month = new Int8Array(n);
  const doy = new Int16Array(n);
  const [y0, m0, d0] = meta.start.split("-").map(Number);
  const t = new Date(Date.UTC(y0, m0 - 1, d0));
  for (let k = 0; k < n; k++) {
    const y = t.getUTCFullYear();
    year[k] = y;
    month[k] = t.getUTCMonth() + 1;
    doy[k] = Math.round((t.getTime() - Date.UTC(y, 0, 1)) / 86400000) + 1;
    t.setUTCDate(t.getUTCDate() + 1);
  }
  return { n, year, month, doy, tmax: col("tmax"), tmin: col("tmin"), tdew: col("tdew_raw"), wind: col("wind"), rs: col("rs"), precip: col("precip") };
}

// ---------------------------------------------------------------------------
// FAO-56 Penman-Monteith reference evapotranspiration (Allen et al. 1998)
// ---------------------------------------------------------------------------
const satVp = (t: number) => 0.6108 * Math.exp((17.27 * t) / (t + 237.3)); // eq. 11

function extraterrestrialRadiation(latDeg: number, doy: number): number {
  const phi = (latDeg * Math.PI) / 180; // eq. 21
  const dr = 1 + 0.033 * Math.cos((2 * Math.PI * doy) / 365.0);
  const delta = 0.409 * Math.sin((2 * Math.PI * doy) / 365.0 - 1.39);
  const ws = Math.acos(Math.max(-1, Math.min(1, -Math.tan(phi) * Math.tan(delta))));
  return ((24 * 60) / Math.PI) * 0.082 * dr * (ws * Math.sin(phi) * Math.sin(delta) + Math.cos(phi) * Math.cos(delta) * Math.sin(ws));
}

export function et0Fao56(tmax: number, tmin: number, tdew: number, u2: number, rs: number, latDeg: number, elevM: number, doy: number): number {
  const tmean = (tmax + tmin) / 2.0;
  const pressure = 101.3 * Math.pow((293.0 - 0.0065 * elevM) / 293.0, 5.26); // eq. 7
  const gamma = 0.000665 * pressure; // eq. 8
  const delta = (4098.0 * satVp(tmean)) / Math.pow(tmean + 237.3, 2); // eq. 13
  const es = (satVp(tmax) + satVp(tmin)) / 2.0; // eq. 12
  const ea = Math.min(satVp(tdew), es); // eq. 14
  const ra = extraterrestrialRadiation(latDeg, doy);
  const rso = (0.75 + 2e-5 * elevM) * ra; // eq. 37
  const rns = (1 - 0.23) * rs; // eq. 38
  const rel = Math.max(0, Math.min(1, rso > 0 ? rs / rso : 0));
  const rnl = ((4.903e-9 * (Math.pow(tmax + 273.16, 4) + Math.pow(tmin + 273.16, 4))) / 2.0) * (0.34 - 0.14 * Math.sqrt(Math.max(ea, 0))) * (1.35 * rel - 0.35); // eq. 39
  const rn = rns - rnl;
  const num = 0.408 * delta * rn + gamma * (900.0 / (tmean + 273.0)) * u2 * (es - ea);
  const den = delta + gamma * (1 + 0.34 * u2);
  return Math.max(num / den, 0); // eq. 6
}

/** Monthly effective precipitation, mm (USDA-SCS, 75 mm storage). */
export function effectivePrecipUsda(pMm: number, etcMm: number): number {
  const pIn = Math.max(pMm, 0) / 25.4;
  const etcIn = Math.max(etcMm, 0) / 25.4;
  const peIn = (0.70917 * Math.pow(pIn, 0.82416) - 0.11556) * Math.pow(10.0, 0.02426 * etcIn);
  const pe = Math.max(peIn, 0) * 25.4;
  return Math.min(Math.min(pe, pMm), etcMm);
}

// ---------------------------------------------------------------------------
export interface Clim {
  n_years: number;
  et0_month: MonthMap;
  precip_month: MonthMap;
  tmax_month: MonthMap;
  tmin_month: MonthMap;
  wind_month: MonthMap;
  windy_days_month: MonthMap;
  heavy_rain_days_month: MonthMap;
  heavy_rain_mm: number;
  hot_day_c: number;
  hot_days_month: MonthMap;
  hot_days: number;
  frost_days_month: MonthMap;
  heat_days_month: Record<number, MonthMap>;
  et0_annual: number;
  precip_annual: number;
  frost_free_days: number[];
  frost_free_median: number;
  frost_free_p20: number;
  last_spring_frost_median_doy: number;
  first_fall_frost_median_doy: number;
}

export interface ClimSettings {
  heavy_rain_mm?: number;
  windy_ms?: number;
  hot_day_c?: number;
}

/** 30-year normals under a scenario. Mirrors apply_scenario() + summarise() in engine/climate.py. */
export function climateFor(w: Weather, lat: number, elevM: number, scenario: Scenario, st: ClimSettings): Clim {
  const sc = clampScenario(scenario);
  const heavy = Number(st.heavy_rain_mm ?? 10.0);
  const windy = Number(st.windy_ms ?? 4.5);
  const hotC = Number(st.hot_day_c ?? 32);
  const rainF = 1.0 + sc.rain_pct / 100.0;

  const z = () => new Float64Array(13);
  const et0 = z(), precip = z(), tmaxS = z(), tminS = z(), windS = z(), days = z();
  const windyN = z(), heavyN = z(), hotN = z(), frostN = z();
  const heatN = HEAT_THRESHOLDS.map(() => z());
  let hotTotal = 0;
  const years: number[] = [];
  const perYear = new Map<number, { n: number; lastSpring: number; firstFall: number }>();

  for (let k = 0; k < w.n; k++) {
    const m = w.month[k];
    const tmax = w.tmax[k] + sc.temp_c;
    const tmin = w.tmin[k] + sc.temp_c;
    const tdew = Math.min(w.tdew[k], tmin);
    const p = w.precip[k] * rainF;
    const e = et0Fao56(tmax, tmin, tdew, w.wind[k], w.rs[k], lat, elevM, w.doy[k]);
    et0[m] += e;
    precip[m] += p;
    tmaxS[m] += tmax;
    tminS[m] += tmin;
    windS[m] += w.wind[k];
    days[m] += 1;
    if (w.wind[k] >= windy) windyN[m] += 1;
    if (p >= heavy) heavyN[m] += 1;
    if (tmax > hotC) {
      hotN[m] += 1;
      hotTotal += 1;
    }
    if (tmin <= 0.0) frostN[m] += 1;
    for (let i = 0; i < HEAT_THRESHOLDS.length; i++) if (tmax > HEAT_THRESHOLDS[i]) heatN[i][m] += 1;

    const y = w.year[k];
    let rec = perYear.get(y);
    if (!rec) {
      rec = { n: 0, lastSpring: 1, firstFall: 366 };
      perYear.set(y, rec);
      years.push(y);
    }
    rec.n += 1;
    if (tmin <= 0.0) {
      const d = w.doy[k];
      if (d < 196) rec.lastSpring = Math.max(rec.lastSpring, d);
      else rec.firstFall = Math.min(rec.firstFall, d);
    }
  }
  const nYears = years.length;
  const perYearMean = (a: Float64Array) => monthMap((m) => pyRound(a[m] / nYears, 2));
  const et0Raw = MONTHS.map((m) => et0[m] / nYears);
  const pRaw = MONTHS.map((m) => precip[m] / nYears);

  const ffd: number[] = [], lastSpring: number[] = [], firstFall: number[] = [];
  for (const y of years) {
    const r = perYear.get(y)!;
    if (r.n < 360) continue;
    ffd.push(Math.max(r.firstFall - r.lastSpring - 1, 0));
    lastSpring.push(r.lastSpring);
    firstFall.push(r.firstFall);
  }
  const heat: Record<number, MonthMap> = {};
  HEAT_THRESHOLDS.forEach((thr, i) => (heat[thr] = perYearMean(heatN[i])));

  return {
    n_years: nYears,
    et0_month: monthMap((m) => pyRound(et0Raw[m - 1], 1)),
    precip_month: monthMap((m) => pyRound(pRaw[m - 1], 1)),
    tmax_month: monthMap((m) => pyRound(tmaxS[m] / days[m], 1)),
    tmin_month: monthMap((m) => pyRound(tminS[m] / days[m], 1)),
    wind_month: monthMap((m) => pyRound(windS[m] / days[m], 2)),
    windy_days_month: perYearMean(windyN),
    heavy_rain_days_month: perYearMean(heavyN),
    heavy_rain_mm: heavy,
    hot_day_c: hotC,
    hot_days_month: perYearMean(hotN),
    hot_days: pyRound(hotTotal / Math.max(nYears, 1), 1),
    frost_days_month: perYearMean(frostN),
    heat_days_month: heat,
    et0_annual: pyRound(npSum(et0Raw), 0),
    precip_annual: pyRound(npSum(pRaw), 0),
    frost_free_days: ffd,
    frost_free_median: median(ffd),
    frost_free_p20: quantile(ffd, 0.2),
    last_spring_frost_median_doy: median(lastSpring),
    first_fall_frost_median_doy: median(firstFall),
  };
}

/** Share of baseline years whose frost-free season was long enough for a crop. */
export function seasonFit(frostFreeDays: number[], needed: number): number {
  if (needed <= 0) return 1.0;
  if (!frostFreeDays.length) return 0.0;
  return pyRound(frostFreeDays.filter((v) => v >= needed).length / frostFreeDays.length, 3);
}

/** Average number of days a year above a crop's heat limit during its months. */
export function heatDaysIn(months: number[], limitC: number, clim: Clim): number {
  const below = HEAT_THRESHOLDS.filter((t) => t <= limitC);
  const thr = below.length ? Math.max(...below) : HEAT_THRESHOLDS[0];
  const table = clim.heat_days_month[thr];
  let s = 0;
  for (const m of months) s += table[m];
  return s;
}
