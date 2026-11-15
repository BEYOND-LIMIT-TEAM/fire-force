/* Contenus construits en JavaScript : étapes de la mission (partagées), page About, équipe. */
import { t } from "./i18n.js";
import { TEAM } from "./team.js";

const esc = (s) => String(s).replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));

const ICONS = [
  '<svg viewBox="0 0 48 48"><path d="M24 24 33 15M14 20l6 6M22 28l-6-6M28 14l6 6M30 22l-6 6"/><rect x="8" y="22" width="12" height="7" rx="1.5" transform="rotate(-45 14 25)"/><rect x="28" y="9" width="12" height="7" rx="1.5" transform="rotate(-45 34 12.5)"/><circle cx="24" cy="24" r="3.5"/><path d="M10 40c6-1 11-5 14-10"/></svg>',
  '<svg viewBox="0 0 48 48"><path d="M6 10h36L28 26v12l-8 4V26z"/><path d="M12 6h24" opacity=".5"/></svg>',
  '<svg viewBox="0 0 48 48"><path d="M6 40V8M6 40h38"/><path d="M12 32l8-9 7 5 9-14"/><circle cx="20" cy="23" r="2"/><circle cx="27" cy="28" r="2"/><circle cx="36" cy="14" r="2"/></svg>',
  '<svg viewBox="0 0 48 48"><path d="M24 44s14-12 14-23a14 14 0 0 0-28 0c0 11 14 23 14 23z"/><circle cx="24" cy="21" r="5"/><path d="M4 44h40" opacity=".5"/></svg>',
];

export function pipeline() {
  return `<ol class="pipe">${t("pipe").map(([h, d], i) => `
    <li><span class="pipe-ico" aria-hidden="true">${ICONS[i]}</span>
      <span class="pipe-n" aria-hidden="true">${String(i + 1).padStart(2, "0")}</span>
      <h3>${esc(h)}</h3><p>${esc(d)}</p></li>`).join("")}</ol>`;
}

export function missionSection() {
  return `<div class="wrap">
    <h2 class="sec-title">${esc(t("mis.title"))}</h2>
    <p class="sec-lead">${esc(t("mis.lead"))}</p>
    ${pipeline()}
    <p class="note">${esc(t("about.note"))}</p>
    <div class="actions inline"><a class="cta primary" href="/app" data-link data-warp>${esc(t("btn.start"))}</a>
    <a class="cta" href="/about" data-link>${esc(t("btn.about"))}</a></div></div>`;
}

export function aboutPage() {
  const goals = t("about.goals");
  return `
  <header class="l-top solid">
    <a class="mini-brand" href="/" data-link aria-label="Fire Force">${FLAME}<span>FIRE FORCE</span></a>
    <nav><button class="langbtn" type="button" data-lang>${esc(t("nav.lang"))}</button>
    <a class="cta small" href="/app" data-link data-warp>${esc(t("btn.start"))}</a></nav>
  </header>
  <main class="about">
    <section class="wrap about-hero">
      <h1 tabindex="-1" data-focus>${esc(t("about.title"))}</h1>
      <p class="lede">${esc(t("about.sub"))}</p>
    </section>
    <section class="wrap two-col">
      <article class="panel"><h2>${esc(t("about.pTitle"))}</h2><p>${esc(t("about.p"))}</p></article>
      <article class="panel"><h2>${esc(t("about.sTitle"))}</h2><p>${esc(t("about.s"))}</p></article>
    </section>
    <section class="wrap">
      <article class="panel goals"><h2>${esc(t("about.goalsTitle"))}</h2>
        <ul>${goals.map((g) => `<li>${esc(g)}</li>`).join("")}</ul></article>
    </section>
    <section class="wrap">
      <h2 class="sec-title">${esc(t("about.howTitle"))}</h2>
      ${pipeline()}
      <p class="note">${esc(t("about.note"))}</p>
    </section>
    <section class="wrap team">
      <h2 class="sec-title">${esc(t("team.title"))}</h2>
      <div class="team-name">${esc(TEAM.name)}</div>
      <p class="sec-lead">${esc(t("team.line"))}</p>
    </section>
    <section class="wrap back"><a class="cta" href="/" data-link>← ${esc(t("btn.back"))}</a>
      <a class="cta primary" href="/app" data-link data-warp>${esc(t("btn.start"))}</a></section>
    <footer class="wrap credits"><p>${esc(t("credits"))}</p></footer>
  </main>`;
}

export const FLAME = '<svg class="flame" viewBox="0 0 24 24" aria-hidden="true"><path d="M12 1.5c.8 4.2 5.6 6.4 5.6 11.8a5.6 5.6 0 0 1-11.2 0c0-2.2 1-3.7 2.3-4.9.1 2 .9 3.2 2 3.7C10.2 8.7 10.4 5 12 1.5z"/></svg>';
