import { useState } from "react";
import { GROUP_COLOR, GROUP_LABEL, MONTHS, fmt, mmToIn, type Criterion, type ScoreResult, type SequenceYear, type Strategy } from "../api";
import { Confidence } from "./ui";

const PANEL_NAME: Record<string, string> = {
  water: "Water",
  climate: "Weather",
  cover: "Greenness and cover",
  soil: "Soil",
  history: "Crop history",
  groundwater: "Groundwater",
};

/** contiguous runs of months, e.g. [1,2,3,9,10] -> [[1,3],[9,10]] */
function runs(months: number[]): [number, number][] {
  const m = [...months].sort((a, b) => a - b);
  const out: [number, number][] = [];
  m.forEach((v) => {
    const last = out[out.length - 1];
    if (last && v === last[1] + 1) last[1] = v;
    else out.push([v, v]);
  });
  return out;
}

function arc(cx: number, cy: number, r: number, a0: number, a1: number): string {
  const p = (a: number) => {
    const rad = ((a - 90) * Math.PI) / 180;
    return [cx + r * Math.cos(rad), cy + r * Math.sin(rad)];
  };
  const [x0, y0] = p(a0);
  const [x1, y1] = p(a1);
  return `M ${x0.toFixed(2)} ${y0.toFixed(2)} A ${r} ${r} 0 ${a1 - a0 > 180 ? 1 : 0} 1 ${x1.toFixed(2)} ${y1.toFixed(2)}`;
}

/**
 * The rotation drawn as a centre pivot seen from above: one lap of the ring is the whole
 * rotation, each coloured arc is a crop in the months it occupies the field, and the
 * pale gaps are months with only stubble or bare soil.
 */
export function RotationRing({ sequence, score, size = 132 }: { sequence: SequenceYear[]; score?: number; size?: number }) {
  const n = sequence.length;
  const c = size / 2;
  const r = size / 2 - 13;
  const total = n * 12;
  const pad = 0.7;
  return (
    <svg className="ring" width={size} height={size} viewBox={`0 0 ${size} ${size}`} role="img"
      aria-label={`${n}-year rotation: ${sequence.map((y) => y.label).join(", then ")}`}>
      <circle cx={c} cy={c} r={r} className="ring-track" strokeWidth={15} fill="none" />
      {sequence.map((y, i) =>
        y.entries.map((e, j) =>
          runs(e.months).map(([m0, m1], k) => {
            const a0 = ((i * 12 + (m0 - 1)) / total) * 360 + pad;
            const a1 = ((i * 12 + m1) / total) * 360 - pad;
            return (
              <path key={`${i}-${j}-${k}`} d={arc(c, c, r, a0, Math.max(a1, a0 + 0.5))} stroke={GROUP_COLOR[e.group] ?? GROUP_COLOR.unknown}
                strokeWidth={15} fill="none" strokeDasharray={e.group === "unknown" ? "3 2" : undefined}>
                <title>{`Year ${y.year}${y.calendar_year ? ` (${y.calendar_year})` : ""}: ${e.label}, ${MONTHS[m0 - 1]}–${MONTHS[m1 - 1]}`}</title>
              </path>
            );
          }),
        ),
      )}
      {sequence.map((_, i) => {
        const a = ((i * 12) / total) * 360 - 90;
        const rad = (a * Math.PI) / 180;
        return <line key={i} x1={c + (r - 10) * Math.cos(rad)} y1={c + (r - 10) * Math.sin(rad)} x2={c + (r + 10) * Math.cos(rad)} y2={c + (r + 10) * Math.sin(rad)} className="ring-tick" />;
      })}
      {score !== undefined && (
        <>
          <text x={c} y={c + 4} className="ring-score" textAnchor="middle">
            {Math.round(score * 100)}
          </text>
          <text x={c} y={c + 21} className="ring-sub" textAnchor="middle">
            of 100
          </text>
        </>
      )}
    </svg>
  );
}

export function RingLegend({ strategies }: { strategies: Strategy[] }) {
  const groups = Array.from(new Set(strategies.flatMap((s) => s.sequence.flatMap((y) => y.entries.map((e) => e.group)))));
  const order = Object.keys(GROUP_LABEL).filter((g) => groups.includes(g));
  return (
    <div className="ring-legend">
      <span className="ring-legend-how">One lap of a ring = the whole rotation. Pale gaps = stubble or bare soil.</span>
      <ul>
        {order.map((g) => (
          <li key={g}>
            <i style={{ background: GROUP_COLOR[g] }} />
            {GROUP_LABEL[g]}
          </li>
        ))}
      </ul>
    </div>
  );
}

function ScoreBars({ s, criteria, weights }: { s: Strategy; criteria: Criterion[]; weights: Record<string, number> }) {
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

function CriterionRow({ c, s, onEvidence }: { c: Criterion; s: Strategy; onEvidence: (panel: string) => void }) {
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
          <table className="data-table">
            <thead>
              <tr>
                <th>What went in</th>
                <th>Value</th>
                <th>Where it comes from</th>
              </tr>
            </thead>
            <tbody>
              {d.inputs.map((i) => (
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

function StrategyCard({ s, result, criteria, open, onToggle, onEvidence }: {
  s: Strategy; result: ScoreResult; criteria: Criterion[]; open: boolean; onToggle: () => void; onEvidence: (panel: string) => void;
}) {
  const existing = result.strategies.find((x) => x.is_existing)!;
  const diff = s.water.irrigation_mm - existing.water.irrigation_mm;
  const [checked, setChecked] = useState<Record<number, boolean>>({});
  return (
    <article className={`strategy ${s.rank === 1 ? "is-top" : ""} ${s.is_existing ? "is-existing" : ""}`}>
      <div className="strategy-main">
        <div className="strategy-ring">
          <RotationRing sequence={s.sequence} score={s.total} />
          <div className="ring-caption">{s.sequence.length}-year cycle</div>
        </div>
        <div className="strategy-text">
          <div className="strategy-tags">
            <span className="rank">
              {s.rank === 1 ? "Scores highest" : `Ranks ${s.rank} of ${result.strategies.length}`}
            </span>
            {s.is_existing && <span className="tag-existing">What you do now</span>}
            <Confidence level={s.confidence.level} />
          </div>
          <h3>{s.name}</h3>
          <p className="strategy-summary">{s.summary}</p>
          <p className="strategy-water">
            Irrigation need about <strong>{fmt(s.water.irrigation_mm)} mm</strong> ({fmt(mmToIn(s.water.irrigation_mm), 1)} in) a year
            {!s.is_existing && Math.abs(diff) >= 5 && (
              <>
                {" "}
                · <strong>{fmt(Math.abs(diff))} mm {diff < 0 ? "less" : "more"}</strong> than now
              </>
            )}
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
              {s.why.map((w, i) => (
                <li key={i}>
                  {w.text}{" "}
                  <button className="link-btn" onClick={() => onEvidence(w.panel)}>
                    See evidence: {PANEL_NAME[w.panel] ?? w.panel}
                  </button>
                </li>
              ))}
            </ul>
            {s.assumptions?.map((a) => (
              <p className="assumption" key={a}>
                Assumption: {a}
              </p>
            ))}
          </section>

          <section>
            <h4>Year by year</h4>
            <ol className="seq">
              {s.sequence.map((y) => (
                <li key={y.year}>
                  <span className="seq-year">{y.calendar_year ?? `Year ${y.year}`}</span>
                  <span className="seq-crops">
                    {y.entries
                      .filter((e, i, arr) => arr.findIndex((x) => x.crop === e.crop) === i)
                      .map((e) => (
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
                {s.benefits.map((b) => (
                  <li key={b}>{b}</li>
                ))}
              </ul>
            </section>
            <section>
              <h4>Risks to review locally</h4>
              <ul className="plain risks">
                {s.risks.map((b) => (
                  <li key={b}>{b}</li>
                ))}
              </ul>
            </section>
          </div>

          <section>
            <h4>What this tool does not know</h4>
            <ul className="plain gaps">
              {s.info_gaps.map((b) => (
                <li key={b}>{b}</li>
              ))}
            </ul>
          </section>

          <section className="verify">
            <h4>Check with a local expert before acting</h4>
            <ul>
              {s.verify.map((v, i) => (
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
              {s.confidence.reasons.map((r) => (
                <li key={r}>{r}</li>
              ))}
            </ul>
          </section>
        </div>
      )}
    </article>
  );
}

function CompareTable({ result, criteria }: { result: ScoreResult; criteria: Criterion[] }) {
  const strategies = result.strategies;
  return (
    <div className="table-scroll">
      <table className="compare">
        <thead>
          <tr>
            <th scope="col">Your priority</th>
            {strategies.map((s) => (
              <th key={s.id} scope="col">
                {s.short}
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

export default function Strategies({ result, criteria, loading, onEvidence }: {
  result: ScoreResult; criteria: Criterion[]; loading: boolean; onEvidence: (panel: string) => void;
}) {
  const [open, setOpen] = useState<string | null>(null);
  const [view, setView] = useState<"cards" | "table">("cards");
  const ordered = [...result.strategies].sort((a, b) => a.rank - b.rank);
  const sc = result.scenario;
  return (
    <section className={`block strategies ${loading ? "is-loading" : ""}`} aria-busy={loading}>
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

      <p className="statement">{result.statement}</p>
      {!sc.is_baseline && (
        <p className="scenario-note">
          What-if weather is on: {sc.temp_c > 0 ? `+${sc.temp_c} °C` : `${sc.temp_c} °C`}, rain {sc.rain_pct > 0 ? "+" : ""}
          {sc.rain_pct} %. Reference ET {fmt(result.climate.et0_annual)} mm (normally {fmt(result.climate_baseline.et0_annual)}), frost-free season{" "}
          {fmt(result.climate.frost_free_median)} days (normally {fmt(result.climate_baseline.frost_free_median)}). A sensitivity test, not a forecast.
        </p>
      )}
      <p className="disclaimer-inline">{result.disclaimer}</p>

      {view === "cards" ? (
        <>
          <RingLegend strategies={result.strategies} />
          <div className="strategy-list">
            {ordered.map((s) => (
              <StrategyCard key={s.id} s={s} result={result} criteria={criteria} open={open === s.id} onToggle={() => setOpen(open === s.id ? null : s.id)} onEvidence={onEvidence} />
            ))}
          </div>
        </>
      ) : (
        <CompareTable result={result} criteria={criteria} />
      )}
    </section>
  );
}
