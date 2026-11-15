/* Page d'accueil : globe, séquence d'ouverture, passage à la plateforme. */
import { Globe } from "./globe.js";
import { apply, t } from "./i18n.js";
import { missionSection } from "./pages.js";

const reduced = matchMedia("(prefers-reduced-motion: reduce)").matches;
let globe = null, landLoaded = false, hotLoaded = false;

async function loadLand() {
  if (landLoaded) return; landLoaded = true;
  try { const r = await fetch("/static/vendor/world-land.json"); if (r.ok) globe.setLand(await r.json()); } catch (e) { /* le globe reste lisible sans continents */ }
}
function loadHot() {
  if (hotLoaded) return; hotLoaded = true;
  const go = async () => {
    try {
      const r = await fetch("/api/hotspots?n=450"); if (!r.ok) return;
      const d = await r.json(); if (!d.lon || !d.lon.length) return;
      globe.setHot(d.lon.map((lon, i) => ({ lon, lat: d.lat[i], v: d.v[i] })));
      document.getElementById("hot-cap").hidden = false;
    } catch (e) { /* hors ligne ou base absente : pas de points, pas d'erreur */ }
  };
  (window.requestIdleCallback || ((f) => setTimeout(f, 1200)))(go, { timeout: 4000 });
}

export function renderStatic() {
  const root = document.getElementById("view-landing");
  apply(root);
  root.querySelector("#mission-body").innerHTML = missionSection();
}

export function enter() {
  const root = document.getElementById("view-landing");
  renderStatic();
  if (!globe) {
    globe = new Globe(document.getElementById("globe"), { reduced });
    root.querySelector("[data-skip]").addEventListener("click", skip);
    addEventListener("keydown", (e) => { if (e.key === "Escape" && !root.hidden && !root.classList.contains("done")) skip(); });
    root.querySelector("[data-explore]").addEventListener("click", () => document.getElementById("mission").scrollIntoView({ behavior: reduced ? "auto" : "smooth" }));
    loadLand(); loadHot();
  }
  globe.resize();
  if (reduced) root.classList.add("done", "go"); else if (!root.classList.contains("go")) requestAnimationFrame(() => root.classList.add("go"));
  globe.start();
  if (!reduced && !root.classList.contains("done")) setTimeout(() => root.classList.add("done"), 5600);
}
export function leave() { if (globe) globe.stop(); }
export function resize() { if (globe) globe.resize(); }

function skip() {
  const root = document.getElementById("view-landing");
  root.classList.add("done", "skipped"); if (globe) globe.finishIntro();
}

/** Transition « saut en hyperespace » vers un lien marqué data-warp. */
export function warp(go) {
  const w = document.getElementById("warp");
  if (reduced || !w) { go(); return; }
  w.classList.remove("out"); w.classList.add("on");
  setTimeout(() => { go(); w.classList.add("out"); setTimeout(() => w.classList.remove("on", "out"), 600); }, 520);
}
