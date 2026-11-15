# DEMO_SCRIPT

Three parts: a 3-minute India walkthrough, a 3-minute Nevada walkthrough, and a one-page
summary for the NASA Space Apps judges.

## Before you start

Open the live site, https://rohith-kumar-ss.github.io/field-shift/, or run it locally:

```bash
python tasks.py dev      # http://localhost:5180 (a static site: there is no API to start)
```

Use a desktop browser at full width, with the page loaded and the map tiles drawn before
you start talking. Numbers quoted below are what the app shows today with the default
sliders; read them off the screen rather than from this page, in case the data has been
rebuilt.

## India walkthrough (3 minutes)

Persona: a rice-wheat farmer near Sangrur, Punjab, whose tubewell has to reach deeper
every few years. The question: *"What could I grow instead of paddy that eases the water
pressure without giving up assured income, and what would I need to check first?"*

| Time | Do | Say |
| :-- | :-- | :-- |
| 0:00 | Landing page. Point at the two rings. | "Same field, a different rotation. Each ring is one year seen from above: colour is a crop holding the ground, the pale gap is bare soil. Rice then wheat leaves May bare and needs about 1,650 mm of irrigation. Maize, wheat and summer moong keeps it covered on about 1,000." |
| 0:15 | Scroll to the three region cards. Point at the bar charts. | "Three pilot areas. The bars are rain by month, the line is what the weather asks for. Nevada: almost no rain. Punjab: a July-August monsoon. The Cauvery delta: rain in October to December. Same tool, same NASA sources, different ground data." |
| 0:30 | **Open Sangrur.** Let the map descend. Click plot **3**. | "From orbit down to the fields. There is no crop map or field-boundary layer here, so these are 300-metre sample blocks of farmland, and the tool is honest about that." |
| 0:45 | Point at the crop-season strip and the tiles. | "It cannot see which crop, but it can count: two green seasons a year, peaking in February and August. Rain 510 mm, the weather asks for 1,740. And NASA's GRACE satellites show stored water across this region falling 3.8 cm every year since 2002." |
| 1:05 | Point at **What I grow now**. | "Because no map says what is grown, the farmer does. Two seasons a year matches rice-wheat, so that is the starting point." |
| 1:15 | Point at the cards. | "Five rotations, the current one included. Under the default priorities maize-wheat-moong scores highest, mainly on water: about 650 mm a year less. Rice-wheat is last on water but first on assured income. The tool says both." |
| 1:35 | Drag **Income and assured sale** to the top, **Save water** to zero. | "Now I am a farmer who cannot risk the mandi price. Watch the cards move. There is no single best rotation, only the best fit for your priorities." Press **Reset**. |
| 1:50 | Under Markets choose **Only crops with assured buying**. | "Tell it I only sell at the support price, and maize and cotton lose income score, with the reason written on the card." Put it back. |
| 2:05 | Open **Why, benefits, risks and what to check** on the top card. | "Every suggestion explains itself with this field's numbers, then lists risks, what the tool does not know, and a checklist for the local agriculture officer or KVK." |
| 2:20 | Click **See evidence: Weather**. | "Here is why ground data matters. NASA's weather model does not know this plain is irrigated: it counts 70 days a year above 40 degrees. India Meteorological Department stations measured 31. We correct the NASA record to the stations month by month." |
| 2:40 | Evidence tab **Long-term water**. | "GRACE weighs the Earth's water from orbit. It is the only way to see groundwater from space, and it covers 300 km, so we say plainly: this is the region, not your tubewell." |
| 2:50 | Switch region to **Cauvery delta**, pick a plot. | "Same tool in Tamil Nadu: kuruvai, thaladi and samba rice, canal water instead of tubewells, and here GRACE shows no decline. The rotations and the questions change; the method does not." |

## Nevada walkthrough (3 minutes)

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
| 2:50 | Click **Long-term water** in the evidence tabs. | "And the long view: USGS wells near this field. The water table has been falling for decades. That is what a satellite cannot show at this scale and a well can." |
| 3:00 | Point at the checklist on the card. | "It ends with a checklist to take to a local agronomist. The tool supports the farmer's judgment. It does not replace it." |

### If you have 30 more seconds

- Click pivot **2**: the soil survey shows pH 9.3 and salinity 3.0 dS/m. The app flags
  that alfalfa loses yield above 2.0 while barley and triticale tolerate far more.
- **Map layers** > *Summer greenness*, and drag the year slider back to 2018 to watch
  pivots appear and go idle.
- **Draw my own field**, tap four corners inside the dashed box, **Finish field**: it is
  scored in the browser from a 140 m grid of soil, terrain and greenness, with satellite
  water use and MODIS marked "not available here" and confidence lowered.
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

**Pilots.** Three farming systems under water stress, one method: Diamond Valley, Nevada
(irrigated alfalfa under centre pivots, 14 fields detected from Landsat); Sangrur, Punjab
(rice-wheat on tubewells, 12 sample plots); the Cauvery delta, Tamil Nadu (canal-fed
paddy, 12 sample plots). Live at https://rohith-kumar-ss.github.io/field-shift/ as a
static site: the scoring runs in the browser.

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
- The same cross-checking carries to India with different ground data: NASA POWER
  against India Meteorological Department stations (days above 40 °C near Sangrur: 70
  raw, 31 at the stations), GRACE for the regional water trend (-3.8 cm a year over
  Punjab since 2002), crop seasons counted from MODIS where no crop map exists.
- Reproducible: one script per source, cached downloads, sanity checks logged in
  DATA_LOG.md, 49 automated tests (one compares the browser engine with the Python
  reference number by number), no demo data.

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

- Three pilot boxes, no local expert review yet, no prices or yields. In India the tool
  counts crop seasons but cannot name the crop, and soil comes from a global model.
