"""Load and validate the rotation knowledge base (knowledge/rotation_knowledge.yaml)."""
from __future__ import annotations

from functools import lru_cache
from pathlib import Path

import yaml

KB_PATH = Path(__file__).resolve().parents[1] / "knowledge" / "rotation_knowledge.yaml"
REQUIRED_TRAITS = ["n_score", "om_score", "root_depth_m", "heat_limit_c", "drought_tolerance", "ky",
                   "frost_free_days_needed", "value_score", "market", "equipment",
                   "establishment_risk", "plantings"]
MARKETS = {"established", "niche", "uncertain"}


class KnowledgeError(ValueError):
    pass


def validate(kb: dict) -> list[str]:
    """Return a list of problems (empty = valid). Used by the tests and at start-up."""
    problems: list[str] = []
    crops = kb.get("crops", {})
    for cid, c in crops.items():
        for key in ("label", "short", "family", "group", "months", "kc", "cover", "traits", "why"):
            if key not in c:
                problems.append(f"crop {cid}: missing '{key}'")
        t = c.get("traits", {})
        for key in REQUIRED_TRAITS:
            if key not in t:
                problems.append(f"crop {cid}: missing trait '{key}'")
        for m, v in c.get("kc", {}).items():
            if not (1 <= int(m) <= 12) or not (0 <= float(v) <= 1.3):
                problems.append(f"crop {cid}: Kc {m}: {v} out of range")
        for m, v in c.get("cover", {}).items():
            if not (1 <= int(m) <= 12) or not (0 <= float(v) <= 1):
                problems.append(f"crop {cid}: cover {m}: {v} out of range")
        for key in ("n_score", "om_score", "drought_tolerance", "value_score", "establishment_risk"):
            if key in t and not (0 <= float(t[key]) <= 1):
                problems.append(f"crop {cid}: {key} must be within 0-1")
        why = c.get("why", {})
        if "kc" not in why:
            problems.append(f"crop {cid}: no source or rationale for kc")
        if not why:
            problems.append(f"crop {cid}: no sources or rationales at all")
    for sid, s in kb.get("strategies", {}).items():
        for key in ("name", "short", "summary", "years", "benefits", "risks", "info_gaps", "verify", "tags"):
            if key not in s:
                problems.append(f"strategy {sid}: missing '{key}'")
        for yi, year in enumerate(s.get("years", []), 1):
            for e in year:
                if e.get("crop") not in crops:
                    problems.append(f"strategy {sid} year {yi}: unknown crop '{e.get('crop')}'")
    total = sum(c.get("default_weight", 0) for c in kb.get("criteria", {}).values())
    if total != 100:
        problems.append(f"default weights sum to {total}, expected 100")
    return problems


@lru_cache(maxsize=1)
def load_kb() -> dict:
    kb = yaml.safe_load(KB_PATH.read_text(encoding="utf-8"))
    problems = validate(kb)
    if problems:
        raise KnowledgeError("; ".join(problems))
    for cid, c in kb["crops"].items():
        c["id"] = cid
        c["kc"] = {int(k): float(v) for k, v in c["kc"].items()}
        c["cover"] = {int(k): float(v) for k, v in c["cover"].items()}
    return kb


def cdl_to_crop(kb: dict) -> dict[int, str]:
    out: dict[int, str] = {}
    for cid, c in kb["crops"].items():
        for code in c.get("cdl_codes", []):
            out[int(code)] = cid
    return out


def entry_months(entry: dict, kb: dict) -> list[int]:
    return list(entry.get("months") or kb["crops"][entry["crop"]]["months"])


def year_profiles(year: list[dict], kb: dict) -> tuple[dict[int, float], dict[int, float]]:
    """Monthly crop coefficient and soil cover for one rotation year (max over its crops)."""
    kc = {m: 0.0 for m in range(1, 13)}
    cover = {m: 0.0 for m in range(1, 13)}
    for e in year:
        crop = kb["crops"][e["crop"]]
        for m in entry_months(e, kb):
            kc[m] = max(kc[m], crop["kc"].get(m, 0.0))
            cover[m] = max(cover[m], crop["cover"].get(m, 0.0))
    return kc, cover


def fill_residue(covers: list[dict[int, float]]) -> list[dict[int, float]]:
    """Months nobody occupies keep half of the previous month's cover as residue (never < 0.1).

    The rotation is treated as a cycle, so December of the last year carries into January
    of the first.
    """
    flat = [covers[y][m] for y in range(len(covers)) for m in range(1, 13)]
    n = len(flat)
    out = flat[:]
    for _ in range(2):                      # second pass closes the cycle
        for i in range(n):
            if flat[i] <= 0.0:
                out[i] = max(0.10, 0.5 * out[i - 1])
    return [{m: round(out[y * 12 + m - 1], 3) for m in range(1, 13)} for y in range(len(covers))]
