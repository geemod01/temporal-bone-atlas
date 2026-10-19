// SlicePane: one orthogonal CT view with a synced crosshair, structure outlines and labels.
import { structureName, structureColor, STRUCTURE_BY_ID, visibleAtDepth } from './content.js';

export const PLANES = {
  axial: { axis: 'z', name: 'Axial', flipX: true, flipY: true, labels: { left: 'R', right: 'L', top: 'A', bottom: 'P' }, coord: 'z' },
  coronal: { axis: 'y', name: 'Coronal', flipX: true, flipY: true, labels: { left: 'R', right: 'L', top: 'S', bottom: 'I' }, coord: 'y' },
  sagittal: { axis: 'x', name: 'Sagittal', flipX: true, flipY: true, labels: { left: 'A', right: 'P', top: 'S', bottom: 'I' }, coord: 'x' }
};
const AXIS_INDEX = { x: 0, y: 1, z: 2 };

export class SlicePane {
  constructor(plane, store, el) {
    this.plane = plane;
    this.def = PLANES[plane];
    this.store = store;
    this.el = el;
    el.classList.add('pane', 'pane-2d');
    el.dataset.pane = plane;
    el.innerHTML = `
      <canvas class="ct"></canvas>
      <canvas class="ovl"></canvas>
      <div class="pane-corner tl"><span class="pane-name">${this.def.name}</span></div>
      <div class="pane-corner tr"><span class="pane-pos"></span><span class="pane-idx"></span></div>
      <div class="pane-corner bl"><span class="pane-wl"></span></div>
      <div class="pane-corner br"><span class="pane-zoom"></span></div>
      <div class="pane-orient l"></div><div class="pane-orient r"></div><div class="pane-orient t"></div><div class="pane-orient b"></div>
      <div class="pane-tip" hidden></div>`;
    this.ct = el.querySelector('canvas.ct');
    this.ovl = el.querySelector('canvas.ovl');
    this.tip = el.querySelector('.pane-tip');
    this.ctx = this.ct.getContext('2d');
    this.octx = this.ovl.getContext('2d');
    this.img = document.createElement('canvas');
    this.mask = document.createElement('canvas');
    this.zoom = 1; this.panX = 0; this.panY = 0;
    this.sliceIdx = -1; this.sliceBuf = null; this.labelBuf = null;
    this.dirty = false;
    this.ds = null;
    this.w = 0; this.h = 0; this.dpr = window.devicePixelRatio || 1;
    this.bindEvents();
    this.ro = new ResizeObserver(() => this.resize());
    this.ro.observe(el);
    store.on('crosshair', () => this.invalidate());
    store.on('selected', () => this.invalidate());
    store.on('hover', () => this.invalidate());
    store.on('settings', (e) => { if (e.key === 'window' || e.key === '*') this.sliceIdx = -1; this.invalidate(); });
    store.on('depth', () => this.invalidate());
    store.on('dataset', (ds) => this.setDataset(ds));
    store.on('tour', () => this.invalidate());
    store.on('quiz', () => this.invalidate());
  }

  // ---------- geometry ----------
  get flipX() { const m = this.store.get('settings').mirror; return (this.plane === 'sagittal') ? this.def.flipX : (this.def.flipX !== m); }
  get flipY() { return this.def.flipY; }
  get sd() { return this.ds ? this.ds.volume.sliceDims(this.def.axis) : null; }
  fitScale() {
    const sd = this.sd; if (!sd) return 1;
    return Math.min(this.w / (sd.cols * sd.colSp), this.h / (sd.rows * sd.rowSp)) * 0.96;
  }
  transform() {
    const sd = this.sd;
    const s = this.fitScale() * this.zoom;
    const drawW = sd.cols * sd.colSp * s, drawH = sd.rows * sd.rowSp * s;
    return { s, drawW, drawH, ox: (this.w - drawW) / 2 + this.panX, oy: (this.h - drawH) / 2 + this.panY, sd };
  }
  // image (u,v) in voxel units -> screen px
  imgToScreen(u, v, t) {
    t = t || this.transform();
    const uu = this.flipX ? (t.sd.cols - u) : u, vv = this.flipY ? (t.sd.rows - v) : v;
    return [t.ox + uu * t.sd.colSp * t.s, t.oy + vv * t.sd.rowSp * t.s];
  }
  screenToImg(sx, sy, t) {
    t = t || this.transform();
    let u = (sx - t.ox) / (t.sd.colSp * t.s), v = (sy - t.oy) / (t.sd.rowSp * t.s);
    if (this.flipX) u = t.sd.cols - u;
    if (this.flipY) v = t.sd.rows - v;
    return [u, v];
  }
  // image (u,v) + current slice -> world
  imgToWorld(u, v) {
    const vol = this.ds.volume, k = this.sliceIndexFromCrosshair();
    const i = u - 0.5, j = v - 0.5;
    if (this.plane === 'axial') return vol.voxelToWorld([i, j, k]);
    if (this.plane === 'coronal') return vol.voxelToWorld([i, k, j]);
    return vol.voxelToWorld([k, i, j]);
  }
  worldToImg(p) {
    const v = this.ds.volume.worldToVoxel(p);
    if (this.plane === 'axial') return [v[0] + 0.5, v[1] + 0.5];
    if (this.plane === 'coronal') return [v[0] + 0.5, v[2] + 0.5];
    return [v[1] + 0.5, v[2] + 0.5];
  }
  screenToWorld(sx, sy) { const [u, v] = this.screenToImg(sx, sy); return this.imgToWorld(u, v); }
  worldToScreen(p, t) { const [u, v] = this.worldToImg(p); return this.imgToScreen(u, v, t); }
  sliceIndexFromCrosshair() {
    const vol = this.ds.volume, c = this.store.get('crosshair');
    const a = AXIS_INDEX[this.def.axis];
    const idx = Math.round((c[a] - vol.origin[a]) / vol.spacing[a]);
    return Math.min(vol.dims[a] - 1, Math.max(0, idx));
  }
  stepSlice(delta) {
    if (!this.ds) return;
    const vol = this.ds.volume, c = this.store.get('crosshair').slice();
    const a = AXIS_INDEX[this.def.axis];
    const k = this.sliceIndexFromCrosshair() + delta;
    const kk = Math.min(vol.dims[a] - 1, Math.max(0, k));
    c[a] = vol.origin[a] + kk * vol.spacing[a];
    this.store.setCrosshair(c, this.plane);
  }
  setSliceIndex(k) { this.stepSlice(k - this.sliceIndexFromCrosshair()); }

  // ---------- lifecycle ----------
  setDataset(ds) {
    this.ds = ds; this.sliceIdx = -1; this.zoom = 1; this.panX = this.panY = 0;
    if (ds) {
      const sd = this.sd;
      this.img.width = sd.cols; this.img.height = sd.rows;
      this.mask.width = sd.cols; this.mask.height = sd.rows;
      this.sliceBuf = new Float32Array(sd.cols * sd.rows);
      this.labelBuf = ds.labels ? new Uint8Array(sd.cols * sd.rows) : null;
      this.imgData = this.ctxImg().createImageData(sd.cols, sd.rows);
      this.maskData = this.mask.getContext('2d').createImageData(sd.cols, sd.rows);
    }
    this.invalidate();
  }
  ctxImg() { return this.img.getContext('2d'); }
  resize() {
    const r = this.el.getBoundingClientRect();
    this.w = Math.max(1, Math.floor(r.width)); this.h = Math.max(1, Math.floor(r.height));
    this.dpr = window.devicePixelRatio || 1;
    for (const c of [this.ct, this.ovl]) {
      c.width = Math.floor(this.w * this.dpr); c.height = Math.floor(this.h * this.dpr);
      c.style.width = this.w + 'px'; c.style.height = this.h + 'px';
    }
    this.invalidate();
  }
  invalidate() {
    if (this.dirty) return;
    this.dirty = true;
    requestAnimationFrame(() => { this.dirty = false; this.render(); });
  }
  resetView() { this.zoom = 1; this.panX = this.panY = 0; this.invalidate(); }
  // Zoom so a world-space box (min/max RAS) fills about `fill` of the pane, centred on it.
  zoomToBounds(bounds, fill = 0.45) {
    if (!this.ds || !bounds) return;
    const [u0, v0] = this.worldToImg(bounds.min), [u1, v1] = this.worldToImg(bounds.max);
    const sd = this.sd;
    const wmm = Math.max(1.5, Math.abs(u1 - u0) * sd.colSp), hmm = Math.max(1.5, Math.abs(v1 - v0) * sd.rowSp);
    const base = this.fitScale();
    const wanted = Math.min((this.w * fill) / wmm, (this.h * fill) / hmm);
    this.zoom = Math.min(12, Math.max(0.4, wanted / base));
    this.panX = this.panY = 0;
    const t = this.transform();
    const [cx, cy] = this.imgToScreen((u0 + u1) / 2, (v0 + v1) / 2, t);
    this.panX = this.w / 2 - cx; this.panY = this.h / 2 - cy;
    this.invalidate();
  }

  // ---------- rendering ----------
  updateSlice() {
    const k = this.sliceIndexFromCrosshair();
    const sdv = this.ds.volume;
    if (k !== this.sliceIdx) {
      this.sliceIdx = k;
      sdv.extractSlice(this.def.axis, k, this.sliceBuf);
      if (this.labelBuf) this.ds.labels.extractSlice(this.def.axis, k, this.labelBuf);
      this.labelStats = null;
    }
    const { w, l } = this.store.get('settings').window;
    const lo = l - w / 2, scale = 255 / w;
    const buf = this.sliceBuf, px = this.imgData.data, n = buf.length;
    for (let i = 0; i < n; i++) {
      let g = (buf[i] - lo) * scale; g = g < 0 ? 0 : g > 255 ? 255 : g;
      const o = i * 4; px[o] = g; px[o + 1] = g; px[o + 2] = g; px[o + 3] = 255;
    }
    this.ctxImg().putImageData(this.imgData, 0, 0);
    this.el.dispatchEvent(new CustomEvent('slice', { bubbles: false }));
  }
  computeLabelStats() {
    // per label: count and centroid within this slice
    const lb = this.labelBuf; if (!lb) return null;
    const sd = this.sd, cols = sd.cols;
    const count = new Uint32Array(256), su = new Float64Array(256), sv = new Float64Array(256);
    for (let p = 0, n = lb.length; p < n; p++) { const L = lb[p]; if (L) { count[L]++; su[L] += (p % cols); sv[L] += Math.floor(p / cols); } }
    const out = [];
    for (let L = 1; L < 256; L++) if (count[L]) out.push({ label: L, id: this.ds.labelIdOf.get(L), count: count[L], u: su[L] / count[L] + 0.5, v: sv[L] / count[L] + 0.5 });
    return out;
  }
  buildMask(selLabel, hoverLabel) {
    const lb = this.labelBuf, md = this.maskData.data, sd = this.sd, cols = sd.cols, rows = sd.rows;
    md.fill(0);
    if (!lb || (!selLabel && !hoverLabel)) return false;
    const sel = [230, 176, 66], hov = [220, 226, 232];
    let any = false;
    for (let v = 0; v < rows; v++) for (let u = 0; u < cols; u++) {
      const p = v * cols + u, L = lb[p];
      if (!L || (L !== selLabel && L !== hoverLabel)) continue;
      any = true;
      const edge = (u === 0 || lb[p - 1] !== L) || (u === cols - 1 || lb[p + 1] !== L) || (v === 0 || lb[p - cols] !== L) || (v === rows - 1 || lb[p + cols] !== L);
      const c = L === selLabel ? sel : hov;
      const o = p * 4; md[o] = c[0]; md[o + 1] = c[1]; md[o + 2] = c[2];
      md[o + 3] = L === selLabel ? (edge ? 235 : 60) : (edge ? 150 : 28);
    }
    if (any) this.mask.getContext('2d').putImageData(this.maskData, 0, 0);
    return any;
  }
  render() {
    if (!this.ds || !this.w) return;
    this.updateSlice();
    const t = this.transform();
    const ctx = this.ctx, dpr = this.dpr;
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    ctx.fillStyle = '#06080a'; ctx.fillRect(0, 0, this.w, this.h);
    ctx.imageSmoothingEnabled = true; ctx.imageSmoothingQuality = 'high';
    ctx.save();
    ctx.translate(t.ox, t.oy);
    ctx.scale(this.flipX ? -1 : 1, this.flipY ? -1 : 1);
    ctx.drawImage(this.img, this.flipX ? -t.drawW : 0, this.flipY ? -t.drawH : 0, t.drawW, t.drawH);
    // structure mask
    const st = this.store.state;
    const selLabel = st.selectedId && this.ds.labelValueOf.get(st.selectedId);
    const hoverLabel = st.hoverId && st.hoverId !== st.selectedId && this.ds.labelValueOf.get(st.hoverId);
    const quizHide = st.quiz && st.quiz.hideNames;
    if (this.buildMask(selLabel || 0, (quizHide ? 0 : hoverLabel) || 0)) {
      ctx.imageSmoothingEnabled = false;
      ctx.drawImage(this.mask, this.flipX ? -t.drawW : 0, this.flipY ? -t.drawH : 0, t.drawW, t.drawH);
    }
    ctx.restore();
    this.renderOverlay(t);
    this.renderCorners(t);
  }
  renderOverlay(t) {
    const o = this.octx, dpr = this.dpr;
    o.setTransform(dpr, 0, 0, dpr, 0, 0);
    o.clearRect(0, 0, this.w, this.h);
    const c = this.store.get('crosshair');
    const [cx, cy] = this.worldToScreen(c, t);
    // crosshair: full-length hairlines with a gap at the centre
    o.strokeStyle = 'rgba(230,176,66,0.9)'; o.lineWidth = 1;
    const gap = 9;
    o.beginPath();
    o.moveTo(0, cy + 0.5); o.lineTo(cx - gap, cy + 0.5); o.moveTo(cx + gap, cy + 0.5); o.lineTo(this.w, cy + 0.5);
    o.moveTo(cx + 0.5, 0); o.lineTo(cx + 0.5, cy - gap); o.moveTo(cx + 0.5, cy + gap); o.lineTo(cx + 0.5, this.h);
    o.stroke();
    // labels
    this.renderLabels(o, t);
  }
  renderLabels(o, t) {
    const st = this.store.state, mode = st.settings.sliceLabels;
    if (!this.labelBuf || mode === 'off') return;
    if (st.quiz && st.quiz.hideNames) return;
    if (!this.labelStats) this.labelStats = this.computeLabelStats();
    const stats = this.labelStats; if (!stats) return;
    const depth = st.depth;
    const fontPx = this.labelFontPx();
    o.font = `500 ${fontPx}px "IBM Plex Sans", system-ui, sans-serif`;
    o.textBaseline = 'middle';
    const placed = [];
    const minCount = Math.max(6, 1600 / (t.s * t.s * t.sd.colSp * t.sd.rowSp) * 0.08);
    const items = stats.filter(s => {
      if (!s.id) return false;
      if (mode === 'selected') return s.id === st.selectedId;
      const def = STRUCTURE_BY_ID.get(s.id);
      if (s.id === st.selectedId) return true;
      if (s.count < minCount) return false;
      if (mode === 'all') return true;
      return def ? visibleAtDepth(def, depth) : false;
    });
    for (const s of items) {
      const [sx, sy] = this.imgToScreen(s.u, s.v, t);
      if (sx < 4 || sy < 4 || sx > this.w - 4 || sy > this.h - 4) continue;
      const name = structureName(s.id);
      const short = name.length > 30 ? name.split(',')[0] : name;
      const wText = o.measureText(short).width;
      let x = sx + 8, y = sy - 8;
      // nudge to avoid overlapping a previous label
      for (let tries = 0; tries < 4; tries++) {
        const clash = placed.some(p => Math.abs(p.x - x) < (p.w + wText) / 2 + 6 && Math.abs(p.y - y) < fontPx + 4);
        if (!clash) break;
        y += fontPx + 6;
      }
      if (x + wText + 8 > this.w) x = sx - wText - 8;
      placed.push({ x: x + wText / 2, y, w: wText });
      const sel = s.id === st.selectedId;
      o.fillStyle = 'rgba(6,8,10,0.72)';
      o.fillRect(x - 4, y - fontPx * 0.7, wText + 8, fontPx * 1.4);
      o.fillStyle = sel ? '#f3cf6f' : structureColor(s.id);
      o.fillText(short, x, y);
      o.strokeStyle = sel ? 'rgba(243,207,111,0.9)' : 'rgba(215,221,227,0.45)'; o.lineWidth = 1;
      o.beginPath(); o.moveTo(sx, sy); o.lineTo(x - 4, y); o.stroke();
    }
  }
  labelFontPx() { const ts = this.store.get('settings').textSize; return ts === 's' ? 10 : ts === 'l' ? 13 : 11.5; }
  renderCorners(t) {
    const vol = this.ds.volume, k = this.sliceIndexFromCrosshair();
    const a = AXIS_INDEX[this.def.axis];
    const pos = vol.origin[a] + k * vol.spacing[a];
    this.el.querySelector('.pane-pos').textContent = `${this.def.coord} ${pos.toFixed(1)} mm`;
    this.el.querySelector('.pane-idx').textContent = `slice ${k + 1} of ${vol.dims[a]}`;
    const { w, l } = this.store.get('settings').window;
    this.el.querySelector('.pane-wl').textContent = `W ${Math.round(w)}  L ${Math.round(l)}`;
    this.el.querySelector('.pane-zoom').textContent = Math.abs(this.zoom - 1) > 0.01 ? `${this.zoom.toFixed(1)}x` : '';
    const lab = this.def.labels, m = this.store.get('settings').mirror && this.plane !== 'sagittal';
    this.el.querySelector('.pane-orient.l').textContent = m ? lab.right : lab.left;
    this.el.querySelector('.pane-orient.r').textContent = m ? lab.left : lab.right;
    this.el.querySelector('.pane-orient.t').textContent = lab.top;
    this.el.querySelector('.pane-orient.b').textContent = lab.bottom;
  }

  // ---------- interaction ----------
  bindEvents() {
    const el = this.el;
    this.pointers = new Map();
    this.drag = null;
    el.addEventListener('contextmenu', e => e.preventDefault());
    el.addEventListener('pointerenter', () => this.store.set('activePane', this.plane));
    el.addEventListener('pointerdown', e => this.onDown(e));
    el.addEventListener('pointermove', e => this.onMove(e));
    el.addEventListener('pointerup', e => this.onUp(e));
    el.addEventListener('pointercancel', e => this.onUp(e));
    el.addEventListener('pointerleave', () => { this.tip.hidden = true; if (!this.drag) this.store.hover(null); });
    el.addEventListener('wheel', e => this.onWheel(e), { passive: false });
    el.addEventListener('dblclick', e => { if (e.target.closest('.pane-corner')) return; this.resetView(); });
  }
  local(e) { const r = this.el.getBoundingClientRect(); return [e.clientX - r.left, e.clientY - r.top]; }
  onDown(e) {
    if (!this.ds) return;
    if (e.target.closest('.pane-corner')) return;
    this.el.setPointerCapture(e.pointerId);
    const [x, y] = this.local(e);
    this.pointers.set(e.pointerId, { x, y });
    this.store.set('activePane', this.plane);
    if (this.store.get('scrollPlane') !== this.plane) this.store.set('scrollPlane', this.plane);
    this.tip.hidden = true;
    if (this.pointers.size === 2) {
      const pts = [...this.pointers.values()];
      this.drag = { mode: 'pinch', d0: Math.hypot(pts[0].x - pts[1].x, pts[0].y - pts[1].y), z0: this.zoom, mid0: [(pts[0].x + pts[1].x) / 2, (pts[0].y + pts[1].y) / 2], pan0: [this.panX, this.panY] };
      return;
    }
    if (e.button === 1 || e.button === 2 || (e.button === 0 && e.altKey)) { this.drag = { mode: 'pan', x0: x, y0: y, pan0: [this.panX, this.panY] }; return; }
    if (e.button === 0 && e.shiftKey) { const { w, l } = this.store.get('settings').window; this.drag = { mode: 'wl', x0: x, y0: y, w0: w, l0: l }; return; }
    if (e.button === 0) {
      this.drag = { mode: 'crosshair', x0: x, y0: y, moved: false, t: performance.now() };
      this.placeCrosshair(x, y);
    }
  }
  placeCrosshair(x, y) {
    const p = this.screenToWorld(x, y);
    this.store.setCrosshair(p, this.plane);
  }
  onMove(e) {
    if (!this.ds) return;
    const [x, y] = this.local(e);
    if (this.pointers.has(e.pointerId)) this.pointers.set(e.pointerId, { x, y });
    const d = this.drag;
    if (!d) { this.hoverAt(x, y); return; }
    if (d.mode === 'crosshair') { if (Math.hypot(x - d.x0, y - d.y0) > 2) d.moved = true; this.placeCrosshair(x, y); }
    else if (d.mode === 'pan') { this.panX = d.pan0[0] + (x - d.x0); this.panY = d.pan0[1] + (y - d.y0); this.invalidate(); }
    else if (d.mode === 'wl') {
      const w = Math.max(1, d.w0 + (x - d.x0) * 8), l = d.l0 + (y - d.y0) * -4;
      this.store.setting('window', { w, l }); this.store.state.settings.windowPreset = 'custom';
    } else if (d.mode === 'pinch' && this.pointers.size === 2) {
      const pts = [...this.pointers.values()];
      const dist = Math.hypot(pts[0].x - pts[1].x, pts[0].y - pts[1].y);
      const mid = [(pts[0].x + pts[1].x) / 2, (pts[0].y + pts[1].y) / 2];
      this.zoom = Math.min(12, Math.max(0.4, d.z0 * dist / (d.d0 || 1)));
      this.panX = d.pan0[0] + (mid[0] - d.mid0[0]); this.panY = d.pan0[1] + (mid[1] - d.mid0[1]);
      this.invalidate();
    }
  }
  onUp(e) {
    this.pointers.delete(e.pointerId);
    const d = this.drag;
    if (d && d.mode === 'crosshair' && !d.moved) {
      // click: select the structure under the cursor if there is one
      const st = this.store.state;
      if (st.settings.clickSelects && this.ds.labels && !(st.quiz && st.quiz.active)) {
        const id = this.ds.labelAt(this.store.get('crosshair'));
        if (id && STRUCTURE_BY_ID.has(id)) this.store.select(id);
      }
      this.store.emit('paneclick', { plane: this.plane });
    }
    if (this.pointers.size === 0) this.drag = null;
    else if (this.pointers.size === 1 && d && d.mode === 'pinch') this.drag = null;
  }
  hoverAt(x, y) {
    const st = this.store.state;
    const p = this.screenToWorld(x, y);
    const id = this.ds.labelAt(p);
    const quizHide = st.quiz && st.quiz.hideNames;
    if (id && STRUCTURE_BY_ID.has(id) && !quizHide) {
      this.store.hover(id);
      this.tip.textContent = structureName(id);
      this.tip.hidden = false;
      const r = this.el.getBoundingClientRect();
      const left = Math.min(x + 14, r.width - this.tip.offsetWidth - 6);
      this.tip.style.left = left + 'px'; this.tip.style.top = (y + 16) + 'px';
    } else { this.store.hover(null); this.tip.hidden = true; }
  }
  onWheel(e) {
    if (!this.ds) return;
    e.preventDefault();
    if (e.ctrlKey || e.metaKey) {
      const [x, y] = this.local(e);
      const t = this.transform();
      const [u, v] = this.screenToImg(x, y, t);
      const factor = Math.exp(-e.deltaY * 0.0015);
      this.zoom = Math.min(12, Math.max(0.4, this.zoom * factor));
      // keep the point under the cursor fixed
      const t2 = this.transform();
      const [sx, sy] = this.imgToScreen(u, v, t2);
      this.panX += x - sx; this.panY += y - sy;
      this.invalidate();
      return;
    }
    const dir = Math.sign(e.deltaY) || Math.sign(e.deltaX);
    if (this.store.get('scrollPlane') !== this.plane) this.store.set('scrollPlane', this.plane);
    if (!this.store.get('sectionArmed')) this.store.set('sectionArmed', true);
    if (dir) this.stepSlice(dir > 0 ? -1 : 1);
  }
}
