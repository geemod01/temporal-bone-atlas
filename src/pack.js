// Reader for the .tba data pack (see tools/tbapack.py) and helpers for building a dataset object.
import { Volume } from './volume.js';

export async function gunzip(bytes) {
  // bytes: Uint8Array (gzip). Uses the browser's DecompressionStream.
  if (bytes.length >= 2 && !(bytes[0] === 0x1f && bytes[1] === 0x8b)) return bytes; // not gzipped
  if (typeof DecompressionStream === 'undefined') throw new Error('This browser cannot decompress gzip (DecompressionStream missing). Use a current Chrome, Edge, Safari or Firefox.');
  const ds = new DecompressionStream('gzip');
  const stream = new Blob([bytes]).stream().pipeThrough(ds);
  const buf = await new Response(stream).arrayBuffer();
  return new Uint8Array(buf);
}

export function base64ToBytes(b64) {
  const bin = atob(b64);
  const out = new Uint8Array(bin.length);
  for (let i = 0; i < bin.length; i++) out[i] = bin.charCodeAt(i);
  return out;
}

const DTYPES = { int16: Int16Array, uint8: Uint8Array, float32: Float32Array, uint16: Uint16Array, int32: Int32Array };

export async function parsePack(bytes) {
  const raw = await gunzip(bytes);
  const magic = String.fromCharCode(raw[0], raw[1], raw[2], raw[3]);
  if (magic !== 'TBA1') throw new Error('Not a Temporal Bone Atlas pack (.tba)');
  const hlen = new DataView(raw.buffer, raw.byteOffset + 4, 4).getUint32(0, true);
  const header = JSON.parse(new TextDecoder().decode(raw.subarray(8, 8 + hlen)));
  let start = 8 + hlen; start += (4 - (start % 4)) % 4;
  const body = raw.subarray(start);
  // Ensure 4-byte alignment of the body for typed array views; copy if needed.
  const bodyAligned = ((body.byteOffset % 4) === 0) ? body : new Uint8Array(body);
  const blob = (name, Ctor) => {
    const b = header.blobs[name];
    if (!b) throw new Error('pack missing blob ' + name);
    const n = b.length / Ctor.BYTES_PER_ELEMENT;
    return new Ctor(bodyAligned.buffer, bodyAligned.byteOffset + b.offset, n);
  };
  const vmeta = header.volume;
  let vdata = blob(vmeta.blob, DTYPES[vmeta.dtype] || Int16Array);
  if (vmeta.encoding === 'delta-x') {
    // lossless: cumulative sum along x with 16-bit wrap-around
    const out = new Int16Array(vdata.length), nx = vmeta.dims[0];
    for (let row = 0; row < vdata.length; row += nx) {
      let acc = 0;
      for (let i = 0; i < nx; i++) { acc = (acc + vdata[row + i]) & 0xffff; out[row + i] = acc; }
    }
    vdata = out; // Int16Array view reinterprets the uint16 bits as signed
  }
  const volume = new Volume({ dims: vmeta.dims, spacing: vmeta.spacing, origin: vmeta.origin, data: vdata, dtype: vmeta.dtype });
  let labels = null;
  if (header.labels) {
    const l = header.labels;
    labels = new Volume({ dims: l.dims, spacing: l.spacing, origin: l.origin, data: blob(l.blob, Uint8Array), dtype: 'uint8' });
  }
  const meshes = (header.meshes || []).map(m => ({
    id: m.id, nv: m.nv, nf: m.nf, centroid: m.centroid, bbox: m.bbox,
    positions: blob(m.v, Float32Array), indices: blob(m.f, Uint32Array)
  }));
  return buildDataset({
    name: header.name, kind: header.kind, side: header.side || 'R', notes: header.notes || '',
    volume, labels, labelIds: header.labelIds || {}, meshes, landmarks: header.landmarks || {}
  });
}

// Normalises a dataset: id->mesh map, label name->value map, anchor lookup.
export function buildDataset(d) {
  d.meshById = new Map(d.meshes.map(m => [m.id, m]));
  d.labelValueOf = new Map(Object.entries(d.labelIds).map(([v, id]) => [id, Number(v)]));
  d.labelIdOf = new Map(Object.entries(d.labelIds).map(([v, id]) => [Number(v), id]));
  d.anchorOf = (id) => {
    if (d.landmarks && d.landmarks[id]) return d.landmarks[id];
    const m = d.meshById.get(id);
    if (m) return m.centroid;
    return null;
  };
  d.boundsOf = (id) => {
    const m = d.meshById.get(id);
    if (m) return { min: m.bbox.slice(0, 3), max: m.bbox.slice(3, 6) };
    if (d.labels && d.labelValueOf.has(id)) {
      if (!d._lb) d._lb = new Map();
      if (!d._lb.has(id)) d._lb.set(id, d.labels.labelBounds(d.labelValueOf.get(id)));
      return d._lb.get(id);
    }
    return null;
  };
  d.labelAt = (p) => {
    if (!d.labels) return null;
    const v = d.labels.sampleWorld(p);
    if (v === undefined || v === 0) return null;
    return d.labelIdOf.get(v) || null;
  };
  return d;
}
