import { GROUP_COLOR, MONTHS, doyToDate, fmt, haToAc, mmToIn, type Dict, type Meta } from "../api";
import { Stat } from "./ui";

const SOURCE_NAME: Dict<string> = {
  power: "NASA POWER weather",
  gridmet: "gridMET correction",
  imerg: "GPM IMERG rainfall",
  smap: "SMAP soil moisture",
  landsat: "Landsat greenness",
  modis: "MODIS 25-year greenness",
  openet: "OpenET water use",
  ssurgo: "SSURGO soils",
  cdl: "USDA crop map",
  srtm: "SRTM terrain",
  groundwater: "USGS wells",
};

export default function FieldSummary({ feature, evidence, meta, onEvidence, onShowSources }: {
  feature: GeoJSON.Feature; evidence: Dict | null; meta: Meta; onEvidence: (panel: string) => void; onShowSources: () => void;
}) {
  const p = feature.properties as Dict;
  const sources: Dict<boolean> = p.sources ?? {};
  const hist: Dict[] = evidence?.history?.slice(-8) ?? [];
  const groupOf = (crop: string) => meta.crops.find((c) => c.id === crop)?.group ?? "unknown";
  const cs = evidence?.climate?.summary;
  const soil = evidence?.soil;
  const vul: number[] = evidence?.vulnerability?.most_vulnerable ?? [];
  const cal: Dict<Dict> = evidence?.greenness?.calendar ?? {};
  const openet: Dict[] = evidence?.water?.openet_annual ?? [];
  const recent = openet.filter((r) => r.year >= 2021);
  const et = recent.length ? recent.reduce((a, r) => a + r.growing_season_et_mm, 0) / recent.length : null;
  const doubtful = hist.filter((h) => h.doubtful).length;

  return (
    <section className="block field">
      <header className="block-head">
        <div>
          <p className="eyebrow">{p.is_custom ? "Your drawn field" : "Pilot field"}</p>
          <h2>{p.name}</h2>
        </div>
        <p className="field-size">
          {fmt(haToAc(p.area_ha))} acres <span>({fmt(p.area_ha, 1)} ha)</span>
        </p>
      </header>
      <p className="fine">{p.boundary_source}.</p>
      {evidence?.custom_note && <p className="notice">{evidence.custom_note}</p>}

      <h3 className="sub">What grew here (satellite record)</h3>
      <ol className="history-strip">
        {hist.map((h) => (
          <li key={h.year} className={h.doubtful ? "doubt" : ""} title={h.note || `${h.cdl_name} on ${Math.round((h.share ?? 0) * 100)} % of the field`}>
            <i style={{ background: GROUP_COLOR[groupOf(h.crop)] ?? GROUP_COLOR.unknown }} />
            <span className="hs-year">{String(h.year).slice(2)}</span>
            <span className="hs-crop">
              {h.label}
              {h.doubtful ? " ?" : ""}
            </span>
          </li>
        ))}
      </ol>
      <p className="fine">
        From the USDA crop map, checked against Landsat greenness.{" "}
        {doubtful > 0 ? (
          <>
            <strong>{doubtful} year(s) marked “?” are doubtful.</strong>{" "}
          </>
        ) : null}
        <button className="link-btn" onClick={() => onEvidence("history")}>
          See why
        </button>
      </p>

      <div className="stats">
        <Stat label="Water used, Apr–Oct" value={et !== null ? fmt(et) : "no record"} unit={et !== null ? "mm" : undefined}
          note={et !== null ? `${fmt(mmToIn(et), 1)} in · OpenET, 2021–25 average` : "OpenET is prepared for pilot fields only"} />
        <Stat label="Frost-free season" value={cs ? fmt(cs.frost_free_median) : "–"} unit="days"
          note={cs ? `${doyToDate(cs.last_spring_frost_median_doy)} to ${doyToDate(cs.first_fall_frost_median_doy)} in a typical year` : ""} />
        <Stat label="Rain in a year" value={cs ? fmt(cs.precip_annual) : "–"} unit="mm"
          note={cs ? `${fmt(mmToIn(cs.precip_annual), 1)} in · the weather asks for ${fmt(cs.et0_annual)} mm` : ""} />
        <Stat label="Days above 32 °C (90 °F)" value={cs ? fmt(cs.hot_days_32) : "–"} unit="a year" note="1996–2025 average" />
        <Stat label="Soil" value={soil?.surface_texture ?? "–"}
          note={soil ? `${fmt(soil.om_pct_0_30, 1)} % organic matter · pH ${fmt(soil.ph_0_30, 1)} · salinity ${fmt(soil.ec_dsm_0_30, 1)} dS/m` : "No soil survey data"} />
        <Stat label="Field tilt" value={evidence?.terrain ? fmt(evidence.terrain.slope_pct_plane, 1) : "–"} unit="%"
          note={evidence?.terrain ? `${evidence.terrain.slope_pct_plane < 1 ? "Nearly flat" : evidence.terrain.slope_pct_plane < 3 ? "Gentle slope" : "Sloping"} · ${fmt(evidence.terrain.elevation_m)} m (${fmt(evidence.terrain.elevation_m * 3.281)} ft)` : ""} />
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
        ● little green cover in most years · ❄ usually under snow · ▲ windiest or stormiest months for this soil · ◆ the two months when heat, water demand and
        greenness dips stack up{vul.length ? ` (${vul.map((m) => MONTHS[m - 1]).join(" and ")})` : ""}.{" "}
        <button className="link-btn" onClick={() => onEvidence("cover")}>
          See evidence
        </button>
      </p>

      <h3 className="sub">Data behind this field</h3>
      <ul className="source-chips">
        {Object.keys(SOURCE_NAME).map((k) => (
          <li key={k} className={sources[k] ? "ok" : "missing"}>
            <span aria-hidden="true">{sources[k] ? "✓" : "✕"}</span> {SOURCE_NAME[k]}
            {!sources[k] && <em> not loaded</em>}
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
