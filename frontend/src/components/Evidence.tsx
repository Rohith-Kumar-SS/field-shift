import { useMemo } from "react";
import { Area, Bar, CartesianGrid, Cell, ComposedChart, Line, ReferenceLine, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { MONTHS, SERIES, fmt, mmToIn, type Dict } from "../api";
import { ChartFrame, Stat, TipBox } from "./ui";

export const PANELS: { id: string; label: string }[] = [
  { id: "water", label: "Water" },
  { id: "climate", label: "Weather" },
  { id: "cover", label: "Greenness and cover" },
  { id: "soil", label: "Soil" },
  { id: "history", label: "Crop history" },
  { id: "groundwater", label: "Groundwater" },
];

const AXIS = { fontSize: 12, fill: "#4c5d5a" };
const GRID = "#dfe5e2";
const NEUTRAL = "#8a9793";
const H = 230;

function trendText(t: Dict | undefined, unit: string, digits = 1): string {
  if (!t || t.slope_per_decade === null || t.slope_per_decade === undefined) return "Not enough years for a trend.";
  const s = `${t.slope_per_decade > 0 ? "+" : ""}${fmt(t.slope_per_decade, digits)} ${unit} per decade${t.from_year ? ` since ${t.from_year}` : ""}`;
  if (!t.significant) return `No clear trend (${s}, which could be chance).`;
  return `${t.direction === "increasing" ? "Rising" : "Falling"}: ${s} (unlikely to be chance).`;
}

const yearTicks = (rows: Dict[]) => rows.filter((r) => String(r.date).endsWith("-01")).map((r) => r.date);
const yearOf = (d: string) => String(d).slice(0, 4);
const monthLabel = (d: string) => `${MONTHS[Number(String(d).slice(5, 7)) - 1]} ${yearOf(d)}`;

// ---------------------------------------------------------------------------
function WaterPanel({ ev }: { ev: Dict }) {
  const w = ev.water ?? {};
  const monthly: Dict[] = useMemo(
    () => (w.openet_monthly ?? []).map((r: Dict) => ({ date: r.date, et: r.flagged ? null : r.et, band: r.et_min != null && r.et_max != null && !r.flagged ? [r.et_min, r.et_max] : null, et0: r.et0_power })),
    [w.openet_monthly],
  );
  const normals: Dict[] = (w.monthly_normals ?? []).map((r: Dict) => ({ ...r, name: MONTHS[r.month - 1] }));
  const cal = w.calibration ?? {};
  const cmp: Dict[] = w.source_comparison ?? [];
  const hasOpenet = monthly.length > 0;
  const gap = normals.reduce((a, r) => a + Math.max(r.et0_power - r.precip, 0), 0);

  return (
    <>
      {hasOpenet ? (
        <ChartFrame
          title="Water this field actually used, month by month (mm)"
          lede="The blue line is the satellite estimate of water evaporated and transpired. The band is how far the six OpenET models disagree. The dashed line is how thirsty the weather was."
          source="OpenET ensemble (Landsat, 30 m) and NASA POWER reference ET. Estimates, not meter readings. Repeated winter values are left out."
          legend={[{ label: "Water used (OpenET)", color: SERIES[0] }, { label: "Range of the models", color: SERIES[0], shape: "band" }, { label: "Weather's demand (reference ET)", color: NEUTRAL, shape: "dash" }]}
          rows={w.openet_monthly} columns={[{ key: "date", label: "Month" }, { key: "et", label: "Water used (mm)" }, { key: "et_min", label: "Lowest model" }, { key: "et_max", label: "Highest model" }, { key: "et0_power", label: "Reference ET (mm)" }]}>
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
              <Area dataKey="band" stroke="none" fill={SERIES[0]} fillOpacity={0.16} isAnimationActive={false} connectNulls={false} />
              <Line dataKey="et0" stroke={NEUTRAL} strokeWidth={1.5} strokeDasharray="5 4" dot={false} isAnimationActive={false} />
              <Line dataKey="et" stroke={SERIES[0]} strokeWidth={2} dot={false} isAnimationActive={false} connectNulls={false} />
            </ComposedChart>
          </ResponsiveContainer>
        </ChartFrame>
      ) : (
        <p className="notice">No OpenET record for this field: it was prepared for the pilot fields only. Water figures below are textbook estimates and are marked low confidence.</p>
      )}

      <ChartFrame
        title="A typical year: rain against the weather's thirst (mm a month)"
        lede={<>Over a year the weather asks for about <strong>{fmt(gap)} mm</strong> ({fmt(mmToIn(gap), 0)} in) more water than rain supplies. That gap is what irrigation has to cover.</>}
        source={`Rain: ${ev.climate?.rain_source ?? "NASA POWER"}. Reference ET: NASA POWER, corrected to gridMET. 1996–2025 averages.${hasOpenet ? " Water used: OpenET, 2016–2025." : ""} Reference ET is for mown grass, not your crop.`}
        legend={[{ label: "Rain", color: SERIES[0], shape: "bar" }, { label: "Weather's demand (reference ET)", color: SERIES[3], shape: "bar" }, ...(hasOpenet ? [{ label: "Water this field used", color: SERIES[2], shape: "bar" as const }] : [])]}
        rows={normals} columns={[{ key: "name", label: "Month" }, { key: "precip", label: "Rain (mm)" }, { key: "et0_power", label: "Reference ET (mm)" }, { key: "et_openet", label: "Water used (mm)" }, { key: "balance", label: "Rain minus demand" }]}>
        <ResponsiveContainer width="100%" height={H}>
          <ComposedChart data={normals} margin={{ top: 8, right: 8, bottom: 0, left: -8 }} barGap={2} barCategoryGap="22%">
            <CartesianGrid stroke={GRID} vertical={false} />
            <XAxis dataKey="name" tick={AXIS} tickLine={false} axisLine={{ stroke: GRID }} interval={0} />
            <YAxis tick={AXIS} tickLine={false} axisLine={false} width={44} />
            <Tooltip cursor={{ fill: "rgba(29,42,46,0.05)" }} content={({ active, payload, label }) => {
              if (!active || !payload?.length) return null;
              const r = payload[0].payload as Dict;
              return <TipBox title={String(label)} rows={[
                { label: "Rain", value: `${fmt(r.precip)} mm`, color: SERIES[0] },
                { label: "Reference ET", value: `${fmt(r.et0_power)} mm`, color: SERIES[3] },
                ...(r.et_openet != null ? [{ label: "Water used", value: `${fmt(r.et_openet)} mm`, color: SERIES[2] }] : [])]} />;
            }} />
            <Bar dataKey="precip" fill={SERIES[0]} radius={[4, 4, 0, 0]} isAnimationActive={false} />
            <Bar dataKey="et0_power" fill={SERIES[3]} radius={[4, 4, 0, 0]} isAnimationActive={false} />
            {hasOpenet && <Bar dataKey="et_openet" fill={SERIES[2]} radius={[4, 4, 0, 0]} isAnimationActive={false} />}
          </ComposedChart>
        </ResponsiveContainer>
      </ChartFrame>

      <div className="explain">
        <h4>How the irrigation estimate is anchored to this field</h4>
        {cal.available ? (
          <>
            <p>
              Textbook crop tables give the water a fully irrigated crop <em>could</em> use. In this field's own alfalfa years, OpenET saw it use about{" "}
              <strong>{Math.round(cal.raw_ratio * 100)} %</strong> of that. Every rotation's water figure is scaled by the same factor ({cal.factor}), so the comparison stays fair.
            </p>
            <div className="table-scroll">
              <table className="data-table">
                <thead><tr><th>Alfalfa year</th><th>OpenET, May–Sep (mm)</th><th>Textbook, May–Sep (mm)</th><th>Ratio</th></tr></thead>
                <tbody>{(cal.rows ?? []).map((r: Dict) => <tr key={r.year}><td>{r.year}</td><td className="num">{fmt(r.openet_mm)}</td><td className="num">{fmt(r.textbook_mm)}</td><td className="num">{fmt(r.ratio, 2)}</td></tr>)}</tbody>
              </table>
            </div>
          </>
        ) : (
          <p>{cal.reason ?? "No OpenET record."} The textbook figure is used as it is, which probably overstates real use.</p>
        )}
      </div>

      {cmp.length > 0 && (
        <div className="explain">
          <h4>Two sources, two answers</h4>
          <p>
            NASA POWER is a satellite-and-model product on a ~50 km grid. GPM IMERG is satellite rainfall on a ~10 km grid. gridMET blends weather stations and terrain at 4 km. Where they disagree, that disagreement is the
            uncertainty. “Rain the tool uses” is {ev.climate?.rain_source ?? "NASA POWER"}.
          </p>
          <div className="table-scroll">
            <table className="data-table">
              <thead><tr><th>Year</th><th>Rain the tool uses (mm)</th>{ev.climate?.imerg && <th>Rain, IMERG as downloaded (mm)</th>}<th>Rain, gridMET (mm)</th><th>Reference ET, NASA POWER (mm)</th><th>Reference ET, gridMET (mm)</th></tr></thead>
              <tbody>{cmp.map((r) => <tr key={r.year}><td>{r.year}</td><td className="num">{fmt(r.precip_power)}</td>{ev.climate?.imerg && <td className="num">{fmt(r.precip_imerg_raw)}</td>}<td className="num">{fmt(r.precip_gridmet)}</td><td className="num">{fmt(r.et0_power)}</td><td className="num">{fmt(r.eto_gridmet)}</td></tr>)}</tbody>
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
        <Tooltip cursor={{ fill: "rgba(29,42,46,0.05)" }} content={({ active, payload, label }) =>
          active && payload?.length ? <TipBox title={String(label)} rows={[{ label: unit, value: fmt(payload[0].payload[k], 1), color }]} /> : null} />
        <Bar dataKey={k} fill={color} radius={[3, 3, 0, 0]} isAnimationActive={false} />
        {refs.map((r) => (
          <ReferenceLine key={r.label} y={r.y} stroke="#1d2a2e" strokeDasharray="4 3" label={{ value: r.label, position: "insideTopRight", style: { ...AXIS, fill: "#1d2a2e" } }} />
        ))}
      </ComposedChart>
    </ResponsiveContainer>
  );
}

function ClimatePanel({ ev }: { ev: Dict }) {
  const c = ev.climate ?? {};
  const rows: Dict[] = c.annual ?? [];
  const t = c.trends ?? {};
  const corr = c.correction ?? {};
  const chk = corr.check ?? {};
  const yearCols = (k: string, label: string) => [{ key: "year", label: "Year" }, { key: k, label }];
  const src = `NASA POWER daily record 1991–2025, ${corr.method === "gridmet" ? "corrected month by month to gridMET (4 km)" : "shifted to field elevation"}. A grid value, not a weather station in the field.`;
  return (
    <>
      {corr.method === "gridmet" && chk.frost_free_days_power_raw != null && (
        <div className="explain callout">
          <h4>Why satellite-era weather grids need ground truth</h4>
          <p>
            NASA POWER's grid cell here averages 2,025 m of mountain and valley. On its own it puts the frost-free season at about{" "}
            <strong>{fmt(chk.frost_free_days_power_raw)} days</strong>. Corrected with gridMET, which uses weather stations and terrain, it is about{" "}
            <strong>{fmt(chk.frost_free_days_power_corrected)} days</strong>: nights on the valley floor run about {fmt(Math.abs(chk.mean_tmin_delta_c), 1)} °C colder, because cold air pools there.
            That difference decides whether a frost-tender crop is safe.
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
        <ChartFrame title="Hot days: above 32 °C (90 °F)" lede={trendText(t.days_over_32, "days")} source={src + (chk.days_over_32_gridmet ? ` gridMET's own count rises by ${fmt(chk.days_over_32_gridmet.per_decade, 1)} days per decade.` : "")} rows={rows} columns={yearCols("days_over_32", "Days above 32 °C")}>
          <YearBars rows={rows} k="days_over_32" color={SERIES[1]} unit="Days above 32 °C" />
        </ChartFrame>
        <ChartFrame title="Frost-free season (days)" lede={trendText(t.frost_free_days, "days")} source={src + " The coldest hollows frost earlier and later than this."} rows={rows} columns={yearCols("frost_free_days", "Frost-free days")}>
          <YearBars rows={rows} k="frost_free_days" color={SERIES[2]} unit="Frost-free days" refs={[{ y: 75, label: "teff needs ~75" }]} />
        </ChartFrame>
        <ChartFrame title="Rain and snow by year (mm)" lede={trendText(t.precip, "mm", 0)} source={`${c.rain_source ?? "NASA POWER"}.${c.imerg ? " A ~10 km satellite estimate tied to rain gauges monthly: it can miss small summer storms." : " GPM IMERG satellite rainfall is not loaded yet."}`} rows={rows} columns={[...yearCols("precip", "Rain (mm)"), { key: "heavy_rain_days", label: "Days with 10 mm or more" }]}>
          <YearBars rows={rows} k="precip" color={SERIES[0]} unit="Rain (mm)" />
        </ChartFrame>
      </div>
      <p className="fine">Heavy-rain days (10 mm or more in a day): {trendText(t.heavy_rain_days, "days", 2).toLowerCase()} Yearly water balance (rain minus reference ET): {trendText(t.water_balance, "mm", 0).toLowerCase()}</p>
    </>
  );
}

// ---------------------------------------------------------------------------
function CoverPanel({ ev }: { ev: Dict }) {
  const g = ev.greenness ?? {};
  const monthly: Dict[] = g.monthly ?? [];
  const modis: Dict[] = g.modis_peak ?? [];
  const vul: Dict[] = ev.vulnerability?.months ?? [];
  const bare: number[] = ev.bare?.months_usually_low_cover ?? [];
  return (
    <>
      <ChartFrame
        title="How green the field was, month by month"
        lede={<>Below the dashed line there is little green cover. {bare.length ? <>That is usual here in <strong>{bare.map((m) => MONTHS[m - 1]).join(", ")}</strong>.</> : "No month is usually below it."} Sharp summer dips are hay cuts.</>}
        source="Landsat 8/9 NDVI (USGS/NASA), 30 m, clear and snow-free observations averaged by month. Brown does not always mean bare: dormant alfalfa and stubble still protect the soil."
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
            <ReferenceLine y={0.25} stroke="#1d2a2e" strokeDasharray="4 3" label={{ value: "little green cover", position: "insideBottomRight", style: { ...AXIS, fill: "#1d2a2e" } }} />
            <Line dataKey="ndvi" stroke={SERIES[2]} strokeWidth={2} dot={false} isAnimationActive={false} connectNulls={false} />
          </ComposedChart>
        </ResponsiveContainer>
      </ChartFrame>

      {modis.length > 0 ? (
        <ChartFrame title="Peak summer greenness over 25 years" lede={trendText(g.modis_trend, "NDVI", 3)}
          source="MODIS/Terra MOD13Q1 (NASA), 250 m, highest June–September value each year. A pivot holds only ~9 MODIS pixels and its edges mix in desert, so this reads lower than Landsat."
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

      <div className="explain">
        <h4>When the crop looks most exposed</h4>
        <p>{ev.vulnerability?.method}</p>
        <div className="table-scroll">
          <table className="data-table">
            <thead><tr><th>Month</th><th>Heat</th><th>Frost</th><th>Water gap</th><th>Greenness dips</th><th>Dry soil</th><th>Combined</th></tr></thead>
            <tbody>
              {vul.map((r) => (
                <tr key={r.month} className={(ev.vulnerability?.most_vulnerable ?? []).includes(r.month) ? "row-hi" : ""}>
                  <td>{MONTHS[r.month - 1]}</td>
                  {["heat", "frost", "water_gap", "greenness_dips", "dry_soil"].map((k) => <td key={k} className="num">{r[k] == null ? "–" : fmt(r[k], 2)}</td>)}
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
  let units: Dict[] = [];
  try {
    units = s?.mapunits ? (typeof s.mapunits === "string" ? JSON.parse(s.mapunits) : s.mapunits) : [];
  } catch {
    units = [];
  }
  // diverging: two hues with a neutral middle
  const zColor = (z: number | null) => (z == null ? "#d5dbd8" : z <= -0.5 ? SERIES[1] : z >= 0.5 ? SERIES[0] : "#b6c0bc");
  return (
    <>
      {s ? (
        <>
          <div className="stats">
            <Stat label="Surface texture" value={s.surface_texture ?? "–"} note={s.muname} />
            <Stat label="Organic matter" value={fmt(s.om_pct_0_30, 1)} unit="%" note={s.om_pct_0_30 < 1.5 ? "Low: typical of desert soils, room to build" : "Top 30 cm"} />
            <Stat label="Salinity (EC)" value={fmt(s.ec_dsm_0_30, 1)} unit="dS/m" note={s.ec_dsm_0_30 >= 2 ? "Above 2: alfalfa starts losing yield" : "Below the level that hurts alfalfa"} />
            <Stat label="pH" value={fmt(s.ph_0_30, 1)} note={s.ph_0_30 >= 8.5 ? "Strongly alkaline" : s.ph_0_30 >= 7.9 ? "Moderately alkaline" : "Near neutral"} />
            <Stat label="Wind erodibility" value={`Group ${s.wind_erodibility_group ?? "–"}`} note={`Index ${fmt(s.wind_erodibility_index)} t/ac/yr: ${s.wind_erodibility_index >= 134 ? "blows easily" : s.wind_erodibility_index >= 86 ? "moderate" : "resists wind"}`} />
            <Stat label="Water it can hold" value={fmt(s.aws_0_100cm_cm * 10)} unit="mm" note="Available to plants in the top metre" />
            <Stat label="Drainage" value={s.drainage_class ?? "–"} note={`Hydrologic group ${s.hydrologic_group ?? "–"}`} />
            <Stat label="Clay / sand" value={`${fmt(s.clay_pct_0_30)} / ${fmt(s.sand_pct_0_30)}`} unit="%" note="Top 30 cm" />
          </div>
          {units.length > 0 && (
            <p className="fine">
              Soil map units under the field: {units.map((u) => `${u.name} (${Math.round(u.share * 100)} %)`).join("; ")}. Source: USDA NRCS SSURGO. These are survey map units with typical values, not samples from your field: a
              soil test is the only measurement.
            </p>
          )}
        </>
      ) : (
        <p className="notice">No soil survey data under this shape.</p>
      )}

      {smRows.length > 0 && (
        <ChartFrame
          title="Surface soil moisture compared with normal"
          lede="Each bar is one month. Orange = clearly drier than usual for that month, blue = clearly wetter, grey = about normal."
          source={`NASA SMAP enhanced L3 (9 km pixel ${sm.cell_id}), top ~5 cm only. The pixel is mostly desert with the pivots mixed in: it shows whether the valley is wet or dry, not the moisture under one pivot.`}
          legend={[{ label: "Drier than usual", color: SERIES[1], shape: "bar" }, { label: "About normal", color: "#b6c0bc", shape: "bar" }, { label: "Wetter than usual", color: SERIES[0], shape: "bar" }]}
          rows={smRows} columns={[{ key: "date", label: "Month" }, { key: "sm", label: "Soil moisture (m³/m³)", digits: 3 }, { key: "z", label: "Against normal (z)", digits: 2 }, { key: "n_days", label: "Days observed" }]}>
          <ResponsiveContainer width="100%" height={H}>
            <ComposedChart data={smRows} margin={{ top: 8, right: 8, bottom: 0, left: -8 }} barCategoryGap={1}>
              <CartesianGrid stroke={GRID} vertical={false} />
              <XAxis dataKey="date" ticks={yearTicks(smRows)} tickFormatter={yearOf} tick={AXIS} tickLine={false} axisLine={{ stroke: GRID }} />
              <YAxis tick={AXIS} tickLine={false} axisLine={false} width={44} domain={[-3, 3]} ticks={[-2, -1, 0, 1, 2]} />
              <Tooltip cursor={{ fill: "rgba(29,42,46,0.05)" }} content={({ active, payload, label }) => {
                if (!active || !payload?.length) return null;
                const r = payload[0].payload as Dict;
                return <TipBox title={monthLabel(String(label))} rows={[
                  { label: "Against normal", value: r.z != null ? `${r.z > 0 ? "+" : ""}${fmt(r.z, 1)}` : "too few readings", color: zColor(r.z) },
                  { label: "Soil moisture", value: r.sm != null ? `${fmt(r.sm, 3)} m³/m³` : "–" }]} />;
              }} />
              <ReferenceLine y={0} stroke="#1d2a2e" />
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
function GroundwaterPanel({ ev }: { ev: Dict }) {
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
  if (!g.available) return <p className="notice">No USGS wells with a long record within {g.radius_km ?? 12} km of this field.</p>;
  const name = (w: Dict) => `Well ${String(w.site_id).replace("USGS-", "").slice(-6)} · ${fmt(w.dist_km, 1)} km away`;
  return (
    <>
      <ChartFrame
        title="Depth to groundwater in nearby wells (metres below ground)"
        lede={<>Lines going down mean the water table is getting deeper. <strong>{g.n_deepening} of {g.n_wells_trend}</strong> long-record wells within {g.radius_km} km have been deepening since 1990{g.median_m_per_decade != null ? <>, by a median of <strong>{fmt(Math.abs(g.median_m_per_decade), 1)} m</strong> ({fmt(Math.abs(g.median_m_per_decade) * 3.281, 0)} ft) per decade</> : null}.</>}
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
        <h4>Why this is here instead of a satellite</h4>
        <p>
          NASA's GRACE satellites weigh changes in stored water, but each reading covers roughly 300 km, far larger than this valley. Wells measure the aquifer directly. This is the clearest example of ground data doing what satellites
          cannot. Diamond Valley is Nevada's first Critical Management Area because pumping has exceeded natural recharge for decades.
        </p>
      </div>
    </>
  );
}

export default function Evidence({ ev, panel, onPanel }: { ev: Dict; panel: string; onPanel: (p: string) => void }) {
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
      <div className="tab-body" role="tabpanel">
        {panel === "water" && <WaterPanel ev={ev} />}
        {panel === "climate" && <ClimatePanel ev={ev} />}
        {panel === "cover" && <CoverPanel ev={ev} />}
        {panel === "soil" && <SoilPanel ev={ev} />}
        {panel === "history" && <HistoryPanel ev={ev} />}
        {panel === "groundwater" && <GroundwaterPanel ev={ev} />}
      </div>
    </section>
  );
}
