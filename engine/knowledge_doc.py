"""Write ROTATION_KNOWLEDGE.md from knowledge/rotation_knowledge.yaml, so the document can
never drift from the values the engine actually uses.

    python -m engine.knowledge_doc
"""
from __future__ import annotations

from pathlib import Path

from .knowledge import entry_months, load_kb

ROOT = Path(__file__).resolve().parents[1]
MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]

FORMULAS = [
    ("Save water", "`score = 2 x (1 - irrigation need / full-alfalfa irrigation need)`, limited to 0-1",
     "Irrigation need = sum over months of `Kc x reference ET x field factor` minus effective rain "
     "(USDA-SCS method), averaged over the rotation. Reference ET is FAO-56 Penman-Monteith from NASA POWER "
     "daily weather, bias-corrected to gridMET. The field factor is the median ratio of OpenET satellite ET to "
     "the textbook figure in that field's own alfalfa years (limited to 0.6-1.15; 1.0 if there is no OpenET "
     "record). 0 = as thirsty as full-season alfalfa on that field, 1 = half the water or less."),
    ("Keep soil covered", "`score = sum over months of (risk weight x share of soil covered)`",
     "Risk weights sum to 1 over the year. They combine windy days (daily mean wind >= 4.5 m/s at 2 m, NASA "
     "POWER) scaled by the soil's wind-erodibility index (SSURGO), and heavy-rain days (>= 10 mm) scaled by "
     "field tilt (SRTM) and the K factor (SSURGO). Cover comes from each crop's monthly cover table; months "
     "nobody occupies keep half of the previous month's cover as residue, never below 0.1."),
    ("Nitrogen from legumes", "legume year = its `n_score`; first year after alfalfa 0.6; second 0.3; a legume "
     "cover crop adds up to 0.5", "Averaged over the rotation."),
    ("Build organic matter", "`sum of om_score x share of the crop's season - 0.08 per sowing`",
     "Averaged over the rotation. Class scores only: organic matter cannot be seen from space."),
    ("Break pest cycles", "`0.45 x break + 0.35 x diversity + 0.20 x stand age`",
     "Break: 0 if alfalfa follows alfalfa, 0.6 for a one-year gap, 1.0 for two or more. Diversity: (number "
     "of plant groups - 1) / 3. Stand age: 1.0 up to 5 years, falling to 0 at 10."),
    ("Forage and income", "`sum of value_score x share of season x market factor`, reduced by water shortage",
     "Market factor: established 1.0; niche 0.5 / 0.8 / 1.0 and uncertain 0.2 / 0.5 / 0.8 for the three market "
     "settings. Where a year needs more irrigation than the farmer's stated supply, relative yield is "
     "`1 - Ky x (1 - ETa / ETc)` (FAO-33). No prices are used."),
    ("Drought and heat resilience", "`0.5 x drought_tolerance + 0.5 x (1 - days above the crop's heat limit in "
     "its season / 45)`", "Weighted by each crop's share of the year, averaged over the rotation."),
    ("Easy to carry out", "`0.45 x season fit + 0.30 x equipment available + 0.25 x (1 - establishment risk)`, "
     "minus 0.05 per extra sowing in a year",
     "Season fit = share of the last 30 years whose frost-free season was at least as long as the crop needs."),
]


def table(headers: list[str], rows: list[list]) -> list[str]:
    out = ["| " + " | ".join(headers) + " |", "| " + " | ".join(":--" for _ in headers) + " |"]
    out += ["| " + " | ".join("" if c is None else str(c) for c in r) + " |" for r in rows]
    return out + [""]


def month_span(months: list[int]) -> str:
    months = sorted(months)
    return MONTHS[months[0] - 1] if len(months) == 1 else f"{MONTHS[months[0] - 1]}-{MONTHS[months[-1] - 1]}"


def main() -> None:
    kb = load_kb()
    L: list[str] = [
        "# ROTATION_KNOWLEDGE", "",
        "The rotation knowledge base behind the Rotation Scenario Explorer. **Generated from "
        "`knowledge/rotation_knowledge.yaml` by `python -m engine.knowledge_doc`; edit the YAML, not this file.**",
        "", "## How to read it", "",
        "- Every value is either taken from a cited reference or is a class score assigned by this project, "
        "with the reasoning given. Entries tagged PROJECT are judgments, not measurements.",
        "- Class scores run from 0 (none / worst) to 1 (most / best). They are **not calibrated to Diamond "
        "Valley** and each is a prompt for local review.",
        "- Kc is the monthly crop coefficient on a grass reference (FAO-56): crop water demand = Kc x reference ET.",
        "- Cover is the share of the soil surface protected by canopy, stubble or residue.",
        "- " + kb["region_note"].strip(), "",
        "## How each priority is scored", "",
    ]
    L += table(["Priority", "Formula", "Details"], [[a, b, c] for a, b, c in FORMULAS])
    L += ["Overall score = sum of (weight x score), with the farmer's slider values normalised to sum to 1. "
          "The code is `engine/scoring.py`; the tests are `tests/test_scoring.py`.", "",
          "## Crop summary", ""]
    rows = []
    for c in kb["crops"].values():
        t = c["traits"]
        rows.append([c["label"], c["group"], t["root_depth_m"], t["ky"], t["heat_limit_c"],
                     t["frost_free_days_needed"] or "-", t["n_score"], t["om_score"], t["drought_tolerance"],
                     t["value_score"], t["market"], ", ".join(t["equipment"]) or "-",
                     t.get("salt_threshold_ds_m") or "-"])
    L += table(["Crop", "Group", "Root depth (m)", "Ky", "Heat limit (°C)", "Frost-free days needed", "N",
                "Organic matter", "Drought tolerance", "Value", "Market", "Equipment", "Salt threshold (dS/m)"], rows)

    L += ["## Crops in detail", ""]
    for c in kb["crops"].values():
        L += [f"### {c['label']}", "", f"Family: {c['family']}. Group: {c['group']}. "
              f"{'Perennial' if c.get('perennial') else 'Annual'}. USDA crop-map codes: "
              f"{', '.join(str(x) for x in c.get('cdl_codes', [])) or 'none'}.", ""]
        L += table([""] + MONTHS, [["Kc"] + [c["kc"].get(m, "") for m in range(1, 13)],
                                   ["Cover"] + [c["cover"].get(m, "") for m in range(1, 13)]])
        why = c["why"]
        rows = [["crop coefficient (Kc)", "see table", why.get("kc", "")]]
        if why.get("cover"):
            rows.append(["soil cover", "see table", why["cover"]])
        for k, v in c["traits"].items():
            val = " to ".join(str(x) for x in v) if isinstance(v, list) and k == "n_credit_kg_ha" else (
                ", ".join(v) if isinstance(v, list) else ("not documented" if v is None else v))
            reason = why.get(k)
            if reason is None:
                reason = {"ky": why.get("drought_tolerance"), "n_credit_kg_ha": why.get("n_score"),
                          "market": why.get("value_score"), "salt_class": why.get("salt_threshold_ds_m")
                          or why.get("salt_class")}.get(k)
            rows.append([k.replace("_", " "), val, reason or "PROJECT class value; see the crop's other notes."])
        L += table(["Trait", "Value", "Source or rationale"], rows)

    L += ["## Rotation strategies", "",
          "The existing rotation is always read from the field's own crop history (USDA crop map checked "
          "against Landsat greenness) and compared with these four.", ""]
    for sid, s in kb["strategies"].items():
        L += [f"### {s['name']}", "", f"`{sid}` - {' '.join(s['summary'].split())}", ""]
        rows = []
        for i, year in enumerate(s["years"], 1):
            parts = [f"{kb['crops'][e['crop']]['short']} ({month_span(entry_months(e, kb))})" for e in year]
            rows.append([i, "; ".join(parts)])
        L += table(["Year", "What is in the field"], rows)
        for title, key in (("May offer", "benefits"), ("Risks needing local review", "risks"),
                           ("Information gaps", "info_gaps"), ("Check with a local expert", "verify")):
            L += [f"**{title}**", ""] + [f"- {x}" for x in s[key]] + [""]

    L += ["## Always check locally", ""] + [f"- {x}" for x in kb["always_verify"]] + [""]
    L += ["## References", ""] + [f"- **{k}**: {v}" for k, v in kb["references"].items()] + [""]
    (ROOT / "ROTATION_KNOWLEDGE.md").write_text("\n".join(L), encoding="utf-8")
    print(f"ROTATION_KNOWLEDGE.md written ({len(kb['crops'])} crops, {len(kb['strategies'])} strategies)")


if __name__ == "__main__":
    main()
