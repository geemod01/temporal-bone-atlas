// Volume: a regular 3D grid in RAS millimetres, stored C-order [z][y][x] (x fastest).
export class Volume {
  constructor({ dims, spacing, origin, data, dtype }) {
    this.dims = dims;           // [nx, ny, nz]
    this.spacing = spacing;     // [sx, sy, sz] mm
    this.origin = origin;       // world of voxel (0,0,0)
    this.data = data;           // typed array
    this.dtype = dtype || 'int16';
    this.nx = dims[0]; this.ny = dims[1]; this.nz = dims[2];
    this.computeRange();
  }
  computeRange() {
    let mn = Infinity, mx = -Infinity;
    const d = this.data, n = d.length;
    const step = Math.max(1, Math.floor(n / 500000));
    for (let i = 0; i < n; i += step) { const v = d[i]; if (v < mn) mn = v; if (v > mx) mx = v; }
    this.min = mn; this.max = mx;
  }
  get extent() { // world bounds [xmin,ymin,zmin,xmax,ymax,zmax], voxel centres
    const o = this.origin, s = this.spacing, d = this.dims;
    return [o[0], o[1], o[2], o[0] + (d[0] - 1) * s[0], o[1] + (d[1] - 1) * s[1], o[2] + (d[2] - 1) * s[2]];
  }
  get center() {
    const e = this.extent;
    return [(e[0] + e[3]) / 2, (e[1] + e[4]) / 2, (e[2] + e[5]) / 2];
  }
  worldToVoxel(p) {
    return [(p[0] - this.origin[0]) / this.spacing[0], (p[1] - this.origin[1]) / this.spacing[1], (p[2] - this.origin[2]) / this.spacing[2]];
  }
  voxelToWorld(v) {
    return [this.origin[0] + v[0] * this.spacing[0], this.origin[1] + v[1] * this.spacing[1], this.origin[2] + v[2] * this.spacing[2]];
  }
  clampIndex(v) {
    return [Math.min(this.nx - 1, Math.max(0, Math.round(v[0]))), Math.min(this.ny - 1, Math.max(0, Math.round(v[1]))), Math.min(this.nz - 1, Math.max(0, Math.round(v[2])))];
  }
  inside(v) {
    return v[0] >= -0.5 && v[1] >= -0.5 && v[2] >= -0.5 && v[0] <= this.nx - 0.5 && v[1] <= this.ny - 0.5 && v[2] <= this.nz - 0.5;
  }
  at(i, j, k) { return this.data[(k * this.ny + j) * this.nx + i]; }
  sampleWorld(p) {
    const v = this.worldToVoxel(p);
    if (!this.inside(v)) return undefined;
    const c = this.clampIndex(v);
    return this.at(c[0], c[1], c[2]);
  }
  // Slice extraction. axis: 'z' (axial, rows=y cols=x), 'y' (coronal, rows=z cols=x), 'x' (sagittal, rows=z cols=y)
  sliceDims(axis) {
    if (axis === 'z') return { cols: this.nx, rows: this.ny, colSp: this.spacing[0], rowSp: this.spacing[1], count: this.nz };
    if (axis === 'y') return { cols: this.nx, rows: this.nz, colSp: this.spacing[0], rowSp: this.spacing[2], count: this.ny };
    return { cols: this.ny, rows: this.nz, colSp: this.spacing[1], rowSp: this.spacing[2], count: this.nx };
  }
  extractSlice(axis, idx, out) {
    const { nx, ny, nz, data } = this;
    if (axis === 'z') {
      const k = Math.min(nz - 1, Math.max(0, idx));
      const base = k * ny * nx;
      out.set(data.subarray(base, base + nx * ny));
    } else if (axis === 'y') {
      const j = Math.min(ny - 1, Math.max(0, idx));
      for (let k = 0; k < nz; k++) {
        const base = (k * ny + j) * nx;
        out.set(data.subarray(base, base + nx), k * nx);
      }
    } else {
      const i = Math.min(nx - 1, Math.max(0, idx));
      for (let k = 0; k < nz; k++) {
        const rowBase = k * ny;
        for (let j = 0; j < ny; j++) out[rowBase + j] = data[(k * ny + j) * nx + i];
      }
    }
    return out;
  }
  // Extent of a label value along each axis (voxel index bounds) — used by quiz/tours when no mesh
  labelBounds(label) {
    const { nx, ny, nz, data } = this;
    let x0 = nx, y0 = ny, z0 = nz, x1 = -1, y1 = -1, z1 = -1, n = 0, sx = 0, sy = 0, sz = 0;
    let p = 0;
    for (let k = 0; k < nz; k++) for (let j = 0; j < ny; j++) for (let i = 0; i < nx; i++, p++) {
      if (data[p] === label) {
        if (i < x0) x0 = i; if (i > x1) x1 = i; if (j < y0) y0 = j; if (j > y1) y1 = j; if (k < z0) z0 = k; if (k > z1) z1 = k;
        n++; sx += i; sy += j; sz += k;
      }
    }
    if (!n) return null;
    return { min: this.voxelToWorld([x0, y0, z0]), max: this.voxelToWorld([x1, y1, z1]), centroid: this.voxelToWorld([sx / n, sy / n, sz / n]), count: n };
  }
}

// A fine core volume inside a coarser wide-field one, presented as ONE grid at the core's spacing
// covering the union of both (the app sees a single, larger volume; the core region is served from the
// core data, the rest bilinearly from the context). Nothing of the union is materialised.
export class CompositeVolume {
  constructor(core, context) {
    this.core = core; this.context = context;
    this.spacing = core.spacing.slice();
    this.dtype = core.dtype;
    const s = this.spacing, ce = core.extent, xe = context.extent;
    // union extent, snapped to the core grid so core voxels map onto union voxels by an integer offset
    this.off = [0, 1, 2].map(a => Math.max(0, Math.ceil((ce[a] - xe[a]) / s[a] - 1e-6)));
    this.origin = [0, 1, 2].map(a => ce[a] - this.off[a] * s[a]);
    this.dims = [0, 1, 2].map(a => this.off[a] + core.dims[a] + Math.max(0, Math.floor((xe[a + 3] - ce[a + 3]) / s[a] + 1e-6)));
    this.nx = this.dims[0]; this.ny = this.dims[1]; this.nz = this.dims[2];
    this.min = Math.min(core.min, context.min); this.max = Math.max(core.max, context.max);
  }
  get extent() { const o = this.origin, s = this.spacing, d = this.dims; return [o[0], o[1], o[2], o[0] + (d[0] - 1) * s[0], o[1] + (d[1] - 1) * s[1], o[2] + (d[2] - 1) * s[2]]; }
  get center() { const e = this.extent; return [(e[0] + e[3]) / 2, (e[1] + e[4]) / 2, (e[2] + e[5]) / 2]; }
  worldToVoxel(p) { return [(p[0] - this.origin[0]) / this.spacing[0], (p[1] - this.origin[1]) / this.spacing[1], (p[2] - this.origin[2]) / this.spacing[2]]; }
  voxelToWorld(v) { return [this.origin[0] + v[0] * this.spacing[0], this.origin[1] + v[1] * this.spacing[1], this.origin[2] + v[2] * this.spacing[2]]; }
  inside(v) { return v[0] >= -0.5 && v[1] >= -0.5 && v[2] >= -0.5 && v[0] <= this.nx - 0.5 && v[1] <= this.ny - 0.5 && v[2] <= this.nz - 0.5; }
  sampleWorld(p) {
    const v = this.core.sampleWorld(p);
    return v !== undefined ? v : this.context.sampleWorld(p);
  }
  at(i, j, k) { return this.sampleWorld(this.voxelToWorld([i, j, k])); }
  sliceDims(axis) {
    if (axis === 'z') return { cols: this.nx, rows: this.ny, colSp: this.spacing[0], rowSp: this.spacing[1], count: this.nz };
    if (axis === 'y') return { cols: this.nx, rows: this.nz, colSp: this.spacing[0], rowSp: this.spacing[2], count: this.ny };
    return { cols: this.ny, rows: this.nz, colSp: this.spacing[1], rowSp: this.spacing[2], count: this.nx };
  }
  // union-grid slice: context (bilinear) everywhere, then the core copied over its own rectangle
  extractSlice(axis, idx, out) {
    const core = this.core, ctx = this.context, off = this.off, sd = this.sliceDims(axis);
    const cols = sd.cols, rows = sd.rows;
    const ca = axis === 'z' ? 2 : axis === 'y' ? 1 : 0;               // slice axis
    const ua = axis === 'x' ? 1 : 0, va = axis === 'z' ? 1 : 2;        // column axis, row axis
    const k = Math.min(this.dims[ca] - 1, Math.max(0, idx));
    const wk = this.origin[ca] + k * this.spacing[ca];
    // context sampling along the slice axis: bilinear in-plane, nearest along the slice axis
    const kc = Math.min(ctx.dims[ca] - 1, Math.max(0, Math.round((wk - ctx.origin[ca]) / ctx.spacing[ca])));
    const cs = [ctx.spacing[0], ctx.spacing[1], ctx.spacing[2]], co = ctx.origin, cd = ctx.dims, cdata = ctx.data;
    const stride = [1, cd[0], cd[0] * cd[1]];
    const nU = cd[ua] - 1, nV = cd[va] - 1;
    const baseK = kc * stride[ca];
    const vs = new Float64Array(rows), vi = new Int32Array(rows), vf = new Float64Array(rows);
    for (let r = 0; r < rows; r++) { let t = (this.origin[va] + r * this.spacing[va] - co[va]) / cs[va]; t = t < 0 ? 0 : t > nV ? nV : t; const i0 = Math.min(nV - 1, Math.floor(t)); vi[r] = i0; vf[r] = t - i0; }
    const ui = new Int32Array(cols), uf = new Float64Array(cols);
    for (let c = 0; c < cols; c++) { let t = (this.origin[ua] + c * this.spacing[ua] - co[ua]) / cs[ua]; t = t < 0 ? 0 : t > nU ? nU : t; const i0 = Math.min(nU - 1, Math.floor(t)); ui[c] = i0; uf[c] = t - i0; }
    const su = stride[ua], sv = stride[va];
    for (let r = 0; r < rows; r++) {
      const b0 = baseK + vi[r] * sv, b1 = b0 + sv, fv = vf[r], gv = 1 - fv, o = r * cols;
      for (let c = 0; c < cols; c++) {
        const p0 = b0 + ui[c] * su, p1 = b1 + ui[c] * su, fu = uf[c], gu = 1 - fu;
        out[o + c] = gv * (gu * cdata[p0] + fu * cdata[p0 + su]) + fv * (gu * cdata[p1] + fu * cdata[p1 + su]);
      }
    }
    // the core's own slice, if this slice passes through it
    const kk = k - off[ca];
    if (kk >= 0 && kk < core.dims[ca]) {
      const csd = core.sliceDims(axis);
      if (!this._coreBuf || this._coreBuf.length !== csd.cols * csd.rows) this._coreBuf = new Float32Array(csd.cols * csd.rows);
      core.extractSlice(axis, kk, this._coreBuf);
      const ou = off[ua], ov = off[va];
      for (let r = 0; r < csd.rows; r++) out.set(this._coreBuf.subarray(r * csd.cols, (r + 1) * csd.cols), (r + ov) * cols + ou);
    }
    return out;
  }
}

// Labels live on the core grid; this presents them on the union grid of a CompositeVolume.
export class OffsetLabels {
  constructor(labels, composite) {
    this.inner = labels; this.off = composite.off;
    this.dims = composite.dims; this.spacing = composite.spacing; this.origin = composite.origin;
    this.nx = this.dims[0]; this.ny = this.dims[1]; this.nz = this.dims[2];
    this.data = labels.data; this.dtype = 'uint8';
  }
  sliceDims(axis) { return this.inner.sliceDims.call(this, axis); }
  extractSlice(axis, idx, out) {
    out.fill(0);
    const ca = axis === 'z' ? 2 : axis === 'y' ? 1 : 0, ua = axis === 'x' ? 1 : 0, va = axis === 'z' ? 1 : 2;
    const kk = idx - this.off[ca], inner = this.inner;
    if (kk < 0 || kk >= inner.dims[ca]) return out;
    const sd = this.sliceDims(axis), isd = inner.sliceDims(axis);
    if (!this._buf || this._buf.length !== isd.cols * isd.rows) this._buf = new Uint8Array(isd.cols * isd.rows);
    inner.extractSlice(axis, kk, this._buf);
    const ou = this.off[ua], ov = this.off[va];
    for (let r = 0; r < isd.rows; r++) out.set(this._buf.subarray(r * isd.cols, (r + 1) * isd.cols), (r + ov) * sd.cols + ou);
    return out;
  }
  sampleWorld(p) { return this.inner.sampleWorld(p); }
  labelBounds(label) { return this.inner.labelBounds(label); }
  worldToVoxel(p) { return this.inner.worldToVoxel(p); }
  voxelToWorld(v) { return this.inner.voxelToWorld(v); }
}
