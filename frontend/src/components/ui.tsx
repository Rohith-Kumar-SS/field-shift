import { useEffect, useState, type ReactNode } from "react";

const CONF_TEXT: Record<string, string> = {
  high: "High confidence",
  medium: "Medium confidence",
  low: "Low confidence",
};
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

interface Column {
  key: string;
  label: string;
  digits?: number;
}

/** Chart shell: title, one-line reading aid, the chart, its source, and a table view. */
export function ChartFrame({
  title,
  lede,
  source,
  children,
  rows,
  columns,
  legend,
}: {
  title: string;
  lede?: ReactNode;
  source: ReactNode;
  children: ReactNode;
  rows?: Record<string, any>[];
  columns?: Column[];
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
