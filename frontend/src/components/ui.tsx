import { useEffect, useState, type ReactNode } from "react";
import { fmt, GROUP_COLOR, MONTHS } from "../data";
import { useSeen, useTween } from "../motion";

const CONF_TEXT: Record<string, string> = { high: "High confidence", medium: "Medium confidence", low: "Low confidence" };
const CONF_HELP: Record<string, string> = {
  high: "Several independent sources for this field agree.",
  medium: "Based on satellite or weather-model data for this field, without ground confirmation.",
  low: "Based on general crop tables, or on things this tool cannot see. Take it to a local adviser.",
};

/** Confidence is never colour alone: a shape (filled dots) and a word carry it too. */
export function Confidence({ level, compact = false }: { level: "high" | "medium" | "low"; compact?: boolean }) {
  const n = level === "high" ? 3 : level === "medium" ? 2 : 1;
  return (
    <span className={`conf conf-${level}`} title={CONF_HELP[level]}>
      <span className="conf-dots" aria-hidden="true">
        {[0, 1, 2].map((i) => (
          <i key={i} className={i < n ? "on" : ""} />
        ))}
      </span>
      {compact ? level : CONF_TEXT[level]}
    </span>
  );
}

export function DemoBadge() {
  return (
    <span className="demo-badge" title="This value is sample data, not a real measurement.">
      Demo data
    </span>
  );
}

/** A figure that glides to its new value. */
export function Num({ value, digits = 0 }: { value: number; digits?: number }) {
  const v = useTween(value);
  return <>{fmt(v, digits)}</>;
}

interface Column {
  key: string;
  label: string;
  digits?: number;
}

/** Chart shell: title, one-line reading aid, the chart, its source, and a table view. */
export function ChartFrame({ title, lede, source, children, rows, columns, legend }: {
  title: string; lede?: ReactNode; source: ReactNode; children: ReactNode; rows?: Record<string, any>[]; columns?: Column[];
  legend?: { label: string; color: string; shape?: "line" | "bar" | "band" | "dash" }[];
}) {
  const [table, setTable] = useState(false);
  return (
    <figure className="chart">
      <figcaption>
        <h4>{title}</h4>
        {lede && <p className="chart-lede">{lede}</p>}
      </figcaption>
      {legend && legend.length > 1 && (
        <ul className="chart-legend">
          {legend.map((l) => (
            <li key={l.label}>
              <i className={`key key-${l.shape ?? "line"}`} style={{ color: l.color }} />
              {l.label}
            </li>
          ))}
        </ul>
      )}
      {table && rows && columns ? (
        <div className="table-scroll">
          <table className="data-table">
            <thead>
              <tr>
                {columns.map((c) => (
                  <th key={c.key}>{c.label}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {rows.map((r, i) => (
                <tr key={i}>
                  {columns.map((c) => {
                    const v = r[c.key];
                    return <td key={c.key}>{typeof v === "number" ? v.toLocaleString("en-US", { maximumFractionDigits: c.digits ?? 1 }) : (v ?? "–")}</td>;
                  })}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : (
        <div className="chart-body">{children}</div>
      )}
      <div className="chart-foot">
        <span className="chart-source">{source}</span>
        {rows && columns && (
          <button className="link-btn" onClick={() => setTable((v) => !v)}>
            {table ? "Show chart" : "Show as table"}
          </button>
        )}
      </div>
    </figure>
  );
}

export function Modal({ title, onClose, children, wide = false }: { title: string; onClose: () => void; children: ReactNode; wide?: boolean }) {
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && onClose();
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);
  return (
    <div className="modal-back" onClick={onClose}>
      <div className={`modal ${wide ? "modal-wide" : ""}`} role="dialog" aria-modal="true" aria-label={title} onClick={(e) => e.stopPropagation()}>
        <header className="modal-head">
          <h2>{title}</h2>
          <button className="btn btn-quiet" onClick={onClose}>
            Close
          </button>
        </header>
        <div className="modal-body">{children}</div>
      </div>
    </div>
  );
}

export function Stat({ label, value, unit, note }: { label: string; value: ReactNode; unit?: string; note?: ReactNode }) {
  return (
    <div className="stat">
      <div className="stat-label">{label}</div>
      <div className="stat-value">
        {value}
        {unit && <span className="stat-unit"> {unit}</span>}
      </div>
      {note && <div className="stat-note">{note}</div>}
    </div>
  );
}

/** Shared tooltip body for the charts: text in ink, a coloured key beside it. */
export function TipBox({ title, rows }: { title: string; rows: { label: string; value: string; color?: string }[] }) {
  return (
    <div className="tip">
      <div className="tip-title">{title}</div>
      {rows.map((r) => (
        <div className="tip-row" key={r.label}>
          <span>
            {r.color && <i style={{ background: r.color }} />}
            {r.label}
          </span>
          <strong>{r.value}</strong>
        </div>
      ))}
    </div>
  );
}

// ---------------------------------------------------------------------------
// The rotation ring: the tool's signature. A field seen from above, like a centre pivot:
// one lap is the whole rotation, each coloured arc a crop in the months it holds the
// ground, and the pale gaps are months of stubble or bare soil.
// ---------------------------------------------------------------------------
export interface RingYear {
  year: number;
  calendar_year?: number | null;
  label: string;
  entries: { crop: string; label: string; group: string; months: number[] }[];
}

/** contiguous runs of months, e.g. [1,2,3,9,10] -> [[1,3],[9,10]] */
function monthRuns(months: number[]): [number, number][] {
  const m = [...months].sort((a, b) => a - b);
  const out: [number, number][] = [];
  m.forEach((v) => {
    const last = out[out.length - 1];
    if (last && v === last[1] + 1) last[1] = v;
    else out.push([v, v]);
  });
  return out;
}

function arcPath(cx: number, cy: number, r: number, a0: number, a1: number): string {
  const p = (a: number) => {
    const rad = ((a - 90) * Math.PI) / 180;
    return [cx + r * Math.cos(rad), cy + r * Math.sin(rad)];
  };
  const [x0, y0] = p(a0);
  const [x1, y1] = p(a1);
  return `M ${x0.toFixed(2)} ${y0.toFixed(2)} A ${r} ${r} 0 ${a1 - a0 > 180 ? 1 : 0} 1 ${x1.toFixed(2)} ${y1.toFixed(2)}`;
}

export function RotationRing({ sequence, score, size = 132, stroke = 15, arm = false, children }: {
  sequence: RingYear[]; score?: number; size?: number; stroke?: number; arm?: boolean; children?: ReactNode;
}) {
  const [ref, seen] = useSeen<SVGSVGElement>();
  const shown = useTween(score ?? 0);
  const n = sequence.length;
  const c = size / 2;
  const r = size / 2 - stroke / 2 - 6;
  const total = n * 12;
  const pad = n > 4 ? 0.7 : 1.1;
  return (
    <svg ref={ref} className={`ring ${seen ? "is-seen" : ""}`} width={size} height={size} viewBox={`0 0 ${size} ${size}`} role="img"
      aria-label={`${n}-year rotation: ${sequence.map((y) => y.label).join(", then ")}`}>
      <circle cx={c} cy={c} r={r} className="ring-track" strokeWidth={stroke} fill="none" />
      {sequence.map((y, i) =>
        y.entries.map((e, j) =>
          monthRuns(e.months).map(([m0, m1], k) => {
            const a0 = ((i * 12 + (m0 - 1)) / total) * 360 + pad;
            const a1 = Math.max(((i * 12 + m1) / total) * 360 - pad, a0 + 0.5);
            return (
              <path key={`${i}-${j}-${k}`} className="ring-arc" pathLength={1} d={arcPath(c, c, r, a0, a1)} stroke={GROUP_COLOR[e.group] ?? GROUP_COLOR.unknown}
                strokeWidth={stroke} fill="none" style={{ animationDelay: `${Math.round((a0 / 360) * 900)}ms` }}>
                <title>{`Year ${y.year}${y.calendar_year ? ` (${y.calendar_year})` : ""}: ${e.label}, ${MONTHS[m0 - 1]}–${MONTHS[m1 - 1]}`}</title>
              </path>
            );
          }),
        ),
      )}
      {sequence.map((_, i) => {
        const rad = ((((i * 12) / total) * 360 - 90) * Math.PI) / 180;
        const k = stroke / 2 + 3;
        return <line key={i} x1={c + (r - k) * Math.cos(rad)} y1={c + (r - k) * Math.sin(rad)} x2={c + (r + k) * Math.cos(rad)} y2={c + (r + k) * Math.sin(rad)} className="ring-tick" />;
      })}
      {arm && (
        <g className="ring-arm" style={{ transformOrigin: `${c}px ${c}px` }}>
          <line x1={c} y1={c} x2={c} y2={c - r - stroke / 2 - 2} />
          <circle cx={c} cy={c} r={3.2} />
        </g>
      )}
      {score !== undefined && (
        <>
          <text x={c} y={c + 4} className="ring-score" textAnchor="middle">
            {Math.round(shown * 100)}
          </text>
          <text x={c} y={c + 21} className="ring-sub" textAnchor="middle">
            of 100
          </text>
        </>
      )}
      {children}
    </svg>
  );
}
