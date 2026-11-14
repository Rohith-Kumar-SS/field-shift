"""Turn the satellite crop map into a usable crop history - and say where it is doubtful.

The USDA Cropland Data Layer is a classification, not a record. On irrigated pivots it
sometimes reports "shrubland", "forest" or "wetland" for a year. Landsat greenness is used
as a second opinion:

  * map says non-crop and the field stayed brown (peak NDVI < 0.35)  -> idle year (consistent)
  * map says non-crop but the field was as green as a crop (>= 0.60) -> doubtful label; the
    crop is taken from the neighbouring years and the year is flagged for the farmer
  * map says a crop but the field stayed brown                       -> flagged as doubtful
"""
from __future__ import annotations

from .knowledge import cdl_to_crop

GREEN, BROWN = 0.60, 0.35


def interpret_history(cdl_rows: list[dict], peak_ndvi: dict[int, float], kb: dict) -> list[dict]:
    """One interpreted record per year, oldest first."""
    mapping = cdl_to_crop(kb)
    noncrop = set(kb["cdl_noncrop_codes"])
    grass = set(kb["cdl_grass_codes"])
    rows = sorted(cdl_rows, key=lambda r: r["year"])
    out: list[dict] = []
    for r in rows:
        code, year = int(r["cdl_code"]), int(r["year"])
        peak = peak_ndvi.get(year)
        crop = mapping.get(code)
        rec = {"year": year, "cdl_code": code, "cdl_name": r["cdl_name"],
               "share": r.get("share"), "peak_ndvi": None if peak is None else round(float(peak), 2),
               "doubtful": False, "note": ""}
        if code in noncrop or crop == "fallow":
            if peak is None:
                rec.update(crop="fallow", doubtful=True,
                           note=f"Crop map says '{r['cdl_name']}'; no greenness record to check it.")
            elif peak >= GREEN:
                rec.update(crop=None, doubtful=True,
                           note=f"Crop map says '{r['cdl_name']}', but the field was as green as an "
                                f"irrigated crop (peak NDVI {peak:.2f}). The label is probably wrong.")
            elif peak < BROWN:
                rec.update(crop="fallow",
                           note=f"Crop map says '{r['cdl_name']}' and the field stayed brown "
                                f"(peak NDVI {peak:.2f}): treated as an idle year.")
            else:
                rec.update(crop="fallow", doubtful=True,
                           note=f"Crop map says '{r['cdl_name']}'; greenness was in between "
                                f"(peak NDVI {peak:.2f}). Treated as idle, but please check.")
        elif code in grass:
            if peak is not None and peak < BROWN:
                rec.update(crop="fallow", doubtful=True,
                           note=f"Crop map says '{r['cdl_name']}' but the field stayed brown "
                                f"(peak NDVI {peak:.2f}): treated as idle.")
            else:
                rec.update(crop="grass_hay", doubtful=True,
                           note=f"Crop map says '{r['cdl_name']}'. Grass hay and alfalfa are often "
                                "confused from space: please confirm.")
        elif crop is None:
            rec.update(crop="unknown_irrigated", doubtful=True,
                       note=f"'{r['cdl_name']}' is not in the crop table; a generic crop is used.")
        else:
            rec["crop"] = crop
            if peak is not None and peak < BROWN:
                rec.update(doubtful=True,
                           note=f"Crop map says '{r['cdl_name']}' but the field stayed brown "
                                f"(peak NDVI {peak:.2f}): possibly idle or newly sown.")
            elif r.get("share") is not None and float(r["share"]) < 0.6:
                rec.update(doubtful=True,
                           note=f"Only {float(r['share']) * 100:.0f} % of the field carried this label.")
        out.append(rec)

    # resolve green-but-mislabelled years from their neighbours
    for i, rec in enumerate(out):
        if rec["crop"] is None:
            prev = next((o["crop"] for o in reversed(out[:i]) if o["crop"] not in (None, "fallow")), None)
            nxt = next((o["crop"] for o in out[i + 1:] if o["crop"] not in (None, "fallow")), None)
            rec["crop"] = prev if (prev and prev == nxt) else (prev or nxt or "unknown_irrigated")
            rec["note"] += f" Assumed '{kb['crops'][rec['crop']]['short']}' from the neighbouring years."

    # an alfalfa year that follows a different crop is a seeding year
    for i, rec in enumerate(out):
        if rec["crop"] == "alfalfa" and i > 0 and out[i - 1]["crop"] not in ("alfalfa", "alfalfa_est"):
            rec["crop"] = "alfalfa_est"
    for rec in out:
        rec["label"] = kb["crops"][rec["crop"]]["short"]
    return out


def existing_rotation(history: list[dict], kb: dict, n_years: int = 8) -> dict:
    """The rotation the field has actually followed, as a cycle the engine can score."""
    recent = history[-n_years:]
    years = [[{"crop": r["crop"]}] for r in recent]
    assumptions: list[str] = []
    crops = [r["crop"] for r in recent]
    if all(c in ("alfalfa", "alfalfa_est") for c in crops) and "alfalfa_est" not in crops:
        years[0] = [{"crop": "alfalfa_est"}]
        assumptions.append(
            f"The crop map shows alfalfa in all {len(recent)} years. The stand is assumed to be "
            f"re-sown about every {len(recent)} years straight back into alfalfa; tell us the real "
            "stand age if you know it.")
    n_alf = sum(c in ("alfalfa", "alfalfa_est") for c in crops)
    n_idle = sum(c == "fallow" for c in crops)
    others = sorted({kb["crops"][c]["short"] for c in crops if c not in ("alfalfa", "alfalfa_est", "fallow")})
    if n_alf == len(crops):
        name = "Continuous alfalfa (as observed)"
    elif n_alf >= len(crops) / 2:
        name = "Mostly alfalfa, as observed"
    else:
        name = "Mixed use, as observed"
    parts = [f"alfalfa in {n_alf} of {len(crops)} years"]
    if others:
        parts.append("also " + ", ".join(others).lower())
    if n_idle:
        parts.append(f"idle in {n_idle}")
    return {
        "id": "existing", "name": name, "short": "Existing rotation",
        "summary": f"What the satellite record shows for {recent[0]['year']}-{recent[-1]['year']}: "
                   + "; ".join(parts) + ".",
        "years": years, "year_labels": [r["year"] for r in recent],
        "tags": ["existing"], "assumptions": assumptions,
        "n_doubtful_years": sum(bool(r["doubtful"]) for r in recent),
        "is_existing": True,
    }
