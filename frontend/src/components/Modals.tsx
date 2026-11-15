import { useState } from "react";
import { MONTHS, type Glossary, type RegionData } from "../data";
import { DemoBadge, Modal } from "./ui";

const STATUS: Record<string, string> = { ok: "Loaded", partial: "Partly loaded", failed: "Not loaded: action needed", skipped: "Skipped" };

export function GlossaryModal({ glossary, onClose }: { glossary: Glossary; onClose: () => void }) {
  return (
    <Modal title="Plain-language guide" onClose={onClose}>
      <p className="modal-lede">{glossary.disclaimer}</p>
      <dl className="glossary">
        {glossary.terms.map((t) => (
          <div key={t.id}>
            <dt>
              {t.plain} <span>{t.term}</span>
            </dt>
            <dd>{t.text}</dd>
          </div>
        ))}
      </dl>
      <h3>What this tool cannot see</h3>
      <ul className="plain">
        {glossary.limits.map((l) => (
          <li key={l}>{l}</li>
        ))}
      </ul>
    </Modal>
  );
}

export function SourcesModal({ region, onClose }: { region: RegionData; onClose: () => void }) {
  const order = ["MUST", "STRONG", "OPTIONAL"];
  const list = [...region.sources].sort((a, b) => order.indexOf(a.tier) - order.indexOf(b.tier));
  return (
    <Modal title={`About the data · ${region.region.short}`} onClose={onClose} wide>
      <p className="modal-lede">
        Every number in this tool was downloaded from the source named below and reduced to field-by-month values. Nothing is simulated.{" "}
        {region.any_demo_data ? (
          <>
            Sample values are marked <DemoBadge />.
          </>
        ) : (
          "No demo data is in use."
        )}
      </p>
      <ul className="sources">
        {list.map((s) => (
          <li key={s.source} className={`src-${s.status}`}>
            <div className="src-head">
              <strong>{s.title}</strong>
              <span className={`src-status st-${s.status}`}>{STATUS[s.status] ?? s.status}</span>
              {s.is_demo_data && <DemoBadge />}
            </div>
            <p>{s.message}</p>
            {s.action_needed && (
              <p className="src-action">
                <strong>What is needed:</strong> {s.action_needed}
              </p>
            )}
            <p className="fine">
              {s.resolution && <>Resolution: {s.resolution}. </>}
              {s.date_range && <>Period: {s.date_range}. </>}
            </p>
            {s.notes && <p className="fine">Caveat: {s.notes}</p>}
            {s.credit && <p className="fine">Credit: {s.credit}</p>}
          </li>
        ))}
      </ul>
      <p className="fine">Basemap: Sentinel-2 cloudless by EOX (Copernicus Sentinel data 2016) and OpenStreetMap contributors. Full log with sanity checks: DATA_LOG.md in the project.</p>
    </Modal>
  );
}

export function MethodModal({ region, onClose }: { region: RegionData | null; onClose: () => void }) {
  const kb = region?.kb;
  const [crop, setCrop] = useState<string>(kb ? Object.keys(kb.crops)[0] : "");
  const c = kb?.crops?.[crop];
  return (
    <Modal title="How the scores work" onClose={onClose} wide>
      <p className="modal-lede">
        Each rotation gets a score from 0 to 100 on each of your priorities. Your sliders decide how much each priority counts, and the overall score is the weighted sum. There is no hidden model: the rules are below, and every score on a
        card opens to show its inputs. The scoring runs in your browser; the same rules, written in Python, are tested against it.
      </p>
      {!kb ? (
        <p>Open a region to see its priorities, crop table and references.</p>
      ) : (
        <>
          <div className="table-scroll">
            <table className="data-table">
              <thead>
                <tr>
                  <th>Priority</th>
                  <th>What it rewards</th>
                  <th>Built from</th>
                </tr>
              </thead>
              <tbody>
                {Object.entries(kb.criteria).map(([id, cr]) => (
                  <tr key={id}>
                    <td>
                      <strong>{cr.label}</strong>
                    </td>
                    <td>{cr.plain}</td>
                    <td>{cr.basis}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>

          <h3>Crop table for {region!.region.short}</h3>
          <p>{kb.region_note} Every value has a source or a stated reason. Class scores (0 to 1) are judgments made for this project, not measurements, and have not been reviewed by a local agronomist.</p>
          <label className="lp-row crop-pick">
            <span>Crop</span>
            <select value={crop} onChange={(e) => setCrop(e.target.value)}>
              {Object.entries(kb.crops).map(([id, v]) => (
                <option key={id} value={id}>
                  {v.label}
                </option>
              ))}
            </select>
          </label>
          {c && (
            <div className="crop-card">
              <p>
                <strong>{c.label}</strong> · {c.family} · {c.group}
              </p>
              <div className="table-scroll">
                <table className="data-table">
                  <thead>
                    <tr>
                      <th />
                      {MONTHS.map((m) => (
                        <th key={m}>{m}</th>
                      ))}
                    </tr>
                  </thead>
                  <tbody>
                    <tr>
                      <td>Crop coefficient</td>
                      {MONTHS.map((m, i) => (
                        <td key={m} className="num">
                          {c.kc[i + 1] ?? "·"}
                        </td>
                      ))}
                    </tr>
                    <tr>
                      <td>Soil cover</td>
                      {MONTHS.map((m, i) => (
                        <td key={m} className="num">
                          {c.cover[i + 1] ?? "·"}
                        </td>
                      ))}
                    </tr>
                  </tbody>
                </table>
              </div>
              <div className="table-scroll">
                <table className="data-table">
                  <thead>
                    <tr>
                      <th>Trait</th>
                      <th>Value</th>
                      <th>Source or reason</th>
                    </tr>
                  </thead>
                  <tbody>
                    {Object.entries(c.traits as Record<string, unknown>).map(([k, v]) => (
                      <tr key={k}>
                        <td>{k.replace(/_/g, " ")}</td>
                        <td className="num">{Array.isArray(v) ? v.join(" – ") : v === null ? "not documented" : String(v)}</td>
                        <td>{c.why[k] ?? (k === "ky" ? c.why.drought_tolerance : "") ?? ""}</td>
                      </tr>
                    ))}
                    <tr>
                      <td>crop coefficient</td>
                      <td />
                      <td>{c.why.kc}</td>
                    </tr>
                    {c.why.cover && (
                      <tr>
                        <td>soil cover</td>
                        <td />
                        <td>{c.why.cover}</td>
                      </tr>
                    )}
                  </tbody>
                </table>
              </div>
            </div>
          )}
          <h3>References</h3>
          <ul className="plain refs">
            {Object.entries(kb.references ?? {}).map(([k, v]) => (
              <li key={k}>
                <strong>{k}</strong>: {String(v)}
              </li>
            ))}
          </ul>
        </>
      )}
    </Modal>
  );
}
