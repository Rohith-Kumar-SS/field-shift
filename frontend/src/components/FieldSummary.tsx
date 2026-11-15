import { GROUP_COLOR, MONTHS, SEASON_COLOR, doyToDate, fmt, haToAc, mmToIn, monthList, type Dict, type RegionData } from "../data";
import { Num, Stat } from "./ui";

const SOURCE_NAME: Dict<string> = {
  power: "NASA POWER weather",
  ground: "Ground-station correction",
  imerg: "GPM IMERG rainfall",
  smap: "SMAP soil moisture",
  landsat: "Landsat greenness",
  modis: "MODIS 25-year greenness",
  et: "Satellite water use",
  soil: "Soil map",
  history: "Crop history",
  srtm: "SRTM terrain",
  groundwater: "Long-term water record",
};

export default function FieldSummary({ feature, evidence, region, onEvidence, onShowSources }: {
  feature: GeoJSON.Feature; evidence: Dict | null; region: RegionData; onEvidence: (panel: string) => void; onShowSources: () => void;
}) {
  const p = feature.properties as Dict;
  const R = region.region;
  const imperial = Boolean(R.imperial);
  const sources: Dict<boolean> = p.sources ?? {};
  const hist: Dict[] = evidence?.history?.slice(-8) ?? [];
  const seasons = evidence?.history_kind === "seasons";
  const groupOf = (crop: string) => region.kb.crops[crop]?.group ?? "unknown";
  const cs = evidence?.climate?.summary;
  const soil = evidence?.soil;
  const vul: number[] = evidence?.vulnerability?.most_vulnerable ?? [];
  const cal: Dict<Dict> = evidence?.greenness?.calendar ?? {};
  const etRows: Dict[] = (evidence?.water?.et_annual ?? []).filter((r: Dict) => r.year >= 2021 && r.months === 12);
  const et = etRows.length ? etRows.reduce((a, r) => a + (R.has_frost ? r.growing_season_et_mm : r.et_mm), 0) / etRows.length : null;
  const doubtful = hist.filter((h) => h.doubtful).length;
  const ph = evidence?.greenness?.phenology;
  const gw = evidence?.groundwater;
  const slope = evidence?.terrain?.slope_pct_plane;
  const etName = String(evidence?.water?.et_source ?? "satellite").split(" (")[0];

  const soilNote = soil
    ? [soil.om_pct_0_30 != null && `${fmt(soil.om_pct_0_30, 1)} % organic matter`, soil.ph_0_30 != null && `pH ${fmt(soil.ph_0_30, 1)}`,
       soil.ec_dsm_0_30 != null ? `salinity ${fmt(soil.ec_dsm_0_30, 1)} dS/m` : "salinity not mapped"].filter(Boolean).join(" · ")
    : "No soil data under this shape";

  return (
    <section className="block field" key={p.field_id}>
      <header className="block-head">
        <div>
          <p className="eyebrow">{p.is_custom ? "Your drawn field" : R.field_unit === "pivot" ? "Pilot field" : "Sample plot"} · {R.short}</p>
          <h2>{p.name}</h2>
        </div>
        <p className="field-size">
          {imperial ? <>{fmt(haToAc(p.area_ha))} acres <span>({fmt(p.area_ha, 1)} ha)</span></> : <>{fmt(p.area_ha, 1)} ha <span>({fmt(haToAc(p.area_ha), 0)} acres)</span></>}
        </p>
      </header>
      <p className="fine">{p.boundary_source}.</p>
      {evidence?.custom_note && <p className="notice">{evidence.custom_note}</p>}

      <h3 className="sub">{seasons ? "Crop seasons seen from space" : "What grew here (satellite record)"}</h3>
      <ol className="history-strip">
        {hist.map((h, i) => (
          <li key={h.year} className={h.doubtful ? "doubt" : ""} style={{ animationDelay: `${i * 55}ms` }}
            title={h.note || (h.cdl_name ? `${h.cdl_name} on ${Math.round((h.share ?? 0) * 100)} % of the field` : h.label)}>
            <i style={{ background: seasons ? SEASON_COLOR[Math.min(h.n_seasons ?? 0, 3)] : (GROUP_COLOR[groupOf(h.crop)] ?? GROUP_COLOR.unknown) }} />
            <span className="hs-year">{String(h.year).slice(2)}</span>
            <span className="hs-crop">
              {seasons ? (h.n_seasons === 0 ? "none seen" : `${h.n_seasons} crop${h.n_seasons > 1 ? "s" : ""}`) : h.label}
              {h.doubtful ? " ?" : ""}
            </span>
          </li>
        ))}
      </ol>
      <p className="fine">
        {seasons ? (
          <>No crop map exists here, so the tool counts green seasons instead: it can see <em>how many</em> crops, not <em>which</em>. You choose your rotation below.{" "}</>
        ) : (
          <>From the USDA crop map, checked against Landsat greenness. {doubtful > 0 ? <strong>{doubtful} year(s) marked “?” are doubtful. </strong> : null}</>
        )}
        <button className="link-btn" onClick={() => onEvidence("history")}>
          See why
        </button>
      </p>

      <div className="stats">
        <Stat label={R.has_frost ? "Water used, Apr–Oct" : "Water used in a year"} value={et !== null ? <Num value={et} /> : "no record"} unit={et !== null ? "mm" : undefined}
          note={et !== null ? `${imperial ? `${fmt(mmToIn(et), 1)} in · ` : ""}${etName}, 2021–25 average` : "Prepared for the pilot fields only"} />
        {R.has_frost ? (
          <Stat label="Frost-free season" value={cs ? <Num value={cs.frost_free_median} /> : "–"} unit="days"
            note={cs ? `${doyToDate(cs.last_spring_frost_median_doy)} to ${doyToDate(cs.first_fall_frost_median_doy)} in a typical year` : ""} />
        ) : (
          <Stat label="Crop seasons a year" value={ph?.median_seasons != null ? fmt(ph.median_seasons) : "–"}
            note={ph?.usual_peak_months?.length ? `Greenest in ${monthList(ph.usual_peak_months)} · ${ph.n_years} years of ${String(ph.source).split(",")[0]}` : "Not enough clear images"} />
        )}
        <Stat label="Rain in a year" value={cs ? <Num value={cs.precip_annual} /> : "–"} unit="mm"
          note={cs ? `${imperial ? `${fmt(mmToIn(cs.precip_annual), 1)} in · ` : ""}the weather asks for ${fmt(cs.et0_annual)} mm` : ""} />
        <Stat label={cs ? `Days above ${cs.hot_day_c} °C${imperial ? ` (${Math.round(cs.hot_day_c * 1.8 + 32)} °F)` : ""}` : "Hot days"} value={cs ? <Num value={cs.hot_days} /> : "–"} unit="a year" note="1996–2025 average" />
        <Stat label="Soil" value={soil?.surface_texture ?? "–"} note={soilNote} />
        {gw?.kind === "grace" && gw.available ? (
          <Stat label="Water stored below" value={`${gw.trend_cm_per_year > 0 ? "+" : "−"}${fmt(Math.abs(gw.trend_cm_per_year), 1)}`} unit="cm a year"
            note={`${gw.significant ? (gw.trend_cm_per_year < 0 ? "Falling" : "Rising") : "No clear trend"} since ${gw.from_year} · GRACE, a region ~300 km wide`} />
        ) : gw?.kind === "wells" && gw.available ? (
          <Stat label="Nearby wells" value={`${gw.n_deepening} of ${gw.n_wells_trend}`} unit="deepening"
            note={gw.median_m_per_decade != null ? `Median ${fmt(Math.abs(gw.median_m_per_decade), 1)} m a decade since 1990 · USGS` : "USGS long records"} />
        ) : (
          <Stat label="Field tilt" value={slope != null ? fmt(slope, 1) : "–"} unit="%" note={slope != null ? (slope < 1 ? "Nearly flat" : slope < 3 ? "Gentle slope" : "Sloping") : ""} />
        )}
      </div>

      <h3 className="sub">Through the year</h3>
      <div className="calendar" role="img" aria-label="Month by month: when green cover is low and when the crop is most exposed">
        <div className="cal-row cal-head">
          <span />
          {MONTHS.map((m) => (
            <span key={m}>{m[0]}</span>
          ))}
        </div>
        <div className="cal-row">
          <span className="cal-label">Little green cover</span>
          {MONTHS.map((m, i) => {
            const c = cal[String(i + 1)] ?? {};
            const share = c.low_cover_share;
            const snow = (c.snow_share ?? 0) >= 0.5 && share === null;
            return (
              <span key={m} className={`cal-cell ${snow ? "snow" : ""}`} title={snow ? `${m}: usually snow-covered` : share == null ? `${m}: no clear images` : `${m}: low cover in ${Math.round(share * 100)} % of years`}
                style={{ background: snow || share == null ? undefined : `rgba(176, 124, 0, ${0.08 + 0.85 * share})` }}>
                {snow ? "❄" : share != null && share >= 0.5 ? "●" : ""}
              </span>
            );
          })}
        </div>
        <div className="cal-row">
          <span className="cal-label">Wind and rain risk</span>
          {MONTHS.map((m, i) => {
            const risk = (evidence?.bare?.risk_months ?? []).includes(i + 1);
            return (
              <span key={m} className="cal-cell" title={risk ? `${m}: one of the three riskiest months for erosion here` : m} style={{ background: risk ? "rgba(213, 94, 0, 0.75)" : undefined }}>
                {risk ? "▲" : ""}
              </span>
            );
          })}
        </div>
        <div className="cal-row">
          <span className="cal-label">Crop most exposed</span>
          {MONTHS.map((m, i) => {
            const row = (evidence?.vulnerability?.months ?? []).find((r: Dict) => r.month === i + 1);
            const top = vul.includes(i + 1);
            return (
              <span key={m} className="cal-cell" title={row ? `${m}: stress index ${row.index} (heat ${row.heat}, water gap ${row.water_gap})` : `${m}: outside the growing season`}
                style={{ background: row ? `rgba(0, 114, 178, ${0.06 + 0.9 * row.index})` : undefined, color: top ? "#fff" : undefined }}>
                {top ? "◆" : ""}
              </span>
            );
          })}
        </div>
      </div>
      <p className="fine">
        ● little green cover in most years{R.has_frost ? " · ❄ usually under snow" : ""} · ▲ windiest or stormiest months for this soil · ◆ the two months when heat, water demand and greenness dips stack up
        {vul.length ? ` (${vul.map((m) => MONTHS[m - 1]).join(" and ")})` : ""}.{" "}
        <button className="link-btn" onClick={() => onEvidence("cover")}>
          See evidence
        </button>
      </p>

      <h3 className="sub">Data behind this field</h3>
      <ul className="source-chips">
        {Object.keys(SOURCE_NAME).filter((k) => k in sources).map((k) => (
          <li key={k} className={sources[k] ? "ok" : "missing"}>
            <span aria-hidden="true">{sources[k] ? "✓" : "✕"}</span> {SOURCE_NAME[k]}
            {!sources[k] && <em> not available here</em>}
          </li>
        ))}
      </ul>
      <p className="fine">
        All values are real downloads; nothing is simulated.{" "}
        <button className="link-btn" onClick={onShowSources}>
          About the data
        </button>
      </p>
    </section>
  );
}
