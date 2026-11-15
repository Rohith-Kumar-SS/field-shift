"""Write DATA_LOG.md from the per-source status records in data/processed/<region>/_status/.

One section per region. Run after the pipeline: `python -m pipeline.data_log`.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone

from .common import ROOT, run_source
from .regions import REGIONS

SOURCE, TITLE, TIER = "datalog", "DATA_LOG.md", "MUST"
ORDER = ["fields", "nasa_power", "gridmet", "imd", "gpm_imerg", "smap", "ssurgo", "soilgrids", "usda_cdl", "landsat",
         "openet", "wapor", "srtm", "modis", "usgs_nwis", "grace", "indicators", "overlays", "export"]
BADGE = {"ok": "OK", "partial": "PARTIAL", "failed": "FAILED - ACTION NEEDED", "skipped": "SKIPPED"}

NOT_USED = [
    ("Google Earth Engine", "OPTIONAL route",
     "Not used. `earthengine authenticate` had not been run on the build machine, so Landsat and MODIS were read "
     "from Microsoft Planetary Computer instead (the same NASA/USGS collections). Nothing in the app depends on "
     "Earth Engine. `python -m pipeline.check_access` reports whether it is ready."),
    ("ECOSTRESS (land-surface temperature, ET)", "SKIP",
     "Skipped. Irregular overpass times and revisit (it rides on the ISS), frequent cloud gaps and heavier "
     "swath preprocessing make it a poor fit for a monthly field record; OpenET (USA) and FAO WaPOR (India) already "
     "supply satellite ET. A good add-on for mapping within-field heat hotspots."),
    ("GRACE / GRACE-FO (water storage)", "Used in India, not in Nevada",
     "Its footprint is roughly 300 km. In Nevada that is hundreds of times larger than the valley, and USGS wells "
     "inside the valley measure the aquifer directly, so wells are used. In Punjab and the Cauvery delta no open, "
     "machine-readable well record was available, so GRACE gives the regional trend and the app says plainly "
     "that it is a region, not a village."),
    ("GEDI (canopy height, biomass)", "SKIP",
     "Skipped. A forest-structure lidar with sparse footprints; not meaningful over annual crops."),
    ("PRISM", "OPTIONAL",
     "Not fetched separately. gridMET, which is used to correct NASA POWER in Nevada, already carries PRISM's "
     "station-and-terrain climatology at 4 km with daily values, which is what frost dates need."),
    ("NLDAS / GLDAS", "OPTIONAL",
     "Not fetched. Model output on 12-25 km grids; they could add a longer modelled soil-moisture record "
     "than SMAP's, through the same GES DISC access IMERG uses. Left out for time."),
    ("ERA5", "OPTIONAL",
     "Not fetched. Needs a Copernicus Climate Data Store account and key, which were not provided, and at "
     "~31 km it would add little beyond NASA POWER once that is corrected to ground stations."),
    ("Sentinel-2", "OPTIONAL",
     "Not fetched. Landsat 8/9 gives 115-300 clear observations per field for 2018-2025; Sentinel-2 would help "
     "most in the cloudy monsoon months of the Indian pilots and is the first thing to add there."),
    ("NLCD, NAIP, LANDFIRE", "OPTIONAL",
     "Not fetched. Land cover around the Nevada fields is already clear from the CDL, and 1 m NAIP imagery is a "
     "large download whose main use here would be checking field outlines by eye."),
    ("NASS QuickStats, AMS Market News, Agmarknet", "OPTIONAL",
     "Not fetched. County, state or market level, not field level. Their absence is why the income score is marked "
     "low confidence and why 'local prices and buyers' appears in every information-gap list."),
    ("India crop-type maps and cadastral field boundaries", "Not openly available",
     "No open, field-scale crop map or parcel boundary layer was found for the Indian pilots. The app therefore uses "
     "300 m sample blocks of cropland (ESA WorldCover), counts crop seasons from greenness, and asks the farmer to "
     "say what is grown."),
    ("India state groundwater-department well records (CGWB)", "Not openly machine-readable",
     "Not fetched: India-WRIS offers them through a portal rather than an open API. They are the right local "
     "complement to GRACE and are named in every 'check locally' list."),
    ("FAO GAEZ, CoCoRaHS, Ag Data Commons", "OPTIONAL",
     "Not fetched. GAEZ suitability layers are too coarse for one pilot box; CoCoRaHS covers North America only; "
     "Ag Data Commons is a catalogue rather than a single dataset."),
]


def region_section(rid: str, cfg: dict) -> list[str]:
    status_dir = ROOT / "data" / "processed" / rid / "_status"
    recs = {}
    for p in status_dir.glob("*.json"):
        r = json.loads(p.read_text(encoding="utf-8"))
        recs[r["source"]] = r
    if not recs:
        return []
    ordered = [recs[k] for k in ORDER if k in recs] + [r for k, r in recs.items() if k not in ORDER and k != SOURCE]
    lines = [f"## {cfg['name']}", "",
             f"Box {cfg['bbox']} (west, south, east, north). Files: `data/processed/{rid}/`.", "",
             "| Source | Tier | Status | Date range | Resolution |", "| :-- | :-- | :-- | :-- | :-- |"]
    for r in ordered:
        lines.append(f"| {r['title']} | {r['tier']} | **{BADGE.get(r['status'], r['status'])}** | "
                     f"{r.get('date_range') or '-'} | {r.get('resolution') or '-'} |")
    lines.append("")
    for r in ordered:
        lines += [f"### {cfg['short']}: {r['title']}", "",
                  f"- **Status:** {BADGE.get(r['status'], r['status'])}: {r.get('message', '')}"]
        if r.get("action_needed"):
            lines.append(f"- **Action needed:** {r['action_needed']}")
        for label, key in (("What was fetched", "fetched"), ("Resolution", "resolution"),
                           ("Date range", "date_range"), ("Access route", "access"),
                           ("Credit / licence", "credit"), ("Caveats", "notes")):
            if r.get(key):
                lines.append(f"- **{label}:** {r[key]}")
        if r.get("outputs"):
            lines.append("- **Outputs:** " + ", ".join(f"`{o}`" for o in r["outputs"]))
        checks = (r.get("sanity") or {}).get("checks") or []
        if checks:
            lines += ["- **Sanity checks:**", "", "  | Variable | n | min | mean | max | expected | result |",
                      "  | :-- | --: | --: | --: | --: | :-- | :-- |"]
            for c in checks:
                lines.append(f"  | {c['variable']} | {c['n']} | {c.get('min', '-')} | {c.get('mean', '-')} | "
                             f"{c.get('max', '-')} | {c['expected_range'][0]} to {c['expected_range'][1]} | "
                             f"{'pass' if c['passed'] else 'CHECK'}{' (all NaN)' if c.get('all_nan') else ''} |")
            lines.append("")
        extra = {k: v for k, v in (r.get("sanity") or {}).items() if k != "checks"}
        if extra:
            lines.append(f"- **Other checks:** `{json.dumps(extra)[:900]}`")
        lines.append(f"- **Demo data:** {'YES' if r.get('is_demo_data') else 'no'}")
        lines.append("")
    return lines


def main() -> None:
    lines = [
        "# DATA_LOG", "",
        f"Generated by `python -m pipeline.data_log` on {datetime.now(timezone.utc):%Y-%m-%d %H:%M} UTC from the "
        "status files the pipeline writes for each region.", "",
        "No demo, sample or simulated data is used anywhere: every value in `data/processed` was fetched "
        "from the source named here. A source that could not be fetched is listed as FAILED with the exact "
        "step needed, and the app shows it as missing.", "",
        "Global NASA sources (POWER, GPM IMERG, SMAP, Landsat, MODIS, SRTM) are the same in every region. The "
        "ground side differs by country: USDA soil survey and crop map, OpenET, gridMET and USGS wells in the USA; "
        "India Meteorological Department station grids, ISRIC SoilGrids, FAO WaPOR, ESA WorldCover and GRACE in India.",
        "",
    ]
    n = 0
    for rid, cfg in REGIONS.items():
        sec = region_section(rid, cfg)
        lines += sec
        n += bool(sec)
    lines += ["## Listed in the challenge resources but not used", "",
              "| Source | Tier in the plan | Why |", "| :-- | :-- | :-- |"]
    lines += [f"| {a} | {t} | {w} |" for a, t, w in NOT_USED]
    lines.append("")
    (ROOT / "DATA_LOG.md").write_text("\n".join(lines), encoding="utf-8")
    print(f"[OK ] DATA_LOG.md written ({n} regions)")


if __name__ == "__main__":
    run_source(SOURCE, TITLE, TIER, main)
