// Binary and ASCII STL reader -> { positions: Float32Array, indices: Uint32Array, centroid, bbox }
export function parseSTL(bytes) {
  const isAscii = (() => {
    const head = new TextDecoder().decode(bytes.subarray(0, Math.min(256, bytes.length)));
    if (!head.trim().startsWith('solid')) return false;
    // binary files can also start with 'solid'; check the facet keyword
    return /facet\s+normal/i.test(new TextDecoder().decode(bytes.subarray(0, Math.min(2000, bytes.length))));
  })();
  let tri;
  if (isAscii) {
    const txt = new TextDecoder().decode(bytes);
    const re = /vertex\s+([-+\d.eE]+)\s+([-+\d.eE]+)\s+([-+\d.eE]+)/g;
    const vals = [];
    let m;
    while ((m = re.exec(txt))) vals.push(+m[1], +m[2], +m[3]);
    tri = new Float32Array(vals);
  } else {
    const dv = new DataView(bytes.buffer, bytes.byteOffset, bytes.byteLength);
    const nf = dv.getUint32(80, true);
    tri = new Float32Array(nf * 9);
    let p = 84;
    for (let f = 0; f < nf; f++) {
      p += 12; // normal
      for (let v = 0; v < 9; v++) { tri[f * 9 + v] = dv.getFloat32(p, true); p += 4; }
      p += 2;
    }
  }
  return weld(tri);
}

// Merge identical vertices so normals are smooth.
export function weld(tri) {
  const nv = tri.length / 3;
  const map = new Map();
  const positions = [];
  const indices = new Uint32Array(nv);
  for (let i = 0; i < nv; i++) {
    const x = tri[i * 3], y = tri[i * 3 + 1], z = tri[i * 3 + 2];
    const key = (Math.round(x * 1000)) + ',' + (Math.round(y * 1000)) + ',' + (Math.round(z * 1000));
    let idx = map.get(key);
    if (idx === undefined) { idx = positions.length / 3; map.set(key, idx); positions.push(x, y, z); }
    indices[i] = idx;
  }
  const pos = new Float32Array(positions);
  return finishMesh(pos, indices);
}

export function finishMesh(positions, indices) {
  const n = positions.length / 3;
  let x0 = Infinity, y0 = Infinity, z0 = Infinity, x1 = -Infinity, y1 = -Infinity, z1 = -Infinity, sx = 0, sy = 0, sz = 0;
  for (let i = 0; i < n; i++) {
    const x = positions[i * 3], y = positions[i * 3 + 1], z = positions[i * 3 + 2];
    if (x < x0) x0 = x; if (x > x1) x1 = x; if (y < y0) y0 = y; if (y > y1) y1 = y; if (z < z0) z0 = z; if (z > z1) z1 = z;
    sx += x; sy += y; sz += z;
  }
  return { positions, indices, nv: n, nf: indices.length / 3, centroid: [sx / n, sy / n, sz / n], bbox: [x0, y0, z0, x1, y1, z1] };
}
