export const MOIS = ["janv.", "févr.", "mars", "avr.", "mai", "juin", "juil.", "août", "sept.", "oct.", "nov.", "déc."];
export const MOIS_LONG = ["janvier", "février", "mars", "avril", "mai", "juin", "juillet", "août", "septembre", "octobre", "novembre", "décembre"];
const fix = (t) => t.replace(/[\u202f\u00a0]/g, "\u00a0");
const nf0 = new Intl.NumberFormat("fr-FR", { maximumFractionDigits: 0 });
const nf1 = new Intl.NumberFormat("fr-FR", { maximumFractionDigits: 1 });
const nf2 = new Intl.NumberFormat("fr-FR", { maximumFractionDigits: 2, minimumFractionDigits: 0 });

export const n0 = (v) => (v == null ? "—" : fix(nf0.format(v)));
export const n1 = (v) => (v == null ? "—" : fix(nf1.format(v)));
export const n2 = (v) => (v == null ? "—" : fix(nf2.format(v)));
export const times = (v) => (v == null ? "—" : `× ${nf1.format(v)}`);

/** "2024-08-04" -> Date locale à midi (évite les décalages de fuseau). */
export const parseISO = (s) => { const [y, m, d] = s.split("-").map(Number); return new Date(y, m - 1, d, 12); };
export const iso = (d) => `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
export const addDays = (s, k) => { const d = parseISO(s); d.setDate(d.getDate() + k); return iso(d); };

export function fmtDate(s, withYear = true) {
  const d = parseISO(s);
  return `${d.getDate() === 1 ? "1er" : d.getDate()} ${MOIS[d.getMonth()]}${withYear ? " " + d.getFullYear() : ""}`;
}
export function fmtRange(a, b) {
  const da = parseISO(a), db = parseISO(b);
  if (a === b) return fmtDate(a);
  if (da.getFullYear() === db.getFullYear()) return `${fmtDate(a, false)} au ${fmtDate(b)}`;
  return `${fmtDate(a)} au ${fmtDate(b)}`;
}
export const fmtLong = (s) => { const d = parseISO(s); return `${d.getDate() === 1 ? "1er" : d.getDate()} ${MOIS_LONG[d.getMonth()]} ${d.getFullYear()}`; };
export const ordinal = (n) => (n === 1 ? "1re" : `${n}ᵉ`);

export const css = (name) => getComputedStyle(document.documentElement).getPropertyValue(name).trim();
export const esc = (s) => String(s).replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));

export function downloadCSV(name, rows) {
  const csv = rows.map((r) => r.map((v) => (v == null ? "" : /[",;\n]/.test(String(v)) ? `"${String(v).replace(/"/g, '""')}"` : v)).join(",")).join("\n");
  const url = URL.createObjectURL(new Blob(["﻿" + csv], { type: "text/csv;charset=utf-8" }));
  const a = document.createElement("a"); a.href = url; a.download = name; document.body.appendChild(a); a.click(); a.remove();
  setTimeout(() => URL.revokeObjectURL(url), 2000);
}

export const LEVEL_LABEL = { critique: "Critique", eleve: "Élevé", normal: "Normal", indetermine: "Non évalué" };
export const STATUS_LABEL = {
  confirmee: "Confirmée par plusieurs capteurs", isolee: "Vue par un seul capteur",
  partielle: "Confirmée sur une partie de la période", non_verifiable: "Non vérifiable", aucune: "—",
};
