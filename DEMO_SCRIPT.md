# DEMO_SCRIPT

Two parts: a 3-minute walkthrough to record or present, and a one-page summary for the
NASA Space Apps judges.

## Before you start

```bash
python tasks.py dev      # API on :8360, app on :5180
```

Open http://localhost:5180 in a desktop browser at full width. Have the page loaded and
the map tiles drawn before you start talking. Numbers quoted below are what the app
shows today for Field 5 and Field 2 with the default sliders; read them off the screen
rather than from this page, in case the data has been rebuilt.

## The 3-minute walkthrough

Persona: an alfalfa grower in Diamond Valley, Nevada, whose groundwater allocation is
being cut year by year. The question: *"What could I rotate into that eases the water
pressure without wrecking my hay income, and what would I need to check first?"*

| Time | Do | Say |
| :-- | :-- | :-- |
| 0:00 | Show the map. Point at the yellow sentence in the dark strip. | "This is Diamond Valley, Nevada. Every circle is a centre pivot, mostly alfalfa. Pumping here has outrun recharge for decades. Our tool helps a grower compare rotations. It never tells them what to plant." |
| 0:15 | Click pivot **5**. | "Pick a field. Everything you now see is real data: NASA POWER weather, GPM IMERG rainfall, SMAP soil moisture, Landsat and MODIS greenness, SRTM terrain, plus USDA soils and crop maps, OpenET water use and USGS wells." |
| 0:30 | Point at the crop strip, then the stat tiles. | "Alfalfa in every year on this strip, thirteen years running in the full record. It used about 810 mm of water each growing season, on a loamy fine sand with half a percent organic matter. Rain supplies about 205 mm a year; the weather asks for 1,340." |
| 0:45 | Point at the "Through the year" calendar. | "This calendar answers two of the challenge's questions. Brown dots: months with little green cover. Triangles: when wind and rain are hardest on this soil. Diamonds: when heat and water demand stack up on the crop, here June and July." |
| 1:00 | Scroll to **Compare rotations**. Point at the rings. | "Five rotations, the existing one included. Each ring is a pivot seen from above: one lap is the whole rotation, colours are crops, pale gaps are bare soil. Under the default priorities the low-water sequence scores highest, mainly on saving water and breaking pest cycles, and it scores lowest on income. The tool says both." |
| 1:20 | Drag **Forage and income** to the top, **Save water** to zero. | "Now I am a grower who cannot give up hay income. Continuous alfalfa moves to the top. There is no single best rotation, only the best fit for your priorities." Then press **Reset**. |
| 1:35 | Drag **Water I can count on** down to 60 %. | "Now cut my water to 60 %. Alfalfa's income score drops hardest, because its yield falls in step with water. That is the real trade-off in this valley." Put it back to 100 %. |
| 1:50 | Open **Why, benefits, risks and what to check** on the top card. | "Every suggestion explains itself with numbers from this field: 118 mm a year less irrigation, thirteen years of alfalfa without a break, sandy soil that blows in spring. Then benefits, risks, and what the tool does not know." |
| 2:05 | Point at the frost risk line, then click **See evidence: Weather**. | "Here is why ground data matters. NASA's weather grid alone gives this valley 134 frost-free days. Corrected with station data it is 81. Teff needs 75, so it only fits in about 70 % of years. Satellites and ground measurements are stronger together." |
| 2:25 | Open **Where each score comes from** > **Save water**. | "Nothing is a black box. Each score opens to its formula, its inputs and their sources, with a confidence level. This one is anchored to OpenET: the field used 82 % of the textbook figure." |
| 2:40 | Set **Warmer by** to +3 °C. | "What if it warms by three degrees? Irrigation need rises by about 60 to 70 mm for every rotation and the frost-free season lengthens. It is a sensitivity test, and it is labelled as one." Reset. |
| 2:50 | Click **Groundwater** in the evidence tabs. | "And the long view: USGS wells near this field. The water table has been falling for decades. That is what a satellite cannot show at this scale and a well can." |
| 3:00 | Point at the checklist on the card. | "It ends with a checklist to take to a local agronomist. The tool supports the farmer's judgment. It does not replace it." |

### If you have 30 more seconds

- Click pivot **2**: the soil survey shows pH 9.3 and salinity 3.0 dS/m. The app flags
  that alfalfa loses yield above 2.0 while barley and triticale tolerate far more.
- **Map layers** > *Summer greenness*, and drag the year slider back to 2018 to watch
  pivots appear and go idle.
- **Draw my own field**, tap four corners inside the dashed box, **Finish field**: it is
  scored from the local rasters, with OpenET and MODIS marked "not loaded" and
  confidence lowered.
- **About the data**: every source with its status, resolution, caveats and credit. A
  source that fails to load is shown as missing with the step needed, never faked.

### Honest answers to likely questions

- *Is any of this simulated?* No. Every value was downloaded from the named source.
- *Did you train a model?* No. Transparent rules and a weighted sum. With no paired
  yield data, a yield model could not have been validated.
- *Has a farmer or agronomist reviewed it?* Not yet. The crop table is from published
  references (FAO-56, FAO-33, SARE, Extension publications) and each value shows its
  source, but it is not locally calibrated. That review is the next step.
- *How much water does rotation really save?* About 17 % in the best case here. Double
  cropping saves almost nothing. The tool reports that plainly.

---

## One-page summary for judges

**Field Shift: Rotation Scenario Explorer.** A map-based tool that lets a farmer pick
or draw a field, see what NASA Earth observations and local soil data say about it, set
their own priorities and limits, and compare five crop rotations, the existing one
included, each with reasons, evidence, benefits, information gaps, risks, a confidence
level and a checklist for a local expert.

**Pilot.** Diamond Valley, Nevada: irrigated alfalfa under centre pivots in Nevada's
first Critical Management Area for groundwater. 14 real fields detected from Landsat.

### Impact

- Addresses a decision growers there face now: shrinking water allocations against the
  need to keep forage income.
- Puts 35 years of weather, 10 years of field water use, 8 years of field greenness, 18
  years of crop history and 60 years of well records behind one field in a few taps.
- Honest about scale: the best rotation here saves about 17 % of irrigation, and the
  tool says so.

### Creativity

- **The rotation ring**: each strategy is drawn as a pivot seen from above, one lap for
  the whole rotation, with bare-soil months showing as gaps.
- **A calendar** that lines up low-cover months, erosion-risk months and crop-stress
  months for the field.
- **Sliders that argue back**: priorities, a water-supply limit, equipment, markets and
  what-if weather all re-rank the options live.
- Field outlines are found by fitting circles to Landsat summer greenness, which
  separates pivots that touch.

### Validity

- NASA data used meaningfully: POWER (weather, reference ET), GPM IMERG (rainfall, heavy-rain
  days), SMAP (soil-moisture anomaly), Landsat (field outlines, greenness, cover), MODIS (25-year greenness), SRTM
  (terrain), with USDA SSURGO and CDL, OpenET, USGS wells and gridMET.
- Published, transparent methods: FAO-56 Penman-Monteith, FAO-56 crop coefficients,
  USDA-SCS effective rain, FAO-33 yield response, Theil-Sen trends with a significance
  test. No black-box model.
- Sources are cross-checked rather than trusted: the crop map against Landsat greenness;
  NASA POWER against gridMET (frost-free season 134 days raw, 81-93 corrected); IMERG
  rainfall against gridMET (4-18 % higher over a year);
  textbook water demand against OpenET (fields use 68-86 % of it).
- Uncertainty is shown, not hidden: a confidence level on every score, OpenET model
  spread, doubtful years flagged, missing sources named on every field.
- Reproducible: one script per source, cached downloads, sanity checks logged in
  DATA_LOG.md, 48 automated tests, no demo data.

### Relevance

- Covers every analysis the challenge lists: temperature, heat stress, rainfall, extreme
  precipitation, soil moisture, evaporation, frost risk, vegetation stress, long-term
  water trends, bare-field periods and vulnerable seasons.
- Compares five rotations including the existing one, each with why, evidence,
  benefits, gaps and risks, exactly as the challenge describes.
- Explains ET, NDVI, soil-moisture anomaly, frost risk and water balance in plain
  language, and shows with a worked local example how satellite and ground data differ.
- Built to support, not replace, the farmer: it never says "plant X".

### Presentation

- Map first, large type (Atkinson Hyperlegible, designed for legibility), few clicks,
  works on a phone.
- Colour-blind-safe palette, checked with a validator; nothing is conveyed by colour
  alone; every chart has a table view.
- Metric with imperial alongside (mm and inches, hectares and acres, °C and °F).

### What is not done

- One valley, 14 fields, no local expert review yet, no prices or yields.
