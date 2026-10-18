#!/usr/bin/env python3
"""
Convert real imaging into a Temporal Bone Atlas data pack (.tba).

Works for an OpenEar specimen (CBCT + the segmentation STL files), for a 3D Slicer
export (NIfTI/NRRD volume + exported STL/OBJ models), or for any temporal bone CT
with or without meshes.

Examples
--------
  # OpenEar specimen "Delta" (adjust paths to where the archive was unpacked)
  python3 tools/convert_openear.py --volume Delta/CBCT --meshes Delta/Models \\
      --name "OpenEar Delta (right)" --side R --spacing 0.3 --labels --out dist/openear_delta.tba

  # A clinical temporal bone CT exported from Slicer with a few segmented structures
  python3 tools/convert_openear.py --volume case1.nii.gz --meshes case1_models --mesh-frame LPS \\
      --intensity hu --name "Case 1 right" --out case1.tba

  # Volume only (no meshes): the app still works for tri-planar reading; set structure
  # locations later in author mode and keep them in a landmarks.json next to the pack.
  python3 tools/convert_openear.py --volume case2.nii.gz --crop none --out case2.tba

Notes
-----
* Output frame is RAS millimetres, isotropic, C-order [z][y][x].
* SimpleITK reads DICOM, NIfTI and NRRD; everything is converted from ITK's LPS to RAS here.
* Mesh files: STL, OBJ, PLY (anything trimesh loads). --mesh-frame says which frame they are
  in (3D Slicer exports LPS by default; the phantom and most research datasets use RAS).
* Structure ids are matched from file names with --map (JSON of id -> list of substrings).
  Unmatched files keep a sanitised file name as id and are listed at the end so you can
  extend the map. See tools/openear_map.json for the default map.
* The OpenEar archives are large; this script reads only what it needs but still expects
  the whole specimen folder on disk.
"""
import argparse
import glob
import json
import os
import re
import sys

import numpy as np

sys.path.insert(0, os.path.dirname(__file__))
from tbapack import write_pack, delta_encode_int16  # noqa: E402

try:
    import SimpleITK as sitk
except ImportError:
    sitk = None
try:
    import trimesh
except ImportError:
    trimesh = None
try:
    import fast_simplification
except ImportError:
    fast_simplification = None


DEFAULT_MAP = os.path.join(os.path.dirname(__file__), 'openear_map.json')


def log(*a):
    print(*a, file=sys.stderr)


# --------------------------------------------------------------------------
# Volume
# --------------------------------------------------------------------------
class LazyVolume:
    """Header-only handle on a volume file; reads voxels only for a requested index region."""

    def __init__(self, path):
        r = sitk.ImageFileReader(); r.SetFileName(path); r.ReadImageInformation()
        self.path = path
        self.size = tuple(int(x) for x in r.GetSize())
        self.spacing = tuple(float(x) for x in r.GetSpacing())
        self.origin = tuple(float(x) for x in r.GetOrigin())
        self.direction = tuple(float(x) for x in r.GetDirection())
        self.pixel_type = sitk.GetPixelIDValueAsString(r.GetPixelID())
        # a tiny image carrying the geometry, so Transform*Point works without voxels
        self._geo = sitk.Image([1, 1, 1], sitk.sitkUInt8)
        self._geo.SetSpacing(self.spacing); self._geo.SetOrigin(self.origin); self._geo.SetDirection(self.direction)

    def GetSize(self): return self.size
    def GetSpacing(self): return self.spacing
    def GetOrigin(self): return self.origin
    def GetDirection(self): return self.direction
    def TransformIndexToPhysicalPoint(self, idx): return self._geo.TransformIndexToPhysicalPoint(tuple(int(i) for i in idx))
    def TransformPhysicalPointToContinuousIndex(self, p): return self._geo.TransformPhysicalPointToContinuousIndex(tuple(float(x) for x in p))

    def read_region(self, index, size):
        r = sitk.ImageFileReader(); r.SetFileName(self.path)
        r.SetExtractIndex([int(x) for x in index]); r.SetExtractSize([int(x) for x in size])
        try:
            return r.Execute()
        except Exception as e:
            # some formats cannot stream (e.g. gzip-compressed NRRD): read whole, crop, release
            log('  streaming read unavailable (%s); reading whole volume then cropping' % str(e).splitlines()[0][:80])
            whole = sitk.ReadImage(self.path)
            return sitk.RegionOfInterest(whole, [int(x) for x in size], [int(x) for x in index])

    def read_all(self):
        return sitk.ReadImage(self.path)


def read_volume(path):
    if sitk is None:
        raise SystemExit('SimpleITK is required: pip install SimpleITK')
    if os.path.isdir(path):
        reader = sitk.ImageSeriesReader()
        ids = reader.GetGDCMSeriesIDs(path)
        if not ids:
            # maybe a folder with a single NIfTI/NRRD
            cands = [f for f in glob.glob(os.path.join(path, '*')) if re.search(r'\.(nii|nii\.gz|nrrd|nhdr|mha|mhd)$', f, re.I)]
            if not cands:
                raise SystemExit('No DICOM series or volume file found in ' + path)
            log('reading volume', cands[0])
            return sitk.ReadImage(cands[0])
        if len(ids) > 1:
            log('found %d DICOM series; using the first (%s). Use a folder with one series to pick another.' % (len(ids), ids[0]))
        files = reader.GetGDCMSeriesFileNames(path, ids[0])
        reader.SetFileNames(files)
        img = reader.Execute()
        log('read DICOM series: %d slices' % len(files))
        return img
    log('opening volume header', path)
    return LazyVolume(path)


def lps_to_ras_point(p):
    return np.array([-p[0], -p[1], p[2]], dtype=np.float64)


def resample_to_ras(img, spacing, crop_ras=None, interpolator=sitk.sitkLinear if sitk else None):
    """Crop (in index space) to the requested RAS box, then resample to isotropic spacing with identity
    direction (in LPS). Returns array in RAS order. With a LazyVolume only the crop region is ever read."""
    lazy = isinstance(img, LazyVolume)
    size = np.array(img.GetSize())
    corners = []
    for i in (0, size[0] - 1):
        for j in (0, size[1] - 1):
            for k in (0, size[2] - 1):
                corners.append(img.TransformIndexToPhysicalPoint((int(i), int(j), int(k))))
    corners = np.array(corners)
    lo, hi = corners.min(0), corners.max(0)
    if crop_ras is not None:
        cx0, cx1, cy0, cy1, cz0, cz1 = crop_ras
        clo = np.array([-cx1, -cy1, cz0]); chi = np.array([-cx0, -cy0, cz1])
        lo = np.maximum(lo, clo); hi = np.minimum(hi, chi)
        # index-space crop with a margin, so the resample only touches the region of interest
        idx = []
        for px in (lo[0], hi[0]):
            for py in (lo[1], hi[1]):
                for pz in (lo[2], hi[2]):
                    idx.append(img.TransformPhysicalPointToContinuousIndex((float(px), float(py), float(pz))))
        idx = np.array(idx)
        i0 = np.maximum(np.floor(idx.min(0)).astype(int) - 2, 0)
        i1 = np.minimum(np.ceil(idx.max(0)).astype(int) + 3, size)
        if np.all(i1 > i0):
            if lazy:
                img = img.read_region(i0, i1 - i0)
            else:
                img = sitk.RegionOfInterest(img, [int(x) for x in (i1 - i0)], [int(x) for x in i0])
            log('cropped input to %s voxels before resampling' % list(img.GetSize()))
    if isinstance(img, LazyVolume):
        log('reading whole volume (no crop)')
        img = img.read_all()
    out_size = np.maximum(1, np.ceil((hi - lo) / spacing).astype(int) + 1)
    ref = sitk.Image([int(x) for x in out_size], sitk.sitkFloat32)
    ref.SetSpacing([spacing] * 3)
    ref.SetOrigin([float(x) for x in lo])
    ref.SetDirection([1, 0, 0, 0, 1, 0, 0, 0, 1])
    out = sitk.Resample(img, ref, sitk.Transform(), interpolator, -1024.0, sitk.sitkFloat32)
    arr = sitk.GetArrayFromImage(out)  # (z, y, x) with +x = L, +y = P
    arr = arr[:, ::-1, ::-1]           # flip to +x = R, +y = A
    nx, ny, nz = out_size
    origin_ras = np.array([-(lo[0] + (nx - 1) * spacing), -(lo[1] + (ny - 1) * spacing), lo[2]])
    return np.ascontiguousarray(arr), origin_ras, np.array([spacing] * 3)


def intensity_to_hu(arr, mode):
    if mode == 'hu':
        return arr
    if mode.startswith('scale:'):
        a, b = [float(x) for x in mode.split(':')[1].split(',')]
        return arr * a + b
    # auto: decide whether the data already looks like HU
    p1, p50, p99 = np.percentile(arr, [1, 50, 99])
    if p1 < -500 and p99 < 4000:
        log('intensity looks like HU already (p1=%.0f, p99=%.0f)' % (p1, p99))
        return arr
    log('intensity does not look like HU (p1=%.0f, p50=%.0f, p99=%.0f); mapping p1->-1000 and p99->2200' % (p1, p50, p99))
    if p99 <= p1:
        return arr
    return (arr - p1) / (p99 - p1) * 3200.0 - 1000.0


# --------------------------------------------------------------------------
# Meshes
# --------------------------------------------------------------------------
def load_map(path):
    with open(path) as f:
        mapping = json.load(f)
    # every atlas structure id is also a pattern, so Slicer exports named after the cards map directly
    content_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'content')
    for cf in glob.glob(os.path.join(content_dir, 'structures_*.json')):
        try:
            with open(cf) as f:
                for card in json.load(f):
                    mapping.setdefault(card['id'], [])
        except Exception:
            pass
    return mapping


def match_id(fname, mapping):
    base = os.path.splitext(os.path.basename(fname))[0].lower()
    hay = base + '.'   # a trailing sentinel lets patterns like "cochlea." match a name that ends in cochlea
    best = None
    for sid, pats in mapping.items():
        for p in list(pats) + [sid, sid + '.']:   # the atlas id itself always counts as a pattern
            if p.lower() in hay:
                if best is None or len(p) > best[1]:
                    best = (sid, len(p))
    if best:
        return best[0], True
    return re.sub(r'[^a-z0-9]+', '_', base).strip('_'), False


def load_mesh_raw(path, scale):
    m = trimesh.load(path, force='mesh')
    if m.is_empty:
        return None
    return np.asarray(m.vertices, dtype=np.float64) * scale, np.asarray(m.faces, dtype=np.int64)


def to_frame(v, f, frame):
    if frame.upper() == 'LPS':
        return v * np.array([-1.0, -1.0, 1.0]), f[:, ::-1]  # keep outward orientation after the mirror
    return v, f


def inside_fraction(v, bounds):
    lo, hi = bounds
    ok = np.all((v >= lo) & (v <= hi), axis=1)
    return float(ok.mean()) if len(v) else 0.0


def decimate(v, f, target_faces):
    if fast_simplification is not None and target_faces and len(f) > target_faces:
        red = 1.0 - target_faces / len(f)
        v2, f2 = fast_simplification.simplify(v.astype(np.float32), f.astype(np.int32), target_reduction=float(red))
        v, f = np.asarray(v2, np.float64), np.asarray(f2, np.int64)
    used = np.unique(f)
    remap = -np.ones(len(v), np.int64); remap[used] = np.arange(len(used))
    v = v[used]; f = remap[f]
    return v.astype(np.float32), f.astype(np.uint32)


def voxelize(mesh_v, mesh_f, origin, spacing, dims, max_voxels=None):
    """Boolean mask (z,y,x) of voxels whose centres lie inside the (closed) mesh.

    Parity rasterisation: for every triangle, find the voxel columns (x,y) whose centre
    projects inside it and record the z of the crossing; inside = between crossing pairs.
    No external ray-tracing dependency, fast enough for tens of thousands of triangles.
    """
    v = np.asarray(mesh_v, np.float64)
    f = np.asarray(mesh_f, np.int64)
    ox, oy, oz = origin
    sx, sy, sz = spacing
    nx, ny, nz = dims
    eps = 1e-4 * sx  # jitter so shared edges are counted once
    tri = v[f]
    cols_i, cols_j, zs = [], [], []
    for t in range(len(tri)):
        p0, p1, p2 = tri[t]
        xmin, xmax = min(p0[0], p1[0], p2[0]), max(p0[0], p1[0], p2[0])
        ymin, ymax = min(p0[1], p1[1], p2[1]), max(p0[1], p1[1], p2[1])
        i0 = max(0, int(np.ceil((xmin - ox - eps) / sx))); i1 = min(nx - 1, int(np.floor((xmax - ox - eps) / sx)))
        j0 = max(0, int(np.ceil((ymin - oy - eps) / sy))); j1 = min(ny - 1, int(np.floor((ymax - oy - eps) / sy)))
        if i1 < i0 or j1 < j0:
            continue
        xs = ox + np.arange(i0, i1 + 1) * sx + eps
        ys = oy + np.arange(j0, j1 + 1) * sy + eps
        X, Y = np.meshgrid(xs, ys, indexing='ij')
        # barycentric coordinates in XY
        d = (p1[1] - p2[1]) * (p0[0] - p2[0]) + (p2[0] - p1[0]) * (p0[1] - p2[1])
        if abs(d) < 1e-12:
            continue
        l0 = ((p1[1] - p2[1]) * (X - p2[0]) + (p2[0] - p1[0]) * (Y - p2[1])) / d
        l1 = ((p2[1] - p0[1]) * (X - p2[0]) + (p0[0] - p2[0]) * (Y - p2[1])) / d
        l2 = 1.0 - l0 - l1
        inside = (l0 >= 0) & (l1 >= 0) & (l2 >= 0)
        if not inside.any():
            continue
        z = l0 * p0[2] + l1 * p1[2] + l2 * p2[2]
        I, J = np.nonzero(inside)
        cols_i.append(I + i0); cols_j.append(J + j0); zs.append(z[inside])
    mask = np.zeros((nz, ny, nx), bool)
    if not cols_i:
        return mask
    I = np.concatenate(cols_i); J = np.concatenate(cols_j); Z = np.concatenate(zs)
    key = I * ny + J
    order = np.lexsort((Z, key))
    I, J, Z, key = I[order], J[order], Z[order], key[order]
    # crossing index within each column
    starts = np.r_[0, np.nonzero(np.diff(key))[0] + 1]
    counts = np.diff(np.r_[starts, len(key)])
    for s0, c in zip(starts, counts):
        if c < 2:
            continue
        zz = Z[s0:s0 + c]
        i, j = I[s0], J[s0]
        for k in range(0, c - 1, 2):
            k0 = int(np.ceil((zz[k] - oz) / sz)); k1 = int(np.floor((zz[k + 1] - oz) / sz))
            if k1 >= k0:
                mask[max(0, k0):min(nz, k1 + 1), j, i] = True
    return mask


def labels_from_volume(path, names_json, origin, spacing, dims, meshes, mapping):
    """Resample a label map onto the pack grid (nearest neighbour) and map its values to atlas ids.

    Value -> name comes from (in order): --label-names JSON, Slicer .seg.nrrd header fields
    (SegmentN_Name / SegmentN_LabelValue), 'labelN=name'-style header keys, or, failing all,
    the mesh whose surface best overlaps each label value.
    """
    log('reading label volume', path)
    img = sitk.ReadImage(path)
    names = {}
    if names_json and os.path.exists(names_json):
        with open(names_json) as f:
            names = {int(k): v for k, v in json.load(f).items()}
    else:
        keys = img.GetMetaDataKeys()
        seg = {}
        for k in keys:
            m = re.match(r'Segment(\d+)_(Name|LabelValue)$', k)
            if m:
                seg.setdefault(int(m.group(1)), {})[m.group(2)] = img.GetMetaData(k)
        for d in seg.values():
            if 'Name' in d and 'LabelValue' in d:
                try:
                    names[int(d['LabelValue'])] = d['Name']
                except ValueError:
                    pass
        if not names:
            for k in keys:
                m = re.match(r'(?:label|value)[_ ]?(\d+)$', k, re.I)
                if m:
                    names[int(m.group(1))] = img.GetMetaData(k)
    # resample onto the pack grid: build the reference image in LPS matching our RAS grid
    nx, ny, nz = dims
    ox, oy, oz = origin
    lo_lps = [-(ox + (nx - 1) * spacing[0]), -(oy + (ny - 1) * spacing[1]), oz]
    ref = sitk.Image([int(nx), int(ny), int(nz)], sitk.sitkUInt16)
    ref.SetSpacing([float(x) for x in spacing]); ref.SetOrigin([float(x) for x in lo_lps]); ref.SetDirection([1, 0, 0, 0, 1, 0, 0, 0, 1])
    if 'vector' in img.GetPixelIDTypeAsString().lower():
        img = sitk.VectorIndexSelectionCast(img, 0)
    img = sitk.Cast(img, sitk.sitkUInt16)
    out = sitk.Resample(img, ref, sitk.Transform(), sitk.sitkNearestNeighbor, 0, sitk.sitkUInt16)
    arr = sitk.GetArrayFromImage(out)[:, ::-1, ::-1]
    values = [int(v) for v in np.unique(arr) if v != 0]
    log('label volume: %d non-zero values%s' % (len(values), (' with names: ' + ', '.join('%d=%s' % (v, names.get(v, '?')) for v in values)) if names else ''))
    # value -> atlas id
    id_of = {}
    unmatched = []
    for v in values:
        nm = names.get(v)
        if nm:
            sid, ok = match_id(nm + '.x', mapping)
            id_of[v] = sid
            if not ok:
                unmatched.append((v, nm, sid))
    if meshes and len(id_of) < len(values):
        # overlap-based matching for unnamed values: which mesh's vertices fall inside each label
        for v in values:
            if v in id_of:
                continue
            best, best_frac = None, 0.0
            for m in meshes:
                pts = m['v'][::max(1, len(m['v']) // 4000)]
                idx = np.round((pts - origin) / spacing).astype(int)
                ok = np.all((idx >= 0) & (idx < np.array(dims)), axis=1)
                if not ok.any():
                    continue
                idx = idx[ok]
                # surfaces sit on the boundary: look at the label 1 voxel inward along the vertex normal is overkill; use a small neighbourhood
                hits = 0
                for dz, dy, dx in ((0, 0, 0), (0, 0, 1), (0, 0, -1), (0, 1, 0), (0, -1, 0), (1, 0, 0), (-1, 0, 0)):
                    j = idx + np.array([dx, dy, dz]); j = np.clip(j, 0, np.array(dims) - 1)
                    hits += (arr[j[:, 2], j[:, 1], j[:, 0]] == v).sum()
                frac = hits / (7.0 * len(idx))
                if frac > best_frac:
                    best, best_frac = m['id'], frac
            if best and best_frac > 0.05:
                id_of[v] = best
                log('  label %d -> %s (by overlap %.0f%%)' % (v, best, best_frac * 100))
            else:
                id_of[v] = 'label_%d' % v
                unmatched.append((v, None, id_of[v]))
    # merge values that map to the same id, renumber 1..n, drop to uint8
    ids = []
    for v in values:
        sid = id_of.get(v, 'label_%d' % v)
        if sid not in ids:
            ids.append(sid)
    if len(ids) > 255:
        log('WARNING: more than 255 labels; keeping the first 255')
        ids = ids[:255]
    lut = np.zeros(int(arr.max()) + 1, np.uint8)
    for v in values:
        sid = id_of.get(v, 'label_%d' % v)
        if sid in ids:
            lut[v] = ids.index(sid) + 1
    labels = lut[arr]
    label_ids = {str(i + 1): sid for i, sid in enumerate(ids)}
    for v, nm, sid in unmatched:
        log('  unmatched label value %d (%s) kept as %s' % (v, nm, sid))
    for sid in ids:
        if sid == 'bone_shell' or sid == 'bone':
            # bone is background in the atlas; keep it only if the user wants it (rarely useful as a label)
            pass
    return labels, label_ids


# --------------------------------------------------------------------------
def main(argv=None):
    log('converter main() entered')
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--volume', required=True, help='DICOM folder or NIfTI/NRRD file')
    ap.add_argument('--meshes', help='folder with STL/OBJ/PLY files')
    ap.add_argument('--map', default=DEFAULT_MAP, help='JSON mapping structure id -> file-name substrings')
    ap.add_argument('--mesh-frame', default='auto', choices=['RAS', 'LPS', 'ras', 'lps', 'auto'], help='frame of the mesh coordinates; auto picks the one that lands inside the volume')
    ap.add_argument('--mesh-scale', type=float, default=1.0, help='multiply mesh coordinates (e.g. 0.001 for micrometres)')
    ap.add_argument('--target-faces', type=int, default=12000, help='decimate meshes above this many faces')
    ap.add_argument('--spacing', type=float, default=0.3, help='output isotropic voxel size in mm')
    ap.add_argument('--crop', default='auto', help="'auto' (meshes bbox + margin), 'none', or x0,x1,y0,y1,z0,z1 in RAS mm")
    ap.add_argument('--margin', type=float, default=6.0, help='margin around the mesh bbox for auto crop (mm)')
    ap.add_argument('--intensity', default='auto', help="'auto', 'hu', or 'scale:a,b' (HU = a*value + b)")
    ap.add_argument('--labels', action='store_true', help='voxelise meshes into a label volume (enables outlines, click-to-select and quiz checks)')
    ap.add_argument('--label-volume', help='segmentation volume (NRRD/NIfTI label map, e.g. OpenEar segmentation) resampled onto the pack grid; preferred over --labels')
    ap.add_argument('--label-names', help='JSON {value: name} for --label-volume when the file carries no names')
    ap.add_argument('--landmarks', help='landmarks.json (from the app or hand-written) to merge')
    ap.add_argument('--name', default=None)
    ap.add_argument('--side', default='R', choices=['R', 'L'])
    ap.add_argument('--notes', default='')
    ap.add_argument('--out', required=True)
    a = ap.parse_args(argv)

    if a.meshes and trimesh is None:
        raise SystemExit('trimesh is required for meshes: pip install trimesh')

    # --- volume header first: its RAS bounding box decides the mesh frame ---
    img = read_volume(a.volume)
    log('input size %s spacing %s' % (img.GetSize(), tuple(round(s, 4) for s in img.GetSpacing())))
    size = np.array(img.GetSize())
    corners = np.array([img.TransformIndexToPhysicalPoint((int(i), int(j), int(k))) for i in (0, size[0] - 1) for j in (0, size[1] - 1) for k in (0, size[2] - 1)])
    corners_ras = corners * np.array([-1.0, -1.0, 1.0])
    vol_bounds = (corners_ras.min(0), corners_ras.max(0))
    log('volume bounds (RAS mm): x %.1f..%.1f  y %.1f..%.1f  z %.1f..%.1f' % (vol_bounds[0][0], vol_bounds[1][0], vol_bounds[0][1], vol_bounds[1][1], vol_bounds[0][2], vol_bounds[1][2]))

    # --- meshes (needed for auto crop) ---
    meshes = []
    unmatched = []
    if a.meshes:
        mapping = load_map(a.map) if os.path.exists(a.map) else {}
        files = sorted(f for f in glob.glob(os.path.join(a.meshes, '*')) if re.search(r'\.(stl|obj|ply|off)$', f, re.I))
        if not files:
            log('no mesh files found in', a.meshes)
        raw = []
        for f in files:
            res = load_mesh_raw(f, a.mesh_scale)
            if res is not None:
                raw.append((f, res[0], res[1]))
        frame = a.mesh_frame.upper()
        if frame == 'AUTO' and raw:
            allv = np.concatenate([v for _, v, _ in raw])
            fr_ras = inside_fraction(allv, vol_bounds)
            fr_lps = inside_fraction(allv * np.array([-1.0, -1.0, 1.0]), vol_bounds)
            frame = 'LPS' if fr_lps > fr_ras else 'RAS'
            log('mesh frame auto: %.0f%% of vertices inside the volume as RAS, %.0f%% as LPS' % (fr_ras * 100, fr_lps * 100))
            if abs(fr_lps - fr_ras) < 0.15 and max(fr_ras, fr_lps) > 0.2:
                # ambiguous: surfaces sit on tissue boundaries, so the correct frame has the larger image gradient at the vertices
                mb = (allv.min(0) - 5, allv.max(0) + 5); coarse, c_origin, c_sp = resample_to_ras(img, 1.0, [mb[0][0], mb[1][0], mb[0][1], mb[1][1], mb[0][2], mb[1][2]])
                g = np.sqrt(sum(np.square(gr) for gr in np.gradient(coarse.astype(np.float32))))
                def grad_at(pts):
                    idx = np.round((pts - c_origin) / c_sp).astype(int)
                    ok = np.all((idx >= 0) & (idx < np.array(coarse.shape)[::-1]), axis=1)
                    idx = idx[ok]
                    return float(g[idx[:, 2], idx[:, 1], idx[:, 0]].mean()) if len(idx) else 0.0
                sample = allv[::max(1, len(allv) // 20000)]
                g_ras = grad_at(sample); g_lps = grad_at(sample * np.array([-1.0, -1.0, 1.0]))
                frame = 'LPS' if g_lps > g_ras else 'RAS'
                log('mesh frame auto: edge strength at vertices %.0f (RAS) vs %.0f (LPS) -> %s' % (g_ras, g_lps, frame))
            else:
                log('mesh frame auto -> %s' % frame)
            if max(fr_ras, fr_lps) < 0.5:
                log('WARNING: meshes mostly fall outside the volume in both frames; check --mesh-scale (units) or the volume choice')
        elif frame == 'AUTO':
            frame = 'RAS'
        for f, v, fc in raw:
            sid, ok = match_id(f, mapping)
            if not ok:
                unmatched.append((os.path.basename(f), sid))
            v, fc = to_frame(v, fc, frame)
            v, fc = decimate(v, fc, a.target_faces)
            if any(m['id'] == sid for m in meshes):
                # merge duplicates (e.g. scala tympani + scala vestibuli -> cochlea)
                prev = next(m for m in meshes if m['id'] == sid)
                off = len(prev['v'])
                prev['v'] = np.concatenate([prev['v'], v]); prev['f'] = np.concatenate([prev['f'], fc + off])
            else:
                meshes.append({'id': sid, 'v': v, 'f': fc, 'file': os.path.basename(f)})
            log('  mesh %-26s <- %s (%d faces)' % (sid, os.path.basename(f), len(fc)))

    # --- crop box ---
    crop = None
    if a.crop == 'auto' and meshes:
        # crop around the ear itself: the compact structures define the box, long structures (dura/sinus,
        # carotid, canal) that run to the edge of the block only extend it up to the margin
        CORE = {'cochlea', 'vestibule', 'labyrinth', 'scc_lateral', 'scc_superior', 'scc_posterior', 'malleus', 'incus', 'stapes',
                'facial_nerve', 'fn_tympanic', 'fn_mastoid', 'fn_labyrinthine', 'fn_meatal', 'geniculate', 'chorda_tympani',
                'tympanic_membrane', 'cochleovestibular_nerve', 'iac', 'round_window'}
        core = [m for m in meshes if m['id'] in CORE] or meshes
        allv = np.concatenate([m['v'] for m in core])
        margin = a.margin if core is meshes else max(a.margin, 14.0)
        lo = allv.min(0) - margin; hi = allv.max(0) + margin
        log('crop from %d core structures with %.0f mm margin' % (len(core), margin))
        crop = [lo[0], hi[0], lo[1], hi[1], lo[2], hi[2]]
        log('auto crop (RAS mm): x %.1f..%.1f  y %.1f..%.1f  z %.1f..%.1f' % tuple(crop))
    elif a.crop not in ('auto', 'none'):
        crop = [float(x) for x in a.crop.split(',')]

    # --- volume ---
    arr, origin, spacing = resample_to_ras(img, a.spacing, crop)
    arr = intensity_to_hu(arr, a.intensity)
    arr = np.clip(arr, -1024, 3071).astype(np.int16)
    dims = [arr.shape[2], arr.shape[1], arr.shape[0]]
    log('output volume %s voxels at %.3f mm, %.1f MB' % (dims, a.spacing, arr.nbytes / 1e6))

    # --- labels from a segmentation volume (preferred) ---
    label_ids = {}
    labels = None
    if a.label_volume:
        labels, label_ids = labels_from_volume(a.label_volume, a.label_names, origin, spacing, dims, meshes, load_map(a.map) if os.path.exists(a.map) else {})
    if labels is None and a.labels and meshes:
        labels = np.zeros(arr.shape, np.uint8)
        # bigger meshes first so small ones override
        order = sorted(meshes, key=lambda m: -float(np.prod(m['v'].max(0) - m['v'].min(0))))
        for i, m in enumerate(order):
            if m['id'] in ('bone', 'bone_shell', 'temporal_bone'):
                continue
            lab = len(label_ids) + 1
            if lab > 255:
                break
            log('  voxelising %s' % m['id'])
            mask = voxelize(m['v'], m['f'], origin, spacing, dims)
            if mask is None or not mask.any():
                continue
            labels[mask] = lab
            label_ids[str(lab)] = m['id']

    # --- landmarks: representative point per mesh (vertex nearest the centroid) ---
    landmarks = {}
    for m in meshes:
        c = m['v'].mean(0)
        v = m['v'][int(np.argmin(((m['v'] - c) ** 2).sum(1)))]
        landmarks[m['id']] = [float(x) for x in v]
    if a.landmarks and os.path.exists(a.landmarks):
        with open(a.landmarks) as f:
            j = json.load(f)
        landmarks.update(j.get('landmarks', j))

    # --- pack ---
    blobs = [('volume', delta_encode_int16(arr).astype('<i2').tobytes())]
    header = {
        'format': 'tba', 'version': 1,
        'name': a.name or os.path.basename(a.out).replace('.tba', ''),
        'kind': 'openear' if 'openear' in (a.name or '').lower() else 'clinical',
        'side': a.side,
        'notes': a.notes,
        'volume': {'blob': 'volume', 'dims': dims, 'spacing': [float(a.spacing)] * 3, 'origin': [float(x) for x in origin], 'dtype': 'int16', 'units': 'HU', 'encoding': 'delta-x'},
        'labelIds': label_ids,
        'meshes': [],
        'landmarks': landmarks,
    }
    if labels is not None:
        blobs.append(('labels', labels.tobytes()))
        header['labels'] = {'blob': 'labels', 'dims': dims, 'spacing': [float(a.spacing)] * 3, 'origin': [float(x) for x in origin], 'dtype': 'uint8'}
    for m in meshes:
        v, f = m['v'].astype(np.float32), m['f'].astype(np.uint32)
        bb = [float(v[:, 0].min()), float(v[:, 1].min()), float(v[:, 2].min()), float(v[:, 0].max()), float(v[:, 1].max()), float(v[:, 2].max())]
        header['meshes'].append({'id': m['id'], 'nv': int(len(v)), 'nf': int(len(f)), 'centroid': [float(x) for x in v.mean(0)], 'bbox': bb, 'v': 'mesh:%s:v' % m['id'], 'f': 'mesh:%s:f' % m['id']})
        blobs.append(('mesh:%s:v' % m['id'], v.astype('<f4').tobytes()))
        blobs.append(('mesh:%s:f' % m['id'], f.astype('<u4').tobytes()))
    os.makedirs(os.path.dirname(os.path.abspath(a.out)), exist_ok=True)
    n = write_pack(a.out, header, blobs)
    log('wrote %s: %.1f MB raw, %.1f MB compressed; %d meshes, %d labels' % (a.out, n / 1e6, os.path.getsize(a.out) / 1e6, len(meshes), len(label_ids)))
    if unmatched:
        log('\nUnmatched mesh files (kept with a generated id; add them to %s to map onto atlas cards):' % a.map)
        for f, sid in unmatched:
            log('  %s -> %s' % (f, sid))


if __name__ == '__main__':
    main()
