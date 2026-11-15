import { n0, n1, n2, times, fmtDate, fmtRange, fmtLong, parseISO, iso, addDays, ordinal, esc, downloadCSV, LEVEL_LABEL, STATUS_LABEL } from "./util.js";
import { FireMap } from "./map.js";
import { renderCalendar, renderWeekly, renderWindow, renderSeason, renderSensors, resizeAll } from "./charts.js";

const $ = (id) => document.getElementById(id);
const PRESETS = [
  { n: "Cameroun", b: [8.4, 1.6, 16.2, 13.1] },
  { n: "Nigeria", b: [2.6, 4.2, 14.7, 13.9] },
  { n: "Sahel", b: [-17.5, 11, 25, 17.5] },
  { n: "Bassin du Congo", b: [12, -6, 30, 5] },
  { n: "RD Congo", b: [12, -13.5, 31.5, 5.5] },
  { n: "Angola – Zambie", b: [12, -18, 34, -8] },
  { n: "Mozambique – Zimbabwe", b: [26, -27, 41, -13] },
  { n: "Madagascar", b: [43, -26, 51, -11.5] },
  { n: "Corne de l'Afrique", b: [34, 2, 51, 15] },
];
const AFRICA = { type: "bbox", bbox: [-18, -35, 52, 37] };

const S = { hist: [], meta: null, cells: null, map: null, zone: null, period: null, params: null, result: null, busy: false, seq: 0 };

/* ------------------------------------------------------------------ démarrage */
async function boot() {
  try {
    const [meta, cells] = await Promise.all([fetch("/api/meta").then(ok), fetch("/api/cells").then(ok)]);
    S.meta = meta; S.cells = cells; S.params = { ...meta.defaults };
  } catch (e) {
    $("verdict").setAttribute("aria-busy", "false");
    $("verdict").innerHTML = `<h1>Le serveur de données ne répond pas.</h1><p class="lede">Vérifiez que l'API est lancée (uvicorn app.main:app) et que la base fireforce.duckdb existe, puis rechargez la page.</p>`;
    return;
  }
  const m = S.meta;
  $("badge").hidden = false;
  if (m.dataset === "demo") { $("badge").textContent = "Données de démonstration (synthétiques)"; $("badge").classList.add("demo"); }
  else $("badge").textContent = `NASA FIRMS · ${m.first_day.slice(0, 4)}–${m.last_day.slice(0, 4)}`;

  S.map = new FireMap($("map"), $("map-tip"), cells2arrays(S.cells), (z) => { setZone(z, false); run(); });
  S.map.loadBorders("/static/vendor/africa.geojson");
  buildPresets(); buildYears(); bindParams(); bindUI();

  const h = readHash();
  S.period = h?.period || quickPeriod("last365");
  S.zone = h?.zone || { type: "bbox", bbox: PRESETS[0].b };
  syncPeriodInputs(); S.map.map.invalidateSize(); setZone(S.zone, true);
  await run();
}
const ok = (r) => { if (!r.ok) throw new Error(r.status); return r.json(); };
function cells2arrays(c) { return { ids: c.ids, lon: Float32Array.from(c.lon), lat: Float32Array.from(c.lat), corners: c.corners.map((a) => Float32Array.from(a)) }; }

/* ------------------------------------------------------------------ zone & période */
function setZone(z, fit = true, noPush = false) {
    S.zone = z; S.map.showZone(z, fit); $("go").disabled = false;
  const b = zoneBounds(z);
  if (z.type === "bbox") { $("c-w").value = round(z.bbox[0]); $("c-s").value = round(z.bbox[1]); $("c-e").value = round(z.bbox[2]); $("c-n").value = round(z.bbox[3]); }
  document.querySelectorAll("#presets .chip").forEach((c) => c.classList.toggle("on", z.type === "bbox" && c.dataset.b === z.bbox.map(round).join(",")));
  $("zone-summary").textContent = z.type === "bbox"
    ? `Rectangle de ${round(b[2] - b[0])}° sur ${round(b[3] - b[1])}°` : `Polygone de ${z.coordinates.length} sommets`;
}
const round = (v) => Math.round(v * 100) / 100;
const zoneBounds = (z) => z.type === "bbox" ? z.bbox : [Math.min(...z.coordinates.map((p) => p[0])), Math.min(...z.coordinates.map((p) => p[1])), Math.max(...z.coordinates.map((p) => p[0])), Math.max(...z.coordinates.map((p) => p[1]))];

function quickPeriod(kind) {
  const end = S.meta.last_day;
  if (kind === "last90") return { start: addDays(end, -89), end };
  return { start: addDays(end, -364), end };
}
function syncPeriodInputs() { $("d-start").value = S.period.start; $("d-end").value = S.period.end; $("d-start").min = $("d-end").min = S.meta.first_day; $("d-start").max = $("d-end").max = S.meta.last_day; }

function buildPresets() {
  $("presets").innerHTML = PRESETS.map((p) => `<button type="button" class="chip" data-b="${p.b.map(round).join(",")}">${esc(p.n)}</button>`).join("");
  $("presets").addEventListener("click", (e) => {
    const c = e.target.closest(".chip"); if (!c) return;
    setZone({ type: "bbox", bbox: c.dataset.b.split(",").map(Number) }, true); run();
  });
}
function buildYears() {
  const y0 = +S.meta.first_day.slice(0, 4), y1 = +S.meta.last_day.slice(0, 4);
  $("q-year").innerHTML = `<option value="">…</option>` + Array.from({ length: y1 - y0 + 1 }, (_, i) => y1 - i).map((y) => `<option>${y}</option>`).join("");
}

const PARAM_DEF = [["p-qe", "o-qe", "q_eleve", (v) => `${v}ᵉ`], ["p-qc", "o-qc", "q_critique", (v) => `${v}ᵉ`], ["p-re", "o-re", "ratio_eleve", (v) => `× ${n2(+v)}`], ["p-rc", "o-rc", "ratio_critique", (v) => `× ${n2(+v)}`], ["p-pl", "o-pl", "plancher", (v) => v]];
function bindParams() {
  const paint = () => PARAM_DEF.forEach(([i, o, k, f]) => { $(i).value = S.params[k]; $(o).textContent = f(S.params[k]); });
  PARAM_DEF.forEach(([i, o, k, f]) => $(i).addEventListener("input", () => { S.params[k] = +$(i).value; $(o).textContent = f($(i).value); }));
  $("reset-params").addEventListener("click", () => { S.params = { ...S.meta.defaults }; paint(); });
  paint();
}

function bindUI() {
  $("form").addEventListener("submit", (e) => { e.preventDefault(); readPeriod(); run(); });
  $("draw-rect").addEventListener("click", () => S.map.startDraw("rect"));
  $("draw-poly").addEventListener("click", () => S.map.startDraw("poly"));
  $("draw-africa").addEventListener("click", () => { S.map.cancelDraw(); setZone(AFRICA, true); run(); });
  $("apply-coords").addEventListener("click", () => {
    const b = ["c-w", "c-s", "c-e", "c-n"].map((i) => parseFloat($(i).value));
    if (b.some(Number.isNaN)) return showError("Renseignez les quatre coordonnées (ouest, sud, est, nord).");
    if (!(b[0] < b[2] && b[1] < b[3])) return showError("L'ouest doit être inférieur à l'est, et le sud inférieur au nord.");
    setZone({ type: "bbox", bbox: b }, true); run();
  });
  document.querySelectorAll("[data-q]").forEach((b) => b.addEventListener("click", () => { S.period = quickPeriod(b.dataset.q); syncPeriodInputs(); run(); }));
  $("q-year").addEventListener("change", (e) => {
    const y = e.target.value; if (!y) return;
    S.period = { start: y + "-01-01" < S.meta.first_day ? S.meta.first_day : y + "-01-01", end: y + "-12-31" > S.meta.last_day ? S.meta.last_day : y + "-12-31" };
    syncPeriodInputs(); e.target.value = ""; run();
  });
  ["d-start", "d-end"].forEach((id) => $(id).addEventListener("change", () => { if ($("d-start").value && $("d-end").value) run(); }));
  $("osm-toggle").addEventListener("change", (e) => S.map.setBasemap(e.target.checked));
  $("btn-method").addEventListener("click", () => $("method").showModal());
  $("dl-days").addEventListener("click", () => exportDays());
  $("dl-weeks").addEventListener("click", () => exportWeeks());
  $("print").addEventListener("click", () => window.print());
  const ex = document.querySelector(".exports");
  const link = document.createElement("button"); link.type = "button"; link.className = "btn small"; link.textContent = "Copier le lien";
  link.addEventListener("click", async () => { try { await navigator.clipboard.writeText(location.href); link.textContent = "Lien copié"; } catch { link.textContent = "Copie impossible"; } setTimeout(() => (link.textContent = "Copier le lien"), 2000); });
  ex.prepend(link);
  new ResizeObserver(() => { clearTimeout(S.rt); S.rt = setTimeout(() => { if (S.result && !S.result.empty) renderCalendar(S.result, $("cal-legend")); resizeAll(); }, 150); }).observe($("chart-weekly"));
  matchMedia("(prefers-color-scheme: dark)").addEventListener("change", () => { S.map.restyle(); if (S.zone) S.map.showZone(S.zone, false); if (S.result) renderAll(S.result); });
}
function readPeriod() {
  const a = $("d-start").value, b = $("d-end").value;
  if (a && b) S.period = { start: a, end: b };
}

/* ------------------------------------------------------------------ analyse */
function showError(msg) { const e = $("error"); e.textContent = msg; e.hidden = !msg; }

async function run() {
  readPeriod(); showError("");
  if (!S.zone) return showError("Choisissez d'abord une zone sur la carte.");
  if (S.period.end < S.period.start) return showError("La date de fin précède la date de début.");
  const seq = ++S.seq;
  $("go").disabled = true; $("go").textContent = "Analyse en cours…";
  $("verdict").setAttribute("aria-busy", "true");
  writeHash();
  const body = { zone: S.zone.type === "bbox" ? { type: "bbox", bbox: S.zone.bbox } : { type: "polygon", coordinates: S.zone.coordinates }, ...S.period, ...S.params };
  try {
    const [res, map] = await Promise.all([
      fetch("/api/analyze", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) }),
      fetch(`/api/map?start=${S.period.start}&end=${S.period.end}`).then(ok),
    ]);
    if (seq !== S.seq) return;
    if (!res.ok) { const d = await res.json().catch(() => ({})); throw new Error(typeof d.detail === "string" ? d.detail : "Requête invalide."); }
    S.result = await res.json(); S.focus = null;
    S.map.setValues(map.values);
    renderAll(S.result);
  } catch (e) {
    if (seq === S.seq) showError(`L'analyse n'a pas abouti : ${e.message}`);
  } finally {
    if (seq === S.seq) { $("go").disabled = false; $("go").textContent = "Analyser cette zone"; $("verdict").setAttribute("aria-busy", "false"); }
  }
}

function renderAll(r) {
  renderVerdict(r); renderMapMeta(r);
  const hidden = r.empty;
  ["sec-calendar", "sec-weekly", "sec-episodes", "sec-window", "sec-season", "sec-sensors"].forEach((id) => ($(id).closest(".two") || $(id)).hidden = hidden);
  if (hidden) return;
  renderCalendar(r, $("cal-legend")); renderWeekly(r); renderEpisodes(r); renderWindow(r); renderSeason(r); renderSensors(r, S.params);
  renderFoot(r);
  requestAnimationFrame(resizeAll);
}

function renderMapMeta(r) {
  $("map-sub").textContent = `Détections harmonisées du ${fmtRange(r.period.start, r.period.end)}, par cellule de ${S.meta.grid_km} km. La zone choisie est cerclée.`;
  $("map-legend").innerHTML = `<span>peu</span><span class="ramp"></span><span>beaucoup</span>`;
  const z = r.zone;
  $("zone-summary").innerHTML = r.empty ? "Cette zone ne contient aucune cellule avec des feux détectés."
    : `<strong>${n0(z.n_cells)} cellules</strong> de ${S.meta.grid_km} km, soit environ ${n0(z.cells_area_km2)} km².${z.approximate ? " Zone plus petite qu'une cellule : on utilise la cellule qui la contient." : ""}`;
}

function levelOf(r) { return r.episodes.some((e) => e.level === "critique") ? "critique" : r.episodes.length ? "eleve" : "normal"; }

function renderVerdict(r) {
  const el = $("verdict");
  if (r.empty) {
    el.dataset.level = "normal";
    el.innerHTML = `<h1>Aucun feu détecté dans cette zone.</h1><p class="lede">La zone ne recouvre aucune cellule de ${S.meta.grid_km} km avec des détections (mer, désert, ou zone trop petite). Choisissez une zone plus grande ou plus au sud ou au nord.</p>`;
    return;
  }
  const k = r.kpi, lvl = levelOf(r), top = r.episodes[0];
  el.dataset.level = lvl;
  const nCrit = r.episodes.filter((e) => e.level === "critique").length;
  const per = fmtRange(r.period.start, r.period.end);
  let h;
  if (lvl === "critique") h = nCrit === 1 ? `Une période critique du ${fmtRange(top.start, top.end)}, ${times(top.ratio)} la normale.` : `${nCrit} périodes critiques, dont la plus forte du ${fmtRange(top.start, top.end)} (${times(top.ratio)} la normale).`;
  else if (lvl === "eleve") h = `Activité élevée du ${fmtRange(top.start, top.end)}, ${times(top.ratio)} la normale.`;
  else if (k.weeks_assessed === 0) h = `Pas assez d'historique pour juger cette période.`;
  else h = `Rien d'inhabituel : la zone reste dans ses variations habituelles.`;

  const parts = [`${n0(k.total)} détections de feux actifs du ${per}.`];
  if (k.ratio != null) {
    const y0 = Math.min(...r.same_window.map((x) => x.year));
    parts.push(k.rank === 1 ? `Ces dates n'ont jamais été aussi actives depuis ${y0}.` : k.ratio >= 1.15 ? `Ces dates sont plus actives que d'habitude (${ordinal(k.rank)} sur ${k.rank_of} ans).` : k.ratio <= 0.85 ? `Ces dates sont plus calmes que d'habitude.` : `Ces dates sont proches de la normale (${ordinal(k.rank)} sur ${k.rank_of} ans).`);
  } else parts.push("Il manque des années de comparaison pour situer cette période.");
  if (top) parts.push(top.status === "confirmee" ? `Signalé indépendamment par ${top.sensors_flagging} capteurs.` : top.status === "isolee" ? `Signalé par un seul capteur : à vérifier avant d'agir.` : "");
  if (k.days_gap > 0) parts.push(`${k.days_gap} jour${k.days_gap > 1 ? "s" : ""} sans donnée satellite ne ${k.days_gap > 1 ? "sont" : "est"} pas compté${k.days_gap > 1 ? "s" : ""}.`);

  const kp = (t, v, s) => `<div class="kpi"><dt>${t}</dt><dd>${v}${s ? `<small>${s}</small>` : ""}</dd></div>`;
  el.innerHTML = `<h1>${esc(h)}</h1><p class="lede">${esc(parts.filter(Boolean).join(" "))}</p>
  <dl class="kpis">
    ${kp("Détections", n0(k.total), `${n1(k.density_per_1000km2)} pour 1 000 km²`)}
    ${kp("Face à la normale", k.ratio != null ? times(k.ratio) : "—", k.expected != null ? `normale : ${n0(k.expected)} sur ces dates` : "historique insuffisant")}
    ${kp("Jours avec feu", `${k.days_with_fire}<span style="font-size:16px;color:var(--ink-2)"> / ${k.days_covered}</span>`, `pic de ${n0(k.peak_value)} le ${k.peak_day ? fmtDate(k.peak_day) : "—"}`)}
    ${kp("Semaines à surveiller", `${k.weeks_critical} <span style="font-size:16px;color:var(--ink-2)">critique${k.weeks_critical > 1 ? "s" : ""}</span>`, `${k.weeks_high} élevée${k.weeks_high > 1 ? "s" : ""} sur ${k.weeks_assessed} évaluées`)}
  </dl>
  `;
}

function renderEpisodes(r) {
  const eps = r.episodes;
  $("ep-sub").textContent = eps.length ? `${eps.length} période${eps.length > 1 ? "s" : ""} élevée${eps.length > 1 ? "s" : ""} ou critique${eps.length > 1 ? "s" : ""}, de la plus grave à la moins grave. Cliquez une ligne pour la repérer sur le graphique, cliquez-la de nouveau pour tout revoir.`
    : "Aucune semaine ne dépasse les seuils sur cette période.";
  if (!eps.length) { $("episodes").innerHTML = `<div class="empty">Aucune période élevée ni critique. Vous pouvez élargir la période ou baisser les seuils dans les réglages de sensibilité.</div>`; return; }
  const icon = (l) => l === "critique" ? `<svg viewBox="0 0 12 12" aria-hidden="true"><path d="M6 0.5 11.5 11H0.5z"/></svg>` : `<svg viewBox="0 0 12 12" aria-hidden="true"><circle cx="6" cy="6" r="5"/></svg>`;
  const conf = (e) => {
    const label = e.status === "confirmee" ? `Confirmée (${e.sensors_flagging} capteurs sur ${e.sensors_evaluated})` : e.status === "isolee" ? `Un seul capteur sur ${e.sensors_evaluated}` : e.status === "partielle" ? "Confirmée en partie" : "Non vérifiable";
    return `<span class="conf ${e.status}"><i></i>${label}</span>`;
  };
  $("episodes").innerHTML = `<div class="table-wrap"><table><thead><tr><th>Niveau</th><th>Période</th><th>Intensité</th><th>Observé / normal</th><th>Capteurs</th></tr></thead><tbody>` +
    eps.map((e, i) => `<tr class="ep" data-i="${i}" tabindex="0"><td><span class="lvl ${e.level}">${icon(e.level)}${LEVEL_LABEL[e.level]}</span></td>
      <td><div class="big">${fmtRange(e.start, e.end)}</div><div class="muted">${e.weeks} semaine${e.weeks > 1 ? "s" : ""}</div></td>
      <td><div class="big">${times(e.ratio)}</div><div class="muted">pic ${times(e.peak_ratio)}${e.record ? " · ★ record" : ""}</div></td>
      <td>${n0(e.observed)} <span class="muted">/ ${n0(e.expected)}</span></td><td>${conf(e)}</td></tr>`).join("") + `</tbody></table></div>`;
  $("episodes").querySelectorAll("tr.ep").forEach((tr) => {
    const act = () => focusEpisode(+tr.dataset.i);
    tr.addEventListener("click", act); tr.addEventListener("keydown", (ev) => { if (ev.key === "Enter" || ev.key === " ") { ev.preventDefault(); act(); } });
  });
}
function focusEpisode(i) {
  const e = S.result.episodes[i], W = S.result.weeks;
  const again = S.focus === i;   // un second clic sur la même ligne revient à la vue d'ensemble
  S.focus = again ? null : i;
  document.querySelectorAll("tr.ep").forEach((t) => t.classList.toggle("on", !again && +t.dataset.i === i));
  const a = W.findIndex((w) => w.end >= e.start), b = W.length - 1 - [...W].reverse().findIndex((w) => w.start <= e.end);
  renderWeekly(S.result, !again && a >= 0 && b >= 0 ? [a, b] : null);
  $("sec-weekly").scrollIntoView({ behavior: matchMedia("(prefers-reduced-motion: reduce)").matches ? "auto" : "smooth", block: "center" });
}

function renderFoot(r) {
  const m = S.meta;
  $("win-sub").textContent = `Total du ${fmtRange(r.period.start, r.period.end)} chaque année. Le trait pointillé est la moyenne des autres années.`;
  const few = r.same_window.length < 2;
  $("chart-window").hidden = few;
  if (few) $("win-sub").textContent = "Cette période est trop longue pour être comparée aux mêmes dates des autres années. Choisissez une période d'un an ou moins.";
  const t = getComputedStyle(document.documentElement), c = (v) => t.getPropertyValue(v).trim();
  $("weekly-legend").innerHTML = `<span><i class="sw" style="background:${c("--lvl-normal")};opacity:.6"></i>Normal</span><span><i class="sw" style="background:${c("--lvl-high")}"></i>Élevé</span><span><i class="sw" style="background:${c("--lvl-crit")}"></i>Critique</span><span>★ semaine critique, la plus forte jamais vue pour cette semaine</span><span class="rule"><strong>Critique</strong> : au-dessus du ${r.params.q_critique}ᵉ centile des mêmes semaines des autres années et au moins ×\u00a0${n2(r.params.ratio_critique)} la normale. <strong>Élevé</strong> : au-dessus du ${r.params.q_eleve}ᵉ centile et au moins ×\u00a0${n2(r.params.ratio_eleve)}.</span><span><i class="sw" style="background:repeating-linear-gradient(135deg,${c("--lvl-normal")} 0 2px,transparent 2px 5px);border:1px solid ${c("--lvl-normal")}"></i>Pas assez de données</span>`;
  $("foot-text").textContent = (m.dataset === "demo" ? "Données de démonstration générées pour tester l'application : elles ne décrivent aucun feu réel. " : "Source : NASA FIRMS (MODIS et VIIRS). ") +
    `Série harmonisée sur une grille de ${m.grid_km} km, de ${fmtLong(m.first_day)} à ${fmtLong(m.last_day)}. Analyse calculée en ${r.elapsed_ms ?? "—"} ms par requêtes SQL sur la base agrégée.`;
}

/* ------------------------------------------------------------------ exports & lien */
function exportDays() {
  const r = S.result; if (!r || r.empty) return;
  downloadCSV(`feux_jours_${r.period.start}_${r.period.end}.csv`, [["date", "detections_harmonisees", "niveau_semaine", "confirmation"], ...r.calendar.map(([d, v, l, s]) => [d, v, l, s])]);
}
function exportWeeks() {
  const r = S.result; if (!r || r.empty) return;
  downloadCSV(`feux_semaines_${r.period.start}_${r.period.end}.csv`, [["annee", "semaine", "debut", "fin", "observe", "normale", "seuil_eleve", "seuil_critique", "rapport", "niveau", "record", "capteurs_signalant", "capteurs_evalues", "confirmation"],
    ...r.weeks.map((w) => [w.year, w.week + 1, w.start, w.end, w.total, w.expected, w.p_eleve, w.p_critique, w.ratio, w.level, w.record ? 1 : 0, w.n_flag, w.n_eval, w.status])]);
}
function writeHash() {
  const z = S.zone.type === "bbox" ? "b:" + S.zone.bbox.map((v) => round(v)).join(",") : "p:" + S.zone.coordinates.map((p) => p.map((v) => Math.round(v * 1000) / 1000).join(",")).join(";");
  history.replaceState(null, "", `#z=${z}&d=${S.period.start}..${S.period.end}`);
}
function readHash() {
  try {
    const m = location.hash.match(/z=([bp]):([^&]+)&d=(\d{4}-\d{2}-\d{2})\.\.(\d{4}-\d{2}-\d{2})/); if (!m) return null;
    const zone = m[1] === "b" ? { type: "bbox", bbox: m[2].split(",").map(Number) } : { type: "polygon", coordinates: m[2].split(";").map((p) => p.split(",").map(Number)) };
    if (zone.type === "bbox" && zone.bbox.length !== 4) return null;
    return { zone, period: { start: m[3], end: m[4] } };
  } catch { return null; }
}

/* ---- intégration au routeur : démarrage différé, premier affichage de la vue ---- */
let booted = null;
export function start() { if (!booted) booted = boot(); return booted; }
export function onShow() { try { if (S.map) S.map.map.invalidateSize(); resizeAll(); } catch (e) { /* vue pas encore prête */ } }
