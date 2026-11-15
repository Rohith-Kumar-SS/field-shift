import { fmt, MONTHS, SERIES, type RegionInfo } from "../data";
import { RotationRing, type RingYear } from "./ui";

// The two rings in the hero are real rotations from the Punjab knowledge base, drawn with the
// same component the comparison uses: the usual rice-wheat year, and maize-wheat-moong.
const NOW: RingYear[] = [{ year: 1, label: "Rice + wheat", entries: [
  { crop: "wheat", label: "Wheat", group: "cool-season cereal", months: [1, 2, 3, 4, 11, 12] },
  { crop: "rice", label: "Rice", group: "flooded rice", months: [6, 7, 8, 9, 10] }] }];
const OPTION: RingYear[] = [{ year: 1, label: "Maize + wheat + moong", entries: [
  { crop: "wheat", label: "Wheat", group: "cool-season cereal", months: [1, 2, 3, 4, 11, 12] },
  { crop: "moong", label: "Summer moong", group: "legume", months: [4, 5, 6] },
  { crop: "maize", label: "Maize", group: "warm-season cereal", months: [6, 7, 8, 9, 10] }] }];

/** Twelve bars of rain against the weather's thirst: each region's water year at a glance. */
function WaterYear({ rain, et0 }: { rain: number[]; et0: number[] }) {
  const W = 264, H = 84, top = Math.max(...rain, ...et0, 1);
  const bw = W / 12;
  const y = (v: number) => H - (v / top) * (H - 6);
  const line = et0.map((v, i) => `${i === 0 ? "M" : "L"} ${(i * bw + bw / 2).toFixed(1)} ${y(v).toFixed(1)}`).join(" ");
  return (
    <svg className="wy" viewBox={`0 0 ${W} ${H + 16}`} role="img"
      aria-label={`Rain by month against the weather's demand. Wettest month ${MONTHS[rain.indexOf(Math.max(...rain))]}.`}>
      {rain.map((v, i) => (
        <rect key={i} className="wy-bar" x={i * bw + 3} width={bw - 6} y={y(v)} height={H - y(v)} rx={3} style={{ animationDelay: `${i * 35}ms` }}>
          <title>{`${MONTHS[i]}: ${fmt(v)} mm of rain, weather asks for ${fmt(et0[i])} mm`}</title>
        </rect>
      ))}
      <path className="wy-line" d={line} pathLength={1} />
      {MONTHS.map((m, i) => (
        <text key={m} x={i * bw + bw / 2} y={H + 13} textAnchor="middle" className="wy-tick">
          {m[0]}
        </text>
      ))}
    </svg>
  );
}

function waterTrend(gw: Record<string, any> | undefined): { value: string; note: string } {
  if (gw?.kind === "wells" && gw.n_wells_trend) {
    return { value: `${gw.n_deepening} of ${gw.n_wells_trend} wells`, note: `getting deeper, ${fmt(Math.abs(gw.median_m_per_decade), 1)} m a decade` };
  }
  if (gw?.kind === "grace" && gw.trend_cm_per_year != null) {
    const v = gw.trend_cm_per_year as number;
    return { value: `${v > 0 ? "+" : "−"}${fmt(Math.abs(v), 1)} cm a year`, note: `stored water, ${v < 0 ? "falling" : "rising"} since ${gw.from_year} (GRACE)` };
  }
  return { value: "–", note: "no long-term water record" };
}

export default function Landing({ regions, onOpen, onHelp }: { regions: RegionInfo[]; onOpen: (id: string) => void; onHelp: (m: "glossary" | "method") => void }) {
  return (
    <main className="landing">
      <section className="hero">
        <div className="hero-furrows" aria-hidden="true" />
        <div className="hero-inner">
          <div className="hero-copy">
            <p className="eyebrow eyebrow-light">NASA Space Apps 2026 · Field Shift</p>
            <h1>
              Same field.
              <br />A different rotation.
            </h1>
            <p className="hero-lede">
              Field Shift lines up thirty years of NASA weather, satellite greenness, soil and water records for one field, then shows how different crop rotations would treat it under the priorities you set.
            </p>
            <p className="hero-promise">It compares options. It never tells you what to plant.</p>
            <div className="hero-actions">
              <a className="btn btn-sun" href="#regions">
                Choose a region
              </a>
              <button className="btn btn-ghost" onClick={() => onHelp("method")}>
                How the scores work
              </button>
            </div>
          </div>
          <figure className="hero-rings" aria-label="Two rotations for the same Punjab field, each drawn as one year seen from above">
            <div className="hero-ring">
              <RotationRing sequence={NOW} size={196} stroke={22} arm />
              <figcaption>
                <strong>Rice, then wheat</strong>
                <span>bare in May, about 1,650 mm of irrigation</span>
              </figcaption>
            </div>
            <div className="hero-ring">
              <RotationRing sequence={OPTION} size={196} stroke={22} arm />
              <figcaption>
                <strong>Maize, wheat, summer moong</strong>
                <span>covered all year, about 1,000 mm</span>
              </figcaption>
            </div>
            <p className="hero-rings-key">One lap of a ring is one year. Colour is a crop holding the ground; pale gaps are bare soil. Figures: sample plot 3, Sangrur.</p>
          </figure>
        </div>
      </section>

      <section className="regions" id="regions">
        <header className="section-head">
          <h2>Where do you farm?</h2>
          <p>Three pilot areas are ready. Each box is about 13 km across, with every source downloaded and checked for it.</p>
        </header>
        <div className="region-grid">
          {regions.map((r, i) => {
            const t = waterTrend(r.stats.groundwater);
            return (
              <article className="region-card" key={r.id} style={{ animationDelay: `${120 + i * 90}ms` }}>
                <p className="eyebrow">{r.country}</p>
                <h3>{r.short}</h3>
                <p className="region-tag">{r.tagline}.</p>
                <WaterYear rain={r.stats.precip_month} et0={r.stats.et0_month} />
                <p className="wy-key">
                  <i className="k-bar" style={{ background: SERIES[0] }} /> rain by month <i className="k-line" /> what the weather asks for
                </p>
                <dl className="region-stats">
                  <div>
                    <dt>Rain</dt>
                    <dd>{fmt(r.stats.precip_annual)} mm</dd>
                  </div>
                  <div>
                    <dt>Weather's demand</dt>
                    <dd>{fmt(r.stats.et0_annual)} mm</dd>
                  </div>
                  <div className="wide">
                    <dt>Long-term water</dt>
                    <dd>
                      {t.value} <span>{t.note}</span>
                    </dd>
                  </div>
                </dl>
                <button className="btn btn-primary region-open" onClick={() => onOpen(r.id)}>
                  Open {r.short.split(",")[0]} <span aria-hidden="true">→</span>
                </button>
                <p className="fine">{r.n_fields} {r.field_unit === "pivot" ? "centre-pivot fields" : "sample plots"} ready, or draw your own.</p>
              </article>
            );
          })}
        </div>
      </section>

      <section className="how">
        <header className="section-head">
          <h2>How it works</h2>
        </header>
        <ol className="how-steps">
          <li>
            <h3>Pick a field</h3>
            <p>Tap a field on the satellite map, or draw your own. You see what grew there, its soil, its weather and how its water has changed.</p>
          </li>
          <li>
            <h3>Say what matters</h3>
            <p>Slide your priorities: water, soil cover, nitrogen, pests, income, heat. Set the water, equipment and buyers you can count on.</p>
          </li>
          <li>
            <h3>Compare rotations</h3>
            <p>Your current rotation and four others are scored side by side. They re-rank as you move a slider, and every score opens to its numbers and sources.</p>
          </li>
          <li>
            <h3>Check before acting</h3>
            <p>Each rotation lists its risks, what the tool cannot see, and what to verify with a local expert.</p>
          </li>
        </ol>
        <p className="how-foot">
          Data: NASA POWER, GPM IMERG, SMAP, Landsat, MODIS, SRTM and GRACE, with USDA, USGS, OpenET, gridMET, India Meteorological Department, ISRIC SoilGrids, FAO WaPOR and ESA WorldCover on the ground side.{" "}
          <button className="link-btn" onClick={() => onHelp("glossary")}>
            Plain-language guide
          </button>
        </p>
      </section>
    </main>
  );
}
