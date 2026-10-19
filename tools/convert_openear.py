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
import bz2
import glob
import json
import os
import re
import sys
import zlib

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
NRRD_TYPES = {
    'signed char': np.int8, 'int8': np.int8, 'int8_t': np.int8,
    'uchar': np.uint8, 'unsigned char': np.uint8, 'uint8': np.uint8, 'uint8_t': np.uint8,
    'short': np.int16, 'short int': np.int16, 'signed short': np.int16, 'signed short int': np.int16, 'int16': np.int16, 'int16_t': np.int16,
    'ushort': np.uint16, 'unsigned short': np.uint16, 'unsigned short int': np.uint16, 'uint16': np.uint16, 'uint16_t': np.uint16,
    'int': np.int32, 'signed int': np.int32, 'int32': np.int32, 'int32_t': np.int32,
    'uint': np.uint32, 'unsigned int': np.uint32, 'uint32': np.uint32, 'uint32_t': np.uint32,
    'longlong': np.int64, 'long long': np.int64, 'long long int': np.int64, 'signed long long': np.int64, 'signed long long int': np.int64, 'int64': np.int64, 'int64_t': np.int64,
    'ulonglong': np.uint64, 'unsigned long long': np.uint64, 'unsigned long long int': np.uint64, 'uint64': np.uint64, 'uint64_t': np.uint64,
    'float': np.float32, 'double': np.float64,
}


class NrrdStream:
    """Slice-by-slice access to an attached-data NRRD (raw, gzip or bzip2) without ever holding the
    whole volume in memory: the stream is decoded sequentially and only the slices the caller keeps
    survive. Handles 3-D images and 3D Slicer's 4-D segmentations (`kinds: list domain domain domain`,
    one layer per overlapping segment group). Geometry is left to ITK (see LazyVolume); this class only
    knows the data layout."""

    def __init__(self, path):
        self.path = path
        fields, kv = {}, {}
        with open(path, 'rb') as f:
            if not f.readline().startswith(b'NRRD'):
                raise ValueError('not a NRRD file')
            while True:
                line = f.readline()
                if not line:
                    raise ValueError('header never ends (detached data file?)')
                if line in (b'\n', b'\r\n'):
                    break
                s = line.decode('utf-8', 'replace').rstrip('\r\n')
                if s.startswith('#'):
                    continue
                if ':=' in s:
                    k, v = s.split(':=', 1); kv[k.strip()] = v.strip()
                elif ': ' in s:
                    k, v = s.split(': ', 1); fields[k.strip().lower()] = v.strip()
                elif s.endswith(':'):
                    fields[s[:-1].strip().lower()] = ''
            self.data_offset = f.tell()
        self.fields, self.kv = fields, kv
        if 'data file' in fields or 'datafile' in fields:
            raise ValueError('detached data file')
        self.encoding = {'gz': 'gzip', 'gzip': 'gzip', 'bz2': 'bzip2', 'bzip2': 'bzip2', 'raw': 'raw'}.get(fields.get('encoding', 'raw').lower())
        if self.encoding is None:
            raise ValueError('encoding %s' % fields.get('encoding'))
        t = fields.get('type', '').lower()
        if t not in NRRD_TYPES:
            raise ValueError('type %s' % t)
        dt = np.dtype(NRRD_TYPES[t])
        if dt.itemsize > 1:
            dt = dt.newbyteorder('>' if fields.get('endian', 'little').lower() == 'big' else '<')
        self.dtype = dt
        self.native_dtype = np.dtype(NRRD_TYPES[t])
        for k in ('byte skip', 'byteskip', 'line skip', 'lineskip'):
            if int(fields.get(k, '0') or 0):
                raise ValueError('%s not supported' % k)
        sizes = [int(x) for x in fields['sizes'].split()]
        kinds = fields.get('kinds', '').lower().split()
        self.list_axis = None
        if len(sizes) == 3:
            pass
        elif len(sizes) == 4:
            non_domain = [i for i, k in enumerate(kinds) if k not in ('domain', 'space', 'time')]
            if kinds and len(non_domain) == 1:
                self.list_axis = non_domain[0]
            elif not kinds and fields.get('space directions', '').split(' ', 1)[0] == 'none':
                self.list_axis = 0
            if self.list_axis not in (0, 3):
                raise ValueError('4-D layout with kinds %s' % (kinds or 'unknown'))
        else:
            raise ValueError('%d-D image' % len(sizes))
        self.layers = 1 if self.list_axis is None else sizes[self.list_axis]
        self.spatial = tuple(s for i, s in enumerate(sizes) if i != self.list_axis)   # (X, Y, Z), X fastest

    def _read_slices(self, want, items):
        """Yield (stored slice index, flat array) for every slice flagged in `want`, decoding in order and
        stopping after the last one wanted. `items` = elements per stored slice."""
        nbytes = items * self.dtype.itemsize
        idx = np.nonzero(want)[0]
        if len(idx) == 0:
            return
        last = int(idx[-1])
        with open(self.path, 'rb') as f:
            if self.encoding == 'raw':
                for s in idx:
                    f.seek(self.data_offset + int(s) * nbytes)
                    b = f.read(nbytes)
                    if len(b) < nbytes:
                        raise ValueError('truncated NRRD data')
                    yield int(s), np.frombuffer(b, self.dtype)
                return
            f.seek(self.data_offset)
            gz = self.encoding == 'gzip'
            dec = zlib.decompressobj(zlib.MAX_WBITS | 32) if gz else bz2.BZ2Decompressor()
            cap = max(nbytes, 1 << 24)   # never inflate more than this per step: labels can expand 1000x
            buf = bytearray()
            pending = b''
            eof = False
            s = 0
            while s <= last:
                if gz:
                    if dec.eof:
                        eof = True
                    elif pending:
                        buf += dec.decompress(pending, cap)
                        pending = dec.unconsumed_tail
                    else:
                        pending = f.read(1 << 20)
                        if not pending:
                            buf += dec.flush(); eof = True
                else:
                    if dec.eof:
                        eof = True
                    elif dec.needs_input:
                        chunk = f.read(1 << 20)
                        if not chunk:
                            eof = True
                        else:
                            buf += dec.decompress(chunk, cap)
                    else:
                        buf += dec.decompress(b'', cap)
                off = 0
                while len(buf) - off >= nbytes and s <= last:
                    if want[s]:
                        yield s, np.frombuffer(bytes(memoryview(buf)[off:off + nbytes]), self.dtype)
                    off += nbytes
                    s += 1
                if off:
                    del buf[:off]
                if eof and s <= last and len(buf) < nbytes:
                    raise ValueError('NRRD data stream ended early (slice %d of %d)' % (s, last + 1))

    def iter_slices(self, z0, z1, want_z=None, layers=None):
        """Yield (layer, z, array[Y, X]) for z in [z0, z1) (further restricted to want_z[z] if given)."""
        X, Y, Z = self.spatial
        N = self.layers
        layers = list(range(N)) if layers is None else [int(n) for n in layers]
        sel = np.zeros(Z, bool); sel[max(0, z0):max(0, min(Z, z1))] = True
        if want_z is not None:
            sel &= np.asarray(want_z, bool)
        if self.list_axis in (None, 0):           # one stored slice = every layer of that z (interleaved)
            for s, flat in self._read_slices(sel, X * Y * N):
                S = flat.reshape(Y, X, N)
                for n in layers:
                    yield n, s, S[:, :, n]
        else:                                     # planar: layer n is stored as slices n*Z .. n*Z+Z-1
            want = np.zeros(Z * N, bool)
            for n in layers:
                want[n * Z:(n + 1) * Z] = sel
            for s, flat in self._read_slices(want, X * Y):
                yield s // Z, s % Z, flat.reshape(Y, X)

    def read_block(self, index, size, layer=0):
        """Numpy block [z][y][x] (native byte order) of one layer, reading only the rows it needs."""
        x0, y0, z0 = [int(v) for v in index]
        sx, sy, sz = [int(v) for v in size]
        out = np.zeros((sz, sy, sx), self.native_dtype)
        for _, kz, S in self.iter_slices(z0, z0 + sz, layers=(layer,)):
            out[kz - z0] = S[y0:y0 + sy, x0:x0 + sx]
        return out


class LazyVolume:
    """Header-only handle on a volume file; reads voxels only for a requested index region.
    NRRD files are streamed (NrrdStream), so even a multi-gigabyte volume costs only its crop."""

    def __init__(self, path):
        r = sitk.ImageFileReader(); r.SetFileName(path); r.ReadImageInformation()
        self.path = path
        self.size = tuple(int(x) for x in r.GetSize())
        self.spacing = tuple(float(x) for x in r.GetSpacing())
        self.origin = tuple(float(x) for x in r.GetOrigin())
        self.direction = tuple(float(x) for x in r.GetDirection())
        self.pixel_type = sitk.GetPixelIDValueAsString(r.GetPixelID())
        self.components = int(r.GetNumberOfComponents())
        self.meta = {k: r.GetMetaData(k) for k in r.GetMetaDataKeys()}
        # a tiny image carrying the geometry, so Transform*Point works without voxels
        self._geo = sitk.Image([1, 1, 1], sitk.sitkUInt8)
        self._geo.SetSpacing(self.spacing); self._geo.SetOrigin(self.origin); self._geo.SetDirection(self.direction)
        self.nrrd = None
        if re.search(r'\.nrrd$', path, re.I):
            try:
                ns = NrrdStream(path)
                if tuple(ns.spatial) == self.size and ns.layers == self.components:
                    self.nrrd = ns
                else:
                    log('  NRRD layout %s x%d does not match ITK %s x%d; not streaming' % (ns.spatial, ns.layers, self.size, self.components))
            except Exception as e:
                log('  NRRD streaming unavailable (%s); ITK will read the whole file' % e)

    def GetSize(self): return self.size
    def GetSpacing(self): return self.spacing
    def GetOrigin(self): return self.origin
    def GetDirection(self): return self.direction
    def TransformIndexToPhysicalPoint(self, idx): return self._geo.TransformIndexToPhysicalPoint(tuple(int(i) for i in idx))
    def TransformPhysicalPointToContinuousIndex(self, p): return self._geo.TransformPhysicalPointToContinuousIndex(tuple(float(x) for x in p))

    def block_image(self, index, size, layer=0):
        """One layer of a region as a SimpleITK image with the right geometry, via the NRRD stream."""
        block = self.nrrd.read_block(index, size, layer)
        img = sitk.GetImageFromArray(block)
        img.SetSpacing(self.spacing); img.SetDirection(self.direction)
        img.SetOrigin(self._geo.TransformIndexToPhysicalPoint(tuple(int(i) for i in index)))
        return img

    def read_region(self, index, size):
        if self.nrrd is not None and self.components == 1:
            log('  streaming %s voxels from the NRRD' % [int(x) for x in size])
            return self.block_image(index, size)
        r = sitk.ImageFileReader(); r.SetFileName(self.path)
        r.SetExtractIndex([int(x) for x in index]); r.SetExtractSize([int(x) for x in size])
        try:
            return r.Execute()
        except Exception as e:
            # some formats cannot stream (e.g. gzip-compressed NIfTI): read whole, crop, release
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


FLIP_LPS = np.diag([-1.0, -1.0, 1.0])   # RAS <-> LPS


def out_to_in_ras(rot):
    """Map from the output (anatomical) RAS frame back to the input RAS frame: p_in = Rt p_out + c."""
    if rot is None:
        return np.eye(3), np.zeros(3)
    return rot['R'].T, np.asarray(rot['center'], np.float64)


def resample_to_ras(img, spacing, crop_ras=None, interpolator=sitk.sitkLinear if sitk else None, rot=None, pre=None):
    """Resample onto an isotropic RAS grid covering `crop_ras` (x0,x1,y0,y1,z0,z1 in the OUTPUT frame; the
    volume's own bounds when None). With `rot` (see estimate_anatomical_frame) the output frame is the
    anatomical one and the volume is rotated into it. Only the input region that lands on the grid is read.
    Returns (array [z][y][x] RAS order, origin RAS, spacing)."""
    lazy = isinstance(img, LazyVolume)
    size = np.array(img.GetSize())
    Rt, c = out_to_in_ras(rot)
    P, p0 = (np.eye(3), np.zeros(3)) if pre is None else linear_matrix(pre)      # registered LPS -> raw (stored) LPS
    P_inv = np.linalg.inv(P)
    corners_raw = np.array([img.TransformIndexToPhysicalPoint((int(i), int(j), int(k))) for i in (0, size[0] - 1) for j in (0, size[1] - 1) for k in (0, size[2] - 1)])
    corners_in = (corners_raw - p0) @ P_inv.T                 # raw LPS -> registered LPS
    corners_out = (corners_in @ FLIP_LPS - c) @ Rt          # input LPS -> input RAS -> output RAS (Rt.T = R)
    lo, hi = corners_out.min(0), corners_out.max(0)        # output-frame bounds of the volume (RAS)
    if crop_ras is not None:
        cx0, cx1, cy0, cy1, cz0, cz1 = crop_ras
        lo = np.maximum(lo, [cx0, cy0, cz0]); hi = np.minimum(hi, [cx1, cy1, cz1])
    out_size = np.maximum(1, np.ceil((hi - lo) / spacing).astype(int) + 1)
    # input region covering the output box (its 8 corners, mapped back)
    box = np.array([[x, y, z] for x in (lo[0], hi[0]) for y in (lo[1], hi[1]) for z in (lo[2], hi[2])])
    box_in_lps = ((box @ Rt.T + c) @ FLIP_LPS) @ P.T + p0
    idx = np.array([img.TransformPhysicalPointToContinuousIndex(tuple(float(x) for x in p)) for p in box_in_lps])
    i0 = np.maximum(np.floor(idx.min(0)).astype(int) - 2, 0)
    i1 = np.minimum(np.ceil(idx.max(0)).astype(int) + 3, size)
    if not np.all(i1 > i0):
        raise SystemExit('the requested crop box lies outside the volume')
    if np.any(i0 > 0) or np.any(i1 < size):
        img = img.read_region(i0, i1 - i0) if lazy else sitk.RegionOfInterest(img, [int(x) for x in (i1 - i0)], [int(x) for x in i0])
        log('cropped input to %s voxels before resampling' % list(img.GetSize()))
    elif lazy:
        log('reading whole volume (no crop)')
        img = img.read_all()
    # reference grid: identity direction in LPS; an affine maps output LPS points to input LPS points
    nx, ny, nz = out_size
    ref = sitk.Image([int(x) for x in out_size], sitk.sitkFloat32)
    ref.SetSpacing([spacing] * 3)
    ref.SetOrigin([float(-hi[0]), float(-hi[1]), float(lo[2])])     # output RAS box in LPS
    ref.SetDirection([1, 0, 0, 0, 1, 0, 0, 0, 1])
    tf = sitk.AffineTransform(3)
    tf.SetMatrix([float(x) for x in (FLIP_LPS @ Rt @ FLIP_LPS).ravel()])
    tf.SetTranslation([float(x) for x in (FLIP_LPS @ c)])
    if pre is not None:
        tf = sitk.CompositeTransform([pre, tf])          # tf first (anatomical -> registered), then pre (registered -> raw)
    out = sitk.Resample(img, ref, tf, interpolator, -1024.0, sitk.sitkFloat32)
    del img
    arr = sitk.GetArrayFromImage(out)  # (z, y, x) with +x = L, +y = P
    arr = arr[:, ::-1, ::-1]           # flip to +x = R, +y = A
    origin_ras = np.array([hi[0] - (nx - 1) * spacing, hi[1] - (ny - 1) * spacing, lo[2]])
    return np.ascontiguousarray(arr), origin_ras, np.array([spacing] * 3)


def resolve_intensity(arr, mode):
    """Turn 'auto' into an explicit mapping ('hu' or 'scale:a,b') decided on this array, so every volume of a
    pack (core and context) gets the same mapping."""
    if mode != 'auto':
        return mode
    p1, p50, p99 = np.percentile(arr, [1, 50, 99])
    if p1 < -500 and p99 < 4000:
        log('intensity looks like HU already (p1=%.0f, p99=%.0f)' % (p1, p99))
        return 'hu'
    log('intensity does not look like HU (p1=%.0f, p50=%.0f, p99=%.0f); mapping p1->-1000 and p99->2200' % (p1, p50, p99))
    if p99 <= p1:
        return 'hu'
    a = 3200.0 / (p99 - p1)
    return 'scale:%g,%g' % (a, -1000.0 - p1 * a)


def intensity_to_hu(arr, mode):
    mode = resolve_intensity(arr, mode)
    if mode == 'hu':
        return arr
    if mode.startswith('scale:'):
        a, b = [float(x) for x in mode.split(':')[1].split(',')]
        return arr * a + b
    return arr


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
    big = os.path.getsize(path) > 20e6          # OpenEar bone blocks are 60-210 MB: skip trimesh's vertex merging
    m = trimesh.load(path, force='mesh', process=not big)
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


BACKGROUND_IDS = {'bone', 'bone_shell', 'temporal_bone'}   # bone is the CT itself; as a label it would swallow every click
CONTEXT_IDS = {'bone_shell', 'sinus_dura', 'dura'}            # large wrapping surfaces: kept as translucent context, no landmark


def pack_grid_in_lps(origin, spacing, dims):
    """SimpleITK reference image (LPS, identity direction) covering the pack's RAS grid; arrays sampled on
    it become RAS order after [:, ::-1, ::-1]."""
    nx, ny, nz = [int(x) for x in dims]
    ox, oy, oz = origin
    lo_lps = [-(ox + (nx - 1) * spacing[0]), -(oy + (ny - 1) * spacing[1]), oz]
    ref = sitk.Image([nx, ny, nz], sitk.sitkUInt8)
    ref.SetSpacing([float(x) for x in spacing]); ref.SetOrigin([float(x) for x in lo_lps]); ref.SetDirection([1, 0, 0, 0, 1, 0, 0, 0, 1])
    return ref


def covering_index_box(src, origin, spacing, dims, rot=None):
    """Index range (i0, i1) of `src` that covers the pack grid (plus a voxel of slack), clamped to the image."""
    nx, ny, nz = [int(x) for x in dims]
    size = np.array(src.GetSize())
    Rt, c = out_to_in_ras(rot)
    pts = []
    for i in (0, nx - 1):
        for j in (0, ny - 1):
            for k in (0, nz - 1):
                p_out = np.array([origin[0] + i * spacing[0], origin[1] + j * spacing[1], origin[2] + k * spacing[2]])
                p_lps = FLIP_LPS @ (Rt @ p_out + c)
                pts.append(src.TransformPhysicalPointToContinuousIndex(tuple(float(x) for x in p_lps)))
    pts = np.array(pts)
    i0 = np.maximum(np.floor(pts.min(0)).astype(int) - 1, 0)
    i1 = np.minimum(np.ceil(pts.max(0)).astype(int) + 2, size)
    return i0, i1


def index_affine(src, origin, spacing, rot=None):
    """(B, b0) with  src continuous index = B @ (i, j, k) + b0  for pack grid indices (i, j, k)."""
    Dir = np.array(src.GetDirection(), dtype=np.float64).reshape(3, 3)
    M_inv = np.linalg.inv(Dir @ np.diag(np.array(src.GetSpacing(), dtype=np.float64)))
    o_lps = np.array(src.GetOrigin(), dtype=np.float64)
    Rt, c = out_to_in_ras(rot)
    B = M_inv @ FLIP_LPS @ Rt @ np.diag(np.asarray(spacing, np.float64))
    b0 = M_inv @ (FLIP_LPS @ (Rt @ np.asarray(origin, np.float64) + c) - o_lps)
    return B, b0


def sample_label_layers(src, origin, spacing, dims, rot=None):
    """Nearest-neighbour sample every layer of a label volume onto the pack grid (optionally rotated into the
    anatomical frame), reading only the slices that land on it. Returns a list of [z][y][x] arrays (RAS
    order), one per layer.

    NRRD input is streamed: when the grids are aligned each decoded slice is sampled straight into the
    output; otherwise the output voxels are bucketed by source slice first (about 20 bytes per output
    voxel) and filled as the slices stream past. Other formats go through ITK on the covering block."""
    nx, ny, nz = [int(x) for x in dims]
    N = n_components(src)
    nrrd = getattr(src, 'nrrd', None)
    size = np.array(src.GetSize())
    if nrrd is not None:
        B, b0 = index_affine(src, origin, spacing, rot)
        out_dtype = np.uint8 if nrrd.native_dtype == np.uint8 else np.uint16
        out = [np.zeros((nz, ny, nx), out_dtype) for _ in range(N)]
        if np.allclose(B - np.diag(np.diag(B)), 0.0, atol=1e-6):
            maps, valid = [], []
            for ax, n_out in ((0, nx), (1, ny), (2, nz)):
                k = np.rint(B[ax, ax] * np.arange(n_out) + b0[ax]).astype(np.int64)
                ok = (k >= 0) & (k < size[ax])
                maps.append(k); valid.append(np.nonzero(ok)[0])
            vx, vy, vz = valid
            if not (len(vx) and len(vy) and len(vz)):
                log('  WARNING: the label volume does not overlap the pack grid at all')
                return out
            mx, my, mz = maps[0][vx], maps[1][vy], maps[2][vz]
            rows_for = {}
            for k_out, k_in in zip(vz.tolist(), mz.tolist()):
                rows_for.setdefault(k_in, []).append(k_out)
            want_z = np.zeros(int(size[2]), bool); want_z[list(rows_for)] = True
            log('  streaming %d of %d label slices (%d layer%s) straight onto the pack grid' % (len(rows_for), size[2], N, '' if N == 1 else 's'))
            ix = np.ix_(my, mx)
            for n, kz, S in nrrd.iter_slices(int(mz.min()), int(mz.max()) + 1, want_z=want_z):
                rows = rows_for.get(kz)
                if not rows:
                    continue
                block = S[ix]
                if block.dtype != out[n].dtype:
                    block = block.astype(out[n].dtype)
                out[n][np.ix_(rows, vy, vx)] = block[None]
            return out
        # rotated: nearest source index of every output voxel, bucketed by source slice
        V = nx * ny * nz
        kx = np.empty(V, np.int16); ky = np.empty(V, np.int16); kz = np.full(V, -1, np.int32)
        ii, jj = np.meshgrid(np.arange(nx, dtype=np.float64), np.arange(ny, dtype=np.float64), indexing='xy')   # (ny, nx)
        base = B[:, 0:1] * ii.ravel()[None, :] + B[:, 1:2] * jj.ravel()[None, :] + b0[:, None]   # (3, ny*nx)
        for k in range(nz):
            idx = np.rint(base + B[:, 2:3] * float(k)).astype(np.int64)
            ok = np.all((idx >= 0) & (idx < size[:, None]), axis=0)
            sl = slice(k * ny * nx, (k + 1) * ny * nx)
            kx[sl] = idx[0]; ky[sl] = idx[1]
            kz[sl] = np.where(ok, idx[2], -1)
        del base, ii, jj, idx, ok
        valid = kz >= 0
        n_valid = int(valid.sum())
        if n_valid == 0:
            log('  WARNING: the label volume does not overlap the pack grid at all')
            return out
        order = np.argsort(kz.astype(np.int16), kind='stable')[V - n_valid:].astype(np.int32)   # radix sort; valid voxels by source slice
        kz_sorted = kz[order]
        slices_used = np.unique(kz_sorted)
        starts = np.searchsorted(kz_sorted, slices_used)
        ends = np.r_[starts[1:], len(order)]
        del kz, kz_sorted, valid
        want_z = np.zeros(int(size[2]), bool); want_z[slices_used] = True
        log('  streaming %d of %d label slices (%d layer%s) onto the rotated pack grid' % (len(slices_used), size[2], N, '' if N == 1 else 's'))
        lookup = {int(z): (int(s0), int(s1)) for z, s0, s1 in zip(slices_used, starts, ends)}
        flat = [o.reshape(-1) for o in out]
        for n, z, S in nrrd.iter_slices(int(slices_used.min()), int(slices_used.max()) + 1, want_z=want_z):
            s0, s1 = lookup[z]
            sel = order[s0:s1]
            flat[n][sel] = S[ky[sel], kx[sel]]
        return out
    # other formats: covering block through ITK, layer by layer
    i0, i1 = covering_index_box(src, origin, spacing, dims, rot)
    if not np.all(i1 > i0):
        log('  WARNING: the label volume does not overlap the pack grid at all')
        return [np.zeros((nz, ny, nx), np.uint8) for _ in range(N)]
    ref = pack_grid_in_lps(origin, spacing, dims)
    Rt, c = out_to_in_ras(rot)
    tf = sitk.AffineTransform(3)
    tf.SetMatrix([float(x) for x in (FLIP_LPS @ Rt @ FLIP_LPS).ravel()])
    tf.SetTranslation([float(x) for x in (FLIP_LPS @ c)])
    out = []
    for n in range(N):
        img = src.read_region(i0, i1 - i0) if isinstance(src, LazyVolume) else sitk.RegionOfInterest(src, [int(x) for x in (i1 - i0)], [int(x) for x in i0])
        if img.GetNumberOfComponentsPerPixel() > 1:
            img = sitk.VectorIndexSelectionCast(img, n)
        if img.GetPixelID() not in (sitk.sitkUInt8, sitk.sitkUInt16):
            img = sitk.Cast(img, sitk.sitkUInt16)
        res = sitk.Resample(img, ref, tf, sitk.sitkNearestNeighbor, 0, img.GetPixelID())
        del img
        out.append(np.ascontiguousarray(sitk.GetArrayFromImage(res)[:, ::-1, ::-1]))
        del res
    log('  resampled %s input voxels (%d layer%s) onto the pack grid' % ([int(x) for x in (i1 - i0)], N, '' if N == 1 else 's'))
    return out


def n_components(src):
    return src.components if isinstance(src, LazyVolume) else int(src.GetNumberOfComponentsPerPixel())


def segment_names(src, names_json):
    """(layer, value) -> name from --label-names JSON (any layer), Slicer SegmentN_* header fields,
    or 'labelN'-style keys."""
    names = {}
    meta = getattr(src, 'meta', None)
    if meta is None:
        meta = {k: src.GetMetaData(k) for k in src.GetMetaDataKeys()}
    N = n_components(src)
    if names_json and os.path.exists(names_json):
        with open(names_json) as f:
            for k, v in json.load(f).items():
                for n in range(N):
                    names[(n, int(k))] = v
        return names
    seg = {}
    for k, v in meta.items():
        m = re.match(r'Segment(\d+)_(Name|LabelValue|Layer)$', k)
        if m:
            seg.setdefault(int(m.group(1)), {})[m.group(2)] = v
    for i, d in sorted(seg.items()):
        if 'Name' not in d:
            continue
        try:
            if 'LabelValue' in d:
                names[(int(d.get('Layer', 0)), int(d['LabelValue']))] = d['Name']
            elif N > 1 and i < N:
                # Slicer before 4.11 (OpenEar's files): one binary layer per segment, no LabelValue/Layer fields
                names[(i, 1)] = d['Name']
            elif N == 1:
                names[(0, i + 1)] = d['Name']
        except ValueError:
            pass
    if not names:
        for k, v in meta.items():
            m = re.match(r'(?:label|value)[_ ]?(\d+)$', k, re.I)
            if m:
                for n in range(N):
                    names[(n, int(m.group(1)))] = v
    return names


def labels_from_volume(path, names_json, origin, spacing, dims, meshes, mapping, rot=None):
    """Sample a segmentation (NRRD/NIfTI label map, including 3D Slicer's multi-layer .seg.nrrd) onto the
    pack grid without loading it whole, and map its segments to atlas ids.

    Segment -> name comes from (in order): --label-names JSON, Slicer header fields
    (SegmentN_Name / SegmentN_LabelValue / SegmentN_Layer), 'labelN=name'-style header keys, or, failing
    all, the mesh whose surface best overlaps the segment. Where segments overlap (Slicer layers), the
    smaller structure wins, so the ossicles and nerves are never hidden under bone.
    """
    log('reading label volume', path)
    src = read_volume(path)
    N = n_components(src)
    log('  label volume %s voxels at %s mm, %d layer%s, %s' % (list(src.GetSize()), tuple(round(s, 4) for s in src.GetSpacing()), N, '' if N == 1 else 's', getattr(src, 'pixel_type', '')))
    names = segment_names(src, names_json)
    layers = sample_label_layers(src, origin, spacing, dims, rot)
    nz, ny, nx = layers[0].shape
    # inventory: (layer, value) -> voxel count, counted in slabs so no giant temporary appears
    segs = []
    for n, L in enumerate(layers):
        counts = np.zeros(int(np.iinfo(L.dtype).max) + 1, np.int64)
        for z in range(0, nz, 16):
            bc = np.bincount(L[z:z + 16].ravel())
            counts[:len(bc)] += bc
        for v in np.nonzero(counts)[0]:
            if v:
                segs.append((n, int(v), int(counts[v])))
    if not segs:
        log('  WARNING: no label voxels inside the pack grid; check that the segmentation is registered to the volume')
        return None, {}
    log('label volume: %d segment%s on the pack grid%s' % (len(segs), '' if len(segs) == 1 else 's',
        (': ' + ', '.join('%s%d=%s' % ('L%d/' % n if N > 1 else '', v, names.get((n, v), '?')) for n, v, _ in segs)) if names
        else ' (no segment names in the header; matching them to the surfaces by overlap)'))
    # segment -> atlas id: by name first; segments with no name, or a name no pattern knows, are matched to
    # the surface that overlaps them (OpenEar's headers say "RW", "Sinus", "Duct"...)
    id_of = {}
    unmatched = []
    weak = set()
    NERVE_IDS = {'facial_nerve', 'cochleovestibular_nerve', 'chorda_tympani', 'fn_meatal', 'fn_labyrinthine', 'fn_tympanic', 'fn_mastoid', 'geniculate', 'gspn', 'cochlear_nerve', 'vestibular_nerve', 'jacobson_nerve'}
    for n, v, _ in segs:
        nm = names.get((n, v))
        if nm:
            sid, ok = match_id(nm + '.x', mapping)
            if re.search(r'nerv|\bn\.', nm, re.I) and sid not in NERVE_IDS:
                ok = False          # "Vestibucochlear Nerve" must not become the cochlea because it contains 'cochlea'
            id_of[(n, v)] = sid
            if not ok:
                weak.add((n, v))
    if meshes and (len(id_of) - len(weak)) < len(segs):
        # overlap-based matching: which mesh's vertices fall inside each segment
        bbox_voxels = {m['id']: float(np.prod(np.maximum(m['v'].max(0) - m['v'].min(0), spacing) / spacing)) for m in meshes}
        for n, v, cnt in segs:
            if (n, v) in id_of and (n, v) not in weak:
                continue
            arr = layers[n]
            best, best_frac = None, 0.0
            for m in meshes:
                if cnt > 1.5 * bbox_voxels[m['id']]:
                    continue   # a segment cannot be bigger than the bounding box of its own surface (rules out bone)
                pts = m['v'][::max(1, len(m['v']) // 4000)]
                idx = np.round((pts - origin) / spacing).astype(int)
                ok = np.all((idx >= 0) & (idx < np.array(dims)), axis=1)
                if not ok.any():
                    continue
                idx = idx[ok]
                hits = 0
                for dz, dy, dx in ((0, 0, 0), (0, 0, 1), (0, 0, -1), (0, 1, 0), (0, -1, 0), (1, 0, 0), (-1, 0, 0)):
                    j = idx + np.array([dx, dy, dz]); j = np.clip(j, 0, np.array(dims) - 1)
                    hits += (arr[j[:, 2], j[:, 1], j[:, 0]] == v).sum()
                frac = hits / (7.0 * len(idx))
                if frac > best_frac:
                    best, best_frac = m['id'], frac
            nm = names.get((n, v))
            tag = ('%s (%s)' % ('layer %d value %d' % (n, v) if N > 1 else 'value %d' % v, nm)) if nm else ('layer %d value %d' % (n, v) if N > 1 else 'value %d' % v)
            if best and best_frac > 0.05:
                id_of[(n, v)] = best
                log('  %s -> %s (by overlap %.0f%%)' % (tag, best, best_frac * 100))
            elif (n, v) in weak:
                unmatched.append((n, v, nm, id_of[(n, v)]))     # keeps the sanitised name as its id
            elif meshes and cnt > 2.0 * max(bbox_voxels.values()):
                id_of[(n, v)] = 'bone'   # bigger than any structure and matching none: the bone block
                log('  %s (%d voxels) is larger than every surface and matches none: treating it as bone' % (tag, cnt))
            else:
                id_of[(n, v)] = 'label_%d' % v if N == 1 else 'label_%d_%d' % (n, v)
                unmatched.append((n, v, None, id_of[(n, v)]))
    else:
        for n, v in weak:
            unmatched.append((n, v, names.get((n, v)), id_of[(n, v)]))
    # composite: largest segments first so the smallest structure wins wherever layers overlap
    order = sorted(segs, key=lambda t: -t[2])
    ids = []
    for n, v, cnt in order:
        sid = id_of[(n, v)]
        if sid in BACKGROUND_IDS:
            log('  skipping %s (%d voxels): bone is the CT itself, not a label' % (names.get((n, v), sid), cnt))
            continue
        if sid not in ids:
            ids.append(sid)
    if len(ids) > 255:
        log('WARNING: more than 255 labels; keeping the first 255')
        ids = ids[:255]
    labels = np.zeros((nz, ny, nx), np.uint8)
    for n, v, cnt in order:
        sid = id_of[(n, v)]
        if sid in ids:
            labels[layers[n] == v] = ids.index(sid) + 1
    del layers
    label_ids = {str(i + 1): sid for i, sid in enumerate(ids)}
    for n, v, nm, sid in unmatched:
        log('  unmatched segment %d (%s) kept as %s' % (v, nm, sid))
    sources = {}
    for n, v, _ in segs:
        sid = id_of[(n, v)]
        if sid in ids and names.get((n, v)):
            sources.setdefault(sid, []).append(names[(n, v)])
    labels_from_volume.sources = sources
    return labels, label_ids


# --------------------------------------------------------------------------
# Registration transforms shipped with a raw scan (OpenEar Beta: no registered CBCT, but the Slicer
# chain FlipXY / InitialGuess / BrainsFit as ITK .h5 files). Which of them apply, in which order and in
# which direction is not recorded, so the converter tries the compositions and keeps the one that puts
# the surfaces on bone edges, exactly the test it uses to tell RAS from LPS surfaces.
# --------------------------------------------------------------------------
def linear_matrix(tf):
    """(A, t) with tf(p) = A p + t, probed numerically (works for any linear ITK transform, composite included)."""
    t = np.array(tf.TransformPoint((0.0, 0.0, 0.0)), dtype=np.float64)
    A = np.column_stack([np.array(tf.TransformPoint(tuple(float(x) for x in e)), dtype=np.float64) - t for e in np.eye(3)])
    return A, t


def affine_from_matrix(A, t):
    tf = sitk.AffineTransform(3)
    tf.SetMatrix([float(x) for x in np.asarray(A).ravel()]); tf.SetTranslation([float(x) for x in t])
    return tf


def choose_pretransform(img, raw_meshes, files):
    """Pick the composition of the shipped transforms (and the surface frame) that lands the surfaces on the
    bone of the raw volume. Returns (pre: sitk.Transform registered-LPS -> raw-LPS or None, frame, report)."""
    import itertools
    mats = []
    for f in files:
        try:
            A, t = linear_matrix(sitk.ReadTransform(f))
            mats.append((os.path.basename(f), A, t))
        except Exception as e:
            log('  transform %s unreadable (%s)' % (os.path.basename(f), e))
    allv = np.concatenate([v for _, v, _ in raw_meshes])
    sample = allv[::max(1, len(allv) // 6000)]
    # a 1 mm copy of the raw volume and its edge strength, in the raw (stored) frame
    whole = img.read_all() if isinstance(img, LazyVolume) else img
    size = np.array(whole.GetSize()); sp = np.array(whole.GetSpacing())
    coarse_sp = 1.0
    out_size = np.maximum(1, np.ceil(size * sp / coarse_sp).astype(int))
    ref = sitk.Image([int(x) for x in out_size], sitk.sitkFloat32)
    ref.SetSpacing([coarse_sp] * 3); ref.SetOrigin(whole.GetOrigin()); ref.SetDirection(whole.GetDirection())
    coarse = sitk.GetArrayFromImage(sitk.Resample(whole, ref, sitk.Transform(), sitk.sitkLinear, -1024.0, sitk.sitkFloat32))
    g = np.sqrt(sum(np.square(gr) for gr in np.gradient(coarse)))
    Dir = np.array(ref.GetDirection()).reshape(3, 3); M_inv = np.linalg.inv(Dir * coarse_sp); o = np.array(ref.GetOrigin())
    def score(A, t, frame):
        pts_lps = sample * (np.array([-1.0, -1.0, 1.0]) if frame == 'RAS' else np.array([1.0, 1.0, 1.0]))
        raw_lps = pts_lps @ A.T + t
        idx = np.rint((raw_lps - o) @ M_inv.T).astype(int)
        ok = np.all((idx >= 0) & (idx < out_size), axis=1)
        inside = float(ok.mean())
        if not ok.any():
            return 0.0, inside
        return float(g[idx[ok, 2], idx[ok, 1], idx[ok, 0]].mean()) * inside, inside
    results = []
    for frame in ('RAS', 'LPS'):
        sc, ins = score(np.eye(3), np.zeros(3), frame)
        results.append((sc, ins, 'none', frame, np.eye(3), np.zeros(3)))
        for k in range(1, len(mats) + 1):
            for subset in itertools.permutations(range(len(mats)), k):
                for inv in itertools.product((False, True), repeat=k):
                    A, t = np.eye(3), np.zeros(3)
                    names = []
                    for i, iv in zip(subset, inv):
                        nm, Ai, ti = mats[i]
                        if iv:
                            Ai = np.linalg.inv(Ai); ti = -Ai @ ti
                        # composition: apply the current (A, t) first, then (Ai, ti)
                        A, t = Ai @ A, Ai @ t + ti
                        names.append(nm.replace('.h5', '') + ('^-1' if iv else ''))
                    sc, ins = score(A, t, frame)
                    results.append((sc, ins, ' then '.join(names), frame, A, t))
    results.sort(key=lambda r: -r[0])
    report = ['transform search over %d candidates (%d files):' % (len(results), len(mats))]
    for sc, ins, nm, frame, _, _ in results[:6]:
        report.append('  edge %6.1f  inside %3.0f%%  %s surfaces, %s' % (sc, ins * 100, frame, nm))
    base = max(r[0] for r in results if r[2] == 'none')
    best = results[0]
    report.append('  (no transform: edge %.1f)' % base)
    if best[2] == 'none' or best[1] < 0.85 or best[0] < 1.3 * base:
        return None, None, report
    return affine_from_matrix(best[4], best[5]), best[3], report


# --------------------------------------------------------------------------
# Anatomical orientation. Research volumes (OpenEar's embedded blocks among them) sit in the scanner frame,
# so their axes are not the patient's. The atlas needs true axial/coronal/sagittal planes, and the
# segmented structures carry enough anatomy to recover them:
#   superior  - the mastoid segment of the facial nerve descends vertically; the malleus and incus hang
#               with their heavy ends (head, body) up; the EAC and the IAC are horizontal lines
#   lateral   - from the cochlea towards the tympanic membrane, along the EAC, and along the IAC from
#               the porus to the fundus
#   side      - the carotid is anterior to the cochlea, the sigmoid sinus / posterior fossa dura posterior
# The result is the RAS frame of a right or left ear with the cochlea at the origin.
# --------------------------------------------------------------------------
def unit(v):
    v = np.asarray(v, dtype=np.float64)
    n = np.linalg.norm(v)
    return v / n if n > 0 else v


def principal_axis(v):
    c = v.mean(0)
    _, s, vt = np.linalg.svd(v - c, full_matrices=False)
    return c, vt[0], s / np.sqrt(len(v))


def estimate_anatomical_frame(meshes):
    """Rotation into the anatomical RAS frame from segmented structures (RAS input frame, any orientation).

    Returns {'R': 3x3 (rows = right, anterior, superior unit vectors in the input frame), 'center': cochlea
    centroid, 'side': 'R'|'L', 'report': [...]} or None when the cues are missing."""
    by = {m['id']: np.asarray(m['v'], np.float64) for m in meshes}
    report = []
    coch_id = next((i for i in ('cochlea', 'labyrinth', 'vestibule') if i in by), None)
    if coch_id is None:
        return None
    coch = by[coch_id].mean(0)
    horiz, vert, lateral = [], [], []          # (unit vector, weight, name)
    if 'eac' in by:
        c, ax, _ = principal_axis(by['eac']); ax = ax * np.sign(np.dot(ax, c - coch))
        horiz.append((ax, 1.0, 'EAC axis')); lateral.append((ax, 0.5, 'EAC axis'))
    iac_id = next((i for i in ('iac', 'cochleovestibular_nerve', 'fn_meatal') if i in by), None)
    if iac_id:
        c, ax, _ = principal_axis(by[iac_id]); ax = ax * np.sign(np.dot(ax, coch - c))
        horiz.append((ax, 1.0, 'IAC axis')); lateral.append((ax, 1.0, 'IAC axis'))
    if 'tympanic_membrane' in by:
        d = unit(by['tympanic_membrane'].mean(0) - coch)
        lateral.append((d, 1.0, 'cochlea->TM')); horiz.append((d, 0.5, 'cochlea->TM'))
    h_mean = unit(sum(w * h for h, w, _ in horiz)) if horiz else None
    fn_id = next((i for i in ('fn_mastoid', 'facial_nerve') if i in by), None)
    if fn_id:
        fn = by[fn_id]
        dist = np.linalg.norm(fn - coch, axis=1)
        # the stylomastoid foramen is the nerve's point farthest from the cochlea; the 9 mm above it are the
        # mastoid segment, which hangs vertically. If that end turns out to lie in the axial plane (a nerve
        # mesh whose meatal end is the far one), take the other extreme instead.
        ends = [fn[np.argmax(dist)]]
        ends.append(fn[np.argmax(np.linalg.norm(fn - ends[0], axis=1))])
        for E in ends:
            seg = fn[np.linalg.norm(fn - E, axis=1) < 9.0]
            if len(seg) < 20:
                continue
            c, ax, sd = principal_axis(seg)
            ax = -ax * np.sign(np.dot(ax, E - c))          # superior = away from the free (inferior) end
            tilt = abs(np.dot(ax, h_mean)) if h_mean is not None else 0.0
            if tilt < 0.7:
                vert.append((ax, 2.0, 'facial nerve, mastoid segment'))
                break
    for oss in ('malleus', 'incus'):
        if oss in by:
            c, ax, _ = principal_axis(by[oss]); proj = (by[oss] - c) @ ax
            mid = (proj.min() + proj.max()) / 2
            ax = ax * (1.0 if mid < 0 else -1.0)         # the vertex centroid sits towards the heavy (superior) end
            vert.append((ax, 1.0, oss + ' long axis'))
    if not vert or not lateral:
        return None
    A = sum(w * np.outer(h, h) for h, w, _ in horiz) - sum(w * np.outer(v, v) for v, w, _ in vert)
    _, evecs = np.linalg.eigh(A)
    s_hat = evecs[:, 0]
    s_hat = s_hat * np.sign(np.dot(s_hat, sum(w * v for v, w, _ in vert)))
    l_sum = sum(w * d for d, w, _ in lateral)
    l_hat = unit(l_sum - np.dot(l_sum, s_hat) * s_hat)
    a_right = np.cross(s_hat, l_hat)                      # anterior if this is a right ear
    votes = 0.0
    for pid, sign in (('carotid_canal', 1.0), ('eustachian_tube', 1.0), ('sigmoid_sinus', -1.0), ('sinus_dura', -1.0), ('dura', -1.0), ('jugular_bulb', -1.0), ('scc_posterior', -1.0)):
        if pid in by:
            votes += sign * np.dot(by[pid].mean(0) - coch, a_right)
    if votes == 0.0:
        report.append('no anterior/posterior structure to tell the side; assuming a right ear')
    side = 'L' if votes < 0 else 'R'
    r_hat = l_hat if side == 'R' else -l_hat
    a_hat = np.cross(s_hat, r_hat)
    R = np.stack([r_hat, a_hat, s_hat])
    deg = lambda a, b: np.degrees(np.arccos(np.clip(abs(np.dot(a, b)), -1.0, 1.0)))
    for v, w, name in vert:
        report.append('%s: %.0f deg from the final superior axis' % (name, deg(v, s_hat)))
    for h, w, name in horiz:
        report.append('%s: %.0f deg from the axial plane' % (name, 90.0 - deg(h, s_hat)))
    for d, w, name in lateral:
        report.append('%s: %.0f deg from the final lateral axis' % (name, deg(d, l_hat)))
    report.append('side %s (anterior/posterior vote %.1f mm)' % (side, votes))
    return {'R': R, 'center': coch, 'side': side, 'report': report}


def rotation_angle_deg(R):
    return float(np.degrees(np.arccos(np.clip((np.trace(R) - 1) / 2, -1.0, 1.0))))


def main(argv=None):
    log('converter main() entered')
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--volume', required=True, help='DICOM folder or NIfTI/NRRD file')
    ap.add_argument('--meshes', help='folder with STL/OBJ/PLY files')
    ap.add_argument('--map', default=DEFAULT_MAP, help='JSON mapping structure id -> file-name substrings')
    ap.add_argument('--mesh-frame', default='auto', choices=['RAS', 'LPS', 'ras', 'lps', 'auto'], help='frame of the mesh coordinates; auto picks the one that lands inside the volume')
    ap.add_argument('--mesh-scale', type=float, default=1.0, help='multiply mesh coordinates (e.g. 0.001 for micrometres)')
    ap.add_argument('--target-faces', type=int, default=12000, help='decimate meshes above this many faces')
    ap.add_argument('--context-faces', type=int, default=90000, help='face budget for context surfaces (bone block, dura), which are large')
    ap.add_argument('--spacing', type=float, default=0.3, help='output isotropic voxel size in mm')
    ap.add_argument('--crop', default='auto', help="'auto' (meshes bbox + margin), 'none', or x0,x1,y0,y1,z0,z1 in RAS mm")
    ap.add_argument('--context-spacing', type=float, default=0.3, help='also store the WHOLE volume at this coarser voxel size as a wide-field context around the cropped core (0 = off)')
    ap.add_argument('--margin', type=float, default=6.0, help='margin around the mesh bbox for auto crop (mm)')
    ap.add_argument('--intensity', default='auto', help="'auto', 'hu', or 'scale:a,b' (HU = a*value + b)")
    ap.add_argument('--labels', action='store_true', help='voxelise meshes into a label volume (enables outlines, click-to-select and quiz checks)')
    ap.add_argument('--label-volume', help='segmentation volume (NRRD/NIfTI label map, e.g. OpenEar segmentation) resampled onto the pack grid; preferred over --labels')
    ap.add_argument('--label-names', help='JSON {value: name} for --label-volume when the file carries no names')
    ap.add_argument('--landmarks', help='landmarks.json (from the app or hand-written) to merge')
    ap.add_argument('--allow-misregistered', action='store_true', help='build even when most surface vertices fall outside the volume')
    ap.add_argument('--transforms', help='folder of ITK/Slicer .h5 transforms shipped with a raw (unregistered) scan: their compositions are tried and the one that lands the surfaces on bone is applied to the volume')
    ap.add_argument('--orient', default='auto', choices=['auto', 'none'], help="'auto' rotates everything into the anatomical frame estimated from the segmented structures (cochlea at the origin); 'none' keeps the volume's own axes")
    ap.add_argument('--name', default=None)
    ap.add_argument('--side', default='auto', choices=['R', 'L', 'auto'], help='auto = from the anatomy (needs --orient auto); otherwise R or L')
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
    pre = None               # registration transform for a raw scan (see choose_pretransform)
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
        tfiles = sorted(glob.glob(os.path.join(a.transforms, '*.h5'))) + sorted(glob.glob(os.path.join(a.transforms, '*.tfm'))) if a.transforms else []
        if tfiles and raw:
            pre, pre_frame, report = choose_pretransform(img, raw, tfiles)
            for line in report:
                log(line)
            if pre is not None:
                log('applying the registration chain to the volume; surfaces are %s' % pre_frame)
                if frame == 'AUTO':
                    frame = pre_frame
            else:
                log('no composition of the shipped transforms puts the surfaces on bone; the volume keeps its stored frame')
        if frame == 'AUTO' and raw and pre is None:
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
            if max(fr_ras, fr_lps) < 0.85 and not a.allow_misregistered:
                raise SystemExit('only %.0f%% of the surface vertices lie inside the volume: the surfaces and the volume are not in the same frame '
                                 '(a raw scan with a registered segmentation, wrong --mesh-scale units, or the wrong volume). Apply the registration first, '
                                 'or pass --allow-misregistered to build anyway.' % (100 * max(fr_ras, fr_lps)))
        elif frame == 'AUTO':
            frame = 'RAS'
        for f, v, fc in raw:
            sid, ok = match_id(f, mapping)
            if not ok:
                unmatched.append((os.path.basename(f), sid))
            v, fc = to_frame(v, fc, frame)
            v, fc = decimate(v, fc, a.context_faces if sid in CONTEXT_IDS else a.target_faces)
            if any(m['id'] == sid for m in meshes):
                # merge duplicates (e.g. scala tympani + scala vestibuli -> cochlea)
                prev = next(m for m in meshes if m['id'] == sid)
                off = len(prev['v'])
                prev['v'] = np.concatenate([prev['v'], v]); prev['f'] = np.concatenate([prev['f'], fc + off])
            else:
                meshes.append({'id': sid, 'v': v, 'f': fc, 'file': os.path.basename(f)})
            log('  mesh %-26s <- %s (%d faces)' % (sid, os.path.basename(f), len(fc)))

    # --- anatomical frame ---
    rot = None
    side = a.side if a.side != 'auto' else 'R'
    if a.orient == 'auto' and meshes:
        est = estimate_anatomical_frame(meshes)
        if est is None:
            log('anatomical frame: not enough structures to estimate it (need the cochlea plus EAC/IAC/TM and a facial nerve or ossicle); keeping the volume axes')
        else:
            rot = est
            ang = rotation_angle_deg(est['R'])
            log('anatomical frame from the structures: rotating by %.0f deg; %s ear; cochlea at the origin' % (ang, 'right' if est['side'] == 'R' else 'left'))
            for line in est['report']:
                log('  ' + line)
            if a.side != 'auto' and a.side != est['side']:
                log('  WARNING: --side %s disagrees with the anatomy, which says %s; using %s' % (a.side, est['side'], est['side']))
            side = est['side']
            for m in meshes:
                m['v'] = ((m['v'] - est['center']) @ est['R'].T).astype(np.float64)
    elif a.orient == 'auto':
        log('anatomical frame: no meshes, keeping the volume axes')

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
    arr, origin, spacing = resample_to_ras(img, a.spacing, crop, rot=rot, pre=pre)
    intensity_mode = resolve_intensity(arr, a.intensity)
    arr = intensity_to_hu(arr, intensity_mode)
    arr = np.clip(arr, -1024, 3071).astype(np.int16)
    dims = [arr.shape[2], arr.shape[1], arr.shape[0]]
    log('output volume %s voxels at %.3f mm, %.1f MB' % (dims, a.spacing, arr.nbytes / 1e6))
    context = None
    if a.context_spacing and a.context_spacing > 0 and crop is not None:
        # the whole scan, coarser: the app shows it around the core so the bone is seen in its entirety
        carr, corigin, cspacing = resample_to_ras(img, a.context_spacing, None, rot=rot, pre=pre)
        carr = np.clip(intensity_to_hu(carr, intensity_mode), -1024, 3071).astype(np.int16)
        # a rotated scan's bounding box is mostly empty corners: keep only the slab that holds the specimen
        keep = carr > -900
        if keep.any():
            lo = [int(np.argmax(keep.any(axis=ax))) for ax in ((1, 2), (0, 2), (0, 1))]          # z, y, x first index
            hi = [int(keep.shape[i] - np.argmax(keep.any(axis=ax)[::-1])) for i, ax in enumerate(((1, 2), (0, 2), (0, 1)))]
            lo = [max(0, v - 2) for v in lo]; hi = [min(n, v + 2) for v, n in zip(hi, keep.shape)]
            carr = np.ascontiguousarray(carr[lo[0]:hi[0], lo[1]:hi[1], lo[2]:hi[2]])
            corigin = corigin + np.array([lo[2], lo[1], lo[0]]) * a.context_spacing
        del keep
        cdims = [carr.shape[2], carr.shape[1], carr.shape[0]]
        context = (carr, corigin, cdims)
        log('context volume %s voxels at %.2f mm, %.1f MB (the whole scan around the %.0fx%.0fx%.0f mm core)' % (cdims, a.context_spacing, carr.nbytes / 1e6, (dims[0] - 1) * a.spacing, (dims[1] - 1) * a.spacing, (dims[2] - 1) * a.spacing))

    # --- labels from a segmentation volume (preferred) ---
    label_ids = {}
    labels = None
    if a.label_volume:
        labels, label_ids = labels_from_volume(a.label_volume, a.label_names, origin, spacing, dims, meshes, load_map(a.map) if os.path.exists(a.map) else {}, rot)
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
        if m['id'] in CONTEXT_IDS:
            continue
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
        'side': side,
        'notes': a.notes,
        'registration': ('shipped transform chain applied to the raw scan (see the conversion log)' if pre is not None else 'volume as stored (registered by the dataset authors)'),
        'orientation': ({'source': 'estimated from the segmented structures', 'rotation_deg': round(rotation_angle_deg(rot['R']), 1),
                         'R_rows_in_source_frame': [[round(float(x), 6) for x in row] for row in rot['R']], 'center_source_ras': [round(float(x), 4) for x in rot['center']],
                         'report': rot['report']} if rot else {'source': 'volume axes as stored'}),
        'volume': {'blob': 'volume', 'dims': dims, 'spacing': [float(a.spacing)] * 3, 'origin': [float(x) for x in origin], 'dtype': 'int16', 'units': 'HU', 'encoding': 'delta-x'},
        'labelIds': label_ids,
        'labelSources': getattr(labels_from_volume, 'sources', {}),   # original segment names behind each label id
        'meshes': [],
        'landmarks': landmarks,
    }
    if context is not None:
        carr, corigin, cdims = context
        blobs.append(('context', delta_encode_int16(carr).astype('<i2').tobytes()))
        header['context'] = {'blob': 'context', 'dims': cdims, 'spacing': [float(a.context_spacing)] * 3, 'origin': [float(x) for x in corigin], 'dtype': 'int16', 'units': 'HU', 'encoding': 'delta-x'}
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
