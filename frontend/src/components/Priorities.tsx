import { fmt, mmToIn, type Constraints, type Meta, type Scenario, type ScoreResult } from "../api";

interface Props {
  meta: Meta;
  weights: Record<string, number>;
  constraints: Constraints;
  scenario: Scenario;
  result: ScoreResult | null;
  onWeights: (w: Record<string, number>) => void;
  onConstraints: (c: Constraints) => void;
  onScenario: (s: Scenario) => void;
  onReset: () => void;
}

const LEVEL = ["Not important", "A little", "Somewhat", "Important", "Very important", "Top priority"];

export default function Priorities({ meta, weights, constraints, scenario, result, onWeights, onConstraints, onScenario, onReset }: Props) {
  const total = Object.values(weights).reduce((a, b) => a + b, 0) || 1;
  const toggleEquip = (id: string) =>
    onConstraints({
      ...constraints,
      equipment: constraints.equipment.includes(id) ? constraints.equipment.filter((e) => e !== id) : [...constraints.equipment, id],
    });
  const supplyMm = result ? result.water_supply_mm : null;

  return (
    <section className="block priorities">
      <header className="block-head">
        <h2>What matters to you</h2>
        <button className="link-btn" onClick={onReset}>
          Reset
        </button>
      </header>
      <p className="block-lede">Slide each one. The rotations re-rank as you go: there is no single best answer, only the best fit for your priorities.</p>

      <div className="sliders">
        {meta.criteria.map((c) => {
          const v = weights[c.id] ?? 0;
          return (
            <div className="slider" key={c.id}>
              <label htmlFor={`w-${c.id}`}>
                <span className="slider-name">{c.label}</span>
                <span className="slider-share">{Math.round((v / total) * 100)} %</span>
              </label>
              <input id={`w-${c.id}`} type="range" min={0} max={50} step={5} value={v} aria-describedby={`d-${c.id}`}
                aria-valuetext={`${LEVEL[Math.min(5, Math.round(v / 10))]}, ${Math.round((v / total) * 100)} percent of the total`}
                onChange={(e) => onWeights({ ...weights, [c.id]: Number(e.target.value) })} />
              <p id={`d-${c.id}`} className="slider-plain">
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
        <input id="supply" type="range" min={40} max={100} step={5} value={constraints.water_supply_pct}
          onChange={(e) => onConstraints({ ...constraints, water_supply_pct: Number(e.target.value) })} />
        <p className="slider-plain">
          100 % = what full-season alfalfa needs on this field
          {supplyMm !== null && result && (
            <>
              {" "}
              ({fmt(result.full_alfalfa_irrigation_mm)} mm). You have set <strong>{fmt(supplyMm)} mm</strong> ({fmt(mmToIn(supplyMm), 1)} in) a year.
            </>
          )}{" "}
          Where a rotation needs more, its forage score drops.
        </p>
      </div>

      <fieldset className="choices">
        <legend>Equipment I have or can hire</legend>
        {meta.constraints.equipment.map((e) => (
          <label key={e.id} className="check">
            <input type="checkbox" checked={constraints.equipment.includes(e.id)} onChange={() => toggleEquip(e.id)} />
            <span>{e.label}</span>
          </label>
        ))}
      </fieldset>

      <fieldset className="choices">
        <legend>Markets</legend>
        {meta.constraints.market.map((m) => (
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
            {scenario.temp_c} °C ({scenario.temp_c > 0 ? "+" : ""}
            {fmt(scenario.temp_c * 1.8, 1)} °F)
          </span>
        </label>
        <input id="sc-temp" type="range" min={meta.scenario.temp_c.min} max={meta.scenario.temp_c.max} step={meta.scenario.temp_c.step} value={scenario.temp_c}
          onChange={(e) => onScenario({ ...scenario, temp_c: Number(e.target.value) })} />
      </div>
      <div className="slider">
        <label htmlFor="sc-rain">
          <span className="slider-name">Rainfall</span>
          <span className="slider-share">
            {scenario.rain_pct > 0 ? "+" : ""}
            {scenario.rain_pct} %
          </span>
        </label>
        <input id="sc-rain" type="range" min={meta.scenario.rain_pct.min} max={meta.scenario.rain_pct.max} step={meta.scenario.rain_pct.step} value={scenario.rain_pct}
          onChange={(e) => onScenario({ ...scenario, rain_pct: Number(e.target.value) })} />
        <p className="slider-plain">
          Shifts every day of the 1991–2025 weather record and recomputes water demand, hot days and frost dates. A sensitivity test, not a climate forecast.
        </p>
      </div>
    </section>
  );
}
