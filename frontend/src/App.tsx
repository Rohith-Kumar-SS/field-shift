import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import Evidence from "./components/Evidence";
import FieldSummary from "./components/FieldSummary";
import Landing from "./components/Landing";
import MapView from "./components/MapView";
import { GlossaryModal, MethodModal, SourcesModal } from "./components/Modals";
import Priorities from "./components/Priorities";
import Strategies from "./components/Strategies";
import { DemoBadge } from "./components/ui";
import { fieldNumber, loadField, loadGlossary, loadRegion, loadRegions, type Constraints, type Dict, type FieldData, type Glossary, type RegionData, type RegionInfo, type Scenario } from "./data";
import type { Clim } from "./engine/climate";
import { buildCustomField, loadAtlas } from "./engine/custom";
import { baselineClimate, defaultConstraints, scoreField } from "./engine/scoring";

const defaultWeights = (r: RegionData) => Object.fromEntries(Object.entries(r.kb.criteria).map(([id, c]) => [id, c.default_weight]));
const regionFromHash = () => decodeURIComponent(window.location.hash.replace(/^#\/?/, "")) || null;

function Brand({ onHome }: { onHome: () => void }) {
  return (
    <button className="brand" onClick={onHome} aria-label="Field Shift: back to the region list">
      <svg width="30" height="30" viewBox="0 0 30 30" aria-hidden="true">
        <circle cx="15" cy="15" r="12.5" fill="none" stroke="currentColor" strokeWidth="2" opacity="0.55" />
        <path d="M15 15 L15 2.5 A12.5 12.5 0 0 1 26.8 19 Z" fill="var(--sun)" />
        <circle cx="15" cy="15" r="2.2" fill="currentColor" />
      </svg>
      <span>
        <strong>Field Shift</strong>
        <em>Rotation Scenario Explorer</em>
      </span>
    </button>
  );
}

export default function App() {
  const [regions, setRegions] = useState<RegionInfo[] | null>(null);
  const [glossary, setGlossary] = useState<Glossary | null>(null);
  const [regionId, setRegionId] = useState<string | null>(regionFromHash);
  const [region, setRegion] = useState<RegionData | null>(null);
  const [customFields, setCustomFields] = useState<GeoJSON.Feature[]>([]);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [field, setField] = useState<FieldData | null>(null);
  const [weights, setWeights] = useState<Record<string, number>>({});
  const [constraints, setConstraints] = useState<Constraints>({ water_supply_pct: 100, equipment: [], market: "some" });
  const [scenario, setScenario] = useState<Scenario>({ rain_pct: 0, temp_c: 0 });
  const [existingId, setExistingId] = useState<string | null>(null);
  const [panel, setPanel] = useState("water");
  const [drawing, setDrawing] = useState(false);
  const [modal, setModal] = useState<null | "glossary" | "sources" | "method">(null);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const custom = useRef<Dict<FieldData>>({});
  const climBase = useRef<{ key: string; clim: Clim } | null>(null);

  // ---- first load and navigation ------------------------------------------------
  useEffect(() => {
    loadRegions().then(setRegions).catch((e: Error) => setError(`The data files could not be loaded (${e.message}). If you are running this yourself, run "python tasks.py data export" first.`));
    loadGlossary().then(setGlossary).catch(() => undefined);
    const onHash = () => setRegionId(regionFromHash());
    window.addEventListener("hashchange", onHash);
    return () => window.removeEventListener("hashchange", onHash);
  }, []);

  const go = useCallback((id: string | null) => {
    window.location.hash = id ? `/${id}` : "";
    setRegionId(id);
    window.scrollTo({ top: 0 });
  }, []);

  useEffect(() => {
    setRegion(null);
    setSelectedId(null);
    setField(null);
    setCustomFields([]);
    setDrawing(false);
    setNotice(null);
    setExistingId(null);
    setScenario({ rain_pct: 0, temp_c: 0 });
    custom.current = {};
    if (!regionId) return;
    let alive = true;
    loadRegion(regionId)
      .then((r) => {
        if (!alive) return;
        setRegion(r);
        setWeights(defaultWeights(r));
        setConstraints(defaultConstraints(r.kb));
        setError(null);
      })
      .catch((e: Error) => alive && setError(`That region could not be loaded: ${e.message}`));
    return () => {
      alive = false;
    };
  }, [regionId]);

  // ---- the selected field: its context, evidence and 30 years of daily weather ----
  useEffect(() => {
    if (!region || !selectedId) return;
    if (custom.current[selectedId]) {
      setField(custom.current[selectedId]);
      return;
    }
    let alive = true;
    setField(null);
    loadField(region, selectedId)
      .then((f) => alive && setField(f))
      .catch((e: Error) => alive && setError(`Could not load this field: ${e.message}`));
    return () => {
      alive = false;
    };
  }, [region, selectedId]);

  // ---- scoring runs in the browser, on every change, with no round trip ------------
  const result = useMemo<Dict | null>(() => {
    if (!region || !field || !selectedId || field.context.field_id !== selectedId) return null;
    try {
      const key = `${region.id}:${selectedId}`;
      if (climBase.current?.key !== key) climBase.current = { key, clim: baselineClimate(field.context, region.kb, field.weather) };
      return scoreField({ ctx: field.context, kb: region.kb, weather: field.weather, weights, constraints, scenario, existingId, climBase: climBase.current.clim });
    } catch (e) {
      console.error(e);
      return null;
    }
  }, [region, field, selectedId, weights, constraints, scenario, existingId]);

  const feature = useMemo(() => {
    if (!region || !selectedId) return null;
    return [...region.fields.features, ...customFields].find((f) => (f.properties as Dict).field_id === selectedId) ?? null;
  }, [region, customFields, selectedId]);

  const select = useCallback((id: string) => {
    setSelectedId(id);
    setNotice(null);
  }, []);

  const showEvidence = useCallback((p: string) => {
    setPanel(p);
    window.requestAnimationFrame(() => document.getElementById("evidence")?.scrollIntoView({ behavior: "smooth", block: "start" }));
  }, []);

  const finishDraw = useCallback(
    (polygon: GeoJSON.Polygon) => {
      if (!region) return;
      setDrawing(false);
      setNotice("Reading soil, greenness and crop history under your shape…");
      const donors = region.fields.features.map((f) => {
        const p = f.properties as Dict;
        return { id: p.field_id as string, lon: p.lon as number, lat: p.lat as number, name: p.name as string };
      });
      loadAtlas(region)
        .then((atlas) => buildCustomField(region, atlas, polygon, donors, (id) => loadField(region, id)))
        .then(({ feature: f, data }) => {
          const id = (f.properties as Dict).field_id as string;
          custom.current[id] = data;
          setCustomFields((prev) => [...prev, f]);
          setSelectedId(id);
          setNotice(null);
        })
        .catch((e: Error) => setNotice(`That field could not be used: ${e.message}`));
    },
    [region],
  );

  const reset = () => {
    if (!region) return;
    setWeights(defaultWeights(region));
    setConstraints(defaultConstraints(region.kb));
    setScenario({ rain_pct: 0, temp_c: 0 });
    setExistingId(null);
  };

  const modals = (
    <>
      {modal === "glossary" && glossary && <GlossaryModal glossary={glossary} onClose={() => setModal(null)} />}
      {modal === "sources" && region && <SourcesModal region={region} onClose={() => setModal(null)} />}
      {modal === "method" && <MethodModal region={region} onClose={() => setModal(null)} />}
    </>
  );

  if (error && !regions) {
    return (
      <main className="fatal">
        <h1>Field Shift</h1>
        <p>{error}</p>
      </main>
    );
  }
  if (!regions) {
    return (
      <main className="fatal">
        <div className="loader" aria-hidden="true" />
        <p>Loading…</p>
      </main>
    );
  }

  // ---- landing: choose a region ------------------------------------------------------
  if (!regionId) {
    return (
      <div className="app app-landing">
        <header className="topbar topbar-dark">
          <Brand onHome={() => go(null)} />
          <nav className="topnav" aria-label="Help">
            <button className="btn btn-ghost" onClick={() => setModal("glossary")}>
              Plain-language guide
            </button>
          </nav>
        </header>
        <Landing regions={regions} onOpen={go} onHelp={setModal} />
        <Footer />
        {modals}
      </div>
    );
  }

  const info = regions.find((r) => r.id === regionId);
  const unit = info?.field_unit === "pivot" ? "field" : "plot";
  const pending = region?.sources.filter((s) => s.status === "failed") ?? [];

  return (
    <div className="app">
      <header className="topbar topbar-dark">
        <Brand onHome={() => go(null)} />
        <nav className="region-tabs" aria-label="Region">
          {regions.map((r) => (
            <button key={r.id} className={r.id === regionId ? "on" : ""} aria-current={r.id === regionId ? "page" : undefined} onClick={() => go(r.id)}>
              {r.short.split(",")[0]}
              <span>{r.country}</span>
            </button>
          ))}
        </nav>
        <nav className="topnav" aria-label="Help">
          {region?.any_demo_data && <DemoBadge />}
          <button className="btn btn-ghost" onClick={() => setModal("glossary")}>
            Guide
          </button>
          <button className="btn btn-ghost" onClick={() => setModal("method")}>
            How scores work
          </button>
          <button className="btn btn-ghost" onClick={() => setModal("sources")} disabled={!region}>
            About the data{pending.length ? ` (${pending.length} pending)` : ""}
          </button>
        </nav>
      </header>

      <p className="promise" role="note">
        <strong>This tool compares options. It does not tell you what to plant.</strong> It supports, and does not replace, your own judgment and local agricultural expertise.
      </p>

      {!region ? (
        <main className="fatal">
          <div className="loader" aria-hidden="true" />
          <p>{error ?? `Coming down to ${info?.short ?? "the region"}…`}</p>
        </main>
      ) : (
        <main className="work" key={region.id}>
          <section className="stage">
            <div className="stage-map">
              <MapView key={region.id} region={region} customFields={customFields} selectedId={selectedId} onSelect={select} drawing={drawing} onDrawFinish={finishDraw} onDrawCancel={() => setDrawing(false)} />
              <div className="map-foot">
                <span>
                  {selectedId ? `Tap another numbered ${unit} to switch.` : `Tap a numbered ${unit} to begin.`}{" "}
                  {unit === "field" ? "Faint circles are other pivots, not analysed." : "Each plot is a 300 m block of farmland: a neighbourhood of small fields."} The dashed box is the pilot area.
                </span>
                {!drawing && region.atlas && (
                  <button className="btn" onClick={() => setDrawing(true)}>
                    Draw my own field
                  </button>
                )}
              </div>
              <div className="field-picker" role="group" aria-label={`Choose a ${unit} by number`}>
                <span>Or pick by number:</span>
                {[...region.fields.features, ...customFields].map((f) => {
                  const p = f.properties as Dict;
                  return (
                    <button key={p.field_id} className={p.field_id === selectedId ? "on" : ""} aria-pressed={p.field_id === selectedId} title={p.name} onClick={() => select(p.field_id)}>
                      {p.is_custom ? "★" : fieldNumber(p.field_id)}
                    </button>
                  );
                })}
              </div>
              {notice && <p className="notice" role="status">{notice}</p>}
              {error && <p className="notice notice-error" role="alert">{error}</p>}
            </div>
            <div className="stage-side">
              {!feature ? (
                <section className="block intro">
                  <p className="eyebrow">{region.region.name}</p>
                  <h2>Start with a {unit}</h2>
                  <p>{region.region.tagline}.</p>
                  <p>
                    Pick one of the {region.fields.features.length} numbered {unit}s on the map, or draw your own inside the dashed box. You will see how it has been farmed, what the weather, water, soil and satellite record say about
                    it, and how {Object.keys(region.kb.strategies).length + (region.kb.settings.existing === "from_history" ? 1 : 0)} rotations compare under the priorities you set.
                  </p>
                  <ul className="plain">
                    <li>What you grow now is always one of them, so you can see what changes.</li>
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
              ) : (
                <FieldSummary feature={feature} evidence={field?.evidence ?? null} region={region} onEvidence={showEvidence} onShowSources={() => setModal("sources")} />
              )}
            </div>
          </section>

          {feature && (
            <section className="decide">
              <Priorities region={region} weights={weights} constraints={constraints} scenario={scenario} result={result} existingId={existingId} onWeights={setWeights} onConstraints={setConstraints} onScenario={setScenario}
                onExisting={setExistingId} onReset={reset} />
              {result ? (
                <Strategies result={result} region={region} onEvidence={showEvidence} />
              ) : (
                <section className="block strategies">
                  <div className="loader" aria-hidden="true" />
                  <p>Reading thirty years of weather for this {unit}…</p>
                </section>
              )}
            </section>
          )}
          {feature && field && <Evidence ev={field.evidence} region={region} panel={panel} onPanel={setPanel} />}
        </main>
      )}
      <Footer />
      {modals}
    </div>
  );
}

function Footer() {
  return (
    <footer className="footer">
      <p>
        Built for the 2026 NASA Space Apps Challenge, “Field Shift: Adapting Farms with NASA Data”. Data: NASA POWER, GPM IMERG, SMAP, Landsat, MODIS, SRTM and GRACE; USDA NRCS and NASS; USGS; OpenET; gridMET; India Meteorological
        Department; ISRIC SoilGrids; FAO WaPOR; ESA WorldCover. NASA does not endorse this tool. The rotation libraries have not been reviewed by a local agronomist.
      </p>
    </footer>
  );
}
