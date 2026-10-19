#!/usr/bin/env python3
"""Self-test for --label-volume: turns the phantom's label map into a 3D Slicer-style two-layer
segmentation (.seg.nrrd, gzip, bone on its own layer), converts it through the streaming reader and
checks the pack's labels against the phantom's own landmarks.

Usage: python3 tools/selftest_labels.py phantom/ /tmp/selftest_labels.tba
"""
import gzip
import json
import os
import subprocess
import sys

import numpy as np
import SimpleITK as sitk

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from tbapack import read_pack  # noqa: E402

phantom, out = sys.argv[1], sys.argv[2]
man = json.load(open(os.path.join(phantom, 'manifest.json')))
img = sitk.ReadImage(os.path.join(phantom, 'labels.nii.gz'))
lab = sitk.GetArrayFromImage(img)                     # [z][y][x], ITK index order
X, Y, Z = img.GetSize()
ids = {int(k): v for k, v in man['labelIds'].items()}
# layer 0: the phantom labels, renumbered 1..n in a shuffled order so values != final ids
values = sorted(ids)
layer0 = np.zeros_like(lab)
fields = []
for n, v in enumerate(values):
    layer0[lab == v] = n + 1
    fields += ['Segment%d_LabelValue:=%d' % (n, n + 1), 'Segment%d_Layer:=0' % n, 'Segment%d_Name:=%s' % (n, ids[v])]
# layer 1: "Bone" everywhere the CT would be bone-ish (a big block) overlapping everything
layer1 = np.zeros_like(lab)
layer1[16:-16, 16:-16, 16:-16] = 1
k = len(values)
fields += ['Segment%d_LabelValue:=1' % k, 'Segment%d_Layer:=1' % k, 'Segment%d_Name:=Bone' % k]
d = img.GetDirection(); o = img.GetOrigin(); sp = img.GetSpacing()
hdr = ['NRRD0004', 'type: unsigned char', 'dimension: 4', 'space: left-posterior-superior', 'sizes: 2 %d %d %d' % (X, Y, Z),
       'space directions: none (%g,%g,%g) (%g,%g,%g) (%g,%g,%g)' % (d[0] * sp[0], d[3] * sp[0], d[6] * sp[0], d[1] * sp[1], d[4] * sp[1], d[7] * sp[1], d[2] * sp[2], d[5] * sp[2], d[8] * sp[2]),
       'kinds: list domain domain domain', 'encoding: gzip', 'space origin: (%g,%g,%g)' % o] + fields
seg_path = os.path.splitext(out)[0] + '.seg.nrrd'
with open(seg_path, 'wb') as f:
    f.write(('\n'.join(hdr) + '\n\n').encode())
    f.write(gzip.compress(np.ascontiguousarray(np.stack([layer0, layer1], axis=-1)).tobytes(), 4))
print('wrote', seg_path, '%.1f MB' % (os.path.getsize(seg_path) / 1e6))

cmd = [sys.executable, '-u', os.path.join(os.path.dirname(os.path.abspath(__file__)), 'convert_openear.py'),
       '--volume', os.path.join(phantom, 'volume.nii.gz'), '--meshes', os.path.join(phantom, 'meshes'), '--spacing', '0.3',
       '--label-volume', seg_path, '--name', 'selftest-labels', '--out', out]
subprocess.run(cmd, check=True)

header, blobs = read_pack(out)
labels = np.frombuffer(blobs['labels'], np.uint8).reshape(header['labels']['dims'][::-1])
origin = np.array(header['labels']['origin']); spacing = np.array(header['labels']['spacing'])
got = header['labelIds']
assert 'bone_shell' not in got.values() and 'bone' not in got.values(), got
missing = set(ids.values()) - set(got.values())
print('pack labels: %d (missing from the pack: %s)' % (len(got), sorted(missing) or 'none'))
# independent ground truth: SimpleITK resamples the original phantom label map onto the pack grid
nx, ny, nz = header['labels']['dims']
ref = sitk.Image([nx, ny, nz], sitk.sitkUInt8)
ref.SetSpacing([float(s) for s in spacing]); ref.SetDirection([1, 0, 0, 0, 1, 0, 0, 0, 1])
ref.SetOrigin([-(origin[0] + (nx - 1) * spacing[0]), -(origin[1] + (ny - 1) * spacing[1]), origin[2]])
truth = sitk.GetArrayFromImage(sitk.Resample(img, ref, sitk.Transform(), sitk.sitkNearestNeighbor, 0, sitk.sitkUInt8))[:, ::-1, ::-1]
value_of = {v: int(k) for k, v in got.items()}
worst = (1.0, None)
for v, sid in ids.items():
    if sid not in value_of:
        continue
    a = labels == value_of[sid]; b = truth == v
    n = int(b.sum())
    if n == 0:
        continue
    dice = 2.0 * int((a & b).sum()) / (int(a.sum()) + n)
    if dice < worst[0]:
        worst = (dice, sid)
print('worst per-structure Dice against ITK resampling of the original label map: %.4f (%s)' % worst)
assert worst[0] > 0.98, 'label volume does not line up with the original label map'
print('selftest_labels OK')
