# Field Shift: Rotation Scenario Explorer

**Live:** https://rohith-kumar-ss.github.io/field-shift/

A decision-support tool for the 2026 NASA Space Apps challenge *Field Shift: Adapting
Farms with NASA Data*. A farmer picks a field (or draws one), sees what thirty years of
NASA weather, satellite greenness, soil and water records say about it, sets their own
priorities, and compares their current crop rotation with four alternatives.

> **It compares options. It never tells anyone what to plant.** Every score opens to the
> formula, the numbers and the sources behind it, and every rotation lists its risks,
> what the tool cannot see, and what to check with a local expert.

Three pilot areas, each a box about 13 km across with every source downloaded and checked:

| Region | Farming system | Fields | What makes it different |
| :-- | :-- | :-- | :-- |
| **Diamond Valley, Nevada, USA** | Irrigated alfalfa under centre pivots, on falling groundwater | 14 pivots detected from Landsat | A crop map exists, so the existing rotation is read from the satellite record |
| **Sangrur, Punjab, India** | Rice-wheat on tubewells | 12 sample plots (300 m blocks of cropland) | No crop map: the farmer says what is grown, and the satellite count of crop seasons checks it |
| **Cauvery delta, Tamil Nadu, India** | Canal-fed paddy (kuruvai, thaladi, samba) | 12 sample plots | Rain arrives October-December; one or two rice crops depending on canal water |

## Status at a glance

- All sources load for all three regions. **No demo, sample or simulated data anywhere.**
- 49 automated tests pass, including one that runs the browser's scoring engine and the
  Python reference on the same fields and compares every number and every sentence.
- The site is static (GitHub Pages): no server, no login, no keys in the browser. Moving a
  slider re-scores instantly on the device.
- **Not done:** no farmer or agronomist has reviewed the rotation libraries. That is the
  next step before anyone acts on them.

## What the tool does

1. **Pick a region, then a field.** The map comes down from orbit to the pilot box.
   Tap a numbered field, pick one from the list under the map, or draw your own.
2. **See the field.** What grew there (crop map in the USA; crop seasons counted from
   greenness in India), water used according to satellites, rain against the weather's
   demand, hot days, soil, long-term water (USGS wells in Nevada, GRACE in India), and a
   month-by-month calendar of bare soil, erosion risk and crop stress.
3. **Say what matters.** Eight sliders: save water, keep soil covered, nitrogen from
   legumes, build organic matter, break pest cycles, income, heat and dry-spell
   resilience, ease. Three limits: water you can count on, equipment, buyers.
   Two what-if sliders shift the whole weather record (warmer, wetter or drier).
4. **Compare rotations.** The current rotation plus four alternatives, each drawn as a
   *rotation ring*: one lap is the whole rotation, coloured arcs are crops holding the
   ground, pale gaps are bare soil. Cards slide into their new order as priorities change.
5. **Open any card** for why it was suggested for *this* field (tied to numbers and to an
   evidence panel), benefits, risks, what the tool does not know, a checklist for a local
   expert, and the formula and inputs behind each of the eight scores.
6. **Evidence panels** with charts and tables for water, weather, greenness and cover,
   soil, crop history and long-term water, each with its source and its limits.

## Run it

```bash
python tasks.py setup            # Python venv + npm packages
python tasks.py dev              # http://localhost:5180
python tasks.py test             # 49 tests
python tasks.py build            # static site in frontend/dist
```

The exported data ships with the repository (`frontend/public/data`), so the app runs
without any credentials. To rebuild the data from the sources:

```bash
cp .env.example .env             # add your own Earthdata token and OpenET key
python tasks.py check            # which services answer (prints no secrets)
python tasks.py data --region all            # everything, cached in data/raw (hours the first time)
python tasks.py data --region punjab_sangrur indicators overlays export   # or single steps
python tasks.py docs             # DATA_LOG.md and ROTATION_KNOWLEDGE.md
```

`python tasks.py deploy` builds the site and publishes it (see `deploy/deploy.py`).

### Credentials

Only the pipeline needs them, and only for two services: a NASA Earthdata bearer token
(GPM IMERG, SMAP, SRTM, GRACE; the account must have accepted the GES DISC data-use
agreement) and an OpenET API key (Nevada only). They live in `.env`, which is git-ignored;
nothing is printed, logged or written into code. Everything else is open without a key.

## Architecture

```
pipeline/            one script per source, cached and resumable; regions.py lists the pilots
  s00..s11           fetch and reduce each source to field x month
  s20_indicators     fuse everything into context (for scoring) + evidence (for charts)
  s30_overlays       map layers
  s40_export         static files for the browser, incl. a 140 m "atlas" for drawn fields
knowledge/<region>.yaml   crops, calendars, class scores, rotations, references (data, not code)
engine/              Python reference: FAO-56 ET, climate summary, scoring, explanations
frontend/src/engine  the same engine in TypeScript: this is what runs in the browser
frontend/src         React + MapLibre + Recharts
tests/               pytest: maths, scoring, wording rule, and Python-vs-browser parity
deploy/deploy.py     GitHub repository + GitHub Pages
```

Why a static site: the scoring is arithmetic on a field's own data, so it can run on the
farmer's device. That removes hosting, cold starts and any need for a connection after
the page has loaded (apart from the satellite basemap), and sliders respond at once.
Each field ships 30 years of locally corrected daily weather as a 131 KB binary file;
the browser recomputes reference ET, frost dates and hot days when a what-if slider moves.

### Harmonisation

Every source is reduced to **field polygon x month** (plus yearly and seasonal
summaries) with area-weighted zonal statistics. Coarse grids (weather 50 km, IMERG 10 km,
SMAP 9 km, GRACE ~300 km) are never presented as field measurements: each panel says
what the pixel covers. NASA POWER is corrected month by month to a ground-station grid
(gridMET in Nevada, India Meteorological Department grids in India) by the delta method.

### Scoring

Transparent weighted multi-criteria analysis: `overall = sum(weight x score)`, eight
criteria scored 0-1 from rules documented in [ROTATION_KNOWLEDGE.md](ROTATION_KNOWLEDGE.md).
No machine-learning model, no yield prediction. The same code serves every region; what
differs is the knowledge base and a few settings (how pest pressure is judged for
perennial stands against annual crops, which rotation is the water yardstick, and
whether the existing rotation is read from a crop map or chosen by the farmer).

## Datasets

Details, date ranges, sanity checks and credits for each, per region: [DATA_LOG.md](DATA_LOG.md).

| Dataset | Regions | Used for |
| :-- | :-- | :-- |
| NASA POWER (daily, 1991-2025) | all | Reference ET, heat, frost, wind, trends, what-if scenarios |
| GPM IMERG (daily, 2001-2025) | all | Rainfall, heavy-rain days |
| SMAP SPL3SMP_E (2015-2025) | all | Soil-moisture anomaly |
| Landsat 8/9 (2018-2025) | all | Field outlines (USA), NDVI, low-cover months, flooded-field signal |
| MODIS MOD13Q1 (2001-2025) | all | 25-year greenness; crop seasons per year (India) |
| SRTM | all | Field tilt and elevation |
| GRACE / GRACE-FO JPL mascons | India | Regional water-storage trend |
| USDA SSURGO, USDA Cropland Data Layer | USA | Soil; crop history |
| OpenET | USA | Satellite ET and model spread; anchors the water estimate |
| gridMET | USA | Ground-informed correction of NASA POWER |
| USGS NWIS wells | USA | Depth to groundwater |
| IMD gridded rainfall (0.25 degree) and temperature (1 degree) | India | Ground-station correction of NASA POWER and IMERG |
| ISRIC SoilGrids 2.0 (250 m) | India | Soil texture, organic carbon, pH |
| FAO WaPOR v3 (300 m) | India | Satellite ET |
| ESA WorldCover (10 m) | India | Finding cropland for the sample plots; land-cover layer |

Not used, with the reason for each (ECOSTRESS, GEDI, PRISM, NLDAS/GLDAS, ERA5,
Sentinel-2 and others): see the last section of DATA_LOG.md.

## What the data showed

These came out of the pipeline, not out of assumptions.

**Weather grids need ground truth, and the error differs by place.**

- *Nevada:* NASA POWER's ~50 km cell puts the frost-free season at about 134 days.
  Corrected with station-informed gridMET it is 81-93 days: valley-floor nights run
  4-5 °C colder because cold air pools there. That decides whether teff is safe.
- *Punjab:* the same product counts about 70 days a year above 40 °C; India
  Meteorological Department stations measured about 31. The global weather model does
  not know the plain is irrigated, and its summer afternoons run up to 3.2 °C too hot.
  Uncorrected, both heat stress and crop water demand would be overstated.
- *Cauvery delta:* days above 38 °C drop from 34 to 10 a year in the station grid, and
  NASA POWER's rainfall (1,060 mm) is below the rain-gauge grid (1,221 mm).

**Water**

- *Nevada:* in their own alfalfa years, 13 of 14 fields used 68-86 % of the textbook
  full-irrigation figure according to OpenET; each field's estimate is scaled by its own
  ratio. Rotation alone saves a modest amount: the thriftiest option needs about 17 %
  less than continuous alfalfa, and the tool says so instead of promising more.
- *Punjab:* rice-wheat needs about 1,650 mm of irrigation delivered a year on a sample
  plot, of which roughly 800 mm is water paddy takes only to be puddled and kept flooded.
  Maize-wheat-moong needs about 1,000 mm. Adding summer moong to rice-wheat *raises* the
  need, because it grows in the hottest, driest months.
- *Cauvery delta:* two rice crops (kuruvai + thaladi) need about 1,560 mm delivered; a
  single samba crop with a pulse on leftover moisture about 720 mm.
- *Long-term water:* most long-record USGS wells near the Nevada pivots have been
  deepening since 1990 (median 0.6-5.0 m per decade). GRACE shows stored water over the
  Punjab region falling by about 3.8 cm a year since 2002, and no fall over the Cauvery
  delta region (+0.7 cm a year).

**Reading the record honestly**

- The USDA crop map sometimes labels green, irrigated pivots "shrubland" or "forest".
  Landsat greenness is the second opinion and doubtful years are flagged.
- Where no crop map exists, greenness peaks give the number of crops a year (two around
  Sangrur, greenest in February and August), which is enough to check the rotation the
  farmer selects and to choose a sensible starting point when they have not said.
- A trend must not straddle a change of data source: rain before 2001 comes from NASA
  POWER and from 2001 from IMERG, so rain-based trends are reported from 2001 only.
- Satellite rainfall is scaled month by month to the ground grid, and the app shows both
  the downloaded and the used values.

## Limitations

- Three pilot boxes. Crop calendars and class scores are written from published
  references and **have not been reviewed by a local agronomist**.
- Nevada field outlines are detected from Landsat; Indian "plots" are 300 m blocks of
  cropland, a neighbourhood of small fields rather than one owner's parcel.
- In India the tool cannot see which crop was grown, only how many seasons. Cloud in the
  monsoon hides crops, and a short pulse on leftover moisture may not register.
- Soil in India comes from a 250 m global model with no salinity layer.
- GRACE describes a region about 300 km across, not a village or a tubewell.
- No prices, yields, costs, pests, diseases, herbicide history, irrigation system, canal
  schedule or water rights are known to the tool. The income score is a rough ordering
  from class scores and is always marked low confidence.
- The flooding-water figure for paddy is a typical value, not a measurement; sandy soils
  take more and part of it seeps back to groundwater.
- The what-if sliders shift the historical weather record uniformly. They are a
  sensitivity test, not a climate projection.
- A drawn field takes weather, soil moisture and long-term water from the nearest pilot
  field, has no satellite water-use record, and is scored with lower confidence.
- The basemap needs an internet connection.

## Tests

`python tasks.py test` runs 49 tests: FAO-56 reference ET against the worked examples in
the FAO paper, effective rain, frost and trend functions, area-weighted zonal
statistics, crop-history interpretation, knowledge-base validation for every region,
each scoring criterion, constraints, scenarios, the annual-cropping rules, the wording
rule (the output never tells the farmer what to plant), and
`tests/test_parity.py`, which bundles the browser engine with esbuild, runs it in Node on
the exported data and compares it with the Python reference: scores to three decimals,
millimetres to within one, every sentence word for word.

## Credits

Data: NASA POWER (NASA LaRC); GPM IMERG (NASA GES DISC); SMAP (NASA NSIDC DAAC); Landsat
8/9 (USGS and NASA, via Microsoft Planetary Computer); MODIS MOD13Q1 (NASA LP DAAC);
SRTM (NASA JPL, LP DAAC); GRACE and GRACE-FO mascons (NASA JPL, PO.DAAC); USDA NRCS
SSURGO; USDA NASS Cropland Data Layer; OpenET; USGS National Water Information System;
gridMET (Abatzoglou 2013); India Meteorological Department gridded rainfall and
temperature (Pai et al. 2014; Srivastava et al. 2009; read with imdlib); ISRIC SoilGrids
2.0; FAO WaPOR v3; ESA WorldCover 2021. Basemap: Sentinel-2 cloudless by EOX (contains
modified Copernicus Sentinel data 2016) and OpenStreetMap contributors. Methods: FAO
Irrigation and Drainage Papers 56 and 33; USDA NRCS National Engineering Handbook Part
623. Full citations in DATA_LOG.md and ROTATION_KNOWLEDGE.md.

NASA does not endorse this tool or any non-U.S. Government entity.

See also: [PLAN.md](PLAN.md) · [DATA_LOG.md](DATA_LOG.md) ·
[ROTATION_KNOWLEDGE.md](ROTATION_KNOWLEDGE.md) · [DEMO_SCRIPT.md](DEMO_SCRIPT.md)
