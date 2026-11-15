/* FieldWise web app — plain JavaScript, Leaflet and Chart.js. No build step. */
"use strict";

/* =============================================================== state & helpers */
const CRIT = ["water", "nitrogen", "organic_matter", "erosion", "infiltration", "pest_break", "income", "forage", "climate_fit"];
const GOAL_ICON = { water: "💧", nitrogen: "🫘", organic_matter: "🪱", erosion: "⛰️", infiltration: "🌱", pest_break: "🐛", income: "💰", forage: "🐄", climate_fit: "☀️" };
const GROUP_COLORS = { cereal: "#e2b354", legume: "#6db57a", root: "#c08a68", cover: "#53b0a1", forage: "#9bc25a", oilseed: "#e59a52", vegetable: "#d46a5f", cash: "#b7a3d6" };
const RISK_COLORS = ["#e3f1e5", "#f6e7b8", "#f0b46b", "#d9603b"];
const MARKET_CYCLE = ["unsure", "good", "low", "no"];
const MARKET_ICON = { unsure: "❔", good: "👍", low: "👌", no: "✖️" };

const S = {
  lang: "en", view: "farmer", crops: [], cropMap: {}, health: {}, field: null, profile: null, result: null,
  farm: null, charts: {}, maps: {}, tab: "farm", wstep: 1, pickCrop: null, pickYear: "1",
  imagery: null, planner: [], plannerTimer: null, pollTimer: null, timeIdx: 0, playTimer: null, gibsLayers: {},
};
const $ = (s, root = document) => root.querySelector(s);
const $$ = (s, root = document) => Array.from(root.querySelectorAll(s));
const esc = (v) => String(v ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const fmt = (v, d = 0) => (v === null || v === undefined || Number.isNaN(Number(v)) ? "–" : Number(v).toFixed(d));
const store = {
  get(k, def) { try { const v = localStorage.getItem(k); return v === null ? def : JSON.parse(v); } catch (_) { return def; } },
  set(k, v) { try { localStorage.setItem(k, JSON.stringify(v)); } catch (_) { /* private mode */ } },
};
function t(key, vars) {
  const d = (window.I18N[S.lang] || {})[key] ?? window.I18N.en[key] ?? key;
  return vars ? String(d).replace(/\{(\w+)\}/g, (_, k) => (vars[k] ?? "")) : d;
}
const months = () => window.MONTHS[S.lang] || window.MONTHS.en;
const cropName = (id) => { const c = S.cropMap[id]; return c ? ((c.names || {})[S.lang] || c.name.replace(/ \(.*\)/, "")) : id; };
const cropIcon = (id) => (S.cropMap[id] || {}).icon || "🌱";
const cropColor = (id) => GROUP_COLORS[(S.cropMap[id] || {}).group] || "#bbb";

async function api(path, opts = {}) {
  const res = await fetch(path, { headers: { "Content-Type": "application/json" }, ...opts });
  if (!res.ok) {
    let msg = res.statusText;
    try { const j = await res.json(); msg = typeof j.detail === "string" ? j.detail : t("err_input"); } catch (_) { /* */ }
    const e = new Error(msg); e.status = res.status; throw e;
  }
  return res.json();
}
function busy(on, text) { $("#loading").hidden = !on; $("#loadingText").textContent = text || t("working"); }
let toastTimer;
function toast(msg) { const el = $("#toast"); el.textContent = msg; el.hidden = false; clearTimeout(toastTimer); toastTimer = setTimeout(() => (el.hidden = true), 4000); }
function modal(html) { $("#modalBody").innerHTML = html; const d = $("#modal"); if (d.open) return; if (d.showModal) d.showModal(); else d.setAttribute("open", ""); }
function chart(id, cfg) {
  if (S.charts[id]) S.charts[id].destroy();
  const el = document.getElementById(id); if (!el) return null;
  cfg.options = Object.assign({ responsive: true, maintainAspectRatio: false, animation: { duration: 250 } }, cfg.options || {});
  S.charts[id] = new Chart(el, cfg); return S.charts[id];
}
Chart.defaults.font.family = "'Source Sans 3', system-ui, sans-serif";
Chart.defaults.color = "#6d655c"; Chart.defaults.borderColor = "#ece5dc";

/* =============================================================== language & view */
function applyLang() {
  document.documentElement.lang = S.lang;
  $$("[data-i18n]").forEach((el) => (el.textContent = t(el.dataset.i18n)));
  $$("[data-i18n-ph]").forEach((el) => (el.placeholder = t(el.dataset.i18nPh)));
  $("#langSelect").value = S.lang;
}
$("#langSelect").onchange = async (e) => {
  S.lang = e.target.value; store.set("fw_lang", S.lang); applyLang();
  if (["tw", "ha"].includes(S.lang)) toast(t("draft_lang"));
  renderStartLists(); renderLearn();
  if (S.field) { busy(true); try { await loadProfile(); renderFarm(); renderLearn(); if (S.result) await analyze(false); } finally { busy(false); } }
};
$$("[data-view]").forEach((b) => b.addEventListener("click", () => setView(b.dataset.view)));
function setView(v) {
  S.view = v; store.set("fw_view", v);
  document.body.classList.toggle("expert-view", v === "expert"); document.body.classList.toggle("farmer-view", v !== "expert");
  $$("[data-view]").forEach((b) => b.classList.toggle("on", b.dataset.view === v));
  setTimeout(() => Object.values(S.charts).forEach((c) => c.resize && c.resize()), 30);
}

/* =============================================================== routing */
const SCREENS = { start: "s-start", loading: "s-loading", farm: "s-farm", story: "s-story", options: "s-options", map: "s-map", whatif: "s-whatif", learn: "s-learn" };
function go(tab, push = true) {
  if (!SCREENS[tab]) tab = "farm";
  if (!["start", "loading"].includes(tab) && !S.field) tab = "start";
  if (tab === "options" && !S.result && S.field) { analyze(true); return; }
  S.tab = tab;
  $$(".screen").forEach((s) => s.classList.toggle("on", s.id === SCREENS[tab]));
  $$("#tabs button").forEach((b) => b.classList.toggle("on", b.dataset.tab === tab));
  const inField = !!S.field && !["start", "loading"].includes(tab);
  $("#tabs").hidden = !inField; document.body.classList.toggle("has-tabs", inField);
  $("#topField").hidden = !inField;
  if (!inField) $("#banner").hidden = true; else renderBanner();
  if (push) history.pushState({ tab }, "", inField ? `#/f/${S.field.id}/${tab}` : "#/");
  if (tab === "map") setTimeout(initMaps, 30);
  if (tab === "start") setTimeout(() => S.maps.start && S.maps.start.invalidateSize(), 30);
  if (tab === "story") setTimeout(() => Object.values(S.charts).forEach((c) => c.resize && c.resize()), 30);
  window.scrollTo({ top: 0 });
}
$$("#tabs button").forEach((b) => b.addEventListener("click", () => go(b.dataset.tab)));
$("#homeBtn").onclick = () => { stopPolling(); go("start"); };
window.addEventListener("popstate", () => route());
async function route() {
  const m = location.hash.match(/^#\/f\/([a-z0-9-]+)\/?(\w+)?/);
  if (m) {
    if (!S.field || S.field.id !== m[1]) { const ok = await openField(m[1], m[2] || "farm", false); if (!ok) go("start", false); }
    else go(m[2] || "farm", false);
  } else go("start", false);
}

/* =============================================================== start screen */
function savedFields() { return store.get("fw_fields", []); }
function saveField(f) { const list = savedFields().filter((x) => x.id !== f.id); list.unshift({ ...f, opened: Date.now() }); store.set("fw_fields", list.slice(0, 20)); }
function renderStartLists() {
  const saved = savedFields();
  $("#savedBox").hidden = !saved.length;
  $("#savedList").innerHTML = saved.map((f) => `<li><button class="open" data-id="${esc(f.id)}"><b>📍 ${esc(f.name)}</b><span class="muted small">${fmt(f.lat, 3)}, ${fmt(f.lon, 3)}</span></button>
    <button class="x" data-del="${esc(f.id)}" aria-label="${esc(t("remove"))}">×</button></li>`).join("");
  const refs = S.refs || [];
  $("#refBox").hidden = !refs.length;
  $("#refList").innerHTML = refs.map((f) => `<li><button class="open" data-id="${esc(f.id)}"><b>${esc(f.name)}</b><span class="muted small">${esc(f.farming_system || "")}${f.data_mode === "demo" ? " · DEV DATA" : ""}</span></button></li>`).join("");
  $$("#savedList .open, #refList .open").forEach((b) => (b.onclick = () => openField(b.dataset.id, "farm")));
  $$("#savedList [data-del]").forEach((b) => (b.onclick = () => { store.set("fw_fields", savedFields().filter((x) => x.id !== b.dataset.del)); renderStartLists(); }));
}
function baseLayers() {
  const sat = L.tileLayer("https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}", { maxZoom: 19, attribution: "Imagery © Esri" });
  const osm = L.tileLayer("https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png", { maxZoom: 19, attribution: "© OpenStreetMap" });
  return { sat, osm };
}
function initStartMap() {
  if (S.maps.start) return;
  const m = L.map("startMap", { zoomControl: true }).setView([3, 18], 3);   // Africa
  const { sat, osm } = baseLayers(); sat.addTo(m);
  L.control.layers({ Satellite: sat, Map: osm }).addTo(m);
  m.on("click", (e) => setPin(e.latlng.lat, e.latlng.lng, false));
  S.maps.start = m;
}
function setPin(lat, lon, zoom = true) {
  const m = S.maps.start;
  if (S.pin) S.pin.remove();
  S.pin = L.marker([lat, lon], { draggable: true }).addTo(m);
  S.pin.on("dragend", () => { const p = S.pin.getLatLng(); S.pinAt = { lat: p.lat, lon: p.lng }; showPin(); });
  S.pinAt = { lat, lon }; if (zoom) m.setView([lat, lon], 15); showPin();
}
function showPin() { $("#pinBox").hidden = false; $("#pinCoords").textContent = `${S.pinAt.lat.toFixed(5)}, ${S.pinAt.lon.toFixed(5)} · ${t("drag_pin")}`; }
$("#searchForm").onsubmit = async (e) => {
  e.preventDefault();
  const q = $("#searchInput").value.trim(); if (!q) return;
  const ul = $("#searchResults"); ul.innerHTML = `<li class="muted">${esc(t("searching"))}</li>`;
  try {
    const r = await fetch(`https://nominatim.openstreetmap.org/search?format=json&limit=6&viewbox=-26,38,60,-36&bounded=0&accept-language=${S.lang}&q=${encodeURIComponent(q)}`);
    const items = await r.json();
    ul.innerHTML = items.length ? items.map((it, i) => `<li><button data-i="${i}">📍 ${esc(it.display_name)}</button></li>`).join("") : `<li class="muted">${esc(t("no_results"))}</li>`;
    $$("button", ul).forEach((b) => (b.onclick = () => { const it = items[b.dataset.i]; setPin(+it.lat, +it.lon); ul.innerHTML = ""; toast(t("tap_exact")); }));
  } catch (_) { ul.innerHTML = `<li class="muted">${esc(t("search_offline"))}</li>`; }
};
$("#gpsBtn").onclick = () => {
  if (!navigator.geolocation) return toast(t("no_gps"));
  busy(true, t("finding_you"));
  navigator.geolocation.getCurrentPosition((p) => { busy(false); setPin(p.coords.latitude, p.coords.longitude); },
    () => { busy(false); toast(t("no_gps")); }, { enableHighAccuracy: true, timeout: 15000 });
};
$("#getDataBtn").onclick = createField;

async function createField() {
  if (!S.pinAt) return;
  const name = $("#fieldName").value.trim() || t("my_field");
  $("#getDataBtn").disabled = true;
  try {
    const { job_id } = await api("/api/fields", { method: "POST", body: JSON.stringify({ lat: S.pinAt.lat, lon: S.pinAt.lon, name }) });
    go("loading");
    $$("#progressSteps li").forEach((li) => li.classList.remove("active", "done"));
    $("#progressErr").hidden = true;
    const order = ["weather", "soil", "ready", "satellite"];
    for (;;) {
      await new Promise((r) => setTimeout(r, 2000));
      const j = await api(`/api/jobs/${job_id}`);
      const idx = order.indexOf(j.stage === "done" ? "satellite" : j.stage);
      $$("#progressSteps li").forEach((li, i) => { li.classList.toggle("done", i < idx || (j.site_id && i <= 2)); li.classList.toggle("active", i === idx); });
      $("#satCount").textContent = j.total ? `(${j.done}/${j.total})` : "";
      $("#progressMsg").textContent = j.message || "";
      if (j.site_id) { saveField({ id: j.site_id, name, lat: S.pinAt.lat, lon: S.pinAt.lon }); await openField(j.site_id, "farm"); break; }
      if (j.status === "error") { $("#progressErr").hidden = false; $("#progressErr").textContent = j.error || t("err_fetch"); break; }
    }
  } catch (err) { toast(err.message); go("start"); } finally { $("#getDataBtn").disabled = false; }
}

/* =============================================================== open a field */
async function openField(id, tab = "farm", push = true) {
  busy(true, t("reading_field"));
  const prev = S.field;
  try {
    S.field = { id }; S.result = null;
    await loadProfile();
    const p = S.profile.site;
    S.field = { id, name: p.name, lat: p.lat, lon: p.lon };
    if (!p.reference) saveField(S.field);
    $("#topFieldName").textContent = p.name;
    S.farm = loadFarm(); S.pickCrop = null; S.wstep = 1;
    renderFarm(); renderLearn(); renderCropRisk();
    resetMaps();
    go(tab === "options" ? "farm" : tab, push);
    watchSatellite();
    if (tab === "options") await analyze(true);
    return true;
  } catch (err) {
    S.field = prev; toast(err.status === 404 ? t("field_missing") : err.message); return false;
  } finally { busy(false); }
}
async function loadProfile() {
  S.profile = await api(`/api/sites/${S.field.id}/profile?lang=${S.lang}`);
  renderBanner(); renderStory();
}
function renderBanner() {
  const p = S.profile, b = $("#banner");
  if (!p) { b.hidden = true; return; }
  if (p.site.data_mode === "demo") { b.hidden = false; b.className = "banner warn"; b.textContent = t("banner_demo"); return; }
  if (p.site.satellite_status === "loading") { b.hidden = false; b.className = "banner"; b.textContent = t("banner_loading"); return; }
  if (["queued", "processing", "pending"].includes(p.ecostress_status)) { b.hidden = false; b.className = "banner"; b.textContent = t("banner_eco"); return; }
  b.hidden = true;
}
function stopPolling() { clearInterval(S.pollTimer); S.pollTimer = null; }
function watchSatellite() {
  stopPolling();
  if (S.profile.site.satellite_status !== "loading") return;
  S.pollTimer = setInterval(async () => {
    try {
      const st = await api(`/api/sites/${S.field.id}`);
      if (st.updated !== S.profile.site.updated) {
        await loadProfile(); renderLearn(); resetMaps(); if (S.tab === "map") initMaps();
        toast(t("new_layers"));
        if (S.result) await analyze(false);
        if (st.satellite_status !== "loading") stopPolling();
      }
    } catch (_) { /* try again next tick */ }
  }, 15000);
}

/* =============================================================== farm setup (wizard) */
function defaultFarm() {
  const p = S.profile;
  const tropical = !(p.zone && p.zone.key === "temperate");
  return {
    current: (p.default_rotation || []).map((r) => ({ crop: r.crop, year: r.year, sow_month: r.sow_month, ...(r.duration_m ? { duration_m: r.duration_m } : {}) })),
    goals: ["income", "nitrogen", "water"], priorities: null, water: p.no_rainfed_season ? "full" : "none", tool: tropical ? "hand" : "tractor",
    keepStaple: true, staple: p.staple || null, market: {}, soilTest: {}, avoid: [],
  };
}
function loadFarm() { return Object.assign(defaultFarm(), store.get(`fw_farm_${S.field.id}`, {})); }
function saveFarm() { store.set(`fw_farm_${S.field.id}`, S.farm); }
function priorities() {
  if (S.farm.priorities) return S.farm.priorities;
  const p = {}; CRIT.forEach((k) => (p[k] = S.farm.goals.includes(k) ? 5 : 1.5));
  p.climate_fit = Math.max(p.climate_fit, 3);
  return p;
}
function fitByMonth(cid) { const r = (S.profile.crop_explorer || []).find((x) => x.crop === cid); return r ? r.by_month : null; }
function suitedCrops() {
  const fits = Object.fromEntries((S.profile.crop_explorer || []).map((r) => [r.crop, r.fit]));
  // crops are offered when this field's own climate gives them a fair chance (or the farmer grows them)
  return S.crops.filter((c) => (fits[c.id] || 0) >= 0.25 || (S.farm && S.farm.current.some((p) => p.crop === c.id)))
    .map((c) => ({ ...c, fit: fits[c.id] || 0, mine: !!(S.farm && S.farm.current.some((p) => p.crop === c.id)) }))
    .sort((a, b) => (b.mine - a.mine) || (b.fit - a.fit));
}

function renderFarm() {
  if (!S.farm) return;
  $("#farmTitle").textContent = t("farm_title_named", { name: S.profile.site.name });
  $("#noRainBox").hidden = !S.profile.no_rainfed_season;
  const list = suitedCrops();
  $("#cropGrid").innerHTML = list.map((c) => {
    const f = c.fit; const col = f >= 0.6 ? "#4c9a5b" : f >= 0.35 ? "#e0a32e" : "#d9603b";
    return `<button class="crop-tile ${S.pickCrop === c.id ? "sel" : ""}" data-crop="${c.id}"><span class="em">${c.icon || "🌱"}</span><b>${esc(cropName(c.id))}</b>
      <small><i class="fitdot" style="background:${col}"></i>${esc(t(f >= 0.6 ? "fit_good" : f >= 0.35 ? "fit_ok" : "fit_poor"))}</small></button>`;
  }).join("");
  $$("#cropGrid .crop-tile").forEach((b) => (b.onclick = () => { S.pickCrop = b.dataset.crop; renderFarm(); $("#monthPick").scrollIntoView({ behavior: "smooth", block: "nearest" }); }));
  $("#monthPick").hidden = !S.pickCrop;
  if (S.pickCrop) {
    $("#pickCropName").textContent = `${cropIcon(S.pickCrop)} ${cropName(S.pickCrop)}`;
    const fm = fitByMonth(S.pickCrop) || [];
    $("#monthButtons").innerHTML = months().map((m, i) => {
      const f = fm[i] ?? null; const col = f === null ? "transparent" : f >= 0.6 ? "#4c9a5b" : f >= 0.35 ? "#e0a32e" : "#d9603b";
      return `<button data-m="${i + 1}" title="${f === null ? "" : Math.round(f * 100) + "/100"}">${esc(m)}<i class="bar" style="background:${col}"></i></button>`;
    }).join("");
    const comps = ((S.cropMap[S.pickCrop] || {}).companions || []).filter((c) => S.cropMap[c]);
    $("#withRow").hidden = !comps.length;
    $("#withSelect").innerHTML = `<option value="">${esc(t("alone"))}</option>` + comps.map((c) => `<option value="${c}">${cropIcon(c)} ${esc(cropName(c))}</option>`).join("");
    if (!comps.includes(S.pickWith)) S.pickWith = "";
    $("#withSelect").value = S.pickWith || "";
    $("#withSelect").onchange = (e) => { S.pickWith = e.target.value; };
    $$("#monthButtons button").forEach((b) => (b.onclick = () => addPlanting(S.pickCrop, +b.dataset.m, S.pickWith || null)));
    const best = fm.length ? fm.indexOf(Math.max(...fm)) : -1;
    $("#fitHint").textContent = best >= 0 ? t("fit_hint", { month: months()[best] }) : "";
  }
  $$(".year-toggle button").forEach((b) => { b.classList.toggle("on", b.dataset.y === S.pickYear); b.onclick = () => { S.pickYear = b.dataset.y; renderFarm(); }; });
  renderPlanList(S.farm.current, "#plantedList", "#currentStrip", (i) => { S.farm.current.splice(i, 1); saveFarm(); renderFarm(); });

  $("#goalGrid").innerHTML = CRIT.map((k) => `<button class="goal ${S.farm.goals.includes(k) ? "sel" : ""}" data-g="${k}" aria-pressed="${S.farm.goals.includes(k)}"><span class="em">${GOAL_ICON[k]}</span><b>${esc(t("g_" + k))}</b><small>${esc(t("gd_" + k))}</small></button>`).join("");
  $$("#goalGrid .goal").forEach((b) => (b.onclick = () => {
    const g = S.farm.goals; const k = b.dataset.g;
    if (g.includes(k)) g.splice(g.indexOf(k), 1); else { if (g.length >= 3) g.shift(); g.push(k); }
    S.farm.priorities = null; saveFarm(); renderFarm(); rerankLocal();
  }));
  const pr = priorities();
  $("#prioSliders").innerHTML = `<h4>${esc(t("fine_tune"))}</h4>` + CRIT.map((k) => `<div class="slider-row"><label>${GOAL_ICON[k]} ${esc(t("g_" + k))}</label><input type="range" min="0" max="5" step="0.5" value="${pr[k]}" data-k="${k}" aria-label="${esc(t("g_" + k))}"><b>${pr[k]}</b></div>`).join("");
  $$("#prioSliders input").forEach((inp) => (inp.oninput = () => { S.farm.priorities = { ...priorities(), [inp.dataset.k]: +inp.value }; inp.nextElementSibling.textContent = inp.value; saveFarm(); rerankLocal(); }));

  $$("#waterChoices button").forEach((b) => { b.classList.toggle("sel", b.dataset.water === S.farm.water); b.onclick = () => { S.farm.water = b.dataset.water; saveFarm(); renderFarm(); }; });
  $$("#toolChoices button").forEach((b) => { b.classList.toggle("sel", b.dataset.tool === S.farm.tool); b.onclick = () => { S.farm.tool = b.dataset.tool; saveFarm(); renderFarm(); }; });
  $("#keepStaple").checked = S.farm.keepStaple; $("#keepStaple").onchange = (e) => { S.farm.keepStaple = e.target.checked; saveFarm(); };
  $("#stapleSelect").innerHTML = list.map((c) => `<option value="${c.id}">${c.icon || ""} ${esc(cropName(c.id))}</option>`).join("");
  const firstCrop = S.farm.current[0] && S.farm.current[0].crop;
  $("#stapleSelect").value = S.farm.staple || firstCrop || (list[0] && list[0].id) || "";
  $("#stapleSelect").onchange = (e) => { S.farm.staple = e.target.value; saveFarm(); };
  const sellCrops = [...new Set([...S.farm.current.map((p) => p.crop), ...list.filter((c) => c.group !== "cover").slice(0, 14).map((c) => c.id)])];
  $("#sellGrid").innerHTML = sellCrops.map((cid) => { const v = S.farm.market[cid] || "unsure"; return `<button data-c="${cid}" data-v="${v}" aria-label="${esc(cropName(cid))}: ${esc(t("mk_" + v))}"><span>${cropIcon(cid)} ${esc(cropName(cid))}</span><span>${MARKET_ICON[v]}</span></button>`; }).join("");
  $$("#sellGrid button").forEach((b) => (b.onclick = () => { const cur = S.farm.market[b.dataset.c] || "unsure"; S.farm.market[b.dataset.c] = MARKET_CYCLE[(MARKET_CYCLE.indexOf(cur) + 1) % 4]; saveFarm(); renderFarm(); }));
  [["stPh", "ph"], ["stSoc", "soc"], ["stClay", "clay"], ["stSand", "sand"]].forEach(([id, k]) => {
    const el = document.getElementById(id); el.value = S.farm.soilTest[k] ?? "";
    el.onchange = () => { const v = el.value === "" ? undefined : +el.value; if (v === undefined) delete S.farm.soilTest[k]; else S.farm.soilTest[k] = v; saveFarm(); };
  });
  $("#avoidChips").innerHTML = list.map((c) => `<button class="${S.farm.avoid.includes(c.id) ? "sel" : ""}" data-c="${c.id}">${c.icon || ""} ${esc(cropName(c.id))}</button>`).join("");
  $$("#avoidChips button").forEach((b) => (b.onclick = () => { const a = S.farm.avoid; const i = a.indexOf(b.dataset.c); if (i >= 0) a.splice(i, 1); else a.push(b.dataset.c); saveFarm(); renderFarm(); }));
  setWizard(S.wstep);
}
function addPlanting(crop, month, withCrop) {
  const years = S.pickYear === "both" ? [1, 2] : [+S.pickYear];
  years.forEach((y) => S.farm.current.push({ crop, year: y, sow_month: month, ...(withCrop ? { with: withCrop } : {}) }));
  S.farm.current.sort((a, b) => (a.year - b.year) || (a.sow_month - b.sow_month));
  if (!S.farm.staple) S.farm.staple = crop;
  saveFarm(); renderFarm(); toast(t("added", { crop: cropName(crop) + (withCrop ? " + " + cropName(withCrop) : ""), month: months()[month - 1] }));
}
function stripHTML(plantings) {
  const cal = new Array(24).fill(null);
  const dur = (id, p) => p.duration_m || (S.cropMap[id] || {}).duration_m || 3;
  plantings.filter((p) => !p.intercrop_with).forEach((p) => {
    const comp = p.with || p.companion; const s = (p.year - 1) * 12 + p.sow_month - 1;
    for (let k = 0; k < dur(p.crop, p); k++) cal[(s + k) % 24] = { crop: p.crop, comp, first: k === 0 };
    if (comp) for (let k = 0; k < ((S.cropMap[comp] || {}).duration_m || 3); k++) { const i = (s + k) % 24; if (cal[i] && cal[i].crop === p.crop) cal[i].inter = true; else if (!cal[i]) cal[i] = { crop: comp, first: false }; }
  });
  const cells = cal.map((c, i) => `<div class="m ${c && c.first ? "first" : ""} ${c && c.inter ? "inter" : ""}" style="background:${c ? cropColor(c.crop) : "#efe9e1"}" title="${esc(months()[i % 12])} · ${esc(t("year_n", { n: Math.floor(i / 12) + 1 }))}: ${c ? esc(cropName(c.crop)) + (c.inter ? " + " + esc(cropName(c.comp)) : "") : esc(t("bare_soil"))}">${c && c.first ? cropIcon(c.crop) + (c.comp ? cropIcon(c.comp) : "") : ""}</div>`).join("");
  const labels = Array.from({ length: 24 }, (_, i) => `<span>${esc(String(months()[i % 12]).slice(0, 1))}</span>`).join("");
  return `<div class="year-split"><span>${esc(t("year1"))}</span><span>${esc(t("year2"))}</span></div><div class="plan-strip">${cells}</div><div class="strip-labels">${labels}</div>`;
}
function renderPlanList(plantings, listSel, stripSel, onRemove) {
  $(stripSel).innerHTML = stripHTML(plantings);
  $(listSel).innerHTML = plantings.length ? plantings.map((p, i) => `<li>${cropIcon(p.crop)} ${esc(cropName(p.crop))}${p.with ? ` + ${cropIcon(p.with)} ${esc(cropName(p.with))}` : ""} · ${esc(t("year_short"))}${p.year} ${esc(months()[p.sow_month - 1])}<button aria-label="${esc(t("remove"))}" data-i="${i}">×</button></li>`).join("") : `<li class="empty">${esc(t("nothing_yet"))}</li>`;
  $$(`${listSel} button`).forEach((b) => (b.onclick = () => onRemove(+b.dataset.i)));
}
$("#clearPlan").onclick = () => { S.farm.current = []; saveFarm(); renderFarm(); };
function setWizard(n) {
  S.wstep = n;
  $$(".wpanel").forEach((p) => p.classList.toggle("on", +p.dataset.w === n));
  $$("#wsteps li").forEach((li) => li.classList.toggle("on", +li.dataset.w === n));
}
$$("[data-next]").forEach((b) => (b.onclick = () => {
  if (+b.dataset.next === 2 && !S.farm.current.length) return toast(t("need_crop"));
  setWizard(+b.dataset.next); window.scrollTo({ top: 0, behavior: "smooth" });
}));
$$("#wsteps li").forEach((li) => (li.onclick = () => setWizard(+li.dataset.w)));
$("#showOptions").onclick = () => analyze(true);

function requestBody(extra = {}) {
  const st = Object.fromEntries(Object.entries(S.farm.soilTest || {}).filter(([, v]) => v !== "" && v !== null && v !== undefined));
  const c = { water: S.farm.water, equipment: S.farm.tool, keep_staple: S.farm.keepStaple, avoid: S.farm.avoid, market: S.farm.market };
  if (S.farm.staple) c.staple = S.farm.staple;
  if (Object.keys(st).length) c.soil_test = st;
  return { current: S.farm.current, priorities: priorities(), lang: S.lang, constraints: c, ...extra };
}

/* =============================================================== options */
async function analyze(goTab) {
  if (!S.farm.current.length) { go("farm"); setWizard(1); return toast(t("need_crop")); }
  busy(true, t("searching_rotations"));
  try {
    S.result = await api(`/api/sites/${S.field.id}/strategies`, { method: "POST", body: JSON.stringify(requestBody()) });
    renderOptions(); renderCropRisk(); setupPlanner(); $("#whatifResults").hidden = true;
    if (S.result.constraints.staple_unavailable) toast(t("staple_unavailable"));
    if (goTab) go("options");
  } catch (err) { modal(`<h3>${esc(t("err_options"))}</h3><p>${esc(err.message)}</p>`); } finally { busy(false); }
}
function rerankLocal() {
  if (!S.result) return;
  const w = priorities(); const sum = CRIT.reduce((a, k) => a + w[k], 0) || 1;
  S.result.strategies.forEach((s) => {
    let v = CRIT.reduce((a, k) => a + s.scores[k] * w[k], 0) / sum;
    v -= 8 * (s.numbers.staple_years_missing || 0) + (s.numbers.staple_missing_cycle ? 25 : 0);
    s.total = Math.round(v * 10) / 10;
  });
  renderOptions();
}
function stratName(s) { const k = "s_" + s.id; return t(k) !== k ? t(k) : s.name; }
function stratTag(s) { const k = "st_" + s.id; return t(k) !== k ? t(k) : (s.tagline || ""); }

function optionCard(s, idx, best) {
  const ex = s.explanation, f = ex.farmer, range = s.robustness && s.robustness.range;
  const robust = s.robustness && s.robustness.by_type.length ? `<div class="robust small"><b>${esc(s.robustness.summary || "")}</b><div class="bars">${s.robustness.by_type.map((ty) => `<div class="${ty.climate_fit >= 60 ? "ok" : "bad"}" title="${esc(ty.name)}">${esc(ty.name.replace(" year", ""))}<br><b>${Math.round(ty.climate_fit)}</b></div>`).join("")}</div></div>` : "";
  const list = (arr, cls, title) => arr && arr.length ? `<div class="${cls}"><h4>${esc(title)}</h4><ul class="plain">${arr.map((x) => `<li>${esc(x)}</li>`).join("")}</ul></div>` : "";
  return `<article class="card opt ${best ? "best" : ""}" data-sid="${esc(s.id)}">
    <div class="head"><div>
      ${s.is_current ? `<span class="badge today">${esc(t("today"))}</span>` : best ? `<span class="badge best">★ ${esc(t("best_for_you"))}</span>` : ""}
      <h3 style="margin-top:6px">${esc(stratName(s))}</h3><p class="tagline">${esc(stratTag(s))}</p></div>
      <div class="ring" style="--p:${Math.max(0, Math.min(100, s.total))}" title="${esc(t("match_help"))}"><b>${Math.round(s.total)}<small>${range ? `${range[0]}–${range[1]}` : ""}</small></b></div></div>
    <div class="row gap wrap"><span class="light ${ex.confidence.level}"><i></i>${esc(t("conf_" + ex.confidence.level))}</span><span class="muted small">${esc(t("range_note"))}</span></div>
    ${stripHTML(s.plantings)}
    <p class="small"><b>${esc(s.sequence)}</b></p>
    ${list(f.good, "good", t("good_for_you"))}${list(f.watch, "watch", t("watch_out"))}<div class="farmer-only">${list(f.ask, "ask", t("ask_officer"))}</div>
    <div class="expert-only">
      <div class="nums"><div><b>${fmt(s.numbers.bare_months_yr)}</b><span>${esc(t("n_bare"))}</span></div><div><b>${s.numbers.n_fixed_kg_yr}</b><span>${esc(t("n_n"))}</span></div><div><b>${s.numbers.irrigation_need_mm_yr}</b><span>${esc(t("n_water"))}</span></div><div><b>${s.numbers.families}</b><span>${esc(t("n_fam"))}</span></div></div>
      <div class="radar-box"><canvas id="radar${idx}"></canvas></div>${robust}
      <details class="ex" open><summary>${esc(t("why"))}</summary><ul>${ex.why.map((w) => `<li>${esc(w)}</li>`).join("")}</ul></details>
      <details class="ex"><summary>${esc(t("evidence"))}</summary><ul>${ex.evidence.map((e) => `<li>${esc(e.claim)} <span class="src-chip">${esc(e.source)}</span></li>`).join("") || `<li>${esc(t("scores_only"))}</li>`}</ul></details>
      <details class="ex"><summary>${esc(t("benefits"))}</summary><ul>${ex.benefits.map((b) => `<li>${esc(b)}</li>`).join("")}</ul></details>
      <details class="ex"><summary>${esc(t("risks"))}</summary><ul>${ex.risks.map((r) => `<li>${esc(r)}</li>`).join("") || `<li>${esc(t("no_risk"))}</li>`}</ul></details>
      <details class="ex"><summary>${esc(t("gaps"))}</summary><ul>${ex.gaps.map((g) => `<li>${esc(g)}</li>`).join("")}</ul></details>
      <details class="ex"><summary>${esc(t("ask_officer"))}</summary><ul>${ex.ask_expert.map((g) => `<li>${esc(g)}</li>`).join("")}</ul></details>
      <p class="muted small">${esc(t("conf_why"))}: ${esc(ex.confidence.reasons.join(" · "))}</p>
    </div>
    <details class="ex farmer-only"><summary>${esc(t("more_detail"))}</summary><ul>${ex.why.map((w) => `<li>${esc(w)}</li>`).join("")}${ex.gaps.slice(0, 3).map((g) => `<li class="muted">${esc(g)}</li>`).join("")}</ul></details>
    <div class="opt-actions">
      ${s.is_current ? "" : `<button class="btn ghost small" data-act="try">✏️ ${esc(t("try_plan"))}</button>`}
      <button class="btn ghost small" data-act="share">📤 ${esc(t("share"))}</button>
      <button class="btn ghost small" data-act="print">🖨️ ${esc(t("print"))}</button>
      ${S.health.llm_enabled ? `<button class="btn ghost small" data-act="explain">💬 ${esc(t("explain_simply"))}</button>` : ""}
    </div></article>`;
}
function renderOptions() {
  const res = S.result, box = $("#options");
  const cur = res.strategies[0];
  const order = [cur, ...res.strategies.slice(1).sort((a, b) => b.total - a.total)];
  const best = order[1];
  $("#optionsSub").textContent = t("options_sub", { n: res.pool_size.toLocaleString(S.lang === "fr" ? "fr" : "en"), k: order.length - 1 });
  box.innerHTML = order.map((s, i) => optionCard(s, i, best && s.id === best.id)).join("");
  order.forEach((s, i) => {
    const card = box.children[i];
    $$("[data-act]", card).forEach((b) => (b.onclick = () => optionAction(b.dataset.act, s)));
    chart(`radar${i}`, {
      type: "radar",
      data: { labels: CRIT.map((k) => t("g_" + k)), datasets: [
        ...(s.is_current ? [] : [{ label: t("today"), data: CRIT.map((k) => cur.scores[k]), borderColor: "#b9ab9c", backgroundColor: "rgba(185,171,156,.12)", pointRadius: 0, borderDash: [4, 3] }]),
        { label: stratName(s), data: CRIT.map((k) => s.scores[k]), borderColor: s.is_current ? "#8a6448" : "#2f6b3a", backgroundColor: s.is_current ? "rgba(138,100,72,.18)" : "rgba(76,154,91,.22)", pointRadius: 2 }] },
      options: { plugins: { legend: { display: !s.is_current, position: "bottom", labels: { boxWidth: 10 } } }, scales: { r: { min: 0, max: 100, ticks: { display: false, stepSize: 25 }, pointLabels: { font: { size: 10 } } } } },
    });
  });
  $("#scoreTable").innerHTML = `<tr><th></th>${order.map((s) => `<th>${esc(stratName(s))}</th>`).join("")}</tr>` +
    CRIT.map((k) => `<tr><td>${GOAL_ICON[k]} ${esc(t("g_" + k))}</td>${order.map((s) => { const d = s.is_current ? 0 : s.delta_vs_current[k]; return `<td>${Math.round(s.scores[k])}${d ? ` <span class="${d > 0 ? "down" : "up"} small">${d > 0 ? "+" : ""}${Math.round(d)}</span>` : ""}</td>`; }).join("")}</tr>`).join("") +
    `<tr><td><b>${esc(t("match"))}</b></td>${order.map((s) => `<td><b>${Math.round(s.total)}</b></td>`).join("")}</tr>
     <tr><td>${esc(t("n_cropwater"))}</td>${order.map((s) => `<td>${s.numbers.crop_water_mm_yr}</td>`).join("")}</tr>`;
}
function shareText(s) {
  const f = s.explanation.farmer;
  return [`FieldWise · ${S.profile.site.name}`, `${stratName(s)}: ${s.sequence}`, ...(f.good || []).map((x) => "✔ " + x), ...(f.watch || []).slice(0, 2).map((x) => "⚠ " + x), t("disclaimer")].join("\n");
}
async function optionAction(act, s) {
  if (act === "try") { $("#plannerBase").value = s.id; loadPlannerFrom(s.id); $("#planner").scrollIntoView({ behavior: "smooth" }); }
  if (act === "share") {
    const text = shareText(s);
    if (navigator.share) { try { await navigator.share({ title: "FieldWise", text }); } catch (_) { /* cancelled */ } }
    else window.open(`https://wa.me/?text=${encodeURIComponent(text)}`, "_blank", "noopener");
  }
  if (act === "print") {
    $$(".opt").forEach((c) => (c.style.display = c.dataset.sid === s.id || c.dataset.sid === "current" ? "" : "none"));
    $("#s-options").classList.add("printing"); window.print(); $("#s-options").classList.remove("printing");
    $$(".opt").forEach((c) => (c.style.display = ""));
  }
  if (act === "explain") {
    modal(`<p><span class="spinner"></span> ${esc(t("working"))}</p>`);
    const langName = { en: "English", fr: "French", tw: "Twi (Akan)", ha: "Hausa" }[S.lang];
    try {
      const r = await api("/api/explain", { method: "POST", body: JSON.stringify({ strategy: s, site_name: S.profile.site.name, language: langName }) });
      $("#modalBody").innerHTML = `<h3>${esc(stratName(s))}</h3><p style="white-space:pre-wrap">${esc(r.text)}</p><p class="muted small">${esc(t("disclaimer"))}</p>`;
    } catch (err) { $("#modalBody").innerHTML = `<p>${esc(err.message)}</p>`; }
  }
}

/* ---------------- planner (make your own plan) */
function setupPlanner() {
  const ss = S.result.strategies;
  $("#plannerBase").innerHTML = ss.map((s) => `<option value="${esc(s.id)}">${esc(stratName(s))}</option>`).join("");
  $("#plannerBase").onchange = (e) => loadPlannerFrom(e.target.value);
  $("#plannerCrop").innerHTML = suitedCrops().map((c) => `<option value="${c.id}">${c.icon || ""} ${esc(cropName(c.id))}</option>`).join("");
  $("#plannerMonth").innerHTML = months().map((m, i) => `<option value="${i + 1}">${esc(m)}</option>`).join("");
  $("#plannerAdd").onclick = () => { const w = $("#plannerWith").value; S.planner.push({ crop: $("#plannerCrop").value, year: +$("#plannerYear").value, sow_month: +$("#plannerMonth").value, ...(w ? { with: w } : {}) }); renderPlanner(); };
  const fillWith = () => { const comps = ((S.cropMap[$("#plannerCrop").value] || {}).companions || []).filter((c) => S.cropMap[c]);
    $("#plannerWith").innerHTML = `<option value="">${esc(t("alone"))}</option>` + comps.map((c) => `<option value="${c}">+ ${cropIcon(c)} ${esc(cropName(c))}</option>`).join(""); };
  $("#plannerCrop").onchange = fillWith; fillWith();
  const base = ss[1] ? ss[1].id : "current";
  $("#plannerBase").value = base; loadPlannerFrom(base);
}
function loadPlannerFrom(id) {
  const s = S.result.strategies.find((x) => x.id === id) || S.result.strategies[0];
  S.planner = (s.compact || s.plantings.filter((p) => !p.intercrop_with)).map((p) => ({ ...p }));
  renderPlanner();
}
function renderPlanner() {
  S.planner.sort((a, b) => (a.year - b.year) || (a.sow_month - b.sow_month));
  renderPlanList(S.planner, "#plannerList", "#plannerStrip", (i) => { S.planner.splice(i, 1); renderPlanner(); });
  clearTimeout(S.plannerTimer);
  $("#plannerResult").innerHTML = `<span class="muted small">${esc(t("working"))}</span>`;
  S.plannerTimer = setTimeout(scorePlanner, 450);
}
async function scorePlanner() {
  if (!S.planner.length) { $("#plannerResult").innerHTML = ""; return; }
  try {
    const r = await api(`/api/sites/${S.field.id}/score`, { method: "POST", body: JSON.stringify(requestBody({ plan: S.planner })) });
    const p = r.plan, f = p.explanation.farmer;
    const d = CRIT.filter((k) => Math.abs(p.delta_vs_current[k]) >= 5).map((k) => `<span>${GOAL_ICON[k]} ${esc(t("g_" + k))} <b class="${p.delta_vs_current[k] > 0 ? "down" : "up"}">${p.delta_vs_current[k] > 0 ? "+" : ""}${Math.round(p.delta_vs_current[k])}</b></span>`).join("");
    $("#plannerResult").innerHTML = `<div class="row gap"><div class="ring" style="--p:${Math.max(0, p.total)}"><b>${Math.round(p.total)}<small>${p.robustness.range ? p.robustness.range.join("–") : ""}</small></b></div>
      <div><b>${esc(t("your_plan_vs", { now: Math.round(r.current_total) }))}</b><div class="delta">${d || `<span>${esc(t("similar"))}</span>`}</div>
      <span class="light ${p.explanation.confidence.level}"><i></i>${esc(t("conf_" + p.explanation.confidence.level))}</span></div></div>
      ${f.good.length ? `<div class="good"><h4>${esc(t("good_for_you"))}</h4><ul class="plain">${f.good.map((x) => `<li>${esc(x)}</li>`).join("")}</ul></div>` : ""}
      ${f.watch.length ? `<div class="watch"><h4>${esc(t("watch_out"))}</h4><ul class="plain">${f.watch.map((x) => `<li>${esc(x)}</li>`).join("")}</ul></div>` : ""}`;
  } catch (err) { $("#plannerResult").textContent = err.message; }
}

/* =============================================================== weather story */
const CAL_KEYS = ["dry", "dryspell", "heat", "frost", "storm", "soilmoist", "stress", "bare", "esi", "uncovered"];
function renderStory() {
  const p = S.profile; if (!p) return;
  $("#storySub").textContent = t("story_sub", { years: p.record }) + (p.zone ? ` ${t("zone_label")}: ${t("zn_" + p.zone.key)}.` : "");
  const n = p.summary_numbers;
  const facts = [["🌧️", `${n.annual_rain_mm} mm`, t("f_rain")], ["🔥", n.hot_days_yr, t("f_hot")], ["🏜️", n.dry_months, t("f_dry")]];
  if (n.frost_days_yr >= 1) facts.push(["❄️", n.frost_days_yr, t("f_frost")]);
  else facts.push(["🌱", (p.windows || []).map((w) => `${months()[w.start - 1]}–${months()[w.end - 1]}`).join(", ") || "–", t("f_season")]);
  $("#bigFacts").innerHTML = facts.map(([e, v, l]) => `<div class="fact"><span class="em">${e}</span><b>${esc(v)}</b><span>${esc(l)}</span></div>`).join("");
  $("#headline").innerHTML = p.headline.map((h) => `<li>${esc(h)}</li>`).join("");

  const win = new Array(12).fill(false); p.windows.forEach((w) => w.months.forEach((m) => (win[m - 1] = true)));
  let html = `<tr><th></th>${months().map((m) => `<th>${esc(m)}</th>`).join("")}</tr><tr><td class="lab small">${esc(t("cal_window"))}</td>${win.map((on) => `<td class="${on ? "win-on" : ""}" style="height:10px;border-radius:4px"></td>`).join("")}</tr>`;
  p.calendar.forEach((row, ri) => {
    const label = CAL_KEYS.includes(row.key) ? t("cal_" + row.key) : row.label;
    html += `<tr><td class="lab">${esc(label)}<span class="src">${esc(row.source)}</span></td>${row.cells.map((c, m) => `<td class="cell lvl-${c.level === null ? "null" : c.level}" data-r="${ri}" data-m="${m}" tabindex="0" aria-label="${esc(label)} ${esc(months()[m])}: ${esc(c.text)}"></td>`).join("")}</tr>`;
  });
  $("#calendar").innerHTML = html;
  $$("#calendar td.cell[data-r]").forEach((td) => {
    const show = () => { const row = p.calendar[+td.dataset.r]; const c = row.cells[+td.dataset.m];
      $("#calDetail").textContent = `${months()[+td.dataset.m]} · ${CAL_KEYS.includes(row.key) ? t("cal_" + row.key) : row.label}: ${c.text} (${t("risk" + (c.level ?? 0))})`; };
    td.onclick = show; td.onkeydown = (e) => { if (e.key === "Enter") show(); };
  });

  const clim = p.charts.climatology;
  chart("chRainEt", { data: { labels: months(), datasets: [
    { type: "bar", label: t("rain_mm"), data: clim.rain, backgroundColor: "#7fb98a", borderRadius: 4 },
    { type: "line", label: t("need_mm"), data: clim.et0, borderColor: "#d9603b", backgroundColor: "#d9603b", tension: .35, pointRadius: 2 }] },
    options: { plugins: { legend: { position: "bottom" } }, scales: { y: { title: { display: true, text: "mm" } } } } });

  const ph = p.phenology;
  const gds = [];
  if (clim.ndvi) gds.push({ type: "line", label: "MODIS NDVI (250 m)", data: clim.ndvi, borderColor: "#2f6b3a", tension: .35, yAxisID: "y" });
  if (clim.landsat_ndvi) gds.push({ type: "line", label: "Landsat NDVI (30 m)", data: clim.landsat_ndvi, borderColor: "#e0a32e", tension: .35, yAxisID: "y" });
  if (ph) gds.push({ type: "bar", label: t("bare_chance"), data: ph.ai_bare_prob.map((v) => Math.round(v * 100)), backgroundColor: "rgba(138,100,72,.25)", yAxisID: "y1" });
  chart("chGreen", { data: { labels: months(), datasets: gds }, options: { plugins: { legend: { position: "bottom" } },
    scales: { y: { title: { display: true, text: "NDVI" } }, y1: { position: "right", min: 0, max: 100, grid: { drawOnChartArea: false }, title: { display: true, text: "%" } } } } });
  $("#phenoNote").textContent = ph ? t("pheno_note", { up: months()[ph.green_up_month - 1], down: months()[ph.dry_down_month - 1] }) : t("no_ndvi");

  $("#trendCards").innerHTML = p.trends.map((c, i) => `<div class="card trend-card ${c.concern ? "concern" : c.significant ? "good" : ""}"><div class="small muted">${esc(c.source)} · ${esc(c.period)}</div><div class="big">${esc(c.text)}</div>
    <div class="small muted">${esc(c.significant ? t("clear_change") : t("normal_ups"))}<span class="expert-only"> (Mann-Kendall p=${c.p_value})</span></div><div class="chart-box spark"><canvas id="tr${i}"></canvas></div></div>`).join("");
  p.trends.forEach((c, i) => chart(`tr${i}`, { type: "line", data: { labels: c.series.map((s) => s.year), datasets: [{ data: c.series.map((s) => s.value), borderColor: c.concern ? "#d9603b" : "#4c9a5b", pointRadius: 0, borderWidth: 2, tension: .3, spanGaps: true }] },
    options: { plugins: { legend: { display: false } }, scales: { x: { display: false }, y: { display: false } } } }));

  const long = p.charts.long;
  if (long.grace_lwe) chart("chGrace", { type: "line", data: { labels: long.grace_lwe.t, datasets: [{ label: "cm", data: long.grace_lwe.v, borderColor: "#2b6f9e", pointRadius: 0, borderWidth: 1.6, fill: { target: { value: 0 }, above: "rgba(43,111,158,.15)", below: "rgba(217,96,59,.18)" } }] },
    options: { plugins: { legend: { display: false } }, scales: { x: { ticks: { maxTicksLimit: 6 } }, y: { title: { display: true, text: "cm" } } } } });
  else chart("chGrace", { type: "line", data: { labels: [], datasets: [] } });
  const ev = p.events;
  $("#eventsList").innerHTML = ev && ev.events.length ? ev.events.map((e) => `<li><b>${esc(e.category_title || e.category)}</b> · ${esc(e.date)} · ${e.distance_km} km<br>${e.link ? `<a href="${esc(e.link)}" target="_blank" rel="noopener">${esc(e.title)}</a>` : esc(e.title)}</li>`).join("")
    : `<li class="empty">${esc(ev ? t("no_events", { km: ev.radius_km, y: ev.years }) : t("events_off"))}</li>`;

  const ag = p.agreement.rain;
  $("#agreeText").textContent = ag ? `${ag.pair}: r = ${ag.r}, bias ${ag.bias_pct}% → ${ag.verdict}` : "GPM not loaded yet.";
  if (long.gpm_rain && long.rain) {
    const n2 = Math.min(72, long.rain.t.length); const tt = long.rain.t.slice(-n2); const gm = Object.fromEntries(long.gpm_rain.t.map((k, i) => [k, long.gpm_rain.v[i]]));
    chart("chRainCompare", { type: "line", data: { labels: tt, datasets: [{ label: "NASA POWER", data: long.rain.v.slice(-n2), borderColor: "#4c9a5b", pointRadius: 0 }, { label: "GPM IMERG", data: tt.map((k) => gm[k] ?? null), borderColor: "#2b6f9e", borderDash: [4, 3], pointRadius: 0 }] },
      options: { plugins: { legend: { position: "bottom" } }, scales: { x: { ticks: { maxTicksLimit: 6 } } } } });
  }
  if (ph) {
    $("#phenoBox").innerHTML = `<p class="small">Gaussian mixture with ${ph.components} greenness levels on ${ph.source === "landsat_ndvi" ? "Landsat 30 m" : "MODIS 250 m"} NDVI vs. fixed rule NDVI &lt; ${ph.rule_threshold}. They agree on ${Math.round(ph.agreement * 100)}% of months. Green-up ${esc(months()[ph.green_up_month - 1])}, dry-down ${esc(months()[ph.dry_down_month - 1])}.${ph.bare_months_trend_per_decade !== null ? ` Bare-month trend: ${ph.bare_months_trend_per_decade} per decade.` : ""}</p>`;
    chart("chPheno", { type: "bar", data: { labels: months(), datasets: [{ label: "AI P(bare)", data: ph.ai_bare_prob, backgroundColor: "#8a6448" }, { label: "Rule P(bare)", data: ph.rule_bare_prob, backgroundColor: "#e0a32e" }, { type: "line", label: "AI certainty", data: ph.certainty, borderColor: "#2b6f9e", pointRadius: 0 }] },
      options: { plugins: { legend: { position: "bottom" } }, scales: { y: { min: 0, max: 1 } } } });
  } else $("#phenoBox").innerHTML = `<p class="empty">${esc(t("no_ndvi"))}</p>`;
  $("#yearTypes").innerHTML = (p.year_types.types || []).map((ty) => `<div class="card soft" style="margin-bottom:8px;padding:10px"><b>${esc(ty.name)}</b> · ${Math.round(ty.share * 100)}% · <span class="${ty.becoming === "more common" ? "up" : ""}">${esc(ty.becoming)}</span><div class="small muted">${Object.entries(ty.means).map(([k, v]) => `${esc(k)} ${v}`).join(" · ")}</div><div class="small muted">${ty.years.slice(-6).join(", ")}</div></div>`).join("");
  const st = p.stress;
  if (st) {
    $("#stressBox").innerHTML = `<table class="data"><tr><th>Model</th><th>R² (unseen years)</th><th>MAE</th></tr>${st.models.map((m) => `<tr><td>${esc(m.model)}${m.model === st.chosen ? " ✔" : ""}</td><td>${m.r2}</td><td>${m.mae}</td></tr>`).join("")}</table><p class="small muted">${esc(st.note)}</p>`;
    chart("chDrivers", { type: "bar", data: { labels: st.drivers.map((d) => d.driver), datasets: [{ data: st.drivers.map((d) => Math.round(d.importance * 100)), backgroundColor: "#8a6448" }] }, options: { indexAxis: "y", plugins: { legend: { display: false } } } });
  } else $("#stressBox").innerHTML = `<p class="empty">${esc(t("no_ndvi"))}</p>`;
  const g = p.gedi;
  $("#bioBox").innerHTML = [
    g && g.available ? `<div><b>GEDI biomass</b><br>${fmt(g.mean)} t/ha (IQR ${fmt(g.p25)}–${fmt(g.p75)}), ${g.footprints} lidar footprints within ${g.radius_km} km</div>` : "<div><b>GEDI</b><br>not loaded</div>",
    clim.eco_esi ? `<div><b>ECOSTRESS ESI</b><br>${clim.eco_esi.map((v, i) => (v === null ? "" : `${esc(months()[i])} ${v.toFixed(2)}`)).filter(Boolean).join(" · ")}</div>` : `<div><b>ECOSTRESS</b><br>${esc(p.ecostress_status || "off")}</div>`,
    `<div><b>${esc(t("soil"))}</b><br>${esc(p.soil.texture || "")} · pH ${fmt(p.soil.ph, 1)} · OC ${fmt(p.soil.soc, 1)} g/kg<br><span class="muted small">${esc(p.soil.source || "")}</span></div>`].join("");

  $("#cropExplorer").innerHTML = `<tr><th>${esc(t("crop"))}</th><th>${esc(t("best_sow"))}</th><th>${esc(t("fit"))}</th>${months().map((m) => `<th>${esc(m)}</th>`).join("")}</tr>` +
    p.crop_explorer.slice(0, 20).map((r) => `<tr><td>${r.icon} ${esc(cropName(r.crop))}</td><td>${esc(months()[r.best_sow_month - 1])}</td><td>${Math.round(r.fit * 100)}</td>${r.by_month.map((v) => `<td><span class="fitcell" title="${Math.round(v * 100)}" style="background:rgba(47,107,58,${Math.max(0.05, v).toFixed(2)})"></span></td>`).join("")}</tr>`).join("");
  renderCropRisk();
}
const STAGE_KEYS = { establish: "stage_establish", grow: "stage_grow", flower: "stage_flower", ripen: "stage_ripen" };
function renderCropRisk() {
  const box = $("#cropRisk");
  // one bar per crop: merge the sowings of the same crop into a single 24-month strip
  const raw = S.result ? S.result.strategies[0].crop_risk : null;
  const rows = raw ? Object.values(raw.reduce((acc, r) => {
    const row = acc[r.crop] || (acc[r.crop] = { crop: r.crop, cells: new Array(24).fill(null) });
    r.cells.forEach((c, i) => { if (c && (!row.cells[i] || c.level > row.cells[i].level)) row.cells[i] = c; });
    return acc; }, {})) : null;
  $("#cropRiskDetail").textContent = "";
  if (!rows) { box.innerHTML = `<p class="empty">${esc(t("cropvs_need"))}</p>`; return; }
  box.innerHTML = rows.map((r, ri) => `<div class="crop-risk-row"><div class="name">${cropIcon(r.crop)} ${esc(cropName(r.crop))}</div><div class="plan-strip">${r.cells.map((c, i) => (c ? `<div class="m" data-r="${ri}" data-i="${i}" role="button" tabindex="0" style="background:${RISK_COLORS[c.level]}" title="${esc(t(STAGE_KEYS[c.stage]))}">${c.stage === "flower" ? "🌼" : c.stage === "establish" ? "🌱" : c.stage === "ripen" ? "🌾" : ""}</div>` : `<div class="m"></div>`)).join("")}</div></div>`).join("")
    + `<div class="strip-labels">${Array.from({ length: 24 }, (_, i) => `<span>${esc(String(months()[i % 12]).slice(0, 1))}</span>`).join("")}</div>`;
  $$("#cropRisk .m[data-r]").forEach((m) => {
    const show = () => { const c = rows[+m.dataset.r].cells[+m.dataset.i];
      const why = c.reasons.map((x) => t("rr_" + x.code, x)).join("; ") || t("rr_none");
      $("#cropRiskDetail").textContent = `${cropName(rows[+m.dataset.r].crop)} · ${months()[c.month - 1]} · ${t(STAGE_KEYS[c.stage])}: ${why}`; };
    m.onclick = show; m.onkeydown = (e) => { if (e.key === "Enter") show(); };
  });
}

/* =============================================================== map: time machine + field zones */
function resetMaps() {
  ["A", "B", "zone"].forEach((k) => { if (S.maps[k]) { S.maps[k].remove(); S.maps[k] = null; } });
  S.gibsLayers = {}; S.zoneLayer = null; clearInterval(S.playTimer); S.playTimer = null; $("#playBtn").textContent = "▶";
}
async function initMaps() {
  const p = S.profile; if (!p) return;
  if (!S.maps.A) {
    S.maps.A = L.map("mapA", { zoomControl: true }).setView([p.site.lat, p.site.lon], 10);
    baseLayers().sat.addTo(S.maps.A);
    L.circleMarker([p.site.lat, p.site.lon], { radius: 7, color: "#fff", weight: 2, fillColor: "#4c9a5b", fillOpacity: 1 }).addTo(S.maps.A).bindTooltip(p.site.name);
    if (!S.imagery || !(S.imagery.themes || []).length) { try { S.imagery = await api("/api/imagery"); } catch (err) { S.imagery = { themes: [], error: err.message }; } }
    const th = S.imagery.themes || [];
    S.theme = (S.theme && th.find((x) => x.key === S.theme.key)) || th.find((x) => x.key === "ndvi") || th[0] || null;
    renderLayerChips(); buildTimeline(); drawGibs();
  }
  if (!S.maps.zone) initZoneMap();
  setTimeout(() => ["A", "B", "zone"].forEach((k) => S.maps[k] && S.maps[k].invalidateSize()), 80);
}
function renderLayerChips() {
  const th = S.imagery.themes || [];
  $("#imageryNote").textContent = th.length ? t("imagery_note") : t("imagery_off");
  $("#layerChips").innerHTML = th.map((x) => `<button class="${S.theme && S.theme.key === x.key ? "on" : ""}" data-k="${x.key}">${esc(t("lyr_" + x.key))}</button>`).join("");
  $$("#layerChips button").forEach((b) => (b.onclick = () => { S.theme = th.find((x) => x.key === b.dataset.k); renderLayerChips(); buildTimeline(); drawGibs(); }));
  const lg = S.theme && S.theme.legend;
  $("#legendImg").hidden = !lg; if (lg) $("#legendImg").src = lg;
  $("#layerAbout").textContent = S.theme ? `${S.theme.about} · ${S.theme.layer}` : "";
  $(".time-row").hidden = !S.theme;
}
function alignDate(d, th) {
  const per = (th.time && th.time.period) || "P1D";
  const m = per.match(/^P(\d+)([DM])$/);
  if (m && m[2] === "M") return new Date(Date.UTC(d.getUTCFullYear(), d.getUTCMonth(), 1));
  if (m && m[2] === "D" && +m[1] > 1) {
    const n = +m[1]; const start = Date.UTC(d.getUTCFullYear(), 0, 1); const doy = Math.floor((d - start) / 864e5);
    return new Date(start + Math.floor(doy / n) * n * 864e5);
  }
  return d;
}
function buildTimeline() {
  if (!S.theme || !S.theme.time) { S.dates = null; return; }
  const end = new Date(S.theme.time.end + "T00:00:00Z"); const start = new Date(S.theme.time.start + "T00:00:00Z");
  const first = new Date(Math.max(start, Date.UTC(end.getUTCFullYear() - 10, end.getUTCMonth(), 1)));
  const dates = [];
  for (let y = first.getUTCFullYear(), mo = first.getUTCMonth(); ; mo++) {
    if (mo > 11) { mo = 0; y++; }
    const d = new Date(Date.UTC(y, mo, 15)); if (d > end) break; dates.push(alignDate(d, S.theme));
  }
  S.dates = dates.length ? dates : [end];
  S.timeIdx = S.dates.length - 1;
  const sl = $("#timeSlider"); sl.max = S.dates.length - 1; sl.value = S.timeIdx;
  sl.oninput = () => { S.timeIdx = +sl.value; drawGibs(); };
  const years = [...new Set(S.dates.map((d) => d.getUTCFullYear()))];
  $("#yearA").innerHTML = $("#yearB").innerHTML = years.map((y) => `<option>${y}</option>`).join("");
  $("#yearA").value = years[0]; $("#yearB").value = years[years.length - 1];
}
const iso = (d) => d.toISOString().slice(0, 10);
function gibsLayer(dateStr) {
  return L.tileLayer(S.theme.template.replace("{time}", dateStr), { maxNativeZoom: S.theme.max_native_zoom, maxZoom: 16, opacity: S.theme.key === "truecolor" ? 1 : 0.75, attribution: "NASA EOSDIS GIBS" });
}
function drawGibs() {
  if (!S.theme || !S.dates || !S.maps.A) return;
  const two = $("#compareToggle").checked;
  const d = S.dates[S.timeIdx];
  let dA = d, dB = null;
  if (two) {
    const mo = d.getUTCMonth();
    dA = alignDate(new Date(Date.UTC(+$("#yearA").value, mo, 15)), S.theme);
    dB = alignDate(new Date(Date.UTC(+$("#yearB").value, mo, 15)), S.theme);
  }
  const label = (x) => `${months()[x.getUTCMonth()]} ${x.getUTCFullYear()}`;
  $("#timeLabel").textContent = label(d);
  if (S.gibsLayers.A) S.gibsLayers.A.remove();
  S.gibsLayers.A = gibsLayer(iso(dA)).addTo(S.maps.A);
  $("#capA").textContent = `${t("lyr_" + S.theme.key)} · ${label(dA)}`;
  $("#mapsWrap").classList.toggle("two", two); $("#colB").hidden = !two; $("#compareCtl").hidden = !two;
  if (two) {
    if (!S.maps.B) {
      S.maps.B = L.map("mapB", { zoomControl: false }).setView(S.maps.A.getCenter(), S.maps.A.getZoom());
      baseLayers().sat.addTo(S.maps.B);
      L.circleMarker([S.profile.site.lat, S.profile.site.lon], { radius: 7, color: "#fff", weight: 2, fillColor: "#4c9a5b", fillOpacity: 1 }).addTo(S.maps.B);
      let syncing = false;
      const sync = (from, to) => from.on("move", () => { if (syncing) return; syncing = true; to.setView(from.getCenter(), from.getZoom(), { animate: false }); syncing = false; });
      sync(S.maps.A, S.maps.B); sync(S.maps.B, S.maps.A);
    }
    if (S.gibsLayers.B) S.gibsLayers.B.remove();
    S.gibsLayers.B = gibsLayer(iso(dB)).addTo(S.maps.B);
    $("#capB").textContent = `${t("lyr_" + S.theme.key)} · ${label(dB)}`;
    setTimeout(() => S.maps.B.invalidateSize(), 60);
  }
  setTimeout(() => S.maps.A.invalidateSize(), 60);
}
$("#compareToggle").onchange = drawGibs; $("#yearA").onchange = drawGibs; $("#yearB").onchange = drawGibs;
$("#playBtn").onclick = () => {
  if (!S.dates) return;
  if (S.playTimer) { clearInterval(S.playTimer); S.playTimer = null; $("#playBtn").textContent = "▶"; return; }
  $("#playBtn").textContent = "⏸";
  if (S.timeIdx >= S.dates.length - 1) S.timeIdx = Math.max(0, S.dates.length - 25);
  S.playTimer = setInterval(() => { S.timeIdx = (S.timeIdx + 1) % S.dates.length; $("#timeSlider").value = S.timeIdx; drawGibs(); }, 1400);
};
function initZoneMap() {
  const p = S.profile; const g = p.field;
  S.maps.zone = L.map("zoneMap").setView([p.site.lat, p.site.lon], 16);
  baseLayers().sat.addTo(S.maps.zone);
  const keys = g ? Object.keys(g.layers).filter((k) => k !== "slope_pct") : [];
  S.zoneKey = keys.includes(S.zoneKey) ? S.zoneKey : keys[0];
  $("#zoneChips").innerHTML = keys.map((k) => `<button class="${k === S.zoneKey ? "on" : ""}" data-k="${k}">${esc(t("zone_" + k))}</button>`).join("");
  $$("#zoneChips button").forEach((b) => (b.onclick = () => { S.zoneKey = b.dataset.k; $$("#zoneChips button").forEach((x) => x.classList.toggle("on", x === b)); drawZones(); }));
  if (g) {
    const s = g.summary;
    $("#zoneNote").textContent = t("zone_note", { e: Math.round(s.high_erosion_share * 100), d: Math.round(s.dry_spot_share * 100), slope: fmt(s.mean_slope_pct, 1) }) + (g.greenness_period ? ` · Landsat ${g.greenness_period}` : "");
  } else $("#zoneNote").textContent = t("zones_off");
  drawZones();
}
function drawZones() {
  if (S.zoneLayer) { S.zoneLayer.remove(); S.zoneLayer = null; }
  const g = S.profile.field; if (!g || !S.zoneKey) return;
  const grid = g.layers[S.zoneKey]; const grp = L.layerGroup(); const green = S.zoneKey === "greenness";
  const color = (v) => (green ? `rgb(${Math.round(200 - 160 * v)},${Math.round(170 + 40 * v)},${Math.round(120 - 80 * v)})` : `rgb(${Math.round(241 - 63 * v)},${Math.round(239 - 181 * v)},${Math.round(229 - 200 * v)})`);
  for (let r = 0; r < g.cells; r++) for (let c = 0; c < g.cells; c++) {
    const v = Math.max(0, Math.min(1, grid[r][c])); const lat0 = g.origin[0] - r * g.dlat; const lon0 = g.origin[1] + c * g.dlon;
    L.rectangle([[lat0 - g.dlat, lon0], [lat0, lon0 + g.dlon]], { stroke: false, fillColor: color(v), fillOpacity: green ? 0.6 : 0.12 + 0.55 * v })
      .bindTooltip(`${t("zone_" + S.zoneKey)}: ${green ? "NDVI " + v.toFixed(2) : Math.round(v * 100) + "/100"} · ${t("slope")} ${fmt(g.layers.slope_pct[r][c], 1)}%`, { sticky: true }).addTo(grp);
  }
  S.zoneLayer = grp.addTo(S.maps.zone);
}

/* =============================================================== what if */
$$("#presetGrid button").forEach((b) => (b.onclick = () => {
  const [r, tc, st] = b.dataset.preset.split(",").map(Number);
  $("#rainS").value = r; $("#tempS").value = tc; $("#stormS").value = st; syncSliders();
  $$("#presetGrid button").forEach((x) => x.classList.toggle("sel", x === b)); runWhatIf();
}));
function syncSliders() { $("#rainV").textContent = `${+$("#rainS").value > 0 ? "+" : ""}${$("#rainS").value}%`; $("#tempV").textContent = `+${(+$("#tempS").value).toFixed(1)}°C`; $("#stormV").textContent = `+${$("#stormS").value}%`; }
["rainS", "tempS", "stormS"].forEach((id) => (document.getElementById(id).oninput = syncSliders));
$("#runWhatIf").onclick = runWhatIf;
async function runWhatIf() {
  if (!S.result) await analyze(false); if (!S.result) return;
  busy(true, t("rerunning"));
  try {
    const body = { scenario: { rain_pct: +$("#rainS").value, temp_c: +$("#tempS").value, storm_pct: +$("#stormS").value }, priorities: priorities(),
      constraints: requestBody().constraints, strategies: S.result.strategies.map((s) => ({ id: s.id, name: s.name, plantings: s.compact || s.plantings })) };
    renderWhatIf(await api(`/api/sites/${S.field.id}/whatif`, { method: "POST", body: JSON.stringify(body) }));
  } catch (err) { toast(err.message); } finally { busy(false); }
}
function renderWhatIf(r) {
  $("#whatifResults").hidden = false;
  const cc = r.climate_change;
  const chip = (lab, [a, b], unit, badUp = true) => { const d = b - a; const cls = !d ? "" : (d > 0) === badUp ? "up" : "down"; return `<div><span class="small muted">${esc(lab)}</span><b>${a} → ${b} ${unit}</b><span class="small ${cls}">${d > 0 ? "+" : ""}${Math.round(d * 10) / 10}</span></div>`; };
  $("#deltaChips").innerHTML = chip(t("f_rain"), cc.annual_rain_mm, "mm", false) + chip(t("need_mm"), cc.annual_et0_mm, "mm") + chip(t("f_hot"), cc.heat_days_yr, "") + chip(t("f_dry"), cc.dry_months, "") + chip(t("wi_heavy"), cc.heavy_days_yr, "");
  const rows = [...r.rows].sort((a, b) => a.scenario_rank - b.scenario_rank);
  const nameOf = (x) => { const s = S.result.strategies.find((q) => q.id === x.id); return s ? stratName(s) : x.name; };
  $("#rankList").innerHTML = rows.map((x) => { const mv = x.base_rank - x.scenario_rank; const drop = Math.round(x.scenario_total - x.base_total);
    return `<div class="rank-item"><span class="pos">${x.scenario_rank}</span><div style="flex:1"><b>${esc(nameOf(x))}</b> ${mv > 0 ? `<span class="down">▲${mv}</span>` : mv < 0 ? `<span class="up">▼${-mv}</span>` : ""}
      <div class="small muted">${esc(t("wi_score", { a: Math.round(x.base_total), b: Math.round(x.scenario_total) }))} (${drop >= 0 ? "+" : ""}${drop})</div><div class="bar"><i style="width:${Math.max(0, Math.min(100, x.scenario_total))}%"></i></div></div></div>`; }).join("");
  chart("chWhatIf", { type: "bar", data: { labels: r.rows.map(nameOf), datasets: [{ label: t("today"), data: r.rows.map((x) => x.base_total), backgroundColor: "#c9b8a6" }, { label: t("scenario"), data: r.rows.map((x) => x.scenario_total), backgroundColor: "#2f6b3a" }] }, options: { plugins: { legend: { position: "bottom" } }, scales: { y: { min: 0, max: 100 } } } });
  if (r.stress) chart("chStressShift", { type: "line", data: { labels: months(), datasets: [{ label: t("today"), data: r.stress.base.map((v) => Math.round(v * 100)), borderColor: "#b9ab9c" }, { label: t("scenario"), data: r.stress.scenario.map((v) => Math.round(v * 100)), borderColor: "#d9603b" }] }, options: { plugins: { legend: { position: "bottom" } } } });
  $("#whatifResults").scrollIntoView({ behavior: "smooth" });
}

/* =============================================================== learn */
const GLOSS = ["et", "sm", "ndvi", "frost", "wb", "grace", "satground", "nfix", "cover", "deep", "drought", "pest", "eco", "gedi"];
function renderLearn() {
  const p = S.profile;
  $("#trustList").innerHTML = ["trust_1", "trust_2", "trust_3", "trust_4"].map((k) => `<li>${esc(t(k))}</li>`).join("");
  $("#glossary").innerHTML = GLOSS.map((k) => `<div class="card glossary-card"><h4>${esc(t("gl_" + k))}</h4><p class="small">${esc(t("gl_" + k + "_d"))}</p></div>`).join("");
  if (!p) return;
  const order = ["power", "gpm", "smap", "ndvi", "et", "grace", "landsat", "ecostress", "gedi", "srtm", "soil"];
  $("#sourcesTable").innerHTML = `<tr><th>${esc(t("dataset"))}</th><th>${esc(t("used_for"))}</th><th>${esc(t("resolution"))}</th><th>${esc(t("status"))}</th></tr>` +
    order.filter((k) => p.layers[k]).map((k) => { const L0 = p.layers[k]; const st = L0.status || (L0.available ? "done" : "off");
      return `<tr><td>${esc(L0.label)}</td><td class="small">${esc(t("use_" + k))}</td><td>${esc(L0.resolution || "")}</td><td><span class="status-dot ${esc(st)}"></span>${esc(t("status_" + st))}</td></tr>`; }).join("");
  const ag = p.agreement.rain;
  $("#uncertList").innerHTML = [t("unc_record", { years: p.record }),
    ag ? t("unc_rain", { r: ag.r, bias: ag.bias_pct, v: t("verdict_" + ag.verdict) }) : t("unc_norain"),
    t("unc_scale"), t("unc_range"), t("unc_ai"), t("unc_local")].map((x) => `<li>${esc(x)}</li>`).join("");
  $("#methodList").innerHTML = ["NASA POWER daily weather (35 y) → FAO-56 Penman-Monteith ET₀, water balance, heat, frost, heavy rain, onset (Mann-Kendall + Sen trends).",
    "All layers harmonised to one monthly, field-centred series with a resolution tag (SRTM 30 m … GRACE ~300 km).",
    "Crop fit per sowing month = temperature × frost × heat at flowering × water (stored soil water, irrigation share) × waterlogging × pH.",
    "Beam search over sowing opportunities → thousands of 2-year rotations; 9 transparent scores; farmer weights; every year must feed the family; the staple stays in its main season.",
    "Robustness: each plan re-scored in every k-means 'kind of year' → score range. Confidence from source agreement, record length, new crops, climate limits, ECOSTRESS and soil test.",
    "AI: Gaussian-mixture season detection vs fixed rule; monotonic gradient boosting stress model vs ridge / random forest / boosting on a time split; permutation importance.",
    "Not modelled: prices, local pests, labour, land tenure, varieties. The farmer and extension officer decide."].map((x) => `<li>${esc(x)}</li>`).join("");
}
$("#gaugeFile").onchange = async (e) => {
  const file = e.target.files[0]; if (!file || !S.field) return;
  const fd = new FormData(); fd.append("file", file); $("#gaugeResult").textContent = t("working");
  try {
    const res = await fetch(`/api/sites/${S.field.id}/gauge`, { method: "POST", body: fd }); const r = await res.json();
    if (!res.ok) throw new Error(r.detail || res.statusText);
    $("#gaugeResult").textContent = t("gauge_result", { n: r.overlap_months, bias: r.bias_before_pct, r: r.corr, before: r.rmse_before_mm, after: r.rmse_after_mm, mm: r.corrected_annual_mm, nasa: r.nasa_annual_mm });
  } catch (err) { $("#gaugeResult").textContent = err.message; }
};

/* =============================================================== boot */
async function init() {
  S.lang = store.get("fw_lang", (navigator.language || "en").slice(0, 2));
  if (!window.I18N[S.lang]) S.lang = "en";
  setView(store.get("fw_view", "farmer")); applyLang();
  initStartMap(); renderLearn();
  try {
    const [crops, refs, health] = await Promise.all([api("/api/crops"), api("/api/reference-sites"), api("/api/health")]);
    S.crops = crops; crops.forEach((c) => (S.cropMap[c.id] = c)); S.refs = refs; S.health = health;
  } catch (err) { modal(`<h3>${esc(t("err_start"))}</h3><p>${esc(err.message)}</p>`); }
  renderStartLists();
  if ("serviceWorker" in navigator) navigator.serviceWorker.register("/sw.js").catch(() => {});
  await route();
}
init();
