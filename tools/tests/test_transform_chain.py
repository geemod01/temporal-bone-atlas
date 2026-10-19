import os as _os
_TOOLS = _os.path.normpath(_os.path.join(_os.path.dirname(_os.path.abspath(__file__)), '..'))
_WORK = _os.environ.get('TBA_TEST_DIR', _os.path.join(_os.path.dirname(_os.path.abspath(__file__)), '_work'))
_os.makedirs(_WORK, exist_ok=True)

"""A raw-frame copy of the full-size fixture CT plus a split, partly inverted transform chain and a decoy:
the converter must recover the chain and produce the same pack as from the registered volume."""
import os, subprocess, sys, time
import numpy as np
import SimpleITK as sitk

S = _WORK
sys.path.insert(0, _TOOLS)
from tbapack import read_pack  # noqa

src = os.path.join(S, 'fullsize/05_Registred_Slicer_Volumes/CBCT_EMBEDDED_Delta.nrrd')
out_dir = os.path.join(S, 'rawfix'); os.makedirs(os.path.join(out_dir, 'tf'), exist_ok=True)
img = sitk.ReadImage(src)
# T: registered LPS -> raw LPS (rigid, 25 deg about a skew axis + translation)
Ta = sitk.Euler3DTransform(); Ta.SetRotation(0.2, -0.3, 0.25); Ta.SetTranslation([12.0, -7.0, 20.0]); Ta.SetCenter([-40.0, -40.0, 40.0])
Tb = sitk.AffineTransform(3); Tb.SetMatrix([-1, 0, 0, 0, -1, 0, 0, 0, 1])        # a FlipXY-like step
# full chain: apply Ta first, then Tb  ->  T = Tb o Ta
T = sitk.CompositeTransform([Tb, Ta])
Tinv = T.GetInverse()
# raw grid covering T(registered volume)
size = np.array(img.GetSize())
corners = np.array([T.TransformPoint(img.TransformIndexToPhysicalPoint((int(i), int(j), int(k)))) for i in (0, size[0]-1) for j in (0, size[1]-1) for k in (0, size[2]-1)])
lo, hi = corners.min(0), corners.max(0)
sp = 0.25   # coarser raw grid keeps the test quick; the registered fixture stays at 0.1252
n = np.ceil((hi - lo) / sp).astype(int) + 1
ref = sitk.Image([int(x) for x in n], sitk.sitkInt16); ref.SetSpacing([sp] * 3); ref.SetOrigin([float(x) for x in lo])
t0 = time.time()
raw = sitk.Resample(img, ref, Tinv, sitk.sitkLinear, -1024, sitk.sitkInt16)     # value_raw(q) = value_reg(T^-1 q)
sitk.WriteImage(raw, os.path.join(out_dir, 'raw_scan.nrrd'), useCompression=True)
print('raw scan written', raw.GetSize(), 'in %.0fs' % (time.time() - t0))
# shipped transforms: Ta as is, Tb INVERTED (so the search must invert it back), plus a decoy
sitk.WriteTransform(Ta, os.path.join(out_dir, 'tf', 'CBCT_InitialGuess.h5'))
sitk.WriteTransform(Tb.GetInverse(), os.path.join(out_dir, 'tf', 'FlipXY.h5'))
decoy = sitk.Euler3DTransform(); decoy.SetRotation(0.5, 0.1, -0.4); decoy.SetTranslation([3.0, 30.0, -11.0])
sitk.WriteTransform(decoy, os.path.join(out_dir, 'tf', 'CBCT_BrainsFit.h5'))

conv = _os.path.join(_TOOLS, 'convert_openear.py')
common = ['--meshes', os.path.join(S, 'fullsize/07_3D_Models'), '--mesh-frame', 'auto', '--spacing', '0.3', '--intensity', 'hu', '--orient', 'auto', '--name', 'chain-test',
          '--label-volume', os.path.join(S, 'fullsize/06_Segmentation/Segmentation.seg.nrrd')]
t0 = time.time()
r = subprocess.run([sys.executable, conv, '--volume', os.path.join(out_dir, 'raw_scan.nrrd'), '--transforms', os.path.join(out_dir, 'tf'), '--out', os.path.join(out_dir, 'from_raw.tba')] + common, capture_output=True, text=True)
log = r.stderr
print('\n'.join(l for l in log.splitlines() if 'transform search' in l or 'edge ' in l or 'applying' in l or 'no composition' in l or 'anatomical frame' in l or 'wrote' in l or 'Error' in l or 'only ' in l))
assert r.returncode == 0, log[-3000:]
r2 = subprocess.run([sys.executable, conv, '--volume', src, '--out', os.path.join(out_dir, 'from_reg.tba')] + common, capture_output=True, text=True)
assert r2.returncode == 0, r2.stderr[-2000:]
print('both conversions done in %.0fs' % (time.time() - t0))
ha, ba = read_pack(os.path.join(out_dir, 'from_raw.tba')); hb, bb = read_pack(os.path.join(out_dir, 'from_reg.tba'))
assert ha['volume']['dims'] == hb['volume']['dims'], (ha['volume']['dims'], hb['volume']['dims'])
def vol(h, b):
    d = h['volume']['dims']; raw = np.frombuffer(b['volume'], '<i2').reshape(d[::-1]); return np.cumsum(raw.astype(np.uint16), axis=-1, dtype=np.uint16).astype(np.int16).astype(np.float32)
va, vb = vol(ha, ba), vol(hb, bb)
bone = vb > 300
diff = np.abs(va - vb)
print('CT from the raw scan vs from the registered one: mean |diff| %.1f HU overall, %.1f HU on bone; correlation %.4f' % (diff.mean(), diff[bone].mean(), np.corrcoef(va.ravel()[::7], vb.ravel()[::7])[0, 1]))
la = np.frombuffer(ba['labels'], np.uint8); lb = np.frombuffer(bb['labels'], np.uint8)
print('labels identical:', np.array_equal(la, lb), '| meshes:', [m['id'] for m in ha['meshes']] == [m['id'] for m in hb['meshes']], '| side', ha['side'], hb['side'])
assert np.corrcoef(va.ravel()[::7], vb.ravel()[::7])[0, 1] > 0.97
print('transform chain test OK')
