"""Full-size stand-in for OpenEar Delta: a 632x617x668 CBCT (int16, gzip NRRD) plus a 2-layer Slicer-style
segmentation of the same grid with 12 segments (bone on its own layer), and matching PLY surfaces.
Everything is streamed slice by slice so this script itself needs almost no memory."""
import gzip
import os
import sys

import numpy as np
import trimesh

OUT = sys.argv[1]
os.makedirs(os.path.join(OUT, '05_Registred_Slicer_Volumes'), exist_ok=True)
os.makedirs(os.path.join(OUT, '06_Segmentation'), exist_ok=True)
os.makedirs(os.path.join(OUT, '07_3D_Models'), exist_ok=True)

X, Y, Z = 632, 617, 668
SP = 0.1252
O_LPS = np.array([-66.3, -63.1, -4.7])      # LPS origin, positive directions -> RAS x = 66.3 - SP*i etc.


def ras_of(i, j, k):
    return np.array([-(O_LPS[0] + SP * i), -(O_LPS[1] + SP * j), O_LPS[2] + SP * k])


# structures (RAS mm): name, kind, params, layer, value
# layer 0 = small structures, layer 1 = bone (1) + EAC/sigmoid/carotid (2,3,4) which overlap bone
STRUCTS = [
    ('Scala Tympani', 'sphere', ((20.0, 15.0, 40.0), 3.2), 0, 1),
    ('Scala Vestibuli', 'sphere', ((23.5, 17.0, 42.0), 2.6), 0, 2),
    ('Malleus', 'sphere', ((14.0, 20.0, 48.0), 2.0), 0, 3),
    ('Incus', 'sphere', ((12.0, 17.5, 48.5), 1.8), 0, 4),
    ('Stapes', 'sphere', ((16.5, 17.0, 45.0), 1.1), 0, 5),
    ('Facial Nerve', 'tube', ((24.0, 22.0, 46.0), (10.0, 14.0, 30.0), 0.9), 0, 6),
    ('Chorda Tympani', 'tube', ((12.0, 16.0, 36.0), (13.0, 21.0, 49.0), 0.35), 0, 7),
    ('Cochleovestibular Nerve', 'tube', ((30.0, 13.0, 41.0), (22.0, 16.0, 41.0), 1.2), 0, 8),
    ('Tympanic Membrane', 'disc', ((9.0, 20.0, 44.0), 4.0, 0.3), 0, 9),
    ('Bone', 'box', ((-2.0, -4.0, 20.0), (44.0, 38.0, 66.0)), 1, 1),
    ('External_Auditory_Canal', 'tube', ((0.0, 20.0, 44.0), (9.0, 20.0, 44.0), 3.5), 1, 2),
    ('Sinus_Dura', 'tube', ((34.0, 36.0, 20.0), (30.0, 30.0, 66.0), 4.0), 1, 3),
    ('Carotis Interna', 'tube', ((20.0, 4.0, 20.0), (24.0, 8.0, 52.0), 2.5), 1, 4),
]


def mask_of(kind, params, P):
    """P: (..., 3) RAS points."""
    if kind == 'sphere':
        c, r = params
        return ((P - np.array(c)) ** 2).sum(-1) <= r * r
    if kind == 'tube':
        a, b, r = params
        a = np.array(a); b = np.array(b); d = b - a; L2 = (d ** 2).sum()
        t = np.clip(((P - a) * d).sum(-1) / L2, 0, 1)
        q = a + t[..., None] * d
        return ((P - q) ** 2).sum(-1) <= r * r
    if kind == 'disc':
        c, r, h = params
        c = np.array(c)
        return (np.abs(P[..., 0] - c[0]) <= h) & (((P[..., 1] - c[1]) ** 2 + (P[..., 2] - c[2]) ** 2) <= r * r)
    if kind == 'box':
        lo, hi = params
        return np.all((P >= np.array(lo)) & (P <= np.array(hi)), axis=-1)
    raise ValueError(kind)


def mesh_of(kind, params):
    if kind == 'sphere':
        c, r = params
        m = trimesh.creation.icosphere(subdivisions=3, radius=r); m.apply_translation(c); return m
    if kind == 'tube':
        a, b, r = params
        a = np.array(a); b = np.array(b)
        m = trimesh.creation.cylinder(radius=r, height=float(np.linalg.norm(b - a)), sections=24)
        d = (b - a) / np.linalg.norm(b - a)
        T = trimesh.geometry.align_vectors([0, 0, 1], d)
        m.apply_transform(T); m.apply_translation((a + b) / 2); return m
    if kind == 'disc':
        c, r, h = params
        m = trimesh.creation.cylinder(radius=r, height=2 * h, sections=32)
        m.apply_transform(trimesh.geometry.align_vectors([0, 0, 1], [1, 0, 0])); m.apply_translation(c); return m
    if kind == 'box':
        lo, hi = params
        m = trimesh.creation.box(extents=np.array(hi) - np.array(lo)); m.apply_translation((np.array(lo) + np.array(hi)) / 2); return m


# --- meshes (RAS, like OpenEar) ---
for i, (name, kind, params, layer, value) in enumerate(STRUCTS):
    m = mesh_of(kind, params)
    fname = '%02d_%s.ply' % (i + 1, name) if name not in ('External_Auditory_Canal',) else 'External_Auditory_Canal.ply'
    if name == 'Bone':
        fname = '12_Bone.ply'
    m.export(os.path.join(OUT, '07_3D_Models', fname))
print('meshes written')

# --- volumes, streamed ---
hdr_ct = ['NRRD0004', 'type: short', 'dimension: 3', 'space: left-posterior-superior', 'sizes: %d %d %d' % (X, Y, Z),
          'space directions: (%g,0,0) (0,%g,0) (0,0,%g)' % (SP, SP, SP), 'kinds: domain domain domain', 'endian: little',
          'encoding: gzip', 'space origin: (%g,%g,%g)' % tuple(O_LPS)]
seg_fields = []
for i, (name, kind, params, layer, value) in enumerate(STRUCTS):
    seg_fields += ['Segment%d_ID:=Segment_%d' % (i, i + 1), 'Segment%d_LabelValue:=%d' % (i, value), 'Segment%d_Layer:=%d' % (i, layer), 'Segment%d_Name:=%s' % (i, name)]
hdr_seg = ['NRRD0004', 'type: unsigned char', 'dimension: 4', 'space: left-posterior-superior', 'sizes: 2 %d %d %d' % (X, Y, Z),
           'space directions: none (%g,0,0) (0,%g,0) (0,0,%g)' % (SP, SP, SP), 'kinds: list domain domain domain', 'encoding: gzip',
           'space origin: (%g,%g,%g)' % tuple(O_LPS)] + seg_fields

ii, jj = np.meshgrid(np.arange(X), np.arange(Y), indexing='xy')   # (Y, X)
rng = np.random.default_rng(3)
with open(os.path.join(OUT, '05_Registred_Slicer_Volumes', 'CBCT_EMBEDDED_Delta.nrrd'), 'wb') as fct, \
     open(os.path.join(OUT, '06_Segmentation', 'Segmentation.seg.nrrd'), 'wb') as fseg:
    fct.write(('\n'.join(hdr_ct) + '\n\n').encode()); fseg.write(('\n'.join(hdr_seg) + '\n\n').encode())
    gct = gzip.GzipFile(fileobj=fct, mode='wb', compresslevel=3); gseg = gzip.GzipFile(fileobj=fseg, mode='wb', compresslevel=3)
    for k in range(Z):
        P = np.stack([-(O_LPS[0] + SP * ii), -(O_LPS[1] + SP * jj), np.full(ii.shape, O_LPS[2] + SP * k)], axis=-1)
        seg = np.zeros((Y, X, 2), np.uint8)
        for name, kind, params, layer, value in STRUCTS:
            m = mask_of(kind, params, P)
            seg[..., layer][m] = value
        # CT: bone box with trabecular noise, air in EAC/structures of layer 0 soft tissue, else -1000
        ct = np.full((Y, X), -1000.0, np.float32)
        bone = seg[..., 1] == 1
        ct[bone] = 1200 + 600 * np.sin(P[bone][:, 0] * 2.1) * np.cos(P[bone][:, 1] * 1.7) + rng.normal(0, 120, bone.sum())
        soft = seg[..., 0] > 0
        ct[soft] = 40 + rng.normal(0, 20, soft.sum())
        ct[seg[..., 1] == 2] = -980          # EAC air
        ct[seg[..., 1] == 3] = 60            # sinus
        ct[seg[..., 1] == 4] = 55            # carotid
        gct.write(np.clip(ct, -1024, 3071).astype('<i2').tobytes())
        gseg.write(seg.tobytes())
        if k % 100 == 0:
            print('slice', k, flush=True)
    gct.close(); gseg.close()
print('done')
for root, _, files in os.walk(OUT):
    for f in files:
        p = os.path.join(root, f)
        print('%8.1f MB  %s' % (os.path.getsize(p) / 1e6, os.path.relpath(p, OUT)))
