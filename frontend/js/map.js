import { css, n0 } from "./util.js";

const RAD = Math.PI / 180;
const mercX = (lon) => (lon + 180) / 360;
const mercY = (lat) => 0.5 - Math.log(Math.tan(Math.PI / 4 + (lat * RAD) / 2)) / (2 * Math.PI);

/** Couche canvas qui dessine les cellules de 30 km (4 coins lon/lat chacune), colorées par le total de la période. */
const FireGrid = L.Layer.extend({
  initialize(cells) {
    this.n = cells.ids.length;
    this.cells = cells;
    this.mx = new Float32Array(this.n * 4); this.my = new Float32Array(this.n * 4);
    for (let i = 0; i < this.n; i++) for (let k = 0; k < 4; k++) {
      this.mx[i * 4 + k] = mercX(cells.corners[2 * k][i]);
      this.my[i * 4 + k] = mercY(cells.corners[2 * k + 1][i]);
    }
    this.values = new Float32Array(this.n); this.vref = 1; this.lut = [];
  },
  onAdd(map) {
    this._map = map;
    this._c = L.DomUtil.create("canvas", "leaflet-zoom-hide");
    this._c.style.pointerEvents = "none";
    map.getPanes().overlayPane.appendChild(this._c);
    map.on("moveend zoomend resize", this.draw, this);
    this.draw();
  },
  onRemove(map) { this._c.remove(); map.off("moveend zoomend resize", this.draw, this); },
  setValues(arr) {
    this.values = Float32Array.from(arr);
    const pos = Array.from(this.values).filter((v) => v > 0).sort((a, b) => a - b);
    this.vref = pos.length ? pos[Math.min(pos.length - 1, Math.floor(pos.length * 0.99))] : 1;
    this.refresh();
  },
  refresh() {
    const stops = ["--r1", "--r2", "--r3", "--r4"].map((v) => hex(css(v)));
    this.lut = Array.from({ length: 48 }, (_, i) => rgb(ramp(stops, i / 47)));
    this.draw();
  },
  draw() {
    if (!this._map || !this._c) return;
    const m = this._map, size = m.getSize(), z = m.getZoom(), world = 256 * Math.pow(2, z);
    const origin = m.getPixelBounds().min, tl = m.containerPointToLayerPoint([0, 0]);
    const c = this._c, dpr = window.devicePixelRatio || 1;
    c.width = size.x * dpr; c.height = size.y * dpr; c.style.width = size.x + "px"; c.style.height = size.y + "px";
    L.DomUtil.setPosition(c, tl);
    const g = c.getContext("2d"); g.scale(dpr, dpr);
    const { mx, my, values, n, lut } = this, lv = Math.log1p(this.vref);
    const edge = world / 30000 > 0 ? 0 : 0; // (placeholder pour un trait fin éventuel)
    for (let i = 0; i < n; i++) {
      const v = values[i];
      if (!(v > 0)) continue;
      const b = i * 4;
      const x0 = mx[b] * world - origin.x, y0 = my[b] * world - origin.y;
      if (x0 < -40 || y0 < -40 || x0 > size.x + 40 || y0 > size.y + 40) continue;
      const t = Math.min(1, Math.sqrt(v / this.vref));
      g.fillStyle = lut[Math.max(0, Math.min(47, Math.round(t * 47)))];
      g.beginPath(); g.moveTo(x0, y0);
      for (let k = 1; k < 4; k++) g.lineTo(mx[b + k] * world - origin.x, my[b + k] * world - origin.y);
      g.closePath(); g.fill();
    }
  },
});

function hex(h) { h = h.replace("#", ""); if (h.length === 3) h = [...h].map((x) => x + x).join(""); return [0, 2, 4].map((i) => parseInt(h.slice(i, i + 2), 16)); }
function ramp(stops, t) { const p = t * (stops.length - 1), i = Math.min(stops.length - 2, Math.floor(p)), f = p - i; return stops[i].map((a, k) => a + (stops[i + 1][k] - a) * f); }
const rgb = (a) => `rgb(${a.map(Math.round).join(",")})`;

export class FireMap {
  constructor(el, tipEl, cells, onZone) {
    this.cells = cells; this.tip = tipEl; this.onZone = onZone;
    this.map = L.map(el, { zoomSnap: 0.5, zoomDelta: 0.5, minZoom: 2, maxZoom: 11, worldCopyJump: false, attributionControl: true });
    this.map.attributionControl.setPrefix(false);
    this.map.fitBounds([[-36, -19], [38, 52]]);
    this.tiles = null; this.osm = false;
    this.layer = new FireGrid(cells).addTo(this.map);
    this.zoneLayers = L.layerGroup().addTo(this.map);
    this.bordersLayer = null;
    this.map.on(L.Draw.Event.CREATED, (e) => {
      this.tool = null; this.setActiveTool(null);
      const lyr = e.layer;
      if (e.layerType === "rectangle") {
        const b = lyr.getBounds();
        onZone({ type: "bbox", bbox: [b.getWest(), b.getSouth(), b.getEast(), b.getNorth()] });
      } else {
        const ring = lyr.getLatLngs()[0].map((p) => [p.lng, p.lat]);
        onZone({ type: "polygon", coordinates: ring });
      }
    });
    this.map.on("draw:drawstop", () => { this.tool = null; this.setActiveTool(null); });
    document.addEventListener("keydown", (e) => { if (e.key === "Escape" && this.drawing) this.cancelDraw(); });
    this.map.on("mousemove", (e) => this.hover(e));
    this.map.on("mouseout", () => (this.tip.hidden = true));
    this.map.on("movestart zoomstart", () => (this.tip.hidden = true));
    this.vals = null;
    new ResizeObserver(() => this.map.invalidateSize()).observe(el);
  }
  setBasemap(on = this.osm) {
    this.osm = !!on;
    if (this.tiles) { this.map.removeLayer(this.tiles); this.tiles = null; }
    document.getElementById("map").classList.toggle("osm-on", this.osm);
    if (!this.osm) return;
    this.tiles = L.tileLayer("https://tile.openstreetmap.org/{z}/{x}/{y}.png",
      { maxZoom: 11, attribution: "© les contributeurs d'OpenStreetMap" }).addTo(this.map);
    this.tiles.bringToBack();
  }
  async loadBorders(url) {
    const gj = await (await fetch(url)).json();
    this.bordersGJ = gj; this.styleBorders();
  }
  styleBorders() {
    if (!this.bordersGJ) return;
    if (this.bordersLayer) this.map.removeLayer(this.bordersLayer);
    this.bordersLayer = L.geoJSON(this.bordersGJ, {
      interactive: false, style: { color: css("--ink-2"), weight: 0.8, opacity: 0.55, fill: true, fillColor: css("--r0"), fillOpacity: 0.55 },
    }).addTo(this.map);
    this.bordersLayer.bringToBack(); if (this.tiles) this.tiles.bringToBack();
    // la grille doit rester au-dessus des frontières : on la ré-attache
    this.map.removeLayer(this.layer); this.layer.addTo(this.map); this.zoneLayers.eachLayer((l) => l.bringToFront && l.bringToFront());
  }
  setValues(arr) { this.vals = arr; this.layer.setValues(arr); }
  restyle() { this.styleBorders(); this.layer.refresh(); }
  vref() { return this.layer.vref; }

  startDraw(kind) {
    this.cancelDraw();
    const shape = { color: css("--accent"), weight: 2, fillOpacity: 0.08 };
    this.tool = kind === "rect" ? new L.Draw.Rectangle(this.map, { shapeOptions: shape }) : new L.Draw.Polygon(this.map, { shapeOptions: shape, allowIntersection: false, showArea: false });
    this.tool.enable(); this.setActiveTool(kind);
  }
  cancelDraw() { if (this.tool) { try { this.tool.disable(); } catch (_) {} this.tool = null; } this.setActiveTool(null); }
  setActiveTool(kind) {
    this.drawing = kind;
    if (this.onTool) this.onTool();
    document.getElementById("draw-rect").classList.toggle("on", kind === "rect");
    document.getElementById("draw-poly").classList.toggle("on", kind === "poly");
    document.getElementById("draw-hint").textContent = kind === "rect" ? "Cliquez, glissez puis relâchez pour tracer le rectangle."
      : kind === "poly" ? "Cliquez pour poser chaque sommet, puis cliquez sur le premier point pour fermer." :
        "Dessinez sur la carte, choisissez une région ou saisissez des coordonnées.";
  }
  clearZone() { this.zoneLayers.clearLayers(); }
  showZone(zone, fit = true) {
    this.zoneLayers.clearLayers();
    let ring;
    if (zone.type === "bbox") { const [w, s, e, n] = zone.bbox; ring = [[s, w], [s, e], [n, e], [n, w]]; }
    else ring = zone.coordinates.map(([lo, la]) => [la, lo]);
    const world = [[-89, -540], [-89, 540], [89, 540], [89, -540]];
    L.polygon([world, ring], { stroke: false, fillColor: "#0b1218", fillOpacity: 0.34, interactive: false }).addTo(this.zoneLayers);
    const outline = L.polygon(ring, { color: css("--accent"), weight: 2.5, fill: false, interactive: false }).addTo(this.zoneLayers);
    if (fit) this.map.fitBounds(outline.getBounds().pad(0.35), { maxZoom: 8, animate: true });
  }
  hover(e) {
    if (!this.vals || this.tool) return;
    const { lon, lat, ids } = this.cells, p = e.latlng;
    let best = -1, bd = 1e9;
    const cl = Math.cos(p.lat * RAD);
    for (let i = 0; i < ids.length; i++) { const dx = (lon[i] - p.lng) * cl, dy = lat[i] - p.lat; const d = dx * dx + dy * dy; if (d < bd) { bd = d; best = i; } }
    if (best < 0 || bd > 0.16 || !(this.vals[best] > 0)) { this.tip.hidden = true; return; }
    this.tip.hidden = false;
    this.tip.textContent = `Cellule de 30 km : ${n0(this.vals[best])} détections sur la période`;
    this.tip.style.left = e.originalEvent.clientX + 14 + "px"; this.tip.style.top = e.originalEvent.clientY + 14 + "px";
  }
}
