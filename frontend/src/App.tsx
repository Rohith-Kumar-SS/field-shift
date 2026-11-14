import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { api, type Constraints, type Dict, type FieldsPayload, type Meta, type Scenario, type ScoreResult } from "./api";
import Evidence from "./components/Evidence";
import FieldSummary from "./components/FieldSummary";
import MapView from "./components/MapView";
import { GlossaryModal, MethodModal, SourcesModal } from "./components/Modals";
import Priorities from "./components/Priorities";
import Strategies from "./components/Strategies";
import { DemoBadge } from "./components/ui";

const defaultWeights = (meta: Meta) => Object.fromEntries(meta.criteria.map((c) => [c.id, c.default_weight]));

export default function App() {
  const [meta, setMeta] = useState<Meta | null>(null);
  const [fields, setFields] = useState<FieldsPayload | null>(null);
  const [customFields, setCustomFields] = useState<GeoJSON.Feature[]>([]);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [evidence, setEvidence] = useState<Dict | null>(null);
  const [result, setResult] = useState<ScoreResult | null>(null);
  const [weights, setWeights] = useState<Record<string, number>>({});
  const [constraints, setConstraints] = useState<Constraints>({ water_supply_pct: 100, equipment: ["hay", "drill"], market: "some" });
  const [scenario, setScenario] = useState<Scenario>({ rain_pct: 0, temp_c: 0 });
  const [panel, setPanel] = useState("water");
  const [drawing, setDrawing] = useState(false);
  const [modal, setModal] = useState<null | "glossary" | "sources" | "method">(null);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [scoring, setScoring] = useState(false);
  const evidenceCache = useRef<Dict<Dict>>({});
  const seq = useRef(0);

  // ---- first load ------------------------------------------------------------
  useEffect(() => {
    Promise.all([api.meta(), api.fields()])
      .then(([m, f]) => {
        setMeta(m);
        setFields(f);
        setWeights(defaultWeights(m));
        setConstraints({ ...m.constraints.defaults });
      })
      .catch((e: Error) => setError(`The data service did not answer (${e.message}). Start it with "python tasks.py dev", and run "python tasks.py data" first if no data has been prepared.`));
  }, []);

  const feature = useMemo(() => {
    if (!fields || !selectedId) return null;
    return [...fields.pilot.features, ...customFields].find((f) => (f.properties as Dict).field_id === selectedId) ?? null;
  }, [fields, customFields, selectedId]);

  // ---- evidence for the selected field ---------------------------------------
  useEffect(() => {
    if (!selectedId) return;
    if (evidenceCache.current[selectedId]) {
      setEvidence(evidenceCache.current[selectedId]);
      return;
    }
    setEvidence(null);
    api
      .evidence(selectedId)
      .then((ev) => {
        evidenceCache.current[selectedId] = ev;
        setEvidence(ev);
      })
      .catch((e: Error) => setError(`Could not load the evidence for this field: ${e.message}`));
  }, [selectedId]);

  // ---- scoring: re-run (debounced) whenever anything the farmer controls changes ----
  useEffect(() => {
    if (!selectedId || !meta) return;
    const mine = ++seq.current;
    setScoring(true);
    const t = window.setTimeout(() => {
      api
        .score(selectedId, weights, constraints, scenario)
        .then((r) => {
          if (mine === seq.current) {
            setResult(r);
            setError(null);
          }
        })
        .catch((e: Error) => mine === seq.current && setError(`Scoring failed: ${e.message}`))
        .finally(() => mine === seq.current && setScoring(false));
    }, 160);
    return () => window.clearTimeout(t);
  }, [selectedId, weights, constraints, scenario, meta]);

  const select = useCallback((id: string) => {
    setSelectedId(id);
    setResult(null);
    setNotice(null);
  }, []);

  const showEvidence = useCallback((p: string) => {
    setPanel(p);
    window.requestAnimationFrame(() => document.getElementById("evidence")?.scrollIntoView({ behavior: "smooth", block: "start" }));
  }, []);

  const finishDraw = useCallback((polygon: GeoJSON.Polygon) => {
    setDrawing(false);
    setNotice("Reading soil, crop history and greenness under your shape…");
    api
      .customField(polygon, "My drawn field")
      .then(({ feature: f, evidence: ev }) => {
        const id = (f.properties as Dict).field_id as string;
        evidenceCache.current[id] = ev;
        setCustomFields((prev) => [...prev, f]);
        setSelectedId(id);
        setResult(null);
        setNotice(null);
      })
      .catch((e: Error) => setNotice(`That field could not be used: ${e.message}`));
  }, []);

  const reset = () => {
    if (!meta) return;
    setWeights(defaultWeights(meta));
    setConstraints({ ...meta.constraints.defaults });
    setScenario({ rain_pct: 0, temp_c: 0 });
  };

  if (error && !meta) {
    return (
      <main className="fatal">
        <h1>Field Shift</h1>
        <p>{error}</p>
      </main>
    );
  }
  if (!meta || !fields) {
    return (
      <main className="fatal">
        <h1>Field Shift</h1>
        <p>Loading the valley…</p>
      </main>
    );
  }

  const pending = meta.sources.filter((s) => s.status === "failed");

  return (
    <div className="app">
      <header className="topbar">
        <div className="brand">
          <svg width="30" height="30" viewBox="0 0 30 30" aria-hidden="true">
            <circle cx="15" cy="15" r="12.5" fill="none" stroke="currentColor" strokeWidth="2" />
            <path d="M15 15 L15 2.5 A12.5 12.5 0 0 1 26.8 19 Z" fill="currentColor" opacity="0.9" />
            <circle cx="15" cy="15" r="2" fill="#fff" />
          </svg>
          <div>
            <h1>Field Shift</h1>
            <p>Rotation Scenario Explorer · {meta.pilot.name}</p>
          </div>
        </div>
        <nav className="topnav" aria-label="Help">
          {meta.any_demo_data && <DemoBadge />}
          <button className="btn btn-quiet" onClick={() => setModal("glossary")}>
            Plain-language guide
          </button>
          <button className="btn btn-quiet" onClick={() => setModal("method")}>
            How scores work
          </button>
          <button className="btn btn-quiet" onClick={() => setModal("sources")}>
            About the data{pending.length ? ` (${pending.length} pending)` : ""}
          </button>
        </nav>
      </header>

      <p className="promise" role="note">
        <strong>This tool compares options. It does not tell you what to plant.</strong> It supports, and does not replace, your own judgment and local agricultural expertise.
      </p>

      <div className="layout">
        <div className="col-map">
          <MapView meta={meta} fields={fields} customFields={customFields} selectedId={selectedId} onSelect={select} drawing={drawing} onDrawFinish={finishDraw} onDrawCancel={() => setDrawing(false)} />
          <div className="map-foot">
            <span>
              {selectedId ? "Tap another numbered circle to switch field." : "Tap a numbered circle to pick a field."} Faint circles are other pivots, not analysed. The dashed box is the pilot area.
            </span>
            {!drawing && (
              <button className="btn" onClick={() => setDrawing(true)}>
                Draw my own field
              </button>
            )}
          </div>
          {notice && <p className="notice" role="status">{notice}</p>}
          {error && <p className="notice notice-error" role="alert">{error}</p>}

          {feature && result && <Strategies result={result} criteria={meta.criteria} loading={scoring} onEvidence={showEvidence} />}
          {feature && !result && <section className="block strategies"><p>Comparing rotations…</p></section>}
          {feature && evidence && <Evidence ev={evidence} panel={panel} onPanel={setPanel} />}
        </div>

        <div className="col-side">
          {!feature && (
            <section className="block intro">
              <h2>Start with a field</h2>
              <p>
                Pick one of the {fields.pilot.features.length} numbered pivots on the map, or draw your own inside the dashed box. You will see how it has been farmed, what the weather, water, soil and satellite record say about it,
                and how five rotations compare under the priorities you set.
              </p>
              <ul className="plain">
                <li>The existing rotation is always one of the five, so you can see what changes.</li>
                <li>Every score opens to show the numbers and sources behind it.</li>
                <li>Every rotation lists what the tool does not know and what to check locally.</li>
              </ul>
              {pending.length > 0 && (
                <p className="notice">
                  {pending.map((p) => p.title).join(", ")} could not be loaded yet.{" "}
                  <button className="link-btn" onClick={() => setModal("sources")}>
                    See what is needed
                  </button>
                </p>
              )}
            </section>
          )}
          {feature && <FieldSummary feature={feature} evidence={evidence} meta={meta} onEvidence={showEvidence} onShowSources={() => setModal("sources")} />}
          {feature && <Priorities meta={meta} weights={weights} constraints={constraints} scenario={scenario} result={result} onWeights={setWeights} onConstraints={setConstraints} onScenario={setScenario} onReset={reset} />}
        </div>
      </div>

      <footer className="footer">
        <p>
          Built for the 2026 NASA Space Apps Challenge, “Field Shift: Adapting Farms with NASA Data”. Data: NASA POWER, SMAP, Landsat, MODIS and SRTM; USDA NRCS SSURGO and NASS Cropland Data Layer; OpenET; USGS; gridMET. NASA does not
          endorse this tool.
        </p>
      </footer>

      {modal === "glossary" && <GlossaryModal meta={meta} onClose={() => setModal(null)} />}
      {modal === "sources" && <SourcesModal meta={meta} onClose={() => setModal(null)} />}
      {modal === "method" && <MethodModal meta={meta} onClose={() => setModal(null)} />}
    </div>
  );
}
