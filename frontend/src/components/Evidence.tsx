import { useMemo } from "react";
import { Area, Bar, CartesianGrid, Cell, ComposedChart, Line, ReferenceLine, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { MONTHS, SERIES, fmt, mmToIn, monthList, type Dict, type RegionData } from "../data";
import { ChartFrame, Stat, TipBox } from "./ui";

export const PANELS: { id: string; label: string }[] = [
  { id: "water", label: "Water" },
  { id: "climate", label: "Weather" },
  { id: "cover", label: "Greenness and cover" },
  { id: "soil", label: "Soil" },
  { id: "history", label: "Crop history" },
  { id: "groundwater", label: "Long-term water" },
];

const AXIS = { fontSize: 12, fill: "#4a5c57" };
const GRID = "#dde4df";
const NEUTRAL = "#869490";
const INK = "#14211e";
const H = 230;

function trendText(t: Dict | undefined | null, unit: string, digits = 1): string {
  if (!t || t.slope_per_decade === null || t.slope_per_decade === undefined) return "Not enough years for a trend.";
  const s = `${t.slope_per_decade > 0 ? "+" : ""}${fmt(t.slope_per_decade, digits)} ${unit} per decade${t.from_year ? ` since ${t.from_year}` : ""}`;
  if (!t.significant) return `No clear trend (${s}, which could be chance).`;
  return `${t.direction === "increasing" ? "Rising" : "Falling"}: ${s} (unlikely to be chance).`;
}

const yearTicks = (rows: Dict[]) => rows.filter((r) => String(r.date).endsWith("-01")).map((r) => r.date);
const yearOf = (d: string) => String(d).slice(0, 4);
const monthLabel = (d: string) => `${MONTHS[Number(String(d).slice(5, 7)) - 1]} ${yearOf(d)}`;
const correctionText = (m: string | undefined) =>
  m === "gridmet" ? "corrected month by month to gridMET (4 km, station-informed)"
  : m === "imd" ? "corrected month by month to India Meteorological Department station grids"
  : m === "imd_rain" ? "shifted to field elevation, rain scaled to IMD rain gauges" : "shifted to field elevation";

// ---------------------------------------------------------------------------
function WaterPanel({ ev, imperial }: { ev: Dict; imperial: boolean }) {
  const w = ev.water ?? {};
  const monthly: Dict[] = useMemo(
    () => (w.et_monthly ?? []).map((r: Dict) => ({ date: r.date, et: r.flagged ? null : r.et, band: r.et_min != null && r.et_max != null && !r.flagged ? [r.et_min, r.et_max] : null, et0: r.et0_power })),
    [w.et_monthly],
  );
  const normals: Dict[] = (w.monthly_normals ?? []).map((r: Dict) => ({ ...r, name: MONTHS[r.month - 1] }));
  const cal = w.calibration ?? {};
  const cmp: Dict[] = w.source_comparison ?? [];
  const hasEt = monthly.length > 0;
  const hasBand = monthly.some((r) => r.band);
  const etName = String(w.et_source ?? "Satellite").split(" (")[0];
  const gap = normals.reduce((a, r) => a + Math.max(r.et0_power - r.precip, 0), 0);
  const ground = ev.climate?.ground_label ?? "ground stations";
  const hasEto = cmp.some((r) => r.eto_ground != null);

  return (
    <>
      {hasEt ? (
        <ChartFrame
          title="Water this field actually used, month by month (mm)"
          lede={`The blue line is the satellite estimate of water evaporated and transpired.${hasBand ? " The band is how far the six OpenET models disagree." : ""} The dashed line is how thirsty the weather was.`}
          source={`${w.et_source ?? "Satellite ET"} and NASA POWER reference ET. Estimates, not meter readings.`}
          legend={[{ label: `Water used (${etName})`, color: SERIES[0] }, ...(hasBand ? [{ label: "Range of the models", color: SERIES[0], shape: "band" as const }] : []), { label: "Weather's demand (reference ET)", color: NEUTRAL, shape: "dash" as const }]}
          rows={w.et_monthly} columns={[{ key: "date", label: "Month" }, { key: "et", label: "Water used (mm)" }, ...(hasBand ? [{ key: "et_min", label: "Lowest model" }, { key: "et_max", label: "Highest model" }] : []), { key: "et0_power", label: "Reference ET (mm)" }]}>
          <ResponsiveContainer width="100%" height={H + 20}>
            <ComposedChart data={monthly} margin={{ top: 8, right: 8, bottom: 0, left: -8 }}>
              <CartesianGrid stroke={GRID} vertical={false} />
              <XAxis dataKey="date" ticks={yearTicks(monthly)} tickFormatter={yearOf} tick={AXIS} tickLine={false} axisLine={{ stroke: GRID }} />
              <YAxis tick={AXIS} tickLine={false} axisLine={false} width={44} />
              <Tooltip cursor={{ stroke: NEUTRAL, strokeDasharray: "3 3" }} content={({ active, payload, label }) => {
                if (!active || !payload?.length) return null;
                const r = payload[0].payload as Dict;
                return <TipBox title={monthLabel(String(label))} rows={[
                  { label: "Water used", value: r.et != null ? `${fmt(r.et)} mm` : "left out", color: SERIES[0] },
                  ...(r.band ? [{ label: "Models range", value: `${fmt(r.band[0])}–${fmt(r.band[1])} mm` }] : []),
                  { label: "Reference ET", value: `${fmt(r.et0)} mm`, color: NEUTRAL }]} />;
              }} />
              {hasBand && <Area dataKey="band" stroke="none" fill={SERIES[0]} fillOpacity={0.16} isAnimationActive={false} connectNulls={false} />}
              <Line dataKey="et0" stroke={NEUTRAL} strokeWidth={1.5} strokeDasharray="5 4" dot={false} isAnimationActive={false} />
              <Line dataKey="et" stroke={SERIES[0]} strokeWidth={2} dot={false} isAnimationActive={false} connectNulls={false} />
            </ComposedChart>
          </ResponsiveContainer>
        </ChartFrame>
      ) : (
        <p className="notice">No satellite water-use record for this shape: it was prepared for the pilot fields only. Water figures below are textbook estimates and are marked low confidence.</p>
      )}

      <ChartFrame
        title="A typical year: rain against the weather's thirst (mm a month)"
        lede={<>Over a year the weather asks for about <strong>{fmt(gap)} mm</strong>{imperial ? ` (${fmt(mmToIn(gap), 0)} in)` : ""} more water than rain supplies in the months when rain falls short. That gap is what irrigation has to cover.</>}
        source={`Rain: ${ev.climate?.rain_source ?? "NASA POWER"}. Reference ET: NASA POWER, ${correctionText(ev.climate?.correction?.method)}. 1996–2025 averages.${hasEt ? ` Water used: ${etName}.` : ""} Reference ET is for mown grass, not your crop.`}
        legend={[{ label: "Rain", color: SERIES[0], shape: "bar" }, { label: "Weather's demand (reference ET)", color: SERIES[3], shape: "bar" }, ...(hasEt ? [{ label: "Water this field used", color: SERIES[2], shape: "bar" as const }] : [])]}
        rows={normals} columns={[{ key: "name", label: "Month" }, { key: "precip", label: "Rain (mm)" }, { key: "et0_power", label: "Reference ET (mm)" }, { key: "et_actual", label: "Water used (mm)" }, { key: "balance", label: "Rain minus demand" }]}>
        <ResponsiveContainer width="100%" height={H}>
          <ComposedChart data={normals} margin={{ top: 8, right: 8, bottom: 0, left: -8 }} barGap={2} barCategoryGap="22%">
            <CartesianGrid stroke={GRID} vertical={false} />
            <XAxis dataKey="name" tick={AXIS} tickLine={false} axisLine={{ stroke: GRID }} interval={0} />
            <YAxis tick={AXIS} tickLine={false} axisLine={false} width={44} />
            <Tooltip cursor={{ fill: "rgba(20,33,30,0.05)" }} content={({ active, payload, label }) => {
              if (!active || !payload?.length) return null;
              const r = payload[0].payload as Dict;
              return <TipBox title={String(label)} rows={[
                { label: "Rain", value: `${fmt(r.precip)} mm`, color: SERIES[0] },
                { label: "Reference ET", value: `${fmt(r.et0_power)} mm`, color: SERIES[3] },
                ...(r.et_actual != null ? [{ label: "Water used", value: `${fmt(r.et_actual)} mm`, color: SERIES[2] }] : [])]} />;
            }} />
            <Bar dataKey="precip" fill={SERIES[0]} radius={[4, 4, 0, 0]} isAnimationActive={false} />
            <Bar dataKey="et0_power" fill={SERIES[3]} radius={[4, 4, 0, 0]} isAnimationActive={false} />
            {hasEt && <Bar dataKey="et_actual" fill={SERIES[2]} radius={[4, 4, 0, 0]} isAnimationActive={false} />}
          </ComposedChart>
        </ResponsiveContainer>
      </ChartFrame>

      <div className="explain">
        <h4>How the irrigation estimate relates to this field's own record</h4>
        {cal.available ? (
          <>
            <p>
              Textbook crop tables give the water a fully irrigated crop <em>could</em> use. In this field's own alfalfa years, OpenET saw it use about <strong>{Math.round(cal.raw_ratio * 100)} %</strong> of that. Every rotation's water
              figure is scaled by the same factor ({cal.factor}), so the comparison stays fair.
            </p>
            <div className="table-scroll">
              <table className="data-table">
                <thead><tr><th>Alfalfa year</th><th>OpenET, May–Sep (mm)</th><th>Textbook, May–Sep (mm)</th><th>Ratio</th></tr></thead>
                <tbody>{(cal.rows ?? []).map((r: Dict) => <tr key={r.year}><td>{r.year}</td><td className="num">{fmt(r.openet_mm)}</td><td className="num">{fmt(r.textbook_mm)}</td><td className="num">{fmt(r.ratio, 2)}</td></tr>)}</tbody>
              </table>
            </div>
          </>
        ) : (
          <p>{cal.reason ?? "No satellite water-use record."} The textbook figure is used as it is.</p>
        )}
      </div>

      {cmp.length > 0 && (
        <div className="explain">
          <h4>Two sources, two answers</h4>
          <p>
            NASA POWER is a satellite-and-model product on a ~50 km grid. GPM IMERG is satellite rainfall on a ~10 km grid. {ground} is built from weather stations on the ground. Where they disagree, that disagreement is the uncertainty.
            “Rain the tool uses” is {ev.climate?.rain_source ?? "NASA POWER"}.
          </p>
          <div className="table-scroll">
            <table className="data-table">
              <thead><tr><th>Year</th><th>Rain the tool uses (mm)</th>{ev.climate?.imerg && <th>Rain, IMERG as downloaded (mm)</th>}<th>Rain, ground stations (mm)</th><th>Reference ET, NASA POWER (mm)</th>{hasEto && <th>Reference ET, ground grid (mm)</th>}</tr></thead>
              <tbody>{cmp.map((r) => <tr key={r.year}><td>{r.year}</td><td className="num">{fmt(r.precip_used)}</td>{ev.climate?.imerg && <td className="num">{fmt(r.precip_imerg_raw)}</td>}<td className="num">{fmt(r.precip_ground)}</td><td className="num">{fmt(r.et0_power)}</td>{hasEto && <td className="num">{fmt(r.eto_ground)}</td>}</tr>)}</tbody>
            </table>
          </div>
        </div>
      )}
    </>
  );
}

// ---------------------------------------------------------------------------
function YearBars({ rows, k, color, unit, refs = [] }: { rows: Dict[]; k: string; color: string; unit: string; refs?: { y: number; label: string }[] }) {
  return (
    <ResponsiveContainer width="100%" height={190}>
      <ComposedChart data={rows} margin={{ top: 14, right: 8, bottom: 0, left: -8 }} barCategoryGap="18%">
        <CartesianGrid stroke={GRID} vertical={false} />
        <XAxis dataKey="year" tick={AXIS} tickLine={false} axisLine={{ stroke: GRID }} interval={4} />
        <YAxis tick={AXIS} tickLine={false} axisLine={false} width={44} />
        <Tooltip cursor={{ fill: "rgba(20,33,30,0.05)" }} content={({ active, payload, label }) =>
          active && payload?.length ? <TipBox title={String(label)} rows={[{ label: unit, value: fmt(payload[0].payload[k], 1), color }]} /> : null} />
        <Bar dataKey={k} fill={color} radius={[3, 3, 0, 0]} isAnimationActive={false} />
        {refs.map((r) => (
          <ReferenceLine key={r.label} y={r.y} stroke={INK} strokeDasharray="4 3" label={{ value: r.label, position: "insideTopRight", style: { ...AXIS, fill: INK } }} />
        ))}
      </ComposedChart>
    </ResponsiveContainer>
  );
}

function ClimatePanel({ ev, region }: { ev: Dict; region: RegionData }) {
  const c = ev.climate ?? {};
  const rows: Dict[] = c.annual ?? [];
  const t = c.trends ?? {};
  const corr = c.correction ?? {};
  const chk = corr.check ?? {};
  const cs = c.summary ?? {};
  const hot = cs.hot_day_c ?? 32;
  const heavy = cs.heavy_rain_mm ?? 10;
  const frost = Boolean(region.region.has_frost);
  const yearCols = (k: string, label: string) => [{ key: "year", label: "Year" }, { key: k, label }];
  const src = `NASA POWER daily record, ${correctionText(corr.method)}. A grid value, not a weather station in the field.`;
  const teff = region.kb.crops.teff?.traits?.frost_free_days_needed;
  return (
    <>
      {corr.method === "gridmet" && chk.frost_free_days_power_raw != null && (
        <div className="explain callout">
          <h4>Why satellite-era weather grids need ground truth</h4>
          <p>
            NASA POWER's grid cell here averages 2,025 m of mountain and valley. On its own it puts the frost-free season at about <strong>{fmt(chk.frost_free_days_power_raw)} days</strong>. Corrected with gridMET, which uses weather
            stations and terrain, it is about <strong>{fmt(chk.frost_free_days_power_corrected)} days</strong>: nights on the valley floor run about {fmt(Math.abs(chk.mean_tmin_delta_c), 1)} °C colder, because cold air pools there. That
            difference decides whether a frost-tender crop is safe.
          </p>
        </div>
      )}
      {corr.method === "imd" && chk.hot_days_power != null && (
        <div className="explain callout">
          <h4>Why satellite-era weather grids need ground truth</h4>
          <p>
            NASA POWER comes from a global weather model that does not know these plains are irrigated or how close the sea is. On its own it counts about <strong>{fmt(chk.hot_days_power)} days</strong> a year above {fmt(chk.hot_day_c)} °C
            here; India Meteorological Department stations measured about <strong>{fmt(chk.hot_days_ground)}</strong>. Afternoons differ by up to {fmt(Math.abs(chk.largest_tmax_delta_c), 1)} °C in the worst month. The tool shifts each
            month of the NASA record to the station average, which changes both heat stress and crop water demand.
          </p>
        </div>
      )}
      <div className="small-multiples">
        <ChartFrame title="Average temperature by year (°C)" lede={trendText(t.tmean, "°C", 2)} source={src} rows={rows} columns={yearCols("tmean", "Mean temperature (°C)")}>
          <ResponsiveContainer width="100%" height={190}>
            <ComposedChart data={rows} margin={{ top: 14, right: 8, bottom: 0, left: -8 }}>
              <CartesianGrid stroke={GRID} vertical={false} />
              <XAxis dataKey="year" tick={AXIS} tickLine={false} axisLine={{ stroke: GRID }} interval={4} />
              <YAxis tick={AXIS} tickLine={false} axisLine={false} width={44} domain={["dataMin - 0.5", "dataMax + 0.5"]} tickFormatter={(v) => fmt(v, 1)} />
              <Tooltip cursor={{ stroke: NEUTRAL, strokeDasharray: "3 3" }} content={({ active, payload, label }) =>
                active && payload?.length ? <TipBox title={String(label)} rows={[{ label: "Mean temperature", value: `${fmt(payload[0].payload.tmean, 1)} °C`, color: SERIES[1] }]} /> : null} />
              <Line dataKey="tmean" stroke={SERIES[1]} strokeWidth={2} dot={{ r: 2.5, strokeWidth: 0, fill: SERIES[1] }} activeDot={{ r: 5 }} isAnimationActive={false} />
            </ComposedChart>
          </ResponsiveContainer>
        </ChartFrame>
        <ChartFrame title={`Hot days: above ${hot} °C`} lede={trendText(t.hot_days, "days")} source={src} rows={rows} columns={yearCols("hot_days", `Days above ${hot} °C`)}>
          <YearBars rows={rows} k="hot_days" color={SERIES[1]} unit={`Days above ${hot} °C`} />
        </ChartFrame>
        {frost ? (
          <ChartFrame title="Frost-free season (days)" lede={trendText(t.frost_free_days, "days")} source={src + " The coldest hollows frost earlier and later than this."} rows={rows} columns={yearCols("frost_free_days", "Frost-free days")}>
            <YearBars rows={rows} k="frost_free_days" color={SERIES[2]} unit="Frost-free days" refs={teff ? [{ y: teff, label: `teff needs ~${teff}` }] : []} />
          </ChartFrame>
        ) : (
          <ChartFrame title={`Heavy-rain days: ${fmt(heavy)} mm or more`} lede={trendText(t.heavy_rain_days, "days", 2)} source={`${c.rain_source ?? "NASA POWER"}. Frost does not limit crops here, so this chart takes its place.`} rows={rows} columns={yearCols("heavy_rain_days", "Heavy-rain days")}>
            <YearBars rows={rows} k="heavy_rain_days" color={SERIES[2]} unit="Heavy-rain days" />
          </ChartFrame>
        )}
        <ChartFrame title="Rain by year (mm)" lede={trendText(t.precip, "mm", 0)} source={`${c.rain_source ?? "NASA POWER"}.${c.imerg ? " A ~10 km satellite estimate tied to rain gauges monthly: it can miss small storms." : " GPM IMERG satellite rainfall is not loaded."}`} rows={rows} columns={[...yearCols("precip", "Rain (mm)"), { key: "heavy_rain_days", label: `Days with ${fmt(heavy)} mm or more` }]}>
          <YearBars rows={rows} k="precip" color={SERIES[0]} unit="Rain (mm)" />
        </ChartFrame>
      </div>
      <p className="fine">
        {frost ? `Heavy-rain days (${fmt(heavy)} mm or more in a day): ${trendText(t.heavy_rain_days, "days", 2).toLowerCase()} ` : ""}Yearly water balance (rain minus reference ET): {trendText(t.water_balance, "mm", 0).toLowerCase()}
        {cs.wettest_months ? ` The three wettest months (${monthList(cs.wettest_months)}) bring ${Math.round((cs.wettest_share ?? 0) * 100)} % of the year's rain.` : ""}
      </p>
    </>
  );
}

// ---------------------------------------------------------------------------
function CoverPanel({ ev, region }: { ev: Dict; region: RegionData }) {
  const g = ev.greenness ?? {};
  const monthly: Dict[] = g.monthly ?? [];
  const modis: Dict[] = g.modis_peak ?? [];
  const vul: Dict[] = ev.vulnerability?.months ?? [];
  const bare: number[] = ev.bare?.months_usually_low_cover ?? [];
  const hay = Boolean(region.kb.crops.alfalfa);
  const hasFrost = vul.some((r) => r.frost != null);
  const fl = g.flood;
  return (
    <>
      <ChartFrame
        title="How green the field was, month by month"
        lede={<>Below the dashed line there is little green cover. {bare.length ? <>That is usual here in <strong>{monthList(bare)}</strong>.</> : "No month is usually below it."}{hay ? " Sharp summer dips are hay cuts." : " Each rise and fall is one crop season."}</>}
        source="Landsat 8/9 NDVI (USGS/NASA), 30 m, clear observations averaged by month. Brown does not always mean bare: stubble still protects the soil, and cloud leaves gaps in the rainy season."
        rows={monthly} columns={[{ key: "date", label: "Month" }, { key: "ndvi", label: "Greenness (NDVI)", digits: 2 }, { key: "n", label: "Clear images" }, { key: "z", label: "Against its own normal (z)", digits: 1 }]}>
        <ResponsiveContainer width="100%" height={H + 20}>
          <ComposedChart data={monthly} margin={{ top: 8, right: 8, bottom: 0, left: -8 }}>
            <CartesianGrid stroke={GRID} vertical={false} />
            <XAxis dataKey="date" ticks={yearTicks(monthly)} tickFormatter={yearOf} tick={AXIS} tickLine={false} axisLine={{ stroke: GRID }} />
            <YAxis tick={AXIS} tickLine={false} axisLine={false} width={44} domain={[0, 1]} ticks={[0, 0.25, 0.5, 0.75, 1]} />
            <Tooltip cursor={{ stroke: NEUTRAL, strokeDasharray: "3 3" }} content={({ active, payload, label }) => {
              if (!active || !payload?.length) return null;
              const r = payload[0].payload as Dict;
              return <TipBox title={monthLabel(String(label))} rows={[
                { label: "Greenness", value: r.ndvi != null ? fmt(r.ndvi, 2) : (r.snow_share ?? 0) >= 0.5 ? "snow" : "no clear image", color: SERIES[2] },
                { label: "Clear images", value: String(r.n ?? 0) }]} />;
            }} />
            <ReferenceLine y={0.25} stroke={INK} strokeDasharray="4 3" label={{ value: "little green cover", position: "insideBottomRight", style: { ...AXIS, fill: INK } }} />
            <Line dataKey="ndvi" stroke={SERIES[2]} strokeWidth={2} dot={false} isAnimationActive={false} connectNulls={false} />
          </ComposedChart>
        </ResponsiveContainer>
      </ChartFrame>

      {modis.length > 0 ? (
        <ChartFrame title="Peak greenness each year, over 25 years" lede={trendText(g.modis_trend, "NDVI", 3)}
          source="MODIS/Terra MOD13Q1 (NASA), 250 m, highest value each year. One field holds only a few MODIS pixels and its edges mix in the neighbours, so this reads lower than Landsat."
          rows={modis} columns={[{ key: "year", label: "Year" }, { key: "ndvi", label: "Peak greenness (NDVI)", digits: 2 }]}>
          <ResponsiveContainer width="100%" height={190}>
            <ComposedChart data={modis} margin={{ top: 14, right: 8, bottom: 0, left: -8 }}>
              <CartesianGrid stroke={GRID} vertical={false} />
              <XAxis dataKey="year" tick={AXIS} tickLine={false} axisLine={{ stroke: GRID }} interval={3} />
              <YAxis tick={AXIS} tickLine={false} axisLine={false} width={44} domain={[0, 1]} ticks={[0, 0.25, 0.5, 0.75, 1]} />
              <Tooltip cursor={{ stroke: NEUTRAL, strokeDasharray: "3 3" }} content={({ active, payload, label }) =>
                active && payload?.length ? <TipBox title={String(label)} rows={[{ label: "Peak greenness", value: fmt(payload[0].payload.ndvi, 2), color: SERIES[2] }]} /> : null} />
              <Line dataKey="ndvi" stroke={SERIES[2]} strokeWidth={2} dot={{ r: 2.5, strokeWidth: 0, fill: SERIES[2] }} activeDot={{ r: 5 }} isAnimationActive={false} />
            </ComposedChart>
          </ResponsiveContainer>
        </ChartFrame>
      ) : (
        <p className="notice">The 25-year MODIS greenness record is prepared for the pilot fields only.</p>
      )}

      {fl && fl.years_with_signal > 0 && (
        <div className="explain">
          <h4>Signs of standing water</h4>
          <p>
            In {fl.years_with_signal} of {fl.years} years Landsat saw the field wetter than it was green{fl.peak_months?.length ? <>, most often in <strong>{monthList(fl.peak_months)}</strong></> : null}: the look of a flooded field at
            transplanting. It is a hint that paddy is grown, not a crop map. Method: land-surface water index against NDVI (Xiao et al. 2005).
          </p>
        </div>
      )}

      <div className="explain">
        <h4>When the crop looks most exposed</h4>
        <p>{ev.vulnerability?.method}</p>
        <div className="table-scroll">
          <table className="data-table">
            <thead><tr><th>Month</th><th>Heat</th>{hasFrost && <th>Frost</th>}<th>Water gap</th><th>Greenness dips</th><th>Dry soil</th><th>Combined</th></tr></thead>
            <tbody>
              {vul.map((r) => (
                <tr key={r.month} className={(ev.vulnerability?.most_vulnerable ?? []).includes(r.month) ? "row-hi" : ""}>
                  <td>{MONTHS[r.month - 1]}</td>
                  {["heat", ...(hasFrost ? ["frost"] : []), "water_gap", "greenness_dips", "dry_soil"].map((k) => <td key={k} className="num">{r[k] == null ? "–" : fmt(r[k], 2)}</td>)}
                  <td className="num"><strong>{fmt(r.index, 2)}</strong></td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        <p className="fine">Each part runs from 0 (no stress) to 1. Highlighted rows are the two highest. A screening aid: it cannot see pests, disease or how the field was irrigated.</p>
      </div>
    </>
  );
}

// ---------------------------------------------------------------------------
function SoilPanel({ ev }: { ev: Dict }) {
  const s = ev.soil;
  const sm = ev.soil_moisture;
  const smRows: Dict[] = sm?.monthly ?? [];
  const grids = s?.source === "soilgrids";
  let units: Dict[] = [];
  try {
    units = s?.mapunits ? (typeof s.mapunits === "string" ? JSON.parse(s.mapunits) : s.mapunits) : [];
  } catch {
    units = [];
  }
  // diverging: two hues with a neutral middle
  const zColor = (z: number | null) => (z == null ? "#d5dbd8" : z <= -0.5 ? SERIES[1] : z >= 0.5 ? SERIES[0] : "#b6c0bc");
  const has = (v: unknown) => v !== null && v !== undefined;
  return (
    <>
      {s ? (
        <>
          <div className="stats">
            <Stat label="Surface texture" value={s.surface_texture ?? "–"} note={s.muname} />
            <Stat label="Organic matter" value={fmt(s.om_pct_0_30, 1)} unit="%" note={s.om_pct_0_30 < 1.5 ? "Low: room to build" : "Top 30 cm"} />
            {has(s.ec_dsm_0_30) ? <Stat label="Salinity (EC)" value={fmt(s.ec_dsm_0_30, 1)} unit="dS/m" note={s.ec_dsm_0_30 >= 2 ? "Above 2: sensitive crops start losing yield" : "Below the level that hurts sensitive crops"} />
              : <Stat label="Salinity" value="not mapped" note="The global soil model has no salinity layer: test where salt is a known problem" />}
            <Stat label="pH" value={fmt(s.ph_0_30, 1)} note={s.ph_0_30 >= 8.5 ? "Strongly alkaline" : s.ph_0_30 >= 7.9 ? "Moderately alkaline" : s.ph_0_30 >= 6.6 ? "Near neutral" : "Acid"} />
            <Stat label="Wind erodibility" value={`Group ${s.wind_erodibility_group ?? "–"}`} note={`Index ${fmt(s.wind_erodibility_index)} t/ac/yr: ${s.wind_erodibility_index >= 134 ? "blows easily" : s.wind_erodibility_index >= 86 ? "moderate" : "resists wind"}`} />
            {has(s.aws_0_100cm_cm) && <Stat label="Water it can hold" value={fmt(s.aws_0_100cm_cm * 10)} unit="mm" note="Available to plants in the top metre" />}
            {has(s.drainage_class) && <Stat label="Drainage" value={s.drainage_class} note={`Hydrologic group ${s.hydrologic_group ?? "–"}`} />}
            <Stat label="Clay / sand" value={`${fmt(s.clay_pct_0_30)} / ${fmt(s.sand_pct_0_30)}`} unit="%" note="Top 30 cm" />
            {has(s.nitrogen_g_kg_0_30) && <Stat label="Total nitrogen" value={fmt(s.nitrogen_g_kg_0_30, 1)} unit="g/kg" note="Top 30 cm, modelled" />}
          </div>
          <p className="fine">
            {grids
              ? `Source: ISRIC SoilGrids 2.0, a global model on a 250 m grid trained on soil profiles worldwide. ${s.derived ? `${s.derived[0].toUpperCase()}${s.derived.slice(1)}. ` : ""}It gives the likely soil for the neighbourhood, not a sample from this field: a soil test is the only measurement.`
              : `${units.length ? `Soil map units under the field: ${units.map((u) => `${u.name} (${Math.round(u.share * 100)} %)`).join("; ")}. ` : ""}Source: USDA NRCS SSURGO. These are survey map units with typical values, not samples from your field: a soil test is the only measurement.`}
          </p>
        </>
      ) : (
        <p className="notice">No soil data under this shape.</p>
      )}

      {smRows.length > 0 && (
        <ChartFrame
          title="Surface soil moisture compared with normal"
          lede="Each bar is one month. Orange = clearly drier than usual for that month, blue = clearly wetter, grey = about normal."
          source={`NASA SMAP enhanced L3 (9 km pixel ${sm.cell_id}), top ~5 cm only. One pixel covers many fields and whatever lies between them: it shows whether the area is wet or dry, not the moisture in one field.`}
          legend={[{ label: "Drier than usual", color: SERIES[1], shape: "bar" }, { label: "About normal", color: "#b6c0bc", shape: "bar" }, { label: "Wetter than usual", color: SERIES[0], shape: "bar" }]}
          rows={smRows} columns={[{ key: "date", label: "Month" }, { key: "sm", label: "Soil moisture (m³/m³)", digits: 3 }, { key: "z", label: "Against normal (z)", digits: 2 }, { key: "n_days", label: "Days observed" }]}>
          <ResponsiveContainer width="100%" height={H}>
            <ComposedChart data={smRows} margin={{ top: 8, right: 8, bottom: 0, left: -8 }} barCategoryGap={1}>
              <CartesianGrid stroke={GRID} vertical={false} />
              <XAxis dataKey="date" ticks={yearTicks(smRows)} tickFormatter={yearOf} tick={AXIS} tickLine={false} axisLine={{ stroke: GRID }} />
              <YAxis tick={AXIS} tickLine={false} axisLine={false} width={44} domain={[-3, 3]} ticks={[-2, -1, 0, 1, 2]} />
              <Tooltip cursor={{ fill: "rgba(20,33,30,0.05)" }} content={({ active, payload, label }) => {
                if (!active || !payload?.length) return null;
                const r = payload[0].payload as Dict;
                return <TipBox title={monthLabel(String(label))} rows={[
                  { label: "Against normal", value: r.z != null ? `${r.z > 0 ? "+" : ""}${fmt(r.z, 1)}` : "too few readings", color: zColor(r.z) },
                  { label: "Soil moisture", value: r.sm != null ? `${fmt(r.sm, 3)} m³/m³` : "–" }]} />;
              }} />
              <ReferenceLine y={0} stroke={INK} />
              <Bar dataKey="z" isAnimationActive={false}>
                {smRows.map((r, i) => <Cell key={i} fill={zColor(r.z)} />)}
              </Bar>
            </ComposedChart>
          </ResponsiveContainer>
        </ChartFrame>
      )}
    </>
  );
}

// ---------------------------------------------------------------------------
function HistoryPanel({ ev }: { ev: Dict }) {
  const hist: Dict[] = [...(ev.history ?? [])].reverse();
  if (ev.history_kind === "seasons") {
    const ph = ev.greenness?.phenology ?? {};
    return (
      <div className="explain">
        <h4>How many crops a year, counted from space</h4>
        <p>
          There is no satellite crop map for this area, so the tool does not claim to know <em>what</em> was grown. It counts the rises and falls in greenness instead: each one is a crop season.
          {ph.median_seasons != null ? <> In a typical year this spot shows <strong>{fmt(ph.median_seasons)} green season{ph.median_seasons === 1 ? "" : "s"}</strong>{ph.usual_peak_months?.length ? <>, greenest in {monthList(ph.usual_peak_months)}</> : null}.</> : null}{" "}
          <strong>You know your field: choose your own rotation under “What I grow now”.</strong>
        </p>
        <div className="table-scroll">
          <table className="data-table">
            <thead><tr><th>Year</th><th>Green seasons</th><th>Greenest months</th><th>Peak greenness</th><th>Note</th></tr></thead>
            <tbody>
              {hist.map((h) => (
                <tr key={h.year}>
                  <td>{h.year}</td>
                  <td>{h.label}</td>
                  <td>{h.peak_months?.length ? monthList(h.peak_months) : "–"}</td>
                  <td className="num">{h.peak_ndvi != null ? fmt(h.peak_ndvi, 2) : "–"}</td>
                  <td>{h.note}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        <p className="fine">
          Source: {ph.source ?? "satellite greenness"}. A season is counted when greenness passes 0.40 and stands at least 0.12 above the dips on either side. Cloud in the rainy season can hide a crop, and a short pulse crop on leftover moisture
          may not register. The latest year can be incomplete.
        </p>
      </div>
    );
  }
  return (
    <div className="explain">
      <h4>What the satellite record says grew here</h4>
      <p>
        The USDA crop map is a classification of satellite images, not a record. On irrigated pivots it sometimes reports “shrubland” or “forest”. Landsat greenness is used as a second opinion, and years where the two disagree are marked
        doubtful. <strong>You know your field: where this is wrong, trust your own records.</strong>
      </p>
      <div className="table-scroll">
        <table className="data-table">
          <thead><tr><th>Year</th><th>Crop map says</th><th>Share of field</th><th>Peak greenness</th><th>Treated as</th><th>Note</th></tr></thead>
          <tbody>
            {hist.map((h) => (
              <tr key={h.year} className={h.doubtful ? "row-doubt" : ""}>
                <td>{h.year}</td>
                <td>{h.cdl_name}</td>
                <td className="num">{h.share != null ? `${Math.round(h.share * 100)} %` : "–"}</td>
                <td className="num">{h.peak_ndvi != null ? fmt(h.peak_ndvi, 2) : "–"}</td>
                <td>{h.label}{h.doubtful ? " ?" : ""}</td>
                <td>{h.note}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <p className="fine">Crop map: USDA NASS Cropland Data Layer, 30 m (10 m from 2024). Peak greenness: Landsat 8/9 from 2018; earlier years have no check.</p>
    </div>
  );
}

// ---------------------------------------------------------------------------
function GroundwaterPanel({ ev, imperial }: { ev: Dict; imperial: boolean }) {
  const g = ev.groundwater ?? {};
  const wells: Dict[] = (g.wells ?? []).slice(0, 4);
  const rows = useMemo(() => {
    const byYear: Dict<Dict> = {};
    wells.forEach((w, i) => w.points.forEach((p: Dict) => {
      if (p.year < 1960) return;
      byYear[p.year] = { ...(byYear[p.year] ?? { year: p.year }), [`w${i}`]: p.depth_m };
    }));
    return Object.values(byYear).sort((a, b) => a.year - b.year);
  }, [wells]);

  if (g.kind === "grace") {
    if (!g.available) return <p className="notice">The GRACE water-storage record is not loaded for this region.</p>;
    const m: Dict[] = g.monthly ?? [];
    const v = g.trend_cm_per_year as number;
    return (
      <>
        <ChartFrame
          title="Water stored in and on the ground, compared with its 2004–2009 average (cm of water)"
          lede={<>{g.significant ? <>The line has been <strong>{v < 0 ? "falling" : "rising"} by about {fmt(Math.abs(v), 1)} cm a year</strong> since {g.from_year}</> : <>No clear trend since {g.from_year}</>}. It adds up groundwater, soil moisture and surface water over a very large area.</>}
          source="NASA GRACE and GRACE-FO, JPL mascon solution RL06.3 (0.5 degree grid, true resolution about 300 km). Months between the two missions (2017–18) are missing."
          rows={m} columns={[{ key: "date", label: "Month" }, { key: "lwe_cm", label: "Stored water (cm)", digits: 1 }, { key: "unc_cm", label: "Uncertainty (cm)", digits: 1 }]}>
          <ResponsiveContainer width="100%" height={H + 30}>
            <ComposedChart data={m} margin={{ top: 8, right: 8, bottom: 0, left: -4 }}>
              <CartesianGrid stroke={GRID} vertical={false} />
              <XAxis dataKey="date" ticks={m.filter((r) => String(r.date).endsWith("-01") && Number(yearOf(r.date)) % 4 === 0).map((r) => r.date)} tickFormatter={yearOf} tick={AXIS} tickLine={false} axisLine={{ stroke: GRID }} />
              <YAxis tick={AXIS} tickLine={false} axisLine={false} width={48} />
              <Tooltip cursor={{ stroke: NEUTRAL, strokeDasharray: "3 3" }} content={({ active, payload, label }) =>
                active && payload?.length ? <TipBox title={monthLabel(String(label))} rows={[{ label: "Stored water", value: `${fmt(payload[0].payload.lwe_cm, 1)} cm`, color: SERIES[0] }]} /> : null} />
              <ReferenceLine y={0} stroke={INK} />
              <Line dataKey="lwe_cm" stroke={SERIES[0]} strokeWidth={2} dot={false} isAnimationActive={false} connectNulls={false} />
            </ComposedChart>
          </ResponsiveContainer>
        </ChartFrame>
        <div className="explain">
          <h4>What this can and cannot tell you</h4>
          <p>
            GRACE weighs the Earth: two satellites sense tiny changes in gravity as water moves. It is the only way to see groundwater from space, but each reading covers an area about 300 km across, far larger than a village or a
            district. It shows which way the whole region is heading, not the level in your own tubewell or canal. For that, use your state groundwater department's well records or your own bore.
          </p>
        </div>
      </>
    );
  }

  if (!g.available) return <p className="notice">No USGS wells with a long record within {g.radius_km ?? 12} km of this field.</p>;
  const name = (w: Dict) => `Well ${String(w.site_id).replace("USGS-", "").slice(-6)} · ${fmt(w.dist_km, 1)} km away`;
  return (
    <>
      <ChartFrame
        title="Depth to groundwater in nearby wells (metres below ground)"
        lede={<>Lines going down mean the water table is getting deeper. <strong>{g.n_deepening} of {g.n_wells_trend}</strong> long-record wells within {g.radius_km} km have been deepening since 1990{g.median_m_per_decade != null ? <>, by a median of <strong>{fmt(Math.abs(g.median_m_per_decade), 1)} m</strong>{imperial ? ` (${fmt(Math.abs(g.median_m_per_decade) * 3.281, 0)} ft)` : ""} per decade</> : null}.</>}
        source="USGS National Water Information System, depth-to-water measurements (yearly median; readings taken while pumping are left out). Wells describe the aquifer, not this field's own well."
        legend={wells.map((w, i) => ({ label: name(w), color: SERIES[i] }))}
        rows={rows} columns={[{ key: "year", label: "Year" }, ...wells.map((w, i) => ({ key: `w${i}`, label: `${name(w)} (m)` }))]}>
        <ResponsiveContainer width="100%" height={H + 30}>
          <ComposedChart data={rows} margin={{ top: 8, right: 8, bottom: 0, left: -4 }}>
            <CartesianGrid stroke={GRID} vertical={false} />
            <XAxis dataKey="year" type="number" domain={["dataMin", "dataMax"]} tick={AXIS} tickLine={false} axisLine={{ stroke: GRID }} tickCount={8} />
            <YAxis reversed tick={AXIS} tickLine={false} axisLine={false} width={48} />
            <Tooltip cursor={{ stroke: NEUTRAL, strokeDasharray: "3 3" }} content={({ active, payload, label }) => {
              if (!active || !payload?.length) return null;
              const r = payload[0].payload as Dict;
              return <TipBox title={String(label)} rows={wells.map((w, i) => ({ label: name(w), value: r[`w${i}`] != null ? `${fmt(r[`w${i}`], 1)} m` : "no reading", color: SERIES[i] }))} />;
            }} />
            {wells.map((_, i) => (
              <Line key={i} dataKey={`w${i}`} stroke={SERIES[i]} strokeWidth={2} dot={{ r: 2.5, strokeWidth: 0, fill: SERIES[i] }} activeDot={{ r: 5 }} connectNulls isAnimationActive={false} />
            ))}
          </ComposedChart>
        </ResponsiveContainer>
      </ChartFrame>
      <div className="explain">
        <h4>Why wells here, and not a satellite</h4>
        <p>
          NASA's GRACE satellites weigh changes in stored water, but each reading covers roughly 300 km, far larger than this valley. Wells measure the aquifer directly. This is the clearest example of ground data doing what satellites
          cannot. Diamond Valley is Nevada's first Critical Management Area because pumping has exceeded natural recharge for decades.
        </p>
      </div>
    </>
  );
}

export default function Evidence({ ev, region, panel, onPanel }: { ev: Dict; region: RegionData; panel: string; onPanel: (p: string) => void }) {
  const imperial = Boolean(region.region.imperial);
  return (
    <section className="block evidence" id="evidence">
      <header className="block-head">
        <h2>Evidence for this field</h2>
      </header>
      <div className="tabs" role="tablist" aria-label="Evidence panels">
        {PANELS.map((p) => (
          <button key={p.id} role="tab" aria-selected={panel === p.id} className={panel === p.id ? "on" : ""} onClick={() => onPanel(p.id)}>
            {p.label}
          </button>
        ))}
      </div>
      <div className="tab-body" role="tabpanel" key={panel}>
        {panel === "water" && <WaterPanel ev={ev} imperial={imperial} />}
        {panel === "climate" && <ClimatePanel ev={ev} region={region} />}
        {panel === "cover" && <CoverPanel ev={ev} region={region} />}
        {panel === "soil" && <SoilPanel ev={ev} />}
        {panel === "history" && <HistoryPanel ev={ev} />}
        {panel === "groundwater" && <GroundwaterPanel ev={ev} imperial={imperial} />}
      </div>
    </section>
  );
}
