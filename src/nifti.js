// Minimal NIfTI-1 reader producing a RAS Volume. Handles axis-aligned affines by flipping/permuting axes.
import { Volume } from './volume.js';
import { gunzip } from './pack.js';

const DT = { 2: Uint8Array, 4: Int16Array, 8: Int32Array, 16: Float32Array, 64: Float64Array, 256: Int8Array, 512: Uint16Array, 768: Uint32Array };

export async function parseNifti(bytes) {
  const raw = await gunzip(bytes);
  const dv = new DataView(raw.buffer, raw.byteOffset, raw.byteLength);
  let little = true;
  let hdrSize = dv.getInt32(0, true);
  if (hdrSize !== 348) { little = false; hdrSize = dv.getInt32(0, false); }
  if (hdrSize !== 348) throw new Error('Not a NIfTI-1 file');
  const dim = []; for (let i = 0; i < 8; i++) dim.push(dv.getInt16(40 + i * 2, little));
  const datatype = dv.getInt16(70, little);
  const bitpix = dv.getInt16(72, little);
  const pixdim = []; for (let i = 0; i < 8; i++) pixdim.push(dv.getFloat32(76 + i * 4, little));
  const voxOffset = dv.getFloat32(108, little);
  const sclSlope = dv.getFloat32(112, little) || 1;
  const sclInter = dv.getFloat32(116, little) || 0;
  const qformCode = dv.getInt16(252, little);
  const sformCode = dv.getInt16(254, little);
  const srow = [];
  for (let i = 0; i < 12; i++) srow.push(dv.getFloat32(280 + i * 4, little));
  const nx = dim[1], ny = dim[2], nz = Math.max(1, dim[3]);
  const Ctor = DT[datatype];
  if (!Ctor) throw new Error('Unsupported NIfTI datatype ' + datatype);
  const n = nx * ny * nz;
  const off = Math.round(voxOffset);
  let data;
  const slice = raw.buffer.slice(raw.byteOffset + off, raw.byteOffset + off + n * (bitpix / 8));
  if (little === ((new Uint8Array(new Uint16Array([1]).buffer))[0] === 1)) {
    data = new Ctor(slice);
  } else {
    // byte swap
    const view = new DataView(slice);
    data = new Ctor(n);
    const bpe = Ctor.BYTES_PER_ELEMENT;
    const getter = { 1: 'getInt8', 2: 'getInt16', 4: 'getFloat32', 8: 'getFloat64' }[bpe];
    for (let i = 0; i < n; i++) data[i] = view[getter](i * bpe, little);
  }
  // affine: prefer sform, else qform-less fallback with pixdim
  let aff;
  if (sformCode > 0) aff = srow;
  else aff = [pixdim[1], 0, 0, 0, 0, pixdim[2], 0, 0, 0, 0, pixdim[3], 0];
  // Determine, for each voxel axis, which world axis it maps to and the sign.
  const cols = [[aff[0], aff[4], aff[8]], [aff[1], aff[5], aff[9]], [aff[2], aff[6], aff[10]]]; // voxel axis i -> world vector
  const perm = [0, 0, 0], sign = [1, 1, 1], sp = [0, 0, 0];
  for (let i = 0; i < 3; i++) {
    const c = cols[i];
    let best = 0;
    for (let a = 1; a < 3; a++) if (Math.abs(c[a]) > Math.abs(c[best])) best = a;
    perm[i] = best; sign[i] = c[best] < 0 ? -1 : 1; sp[i] = Math.hypot(c[0], c[1], c[2]) || Math.abs(pixdim[i + 1]) || 1;
  }
  const origin0 = [aff[3], aff[7], aff[11]];
  // Reorder into RAS (+x = R, +y = A, +z = S). Supports permutations and flips; oblique scans are approximated.
  const dimsIn = [nx, ny, nz];
  const outDims = [0, 0, 0], outSp = [0, 0, 0];
  for (let i = 0; i < 3; i++) { outDims[perm[i]] = dimsIn[i]; outSp[perm[i]] = sp[i]; }
  const isIdentity = perm[0] === 0 && perm[1] === 1 && perm[2] === 2 && sign.every(s => s === 1);
  let out, outOrigin = [0, 0, 0];
  if (isIdentity) { out = data; outOrigin = origin0; }
  else {
    out = new Ctor(n);
    // world coordinate of input voxel (i,j,k): origin0 + i*col0 + j*col1 + k*col2. For out index along world axis w:
    // input axis a = perm^-1[w]; index along a maps to out index = sign>0 ? idx : (dimsIn[a]-1-idx)
    const inv = [0, 0, 0]; for (let i = 0; i < 3; i++) inv[perm[i]] = i;
    const [ox, oy, oz] = outDims;
    for (let k = 0; k < nz; k++) for (let j = 0; j < ny; j++) for (let i = 0; i < nx; i++) {
      const idx = [i, j, k];
      const o = [0, 0, 0];
      for (let a = 0; a < 3; a++) { const w = perm[a]; o[w] = sign[a] > 0 ? idx[a] : (dimsIn[a] - 1 - idx[a]); }
      out[(o[2] * oy + o[1]) * ox + o[0]] = data[(k * ny + j) * nx + i];
    }
    // origin: world position of out voxel (0,0,0) = min corner along each world axis
    for (let w = 0; w < 3; w++) {
      const a = inv[w];
      const start = origin0[w];
      const endAlong = origin0[w] + cols[a][w] * (dimsIn[a] - 1);
      outOrigin[w] = Math.min(start, endAlong);
    }
    // Other axes' contributions (for pure permutations the off-diagonal terms are ~0)
  }
  let vol = new Volume({ dims: outDims, spacing: outSp, origin: outOrigin, data: out, dtype: Ctor === Int16Array ? 'int16' : Ctor.name.toLowerCase().replace('array', '') });
  if ((sclSlope !== 1 || sclInter !== 0) && !(sclSlope === 0)) {
    const f = new Float32Array(vol.data.length);
    for (let i = 0; i < f.length; i++) f[i] = vol.data[i] * sclSlope + sclInter;
    vol = new Volume({ dims: outDims, spacing: outSp, origin: outOrigin, data: f, dtype: 'float32' });
  }
  return vol;
}
