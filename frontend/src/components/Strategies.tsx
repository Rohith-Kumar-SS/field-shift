import { useState } from "react";
import { GROUP_COLOR, fmt, groupLegend, mm, type Dict, type RegionData } from "../data";
import { useFlip } from "../motion";
import { Confidence, Num, RotationRing } from "./ui";

const PANEL_NAME: Record<string, string> = {
  water: "Water",
  climate: "Weather",
  cover: "Greenness and cover",
  soil: "Soil",
  history: "Crop history",
  groundwater: "Long-term water",
};

type Criteria = { id: string; label: string }[];

function RingLegend({ strategies, region }: { strategies: Dict[]; region: RegionData }) {
  const groups = Array.from(new Set<string>(strategies.flatMap((s) => s.sequence.flatMap((y: Dict) => y.entries.map((e: Dict) => e.group)))));
  return (
    <div className="ring-legend">
      <span className="ring-legend-how">One lap of a ring = the whole rotation. Pale gaps = stubble or bare soil.</span>
      <ul>
        {groupLegend(region.kb, groups).map((g) => (
          <li key={g.group}>
            <i style={{ background: g.color }} />
            {g.label}
          </li>
        ))}
      </ul>
    </div>
  );
}

function ScoreBars({ s, criteria, weights }: { s: Dict; criteria: Criteria; weights: Record<string, number> }) {
  const shown = criteria.filter((c) => (weights[c.id] ?? 0) > 0.0005).sort((a, b) => (weights[b.id] ?? 0) - (weights[a.id] ?? 0));
  return (
    <ul className="bars" aria-label="Score on each of your priorities">
      {shown.map((c) => {
        const d = s.criteria[c.id];
        return (
          <li key={c.id} title={`${d.headline}. Counts for ${Math.round(d.weight * 100)} % of the total.`}>
            <span className="bars-label">{c.label}</span>
            <span className="bars-track">
              <span className="bars-fill" style={{ width: `${Math.max(d.score * 100, 1.5)}%` }} />
            </span>
            <span className="bars-val">{Math.round(d.score * 100)}</span>
          </li>
        );
      })}
    </ul>
  );
}

function CriterionRow({ c, s, onEvidence }: { c: { id: string; label: string }; s: Dict; onEvidence: (panel: string) => void }) {
  const [open, setOpen] = useState(false);
  const d = s.criteria[c.id];
  return (
    <li className="crit">
      <button className="crit-head" onClick={() => setOpen((v) => !v)} aria-expanded={open}>
        <span className="crit-name">{c.label}</span>
        <span className="crit-headline">{d.headline}</span>
        <span className="crit-score">{Math.round(d.score * 100)}</span>
        <span className="chev" aria-hidden="true">{open ? "−" : "+"}</span>
      </button>
      {open && (
        <div className="crit-body">
          <p className="crit-formula">
            <strong>How it is worked out:</strong> {d.formula}
          </p>
          <div className="table-scroll">
            <table className="data-table">
              <thead>
                <tr>
                  <th>What went in</th>
                  <th>Value</th>
                  <th>Where it comes from</th>
                </tr>
              </thead>
              <tbody>
                {d.inputs.map((i: Dict) => (
                  <tr key={i.label}>
                    <td>{i.label}</td>
                    <td className="num">
                      {i.value === null || i.value === undefined ? "not available" : typeof i.value === "number" ? fmt(i.value, Number.isInteger(i.value) ? 0 : 2) : String(i.value)} {i.unit}
                    </td>
                    <td>{i.source}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <p className="crit-note">
            <Confidence level={d.confidence} /> {d.note}
          </p>
          <p className="crit-foot">
            Counts for {Math.round(d.weight * 100)} % of the total under your priorities.{" "}
            <button className="link-btn" onClick={() => onEvidence(d.panel)}>
              See the {PANEL_NAME[d.panel]?.toLowerCase() ?? d.panel} evidence
            </button>
          </p>
        </div>
      )}
    </li>
  );
}

function StrategyCard({ s, result, criteria, imperial, open, onToggle, onEvidence, flipRef }: {
  s: Dict; result: Dict; criteria: Criteria; imperial: boolean; open: boolean; onToggle: () => void; onEvidence: (panel: string) => void; flipRef: (el: HTMLElement | null) => void;
}) {
  const existing = result.strategies.find((x: Dict) => x.is_existing)!;
  const diff = s.water.irrigation_mm - existing.water.irrigation_mm;
  const [checked, setChecked] = useState<Record<number, boolean>>({});
  const n = s.sequence.length;
  return (
    <article ref={flipRef} className={`strategy ${s.rank === 1 ? "is-top" : ""} ${s.is_existing ? "is-existing" : ""}`}>
      <div className="strategy-main">
        <div className="strategy-ring">
          <RotationRing sequence={s.sequence} score={s.total} />
          <div className="ring-caption">{n === 1 ? "every year" : `${n}-year cycle`}</div>
        </div>
        <div className="strategy-text">
          <div className="strategy-tags">
            <span className="rank">{s.rank === 1 ? "Scores highest" : `Ranks ${s.rank} of ${result.strategies.length}`}</span>
            {s.is_existing && <span className="tag-existing">What you do now</span>}
            <Confidence level={s.confidence.level} />
          </div>
          <h3>{s.name}</h3>
          <p className="strategy-summary">{s.summary}</p>
          <p className="strategy-water">
            Irrigation need about{" "}
            <strong>
              <Num value={s.water.irrigation_mm} /> mm
            </strong>
            {imperial ? ` (${fmt(s.water.irrigation_mm / 25.4, 1)} in)` : ""} a year
            {!s.is_existing && Math.abs(diff) >= 5 && (
              <>
                {" "}
                · <strong>{fmt(Math.abs(diff))} mm {diff < 0 ? "less" : "more"}</strong> than now
              </>
            )}
            {s.water.extra_pumping_mm > 0 && <span className="water-split"> · {fmt(s.water.extra_pumping_mm)} mm of it keeps paddy flooded</span>}
          </p>
          <ScoreBars s={s} criteria={criteria} weights={result.weights} />
        </div>
      </div>
      <button className="btn btn-quiet strategy-toggle" onClick={onToggle} aria-expanded={open}>
        {open ? "Hide the reasons" : "Why, benefits, risks and what to check"}
      </button>

      {open && (
        <div className="strategy-detail">
          <section>
            <h4>{s.is_existing ? "Why it is shown" : "Why it was suggested for this field"}</h4>
            <ul className="why">
              {s.why.map((w: Dict, i: number) => (
                <li key={i}>
                  {w.text}{" "}
                  <button className="link-btn" onClick={() => onEvidence(w.panel)}>
                    See evidence: {PANEL_NAME[w.panel] ?? w.panel}
                  </button>
                </li>
              ))}
            </ul>
            {s.assumptions?.map((a: string) => (
              <p className="assumption" key={a}>
                Assumption: {a}
              </p>
            ))}
          </section>

          <section>
            <h4>Year by year</h4>
            <ol className="seq">
              {s.sequence.map((y: Dict) => (
                <li key={y.year}>
                  <span className="seq-year">{y.calendar_year ?? (n === 1 ? "Every year" : `Year ${y.year}`)}</span>
                  <span className="seq-crops">
                    {y.entries
                      .filter((e: Dict, i: number, arr: Dict[]) => arr.findIndex((x) => x.crop === e.crop) === i)
                      .map((e: Dict) => (
                        <span className="seq-crop" key={e.crop}>
                          <i style={{ background: GROUP_COLOR[e.group] ?? GROUP_COLOR.unknown }} />
                          {e.label}
                        </span>
                      ))}
                  </span>
                  <span className="seq-water">{fmt(s.water.by_year[y.year - 1]?.irrigation_mm)} mm</span>
                </li>
              ))}
            </ol>
            <p className="fine">Right-hand figures: estimated irrigation need in that year.</p>
          </section>

          <div className="two-col">
            <section>
              <h4>What it may offer</h4>
              <ul className="plain">
                {s.benefits.map((b: string) => (
                  <li key={b}>{b}</li>
                ))}
              </ul>
            </section>
            <section>
              <h4>Risks to review locally</h4>
              <ul className="plain risks">
                {s.risks.map((b: string) => (
                  <li key={b}>{b}</li>
                ))}
              </ul>
            </section>
          </div>

          <section>
            <h4>What this tool does not know</h4>
            <ul className="plain gaps">
              {s.info_gaps.map((b: string) => (
                <li key={b}>{b}</li>
              ))}
            </ul>
          </section>

          <section className="verify">
            <h4>Check with a local expert before acting</h4>
            <ul>
              {s.verify.map((v: string, i: number) => (
                <li key={v}>
                  <label>
                    <input type="checkbox" checked={!!checked[i]} onChange={(e) => setChecked({ ...checked, [i]: e.target.checked })} />
                    <span>{v}</span>
                  </label>
                </li>
              ))}
            </ul>
          </section>

          <section>
            <h4>Where each score comes from</h4>
            <ul className="crits">
              {criteria.map((c) => (
                <CriterionRow key={c.id} c={c} s={s} onEvidence={onEvidence} />
              ))}
            </ul>
          </section>

          <section className="conf-box">
            <h4>
              Data confidence: <Confidence level={s.confidence.level} />
            </h4>
            <ul className="plain">
              {s.confidence.reasons.map((r: string) => (
                <li key={r}>{r}</li>
              ))}
            </ul>
          </section>
        </div>
      )}
    </article>
  );
}

function CompareTable({ result, criteria }: { result: Dict; criteria: Criteria }) {
  const strategies: Dict[] = result.strategies;
  return (
    <div className="table-scroll">
      <table className="compare">
        <thead>
          <tr>
            <th scope="col">Your priority</th>
            {strategies.map((s) => (
              <th key={s.id} scope="col">
                {s.short}
                {s.is_existing && <span className="weight">now</span>}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {criteria.map((c) => {
            const best = Math.max(...strategies.map((s) => s.scores[c.id]));
            return (
              <tr key={c.id}>
                <th scope="row">
                  {c.label}
                  <span className="weight">{Math.round((result.weights[c.id] ?? 0) * 100)} %</span>
                </th>
                {strategies.map((s) => {
                  const v = s.scores[c.id];
                  const top = Math.abs(v - best) < 0.005;
                  return (
                    <td key={s.id} className={top ? "is-best" : ""}>
                      <span className="cell-bar">
                        <span style={{ width: `${Math.max(v * 100, 2)}%` }} />
                      </span>
                      <span className="cell-val">
                        {Math.round(v * 100)}
                        {top && <abbr title="Highest on this priority"> ▲</abbr>}
                      </span>
                    </td>
                  );
                })}
              </tr>
            );
          })}
          <tr className="row-sep">
            <th scope="row">Irrigation need, mm a year</th>
            {strategies.map((s) => (
              <td key={s.id}>
                <span className="cell-val">{fmt(s.water.irrigation_mm)}</span>
              </td>
            ))}
          </tr>
          <tr className="row-total">
            <th scope="row">Overall, weighted by your priorities</th>
            {strategies.map((s) => (
              <td key={s.id}>
                <span className="cell-val">
                  {Math.round(s.total * 100)}
                  {s.rank === 1 && <abbr title="Highest overall"> ▲</abbr>}
                </span>
              </td>
            ))}
          </tr>
        </tbody>
      </table>
      <p className="fine">Scores run from 0 to 100 on each priority. ▲ marks the highest in a row. The percentages are how much each priority counts.</p>
    </div>
  );
}

export default function Strategies({ result, region, onEvidence }: { result: Dict; region: RegionData; onEvidence: (panel: string) => void }) {
  const [open, setOpen] = useState<string | null>(null);
  const [view, setView] = useState<"cards" | "table">("cards");
  const flip = useFlip();
  const criteria: Criteria = Object.entries(region.kb.criteria).map(([id, c]) => ({ id, label: c.label }));
  const ordered: Dict[] = [...result.strategies].sort((a, b) => a.rank - b.rank);
  const sc = result.scenario;
  const imperial = Boolean(region.region.imperial);
  const frost = Boolean(region.region.has_frost);
  return (
    <section className="block strategies" id="compare">
      <header className="block-head">
        <h2>Compare rotations</h2>
        <div className="seg" role="tablist" aria-label="How to show the comparison">
          <button role="tab" aria-selected={view === "cards"} className={view === "cards" ? "on" : ""} onClick={() => setView("cards")}>
            Cards
          </button>
          <button role="tab" aria-selected={view === "table"} className={view === "table" ? "on" : ""} onClick={() => setView("table")}>
            Side by side
          </button>
        </div>
      </header>

      <p className="statement" aria-live="polite">{result.statement}</p>
      {!sc.is_baseline && (
        <p className="scenario-note">
          What-if weather is on: {sc.temp_c > 0 ? `+${sc.temp_c} °C` : `${sc.temp_c} °C`}, rain {sc.rain_pct > 0 ? "+" : ""}
          {sc.rain_pct} %. The weather's demand becomes {mm(result.climate.et0_annual, imperial)} a year (normally {fmt(result.climate_baseline.et0_annual)})
          {frost
            ? `, and the frost-free season ${fmt(result.climate.frost_free_median)} days (normally ${fmt(result.climate_baseline.frost_free_median)})`
            : `, with ${fmt(result.climate.hot_days)} days above ${result.climate.hot_day_c} °C (normally ${fmt(result.climate_baseline.hot_days)})`}
          . A sensitivity test, not a forecast.
        </p>
      )}
      <p className="disclaimer-inline">{result.disclaimer}</p>

      {view === "cards" ? (
        <>
          <RingLegend strategies={result.strategies} region={region} />
          <div className="strategy-list">
            {ordered.map((s) => (
              <StrategyCard key={s.id} s={s} result={result} criteria={criteria} imperial={imperial} open={open === s.id} onToggle={() => setOpen(open === s.id ? null : s.id)} onEvidence={onEvidence} flipRef={flip(s.id)} />
            ))}
          </div>
        </>
      ) : (
        <CompareTable result={result} criteria={criteria} />
      )}
    </section>
  );
}
