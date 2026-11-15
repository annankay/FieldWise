# FieldWise — NASA Earth data → healthier crop rotations

FieldWise is a decision-support web app for farmers and extension officers. A farmer finds their field on the map, says what they grow and what matters to them, and gets:

1. **A weather story for their exact field** from 35 years of NASA data: rain, very hot days, dry months, changes over time, when the land is bare, floods and droughts nearby, underground water trend.
2. **Their own crops vs. the weather**: each crop's growth stages lined up against the risky months.
3. **3–4 rotation options next to the current one**, each with what's good, what to watch out for, what to check with the extension officer, a confidence level and a score range from bad years to good years.
4. **"Make your own plan"**: change any option and see the score update live.
5. **A satellite time machine**: NASA Worldview imagery (greenness, soil moisture, ground heat, rain, true colour) with a date slider and a two-year comparison, plus problem spots on the field (erosion, dry spots, frost pockets, Landsat greenness).
6. **What if?**: drier, hotter or stormier futures re-run on 35 years of weather.
7. **Learn**: plain-language glossary, every dataset and its status, how sure the tool is, and your own rain gauge to correct NASA rainfall.

**It works for any field in Africa** (and beyond): the climate type, the crops that fit and a typical starting rotation are worked out from each field's own NASA data, not from a fixed list of towns. 19 example fields cover West, Central, East, Southern and North Africa.

It works on phones and laptops, in **English and French** (Twi and Hausa drafts), with a **Farmer view** (simple) and an **Expert view** (all the science). It installs like an app and opens offline with the last results viewed.

> FieldWise supports decisions. It never replaces the farmer's judgment or local agricultural experts.

---

## 1. Run it on your laptop (VS Code)

```bash
python -m venv .venv
# Windows: .venv\Scripts\activate     macOS/Linux: source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env                 # Windows: copy .env.example .env  — then fill it in (section 2)
python run.py                        # opens http://127.0.0.1:8000
```

In VS Code you can press **F5** instead and pick **"▶ Run FieldWise (web app)"**.

**Production uses real NASA data only.** The first time, the app has no fields: search for a place, drop a pin and press **"Get NASA data for this field"**. Weather and soil arrive in about a minute and the farmer can start planning. Satellite layers keep arriving in the background, and the page updates by itself.

For development without internet, run **"▶ Run FieldWise with DEVELOPMENT test data"** (sets `FIELDWISE_DEMO=1`). That data is synthetic, clearly marked, and never shown in production.

## 2. Connect the NASA sources

| Source | Needs | What it adds |
|---|---|---|
| NASA POWER, SoilGrids, GIBS/Worldview, EONET | nothing | Weather, soil, time-machine imagery, natural events |
| Google Earth Engine | `GEE_PROJECT` + `earthengine authenticate` (or a service account on a server) | GPM, SMAP, MODIS NDVI/ET, GRACE, SRTM, **Landsat 30 m**, **GEDI biomass** |
| NASA Earthdata (AppEEARS) | `EARTHDATA_USERNAME` / `EARTHDATA_PASSWORD` | **ECOSTRESS** 70 m plant water stress (queued at NASA; collected automatically later) |
| Anthropic (optional) | `ANTHROPIC_API_KEY` | "Explain simply" and AI translation |

Then check everything from your laptop:

```bash
earthengine authenticate
python scripts/check_setup.py        # every source should say [ OK ]
python scripts/build_cache.py --all  # real data for the 19 example fields across Africa (about 1 hour)
python scripts/build_cache.py --refresh   # later: collect finished ECOSTRESS requests
```

Layer names on GIBS and AppEEARS are discovered at run time, so a NASA version update does not break the app. If a source fails, FieldWise keeps working without it, shows the gap, and lowers the confidence level.

## 3. Africa-wide coverage

- **Any pin works.** POWER, SoilGrids, SMAP, MODIS, GPM, GRACE, Landsat, SRTM, GEDI and ECOSTRESS all cover the whole continent.
- **Climate type from the data:** humid tropics, sub-humid savanna, semi-arid Sahel, arid, highland and plateau, Mediterranean winter rain, or cold winters, plus one or two rainy seasons (`backend/engine/farming_systems.py`).
- **Crops are offered wherever this field's climate suits them.** There is no fixed "tropical" or "temperate" list, so highland wheat, teff and faba bean appear in Ethiopia, and chickpea and lentil in Morocco.
- **41 crops**, including teff, finger millet, lowland rice, chickpea, lentil, faba bean, potato, onion, hot pepper, cotton, cocoyam, desmodium (push-pull) and berseem.
- **Intercropping**, the main African practice: maize with beans, cowpea, pigeon pea, groundnut or desmodium; millet or sorghum with cowpea; cassava with legumes. A farmer can record intercrops, and the engine suggests them.
- **A typical starting rotation** is generated for any new pin: the zone's usual staple, sown at the start of the main rains, plus a second-season crop where there are two rainy seasons. The farmer edits it.
- **Highland temperature fix:** POWER temperatures are shifted by the lapse rate to the field's own SRTM height.
- **Deserts and irrigated oases:** when rain alone can't grow a crop, the app says so, defaults to irrigation, and opens every warm month for sowing.
- **Example fields:** Ejura and Tamale (Ghana), Kano (Nigeria), Ségou (Mali), Kaolack (Senegal), Bobo-Dioulasso (Burkina Faso), Bafoussam (Cameroon), Bahir Dar (Ethiopia), Nakuru (Kenya), Mbale (Uganda), Musanze (Rwanda), Morogoro (Tanzania), Lilongwe (Malawi), Chipata (Zambia), Nampula (Mozambique), Bulawayo (Zimbabwe), Bethlehem (South Africa), Meknès (Morocco), Fayoum (Egypt). Add more in `backend/data/sites.json`.
- **Not covered yet:** tree and plantation crops (cocoa, coffee, oil palm, cashew, banana and plantain), which are not rotated in the same way. Arabic, Portuguese, Swahili and Amharic interfaces are not done yet.

## 4. What the farmer can tell FieldWise

- **Crops and sowing months** over two years (tap a crop, tap a month; green bars show good months for this field), including **what is grown together** (intercrops)
- **Top 3 goals**: save water, feed the soil, build rich soil, stop erosion, help rain soak in, fewer pests, more income, animal feed, safety from heat and drought (sliders in Expert view)
- **Water** they can give in dry months: rain only, a little, some, full irrigation
- **Tools**: hand, animals, tractor (crops that need machines are excluded for hand and animal farms)
- **Main food crop** kept in its usual season
- **Which crops they can sell nearby**: good price, low price, no buyer, not sure
- **Their own soil test** (pH, organic carbon, clay, sand), which replaces the satellite soil map
- **Crops they won't grow**

Every suggestion must produce food, feed or income every year. Cover-crop-only years are never suggested.

## 5. How it decides

```
NASA POWER daily (35 y) ─► FAO-56 Penman-Monteith ET₀ ─► monthly features, climatology, trends (Mann-Kendall)
GPM · SMAP · MODIS · GRACE · Landsat · ECOSTRESS ─► one monthly field-centred series (resolution-tagged)
SRTM ─► slope, erosion / dry-spot / frost-pocket zones          GEDI ─► biomass the land can hold
crop table (41 crops) ─► fit per sowing month = temperature × frost × heat at flowering × water × waterlogging × pH
beam search (incl. intercrops) ─► thousands of two-year rotations ─► 9 transparent scores (0–100) ─► weighted by the farmer's goals
k-means "kinds of year" ─► every option re-scored per kind of year ─► score range + robustness
explanations from the numbers: why · evidence (dataset named) · benefits · risks · gaps · ask your officer · confidence
```

**AI and statistics**, each compared against a simpler alternative:
- **Season detection:** a Gaussian mixture model on Landsat (or MODIS) greenness learns what "bare", "growing" and "full crop" look like for this field, compared with a fixed NDVI threshold.
- **Crop-stress model:** ridge regression, random forest, gradient boosting and a physics-guided monotonic booster, tested on later years they never saw. The monotonic model is used for what-ifs, so more rain can never "cause" stress.
- **Kinds of year:** k-means on yearly rain, onset, dry spells and heat.
- **Trends:** Mann-Kendall test with Sen's slope.
- **Ground fusion:** monthly bias correction of NASA rainfall with the farmer's own gauge.

## 6. Project layout

```
run.py                      start on a laptop
Dockerfile                  production image (see DEPLOY.md)
backend/
  api.py                    FastAPI: validated JSON API, rate limits, security headers, serves the app
  service.py                loads a field once; profile / strategies / score / what-if
  config.py  i18n.py        settings (.env); backend sentences in English + French
  fetchers/                 power · soilgrids · gee (incl. Landsat, GEDI) · appeears (ECOSTRESS) · gibs · eonet · builder · cache
  pipeline/                 et0 · features · seasons · trends · harmonize · fieldgrid · fusion
  engine/                   crops (fit) · scoring (9 criteria, intercrops) · search · strategies · farming_systems (zones, default rotation) · vulnerability · explain · llm
  ml/                       phenology (Gaussian mixture) · stress (model comparison) · yeartypes (k-means)
  data/                     crops.json (with local names) · sites.json (reference fields) · cache/ (downloaded data)
frontend/                   index.html · app.js · i18n.js · styles.css · sw.js (offline) · manifest · vendor/
scripts/                    check_setup.py · build_cache.py
tests/                      33 tests (science, NASA parsers, API, validation, rate limit, security)
```

## 7. Before launch

- [ ] `python scripts/check_setup.py` all green on the server's keys
- [ ] Real data cached for the 19 example fields
- [ ] **Native speakers review the Twi and Hausa** text (`frontend/i18n.js`, crop names in `backend/data/crops.json`)
- [ ] An agronomist reviews `crops.json` (traits, local varieties) and `sites.json` (default rotations, market values)
- [ ] Test with 5+ farmers on their own phones; watch where they hesitate
- [ ] Choose map tile providers with a key for heavy use (OpenStreetMap and Esri have usage limits)
- [ ] Deploy (DEPLOY.md), add HTTPS, monitor `/api/health`

## 8. Honest limits

POWER weather is a ~50 km average, SMAP 9 km, GRACE ~300 km. Crop traits and market values are general estimates. Prices, local pests, labour, land rights and local varieties are not modelled. Every option lists its own information gaps and what to check locally. Field data is stored on the server under unguessable IDs and is not listed publicly. A farmer's field list lives only on their own device.
