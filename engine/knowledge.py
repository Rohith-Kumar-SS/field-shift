"""Load and validate a region's rotation knowledge base (knowledge/<region>.yaml)."""
from __future__ import annotations

from functools import lru_cache
from pathlib import Path

import yaml

KB_DIR = Path(__file__).resolve().parents[1] / "knowledge"
DEFAULT_REGION = "diamond_valley_nv"
REQUIRED_TRAITS = ["n_score", "om_score", "root_depth_m", "heat_limit_c", "drought_tolerance", "ky",
                   "frost_free_days_needed", "value_score", "market", "equipment",
                   "establishment_risk", "plantings"]
CRITERIA = ["water", "cover", "nitrogen", "organic_matter", "pest_break", "income", "resilience", "feasibility"]
# market class -> factor under the farmer's three market settings
MARKET_FACTOR = {
    "assured": {"established_only": 1.0, "some": 1.0, "open": 1.0},
    "established": {"established_only": 1.0, "some": 1.0, "open": 1.0},
    "niche": {"established_only": 0.5, "some": 0.8, "open": 1.0},
    "uncertain": {"established_only": 0.2, "some": 0.5, "open": 0.8},
}
# Where some crops have an assured (support-price) buyer, "established" crops are the risky ones
MARKET_FACTOR_WITH_ASSURED = {**MARKET_FACTOR,
                              "established": {"established_only": 0.6, "some": 0.9, "open": 1.0}}


class KnowledgeError(ValueError):
    pass


def regions() -> list[str]:
    return sorted(p.stem for p in KB_DIR.glob("*.yaml"))


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
    for sid, s in kb.get("strategies", {}).items():
        for key in ("name", "short", "summary", "years", "benefits", "risks", "info_gaps", "verify", "tags"):
            if key not in s:
                problems.append(f"strategy {sid}: missing '{key}'")
        for yi, year in enumerate(s.get("years", []), 1):
            for e in year:
                if e.get("crop") not in crops:
                    problems.append(f"strategy {sid} year {yi}: unknown crop '{e.get('crop')}'")
                elif e.get("months") and not set(e["months"]) <= set(crops[e["crop"]]["months"]) | set(crops[e["crop"]]["cover"]):
                    problems.append(f"strategy {sid} year {yi}: {e['crop']} given months outside its calendar")
    crit = kb.get("criteria", {})
    if sorted(crit) != sorted(CRITERIA):
        problems.append(f"criteria must be exactly {CRITERIA}")
    total = sum(c.get("default_weight", 0) for c in crit.values())
    if total != 100:
        problems.append(f"default weights sum to {total}, expected 100")
    st = kb.get("settings", {})
    for key in ("existing", "pest_model", "stand_crops", "water_reference", "heavy_rain_mm", "hot_day_c",
                "heat_days_full", "equipment", "default_equipment", "market"):
        if key not in st:
            problems.append(f"settings: missing '{key}'")
    if st.get("existing") == "choose":
        d = st.get("existing_default")
        if d not in kb.get("strategies", {}):
            problems.append("settings.existing_default must name a strategy")
        if not any(s.get("existing_option") for s in kb.get("strategies", {}).values()):
            problems.append("no strategy is marked existing_option")
    ref = st.get("water_reference", {})
    if "strategy" in ref and ref["strategy"] not in kb.get("strategies", {}):
        problems.append("settings.water_reference.strategy must name a strategy")
    eq = {e["id"] for e in st.get("equipment", [])}
    for cid, c in crops.items():
        for need in c.get("traits", {}).get("equipment", []):
            if need not in eq:
                problems.append(f"crop {cid}: equipment '{need}' is not in settings.equipment")
    return problems


@lru_cache(maxsize=8)
def load_kb(region: str = DEFAULT_REGION) -> dict:
    path = KB_DIR / f"{region}.yaml"
    if not path.exists():
        raise KnowledgeError(f"No knowledge base for region '{region}' ({path.name})")
    kb = yaml.safe_load(path.read_text(encoding="utf-8"))
    problems = validate(kb)
    if problems:
        raise KnowledgeError(f"{path.name}: " + "; ".join(problems))
    kb["region"] = region
    for cid, c in kb["crops"].items():
        c["id"] = cid
        c["kc"] = {int(k): float(v) for k, v in c["kc"].items()}
        c["cover"] = {int(k): float(v) for k, v in c["cover"].items()}
        c.setdefault("perennial", False)
        c.setdefault("irrigated", True)
    for sid, s in kb["strategies"].items():
        s["id"] = sid
    has_assured = any(c["traits"]["market"] == "assured" for c in kb["crops"].values())
    kb["market_factor"] = MARKET_FACTOR_WITH_ASSURED if has_assured else MARKET_FACTOR
    return kb


def reference_years(kb: dict) -> list[list[dict]]:
    """The rotation whose irrigation need is the yardstick for the water score."""
    ref = kb["settings"]["water_reference"]
    return ref["years"] if "years" in ref else kb["strategies"][ref["strategy"]]["years"]


def cdl_to_crop(kb: dict) -> dict[int, str]:
    out: dict[int, str] = {}
    for cid, c in kb["crops"].items():
        for code in c.get("cdl_codes", []):
            out[int(code)] = cid
    return out


def entry_months(entry: dict, kb: dict) -> list[int]:
    return list(entry.get("months") or kb["crops"][entry["crop"]]["months"])


def year_profiles(year: list[dict], kb: dict) -> tuple[dict[int, float], dict[int, float]]:
    """Monthly crop coefficient (irrigated crops only) and soil cover for one rotation year."""
    kc = {m: 0.0 for m in range(1, 13)}
    cover = {m: 0.0 for m in range(1, 13)}
    for e in year:
        crop = kb["crops"][e["crop"]]
        for m in entry_months(e, kb):
            if crop.get("irrigated", True):
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
