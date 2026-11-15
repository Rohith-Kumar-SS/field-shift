import { fmt, mm, type Constraints, type Dict, type RegionData, type Scenario } from "../data";

interface Props {
  region: RegionData;
  weights: Record<string, number>;
  constraints: Constraints;
  scenario: Scenario;
  result: Dict | null;
  existingId: string | null;
  onWeights: (w: Record<string, number>) => void;
  onConstraints: (c: Constraints) => void;
  onScenario: (s: Scenario) => void;
  onExisting: (id: string | null) => void;
  onReset: () => void;
}

const LEVEL = ["Not important", "A little", "Somewhat", "Important", "Very important", "Top priority"];

/** A range input whose filled part is drawn with a CSS variable, so the track itself shows the value. */
function Range({ id, min, max, step, value, onChange, describedBy, valueText }: {
  id: string; min: number; max: number; step: number; value: number; onChange: (v: number) => void; describedBy?: string; valueText?: string;
}) {
  const pct = ((value - min) / (max - min)) * 100;
  return <input id={id} type="range" min={min} max={max} step={step} value={value} aria-describedby={describedBy} aria-valuetext={valueText}
    style={{ ["--fill" as any]: `${pct}%` }} onChange={(e) => onChange(Number(e.target.value))} />;
}

export default function Priorities({ region, weights, constraints, scenario, result, existingId, onWeights, onConstraints, onScenario, onExisting, onReset }: Props) {
  const kb = region.kb;
  const imperial = Boolean(region.region.imperial);
  const total = Object.values(weights).reduce((a, b) => a + b, 0) || 1;
  const toggleEquip = (id: string) =>
    onConstraints({ ...constraints, equipment: constraints.equipment.includes(id) ? constraints.equipment.filter((e) => e !== id) : [...constraints.equipment, id] });
  const options = Object.values(kb.strategies).filter((s) => s.existing_option);
  const chosen = result?.existing?.chosen ?? existingId ?? kb.settings.existing_default;
  const refLabel: string = kb.settings.water_reference.label;

  return (
    <section className="block priorities" id="priorities">
      <header className="block-head">
        <h2>What matters to you</h2>
        <button className="link-btn" onClick={onReset}>
          Reset
        </button>
      </header>
      <p className="block-lede">Slide each one. The rotations re-rank as you go: there is no single best answer, only the best fit for your priorities.</p>

      {kb.settings.existing === "choose" && (
        <div className="now-pick">
          <label htmlFor="now">What I grow now</label>
          <select id="now" value={chosen} onChange={(e) => onExisting(e.target.value)}>
            {options.map((s) => (
              <option key={s.id} value={s.id}>
                {s.name}
              </option>
            ))}
          </select>
          {(result?.existing?.assumptions ?? []).map((a: string) => (
            <p className="slider-plain" key={a}>
              {a}
            </p>
          ))}
        </div>
      )}

      <div className="sliders">
        {Object.entries(kb.criteria).map(([id, c]) => {
          const v = weights[id] ?? 0;
          return (
            <div className="slider" key={id}>
              <label htmlFor={`w-${id}`}>
                <span className="slider-name">{c.label}</span>
                <span className="slider-share">{Math.round((v / total) * 100)} %</span>
              </label>
              <Range id={`w-${id}`} min={0} max={50} step={5} value={v} describedBy={`d-${id}`}
                valueText={`${LEVEL[Math.min(5, Math.round(v / 10))]}, ${Math.round((v / total) * 100)} percent of the total`} onChange={(n) => onWeights({ ...weights, [id]: n })} />
              <p id={`d-${id}`} className="slider-plain">
                {c.plain}
              </p>
            </div>
          );
        })}
      </div>

      <h3 className="sub">Your limits</h3>
      <div className="slider">
        <label htmlFor="supply">
          <span className="slider-name">Water I can count on</span>
          <span className="slider-share">{constraints.water_supply_pct} %</span>
        </label>
        <Range id="supply" min={40} max={100} step={5} value={constraints.water_supply_pct} onChange={(n) => onConstraints({ ...constraints, water_supply_pct: n })} />
        <p className="slider-plain">
          100 % = what {refLabel} needs on this field
          {result && (
            <>
              {" "}
              ({fmt(result.reference_irrigation_mm)} mm). You have set <strong>{mm(result.water_supply_mm, imperial)}</strong> a year.
            </>
          )}{" "}
          Where a rotation needs more, its income score drops.
        </p>
      </div>

      <fieldset className="choices">
        <legend>Equipment I have or can hire</legend>
        {(kb.settings.equipment as Dict[]).map((e) => (
          <label key={e.id} className="check">
            <input type="checkbox" checked={constraints.equipment.includes(e.id)} onChange={() => toggleEquip(e.id)} />
            <span>{e.label}</span>
          </label>
        ))}
      </fieldset>

      <fieldset className="choices">
        <legend>Markets</legend>
        {(kb.settings.market as Dict[]).map((m) => (
          <label key={m.id} className="check">
            <input type="radio" name="market" checked={constraints.market === m.id} onChange={() => onConstraints({ ...constraints, market: m.id })} />
            <span>{m.label}</span>
          </label>
        ))}
      </fieldset>

      <h3 className="sub">What if the weather changes?</h3>
      <div className="slider">
        <label htmlFor="sc-temp">
          <span className="slider-name">Warmer by</span>
          <span className="slider-share">
            {scenario.temp_c > 0 ? "+" : ""}
            {scenario.temp_c} °C{imperial ? ` (${scenario.temp_c > 0 ? "+" : ""}${fmt(scenario.temp_c * 1.8, 1)} °F)` : ""}
          </span>
        </label>
        <Range id="sc-temp" min={region.scenario.temp_c.min} max={region.scenario.temp_c.max} step={region.scenario.temp_c.step} value={scenario.temp_c} onChange={(n) => onScenario({ ...scenario, temp_c: n })} />
      </div>
      <div className="slider">
        <label htmlFor="sc-rain">
          <span className="slider-name">Rainfall</span>
          <span className="slider-share">
            {scenario.rain_pct > 0 ? "+" : ""}
            {scenario.rain_pct} %
          </span>
        </label>
        <Range id="sc-rain" min={region.scenario.rain_pct.min} max={region.scenario.rain_pct.max} step={region.scenario.rain_pct.step} value={scenario.rain_pct} onChange={(n) => onScenario({ ...scenario, rain_pct: n })} />
        <p className="slider-plain">Shifts every day of the 1996–2025 weather record and recomputes water demand, hot days and frost dates. A sensitivity test, not a climate forecast.</p>
      </div>
    </section>
  );
}
