# ROTATION_KNOWLEDGE

The rotation knowledge bases behind the Rotation Scenario Explorer, one per pilot region. **Generated from `knowledge/<region>.yaml` by `python -m engine.knowledge_doc`; edit the YAML, not this file.**

## How to read it

- Every value is either taken from a cited reference or is a class score assigned by this project, with the reasoning given. Entries tagged PROJECT are judgments, not measurements.
- Class scores run from 0 (none / worst) to 1 (most / best). They are **not calibrated locally and have not been reviewed by a local agronomist**: each is a prompt for local review.
- Kc is the monthly crop coefficient on a grass reference (FAO-56): crop water demand = Kc x reference ET.
- Cover is the share of the soil surface protected by canopy, stubble or residue.

---

# Region: `cauvery_delta_tn`

Written for canal-irrigated paddy land of the old Cauvery delta (about 30 m above sea level, heavy clay soils, roughly 1,000-1,200 mm of rain of which about half falls in October-December). Seasons follow TNAU's Crop Production Guide: kuruvai (June-September), samba (August-January), thaladi (October-February) and rice-fallow crops afterwards.

- Existing rotation: **chosen by the farmer (default suggested from the number of green seasons seen from space)**
- Water yardstick: **kuruvai + thaladi rice**
- Hot day: above **38 °C**; heavy-rain day: **50 mm** or more

## How each priority is scored

| Priority | Formula | Details |
| :-- | :-- | :-- |
| Save water | `score = 2 x (1 - irrigation to deliver / kuruvai + thaladi rice irrigation to deliver)`, limited to 0-1 | Irrigation to deliver = sum over months of `Kc x reference ET x field factor` minus effective rain (USDA-SCS method), plus the water a paddy field takes to be puddled and kept flooded (`extra_water_mm`, zero for every other crop), averaged over the rotation. Reference ET is FAO-56 Penman-Monteith from NASA POWER daily weather, corrected month by month to a ground-station grid. The field factor is 1.0 unless the region has a crop map and satellite ET to anchor it. 0 = as thirsty as kuruvai + thaladi rice on that field, 1 = half the water or less. |
| Keep soil covered | `score = sum over months of (risk weight x share of soil covered)` | Risk weights sum to 1 over the year. They combine windy days (daily mean wind >= 4.5 m/s at 2 m) scaled by the soil's wind-erodibility index, and heavy-rain days (>= 50 mm) scaled by field tilt (SRTM) and the soil K factor. Cover comes from each crop's monthly cover table; months nobody occupies keep half of the previous month's cover as residue, never below 0.1. |
| Nitrogen from legumes | `sum of n_score x share of the crop's season`, limited to 1 | Averaged over the rotation. |
| Build organic matter | `sum of om_score x share of the crop's season - 0.08 per sowing` | Averaged over the rotation. Class scores only: organic matter cannot be seen from space. |
| Break pest cycles | `0.35 x diversity + 0.30 x change + 0.35 x hand-overs` | Diversity: (number of plant groups - 1) / 3. Change: share of crops that differ from one year to the next. Hand-overs: share of crop-to-crop hand-overs that are not cereal after cereal. |
| Income and assured sale | `sum of value_score x share of season x market factor`, reduced by water shortage | Market factor depends on the crop's market class and the farmer's market setting. Where a year needs more irrigation than the farmer's stated supply, the shortfall is shared in proportion and relative yield is `1 - Ky x (1 - ETa / ETc)` (FAO-33). No prices are used. |
| Heat and dry-spell resilience | `0.5 x drought_tolerance + 0.5 x (1 - days above the crop's heat limit in its season / 30)` | Weighted by each crop's share of the year, averaged over the rotation. |
| Easy to carry out | `0.45 x season fit + 0.30 x equipment available + 0.25 x (1 - establishment risk)`, minus 0.05 per extra sowing in a year | Season fit = share of the last 30 years whose frost-free season was at least as long as the crop needs (always 1 where frost does not limit crops). |

Overall score = sum of (weight x score), with the farmer's slider values normalised to sum to 1. Reference code: `engine/scoring.py`; browser port: `frontend/src/engine/scoring.ts`; the two are compared by `tests/test_parity.py`.

## Crop summary

| Crop | Group | Root depth (m) | Ky | Heat limit (°C) | Frost-free days needed | N | Organic matter | Drought tolerance | Value | Market | Equipment | Salt threshold (dS/m) | Flooding water (mm) |
| :-- | :-- | :-- | :-- | :-- | :-- | :-- | :-- | :-- | :-- | :-- | :-- | :-- | :-- |
| Kuruvai rice (short duration, June-September) | flooded rice | 0.6 | 1.2 | 38 | - | 0.0 | 0.35 | 0.1 | 0.5 | assured | puddler, combine | 3.0 | 500 |
| Thaladi rice (after kuruvai, October-February) | flooded rice | 0.6 | 1.2 | 38 | - | 0.0 | 0.35 | 0.3 | 0.5 | assured | puddler, combine | 3.0 | 400 |
| Samba rice (long duration, August-January) | flooded rice | 0.6 | 1.2 | 38 | - | 0.0 | 0.4 | 0.3 | 0.65 | assured | puddler, combine | 3.0 | 500 |
| Rice-fallow blackgram or greengram | legume | 0.7 | 1.0 | 40 | - | 0.5 | 0.25 | 0.6 | 0.15 | established | - | - | - |
| Rice-fallow cotton (February-June) | broadleaf | 1.2 | 0.85 | 40 | - | 0.0 | 0.3 | 0.65 | 0.4 | established | drill | 7.7 | - |
| Kuruvai-season maize or millet (instead of rice) | warm-season cereal | 1.2 | 1.1 | 38 | - | 0.0 | 0.45 | 0.6 | 0.28 | established | drill | 1.7 | - |
| Green manure (daincha or sunn hemp, ploughed in) | legume | 1.0 | 1.0 | 42 | - | 0.7 | 0.8 | 0.6 | 0.0 | none | - | - | - |
| Fallow (no crop) | none | 0.0 | 0.0 | 60 | - | 0.0 | 0.0 | 1.0 | 0.0 | none | - | - | - |

## Crops in detail

### Kuruvai rice (short duration, June-September)

Family: Poaceae. Group: flooded rice. Annual.

|  | Jan | Feb | Mar | Apr | May | Jun | Jul | Aug | Sep | Oct | Nov | Dec |
| :-- | :-- | :-- | :-- | :-- | :-- | :-- | :-- | :-- | :-- | :-- | :-- | :-- |
| Kc |  |  |  |  |  | 0.7 | 1.15 | 1.2 | 0.75 |  |  |  |
| Cover |  |  |  |  |  | 0.35 | 0.8 | 0.95 | 0.75 | 0.25 |  |  |

| Trait | Value | Source or rationale |
| :-- | :-- | :-- |
| crop coefficient (Kc) | see table | FAO56 Table 12: rice Kc 1.05 initial, 1.20 mid-season, 0.90-0.60 late; a 105-110 day crop transplanted in June (TNAU). |
| soil cover | see table | Flooded canopy June-September; stubble, soon puddled again, in October. |
| n score | 0.0 | PROJECT class value; see the crop's other notes. |
| n credit kg ha | 0 to 0 | PROJECT class value; see the crop's other notes. |
| om score | 0.35 | PROJECT class value; see the crop's other notes. |
| root depth m | 0.6 | PROJECT class value; see the crop's other notes. |
| heat limit c | 38 | PROJECT class value; see the crop's other notes. |
| drought tolerance | 0.1 | Grown in the hot, dry south-west monsoon months almost entirely on canal water: if the Mettur opening is late or flows are low, this crop fails or is not planted (METTUR). |
| ky | 1.2 | Grown in the hot, dry south-west monsoon months almost entirely on canal water: if the Mettur opening is late or flows are low, this crop fails or is not planted (METTUR). |
| frost free days needed | 0 | PROJECT class value; see the crop's other notes. |
| value score | 0.5 | With the thaladi crop this makes up the reference income (0.50 + 0.50 = 1.0). Bought at direct purchase centres at the support price. |
| market | assured | With the thaladi crop this makes up the reference income (0.50 + 0.50 = 1.0). Bought at direct purchase centres at the support price. |
| equipment | puddler, combine | PROJECT class value; see the crop's other notes. |
| establishment risk | 0.3 | Depends on the reservoir opening on time (METTUR). |
| plantings | 1 | PROJECT class value; see the crop's other notes. |
| salt threshold ds m | 3.0 | FAO29 Table 4: paddy rice 3.0 dS/m. |
| salt class | moderately sensitive | FAO29 Table 4: paddy rice 3.0 dS/m. |
| extra water mm | 500 | Puddling and keeping the field flooded take roughly 400-600 mm beyond what the crop transpires; in heavy delta clay less seeps away than in lighter soils (PROJECT estimate from FAO56 chapter on paddy). |

### Thaladi rice (after kuruvai, October-February)

Family: Poaceae. Group: flooded rice. Annual.

|  | Jan | Feb | Mar | Apr | May | Jun | Jul | Aug | Sep | Oct | Nov | Dec |
| :-- | :-- | :-- | :-- | :-- | :-- | :-- | :-- | :-- | :-- | :-- | :-- | :-- |
| Kc | 1.0 | 0.45 |  |  |  |  |  |  |  | 0.7 | 1.15 | 1.2 |
| Cover | 0.9 | 0.5 |  |  |  |  |  |  |  | 0.35 | 0.8 | 0.95 |

| Trait | Value | Source or rationale |
| :-- | :-- | :-- |
| crop coefficient (Kc) | see table | FAO56 Table 12 rice values on a 130-135 day crop transplanted in October (TNAU). |
| n score | 0.0 | PROJECT class value; see the crop's other notes. |
| n credit kg ha | 0 to 0 | PROJECT class value; see the crop's other notes. |
| om score | 0.35 | PROJECT class value; see the crop's other notes. |
| root depth m | 0.6 | PROJECT class value; see the crop's other notes. |
| heat limit c | 38 | PROJECT class value; see the crop's other notes. |
| drought tolerance | 0.3 | Grown through the north-east monsoon, so rain supplies much of its water; the risk is flooding in November-December rather than drought. |
| ky | 1.2 | Grown through the north-east monsoon, so rain supplies much of its water; the risk is flooding in November-December rather than drought. |
| frost free days needed | 0 | PROJECT class value; see the crop's other notes. |
| value score | 0.5 | Half of the reference income; assured purchase. |
| market | assured | Half of the reference income; assured purchase. |
| equipment | puddler, combine | PROJECT class value; see the crop's other notes. |
| establishment risk | 0.2 | Young seedlings can be submerged by cyclonic rain in November. |
| plantings | 1 | PROJECT class value; see the crop's other notes. |
| salt threshold ds m | 3.0 | PROJECT class value; see the crop's other notes. |
| salt class | moderately sensitive | PROJECT class value; see the crop's other notes. |
| extra water mm | 400 | As for kuruvai rice, a little less because the season is wet and cool (PROJECT). |

### Samba rice (long duration, August-January)

Family: Poaceae. Group: flooded rice. Annual.

|  | Jan | Feb | Mar | Apr | May | Jun | Jul | Aug | Sep | Oct | Nov | Dec |
| :-- | :-- | :-- | :-- | :-- | :-- | :-- | :-- | :-- | :-- | :-- | :-- | :-- |
| Kc | 0.55 |  |  |  |  |  |  | 0.6 | 1.1 | 1.2 | 1.2 | 1.05 |
| Cover | 0.6 |  |  |  |  |  |  | 0.3 | 0.75 | 0.95 | 0.95 | 0.95 |

| Trait | Value | Source or rationale |
| :-- | :-- | :-- |
| crop coefficient (Kc) | see table | FAO56 Table 12 rice values on a 150-160 day crop planted in August-September (TNAU). |
| n score | 0.0 | PROJECT class value; see the crop's other notes. |
| n credit kg ha | 0 to 0 | PROJECT class value; see the crop's other notes. |
| om score | 0.4 | A long crop leaves more root and stubble than a short one. |
| root depth m | 0.6 | PROJECT class value; see the crop's other notes. |
| heat limit c | 38 | PROJECT class value; see the crop's other notes. |
| drought tolerance | 0.3 | Most of its season falls in the north-east monsoon; needs canal water mainly to establish. |
| ky | 1.2 | Most of its season falls in the north-east monsoon; needs canal water mainly to establish. |
| frost free days needed | 0 | PROJECT class value; see the crop's other notes. |
| value score | 0.65 | One long crop yields more than either short crop but less than two (PROJECT class score). Assured purchase. |
| market | assured | One long crop yields more than either short crop but less than two (PROJECT class score). Assured purchase. |
| equipment | puddler, combine | PROJECT class value; see the crop's other notes. |
| establishment risk | 0.15 | PROJECT class value; see the crop's other notes. |
| plantings | 1 | PROJECT class value; see the crop's other notes. |
| salt threshold ds m | 3.0 | PROJECT class value; see the crop's other notes. |
| salt class | moderately sensitive | PROJECT class value; see the crop's other notes. |
| extra water mm | 500 | PROJECT class value; see the crop's other notes. |

### Rice-fallow blackgram or greengram

Family: Fabaceae. Group: legume. Annual. Grown on leftover soil moisture: adds no irrigation need.

|  | Jan | Feb | Mar | Apr | May | Jun | Jul | Aug | Sep | Oct | Nov | Dec |
| :-- | :-- | :-- | :-- | :-- | :-- | :-- | :-- | :-- | :-- | :-- | :-- | :-- |
| Kc |  | 0.5 | 1.0 | 0.5 |  |  |  |  |  |  |  |  |
| Cover |  | 0.4 | 0.75 | 0.5 |  |  |  |  |  |  |  |  |

| Trait | Value | Source or rationale |
| :-- | :-- | :-- |
| crop coefficient (Kc) | see table | FAO56 Table 12: green gram and similar pulses Kc 0.4 initial, 1.05 mid-season, 0.6-0.35 late. Broadcast into the standing rice a week before harvest and grown on the moisture left in the soil, with no irrigation (TRRI), so it adds nothing to irrigation need. |
| n score | 0.5 | A legume: fixes nitrogen and leaves a modest amount for the next rice crop (SARE; TRRI). |
| n credit kg ha | 15 to 40 | A legume: fixes nitrogen and leaves a modest amount for the next rice crop (SARE; TRRI). |
| om score | 0.25 | PROJECT class value; see the crop's other notes. |
| root depth m | 0.7 | PROJECT class value; see the crop's other notes. |
| heat limit c | 40 | PROJECT class value; see the crop's other notes. |
| drought tolerance | 0.6 | PROJECT class value; see the crop's other notes. |
| ky | 1.0 | PROJECT class value; see the crop's other notes. |
| frost free days needed | 0 | PROJECT class value; see the crop's other notes. |
| value score | 0.15 | Low and variable yields (often 300-500 kg/ha) but almost no cost. |
| market | established | Low and variable yields (often 300-500 kg/ha) but almost no cost. |
| equipment |  | PROJECT class value; see the crop's other notes. |
| establishment risk | 0.35 | Depends entirely on residual moisture and on January-February rain; yellow mosaic virus is common (TRRI). |
| plantings | 1 | PROJECT class value; see the crop's other notes. |
| salt threshold ds m | not documented | PROJECT class value; see the crop's other notes. |
| salt class | sensitive | PROJECT class value; see the crop's other notes. |

### Rice-fallow cotton (February-June)

Family: Malvaceae. Group: broadleaf. Annual.

|  | Jan | Feb | Mar | Apr | May | Jun | Jul | Aug | Sep | Oct | Nov | Dec |
| :-- | :-- | :-- | :-- | :-- | :-- | :-- | :-- | :-- | :-- | :-- | :-- | :-- |
| Kc |  | 0.35 | 0.7 | 1.1 | 1.15 | 0.6 |  |  |  |  |  |  |
| Cover |  | 0.15 | 0.45 | 0.8 | 0.9 | 0.6 | 0.25 |  |  |  |  |  |

| Trait | Value | Source or rationale |
| :-- | :-- | :-- |
| crop coefficient (Kc) | see table | FAO56 Table 12: cotton Kc 0.35 initial, 1.15-1.20 mid-season, 0.70-0.50 late, on the short rice-fallow season (TRRI). |
| n score | 0.0 | PROJECT class value; see the crop's other notes. |
| n credit kg ha | 0 to 0 | PROJECT class value; see the crop's other notes. |
| om score | 0.3 | PROJECT class value; see the crop's other notes. |
| root depth m | 1.2 | PROJECT class value; see the crop's other notes. |
| heat limit c | 40 | PROJECT class value; see the crop's other notes. |
| drought tolerance | 0.65 | Deep taproot (Ky 0.85, FAO33), but it grows through the hottest, driest months on borewell water. |
| ky | 0.85 | Deep taproot (Ky 0.85, FAO33), but it grows through the hottest, driest months on borewell water. |
| frost free days needed | 0 | PROJECT class value; see the crop's other notes. |
| value score | 0.4 | A real cash crop in the delta, sold through regulated markets at prices that swing. |
| market | established | A real cash crop in the delta, sold through regulated markets at prices that swing. |
| equipment | drill | PROJECT class value; see the crop's other notes. |
| establishment risk | 0.35 | Sown into wet rice stubble; summer showers and sucking pests decide the crop. |
| plantings | 1 | PROJECT class value; see the crop's other notes. |
| salt threshold ds m | 7.7 | FAO29 Table 4: cotton 7.7 dS/m. |
| salt class | tolerant | FAO29 Table 4: cotton 7.7 dS/m. |

### Kuruvai-season maize or millet (instead of rice)

Family: Poaceae. Group: warm-season cereal. Annual.

|  | Jan | Feb | Mar | Apr | May | Jun | Jul | Aug | Sep | Oct | Nov | Dec |
| :-- | :-- | :-- | :-- | :-- | :-- | :-- | :-- | :-- | :-- | :-- | :-- | :-- |
| Kc |  |  |  |  |  | 0.4 | 0.9 | 1.1 | 0.55 |  |  |  |
| Cover |  |  |  |  |  | 0.2 | 0.65 | 0.9 | 0.7 | 0.3 |  |  |

| Trait | Value | Source or rationale |
| :-- | :-- | :-- |
| crop coefficient (Kc) | see table | FAO56 Table 12: maize Kc mid-season 1.20, millet 1.00; an in-between value is used for a 100-110 day crop with no puddling or standing water. |
| n score | 0.0 | PROJECT class value; see the crop's other notes. |
| n credit kg ha | 0 to 0 | PROJECT class value; see the crop's other notes. |
| om score | 0.45 | PROJECT class value; see the crop's other notes. |
| root depth m | 1.2 | PROJECT class value; see the crop's other notes. |
| heat limit c | 38 | PROJECT class value; see the crop's other notes. |
| drought tolerance | 0.6 | Can be raised with a few irrigations from a borewell when canal water is late (TNAU alternative-crop advice for delayed-water years). |
| ky | 1.1 | Can be raised with a few irrigations from a borewell when canal water is late (TNAU alternative-crop advice for delayed-water years). |
| frost free days needed | 0 | PROJECT class value; see the crop's other notes. |
| value score | 0.28 | Worth clearly less than a rice crop and has no assured buyer (PROJECT class score). |
| market | established | Worth clearly less than a rice crop and has no assured buyer (PROJECT class score). |
| equipment | drill | PROJECT class value; see the crop's other notes. |
| establishment risk | 0.3 | Heavy delta clay drains slowly; these crops suffer if the field floods. |
| plantings | 1 | PROJECT class value; see the crop's other notes. |
| salt threshold ds m | 1.7 | FAO29 Table 4: maize 1.7 dS/m. |
| salt class | moderately sensitive | FAO29 Table 4: maize 1.7 dS/m. |

### Green manure (daincha or sunn hemp, ploughed in)

Family: Fabaceae. Group: legume. Annual.

|  | Jan | Feb | Mar | Apr | May | Jun | Jul | Aug | Sep | Oct | Nov | Dec |
| :-- | :-- | :-- | :-- | :-- | :-- | :-- | :-- | :-- | :-- | :-- | :-- | :-- |
| Kc |  |  |  |  | 0.5 | 0.9 | 0.6 |  |  |  |  |  |
| Cover |  |  |  |  | 0.3 | 0.8 | 0.6 |  |  |  |  |  |

| Trait | Value | Source or rationale |
| :-- | :-- | :-- |
| crop coefficient (Kc) | see table | Treated as a legume canopy (FAO56 Table 12 pulses) for the 45-50 days before it is ploughed in. |
| n score | 0.7 | A 45-day stand ploughed in before transplanting supplies roughly 40-80 kg N/ha to the rice (TNAU; SARE). |
| n credit kg ha | 40 to 80 | A 45-day stand ploughed in before transplanting supplies roughly 40-80 kg N/ha to the rice (TNAU; SARE). |
| om score | 0.8 | All of its growth goes back into the soil. |
| root depth m | 1.0 | PROJECT class value; see the crop's other notes. |
| heat limit c | 42 | PROJECT class value; see the crop's other notes. |
| drought tolerance | 0.6 | Needs summer showers or one or two irrigations to establish. |
| ky | 1.0 | Needs summer showers or one or two irrigations to establish. |
| frost free days needed | 0 | PROJECT class value; see the crop's other notes. |
| value score | 0.0 | No sale crop: its return is the fertiliser saved and the soil built. |
| market | none | No sale crop: its return is the fertiliser saved and the soil built. |
| equipment |  | PROJECT class value; see the crop's other notes. |
| establishment risk | 0.2 | PROJECT class value; see the crop's other notes. |
| plantings | 1 | PROJECT class value; see the crop's other notes. |
| salt threshold ds m | not documented | PROJECT class value; see the crop's other notes. |
| salt class | tolerant (daincha) | PROJECT class value; see the crop's other notes. |

### Fallow (no crop)

Family: none. Group: none. Annual.

|  | Jan | Feb | Mar | Apr | May | Jun | Jul | Aug | Sep | Oct | Nov | Dec |
| :-- | :-- | :-- | :-- | :-- | :-- | :-- | :-- | :-- | :-- | :-- | :-- | :-- |
| Kc |  |  |  |  |  |  |  |  |  |  |  |  |
| Cover | 0.2 | 0.2 | 0.15 | 0.15 | 0.15 | 0.15 | 0.15 | 0.2 | 0.2 | 0.25 | 0.25 | 0.25 |

| Trait | Value | Source or rationale |
| :-- | :-- | :-- |
| crop coefficient (Kc) | see table | No irrigation is applied. |
| soil cover | see table | Stubble and weeds only. |
| n score | 0.0 | PROJECT class value; see the crop's other notes. |
| n credit kg ha | 0 to 0 | PROJECT class value; see the crop's other notes. |
| om score | 0.0 | PROJECT class value; see the crop's other notes. |
| root depth m | 0.0 | PROJECT class value; see the crop's other notes. |
| heat limit c | 60 | PROJECT class value; see the crop's other notes. |
| drought tolerance | 1.0 | PROJECT class value; see the crop's other notes. |
| ky | 0.0 | PROJECT class value; see the crop's other notes. |
| frost free days needed | 0 | PROJECT class value; see the crop's other notes. |
| value score | 0.0 | PROJECT class value; see the crop's other notes. |
| market | none | PROJECT class value; see the crop's other notes. |
| equipment |  | PROJECT class value; see the crop's other notes. |
| establishment risk | 0.0 | PROJECT class value; see the crop's other notes. |
| plantings | 0 | PROJECT class value; see the crop's other notes. |
| salt threshold ds m | not documented | PROJECT class value; see the crop's other notes. |
| salt class | not applicable | PROJECT class value; see the crop's other notes. |

## Rotation strategies

### Kuruvai rice, thaladi rice and a rice-fallow pulse

`kuruvai_thaladi_pulse` (can be chosen as the existing rotation) - Two rice crops a year (June-September and October-February), then blackgram on leftover moisture.

| Year | What is in the field |
| :-- | :-- |
| 1 | Thaladi rice (Jan-Feb); Rice-fallow pulse (Feb-Apr); Kuruvai rice (Jun-Sep); Thaladi rice (Oct-Dec) |

**May offer**

- Two assured rice crops: the highest income when canal water arrives on time.
- A pulse at almost no cost adds a little nitrogen and food.
- The system the delta's canals, labour and markets are built around.

**Risks needing local review**

- The kuruvai crop depends on the Mettur reservoir opening on time and on borewells when it does not.
- Rice after rice builds up stem borer, leaf folder and brown planthopper, and puddles the soil twice a year.
- Thaladi seedlings can be drowned by cyclonic rain in November.

**Information gaps**

- How often canal water reached your village by mid-June in the last ten years.
- Whether you have a borewell, and its water quality.

**Check with a local expert**

- Ask the Public Works Department section office or the water users' association about this year's release schedule.
- Ask TNAU extension or the KVK which short-duration variety suits a late start.

### One samba rice crop and a rice-fallow pulse

`samba_pulse` (can be chosen as the existing rotation) - A single long-duration rice crop from August to January, then blackgram; the land rests in summer.

| Year | What is in the field |
| :-- | :-- |
| 1 | Samba rice (Jan); Rice-fallow pulse (Feb-Apr); Samba rice (Aug-Dec) |

**May offer**

- Needs canal water only from August, so a late Mettur opening matters much less.
- Most of the crop's water comes from the north-east monsoon.
- Half the puddling and a long break from rice pests.

**Risks needing local review**

- One rice crop earns clearly less than two.
- The field lies bare through the hot months from April to July.
- The whole year rides on one crop and on the north-east monsoon.

**Information gaps**

- Whether summer showers are enough here to grow a green manure in the gap.

**Check with a local expert**

- Compare your own income from single and double cropping over wet and dry years.

### Samba rice, rice-fallow pulse and a summer green manure

`samba_pulse_greenmanure` - As above, with daincha or sunn hemp grown in May-July and ploughed in before the samba crop.

| Year | What is in the field |
| :-- | :-- |
| 1 | Samba rice (Jan); Rice-fallow pulse (Feb-Apr); Green manure (May-Jul); Samba rice (Aug-Dec) |

**May offer**

- Two legumes a year: the most nitrogen and organic matter of the options here.
- The soil is covered in early summer instead of lying bare.
- Still needs canal water only from August.

**Risks needing local review**

- The green manure needs summer showers or a borewell irrigation to establish.
- One rice crop earns less than two; the green manure itself earns nothing.
- Ploughing in has to be done on time, about ten days before transplanting.

**Information gaps**

- Whether daincha or sunn hemp seed is available and subsidised this year.

**Check with a local expert**

- Ask the agriculture extension centre about green-manure seed supply.
- Use a soil test to see how much fertiliser the green manure lets you cut.

### Maize or millet in kuruvai, then thaladi rice and a pulse

`millet_thaladi_pulse` - A dry-sown maize or millet replaces the kuruvai rice; thaladi rice and blackgram follow.

| Year | What is in the field |
| :-- | :-- |
| 1 | Thaladi rice (Jan-Feb); Rice-fallow pulse (Feb-Apr); Maize or millet (Jun-Sep); Thaladi rice (Oct-Dec) |

**May offer**

- The June-September crop no longer needs standing water or an on-time canal.
- Keeps one assured rice crop and the land in use all year.
- A different plant group breaks the rice-after-rice pest cycle.

**Risks needing local review**

- Heavy delta clay drains slowly: maize and millets suffer if the field floods.
- No assured buyer at a support price for the kuruvai-season crop.
- Needs dry-land sowing equipment that paddy farms may not own.

**Information gaps**

- Whether your field drains well enough for an upland crop in July-August.
- Local buyers and prices for maize or millets.

**Check with a local expert**

- Ask TNAU extension about the alternative-crop package offered in delayed-water years.
- Try it on your best-drained field first.

### Samba rice and rice-fallow cotton

`samba_cotton` - A single samba rice crop, then cotton from February to June on borewell water.

| Year | What is in the field |
| :-- | :-- |
| 1 | Samba rice (Jan); Rice-fallow cotton (Feb-Jun); Samba rice (Aug-Dec) |

**May offer**

- A cash crop in the months when the canals are dry.
- A deep-rooted crop from a different family; tolerates salty water better than rice.
- Only one puddling a year.

**Risks needing local review**

- Cotton needs irrigation through the hottest months, from a borewell: it shifts water use to groundwater.
- Prices and yields swing; sucking pests are common.
- No pulse in the rotation, so no legume nitrogen.

**Information gaps**

- Borewell depth, yield and salinity.
- Last season's cotton price at the regulated market.

**Check with a local expert**

- Check borewell water quality before relying on it for cotton.
- Ask the Tamil Nadu Rice Research Institute about rice-fallow cotton varieties and sowing dates.

## Always check locally

- This year's Mettur opening date and the canal turn schedule for your village.
- A soil test (organic carbon, pH, salinity, nutrients), especially near the coast and at the tail end of canals.
- Which crops are being bought at support prices this season, and where.
- Varieties and sowing windows in the current TNAU Crop Production Guide.

## References

- **FAO56**: Allen, R.G., Pereira, L.S., Raes, D., Smith, M. (1998). Crop evapotranspiration. FAO Irrigation and Drainage Paper 56 (Tables 11, 12, 17, 22).
- **FAO33**: Doorenbos, J., Kassam, A.H. (1979). Yield response to water. FAO Irrigation and Drainage Paper 33; updated in Steduto et al. (2012), FAO Paper 66.
- **FAO29**: Ayers, R.S., Westcot, D.W. (1985). Water quality for agriculture. FAO Irrigation and Drainage Paper 29, Table 4 (crop salt tolerance).
- **TNAU**: Tamil Nadu Agricultural University, Coimbatore. Crop Production Guide (Agriculture) and the TNAU Agritech Portal: seasons, varieties and durations for the Cauvery delta zone.
- **TRRI**: Tamil Nadu Rice Research Institute, Aduthurai (TNAU): rice-fallow pulses and rice-fallow cotton recommendations for the delta.
- **METTUR**: Water Resources Department, Government of Tamil Nadu: the Mettur (Stanley) reservoir is customarily opened for delta irrigation on 12 June; in years of low storage the opening is delayed and the kuruvai crop is cut back.
- **SARE**: Clark, A. (ed.) (2007). Managing Cover Crops Profitably, 3rd edition. SARE Handbook 9 (legume nitrogen, green manures).
- **PROJECT**: Class score assigned by this project from the general agronomy cited alongside it; not locally calibrated.

---

# Region: `diamond_valley_nv`

Written for irrigated forage systems of the Great Basin (cold desert, about 1,800 m). Do not reuse the crop calendars elsewhere without local review.

- Existing rotation: **read from the crop map and greenness record**
- Water yardstick: **full-season alfalfa**
- Hot day: above **32 °C**; heavy-rain day: **10 mm** or more

## How each priority is scored

| Priority | Formula | Details |
| :-- | :-- | :-- |
| Save water | `score = 2 x (1 - irrigation to deliver / full-season alfalfa irrigation to deliver)`, limited to 0-1 | Irrigation to deliver = sum over months of `Kc x reference ET x field factor` minus effective rain (USDA-SCS method), plus the water a paddy field takes to be puddled and kept flooded (`extra_water_mm`, zero for every other crop), averaged over the rotation. Reference ET is FAO-56 Penman-Monteith from NASA POWER daily weather, corrected month by month to a ground-station grid. The field factor is 1.0 unless the region has a crop map and satellite ET to anchor it. 0 = as thirsty as full-season alfalfa on that field, 1 = half the water or less. |
| Keep soil covered | `score = sum over months of (risk weight x share of soil covered)` | Risk weights sum to 1 over the year. They combine windy days (daily mean wind >= 4.5 m/s at 2 m) scaled by the soil's wind-erodibility index, and heavy-rain days (>= 10 mm) scaled by field tilt (SRTM) and the soil K factor. Cover comes from each crop's monthly cover table; months nobody occupies keep half of the previous month's cover as residue, never below 0.1. |
| Nitrogen from legumes | legume year = its `n_score`; first year after the stand 0.6; second 0.3; a legume cover crop adds up to 0.5 | Averaged over the rotation. |
| Build organic matter | `sum of om_score x share of the crop's season - 0.08 per sowing` | Averaged over the rotation. Class scores only: organic matter cannot be seen from space. |
| Break pest cycles | `0.45 x break + 0.35 x diversity + 0.20 x stand age` | Break: 0 if the stand follows itself, 0.6 for a one-year gap, 1.0 for two or more. Diversity: (number of plant groups - 1) / 3. Stand age: 1.0 up to 5 years, falling to 0 at 10. |
| Forage and income | `sum of value_score x share of season x market factor`, reduced by water shortage | Market factor depends on the crop's market class and the farmer's market setting. Where a year needs more irrigation than the farmer's stated supply, the shortfall is shared in proportion and relative yield is `1 - Ky x (1 - ETa / ETc)` (FAO-33). No prices are used. |
| Drought and heat resilience | `0.5 x drought_tolerance + 0.5 x (1 - days above the crop's heat limit in its season / 45)` | Weighted by each crop's share of the year, averaged over the rotation. |
| Easy to carry out | `0.45 x season fit + 0.30 x equipment available + 0.25 x (1 - establishment risk)`, minus 0.05 per extra sowing in a year | Season fit = share of the last 30 years whose frost-free season was at least as long as the crop needs (always 1 where frost does not limit crops). |

Overall score = sum of (weight x score), with the farmer's slider values normalised to sum to 1. Reference code: `engine/scoring.py`; browser port: `frontend/src/engine/scoring.ts`; the two are compared by `tests/test_parity.py`.

## Crop summary

| Crop | Group | Root depth (m) | Ky | Heat limit (°C) | Frost-free days needed | N | Organic matter | Drought tolerance | Value | Market | Equipment | Salt threshold (dS/m) | Flooding water (mm) |
| :-- | :-- | :-- | :-- | :-- | :-- | :-- | :-- | :-- | :-- | :-- | :-- | :-- | :-- |
| Alfalfa hay (established stand) | legume | 2.5 | 1.1 | 32 | - | 1.0 | 0.75 | 0.6 | 1.0 | established | hay | 2.0 | - |
| Alfalfa, establishment year | legume | 1.2 | 1.1 | 32 | - | 0.8 | 0.5 | 0.35 | 0.55 | established | hay, drill | 2.0 | - |
| Winter cereal for hay (triticale, winter wheat or rye) | cool-season grass | 1.5 | 1.05 | 30 | - | 0.0 | 0.5 | 0.7 | 0.45 | established | hay, drill | 6.0 | - |
| Teff grass hay (warm-season annual) | warm-season grass | 0.8 | 0.9 | 38 | 75 | 0.0 | 0.4 | 0.75 | 0.5 | niche | hay, drill | - | - |
| Sorghum-sudangrass hay (warm-season annual) | warm-season grass | 1.5 | 0.9 | 38 | 100 | 0.0 | 0.55 | 0.85 | 0.45 | established | hay, drill | 6.8 | - |
| Spring small-grain hay (oats or barley) | cool-season grass | 1.2 | 1.15 | 30 | - | 0.0 | 0.4 | 0.55 | 0.4 | established | hay, drill | 8.0 | - |
| Spring small grain for grain (barley or spring wheat) | cool-season grass | 1.2 | 1.15 | 30 | - | 0.0 | 0.55 | 0.5 | 0.4 | established | drill, combine | 8.0 | - |
| Safflower (deep-rooted oilseed) | broadleaf | 2.0 | 0.8 | 36 | 110 | 0.0 | 0.35 | 0.85 | 0.3 | uncertain | drill, combine | - | - |
| Winter cover crop mix (cereal + winter pea or vetch) | cover mix | 1.0 | 1.0 | 30 | - | 0.5 | 0.75 | 0.6 | 0.05 | none (soil benefit; some grazing value) | drill | - | - |
| Irrigated grass hay or pasture | cool-season grass | 1.0 | 1.0 | 30 | - | 0.0 | 0.85 | 0.5 | 0.55 | established | hay | - | - |
| Idle or fallow (not irrigated) | none | 0.0 | 0.0 | 60 | - | 0.0 | 0.0 | 1.0 | 0.0 | none | - | - | - |
| Irrigated crop, type uncertain | unknown | 1.0 | 1.1 | 32 | - | 0.0 | 0.45 | 0.5 | 0.5 | established | - | - | - |

## Crops in detail

### Alfalfa hay (established stand)

Family: Fabaceae. Group: legume. Perennial. USDA crop-map codes: 36.

|  | Jan | Feb | Mar | Apr | May | Jun | Jul | Aug | Sep | Oct | Nov | Dec |
| :-- | :-- | :-- | :-- | :-- | :-- | :-- | :-- | :-- | :-- | :-- | :-- | :-- |
| Kc |  |  |  | 0.55 | 0.9 | 0.95 | 0.95 | 0.95 | 0.9 | 0.55 |  |  |
| Cover | 0.6 | 0.6 | 0.65 | 0.8 | 0.9 | 0.9 | 0.9 | 0.9 | 0.9 | 0.85 | 0.7 | 0.6 |

| Trait | Value | Source or rationale |
| :-- | :-- | :-- |
| crop coefficient (Kc) | see table | FAO56 Table 12: alfalfa hay, averaged over cutting cycles, Kc mid 0.95; lower in April and October when growth starts and ends around frost at this elevation (PROJECT). |
| soil cover | see table | Perennial canopy from spring to autumn; crowns and stubble still protect the surface in winter (RUSLE cover concept; PROJECT class values). |
| n score | 1.0 | Legume: fixes its own nitrogen. Credit to the following crop commonly 80-170 kg N/ha after a stand is taken out (SARE; UC3512). |
| n credit kg ha | 80 to 170 | Legume: fixes its own nitrogen. Credit to the following crop commonly 80-170 kg N/ha after a stand is taken out (SARE; UC3512). |
| om score | 0.75 | Large perennial root system and several years without tillage, but nearly all top growth leaves the field as hay (UC3512; PROJECT). |
| root depth m | 2.5 | FAO56 Table 22: maximum effective rooting depth 1.0-3.0 m for alfalfa. |
| heat limit c | 32 | Cool-season legume: growth and forage quality fall off above roughly 30-35 °C ('summer slump', UC3512). 32 °C is used as the stress line. |
| drought tolerance | 0.6 | Deep roots and the ability to go dormant and survive a dry spell, but yield falls in step with water (Ky 1.1, FAO33). |
| ky | 1.1 | Deep roots and the ability to go dormant and survive a dry spell, but yield falls in step with water (Ky 1.1, FAO33). |
| frost free days needed | 0 | PROJECT class value; see the crop's other notes. |
| value score | 1.0 | Reference crop for the valley: established hay market and equipment. All other value scores are relative to this. |
| market | established | Reference crop for the valley: established hay market and equipment. All other value scores are relative to this. |
| equipment | hay | PROJECT class value; see the crop's other notes. |
| establishment risk | 0.05 | PROJECT class value; see the crop's other notes. |
| plantings | 0 | PROJECT class value; see the crop's other notes. |
| salt threshold ds m | 2.0 | FAO29 Table 4: yield starts to fall above ECe 2.0 dS/m. |
| salt class | moderately sensitive | FAO29 Table 4: yield starts to fall above ECe 2.0 dS/m. |

### Alfalfa, establishment year

Family: Fabaceae. Group: legume. Perennial.

|  | Jan | Feb | Mar | Apr | May | Jun | Jul | Aug | Sep | Oct | Nov | Dec |
| :-- | :-- | :-- | :-- | :-- | :-- | :-- | :-- | :-- | :-- | :-- | :-- | :-- |
| Kc |  |  |  | 0.4 | 0.5 | 0.8 | 0.95 | 0.95 | 0.9 | 0.55 |  |  |
| Cover |  |  |  | 0.15 | 0.3 | 0.6 | 0.85 | 0.9 | 0.9 | 0.85 | 0.7 | 0.6 |

| Trait | Value | Source or rationale |
| :-- | :-- | :-- |
| crop coefficient (Kc) | see table | FAO56 Table 12 initial Kc 0.40 for alfalfa, rising to the established-stand value once the canopy closes (PROJECT monthly shape for a spring seeding). |
| soil cover | see table | Bare seedbed in April-May, the windiest part of the year, until the canopy closes. |
| n score | 0.8 | PROJECT class value; see the crop's other notes. |
| n credit kg ha | 0 to 40 | PROJECT class value; see the crop's other notes. |
| om score | 0.5 | PROJECT class value; see the crop's other notes. |
| root depth m | 1.2 | PROJECT class value; see the crop's other notes. |
| heat limit c | 32 | PROJECT class value; see the crop's other notes. |
| drought tolerance | 0.35 | Seedlings have shallow roots and cannot be allowed to dry out. |
| ky | 1.1 | Seedlings have shallow roots and cannot be allowed to dry out. |
| frost free days needed | 0 | PROJECT class value; see the crop's other notes. |
| value score | 0.55 | Seeding-year hay yield is commonly about half of an established stand (UC3512). |
| market | established | Seeding-year hay yield is commonly about half of an established stand (UC3512). |
| equipment | hay, drill | PROJECT class value; see the crop's other notes. |
| establishment risk | 0.35 | Small-seeded, shallow-sown crop: wind, crusting, frost and, after old alfalfa, autotoxicity can all thin a new stand (UC3512; AUTOTOX). |
| plantings | 1 | PROJECT class value; see the crop's other notes. |
| salt threshold ds m | 2.0 | PROJECT class value; see the crop's other notes. |
| salt class | moderately sensitive (seedlings more so) | PROJECT class value; see the crop's other notes. |

### Winter cereal for hay (triticale, winter wheat or rye)

Family: Poaceae. Group: cool-season grass. Annual. USDA crop-map codes: 24, 27, 205.

|  | Jan | Feb | Mar | Apr | May | Jun | Jul | Aug | Sep | Oct | Nov | Dec |
| :-- | :-- | :-- | :-- | :-- | :-- | :-- | :-- | :-- | :-- | :-- | :-- | :-- |
| Kc |  |  |  | 0.8 | 1.1 | 1.05 |  |  | 0.4 | 0.5 |  |  |
| Cover | 0.7 | 0.7 | 0.75 | 0.85 | 0.95 | 0.95 | 0.5 | 0.4 | 0.3 | 0.6 | 0.7 | 0.7 |

| Trait | Value | Source or rationale |
| :-- | :-- | :-- |
| crop coefficient (Kc) | see table | FAO56 Table 12: winter wheat Kc mid 1.15, initial 0.4-0.7; cut for hay around heading so the high-demand grain-fill period is skipped (PROJECT calendar: sown September, cut late June). |
| soil cover | see table | Green cover from October to June, including the windy spring; stubble afterwards (SARE). |
| n score | 0.0 | PROJECT class value; see the crop's other notes. |
| n credit kg ha | 0 to 0 | PROJECT class value; see the crop's other notes. |
| om score | 0.5 | Dense fibrous roots; top growth removed as hay (SARE). |
| root depth m | 1.5 | FAO56 Table 22: winter wheat 1.5-1.8 m. |
| heat limit c | 30 | Cool-season cereal; harvested before midsummer heat, which is the point of using it. |
| drought tolerance | 0.7 | Grows on winter and spring moisture and finishes before peak summer demand (drought escape); Ky about 1.05 (FAO33, winter wheat). |
| ky | 1.05 | Grows on winter and spring moisture and finishes before peak summer demand (drought escape); Ky about 1.05 (FAO33, winter wheat). |
| frost free days needed | 0 | PROJECT class value; see the crop's other notes. |
| value score | 0.45 | Cereal hay sells into the same hay market at a lower price and tonnage than alfalfa (PROJECT class score; no local prices in this tool). |
| market | established | Cereal hay sells into the same hay market at a lower price and tonnage than alfalfa (PROJECT class score; no local prices in this tool). |
| equipment | hay, drill | PROJECT class value; see the crop's other notes. |
| establishment risk | 0.15 | PROJECT class value; see the crop's other notes. |
| plantings | 1 | PROJECT class value; see the crop's other notes. |
| salt threshold ds m | 6.0 | FAO29 Table 4: wheat 6.0 dS/m, triticale 6.1, rye 11.4. |
| salt class | moderately tolerant to tolerant | FAO29 Table 4: wheat 6.0 dS/m, triticale 6.1, rye 11.4. |

### Teff grass hay (warm-season annual)

Family: Poaceae. Group: warm-season grass. Annual.

|  | Jan | Feb | Mar | Apr | May | Jun | Jul | Aug | Sep | Oct | Nov | Dec |
| :-- | :-- | :-- | :-- | :-- | :-- | :-- | :-- | :-- | :-- | :-- | :-- | :-- |
| Kc |  |  |  |  |  | 0.4 | 0.9 | 1.0 | 0.6 |  |  |  |
| Cover |  |  |  |  |  | 0.2 | 0.7 | 0.9 | 0.8 | 0.5 | 0.4 | 0.35 |

| Trait | Value | Source or rationale |
| :-- | :-- | :-- |
| crop coefficient (Kc) | see table | No FAO56 entry for teff; millet is used as the analogue (FAO56 Table 12: Kc mid 1.00, initial 0.30). Nevada trial figures for irrigation vary widely (UNR_TEF), so this is a LOW-confidence value. |
| soil cover | see table | Fast summer canopy; fine stubble is left over winter. |
| n score | 0.0 | PROJECT class value; see the crop's other notes. |
| n credit kg ha | 0 to 0 | PROJECT class value; see the crop's other notes. |
| om score | 0.4 | PROJECT class value; see the crop's other notes. |
| root depth m | 0.8 | Shallow fibrous root system (FAO56 Table 22 millet 1.0-2.0 m; teff is finer and shallower, PROJECT). |
| heat limit c | 38 | Warm-season (C4) grass from the Ethiopian highlands: tolerates heat that stresses alfalfa. |
| drought tolerance | 0.75 | Short season and C4 water-use efficiency; Ky taken as 0.9 by analogy with sorghum (FAO33). |
| ky | 0.9 | Short season and C4 water-use efficiency; Ky taken as 0.9 by analogy with sorghum (FAO33). |
| frost free days needed | 75 | Killed by frost. Roughly 45-55 days from sowing to a first cut and warm soil at sowing, so about 75 frost-free days are needed for one good cut and about 100 for two (UNR_TEF; PROJECT). |
| value score | 0.5 | Fine-stemmed hay with a horse-hay market, but buyers are few and local (UNR_TEF): a niche market. |
| market | niche | Fine-stemmed hay with a horse-hay market, but buyers are few and local (UNR_TEF): a niche market. |
| equipment | hay, drill | PROJECT class value; see the crop's other notes. |
| establishment risk | 0.4 | Tiny seed sown very shallow into a firm seedbed; stands fail if the surface dries or crusts (UNR_TEF). |
| plantings | 1 | PROJECT class value; see the crop's other notes. |
| salt threshold ds m | not documented | PROJECT class value; see the crop's other notes. |
| salt class | not well documented | PROJECT class value; see the crop's other notes. |

### Sorghum-sudangrass hay (warm-season annual)

Family: Poaceae. Group: warm-season grass. Annual. USDA crop-map codes: 4.

|  | Jan | Feb | Mar | Apr | May | Jun | Jul | Aug | Sep | Oct | Nov | Dec |
| :-- | :-- | :-- | :-- | :-- | :-- | :-- | :-- | :-- | :-- | :-- | :-- | :-- |
| Kc |  |  |  |  |  | 0.45 | 0.9 | 0.95 | 0.7 |  |  |  |
| Cover |  |  |  |  |  | 0.25 | 0.75 | 0.9 | 0.85 | 0.55 | 0.45 | 0.4 |

| Trait | Value | Source or rationale |
| :-- | :-- | :-- |
| crop coefficient (Kc) | see table | FAO56 Table 12: Sudan grass hay (annual), averaged cutting effects, Kc mid 0.90, initial 0.50. |
| n score | 0.0 | PROJECT class value; see the crop's other notes. |
| n credit kg ha | 0 to 0 | PROJECT class value; see the crop's other notes. |
| om score | 0.55 | High biomass and a deep, fibrous root system (SARE). |
| root depth m | 1.5 | FAO56 Table 22: sorghum 1.0-2.0 m. |
| heat limit c | 38 | PROJECT class value; see the crop's other notes. |
| drought tolerance | 0.85 | Sorghum Ky 0.9 (FAO33): one of the more drought-tolerant summer forages. |
| ky | 0.9 | Sorghum Ky 0.9 (FAO33): one of the more drought-tolerant summer forages. |
| frost free days needed | 100 | Needs warm soil and about 100 frost-free days for two cuts; frosted regrowth also carries a prussic-acid risk for livestock (SARE). |
| value score | 0.45 | PROJECT class value; see the crop's other notes. |
| market | established | PROJECT class value; see the crop's other notes. |
| equipment | hay, drill | PROJECT class value; see the crop's other notes. |
| establishment risk | 0.25 | PROJECT class value; see the crop's other notes. |
| plantings | 1 | PROJECT class value; see the crop's other notes. |
| salt threshold ds m | 6.8 | FAO29 Table 4: sorghum 6.8 dS/m. |
| salt class | moderately tolerant | FAO29 Table 4: sorghum 6.8 dS/m. |

### Spring small-grain hay (oats or barley)

Family: Poaceae. Group: cool-season grass. Annual. USDA crop-map codes: 28.

|  | Jan | Feb | Mar | Apr | May | Jun | Jul | Aug | Sep | Oct | Nov | Dec |
| :-- | :-- | :-- | :-- | :-- | :-- | :-- | :-- | :-- | :-- | :-- | :-- | :-- |
| Kc |  |  |  | 0.4 | 0.85 | 1.1 | 0.6 |  |  |  |  |  |
| Cover |  |  |  | 0.25 | 0.7 | 0.95 | 0.6 | 0.4 | 0.35 | 0.3 | 0.3 | 0.25 |

| Trait | Value | Source or rationale |
| :-- | :-- | :-- |
| crop coefficient (Kc) | see table | FAO56 Table 12: barley and oats Kc mid 1.15, initial 0.30; cut for hay in early July (PROJECT calendar: sown April). |
| soil cover | see table | Bare seedbed in April; stubble only from mid-July unless a cover crop follows. |
| n score | 0.0 | PROJECT class value; see the crop's other notes. |
| n credit kg ha | 0 to 0 | PROJECT class value; see the crop's other notes. |
| om score | 0.4 | PROJECT class value; see the crop's other notes. |
| root depth m | 1.2 | FAO56 Table 22: barley and oats 1.0-1.5 m. |
| heat limit c | 30 | PROJECT class value; see the crop's other notes. |
| drought tolerance | 0.55 | Spring cereals are sensitive to water shortage at heading (Ky about 1.15, FAO33) but finish before late-summer heat. |
| ky | 1.15 | Spring cereals are sensitive to water shortage at heading (Ky about 1.15, FAO33) but finish before late-summer heat. |
| frost free days needed | 0 | PROJECT class value; see the crop's other notes. |
| value score | 0.4 | The familiar, low-risk break crop in western alfalfa systems (AUTOTOX), with a modest hay value. |
| market | established | The familiar, low-risk break crop in western alfalfa systems (AUTOTOX), with a modest hay value. |
| equipment | hay, drill | PROJECT class value; see the crop's other notes. |
| establishment risk | 0.1 | PROJECT class value; see the crop's other notes. |
| plantings | 1 | PROJECT class value; see the crop's other notes. |
| salt threshold ds m | 8.0 | FAO29 Table 4: barley 8.0 dS/m (forage barley 6.0). |
| salt class | tolerant (barley); oats less so | FAO29 Table 4: barley 8.0 dS/m (forage barley 6.0). |

### Spring small grain for grain (barley or spring wheat)

Family: Poaceae. Group: cool-season grass. Annual. USDA crop-map codes: 21, 22, 23, 25.

|  | Jan | Feb | Mar | Apr | May | Jun | Jul | Aug | Sep | Oct | Nov | Dec |
| :-- | :-- | :-- | :-- | :-- | :-- | :-- | :-- | :-- | :-- | :-- | :-- | :-- |
| Kc |  |  |  | 0.4 | 0.85 | 1.15 | 1.0 | 0.35 |  |  |  |  |
| Cover |  |  |  | 0.25 | 0.7 | 0.95 | 0.95 | 0.7 | 0.6 | 0.55 | 0.5 | 0.5 |

| Trait | Value | Source or rationale |
| :-- | :-- | :-- |
| crop coefficient (Kc) | see table | FAO56 Table 12: barley, oats and spring wheat Kc mid 1.15, end 0.25-0.4. |
| n score | 0.0 | PROJECT class value; see the crop's other notes. |
| n credit kg ha | 0 to 0 | PROJECT class value; see the crop's other notes. |
| om score | 0.55 | Straw and stubble stay on the field when only the grain is taken (SARE). |
| root depth m | 1.2 | PROJECT class value; see the crop's other notes. |
| heat limit c | 30 | Heat above about 30 °C during grain fill cuts yield in cool-season cereals. |
| drought tolerance | 0.5 | PROJECT class value; see the crop's other notes. |
| ky | 1.15 | PROJECT class value; see the crop's other notes. |
| frost free days needed | 0 | PROJECT class value; see the crop's other notes. |
| value score | 0.4 | PROJECT class value; see the crop's other notes. |
| market | established | PROJECT class value; see the crop's other notes. |
| equipment | drill, combine | PROJECT class value; see the crop's other notes. |
| establishment risk | 0.1 | PROJECT class value; see the crop's other notes. |
| plantings | 1 | PROJECT class value; see the crop's other notes. |
| salt threshold ds m | 8.0 | FAO29 Table 4: barley 8.0, wheat 6.0 dS/m. |
| salt class | tolerant (barley); wheat moderately tolerant | FAO29 Table 4: barley 8.0, wheat 6.0 dS/m. |

### Safflower (deep-rooted oilseed)

Family: Asteraceae. Group: broadleaf. Annual. USDA crop-map codes: 33.

|  | Jan | Feb | Mar | Apr | May | Jun | Jul | Aug | Sep | Oct | Nov | Dec |
| :-- | :-- | :-- | :-- | :-- | :-- | :-- | :-- | :-- | :-- | :-- | :-- | :-- |
| Kc |  |  |  | 0.35 | 0.55 | 1.0 | 1.1 | 0.85 | 0.3 |  |  |  |
| Cover |  |  |  | 0.1 | 0.3 | 0.7 | 0.9 | 0.85 | 0.5 | 0.3 | 0.25 | 0.2 |

| Trait | Value | Source or rationale |
| :-- | :-- | :-- |
| crop coefficient (Kc) | see table | FAO56 Table 12: safflower Kc mid 1.0-1.15, initial 0.35, end 0.25. NOTE: fully irrigated safflower is not a low-water crop; its reputation comes from surviving on stored soil water. |
| n score | 0.0 | PROJECT class value; see the crop's other notes. |
| n credit kg ha | 0 to 0 | PROJECT class value; see the crop's other notes. |
| om score | 0.35 | Sparse, woody residue (PROJECT). |
| root depth m | 2.0 | FAO56 Table 22: 1.0-2.0 m; a taproot that can draw on moisture below most forage roots. |
| heat limit c | 36 | PROJECT class value; see the crop's other notes. |
| drought tolerance | 0.85 | Ky 0.8 (FAO33): yield falls less than water does, which is what makes deliberate under-irrigation workable. |
| ky | 0.8 | Ky 0.8 (FAO33): yield falls less than water does, which is what makes deliberate under-irrigation workable. |
| frost free days needed | 110 | A long-season crop (about 120-150 days sowing to harvest). Seedlings tolerate frost; 110 days is the PROJECT minimum for the frost-sensitive stem-elongation-to-flowering period plus ripening. |
| value score | 0.3 | An oilseed needs a buyer and an elevator within hauling distance; none is assumed here (PROJECT). This is the largest information gap for this crop. |
| market | uncertain | An oilseed needs a buyer and an elevator within hauling distance; none is assumed here (PROJECT). This is the largest information gap for this crop. |
| equipment | drill, combine | PROJECT class value; see the crop's other notes. |
| establishment risk | 0.25 | PROJECT class value; see the crop's other notes. |
| plantings | 1 | PROJECT class value; see the crop's other notes. |
| salt threshold ds m | not documented | PROJECT class value; see the crop's other notes. |
| salt class | moderately tolerant | FAO29 Table 4 lists safflower as moderately tolerant without a threshold value. |

### Winter cover crop mix (cereal + winter pea or vetch)

Family: Poaceae + Fabaceae. Group: cover mix. Annual. USDA crop-map codes: 224.

|  | Jan | Feb | Mar | Apr | May | Jun | Jul | Aug | Sep | Oct | Nov | Dec |
| :-- | :-- | :-- | :-- | :-- | :-- | :-- | :-- | :-- | :-- | :-- | :-- | :-- |
| Kc |  |  |  | 0.7 | 0.8 |  |  |  | 0.4 | 0.5 |  |  |
| Cover | 0.75 | 0.75 | 0.8 | 0.9 | 0.95 | 0.5 |  |  | 0.35 | 0.65 | 0.75 | 0.75 |

| Trait | Value | Source or rationale |
| :-- | :-- | :-- |
| crop coefficient (Kc) | see table | Treated as a small-grain canopy (FAO56 Table 12 cereals) until it is terminated in May. It uses real water: in a dry climate a cover crop is not free (SARE). |
| soil cover | see table | Green cover through winter and the windy spring; a mulch after termination (SARE). |
| n score | 0.5 | The legume part fixes nitrogen: SARE reports roughly 30-110 kg N/ha or more for winter peas and hairy vetch depending on growth before termination. |
| n credit kg ha | 30 to 110 | The legume part fixes nitrogen: SARE reports roughly 30-110 kg N/ha or more for winter peas and hairy vetch depending on growth before termination. |
| om score | 0.75 | All growth is returned to the soil (SARE). |
| root depth m | 1.0 | PROJECT class value; see the crop's other notes. |
| heat limit c | 30 | PROJECT class value; see the crop's other notes. |
| drought tolerance | 0.6 | PROJECT class value; see the crop's other notes. |
| ky | 1.0 | PROJECT class value; see the crop's other notes. |
| frost free days needed | 0 | PROJECT class value; see the crop's other notes. |
| value score | 0.05 | No sale crop; some grazing value where livestock are available. |
| market | none (soil benefit; some grazing value) | No sale crop; some grazing value where livestock are available. |
| equipment | drill | PROJECT class value; see the crop's other notes. |
| establishment risk | 0.2 | PROJECT class value; see the crop's other notes. |
| plantings | 1 | PROJECT class value; see the crop's other notes. |
| salt threshold ds m | not documented | PROJECT class value; see the crop's other notes. |
| salt class | depends on the mix | PROJECT class value; see the crop's other notes. |

### Irrigated grass hay or pasture

Family: Poaceae. Group: cool-season grass. Perennial. USDA crop-map codes: 37, 176, 59.

|  | Jan | Feb | Mar | Apr | May | Jun | Jul | Aug | Sep | Oct | Nov | Dec |
| :-- | :-- | :-- | :-- | :-- | :-- | :-- | :-- | :-- | :-- | :-- | :-- | :-- |
| Kc |  |  |  | 0.7 | 0.95 | 1.0 | 1.0 | 0.95 | 0.9 | 0.65 |  |  |
| Cover | 0.75 | 0.75 | 0.8 | 0.9 | 0.95 | 0.95 | 0.95 | 0.95 | 0.95 | 0.9 | 0.8 | 0.75 |

| Trait | Value | Source or rationale |
| :-- | :-- | :-- |
| crop coefficient (Kc) | see table | FAO56 Table 12: grass hay and rotated pasture Kc 0.85-1.05. |
| soil cover | see table | Year-round sod. |
| n score | 0.0 | PROJECT class value; see the crop's other notes. |
| n credit kg ha | 0 to 0 | PROJECT class value; see the crop's other notes. |
| om score | 0.85 | Dense perennial sod and fibrous roots, no tillage (SARE). |
| root depth m | 1.0 | PROJECT class value; see the crop's other notes. |
| heat limit c | 30 | PROJECT class value; see the crop's other notes. |
| drought tolerance | 0.5 | Cool-season grasses slow down or go dormant in summer heat and drought (PROJECT). |
| ky | 1.0 | Cool-season grasses slow down or go dormant in summer heat and drought (PROJECT). |
| frost free days needed | 0 | PROJECT class value; see the crop's other notes. |
| value score | 0.55 | PROJECT class value; see the crop's other notes. |
| market | established | PROJECT class value; see the crop's other notes. |
| equipment | hay | PROJECT class value; see the crop's other notes. |
| establishment risk | 0.1 | PROJECT class value; see the crop's other notes. |
| plantings | 0 | PROJECT class value; see the crop's other notes. |
| salt threshold ds m | not documented | PROJECT class value; see the crop's other notes. |
| salt class | varies by species (tall wheatgrass tolerant, orchardgrass sensitive) | PROJECT class value; see the crop's other notes. |

### Idle or fallow (not irrigated)

Family: none. Group: none. Annual. USDA crop-map codes: 61, 131, 152, 64, 65.

|  | Jan | Feb | Mar | Apr | May | Jun | Jul | Aug | Sep | Oct | Nov | Dec |
| :-- | :-- | :-- | :-- | :-- | :-- | :-- | :-- | :-- | :-- | :-- | :-- | :-- |
| Kc |  |  |  |  |  |  |  |  |  |  |  |  |
| Cover | 0.15 | 0.15 | 0.15 | 0.15 | 0.2 | 0.2 | 0.2 | 0.2 | 0.15 | 0.15 | 0.15 | 0.15 |

| Trait | Value | Source or rationale |
| :-- | :-- | :-- |
| crop coefficient (Kc) | see table | No irrigation is applied; evaporation is met by rain. |
| soil cover | see table | Sparse weeds and old residue only: the soil is largely exposed (RUSLE). |
| n score | 0.0 | PROJECT class value; see the crop's other notes. |
| n credit kg ha | 0 to 0 | PROJECT class value; see the crop's other notes. |
| om score | 0.0 | No living roots and no residue returned. |
| root depth m | 0.0 | PROJECT class value; see the crop's other notes. |
| heat limit c | 60 | PROJECT class value; see the crop's other notes. |
| drought tolerance | 1.0 | PROJECT class value; see the crop's other notes. |
| ky | 0.0 | PROJECT class value; see the crop's other notes. |
| frost free days needed | 0 | PROJECT class value; see the crop's other notes. |
| value score | 0.0 | PROJECT class value; see the crop's other notes. |
| market | none | PROJECT class value; see the crop's other notes. |
| equipment |  | PROJECT class value; see the crop's other notes. |
| establishment risk | 0.0 | PROJECT class value; see the crop's other notes. |
| plantings | 0 | PROJECT class value; see the crop's other notes. |
| salt threshold ds m | not documented | PROJECT class value; see the crop's other notes. |
| salt class | not applicable | PROJECT class value; see the crop's other notes. |

### Irrigated crop, type uncertain

Family: unknown. Group: unknown. Annual. USDA crop-map codes: 1, 43, 44, 5, 6, 12, 41, 42, 53.

|  | Jan | Feb | Mar | Apr | May | Jun | Jul | Aug | Sep | Oct | Nov | Dec |
| :-- | :-- | :-- | :-- | :-- | :-- | :-- | :-- | :-- | :-- | :-- | :-- | :-- |
| Kc |  |  |  | 0.4 | 0.7 | 1.0 | 1.05 | 0.9 | 0.6 |  |  |  |
| Cover |  |  |  | 0.2 | 0.5 | 0.8 | 0.9 | 0.9 | 0.7 | 0.4 | 0.35 | 0.3 |

| Trait | Value | Source or rationale |
| :-- | :-- | :-- |
| crop coefficient (Kc) | see table | Generic irrigated field crop (FAO56 Table 12 mid-range). Used only when the crop map and the greenness record disagree about what grew. |
| n score | 0.0 | PROJECT class value; see the crop's other notes. |
| n credit kg ha | 0 to 0 | PROJECT class value; see the crop's other notes. |
| om score | 0.45 | PROJECT class value; see the crop's other notes. |
| root depth m | 1.0 | PROJECT class value; see the crop's other notes. |
| heat limit c | 32 | PROJECT class value; see the crop's other notes. |
| drought tolerance | 0.5 | PROJECT class value; see the crop's other notes. |
| ky | 1.1 | PROJECT class value; see the crop's other notes. |
| frost free days needed | 0 | PROJECT class value; see the crop's other notes. |
| value score | 0.5 | Neutral placeholder. Correct the crop history to replace it. |
| market | established | Neutral placeholder. Correct the crop history to replace it. |
| equipment |  | PROJECT class value; see the crop's other notes. |
| establishment risk | 0.2 | PROJECT class value; see the crop's other notes. |
| plantings | 1 | PROJECT class value; see the crop's other notes. |
| salt threshold ds m | not documented | PROJECT class value; see the crop's other notes. |
| salt class | unknown | PROJECT class value; see the crop's other notes. |

## Rotation strategies

### Alfalfa with a two-year double-crop forage break

`cereal_teff_break` - Five years of alfalfa, then two years in which a winter cereal cut for hay in June is followed by teff in the summer, before alfalfa is sown again.

| Year | What is in the field |
| :-- | :-- |
| 1 | Alfalfa (new) (Apr-Dec) |
| 2 | Alfalfa (Jan-Dec) |
| 3 | Alfalfa (Jan-Dec) |
| 4 | Alfalfa (Jan-Dec) |
| 5 | Alfalfa (Jan-Aug); Winter cereal hay (Sep-Dec) |
| 6 | Winter cereal hay (Jan-Jun); Teff (Jun-Sep); Winter cereal hay (Sep-Dec) |
| 7 | Winter cereal hay (Jan-Jun); Teff (Jun-Dec) |

**May offer**

- Keeps the field producing forage in every year, with two crops in each break year.
- A two-year gap between alfalfa stands meets the usual autotoxicity guidance.
- The winter cereal keeps the soil covered through the windy spring.
- The cereal and teff can use nitrogen left by the alfalfa.

**Risks needing local review**

- Teff stands fail easily: tiny seed, shallow sowing, and no frost tolerance.
- Two sowings a year in the break years: more field work and a tight June turnaround.
- Double-cropping uses almost as much water as alfalfa: this is not a water-saving option.
- Herbicides used in alfalfa can carry over and injure the following crops.
- Teff and cereal hay need buyers; the teff market is small.

**Information gaps**

- Local teff and cereal-hay prices and buyers.
- Teff water use here: published Nevada figures disagree widely.
- Whether your frost-free season is long enough for teff in a cool year.
- Herbicide history of the field.

**Check with a local expert**

- Ask Extension or a neighbour who has grown teff at this elevation about sowing date and stand success.
- Check plant-back intervals on the labels of the herbicides used in the alfalfa.
- Line up a hay buyer before sowing teff.
- Confirm how your water right or allocation treats a split-season crop.

### Alfalfa with a deep-rooted crop and a winter cover crop

`safflower_cover` - Five years of alfalfa, then a year of safflower followed by a winter cover crop mix, then spring grain hay, before alfalfa is sown again.

| Year | What is in the field |
| :-- | :-- |
| 1 | Alfalfa (new) (Apr-Dec) |
| 2 | Alfalfa (Jan-Dec) |
| 3 | Alfalfa (Jan-Dec) |
| 4 | Alfalfa (Jan-Dec) |
| 5 | Alfalfa (Jan-Dec) |
| 6 | Safflower (Apr-Sep); Winter cover crop (Sep-Dec) |
| 7 | Winter cover crop (Jan-May); Oat/barley hay (May-Aug) |

**May offer**

- A taproot crop from a different plant family breaks alfalfa pest and disease cycles.
- The cover crop protects the soil over winter and spring and returns all its growth to the soil.
- Safflower tolerates being under-irrigated better than alfalfa.

**Risks needing local review**

- Fully irrigated safflower uses a lot of water; savings only come if it is deliberately under-irrigated.
- Needs a combine and a buyer: neither is certain here.
- A long-season crop in a short frost-free season.
- The cover crop uses water and has to be terminated on time.

**Information gaps**

- Whether any safflower buyer or elevator is within hauling distance.
- Safflower yield at this elevation: no local trial data in this tool.
- How much stored soil water is really available below the alfalfa root zone.

**Check with a local expert**

- Ask Extension whether safflower has been grown successfully in the valley.
- Get a custom-harvest quote if you do not own a combine.
- Check with NRCS whether a cover crop qualifies for cost-share.
- Take a deep soil-moisture or soil-test sample before relying on stored water.

### Shorter alfalfa stands with a small-grain hay year

`short_stand_grain` - Four years of alfalfa after the seeding year, then one year of oat or barley hay, then alfalfa again: the conventional, low-risk rotation of western alfalfa growers.

| Year | What is in the field |
| :-- | :-- |
| 1 | Alfalfa (new) (Apr-Dec) |
| 2 | Alfalfa (Jan-Dec) |
| 3 | Alfalfa (Jan-Dec) |
| 4 | Alfalfa (Jan-Dec) |
| 5 | Alfalfa (Jan-Dec) |
| 6 | Oat/barley hay (Apr-Dec) |

**May offer**

- Uses the hay equipment and hay market you already have.
- One year out of alfalfa reduces autotoxicity risk for the new seeding.
- The grain-hay year needs less water and none in late summer.
- Younger stands are usually thicker and more productive.

**Risks needing local review**

- Only a one-year break: the minimum that Extension guidance suggests.
- The field is bare in April and mostly stubble from July of the grain year.
- More frequent seeding costs: a seeding year yields about half.

**Information gaps**

- The real age and condition of your current stand.
- Your seeding cost and the price difference between grain hay and alfalfa.

**Check with a local expert**

- Walk the stand: count plants or stems per square foot to see if it is past its best.
- Discuss with Extension whether one year is a long enough break on your soil.

### Short alfalfa stand with three single-crop, low-water years

`water_saver` - Three years of alfalfa after the seeding year, then three years of one short-season forage each: winter cereal hay, then teff after a winter cover crop, then oat or barley hay. No irrigation in the gaps between them.

| Year | What is in the field |
| :-- | :-- |
| 1 | Alfalfa (new) (Apr-Dec) |
| 2 | Alfalfa (Jan-Dec) |
| 3 | Alfalfa (Jan-Dec) |
| 4 | Alfalfa (Jan-Aug); Winter cereal hay (Sep-Dec) |
| 5 | Winter cereal hay (Jan-Aug); Winter cover crop (Sep-Dec) |
| 6 | Winter cover crop (Jan-May); Teff (Jun-Dec) |
| 7 | Oat/barley hay (Apr-Dec) |

**May offer**

- The lowest irrigation need of the options here: each break year grows one short-season crop.
- Most of the water is used in spring, outside the July-August peak.
- Wide mix of plant families and a three-year alfalfa break.

**Risks needing local review**

- Less alfalfa and single-cropped years mean clearly less forage to sell.
- Stubble only in late summer and autumn of two of the break years.
- Depends on teff, the least certain crop here.

**Information gaps**

- Whether annual-forage hay can be sold in the volume this would produce.
- Labour and machinery time for five sowings in seven years.

**Check with a local expert**

- Budget it with Extension enterprise sheets using your own prices.
- Try the annual-forage sequence on part of one pivot first.

## Always check locally

- Water right, allocation or groundwater-plan rules that apply to this field.
- A current soil test (salinity, sodium, nutrients, organic matter).
- Local seed availability and sowing dates.
- Local buyers and prices for every crop that is new to you.

## References

- **FAO56**: Allen, R.G., Pereira, L.S., Raes, D., Smith, M. (1998). Crop evapotranspiration: guidelines for computing crop water requirements. FAO Irrigation and Drainage Paper 56 (Tables 11, 12, 17 and 22).
- **FAO33**: Doorenbos, J., Kassam, A.H. (1979). Yield response to water. FAO Irrigation and Drainage Paper 33 (yield response factor Ky); updated in Steduto et al. (2012), FAO Irrigation and Drainage Paper 66.
- **FAO29**: Ayers, R.S., Westcot, D.W. (1985). Water quality for agriculture. FAO Irrigation and Drainage Paper 29, Table 4 (crop salt tolerance, after Maas & Hoffman 1977).
- **SARE**: Clark, A. (ed.) (2007). Managing Cover Crops Profitably, 3rd edition. Sustainable Agriculture Research and Education (SARE) Handbook Series 9.
- **UC3512**: Summers, C.G., Putnam, D.H. (eds.) (2008). Irrigated Alfalfa Management for Mediterranean and Desert Zones. University of California Agriculture and Natural Resources Publication 3512.
- **AUTOTOX**: Extension guidance on alfalfa autotoxicity: University of Minnesota Extension ('allow at least one year between terminating an old alfalfa stand and reseeding'); Oklahoma State University Extension, 'Alfalfa Autotoxicity: A Good Reason to Rotate Alfalfa Fields'; University of Wisconsin Extension, 'Understanding autotoxicity in alfalfa'.
- **UNR_TEF**: Davison, J. (2005). Tef Demonstration Planting Results for 2004. University of Nevada, Reno Extension Fact Sheet FS-05-28, and related UNR Extension tef fact sheets and news releases (reported irrigation ranges from about one third of alfalfa's to 2.7-3.7 acre-feet per acre: the spread is itself a finding).
- **NRCS_WIND**: USDA NRCS National Agronomy Manual, Part 502 (Wind Erosion): wind erodibility groups (WEG) and soil erodibility index I.
- **RUSLE**: Renard, K.G. et al. (1997). Predicting Soil Erosion by Water: RUSLE. USDA Agriculture Handbook 703 (cover-management concept: soil is protected in proportion to canopy and residue cover when erosive weather arrives).
- **NEH623**: USDA NRCS National Engineering Handbook, Part 623, Chapter 2: Irrigation Water Requirements (USDA-SCS effective precipitation method).
- **PROJECT**: Class score assigned by this project from the general agronomy cited alongside it; not locally calibrated.

---

# Region: `punjab_sangrur`

Written for irrigated rice-wheat farms of central-southern Punjab (about 230 m, semi-arid, 550-650 mm of rain, three quarters of it in July-September). Crop calendars follow PAU's Package of Practices. Do not reuse elsewhere without local review.

- Existing rotation: **chosen by the farmer (default suggested from the number of green seasons seen from space)**
- Water yardstick: **rice-wheat**
- Hot day: above **40 °C**; heavy-rain day: **50 mm** or more

## How each priority is scored

| Priority | Formula | Details |
| :-- | :-- | :-- |
| Save water | `score = 2 x (1 - irrigation to deliver / rice-wheat irrigation to deliver)`, limited to 0-1 | Irrigation to deliver = sum over months of `Kc x reference ET x field factor` minus effective rain (USDA-SCS method), plus the water a paddy field takes to be puddled and kept flooded (`extra_water_mm`, zero for every other crop), averaged over the rotation. Reference ET is FAO-56 Penman-Monteith from NASA POWER daily weather, corrected month by month to a ground-station grid. The field factor is 1.0 unless the region has a crop map and satellite ET to anchor it. 0 = as thirsty as rice-wheat on that field, 1 = half the water or less. |
| Keep soil covered | `score = sum over months of (risk weight x share of soil covered)` | Risk weights sum to 1 over the year. They combine windy days (daily mean wind >= 4.5 m/s at 2 m) scaled by the soil's wind-erodibility index, and heavy-rain days (>= 50 mm) scaled by field tilt (SRTM) and the soil K factor. Cover comes from each crop's monthly cover table; months nobody occupies keep half of the previous month's cover as residue, never below 0.1. |
| Nitrogen from legumes | `sum of n_score x share of the crop's season`, limited to 1 | Averaged over the rotation. |
| Build organic matter | `sum of om_score x share of the crop's season - 0.08 per sowing` | Averaged over the rotation. Class scores only: organic matter cannot be seen from space. |
| Break pest cycles | `0.35 x diversity + 0.30 x change + 0.35 x hand-overs` | Diversity: (number of plant groups - 1) / 3. Change: share of crops that differ from one year to the next. Hand-overs: share of crop-to-crop hand-overs that are not cereal after cereal. |
| Income and assured sale | `sum of value_score x share of season x market factor`, reduced by water shortage | Market factor depends on the crop's market class and the farmer's market setting. Where a year needs more irrigation than the farmer's stated supply, the shortfall is shared in proportion and relative yield is `1 - Ky x (1 - ETa / ETc)` (FAO-33). No prices are used. |
| Heat and dry-spell resilience | `0.5 x drought_tolerance + 0.5 x (1 - days above the crop's heat limit in its season / 30)` | Weighted by each crop's share of the year, averaged over the rotation. |
| Easy to carry out | `0.45 x season fit + 0.30 x equipment available + 0.25 x (1 - establishment risk)`, minus 0.05 per extra sowing in a year | Season fit = share of the last 30 years whose frost-free season was at least as long as the crop needs (always 1 where frost does not limit crops). |

Overall score = sum of (weight x score), with the farmer's slider values normalised to sum to 1. Reference code: `engine/scoring.py`; browser port: `frontend/src/engine/scoring.ts`; the two are compared by `tests/test_parity.py`.

## Crop summary

| Crop | Group | Root depth (m) | Ky | Heat limit (°C) | Frost-free days needed | N | Organic matter | Drought tolerance | Value | Market | Equipment | Salt threshold (dS/m) | Flooding water (mm) |
| :-- | :-- | :-- | :-- | :-- | :-- | :-- | :-- | :-- | :-- | :-- | :-- | :-- | :-- |
| Rice (paddy, transplanted) | flooded rice | 0.6 | 1.2 | 38 | - | 0.0 | 0.3 | 0.15 | 0.55 | assured | combine | 3.0 | 800 |
| Wheat | cool-season cereal | 1.5 | 1.05 | 32 | - | 0.0 | 0.4 | 0.5 | 0.45 | assured | drill, combine | 6.0 | - |
| Kharif maize | warm-season cereal | 1.3 | 1.25 | 36 | - | 0.0 | 0.5 | 0.45 | 0.38 | established | planter, combine | 1.7 | - |
| Cotton (Bt hybrids) | broadleaf | 1.4 | 0.85 | 40 | - | 0.0 | 0.35 | 0.7 | 0.5 | established | planter | 7.7 | - |
| Summer moong (green gram, 60-65 days) | legume | 0.8 | 1.0 | 42 | - | 0.6 | 0.3 | 0.5 | 0.15 | established | drill | 1.8 | - |
| Gram (chickpea) | legume | 1.0 | 0.9 | 32 | - | 0.7 | 0.35 | 0.75 | 0.3 | established | drill, combine | - | - |
| Fallow (no crop) | none | 0.0 | 0.0 | 60 | - | 0.0 | 0.0 | 1.0 | 0.0 | none | - | - | - |

## Crops in detail

### Rice (paddy, transplanted)

Family: Poaceae. Group: flooded rice. Annual.

|  | Jan | Feb | Mar | Apr | May | Jun | Jul | Aug | Sep | Oct | Nov | Dec |
| :-- | :-- | :-- | :-- | :-- | :-- | :-- | :-- | :-- | :-- | :-- | :-- | :-- |
| Kc |  |  |  |  |  | 0.55 | 1.1 | 1.2 | 1.15 | 0.5 |  |  |
| Cover |  |  |  |  |  | 0.3 | 0.7 | 0.95 | 0.95 | 0.6 | 0.15 |  |

| Trait | Value | Source or rationale |
| :-- | :-- | :-- |
| crop coefficient (Kc) | see table | FAO56 Table 12: rice Kc 1.05 initial, 1.20 mid-season, 0.90-0.60 late. June is counted at about half because transplanting starts from mid-June (ACT2009). |
| soil cover | see table | Standing water and canopy from July to September; after combine harvest the loose straw is usually burnt or removed, leaving the soil nearly bare in late October-November (PROJECT). |
| n score | 0.0 | PROJECT class value; see the crop's other notes. |
| n credit kg ha | 0 to 0 | PROJECT class value; see the crop's other notes. |
| om score | 0.3 | Puddling breaks soil structure every year and most straw is burnt or removed (CA; PROJECT). |
| root depth m | 0.6 | PROJECT class value; see the crop's other notes. |
| heat limit c | 38 | PROJECT class value; see the crop's other notes. |
| drought tolerance | 0.15 | The most water-sensitive cereal: yield falls faster than water (Ky about 1.2, FAO33). |
| ky | 1.2 | The most water-sensitive cereal: yield falls faster than water (Ky about 1.2, FAO33). |
| frost free days needed | 0 | PROJECT class value; see the crop's other notes. |
| value score | 0.55 | With wheat this makes up the reference income (rice 0.55 + wheat 0.45 = 1.0). Procured at the minimum support price: an assured sale. |
| market | assured | With wheat this makes up the reference income (rice 0.55 + wheat 0.45 = 1.0). Procured at the minimum support price: an assured sale. |
| equipment | combine | PROJECT class value; see the crop's other notes. |
| establishment risk | 0.1 | PROJECT class value; see the crop's other notes. |
| plantings | 1 | PROJECT class value; see the crop's other notes. |
| salt threshold ds m | 3.0 | FAO29 Table 4: paddy rice 3.0 dS/m. |
| salt class | moderately sensitive | FAO29 Table 4: paddy rice 3.0 dS/m. |
| extra water mm | 800 | On top of what the crop transpires, puddling and keeping the field flooded take roughly 700-1,000 mm more pumping. Most of that seeps back to the aquifer, so it costs pumping and electricity rather than groundwater (HUMPHREYS). It is shown in the app but not counted in the water score. |

### Wheat

Family: Poaceae. Group: cool-season cereal. Annual.

|  | Jan | Feb | Mar | Apr | May | Jun | Jul | Aug | Sep | Oct | Nov | Dec |
| :-- | :-- | :-- | :-- | :-- | :-- | :-- | :-- | :-- | :-- | :-- | :-- | :-- |
| Kc | 1.05 | 1.15 | 1.05 | 0.35 |  |  |  |  |  |  | 0.4 | 0.7 |
| Cover | 0.85 | 0.95 | 0.95 | 0.7 | 0.35 |  |  |  |  |  | 0.2 | 0.55 |

| Trait | Value | Source or rationale |
| :-- | :-- | :-- |
| crop coefficient (Kc) | see table | FAO56 Table 12: winter wheat Kc 0.4-0.7 initial, 1.15 mid-season, 0.25-0.4 at harvest; sown in November, harvested mid-April (PAU). |
| soil cover | see table | Bare seedbed in November unless sown into rice residue; full canopy January-March; stubble after April. |
| n score | 0.0 | PROJECT class value; see the crop's other notes. |
| n credit kg ha | 0 to 0 | PROJECT class value; see the crop's other notes. |
| om score | 0.4 | Fibrous roots; the straw is taken off as fodder. |
| root depth m | 1.5 | PROJECT class value; see the crop's other notes. |
| heat limit c | 32 | Heat above about 32 °C during grain filling in March shrivels the grain ('terminal heat'); this is the crop's main climate risk here (PAU). |
| drought tolerance | 0.5 | PROJECT class value; see the crop's other notes. |
| ky | 1.05 | PROJECT class value; see the crop's other notes. |
| frost free days needed | 0 | PROJECT class value; see the crop's other notes. |
| value score | 0.45 | Reference income together with rice; procured at the minimum support price. |
| market | assured | Reference income together with rice; procured at the minimum support price. |
| equipment | drill, combine | PROJECT class value; see the crop's other notes. |
| establishment risk | 0.1 | PROJECT class value; see the crop's other notes. |
| plantings | 1 | PROJECT class value; see the crop's other notes. |
| salt threshold ds m | 6.0 | FAO29 Table 4: wheat 6.0 dS/m. |
| salt class | moderately tolerant | FAO29 Table 4: wheat 6.0 dS/m. |

### Kharif maize

Family: Poaceae. Group: warm-season cereal. Annual.

|  | Jan | Feb | Mar | Apr | May | Jun | Jul | Aug | Sep | Oct | Nov | Dec |
| :-- | :-- | :-- | :-- | :-- | :-- | :-- | :-- | :-- | :-- | :-- | :-- | :-- |
| Kc |  |  |  |  |  | 0.35 | 0.8 | 1.2 | 1.1 | 0.45 |  |  |
| Cover |  |  |  |  |  | 0.15 | 0.6 | 0.9 | 0.9 | 0.6 | 0.35 |  |

| Trait | Value | Source or rationale |
| :-- | :-- | :-- |
| crop coefficient (Kc) | see table | FAO56 Table 12: maize (grain) Kc 0.3 initial, 1.20 mid-season, 0.35-0.6 late; sown mid-June to early July (PAU). No puddling and no standing water. |
| n score | 0.0 | PROJECT class value; see the crop's other notes. |
| n credit kg ha | 0 to 0 | PROJECT class value; see the crop's other notes. |
| om score | 0.5 | More stalk and root left than rice, with no puddling (CA). |
| root depth m | 1.3 | PROJECT class value; see the crop's other notes. |
| heat limit c | 36 | PROJECT class value; see the crop's other notes. |
| drought tolerance | 0.45 | Very sensitive to dry spells at tasselling and silking (Ky 1.25, FAO33); it also suffers from waterlogging after heavy monsoon rain. |
| ky | 1.25 | Very sensitive to dry spells at tasselling and silking (Ky 1.25, FAO33); it also suffers from waterlogging after heavy monsoon rain. |
| frost free days needed | 0 | PROJECT class value; see the crop's other notes. |
| value score | 0.38 | A support price is announced but little is bought at it; prices in the mandi swing, and grain has to be dried (PROJECT class score; no prices in this tool). |
| market | established | A support price is announced but little is bought at it; prices in the mandi swing, and grain has to be dried (PROJECT class score; no prices in this tool). |
| equipment | planter, combine | PROJECT class value; see the crop's other notes. |
| establishment risk | 0.25 | Stands are easily lost to waterlogging or stray cattle; fall armyworm has been a pest since 2018 (PAU). |
| plantings | 1 | PROJECT class value; see the crop's other notes. |
| salt threshold ds m | 1.7 | FAO29 Table 4: maize 1.7 dS/m. |
| salt class | moderately sensitive | FAO29 Table 4: maize 1.7 dS/m. |

### Cotton (Bt hybrids)

Family: Malvaceae. Group: broadleaf. Annual.

|  | Jan | Feb | Mar | Apr | May | Jun | Jul | Aug | Sep | Oct | Nov | Dec |
| :-- | :-- | :-- | :-- | :-- | :-- | :-- | :-- | :-- | :-- | :-- | :-- | :-- |
| Kc |  |  |  |  | 0.35 | 0.6 | 1.0 | 1.15 | 1.15 | 0.8 | 0.45 |  |
| Cover |  |  |  |  | 0.1 | 0.35 | 0.7 | 0.9 | 0.9 | 0.8 | 0.5 |  |

| Trait | Value | Source or rationale |
| :-- | :-- | :-- |
| crop coefficient (Kc) | see table | FAO56 Table 12: cotton Kc 0.35 initial, 1.15-1.20 mid-season, 0.70-0.50 late; sown late April-May, picked October-November (PAU). |
| n score | 0.0 | PROJECT class value; see the crop's other notes. |
| n credit kg ha | 0 to 0 | PROJECT class value; see the crop's other notes. |
| om score | 0.35 | PROJECT class value; see the crop's other notes. |
| root depth m | 1.4 | PROJECT class value; see the crop's other notes. |
| heat limit c | 40 | PROJECT class value; see the crop's other notes. |
| drought tolerance | 0.7 | Deep taproot; yield falls less than water (Ky 0.85, FAO33). |
| ky | 0.85 | Deep taproot; yield falls less than water (Ky 0.85, FAO33). |
| frost free days needed | 0 | PROJECT class value; see the crop's other notes. |
| value score | 0.5 | Can match paddy in a good year, but yields and prices swing widely; bought by the Cotton Corporation of India and private traders. |
| market | established | Can match paddy in a good year, but yields and prices swing widely; bought by the Cotton Corporation of India and private traders. |
| equipment | planter | PROJECT class value; see the crop's other notes. |
| establishment risk | 0.4 | Whitefly and pink bollworm have caused repeated crop failures in the cotton belt; this is the crop's defining risk (PAU). |
| plantings | 1 | PROJECT class value; see the crop's other notes. |
| salt threshold ds m | 7.7 | FAO29 Table 4: cotton 7.7 dS/m. |
| salt class | tolerant | FAO29 Table 4: cotton 7.7 dS/m. |

### Summer moong (green gram, 60-65 days)

Family: Fabaceae. Group: legume. Annual.

|  | Jan | Feb | Mar | Apr | May | Jun | Jul | Aug | Sep | Oct | Nov | Dec |
| :-- | :-- | :-- | :-- | :-- | :-- | :-- | :-- | :-- | :-- | :-- | :-- | :-- |
| Kc |  |  |  | 0.3 | 0.95 | 0.5 |  |  |  |  |  |  |
| Cover |  |  |  | 0.2 | 0.8 | 0.6 |  |  |  |  |  |  |

| Trait | Value | Source or rationale |
| :-- | :-- | :-- |
| crop coefficient (Kc) | see table | FAO56 Table 12: green gram Kc 0.4 initial, 1.05 mid-season, 0.60-0.35 late. Short-duration varieties fit between wheat harvest and paddy transplanting (PAU). April and June are part months. |
| n score | 0.6 | A legume that fixes nitrogen; ploughing in the residue after picking the pods returns roughly 25-50 kg N/ha (SARE; CA). |
| n credit kg ha | 25 to 50 | A legume that fixes nitrogen; ploughing in the residue after picking the pods returns roughly 25-50 kg N/ha (SARE; CA). |
| om score | 0.3 | PROJECT class value; see the crop's other notes. |
| root depth m | 0.8 | PROJECT class value; see the crop's other notes. |
| heat limit c | 42 | PROJECT class value; see the crop's other notes. |
| drought tolerance | 0.5 | Grown in May-June, when the weather's water demand is at its yearly peak. |
| ky | 1.0 | Grown in May-June, when the weather's water demand is at its yearly peak. |
| frost free days needed | 0 | PROJECT class value; see the crop's other notes. |
| value score | 0.15 | A small extra crop; a support price exists but buying at it has been patchy. |
| market | established | A small extra crop; a support price exists but buying at it has been patchy. |
| equipment | drill | PROJECT class value; see the crop's other notes. |
| establishment risk | 0.3 | Pre-monsoon rain at maturity spoils the grain, and the crop needs 3-4 irrigations in the hottest weeks of the year (PAU). |
| plantings | 1 | PROJECT class value; see the crop's other notes. |
| salt threshold ds m | 1.8 | PROJECT class value; see the crop's other notes. |
| salt class | sensitive | PROJECT class value; see the crop's other notes. |

### Gram (chickpea)

Family: Fabaceae. Group: legume. Annual.

|  | Jan | Feb | Mar | Apr | May | Jun | Jul | Aug | Sep | Oct | Nov | Dec |
| :-- | :-- | :-- | :-- | :-- | :-- | :-- | :-- | :-- | :-- | :-- | :-- | :-- |
| Kc | 1.0 | 0.8 | 0.35 |  |  |  |  |  |  | 0.4 | 0.6 | 0.9 |
| Cover | 0.9 | 0.9 | 0.6 | 0.3 |  |  |  |  |  | 0.15 | 0.45 | 0.75 |

| Trait | Value | Source or rationale |
| :-- | :-- | :-- |
| crop coefficient (Kc) | see table | FAO56 Table 12: chickpea Kc 0.4 initial, 1.00 mid-season, 0.35 late; sown late October, harvested late March (PAU). |
| n score | 0.7 | A legume: fixes its own nitrogen and leaves some for the next crop (SARE). |
| n credit kg ha | 20 to 40 | A legume: fixes its own nitrogen and leaves some for the next crop (SARE). |
| om score | 0.35 | PROJECT class value; see the crop's other notes. |
| root depth m | 1.0 | PROJECT class value; see the crop's other notes. |
| heat limit c | 32 | PROJECT class value; see the crop's other notes. |
| drought tolerance | 0.75 | Needs only one or two irrigations; too much water or winter rain brings wilt and blight (PAU). |
| ky | 0.9 | Needs only one or two irrigations; too much water or winter rain brings wilt and blight (PAU). |
| frost free days needed | 0 | PROJECT class value; see the crop's other notes. |
| value score | 0.3 | Lower and less certain yield than wheat; frost in January and pod borer are the main losses (PROJECT class score). |
| market | established | Lower and less certain yield than wheat; frost in January and pod borer are the main losses (PROJECT class score). |
| equipment | drill, combine | PROJECT class value; see the crop's other notes. |
| establishment risk | 0.3 | PROJECT class value; see the crop's other notes. |
| plantings | 1 | PROJECT class value; see the crop's other notes. |
| salt threshold ds m | not documented | PROJECT class value; see the crop's other notes. |
| salt class | sensitive | PROJECT class value; see the crop's other notes. |

### Fallow (no crop)

Family: none. Group: none. Annual.

|  | Jan | Feb | Mar | Apr | May | Jun | Jul | Aug | Sep | Oct | Nov | Dec |
| :-- | :-- | :-- | :-- | :-- | :-- | :-- | :-- | :-- | :-- | :-- | :-- | :-- |
| Kc |  |  |  |  |  |  |  |  |  |  |  |  |
| Cover | 0.15 | 0.15 | 0.15 | 0.15 | 0.15 | 0.15 | 0.25 | 0.25 | 0.25 | 0.2 | 0.15 | 0.15 |

| Trait | Value | Source or rationale |
| :-- | :-- | :-- |
| crop coefficient (Kc) | see table | No irrigation is applied. |
| soil cover | see table | Stubble and weeds only. |
| n score | 0.0 | PROJECT class value; see the crop's other notes. |
| n credit kg ha | 0 to 0 | PROJECT class value; see the crop's other notes. |
| om score | 0.0 | PROJECT class value; see the crop's other notes. |
| root depth m | 0.0 | PROJECT class value; see the crop's other notes. |
| heat limit c | 60 | PROJECT class value; see the crop's other notes. |
| drought tolerance | 1.0 | PROJECT class value; see the crop's other notes. |
| ky | 0.0 | PROJECT class value; see the crop's other notes. |
| frost free days needed | 0 | PROJECT class value; see the crop's other notes. |
| value score | 0.0 | PROJECT class value; see the crop's other notes. |
| market | none | PROJECT class value; see the crop's other notes. |
| equipment |  | PROJECT class value; see the crop's other notes. |
| establishment risk | 0.0 | PROJECT class value; see the crop's other notes. |
| plantings | 0 | PROJECT class value; see the crop's other notes. |
| salt threshold ds m | not documented | PROJECT class value; see the crop's other notes. |
| salt class | not applicable | PROJECT class value; see the crop's other notes. |

## Rotation strategies

### Rice-wheat every year

`rice_wheat` (can be chosen as the existing rotation) - Transplanted paddy from mid-June, then wheat from November. What most farms here grow.

| Year | What is in the field |
| :-- | :-- |
| 1 | Wheat (Jan-Apr); Rice (Jun-Oct); Wheat (Nov-Dec) |

**May offer**

- Both crops are bought at the minimum support price: the surest income available.
- Machinery, labour, inputs and know-how are all in place.
- High and stable yields under assured irrigation.

**Risks needing local review**

- The highest water use of the options here, in a district whose groundwater is classed over-exploited.
- Three weeks between paddy harvest and wheat sowing push farmers to burn the straw.
- Two cereals every year: weeds such as Phalaris, and soil that hardens under puddling.
- Wheat is exposed to March heat; late sowing after paddy makes it worse.

**Information gaps**

- Your tubewell depth, discharge and how fast the water level is falling.
- Whether you burn, remove or keep the paddy straw.

**Check with a local expert**

- Ask the block agriculture office for the groundwater category of your block.
- Ask PAU or the KVK about short-duration paddy varieties and the Happy Seeder for sowing wheat into straw.

### Rice-wheat with summer moong

`rice_wheat_moong` (can be chosen as the existing rotation) - The same rice and wheat, with a 60-day moong crop in April-June between them.

| Year | What is in the field |
| :-- | :-- |
| 1 | Wheat (Jan-Apr); Summer moong (Apr-Jun); Rice (Jun-Oct); Wheat (Nov-Dec) |

**May offer**

- Adds a legume: some nitrogen for the paddy and a third plant family.
- Covers the soil in the hot, windy weeks of May.
- A little extra income without giving up rice or wheat.

**Risks needing local review**

- Moong needs 3-4 irrigations in the hottest part of the year: this option uses MORE water, not less.
- Rain at maturity in June can ruin the grain.
- Leaves very little time before paddy transplanting.

**Information gaps**

- Whether moong was bought at the support price in your mandi last season.
- Whitefly and yellow mosaic pressure in your village.

**Check with a local expert**

- Check with the KVK which short-duration variety and sowing date fit after your wheat harvest.
- Ask whether procurement of moong is planned this year.

### Maize instead of paddy, with wheat and summer moong

`maize_wheat_moong` (can be chosen as the existing rotation) - Kharif maize replaces paddy; wheat follows; summer moong fills April-June.

| Year | What is in the field |
| :-- | :-- |
| 1 | Wheat (Jan-Apr); Summer moong (Apr-Jun); Maize (Jun-Oct); Wheat (Nov-Dec) |

**May offer**

- Maize transpires less than paddy and needs no puddling or standing water: far less pumping.
- No paddy straw to burn; wheat can be sown on time.
- Soil structure recovers without puddling, and a legume is added.

**Risks needing local review**

- Maize has no assured buyer at the support price: income depends on the mandi price.
- Maize fails if the field floods after heavy monsoon rain, or dries at tasselling.
- Needs a planter, and the grain must be dried before sale.

**Information gaps**

- Maize price and buyers near you (starch mills, poultry feed, ethanol plants).
- Whether your fields drain well enough for maize in a wet July.

**Check with a local expert**

- Ask about the state's crop-diversification incentive for moving out of paddy.
- Talk to a neighbour who grows kharif maize about drainage and fall armyworm.
- Line up a buyer or a dryer before sowing.

### Cotton-wheat

`cotton_wheat` (can be chosen as the existing rotation) - Bt cotton from May to November, then late-sown wheat. The rotation of Punjab's south-west.

| Year | What is in the field |
| :-- | :-- |
| 1 | Wheat (Jan-Apr); Cotton (May-Nov); Wheat (Nov-Dec) |

**May offer**

- A deep-rooted crop from a different family; no puddling.
- Tolerates salty water and soil better than paddy or maize.
- Can earn as much as paddy in a good year.

**Risks needing local review**

- Whitefly and pink bollworm have wiped out crops in recent years: the largest risk of any option here.
- Wheat is sown late after the last picking, which exposes it more to March heat.
- Picking needs a lot of labour.

**Information gaps**

- Pest pressure in your block over the last three seasons.
- Whether heavier soils here suit cotton; it prefers lighter, well-drained land.

**Check with a local expert**

- Ask the agriculture department for this year's recommended Bt hybrids and the pest advisory.
- Check canal or tubewell water quality if salinity is suspected.

### Paddy every other year

`alternate_paddy` - Rice-wheat one year; maize, gram and summer moong the next.

| Year | What is in the field |
| :-- | :-- |
| 1 | Gram (Jan-Mar); Summer moong (Apr-Jun); Rice (Jun-Oct); Wheat (Nov-Dec) |
| 2 | Wheat (Jan-Apr); Maize (Jun-Oct); Gram (Oct-Dec) |

**May offer**

- Halves the paddy area while keeping an assured crop every year.
- Two legumes in two years and four plant groups.
- The field is puddled only every second year.

**Risks needing local review**

- Gram and maize have less certain yields and prices than wheat and paddy.
- More crops to learn and more sowing dates to hit.
- Gram dislikes heavy, wet soil and frost.

**Information gaps**

- Local prices for maize and gram.
- Whether your soil is light enough for gram.

**Check with a local expert**

- Try it on a part of the farm first.
- Ask PAU extension which gram and maize varieties suit your block.

## Always check locally

- Groundwater category of your block and the depth of water in your own tubewell.
- A soil health card test (organic carbon, pH, salinity, nutrients).
- This season's minimum support prices and which crops are actually being procured.
- Sowing windows and varieties in the current PAU Package of Practices.

## References

- **FAO56**: Allen, R.G., Pereira, L.S., Raes, D., Smith, M. (1998). Crop evapotranspiration. FAO Irrigation and Drainage Paper 56 (Tables 11, 12, 17, 22).
- **FAO33**: Doorenbos, J., Kassam, A.H. (1979). Yield response to water. FAO Irrigation and Drainage Paper 33; updated in Steduto et al. (2012), FAO Paper 66.
- **FAO29**: Ayers, R.S., Westcot, D.W. (1985). Water quality for agriculture. FAO Irrigation and Drainage Paper 29, Table 4 (crop salt tolerance).
- **PAU**: Punjab Agricultural University, Ludhiana. Package of Practices for Crops of Punjab: Kharif and Rabi (published every year). Sowing windows, durations and irrigation numbers.
- **HUMPHREYS**: Humphreys, E. et al. (2010). Halting the groundwater decline in north-west India: which crop technologies will be winners? Advances in Agronomy 109: 155-217. (Only lower ET is a real saving; water that percolates from paddy largely returns to the aquifer.)
- **ACT2009**: The Punjab Preservation of Subsoil Water Act, 2009: paddy nursery and transplanting dates are fixed by notification each year (transplanting from mid-June), to move the crop away from the hottest, driest weeks.
- **RODELL**: Rodell, M., Velicogna, I., Famiglietti, J.S. (2009). Satellite-based estimates of groundwater depletion in India. Nature 460: 999-1002. (GRACE: about 4 cm of water a year lost across Rajasthan, Punjab and Haryana, 2002-2008.)
- **CGWB**: Central Ground Water Board, Dynamic Ground Water Resources of India (periodic assessments): most blocks of Sangrur and Barnala districts are classed over-exploited.
- **SARE**: Clark, A. (ed.) (2007). Managing Cover Crops Profitably, 3rd edition. SARE Handbook 9 (legume nitrogen).
- **CA**: Jat, M.L. et al. and CIMMYT-ICAR work on conservation agriculture in the rice-wheat and maize-wheat systems of north-west India (zero tillage, residue retention with the Happy Seeder, summer mungbean).
- **PROJECT**: Class score assigned by this project from the general agronomy cited alongside it; not locally calibrated.

---
