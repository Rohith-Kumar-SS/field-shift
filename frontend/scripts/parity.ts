// Runs the browser's scoring engine in Node on the exported static data, for tests/test_parity.py.
// Usage (the test bundles this with esbuild first):
//   node parity.mjs <data dir> <cases.json> <out.json>
// @ts-nocheck
import { readFileSync, writeFileSync } from "node:fs";
import { join } from "node:path";

import { decodeWeather } from "../src/engine/climate";
import { scoreField } from "../src/engine/scoring";

const [dataDir, casesPath, outPath] = process.argv.slice(2);
const cases = JSON.parse(readFileSync(casesPath, "utf-8"));
const cache = new Map();
const json = (p) => {
  if (!cache.has(p)) cache.set(p, JSON.parse(readFileSync(p, "utf-8")));
  return cache.get(p);
};

const out = cases.map((c) => {
  const dir = join(dataDir, c.region);
  const kb = json(join(dir, "kb.json"));
  const region = json(join(dir, "region.json"));
  const field = json(join(dir, "fields", `${c.field_id}.json`));
  const buf = readFileSync(join(dir, "weather", `${c.field_id}.bin`));
  const weather = decodeWeather(buf.buffer.slice(buf.byteOffset, buf.byteOffset + buf.byteLength), region.weather);
  return scoreField({ ctx: field.context, kb, weather, weights: c.weights, constraints: c.constraints, scenario: c.scenario, existingId: c.existing_id ?? null });
});
writeFileSync(outPath, JSON.stringify(out));
