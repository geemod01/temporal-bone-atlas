"""Rotated label sampling (streaming, bucketed by source slice) must match ITK's affine nearest-neighbour resampling."""
import os as _os
_TOOLS = _os.path.normpath(_os.path.join(_os.path.dirname(_os.path.abspath(__file__)), '..'))
_WORK = _os.environ.get('TBA_TEST_DIR', _os.path.join(_os.path.dirname(_os.path.abspath(__file__)), '_work'))
_os.makedirs(_WORK, exist_ok=True)

import os, sys, numpy as np, SimpleITK as sitk
sys.path.insert(0, _TOOLS)
import convert_openear as co
OUT = os.path.join(_WORK, 'nrrd_fixtures')
spacing = np.array([0.15, 0.15, 0.15]); dims = [70, 60, 50]
origin = np.array([-5.25 + 0.03, -4.5 + 0.01, -3.75 + 0.02])   # the output frame has the rotation centre at its origin
# a rotation of 37 deg about a skewed axis, centred somewhere inside the fixture
def rotmat(axis, deg):
    a = np.radians(deg); k = axis / np.linalg.norm(axis); K = np.array([[0, -k[2], k[1]], [k[2], 0, -k[0]], [-k[1], k[0], 0]])
    return np.eye(3) + np.sin(a) * K + (1 - np.cos(a)) * K @ K
rot = {'R': rotmat(np.array([0.3, 1.0, 0.5]), 37.0), 'center': np.array([-22.0, -20.0, -19.0])}
fails = 0
for name in ['seg4d_gz.seg.nrrd', 'seg4d_planar.seg.nrrd', 'seg3d_short.nrrd', 'seg4d_rot.seg.nrrd']:
    path = os.path.join(OUT, name)
    lv = co.LazyVolume(path)
    mine = co.sample_label_layers(lv, origin, spacing, dims, rot)
    # reference: ITK on the whole image with the same affine
    whole = sitk.ReadImage(path)
    ref = co.pack_grid_in_lps(origin, spacing, dims)
    Rt, c = co.out_to_in_ras(rot)
    tf = sitk.AffineTransform(3); tf.SetMatrix([float(x) for x in (co.FLIP_LPS @ Rt @ co.FLIP_LPS).ravel()]); tf.SetTranslation([float(x) for x in (co.FLIP_LPS @ c)])
    Nc = whole.GetNumberOfComponentsPerPixel()
    for n in range(Nc):
        img = whole if Nc == 1 else sitk.VectorIndexSelectionCast(whole, n)
        img = sitk.Cast(img, sitk.sitkUInt16)
        res = sitk.GetArrayFromImage(sitk.Resample(img, ref, tf, sitk.sitkNearestNeighbor, 0, sitk.sitkUInt16))[:, ::-1, ::-1]
        a = mine[n].astype(np.int64); b = res.astype(np.int64)
        diff = int((a != b).sum()); nz = int((b != 0).sum())
        ok = diff <= max(3, nz // 200)     # rotated grids put many samples near voxel-boundary ties
        print('%-24s layer %d: %7d labelled, %5d differ %s' % (name, n, nz, diff, 'ok' if ok else 'FAIL')); fails += not ok
print('FAILS', fails); sys.exit(1 if fails else 0)
