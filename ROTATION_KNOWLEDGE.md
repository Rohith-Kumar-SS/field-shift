# ROTATION_KNOWLEDGE

The rotation knowledge base behind the Rotation Scenario Explorer. **Generated from `knowledge/rotation_knowledge.yaml` by `python -m engine.knowledge_doc`; edit the YAML, not this file.**

## How to read it

- Every value is either taken from a cited reference or is a class score assigned by this project, with the reasoning given. Entries tagged PROJECT are judgments, not measurements.
- Class scores run from 0 (none / worst) to 1 (most / best). They are **not calibrated to Diamond Valley** and each is a prompt for local review.
- Kc is the monthly crop coefficient on a grass reference (FAO-56): crop water demand = Kc x reference ET.
- Cover is the share of the soil surface protected by canopy, stubble or residue.
- Written for irrigated forage systems of the Great Basin (cold desert, about 1,800 m). Do not reuse the crop calendars elsewhere without local review.

## How each priority is scored

| Priority | Formula | Details |
| :-- | :-- | :-- |
| Save water | `score = 2 x (1 - irrigation need / full-alfalfa irrigation need)`, limited to 0-1 | Irrigation need = sum over months of `Kc x reference ET x field factor` minus effective rain (USDA-SCS method), averaged over the rotation. Reference ET is FAO-56 Penman-Monteith from NASA POWER daily weather, bias-corrected to gridMET. The field factor is the median ratio of OpenET satellite ET to the textbook figure in that field's own alfalfa years (limited to 0.6-1.15; 1.0 if there is no OpenET record). 0 = as thirsty as full-season alfalfa on that field, 1 = half the water or less. |
| Keep soil covered | `score = sum over months of (risk weight x share of soil covered)` | Risk weights sum to 1 over the year. They combine windy days (daily mean wind >= 4.5 m/s at 2 m, NASA POWER) scaled by the soil's wind-erodibility index (SSURGO), and heavy-rain days (>= 10 mm) scaled by field tilt (SRTM) and the K factor (SSURGO). Cover comes from each crop's monthly cover table; months nobody occupies keep half of the previous month's cover as residue, never below 0.1. |
| Nitrogen from legumes | legume year = its `n_score`; first year after alfalfa 0.6; second 0.3; a legume cover crop adds up to 0.5 | Averaged over the rotation. |
| Build organic matter | `sum of om_score x share of the crop's season - 0.08 per sowing` | Averaged over the rotation. Class scores only: organic matter cannot be seen from space. |
| Break pest cycles | `0.45 x break + 0.35 x diversity + 0.20 x stand age` | Break: 0 if alfalfa follows alfalfa, 0.6 for a one-year gap, 1.0 for two or more. Diversity: (number of plant groups - 1) / 3. Stand age: 1.0 up to 5 years, falling to 0 at 10. |
| Forage and income | `sum of value_score x share of season x market factor`, reduced by water shortage | Market factor: established 1.0; niche 0.5 / 0.8 / 1.0 and uncertain 0.2 / 0.5 / 0.8 for the three market settings. Where a year needs more irrigation than the farmer's stated supply, relative yield is `1 - Ky x (1 - ETa / ETc)` (FAO-33). No prices are used. |
| Drought and heat resilience | `0.5 x drought_tolerance + 0.5 x (1 - days above the crop's heat limit in its season / 45)` | Weighted by each crop's share of the year, averaged over the rotation. |
| Easy to carry out | `0.45 x season fit + 0.30 x equipment available + 0.25 x (1 - establishment risk)`, minus 0.05 per extra sowing in a year | Season fit = share of the last 30 years whose frost-free season was at least as long as the crop needs. |

Overall score = sum of (weight x score), with the farmer's slider values normalised to sum to 1. The code is `engine/scoring.py`; the tests are `tests/test_scoring.py`.

## Crop summary

| Crop | Group | Root depth (m) | Ky | Heat limit (°C) | Frost-free days needed | N | Organic matter | Drought tolerance | Value | Market | Equipment | Salt threshold (dS/m) |
| :-- | :-- | :-- | :-- | :-- | :-- | :-- | :-- | :-- | :-- | :-- | :-- | :-- |
| Alfalfa hay (established stand) | legume | 2.5 | 1.1 | 32 | - | 1.0 | 0.75 | 0.6 | 1.0 | established | hay | 2.0 |
| Alfalfa, establishment year | legume | 1.2 | 1.1 | 32 | - | 0.8 | 0.5 | 0.35 | 0.55 | established | hay, drill | 2.0 |
| Winter cereal for hay (triticale, winter wheat or rye) | cool-season grass | 1.5 | 1.05 | 30 | - | 0.0 | 0.5 | 0.7 | 0.45 | established | hay, drill | 6.0 |
| Teff grass hay (warm-season annual) | warm-season grass | 0.8 | 0.9 | 38 | 75 | 0.0 | 0.4 | 0.75 | 0.5 | niche | hay, drill | - |
| Sorghum-sudangrass hay (warm-season annual) | warm-season grass | 1.5 | 0.9 | 38 | 100 | 0.0 | 0.55 | 0.85 | 0.45 | established | hay, drill | 6.8 |
| Spring small-grain hay (oats or barley) | cool-season grass | 1.2 | 1.15 | 30 | - | 0.0 | 0.4 | 0.55 | 0.4 | established | hay, drill | 8.0 |
| Spring small grain for grain (barley or spring wheat) | cool-season grass | 1.2 | 1.15 | 30 | - | 0.0 | 0.55 | 0.5 | 0.4 | established | drill, combine | 8.0 |
| Safflower (deep-rooted oilseed) | broadleaf | 2.0 | 0.8 | 36 | 110 | 0.0 | 0.35 | 0.85 | 0.3 | uncertain | drill, combine | - |
| Winter cover crop mix (cereal + winter pea or vetch) | cover mix | 1.0 | 1.0 | 30 | - | 0.5 | 0.75 | 0.6 | 0.05 | none (soil benefit; some grazing value) | drill | - |
| Irrigated grass hay or pasture | cool-season grass | 1.0 | 1.0 | 30 | - | 0.0 | 0.85 | 0.5 | 0.55 | established | hay | - |
| Idle or fallow (not irrigated) | none | 0.0 | 0.0 | 60 | - | 0.0 | 0.0 | 1.0 | 0.0 | none | - | - |
| Irrigated crop, type uncertain | unknown | 1.0 | 1.1 | 32 | - | 0.0 | 0.45 | 0.5 | 0.5 | established | - | - |

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

Family: Fabaceae. Group: legume. Perennial. USDA crop-map codes: none.

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

Family: Poaceae. Group: warm-season grass. Annual. USDA crop-map codes: none.

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

The existing rotation is always read from the field's own crop history (USDA crop map checked against Landsat greenness) and compared with these four.

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
