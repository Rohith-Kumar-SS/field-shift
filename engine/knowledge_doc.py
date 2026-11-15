"""Write ROTATION_KNOWLEDGE.md from knowledge/<region>.yaml, so the document can never drift
from the values the engine actually uses.

    python -m engine.knowledge_doc
"""
from __future__ import annotations

from pathlib import Path

from .knowledge import entry_months, load_kb, regions

ROOT = Path(__file__).resolve().parents[1]
MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]


def formulas(kb: dict) -> list[list[str]]:
    st = kb["settings"]
    ref = st["water_reference"]["label"]
    stand = st["pest_model"] == "stand"
    labels = {cid: c["label"] for cid, c in kb["criteria"].items()}
    return [
        [labels["water"], f"`score = 2 x (1 - irrigation to deliver / {ref} irrigation to deliver)`, limited to 0-1",
         "Irrigation to deliver = sum over months of `Kc x reference ET x field factor` minus effective rain "
         "(USDA-SCS method), plus the water a paddy field takes to be puddled and kept flooded "
         "(`extra_water_mm`, zero for every other crop), averaged over the rotation. Reference ET is FAO-56 "
         "Penman-Monteith from NASA POWER daily weather, corrected month by month to a ground-station grid. "
         "The field factor is 1.0 unless the region has a crop map and satellite ET to anchor it. "
         f"0 = as thirsty as {ref} on that field, 1 = half the water or less."],
        [labels["cover"], "`score = sum over months of (risk weight x share of soil covered)`",
         f"Risk weights sum to 1 over the year. They combine windy days (daily mean wind >= {st.get('windy_ms', 4.5)} "
         "m/s at 2 m) scaled by the soil's wind-erodibility index, and heavy-rain days "
         f"(>= {st['heavy_rain_mm']} mm) scaled by field tilt (SRTM) and the soil K factor. Cover comes from each "
         "crop's monthly cover table; months nobody occupies keep half of the previous month's cover as residue, "
         "never below 0.1."],
        [labels["nitrogen"],
         "legume year = its `n_score`; first year after the stand 0.6; second 0.3; a legume cover crop adds up to 0.5"
         if stand else "`sum of n_score x share of the crop's season`, limited to 1",
         "Averaged over the rotation."],
        [labels["organic_matter"], "`sum of om_score x share of the crop's season - 0.08 per sowing`",
         "Averaged over the rotation. Class scores only: organic matter cannot be seen from space."],
        [labels["pest_break"],
         "`0.45 x break + 0.35 x diversity + 0.20 x stand age`" if stand else
         "`0.35 x diversity + 0.30 x change + 0.35 x hand-overs`",
         "Break: 0 if the stand follows itself, 0.6 for a one-year gap, 1.0 for two or more. Diversity: (number of "
         "plant groups - 1) / 3. Stand age: 1.0 up to 5 years, falling to 0 at 10." if stand else
         "Diversity: (number of plant groups - 1) / 3. Change: share of crops that differ from one year to the "
         "next. Hand-overs: share of crop-to-crop hand-overs that are not cereal after cereal."],
        [labels["income"], "`sum of value_score x share of season x market factor`, reduced by water shortage",
         "Market factor depends on the crop's market class and the farmer's market setting. Where a year needs "
         "more irrigation than the farmer's stated supply, the shortfall is shared in proportion and relative "
         "yield is `1 - Ky x (1 - ETa / ETc)` (FAO-33). No prices are used."],
        [labels["resilience"], "`0.5 x drought_tolerance + 0.5 x (1 - days above the crop's heat limit in its "
         f"season / {st['heat_days_full']})`", "Weighted by each crop's share of the year, averaged over the rotation."],
        [labels["feasibility"], "`0.45 x season fit + 0.30 x equipment available + 0.25 x (1 - establishment risk)`, "
         "minus 0.05 per extra sowing in a year",
         "Season fit = share of the last 30 years whose frost-free season was at least as long as the crop needs "
         "(always 1 where frost does not limit crops)."],
    ]


def table(headers: list[str], rows: list[list]) -> list[str]:
    out = ["| " + " | ".join(headers) + " |", "| " + " | ".join(":--" for _ in headers) + " |"]
    out += ["| " + " | ".join("" if c is None else str(c) for c in r) + " |" for r in rows]
    return out + [""]


def month_span(months: list[int]) -> str:
    months = sorted(months)
    return MONTHS[months[0] - 1] if len(months) == 1 else f"{MONTHS[months[0] - 1]}-{MONTHS[months[-1] - 1]}"


def region_section(rid: str) -> list[str]:
    kb = load_kb(rid)
    st = kb["settings"]
    L = [f"# Region: `{rid}`", "", " ".join(kb["region_note"].split()), "",
         f"- Existing rotation: **{'read from the crop map and greenness record' if st['existing'] == 'from_history' else 'chosen by the farmer (default suggested from the number of green seasons seen from space)'}**",
         f"- Water yardstick: **{st['water_reference']['label']}**",
         f"- Hot day: above **{st['hot_day_c']} °C**; heavy-rain day: **{st['heavy_rain_mm']} mm** or more", "",
         "## How each priority is scored", ""]
    L += table(["Priority", "Formula", "Details"], formulas(kb))
    L += ["Overall score = sum of (weight x score), with the farmer's slider values normalised to sum to 1. "
          "Reference code: `engine/scoring.py`; browser port: `frontend/src/engine/scoring.ts`; the two are "
          "compared by `tests/test_parity.py`.", "", "## Crop summary", ""]
    rows = []
    for c in kb["crops"].values():
        t = c["traits"]
        rows.append([c["label"], c["group"], t["root_depth_m"], t["ky"], t["heat_limit_c"],
                     t["frost_free_days_needed"] or "-", t["n_score"], t["om_score"], t["drought_tolerance"],
                     t["value_score"], t["market"], ", ".join(t["equipment"]) or "-",
                     t.get("salt_threshold_ds_m") or "-", t.get("extra_water_mm") or "-"])
    L += table(["Crop", "Group", "Root depth (m)", "Ky", "Heat limit (°C)", "Frost-free days needed", "N",
                "Organic matter", "Drought tolerance", "Value", "Market", "Equipment", "Salt threshold (dS/m)",
                "Flooding water (mm)"], rows)

    L += ["## Crops in detail", ""]
    for c in kb["crops"].values():
        L += [f"### {c['label']}", "", f"Family: {c['family']}. Group: {c['group']}. "
              f"{'Perennial' if c.get('perennial') else 'Annual'}."
              + ("" if c.get("irrigated", True) else " Grown on leftover soil moisture: adds no irrigation need.")
              + (f" USDA crop-map codes: {', '.join(str(x) for x in c['cdl_codes'])}." if c.get("cdl_codes") else ""), ""]
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

    L += ["## Rotation strategies", ""]
    for sid, s in kb["strategies"].items():
        L += [f"### {s['name']}", "", f"`{sid}`{' (can be chosen as the existing rotation)' if s.get('existing_option') else ''} - "
              f"{' '.join(s['summary'].split())}", ""]
        rows = []
        for i, year in enumerate(s["years"], 1):
            parts = [f"{kb['crops'][e['crop']]['short']} ({month_span(entry_months(e, kb))})" for e in year]
            rows.append([i, "; ".join(parts)])
        L += table(["Year", "What is in the field"], rows)
        for title, key in (("May offer", "benefits"), ("Risks needing local review", "risks"),
                           ("Information gaps", "info_gaps"), ("Check with a local expert", "verify")):
            L += [f"**{title}**", ""] + [f"- {x}" for x in s[key]] + [""]

    L += ["## Always check locally", ""] + [f"- {x}" for x in kb["always_verify"]] + [""]
    L += ["## References", ""] + [f"- **{k}**: {v}" for k, v in kb["references"].items()] + ["", "---", ""]
    return L


def main() -> None:
    L: list[str] = [
        "# ROTATION_KNOWLEDGE", "",
        "The rotation knowledge bases behind the Rotation Scenario Explorer, one per pilot region. **Generated from "
        "`knowledge/<region>.yaml` by `python -m engine.knowledge_doc`; edit the YAML, not this file.**",
        "", "## How to read it", "",
        "- Every value is either taken from a cited reference or is a class score assigned by this project, "
        "with the reasoning given. Entries tagged PROJECT are judgments, not measurements.",
        "- Class scores run from 0 (none / worst) to 1 (most / best). They are **not calibrated locally and have "
        "not been reviewed by a local agronomist**: each is a prompt for local review.",
        "- Kc is the monthly crop coefficient on a grass reference (FAO-56): crop water demand = Kc x reference ET.",
        "- Cover is the share of the soil surface protected by canopy, stubble or residue.", "", "---", "",
    ]
    ids = regions()
    for rid in ids:
        L += region_section(rid)
    (ROOT / "ROTATION_KNOWLEDGE.md").write_text("\n".join(L), encoding="utf-8")
    print(f"ROTATION_KNOWLEDGE.md written ({len(ids)} regions)")


if __name__ == "__main__":
    main()
