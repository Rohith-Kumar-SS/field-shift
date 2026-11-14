# PLAN — Field Shift: Rotation Scenario Explorer

2026 NASA Space Apps Challenge · "Field Shift: Adapting Farms with NASA Data"

## 1. What I understood

**The requirement (problem statement — this wins any conflict).**
Build a decision-support tool that combines NASA Earth observations with local soil
information, crop characteristics and farmer priorities, so a farmer can *explore* crop
rotation strategies that may strengthen soil health and resilience to changing weather
and water. The tool should:

- analyse temperature, heat stress, rainfall, soil moisture, evaporation, frost risk,
  extreme precipitation, vegetation stress and long-term water trends;
- highlight when fields are typically bare and when the current crop looks vulnerable;
- compare **at least three rotation strategies, including the existing one**, and for
  each explain *why it was suggested, what evidence supports it, what benefits it may
  offer, where information gaps exist, and what risks need local review*;
- explain the science in plain language (ET, soil-moisture anomaly, NDVI, frost risk,
  water balance; satellite vs ground measurements);
- let farmers enter priorities and constraints;
- **support, not replace, farmer judgment and local expertise.**

**The strategy (research report).** Narrow scope + real NASA data + credible agronomic
rules + excellent explanation. A field-level "Rotation Scenario Explorer" driven by
transparent weighted multi-criteria scoring (MCDA) — no black-box yield model — with all
heavy geospatial work precomputed so the demo reads local files only.

## 2. Final scope

| Item | Decision |
| :-- | :-- |
| Product | Map-first web app: pick or draw a field → field snapshot → set priorities → compare strategies with evidence, gaps, risks, confidence |
| Pilot region | **Diamond Valley, Eureka County, Nevada** (see §3) |
| Fields | ~12 real irrigated fields (centre pivots) taken from the OpenET field-boundary database; any polygon drawn inside the pilot box is also scored from the local rasters |
| History | Field-scale satellite record 2018–2025; crop history (CDL) 2008–2025; climate record 1991–2025 for trends |
| Strategies | Existing rotation (read from the USDA Cropland Data Layer) + 4 alternatives from a documented rotation library |
| Scoring | Weighted MCDA over 8 farmer priorities; rule-based agronomy + statistical climatology; every number traceable to an evidence panel |
| Scenarios | Rainfall-change and temperature-change sliders that recompute water demand, heat and frost indicators, then re-score |
| Out of scope | Yield prediction, irrigation scheduling, prices, pest forecasts, multi-region coverage, user accounts |

## 3. Pilot region — why Diamond Valley

- It is Nevada irrigated alfalfa country, as the report recommends and as the challenge
  imagery shows.
- Groundwater there is over-appropriated and declining; Nevada's State Engineer made it
  the state's first Critical Management Area. "Can I keep forage income while using less
  water?" is the real question growers face, so the tool's central trade-off is not
  hypothetical.
- Fields are large centre pivots (~50 ha), which suits 30 m Landsat and makes even 250 m
  MODIS usable at pivot centres.
- It is inside OpenET's coverage, so there is field-scale evapotranspiration evidence.
- At ~1,800 m elevation the frost-free season is short — a real, data-visible constraint
  on which rotation crops are feasible.

If a data source turns out not to cover the valley, the fallback is Mason/Smith Valley
(Lyon County, NV). This file will be updated if that happens.

## 4. Data plan (follows the report's triage)

| Tier | Source | What I take from it | Access |
| :-- | :-- | :-- | :-- |
| MUST | NASA POWER | Daily Tmax/Tmin/dewpoint/wind/solar/precip 1991–2025 → reference ET (FAO-56), heat days, frost dates, water balance, trends | REST API, no key |
| MUST | GPM IMERG | Daily + monthly precipitation → totals, variability, extreme-rain days | GES DISC OPeNDAP, Earthdata token |
| MUST | SMAP | Surface/root-zone soil moisture → monthly anomaly (z-score) | NSIDC cloud OPeNDAP, Earthdata token |
| MUST | SSURGO | Texture, organic matter, available water, drainage, hydrologic group, erodibility, wind-erodibility, salinity | USDA Soil Data Access |
| MUST | USDA CDL | Crop each year 2008–2025 → existing rotation, diversity | CropScape web service |
| STRONG | Landsat 8/9 | 30 m NDVI and bare-soil index → greenness, low-cover windows, stress dips | Earth Engine if authenticated, else Planetary Computer STAC |
| STRONG | OpenET | Field boundaries + monthly actual ET, reference ET, precipitation | OpenET API key |
| OPTIONAL | SRTM | Slope → erosion/runoff context | LP DAAC (Earthdata token) or NASADEM |
| OPTIONAL | MODIS | 250 m NDVI 2001–2025 → long-term greenness trend | ORNL DAAC subset API |
| OPTIONAL | USGS NWIS | Groundwater levels → long-term water trend (ground truth) | USGS water services |
| OPTIONAL | PRISM, NLDAS/GLDAS, Sentinel-2, NLCD, NAIP, ERA5, NASS QuickStats | Only if time permits; each is logged as used or skipped with the reason | — |
| SKIP | ECOSTRESS, GRACE/GRACE-FO, GEDI | Reasons recorded in README (irregular revisit / ~300 km footprint / forest-structure product) | — |

Rules I will hold to: reproducible scripts in `/pipeline` (one per source + `run_all.py`);
raw cache in `/data/raw` (git-ignored); processed Parquet/GeoJSON in `/data/processed`;
every source logged in `DATA_LOG.md` with a sanity check; **no fabricated or silently
simulated data** — anything not real is tagged `is_demo_data: true` and badged in the UI.

Harmonisation: everything is reduced to **field polygons × month** (area-weighted zonal
statistics for rasters, cell value for coarse grids, dominant + area-weighted values for
soil map units), plus annual and growing-season summaries.

## 5. Scoring design

Score(strategy) = Σ wᵢ · sᵢ(strategy), weights from the farmer's sliders, normalised to 1.

| Priority | How sᵢ is built (0–1) | Main evidence |
| :-- | :-- | :-- |
| Water conservation | Crop water demand (FAO-56 crop coefficients × reference ET) minus effective rain, averaged over the rotation | POWER, IMERG, OpenET |
| Soil cover / erosion | Share of the year the rotation keeps soil covered, weighted by the months when wind and rain hazards are highest for this field | Landsat, IMERG, POWER wind, SRTM, SSURGO |
| Nitrogen | Time-weighted legume / N-credit class | Knowledge base |
| Organic matter | Residue and root inputs, perennial years, tillage events | Knowledge base, SSURGO baseline |
| Pest-cycle disruption | Crop-family diversity and length of break between alfalfa stands | CDL history, knowledge base |
| Forage / income | Forage yield class × market strength, adjusted by market constraint | Knowledge base (explicit info gap: no local prices) |
| Drought / heat resilience | Crop tolerance vs this field's heat-day and frost exposure in that crop's season | POWER, knowledge base |
| Feasibility | Season fit (frost-free days), equipment the farmer has, establishment difficulty | POWER, farmer input |

Constraints (water available, equipment, market openness) apply visible penalties and
flags; they never silently remove a strategy. Wording rule: the tool never says "plant
crop X" — only "under your priorities, strategy B scores highest for …".

## 6. Architecture

```
/pipeline   one script per source  ->  /data/raw (cache)  ->  /data/processed (Parquet, GeoJSON, PNG overlays)
/knowledge  rotation_knowledge.yaml (crop traits, rotations, each value with a source or rationale)
/engine     indicators.py + scoring.py (pure Python, unit-tested)
/backend    FastAPI: fields, indicators, evidence, POST /api/score (weights, constraints, scenario)
/frontend   React + Vite + TypeScript, MapLibre GL JS, Recharts
```

## 7. Adjustments to the suggested stack

- **`make` is not installed on this Windows machine.** A cross-platform `tasks.py`
  provides `setup`, `data`, `dev`, `test`; the `Makefile` simply forwards to it, so
  `make setup / make data / make dev` work wherever `make` exists.
- **Python 3.12** virtual environment (widest geospatial wheel support).
- **Earth Engine is not authenticated on this machine yet**, so Landsat comes from
  Microsoft Planetary Computer (same Landsat Collection 2 Level-2 data). The Earth
  Engine path activates once `earthengine authenticate` has been run.

## 8. Order of work

read inputs → PLAN.md → .gitignore / .env.example → data pipeline → knowledge base →
scoring engine + tests → backend → frontend → integrate and test → docs. Commit after
each stage.
