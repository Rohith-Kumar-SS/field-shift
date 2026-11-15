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
| Fields | 14 real irrigated fields (centre pivots) detected from Landsat (see §9: OpenET's boundary endpoint did not work); any polygon drawn inside the pilot box is also scored from the local rasters |
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

## 9. What changed during the build

The plan above was written before any data was fetched. These are the places where
reality differed, and what was done instead.

| Planned | What happened | What was done |
| :-- | :-- | :-- |
| Field boundaries from OpenET | `/geodatabase/metadata/ids` returned HTTP 400 "Invalid geometry" for every request, including the example in OpenET's own documentation | Boundaries are detected from Landsat: the largest circle inside each irrigated footprint on a peak-summer NDVI composite (93 pivots found, 14 chosen for variety of crop history and spread) |
| Pilot box 0.20 x 0.22 degrees | Larger than OpenET's 50,000-acre limit and wider than needed | Tightened to the irrigated core: [-116.08, 39.62, -115.95, 39.75] |
| CDL from CropScape | The CropScape service timed out | USDA CroplandCROS image service (the successor), 2008-2025; CropScape kept as a fallback |
| IMERG and SMAP by OPeNDAP subset | SMAP worked. GES DISC first refused IMERG: the token's account had not accepted the data-use agreement | SMAP loaded straight away. IMERG was recorded as failed with the exact step, and no data was invented. On 15 Nov 2026 a token from an approved account was installed and IMERG loaded through the same OPeNDAP route (9,039 days, 2001 to Sep 2025). It is scaled month by month to gridMET, and rain-based trends use the IMERG years only |
| NASA POWER moved to field elevation with a lapse rate | That gave a 134-day frost-free season, which is wrong for a valley floor where cold air pools | Added gridMET (4 km, station-informed) and a month-by-month bias correction of NASA POWER; the frost-free season becomes 81-93 days |
| Landsat via Earth Engine or Planetary Computer | Earth Engine was not authenticated | Planetary Computer; Earth Engine is not needed |
| Water score = 1 - irrigation / reference ET | Compressed the differences so much that the thirstiest rotation could still win with water weighted at 70 % | Score is now the share of full-alfalfa irrigation saved, stretched so that saving half scores 1 |
| "Long-term water trends" source not fixed | GRACE is far too coarse for one valley | USGS well records inside the valley (310 wells, back to the 1960s) |
| MODIS window around the pilot centre | Two edge fields fell outside: the sinusoidal grid is sheared at this longitude | Window widened; all 14 fields covered |

Still open: review of the rotation library by a local agronomist.

## 10. Second phase: India, a static site, and motion (November 2026)

Asked for after the Nevada build: make it work for India, make the interface attractive and
easy to use with motion that means something, and publish it on GitHub Pages.

**Regions.** Punjab (Sangrur) and Tamil Nadu (Cauvery delta) were added and Nevada kept, behind a
region switcher. `pipeline/regions.py` holds one entry per region; data lives in
`data/{raw,processed}/<region>/`. Global NASA sources are shared; the ground side differs:

| Need | USA | India |
| :-- | :-- | :-- |
| Field outlines | detected from Landsat (pivots) | 300 m sample blocks of ESA WorldCover cropland |
| Crop history | USDA Cropland Data Layer, checked against Landsat | crop seasons counted from MODIS greenness; the farmer names the rotation |
| Soil | USDA SSURGO | ISRIC SoilGrids 250 m |
| Satellite ET | OpenET | FAO WaPOR v3 |
| Ground correction of NASA POWER | gridMET | IMD rain-gauge and temperature grids |
| Long-term water | USGS wells | GRACE / GRACE-FO mascons |

**Engine changes.** One engine, three knowledge bases. New settings: `pest_model` (perennial
stand or annual crops), `existing` (read from history or chosen), `water_reference`, region
thresholds for a hot day and a heavy-rain day. The water score now uses water *delivered* to the
field (crop need plus the water paddy takes to be puddled and flooded), because scoring crop need
alone made rice-wheat look no thirstier than maize-wheat-moong, which no farmer would recognise.
Where no crop map exists, the default "what I grow now" is the common rotation whose number of
crops matches the green seasons seen from space.

**What the India data forced.** NASA POWER ran 3-4 degC too hot over irrigated Punjab in summer
(70 days above 40 degC against 31 at IMD stations), so IMD temperature was added as a second
ground correction, not just rainfall. ORNL's MODIS service was down, so MODIS comes from
Planetary Computer. GRACE has no OPeNDAP subset, so the one 44 MB file is downloaded and shared.

**Static site.** GitHub Pages cannot run Python, so the FastAPI server was retired. The pipeline
exports everything per region (`pipeline/s40_export.py`), including 30 years of corrected daily
weather per field as a 131 KB binary, and the scoring engine was ported to TypeScript
(`frontend/src/engine`). The Python engine stays as the tested reference; `tests/test_parity.py`
runs both on the same fields and compares numbers and sentences. Porting exposed three places
where the two languages differ silently (banker's rounding, Python 3.12's compensated `sum`,
numpy's pairwise sum) and one comparison at exact equality that depended on the last bit of a
float; all four are now handled explicitly. Fields drawn by the user are described in the browser
from a 140 m "atlas" grid of soil, terrain, monthly greenness and crop-map values.

**Interface.** A landing page with the two-ring comparison and one card per region, each with
its water year as a small chart. Motion is used where it carries meaning: the map descends from
orbit to the pilot box; rings draw themselves month by month; cards slide to their new rank when a
priority changes; figures glide to new values under what-if weather. All of it stands down under
`prefers-reduced-motion`. A pick-by-number row under the map serves keyboards and small screens.
