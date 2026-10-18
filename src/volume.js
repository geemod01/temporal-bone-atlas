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
