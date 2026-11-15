/* Routeur minimal par chemins (/, /about, /app). Le dashboard n'est démarré qu'à sa première visite. */
import * as landing from "./landing.js";
import { aboutPage } from "./pages.js";
import { apply, getLang, setLang, t } from "./i18n.js";

const VIEWS = { "/": "landing", "/about": "about", "/app": "app" };
const TITLE_APP = document.title;
let current = null;

const $ = (id) => document.getElementById(id);
const norm = (p) => (p.length > 1 ? p.replace(/\/+$/, "") : p) || "/";

function show(name) {
  for (const v of ["landing", "about", "app"]) $(`view-${v}`).hidden = v !== name;
  document.documentElement.dataset.view = name;
  document.documentElement.lang = name === "app" ? "fr" : getLang();
}

async function render(path) {
  const name = VIEWS[norm(path)] || "landing";
  if (current === "landing" && name !== "landing") landing.leave();
  show(name);
  if (name === "landing") { document.title = t("title.landing"); landing.enter(); }
  else if (name === "about") { document.title = t("title.about"); const el = $("view-about"); el.innerHTML = aboutPage(); }
  else { document.title = TITLE_APP; const app = await import("/static/js/app.js"); await app.start(); app.onShow(); }
  current = name;
  window.scrollTo(0, 0);
  const f = $(`view-${name}`).querySelector("[data-focus]"); if (f) f.focus({ preventScroll: true });
}

export function navigate(path, { replace = false } = {}) {
  if (norm(location.pathname) === norm(path) && current) return;
  history[replace ? "replaceState" : "pushState"](null, "", path);
  return render(path);
}

document.addEventListener("click", (e) => {
  const lang = e.target.closest("[data-lang]");
  if (lang) { setLang(getLang() === "en" ? "fr" : "en"); render(location.pathname); return; }
  const a = e.target.closest("a[data-link]");
  if (!a || e.defaultPrevented || e.button !== 0 || e.metaKey || e.ctrlKey || e.shiftKey || e.altKey) return;
  e.preventDefault();
  const href = a.getAttribute("href");
  if (a.hasAttribute("data-warp")) landing.warp(() => navigate(href)); else navigate(href);
});
addEventListener("popstate", () => render(location.pathname));
addEventListener("resize", () => landing.resize());
render(location.pathname);
