"""Checks NrrdStream + the lean label sampler against SimpleITK on Slicer-style files."""
import os as _os
_TOOLS = _os.path.normpath(_os.path.join(_os.path.dirname(_os.path.abspath(__file__)), '..'))
_WORK = _os.environ.get('TBA_TEST_DIR', _os.path.join(_os.path.dirname(_os.path.abspath(__file__)), '_work'))
_os.makedirs(_WORK, exist_ok=True)

import bz2
import gzip
import os
import sys
import time
import zlib

import numpy as np
import SimpleITK as sitk

sys.path.insert(0, _TOOLS)
import convert_openear as co  # noqa: E402

OUT = os.path.join(_WORK, 'nrrd_fixtures')
os.makedirs(OUT, exist_ok=True)


def write_nrrd(path, data, layers_first=True, encoding='gzip', space='left-posterior-superior', dirs=((0.125, 0, 0), (0, 0.125, 0), (0, 0, 0.125)), origin=(26, 24, -24), extra=(), dtype='unsigned char', kinds_name='list'):
    """data: (N, Z, Y, X) numpy (N layers) or (Z, Y, X)."""
    hdr = ['NRRD0004', '# test fixture', 'type: %s' % dtype]
    if data.ndim == 4:
        N, Z, Y, X = data.shape
        hdr.append('dimension: 4')
        hdr.append('space: %s' % space)
        if layers_first:
            hdr.append('sizes: %d %d %d %d' % (N, X, Y, Z))
            hdr.append('space directions: none (%g,%g,%g) (%g,%g,%g) (%g,%g,%g)' % tuple(sum(dirs, ())))
            hdr.append('kinds: %s domain domain domain' % kinds_name)
            raw = np.ascontiguousarray(np.moveaxis(data, 0, -1))   # (Z, Y, X, N): N fastest
        else:
            hdr.append('sizes: %d %d %d %d' % (X, Y, Z, N))
            hdr.append('space directions: (%g,%g,%g) (%g,%g,%g) (%g,%g,%g) none' % tuple(sum(dirs, ())))
            hdr.append('kinds: domain domain domain %s' % kinds_name)
            raw = np.ascontiguousarray(data)                       # (N, Z, Y, X)
    else:
        Z, Y, X = data.shape
        hdr += ['dimension: 3', 'space: %s' % space, 'sizes: %d %d %d' % (X, Y, Z),
                'space directions: (%g,%g,%g) (%g,%g,%g) (%g,%g,%g)' % tuple(sum(dirs, ())), 'kinds: domain domain domain']
        raw = np.ascontiguousarray(data)
    if np.dtype(data.dtype).itemsize > 1:
        hdr.append('endian: little')
    hdr.append('encoding: %s' % encoding)
    hdr.append('space origin: (%g,%g,%g)' % tuple(origin))
    hdr += list(extra)
    body = raw.astype(raw.dtype.newbyteorder('<')).tobytes()
    if encoding == 'gzip':
        body = gzip.compress(body, 6)
    elif encoding == 'bzip2':
        body = bz2.compress(body)
    with open(path, 'wb') as f:
        f.write(('\n'.join(hdr) + '\n\n').encode()); f.write(body)


def make_segmentation(Z=96, Y=80, X=72, seed=1):
    rng = np.random.default_rng(seed)
    zz, yy, xx = np.mgrid[0:Z, 0:Y, 0:X]
    L0 = np.zeros((Z, Y, X), np.uint8)
    L1 = np.zeros((Z, Y, X), np.uint8)
    # layer 0: small structures (spheres), values 1..4
    for v, (cz, cy, cx, r) in enumerate([(40, 40, 36, 9), (60, 30, 30, 6), (30, 55, 50, 5), (70, 60, 20, 4)], start=1):
        L0[(zz - cz) ** 2 + (yy - cy) ** 2 + (xx - cx) ** 2 <= r * r] = v
    # layer 1: a big "bone" (value 1) overlapping everything + a tube (value 2)
    L1[(zz > 10) & (zz < 90) & (yy > 8) & (yy < 70) & ((xx + yy + zz) % 7 != 0)] = 1
    L1[((yy - 40) ** 2 + (xx - 36) ** 2 <= 9)] = 2
    noise = rng.integers(0, 2, size=(Z, Y, X), dtype=np.uint8)   # make it less compressible in places
    L1[(zz % 13 == 0)] = noise[(zz % 13 == 0)]
    return np.stack([L0, L1])


SEG_FIELDS = ['Segment0_LabelValue:=1', 'Segment0_Layer:=0', 'Segment0_Name:=Scala Tympani',
              'Segment1_LabelValue:=2', 'Segment1_Layer:=0', 'Segment1_Name:=Malleus',
              'Segment2_LabelValue:=3', 'Segment2_Layer:=0', 'Segment2_Name:=Incus',
              'Segment3_LabelValue:=4', 'Segment3_Layer:=0', 'Segment3_Name:=Stapes',
              'Segment4_LabelValue:=1', 'Segment4_Layer:=1', 'Segment4_Name:=Bone',
              'Segment5_LabelValue:=2', 'Segment5_Layer:=1', 'Segment5_Name:=Facial Nerve']

seg = make_segmentation()
N, Z, Y, X = seg.shape
dirs_flip = ((-0.125, 0, 0), (0, -0.125, 0), (0, 0, 0.125))
fixtures = {
    'seg4d_gz.seg.nrrd': dict(data=seg, encoding='gzip', dirs=dirs_flip),
    'seg4d_raw.seg.nrrd': dict(data=seg, encoding='raw', dirs=dirs_flip),
    'seg4d_planar.seg.nrrd': dict(data=seg, encoding='gzip', dirs=dirs_flip, layers_first=False),
    'seg3d_gz.nrrd': dict(data=seg[1], encoding='gzip', dirs=dirs_flip),
    'seg3d_short.nrrd': dict(data=seg[1].astype(np.int16) * 100, encoding='gzip', dirs=dirs_flip, dtype='short'),
    'seg4d_ras.seg.nrrd': dict(data=seg, encoding='gzip', space='right-anterior-superior', dirs=((0.125, 0, 0), (0, 0.125, 0), (0, 0, 0.125)), origin=(-26, -24, -24)),
    'seg4d_rot.seg.nrrd': dict(data=seg, encoding='gzip', dirs=((0.125 * 0.96, 0.125 * 0.28, 0), (-0.125 * 0.28, 0.125 * 0.96, 0), (0, 0, 0.125))),
}
for name, kw in fixtures.items():
    write_nrrd(os.path.join(OUT, name), extra=SEG_FIELDS if 'seg' in name else (), **kw)

# ---- 1. block reads agree with SimpleITK everywhere ----
fails = 0
for name in fixtures:
    path = os.path.join(OUT, name)
    try:
        lv = co.LazyVolume(path)
    except Exception as e:
        print('ITK cannot read %s: %s' % (name, e)); fails += 1; continue
    if lv.nrrd is None:
        print('%-24s no streaming (%s)' % (name, 'planar layout is expected to fall back' if 'planar' in name else 'UNEXPECTED')); fails += 'planar' not in name; continue
    whole = sitk.ReadImage(path)
    rng = np.random.default_rng(0)
    t0 = time.time()
    for trial in range(6):
        i0 = rng.integers(0, [X // 2, Y // 2, Z // 2]); sz = rng.integers(1, [X - i0[0], Y - i0[1], Z - i0[2]] + np.array([1, 1, 1]))
        for layer in range(lv.components):
            blk = lv.nrrd.read_block(i0, sz, layer)
            ref = whole if whole.GetNumberOfComponentsPerPixel() == 1 else sitk.VectorIndexSelectionCast(whole, layer)
            ref = sitk.GetArrayFromImage(sitk.RegionOfInterest(ref, [int(x) for x in sz], [int(x) for x in i0]))
            if not np.array_equal(blk.astype(np.int64), ref.astype(np.int64)):
                print('MISMATCH', name, 'layer', layer, i0, sz); fails += 1
    img = lv.block_image((3, 4, 5), (10, 11, 12))
    p1 = img.TransformIndexToPhysicalPoint((0, 0, 0)); p2 = whole.TransformIndexToPhysicalPoint((3, 4, 5))
    if not np.allclose(p1, p2):
        print('GEOMETRY MISMATCH', name, p1, p2); fails += 1
    print('%-24s layers=%d dtype=%s enc=%s  blocks ok (%.2fs)' % (name, lv.components, lv.nrrd.dtype, lv.nrrd.encoding, time.time() - t0))

# ---- 2. lean label sampling == whole-volume ITK resampling, on a pack grid that partly overlaps ----
spacing = np.array([0.15, 0.15, 0.15])
origin = np.array([-30.0 + 0.3, -28.0 + 0.1, -21.0 + 0.05])   # RAS origin of the pack grid (partly outside the seg)
dims = [70, 60, 50]


def reference_layers(path):
    whole = sitk.ReadImage(path)
    ref = co.pack_grid_in_lps(origin, spacing, dims)
    outs = []
    Nc = whole.GetNumberOfComponentsPerPixel()
    for n in range(Nc):
        img = whole if Nc == 1 else sitk.VectorIndexSelectionCast(whole, n)
        img = sitk.Cast(img, sitk.sitkUInt16)
        res = sitk.Resample(img, ref, sitk.Transform(), sitk.sitkNearestNeighbor, 0, sitk.sitkUInt16)
        outs.append(sitk.GetArrayFromImage(res)[:, ::-1, ::-1])
    return outs


for name in fixtures:
    path = os.path.join(OUT, name)
    lv = co.LazyVolume(path)
    mine = co.sample_label_layers(lv, origin, spacing, dims)
    refs = reference_layers(path)
    for n, (a, b) in enumerate(zip(mine, refs)):
        a = a.astype(np.int64); b = b.astype(np.int64)
        diff = int((a != b).sum())
        nz = int((b != 0).sum())
        # nearest-neighbour ties on exact half-voxel positions can legitimately differ; allow a sliver
        ok = diff <= max(2, nz // 2000) if 'rot' not in name else diff <= max(50, nz // 100)
        print('%-24s layer %d: %7d labelled voxels, %5d differ from ITK %s' % (name, n, nz, diff, 'ok' if ok else 'FAIL'))
        fails += not ok

# ---- 3. the whole labels_from_volume path: names, layer priority, bone dropped ----
mapping = co.load_map(_os.path.join(_TOOLS, 'openear_map.json'))
labels, ids = co.labels_from_volume(os.path.join(OUT, 'seg4d_gz.seg.nrrd'), None, origin, spacing, dims, [], mapping)
print('label ids:', ids)
assert 'bone_shell' not in ids.values() and 'bone' not in ids.values(), 'bone must be dropped'
assert {'cochlea', 'malleus', 'facial_nerve'} <= set(ids.values()) <= {'cochlea', 'malleus', 'incus', 'stapes', 'facial_nerve'}, ids
# a voxel inside the malleus sphere (layer 0) that is also bone (layer 1) must read malleus
cz, cy, cx = 60, 30, 30
p_lps = np.array([26, 24, -24]) + np.array([-0.125 * cx, -0.125 * cy, 0.125 * cz])
p_ras = np.array([-p_lps[0], -p_lps[1], p_lps[2]])
k = np.rint((p_ras - origin) / spacing).astype(int)
if np.all(k >= 0) and np.all(k < np.array(dims)):
    v = labels[k[2], k[1], k[0]]
    print('voxel at malleus centre ->', ids.get(str(v)))
    assert ids.get(str(v)) == 'malleus', 'small structure must win over bone'
else:
    print('malleus centre outside the test grid (k=%s); skipped' % k)

# ---- 4. old-Slicer layout (one binary layer per segment, Segment*_Name only) + name-less overlap path ----
import trimesh
old = np.stack([(seg[0] == 1).astype(np.uint8), (seg[0] == 2).astype(np.uint8), (seg[1] == 1).astype(np.uint8)])   # scala tympani, malleus, bone
fields_old = ['Segment0_Name:=Scala Tympani', 'Segment0_ID:=Segment_1', 'Segment1_Name:=Malleus', 'Segment2_Name:=Bone']
grid_origin = np.array([-26.0 + 0.125 * 0, -24.0, -24.0]); grid_dims = [96, 100, 120]; grid_sp = np.array([0.5, 0.5, 0.5])
write_nrrd(os.path.join(OUT, 'seg4d_old.seg.nrrd'), old, encoding='gzip', dirs=dirs_flip, extra=fields_old)
labels, ids = co.labels_from_volume(os.path.join(OUT, 'seg4d_old.seg.nrrd'), None, grid_origin, grid_sp, grid_dims, [], mapping)
print('old-Slicer ids:', ids)
assert set(ids.values()) == {'cochlea', 'malleus'}, ids
# same data without any names: meshes must drive the matching and bone must not be absorbed
write_nrrd(os.path.join(OUT, 'seg4d_noname.seg.nrrd'), old, encoding='gzip', dirs=dirs_flip)
def sphere_mesh(sid, c_idx, r_idx):
    c = np.array([-26.0 + 0.125 * c_idx[2], -24.0 + 0.125 * c_idx[1], -24.0 + 0.125 * c_idx[0]])   # idx (z, y, x) -> RAS
    m = trimesh.creation.icosphere(subdivisions=2, radius=r_idx * 0.125); m.apply_translation(c)
    return {'id': sid, 'v': np.asarray(m.vertices, np.float64), 'f': np.asarray(m.faces, np.int64)}
meshes = [sphere_mesh('cochlea', (40, 40, 36), 9), sphere_mesh('malleus', (60, 30, 30), 6), sphere_mesh('facial_nerve', (30, 55, 50), 5)]
labels, ids = co.labels_from_volume(os.path.join(OUT, 'seg4d_noname.seg.nrrd'), None, grid_origin, grid_sp, grid_dims, meshes, mapping)
print('overlap-matched ids:', ids)
assert set(ids.values()) == {'cochlea', 'malleus'}, ids
print('old-Slicer + overlap paths OK')

print('FAILS:', fails)
sys.exit(1 if fails else 0)
