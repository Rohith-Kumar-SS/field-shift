"""The browser's TypeScript scoring engine must agree with the Python reference.

Both are run on the exported static data (frontend/public/data): the same field context,
the same 16-bit daily weather file, the same knowledge base. Scores must match to three
decimals, millimetres to +-1, and every sentence word for word (numbers inside sentences
get the same +-1 allowance for rounding at the last digit).

Skipped when Node or the exported data are not there (`python tasks.py data export`).
"""
from __future__ import annotations

import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest

from engine import static_data
from engine.climate import Scenario
from engine.knowledge import load_kb
from engine.scoring import score_field

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "frontend" / "public" / "data"
ESBUILD = ROOT / "frontend" / "node_modules" / "esbuild" / "bin" / "esbuild"
NUM = re.compile(r"-?\d+(?:\.\d+)?")

VARIANTS = [
    {},
    {"weights": {"water": 100}},
    {"weights": {"income": 60, "pest_break": 20, "cover": 20},
     "constraints": {"water_supply_pct": 60, "market": "established_only", "equipment": []}},
    {"scenario": {"rain_pct": -30, "temp_c": 3}},
    {"scenario": {"rain_pct": 20, "temp_c": 1.5}, "constraints": {"water_supply_pct": 130, "market": "open"}},
    {"existing_alt": True},
]


def build_cases() -> list[dict]:
    cases = []
    if not (DATA / "regions.json").exists():
        return cases
    for region in json.loads((DATA / "regions.json").read_text(encoding="utf-8")):
        rid = region["id"]
        kb = load_kb(rid)
        ids = sorted(p.stem for p in (DATA / rid / "fields").glob("*.json"))
        options = [sid for sid, s in kb["strategies"].items() if s.get("existing_option")]
        for fid in (ids[0], ids[len(ids) // 2], ids[-1]):
            for v in VARIANTS:
                case = {"region": rid, "field_id": fid, "weights": v.get("weights"),
                        "constraints": v.get("constraints"), "scenario": v.get("scenario"), "existing_id": None}
                if v.get("existing_alt"):
                    if not options:
                        continue
                    case["existing_id"] = options[-1]
                cases.append(case)
    return cases


def close(a, b, path: str) -> list[str]:
    """Differences between two JSON values, with tolerances for rounding at the last digit."""
    if isinstance(a, bool) or isinstance(b, bool) or a is None or b is None:
        return [] if a == b else [f"{path}: {a!r} != {b!r}"]
    if isinstance(a, (int, float)) and isinstance(b, (int, float)):
        tol = 1.0001 if (float(a).is_integer() and float(b).is_integer() and abs(a) > 3) else 0.0021 if abs(a) <= 3 else 0.11
        return [] if abs(a - b) <= tol else [f"{path}: {a} != {b}"]
    if isinstance(a, str) and isinstance(b, str):
        if a == b:
            return []
        if NUM.sub("#", a) != NUM.sub("#", b):
            return [f"{path}: {a!r} != {b!r}"]
        na, nb = [float(x) for x in NUM.findall(a)], [float(x) for x in NUM.findall(b)]
        return [] if all(abs(x - y) <= 1.0001 for x, y in zip(na, nb)) else [f"{path}: {a!r} != {b!r}"]
    if isinstance(a, dict) and isinstance(b, dict):
        out = [f"{path}: keys differ: {sorted(set(a) ^ set(b))}"] if set(a) != set(b) else []
        for k in a.keys() & b.keys():
            out += close(a[k], b[k], f"{path}.{k}")
        return out
    if isinstance(a, list) and isinstance(b, list):
        if len(a) != len(b):
            return [f"{path}: length {len(a)} != {len(b)}"]
        out = []
        for i, (x, y) in enumerate(zip(a, b)):
            out += close(x, y, f"{path}[{i}]")
        return out
    return [f"{path}: type {type(a).__name__} != {type(b).__name__}"]


@pytest.mark.skipif(not (DATA / "regions.json").exists(), reason="static data not exported")
@pytest.mark.skipif(shutil.which("node") is None or not ESBUILD.exists(), reason="Node / frontend packages not installed")
def test_browser_engine_matches_python_reference(tmp_path):
    cases = build_cases()
    assert len(cases) >= 10
    bundle = tmp_path / "parity.mjs"
    subprocess.run(["node", str(ESBUILD), str(ROOT / "frontend" / "scripts" / "parity.ts"), "--bundle",
                    "--platform=node", "--format=esm", f"--outfile={bundle}", "--log-level=error"],
                   check=True, cwd=ROOT / "frontend")
    (tmp_path / "cases.json").write_text(json.dumps(cases), encoding="utf-8")
    subprocess.run(["node", str(bundle), str(DATA), str(tmp_path / "cases.json"), str(tmp_path / "out.json")],
                   check=True)
    browser = json.loads((tmp_path / "out.json").read_text(encoding="utf-8"))

    problems = []
    for case, got in zip(cases, browser):
        rid, fid = case["region"], case["field_id"]
        ctx = json.loads((DATA / rid / "fields" / f"{fid}.json").read_text(encoding="utf-8"))["context"]
        ctx["power"] = {"base": static_data.decode(DATA / rid / "weather" / f"{fid}.bin")}
        sc = case["scenario"] or {}
        want = score_field(ctx, load_kb(rid), case["weights"], case["constraints"],
                           Scenario(rain_pct=sc.get("rain_pct", 0), temp_c=sc.get("temp_c", 0)),
                           existing_id=case["existing_id"])
        want = json.loads(json.dumps(want))            # same shape as the browser's JSON
        assert got["ranking"] == want["ranking"], f"{rid} {fid} {case}: ranking differs"
        diffs = close(want, got, f"{rid}/{fid}")
        problems += [f"{d}   [case: weights={case['weights']} constraints={case['constraints']} "
                     f"scenario={case['scenario']} existing={case['existing_id']}]" for d in diffs[:6]]
    assert not problems, "\n".join(problems[:40])
