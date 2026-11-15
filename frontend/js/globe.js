/* Globe orthographique dessiné en canvas 2D : étoiles, atmosphère, continents, orbites, satellites,
 * et les cellules de feu les plus actives (données réelles de la base, quand elles sont disponibles). */
const D2R = Math.PI / 180;
const clamp = (x, a = 0, b = 1) => Math.min(b, Math.max(a, x));
const smooth = (x) => { x = clamp(x); return x * x * (3 - 2 * x); };

export class Globe {
  constructor(canvas, { reduced = false } = {}) {
    this.cv = canvas; this.ctx = canvas.getContext("2d");
    this.reduced = reduced; this.land = []; this.hot = [];
    this.t0 = performance.now(); this.intro = reduced ? 1 : 0; this.skipTo = null;
    this.ptr = { x: 0, y: 0, tx: 0, ty: 0 }; this.raf = 0; this.running = false;
    this.stars = []; this.orbits = [
      { rot: -24 * D2R, ry: 0.30, rx: 1.42, sp: 0.19, ph: 0.4 },
      { rot: 38 * D2R, ry: 0.24, rx: 1.58, sp: -0.13, ph: 2.6 },
      { rot: 8 * D2R, ry: 0.50, rx: 1.30, sp: 0.09, ph: 4.4 },
    ];
    this.resize(); this._onResize = () => { this.resize(); if (!this.running) this.frame(performance.now()); };
    addEventListener("resize", this._onResize);
    this._onMove = (e) => { this.ptr.tx = (e.clientX / innerWidth - 0.5) * 2; this.ptr.ty = (e.clientY / innerHeight - 0.5) * 2; };
    if (!reduced) addEventListener("pointermove", this._onMove, { passive: true });
  }
  setLand(polys) { this.land = polys; if (!this.running) this.frame(performance.now()); }
  setHot(h) { this.hot = h; }
  finishIntro() { this.skipTo = performance.now(); }

  resize() {
    const dpr = Math.min(devicePixelRatio || 1, 2);
    const r = this.cv.getBoundingClientRect();
    this.W = Math.max(320, r.width); this.H = Math.max(320, r.height);
    this.cv.width = Math.round(this.W * dpr); this.cv.height = Math.round(this.H * dpr);
    this.ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    const narrow = this.W < 760;
    if (narrow) { this.R = Math.min(this.W * 0.5, this.H * 0.21); this.cx = this.W * 0.5; this.cy = this.H * 0.26; }
    else { this.R = Math.min(this.W * 0.31, this.H * 0.44); this.cx = this.W * 0.67; this.cy = this.H * 0.52; }
    const n = narrow ? 110 : 240; let s = 7;
    const rnd = () => (s = (s * 16807) % 2147483647) / 2147483647;   // même ciel à chaque chargement
    this.stars = Array.from({ length: n }, () => ({ x: rnd(), y: rnd(), r: 0.3 + rnd() * 1.1, p: rnd() * 6.28, sp: 0.4 + rnd() * 1.4, hue: rnd() }));
  }

  start() { if (this.running) return; this.running = true; this.t0 = performance.now() - (this.intro >= 1 ? 6000 : 0); const loop = (now) => { if (!this.running) return; this.frame(now); this.raf = requestAnimationFrame(loop); }; this.raf = requestAnimationFrame(loop); }
  stop() { this.running = false; cancelAnimationFrame(this.raf); }
  destroy() { this.stop(); removeEventListener("resize", this._onResize); removeEventListener("pointermove", this._onMove); }

  proj(lon, lat, l0, p0) {
    const l = lon * D2R - l0, p = lat * D2R, cp = Math.cos(p), sp = Math.sin(p);
    const cc = Math.sin(p0) * sp + Math.cos(p0) * cp * Math.cos(l);
    return { x: cp * Math.sin(l), y: Math.cos(p0) * sp - Math.sin(p0) * cp * Math.cos(l), c: cc };
  }

  frame(now) {
    const { ctx, W, H, cx, cy, R } = this;
    if (this.skipTo != null) { this.t0 = Math.min(this.t0, now - 6000); this.skipTo = null; }
    const t = this.reduced ? 99 : (now - this.t0) / 1000;
    this.intro = clamp(t / 5);
    this.ptr.x += (this.ptr.tx - this.ptr.x) * 0.04; this.ptr.y += (this.ptr.ty - this.ptr.y) * 0.04;
    const aStars = smooth(t / 1.6), aGlobe = smooth((t - 0.5) / 1.8), aOrb = smooth((t - 1.5) / 1.5);
    const settle = 1 - smooth(t / 3.4);
    const lon0 = (20 + Math.sin(t * 0.11) * 16 - settle * 110 + this.ptr.x * 9) * D2R;
    const lat0 = (8 - this.ptr.y * 5 + settle * 12) * D2R;
    ctx.clearRect(0, 0, W, H);

    // étoiles
    for (const s of this.stars) {
      const tw = 0.55 + 0.45 * Math.sin(t * s.sp + s.p);
      ctx.globalAlpha = aStars * tw * (0.35 + s.r * 0.5);
      ctx.fillStyle = s.hue > 0.86 ? "#9ED8FF" : s.hue > 0.78 ? "#FFD9A8" : "#F1F7FF";
      ctx.beginPath(); ctx.arc(s.x * W + this.ptr.x * -4 * s.r, s.y * H + this.ptr.y * -3 * s.r, s.r, 0, 6.283); ctx.fill();
    }
    ctx.globalAlpha = 1;
    if (aGlobe <= 0) return;

    // halo atmosphérique
    const halo = ctx.createRadialGradient(cx, cy, R * 0.9, cx, cy, R * 1.5);
    halo.addColorStop(0, `rgba(52,136,255,${0.42 * aGlobe})`); halo.addColorStop(0.35, `rgba(0,217,255,${0.10 * aGlobe})`); halo.addColorStop(1, "rgba(5,11,24,0)");
    ctx.fillStyle = halo; ctx.fillRect(cx - R * 1.6, cy - R * 1.6, R * 3.2, R * 3.2);

    this.orbitsPass(t, aOrb, false);

    // sphère
    ctx.save(); ctx.globalAlpha = aGlobe;
    const sph = ctx.createRadialGradient(cx - R * 0.35, cy - R * 0.4, R * 0.1, cx, cy, R);
    sph.addColorStop(0, "#14407A"); sph.addColorStop(0.55, "#0A2347"); sph.addColorStop(1, "#050E22");
    ctx.beginPath(); ctx.arc(cx, cy, R, 0, 6.283); ctx.fillStyle = sph; ctx.fill();
    ctx.clip();

    // graticule
    ctx.lineWidth = 0.6; ctx.strokeStyle = "rgba(0,217,255,0.13)";
    for (let lo = -180; lo < 180; lo += 20) this.line(lo, 0, true, lon0, lat0);
    for (let la = -80; la <= 80; la += 20) this.line(la, 0, false, lon0, lat0);

    // continents
    ctx.fillStyle = "rgba(28,92,150,0.55)"; ctx.strokeStyle = "rgba(0,217,255,0.55)"; ctx.lineWidth = 0.8; ctx.lineJoin = "round";
    for (const poly of this.land) {
      ctx.beginPath(); let any = false;
      for (const ring of poly) {
        let first = true;
        for (const pt of ring) {
          const q = this.proj(pt[0], pt[1], lon0, lat0);
          let x = q.x, y = q.y;
          if (q.c < 0) { const m = Math.hypot(x, y) || 1; x /= m; y /= m; } else any = true;   // face cachée : on colle au bord
          const px = cx + x * R, py = cy - y * R;
          if (first) { ctx.moveTo(px, py); first = false; } else ctx.lineTo(px, py);
        }
        ctx.closePath();
      }
      if (any) { ctx.fill(); ctx.stroke(); }
    }

    // feux réels
    if (this.hot.length) {
      ctx.globalCompositeOperation = "lighter";
      for (const h of this.hot) {
        const q = this.proj(h.lon, h.lat, lon0, lat0); if (q.c <= 0.02) continue;
        const pulse = 0.6 + 0.4 * Math.sin(t * 2 + h.lon * 3.1);
        const rr = (1.1 + h.v * 2.6) * (R / 300) * (0.75 + 0.45 * pulse) * q.c ** 0.5;
        const px = cx + q.x * R, py = cy - q.y * R;
        const g = ctx.createRadialGradient(px, py, 0, px, py, rr * 2.6);
        g.addColorStop(0, `rgba(255,196,120,${0.8 * aGlobe})`); g.addColorStop(0.3, `rgba(255,140,40,${0.38 * aGlobe})`); g.addColorStop(1, "rgba(255,70,85,0)");
        ctx.fillStyle = g; ctx.beginPath(); ctx.arc(px, py, rr * 2.6, 0, 6.283); ctx.fill();
      }
      ctx.globalCompositeOperation = "source-over";
    }

    // relief de la sphère : bord assombri, reflet côté lumière
    const shade = ctx.createRadialGradient(cx - R * 0.25, cy - R * 0.3, R * 0.45, cx, cy, R * 1.02);
    shade.addColorStop(0, "rgba(5,11,24,0)"); shade.addColorStop(1, "rgba(3,7,16,0.72)");
    ctx.fillStyle = shade; ctx.fillRect(cx - R, cy - R, R * 2, R * 2);
    ctx.restore();

    // liseré lumineux + anneau holographique
    ctx.save(); ctx.globalAlpha = aGlobe;
    ctx.beginPath(); ctx.arc(cx, cy, R, 0, 6.283); ctx.lineWidth = 1.4; ctx.strokeStyle = "rgba(0,217,255,0.75)"; ctx.shadowColor = "rgba(0,217,255,0.9)"; ctx.shadowBlur = 18; ctx.stroke();
    ctx.shadowBlur = 0; ctx.setLineDash([2, 9]); ctx.lineDashOffset = -t * 6; ctx.lineWidth = 1.2; ctx.strokeStyle = "rgba(0,217,255,0.45)";
    ctx.beginPath(); ctx.arc(cx, cy, R * 1.11, 0, 6.283); ctx.stroke();
    ctx.setLineDash([]); ctx.lineDashOffset = 0;
    for (let i = 0; i < 72; i++) {   // graduations tournantes
      const a = i * (6.283 / 72) + t * 0.05, long = i % 6 === 0, r1 = R * 1.145, r2 = R * (long ? 1.19 : 1.165);
      ctx.strokeStyle = long ? "rgba(255,157,46,0.7)" : "rgba(0,217,255,0.28)"; ctx.lineWidth = long ? 1.4 : 0.8;
      ctx.beginPath(); ctx.moveTo(cx + Math.cos(a) * r1, cy + Math.sin(a) * r1); ctx.lineTo(cx + Math.cos(a) * r2, cy + Math.sin(a) * r2); ctx.stroke();
    }
    ctx.restore();

    this.orbitsPass(t, aOrb, true);
  }

  line(a, _b, isMeridian, l0, p0) {
    const { ctx, cx, cy, R } = this; let pen = false; ctx.beginPath();
    for (let k = -90; k <= 90; k += 3) {
      const q = isMeridian ? this.proj(a, k, l0, p0) : this.proj(k * 2, a, l0, p0);
      if (q.c < 0) { pen = false; continue; }
      const x = cx + q.x * R, y = cy - q.y * R; if (!pen) { ctx.moveTo(x, y); pen = true; } else ctx.lineTo(x, y);
    }
    ctx.stroke();
  }

  /** Orbites : moitié arrière avant la sphère (front=false), moitié avant après (front=true). */
  orbitsPass(t, a, front) {
    if (a <= 0) return;
    const { ctx, cx, cy, R } = this;
    this.orbits.forEach((o, i) => {
      const rx = R * o.rx, ry = R * o.rx * o.ry;
      const pos = (th) => { const x = Math.cos(th) * rx, y = Math.sin(th) * ry; return [cx + x * Math.cos(o.rot) - y * Math.sin(o.rot), cy + x * Math.sin(o.rot) + y * Math.cos(o.rot)]; };
      ctx.save(); ctx.globalAlpha = a * (front ? 0.85 : 0.35);
      ctx.beginPath();
      const a0 = front ? 0 : Math.PI, a1 = front ? Math.PI : Math.PI * 2;
      for (let th = a0; th <= a1 + 0.001; th += 0.05) { const [x, y] = pos(th); th === a0 ? ctx.moveTo(x, y) : ctx.lineTo(x, y); }
      ctx.strokeStyle = i === 1 ? "rgba(255,157,46,0.55)" : "rgba(0,217,255,0.5)"; ctx.lineWidth = 1; ctx.stroke();
      // satellite
      const th = ((o.ph + t * o.sp) % 6.2832 + 6.2832) % 6.2832, isFront = th < Math.PI;
      if (isFront === front) {
        const [sx, sy] = pos(th);
        for (let k = 1; k <= 14; k++) {   // traînée
          const tt = th - Math.sign(o.sp) * k * 0.035, [x, y] = pos(tt);
          ctx.globalAlpha = a * (1 - k / 15) * 0.5; ctx.fillStyle = i === 1 ? "#FF9D2E" : "#00D9FF";
          ctx.beginPath(); ctx.arc(x, y, 1.6 * (1 - k / 18), 0, 6.283); ctx.fill();
        }
        ctx.globalAlpha = a; ctx.shadowColor = i === 1 ? "#FF9D2E" : "#00D9FF"; ctx.shadowBlur = 14; ctx.fillStyle = "#F1F7FF";
        ctx.beginPath(); ctx.arc(sx, sy, 2.6, 0, 6.283); ctx.fill(); ctx.shadowBlur = 0;
        if (front) {   // faisceau d'observation vers la Terre
          const g = ctx.createLinearGradient(sx, sy, cx, cy); g.addColorStop(0, "rgba(0,217,255,0.35)"); g.addColorStop(0.5, "rgba(0,217,255,0)");
          ctx.strokeStyle = g; ctx.lineWidth = 1; ctx.beginPath(); ctx.moveTo(sx, sy); ctx.lineTo(cx, cy); ctx.stroke();
        }
      }
      ctx.restore();
    });
  }
}
