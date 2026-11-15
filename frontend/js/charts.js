import { css, MOIS, n0, n1, n2, times, fmtDate, fmtRange, fmtLong, parseISO, addDays, LEVEL_LABEL, STATUS_LABEL, esc } from "./util.js";

const inst = {};
function chart(id) {
  if (!inst[id]) { inst[id] = echarts.init(document.getElementById(id), null, { renderer: "canvas" }); }
  return inst[id];
}
export function resizeAll() { Object.values(inst).forEach((c) => c.resize()); }
export function T() {
  return {
    ink: css("--ink"), ink2: css("--ink-2"), line: css("--line"), panel: css("--panel"), accent: css("--accent"),
    normal: css("--lvl-normal"), high: css("--lvl-high"), crit: css("--lvl-crit"),
    ramp: ["--r0", "--r1", "--r2", "--r3", "--r4"].map(css), sens: ["--s1", "--s2", "--s3", "--s4"].map(css),
    font: css("--f-body"), display: css("--f-display"),
  };
}
function weekLabels(W) {
  let prev = null;
  return W.map((w) => { const y = w.start.slice(0, 4), base = fmtDate(w.start, false); const out = y !== prev ? `${base}\n${y}` : base; prev = y; return out; });
}
const short = (v) => (Math.abs(v) >= 1e6 ? n1(v / 1e6) + " M" : Math.abs(v) >= 1000 ? n0(v / 1000) + " k" : v);
const lvlColor = (t, l) => (l === "critique" ? t.crit : l === "eleve" ? t.high : t.normal);
const tipStyle = (t) => ({ backgroundColor: t.panel, borderColor: t.line, textStyle: { color: t.ink, fontFamily: t.font, fontSize: 13 }, extraCssText: "box-shadow:0 6px 24px rgba(0,0,0,.2);border-radius:10px;" });
const SENSOR_NAME = { MODIS: "MODIS", VIIRS_SNPP: "VIIRS S-NPP", VIIRS_N20: "VIIRS NOAA-20", VIIRS_N21: "VIIRS NOAA-21" };
const SYMBOLS = ["circle", "rect", "triangle", "diamond"];

const statusLine = (w) => w.level === "normal" || w.level === "indetermine" ? "" :
  `<br>${w.n_eval >= 2 ? (w.status === "confirmee" ? `Confirmée : ${w.n_flag} capteurs sur ${w.n_eval}` : w.status === "isolee" ? `Vue par ${w.n_flag} capteur sur ${w.n_eval} seulement` : "") : "Non vérifiable (un seul capteur)"}`;

/* ---------------------------------------------------------------- calendrier */
export function renderCalendar(r, legendEl) {
  const t = T(), el = document.getElementById("chart-calendar");
  const ps = r.period.start, pe = r.period.end;
  const y0 = +ps.slice(0, 4), y1 = +pe.slice(0, 4), years = [];
  for (let y = y0; y <= y1; y++) years.push(y);
  const W = el.clientWidth, left = 54, right = 8;
  const ncols = (y) => {
    const a = ps > `${y}-01-01` ? ps : `${y}-01-01`, b = pe < `${y}-12-31` ? pe : `${y}-12-31`;
    const fd = new Date(y, 0, 1).getDay(), da = parseISO(a), days = Math.round((parseISO(b) - da) / 864e5) + 1;
    return Math.ceil((days + ((da.getDay() - fd + 7) % 7)) / 7);
  };
  const nmax = Math.max(...years.map(ncols));
  const cw = Math.max(5, Math.min(30, (W - left - right) / nmax)), ch = Math.max(10, Math.min(24, cw));
  const block = 7 * ch + 38;
  el.style.height = years.length * block + 6 + "px";

  const calendars = [], series = [], heatIdx = [];
  const byYear = Object.fromEntries(years.map((y) => [y, { heat: [], gap: [] }]));
  for (const [d, v, lvl, st] of r.calendar) {
    const y = +d.slice(0, 4);
    if (v == null) byYear[y].gap.push([d, 1]); else byYear[y].heat.push([d, v, lvl, st]);
  }
  const weeksFlag = r.weeks.filter((w) => w.level === "critique" || w.level === "eleve");
  years.forEach((y, i) => {
    const a = ps > `${y}-01-01` ? ps : `${y}-01-01`, b = pe < `${y}-12-31` ? pe : `${y}-12-31`;
    const fd = new Date(y, 0, 1).getDay();
    calendars.push({
      top: i * block + 26, left, cellSize: [cw, ch], range: [a, b], orient: "horizontal",
      itemStyle: { borderWidth: 2, borderColor: t.panel, color: t.ramp[0] }, splitLine: { show: false },
      dayLabel: { show: false, firstDay: fd },
      monthLabel: { nameMap: MOIS, color: t.ink2, fontFamily: t.font, fontSize: 12, margin: 7 },
      yearLabel: { show: true, position: "left", color: t.ink, fontFamily: t.display, fontWeight: 600, fontSize: 15, margin: 12 },
    });
    heatIdx.push(series.length);
    series.push({ type: "heatmap", coordinateSystem: "calendar", calendarIndex: i, data: byYear[y].heat, itemStyle: { borderWidth: 2, borderColor: t.panel }, emphasis: { itemStyle: { borderColor: t.ink, borderWidth: 2 } }, progressive: 0 });
    series.push({
      type: "heatmap", coordinateSystem: "calendar", calendarIndex: i, data: byYear[y].gap, silent: false, name: "Pas de données",
      itemStyle: { color: t.normal, opacity: 0.55, borderWidth: 2, borderColor: t.panel, decal: { symbol: "rect", dashArrayX: [1, 0], dashArrayY: [2, 4], rotation: -Math.PI / 4, color: t.panel } },
    });
    // contours des semaines inhabituelles : un rectangle par tronçon de colonne
    const segs = [];
    for (const w of weeksFlag) {
      if (+w.start.slice(0, 4) !== y) continue;
      const parts = w.week === 51 ? [[w.start, addDays(w.start, 6)], [addDays(w.start, 7), w.end]] : [[w.start, w.end]];
      parts.forEach(([s0, s1], pi) => {
        if (s1 < s0) return;
        const s = s0 < a ? a : s0, e = s1 > b ? b : s1;
        if (e < s) return;
        segs.push({ value: [s, e], w, first: pi === 0 });
      });
    }
    series.push({
      type: "custom", coordinateSystem: "calendar", calendarIndex: i, data: segs, z: 10, name: "Semaines inhabituelles",
      renderItem(params, api) {
        const d = segs[params.dataIndex];
        const p0 = api.coord([d.value[0]]), p1 = api.coord([d.value[1]]);
        const x = p0[0] - cw / 2, yy = p0[1] - ch / 2, h = p1[1] - p0[1] + ch;
        const crit = d.w.level === "critique", conf = d.w.status === "confirmee";
        const kids = [{
          type: "rect", shape: { x: x - 1, y: yy - 1, width: cw + 2, height: h + 2, r: 3 }, style: { fill: "transparent", stroke: t.panel, lineWidth: 3.5 },
        }, {
          type: "rect", shape: { x: x + 0.5, y: yy + 0.5, width: cw - 1, height: h - 1, r: 2 },
          style: { fill: "transparent", stroke: t.ink, lineWidth: crit ? 2.6 : 1.8, lineDash: crit ? null : [4, 3] },
        }];
        if (conf && d.first) kids.push({ type: "circle", shape: { cx: x + cw / 2, cy: yy - 6, r: Math.max(3, Math.min(4.5, cw / 3)) }, style: { fill: t.accent, stroke: t.panel, lineWidth: 1.5 } });
        return { type: "group", children: kids };
      },
    });
  });

  const sc = r.calendar_scale || {};
  const p50 = sc.p50 ?? 1, p90 = sc.p90 ?? 2, p98 = sc.p98 ?? 3;
  chart("chart-calendar").setOption({
    animation: false, calendar: calendars, series,
    visualMap: {
      type: "piecewise", show: false, seriesIndex: heatIdx, dimension: 1,
      pieces: [{ value: 0, color: t.ramp[0] }, { gt: 0, lte: p50, color: t.ramp[1] }, { gt: p50, lte: p90, color: t.ramp[2] }, { gt: p90, lte: p98, color: t.ramp[3] }, { gt: p98, color: t.ramp[4] }],
    },
    tooltip: {
      ...tipStyle(t), confine: true,
      formatter(p) {
        if (p.seriesType === "custom") {
          const w = p.data.w;
          return `<b>Semaine du ${fmtRange(w.start, w.end)}</b><br><span style="color:${lvlColor(t, w.level)};font-weight:700">${LEVEL_LABEL[w.level]}</span> · ${times(w.ratio)} la normale<br>${n0(w.total)} détections (normale : ${n0(w.expected)})${statusLine(w)}${w.record && w.level === "critique" ? "<br>★ Valeur la plus forte observée pour cette semaine" : ""}`;
        }
        if (p.seriesName === "Pas de données") return `<b>${fmtDate(p.data[0])}</b><br>Aucun capteur n'a observé ce jour-là.`;
        const [d, v, lvl] = p.data;
        return `<b>${fmtLong(d)}</b><br>${n0(v)} détection${v >= 2 ? "s" : ""}${lvl === "critique" || lvl === "eleve" ? `<br>Semaine ${LEVEL_LABEL[lvl].toLowerCase()}e` : ""}`;
      },
    },
  }, true);
  chart("chart-calendar").resize();

  const sw = (c, txt) => `<span><i class="sw" style="background:${c}"></i>${txt}</span>`;
  legendEl.innerHTML =
    sw(t.ramp[0], "Aucun feu") + sw(t.ramp[1], `jusqu'à ${n0(p50)}`) + sw(t.ramp[2], `jusqu'à ${n0(p90)}`) + sw(t.ramp[3], `jusqu'à ${n0(p98)}`) + sw(t.ramp[4], `plus de ${n0(p98)}`) +
    `<span class="muted">détections par jour</span>` +
    `<span><i class="sw hatch" style="width:13px;height:13px;display:inline-block;border-radius:3px;margin-right:5px;vertical-align:-2px;background:repeating-linear-gradient(135deg,${t.normal} 0 2px,transparent 2px 5px);border:1px solid ${t.normal}"></i>Pas de données</span>` +
    `<span><i class="ring"></i>Semaine critique</span><span><i class="ring dash"></i>Semaine élevée</span><span><i class="dot"></i>Confirmée par plusieurs capteurs</span>`;
}

/* ---------------------------------------------------------------- hebdomadaire */
export function renderWeekly(r, focus) {
  const t = T(), W = r.weeks;
  const seuilNom = `Seuil critique (${r.params.q_critique}ᵉ centile des autres années)`;
  const labels = weekLabels(W);
  const maxv = Math.max(1, ...W.map((w) => Math.max(w.total ?? 0, w.p_critique ?? 0)));
  const inFocus = (i) => !!focus && i >= focus[0] && i <= focus[1];
  const bars = W.map((w, i) => w.total == null ? null : { value: w.total, itemStyle: {
    color: lvlColor(t, w.level),
    opacity: focus ? (inFocus(i) ? 1 : 0.28) : (w.level === "normal" || w.level === "indetermine" ? 0.5 : 1),
    ...(inFocus(i) ? { borderColor: t.ink, borderWidth: 2 } : {}) } });
  const gaps = W.map((w) => (w.total == null ? { value: maxv * 0.05, itemStyle: { color: t.normal, opacity: 0.6, decal: { symbol: "rect", dashArrayX: [1, 0], dashArrayY: [2, 4], rotation: -Math.PI / 4, color: t.panel } } } : null));
  const recs = W.map((w, i) => (w.record && w.level === "critique" && w.total != null ? [i, w.total] : null)).filter(Boolean);
  // la période cliquée dans le tableau : barres cerclées, le reste estompé, et la vue se centre dessus
  let zoom = {};
  if (focus && W.length > 70) {
    const pad = Math.max(8, Math.round((26 - (focus[1] - focus[0] + 1)) / 2));
    zoom = { startValue: Math.max(0, focus[0] - pad), endValue: Math.min(W.length - 1, focus[1] + pad) };
  }
  chart("chart-weekly").setOption({
    animation: false, grid: { left: 52, right: 16, top: 34, bottom: W.length > 70 ? 76 : 50 },
    legend: { top: 0, left: 0, itemWidth: 14, itemHeight: 10, textStyle: { color: t.ink2, fontFamily: t.font }, data: ["Détections", "Normale", seuilNom] },
    xAxis: { type: "category", data: labels, axisLabel: { color: t.ink2, fontFamily: t.font, interval: Math.max(0, Math.ceil(W.length / 13) - 1), hideOverlap: true, lineHeight: 15 }, axisLine: { lineStyle: { color: t.line } }, axisTick: { show: false } },
    yAxis: { type: "value", axisLabel: { color: t.ink2, fontFamily: t.font, formatter: short }, splitLine: { lineStyle: { color: t.line, opacity: 0.6 } } },
    dataZoom: W.length > 70 ? [{ type: "inside", ...zoom }, { type: "slider", height: 18, bottom: 6, borderColor: t.line, fillerColor: "rgba(14,107,115,.15)", textStyle: { color: t.ink2 }, ...zoom }] : [],
    tooltip: {
      ...tipStyle(t), trigger: "axis", axisPointer: { type: "shadow", shadowStyle: { color: "rgba(120,140,160,.12)" } }, confine: true,
      formatter(ps) {
        const w = W[ps[0].dataIndex];
        if (w.total == null) return `<b>Semaine du ${fmtRange(w.start, w.end)}</b><br>Pas assez de données pour évaluer cette semaine.`;
        return `<b>Semaine du ${fmtRange(w.start, w.end)}</b><br>${n0(w.total)} détections · normale ${n0(w.expected)}${w.ratio != null ? " (" + times(w.ratio) + ")" : ""}<br><span style="color:${lvlColor(t, w.level)};font-weight:700">${LEVEL_LABEL[w.level]}</span>${statusLine(w)}${w.record && w.level === "critique" ? "<br>★ Valeur la plus forte observée pour cette semaine" : ""}`;
      },
    },
    series: [
      { name: "Détections", type: "bar", itemStyle: { color: t.normal }, data: bars, barCategoryGap: "22%" },
      { name: "Pas de données", type: "bar", data: gaps, barGap: "-100%", silent: true },
      { name: "Normale", type: "line", data: W.map((w) => w.expected), symbol: "none", lineStyle: { color: t.ink, width: 2 }, itemStyle: { color: t.ink }, z: 5 },
      { name: seuilNom, type: "line", data: W.map((w) => w.p_critique), symbol: "none", lineStyle: { color: t.crit, width: 1.6, type: [5, 4] }, itemStyle: { color: t.crit }, z: 4 },
      { name: "Record", type: "scatter", data: recs, symbol: "path://M12 1l3.1 6.6 7.2.9-5.3 4.9 1.4 7.1L12 17l-6.4 3.5 1.4-7.1L1.7 8.5l7.2-.9z", symbolSize: 13, itemStyle: { color: t.ink, borderColor: t.panel, borderWidth: 1.5 }, z: 8, tooltip: { show: false } },
    ],
  }, true);
}

/* ---------------------------------------------------------------- mêmes dates */
export function renderWindow(r) {
  const t = T(), sw = r.same_window;
  // libellé tiré des vraies dates de chaque fenêtre : « 2015 » si elle tient dans une année, « 2015–18 » sinon
  const lab = (x) => { const a = x.start.slice(0, 4), b = x.end.slice(0, 4); return a === b ? a : `${a}–${b.slice(2)}`; };
  const others = sw.filter((x) => !x.selected).map((x) => x.total);
  const mean = others.length ? others.reduce((a, b) => a + b, 0) / others.length : null;
  chart("chart-window").setOption({
    animation: false, grid: { left: 52, right: 12, top: 26, bottom: 30 },
    xAxis: { type: "category", data: sw.map(lab), axisLabel: { color: t.ink2, fontFamily: t.font, interval: 0, fontSize: 11.5, rotate: sw.length > 9 ? 40 : 0 }, axisLine: { lineStyle: { color: t.line } }, axisTick: { show: false } },
    yAxis: { type: "value", axisLabel: { color: t.ink2, fontFamily: t.font, formatter: short }, splitLine: { lineStyle: { color: t.line, opacity: 0.6 } } },
    tooltip: { ...tipStyle(t), trigger: "axis", confine: true, formatter: (ps) => { const x = sw[ps[0].dataIndex]; return `<b>${fmtRange(x.start, x.end)}</b><br>${n0(x.total)} détections${x.selected ? "<br>Période choisie" : ""}`; } },
    series: [{
      type: "bar", barCategoryGap: "28%", data: sw.map((x) => ({ value: x.total, itemStyle: { color: x.selected ? t.accent : t.ink2, opacity: x.selected ? 1 : 0.4 } })),
      markLine: mean == null ? undefined : { silent: true, symbol: "none", label: { show: false }, lineStyle: { color: t.ink, type: [5, 4], width: 1.4 }, data: [{ yAxis: mean }] },
    }],
  }, true);
}

/* ---------------------------------------------------------------- saison */
export function renderSeason(r) {
  const t = T(), S = r.seasonal, ps = r.period.start, pe = r.period.end;
  const y0 = +ps.slice(0, 4), y1 = +pe.slice(0, 4), sel = new Set(); for (let y = y0; y <= y1; y++) sel.add(String(y));
  const firstOfMonth = {}; for (let m = 0; m < 12; m++) { const w = Math.min(51, Math.floor((Date.UTC(2023, m, 1) - Date.UTC(2023, 0, 1)) / 864e5 / 7)); if (!(w in firstOfMonth)) firstOfMonth[w] = MOIS[m]; }
  const cats = S.weeks.map((w) => firstOfMonth[w - 1] || "");
  const others = Object.entries(S.years).filter(([y]) => !sel.has(y));
  const series = others.map(([y, v], i) => ({ name: i === 0 ? "Autres années" : y, type: "line", data: v, symbol: "none", lineStyle: { width: 1, color: t.ink2, opacity: 0.28 }, silent: true, z: 1, tooltip: { show: false } }));
  const hi = [...sel].filter((y) => S.years[y]);
  hi.forEach((y, k) => series.push({ name: y, type: "line", data: S.years[y], symbol: "none", lineStyle: { width: 3, color: t.accent, type: k === 0 || hi.length === 1 ? "solid" : [7, 4] }, itemStyle: { color: t.accent }, z: 6, endLabel: { show: true, formatter: y, color: t.accent, fontFamily: t.font, fontWeight: 700 } }));
  series.push({ name: "Normale", type: "line", data: S.mean, symbol: "none", lineStyle: { width: 2, color: t.ink, type: [6, 4] }, itemStyle: { color: t.ink }, z: 4 });
  let area;
  if (y0 === y1) {
    const w0 = Math.min(51, Math.floor((Date.UTC(2023, +ps.slice(5, 7) - 1, +ps.slice(8, 10)) - Date.UTC(2023, 0, 1)) / 864e5 / 7));
    const w1 = Math.min(51, Math.floor((Date.UTC(2023, +pe.slice(5, 7) - 1, +pe.slice(8, 10)) - Date.UTC(2023, 0, 1)) / 864e5 / 7));
    area = { silent: true, data: [[{ xAxis: w0, itemStyle: { color: t.accent, opacity: 0.1 } }, { xAxis: w1 }]] };
  }
  if (area) series[series.length - 1].markArea = area;
  chart("chart-season").setOption({
    animation: false, grid: { left: 52, right: 40, top: 30, bottom: 28 },
    legend: { top: 0, left: 0, itemWidth: 16, itemHeight: 8, textStyle: { color: t.ink2, fontFamily: t.font }, data: ["Autres années", "Normale"] },
    xAxis: { type: "category", data: S.weeks.map(String), boundaryGap: false, axisLabel: { color: t.ink2, fontFamily: t.font, interval: 0, formatter: (v, i) => cats[i] }, axisTick: { show: false }, axisLine: { lineStyle: { color: t.line } } },
    yAxis: { type: "value", axisLabel: { color: t.ink2, fontFamily: t.font, formatter: short }, splitLine: { lineStyle: { color: t.line, opacity: 0.6 } } },
    tooltip: { ...tipStyle(t), trigger: "axis", confine: true, formatter: (ps) => `<b>Semaine ${ps[0].axisValue}</b>` + ps.filter((p) => p.value != null && p.seriesName !== "Autres années" && !/^\d{4}$/.test(p.seriesName) || sel.has(p.seriesName)).map((p) => `<br>${p.marker} ${p.seriesName} : ${n0(p.value)}`).join("") },
    series,
  }, true);
}

/* ---------------------------------------------------------------- capteurs */
export function renderSensors(r, params) {
  const t = T(), W = r.weeks;
  const labels = weekLabels(W);
  const key = (y, w) => y * 52 + w;
  const names = Object.keys(r.sensors);
  const series = names.map((nm, i) => {
    const map = new Map(r.sensors[nm].weeks.map((x) => [key(x.year, x.week), x]));
    return {
      name: SENSOR_NAME[nm] || nm, type: "line", symbol: SYMBOLS[i % 4], symbolSize: 6, showSymbol: W.length < 45,
      data: W.map((w) => { const x = map.get(key(w.year, w.week)); return x && x.ratio != null ? x.ratio : null; }),
      lineStyle: { width: 2, color: t.sens[i % 4], type: i === 3 ? [6, 3] : "solid" }, itemStyle: { color: t.sens[i % 4] },
    };
  });
  series[0] && (series[0].markLine = { silent: true, symbol: "none", label: { color: t.ink2, fontFamily: t.font, position: "insideStartTop" }, lineStyle: { type: [4, 4], width: 1.2 }, data: [{ yAxis: 1, label: { formatter: "normale" }, lineStyle: { color: t.ink } }, { yAxis: params.ratio_eleve, label: { formatter: "seuil élevé" }, lineStyle: { color: t.high } }, { yAxis: params.ratio_critique, label: { formatter: "seuil critique" }, lineStyle: { color: t.crit } }] });
  chart("chart-sensors").setOption({
    animation: false, grid: { left: 52, right: 16, top: 36, bottom: W.length > 70 ? 76 : 50 },
    legend: { top: 0, left: 0, itemWidth: 22, itemHeight: 10, textStyle: { color: t.ink2, fontFamily: t.font } },
    xAxis: { type: "category", data: labels, boundaryGap: false, axisLabel: { color: t.ink2, fontFamily: t.font, interval: Math.max(0, Math.ceil(W.length / 13) - 1), hideOverlap: true, lineHeight: 15 }, axisTick: { show: false }, axisLine: { lineStyle: { color: t.line } } },
    yAxis: { type: "value", min: 0, max: (v) => Math.min(6, Math.max(2.2, Math.ceil(v.max * 10) / 10)), axisLabel: { color: t.ink2, fontFamily: t.font }, splitLine: { lineStyle: { color: t.line, opacity: 0.6 } } },
    dataZoom: W.length > 70 ? [{ type: "inside" }, { type: "slider", height: 18, bottom: 6, borderColor: t.line, textStyle: { color: t.ink2 } }] : [],
    tooltip: { ...tipStyle(t), trigger: "axis", confine: true, formatter: (ps) => { const w = W[ps[0].dataIndex]; return `<b>Semaine du ${fmtRange(w.start, w.end)}</b>` + ps.map((p) => `<br>${p.marker} ${p.seriesName} : ${p.value == null ? "—" : times(p.value)}`).join(""); } },
    series,
  }, true);
}
