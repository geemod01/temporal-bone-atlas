#!/usr/bin/env python3
"""
Fetch one OpenEar specimen from Zenodo (record 1473724), extract only the parts the atlas
needs (CBCT volume + segmentation surfaces), convert them to a .tba pack and register the
pack in data/datasets.json.

It reads the zip *remotely* with HTTP range requests, so only the needed members
(hundreds of MB) come down instead of the whole 4-14 GB archive. If the server refuses
ranges it falls back to a full download (--full).

Examples
--------
  python3 tools/fetch_openear.py --specimen delta --list            # show what is in the archive
  python3 tools/fetch_openear.py --specimen delta --out data        # fetch + convert
  python3 tools/fetch_openear.py --specimen all --out data          # every specimen (slow)

Nothing here needs the user's machine: it is what the GitHub Actions workflow runs.
"""
import argparse
import io
import json
import os
import re
import subprocess
import sys
import time
import zipfile

import requests

RECORD = '1473724'
API = 'https://zenodo.org/api/records/' + RECORD
SPECIMENS = ['alpha', 'beta', 'gamma', 'delta', 'epsilon', 'zeta', 'eta', 'theta']
HERE = os.path.dirname(os.path.abspath(__file__))

VOLUME_EXT = re.compile(r'\.(dcm|dicom|ima|nrrd|nhdr|nii|nii\.gz|mha|mhd|raw|vti|seg\.nrrd)$', re.I)
MESH_EXT = re.compile(r'\.(stl|obj|ply|off|vtk|vtp)$', re.I)
RAW_DIR = re.compile(r'(raw|dicom|tiff?)', re.I)
META_EXT = re.compile(r'\.(txt|md|json|csv|xml|pdf|rtf)$', re.I)
# folders that are clearly the colour micro-slicing stacks (the bulk of every archive)
SKIP_DIR = re.compile(r'(micro.?slic|microsection|slic(e|ing).?image|histolog|photo|png|jpg|tif)', re.I)


_progress = {'lines': [], 'last': 0.0, 'id': None}


def _post_progress(force=False):
    """When PROGRESS_COMMENT is set (CI), mirror the log into a commit comment every ~15 s so the
    tail survives even if the runner is killed."""
    if not os.environ.get('PROGRESS_COMMENT'):
        return
    now = time.time()
    if not force and now - _progress['last'] < 15:
        return
    _progress['last'] = now
    repo = os.environ.get('GITHUB_REPOSITORY'); sha = os.environ.get('GITHUB_SHA'); tok = os.environ.get('GH_TOKEN') or os.environ.get('GITHUB_TOKEN')
    if not (repo and sha and tok):
        return
    body = 'Conversion progress (run %s) at %s UTC\n\n```\n%s\n```' % (os.environ.get('GITHUB_RUN_ID', '?'), time.strftime('%H:%M:%S', time.gmtime()), '\n'.join(_progress['lines'][-80:])[-50000:])
    try:
        h = {'Authorization': 'Bearer ' + tok, 'Accept': 'application/vnd.github+json'}
        if _progress['id'] is None:
            r = requests.post('https://api.github.com/repos/%s/commits/%s/comments' % (repo, sha), json={'body': body}, headers=h, timeout=20)
            if r.ok:
                _progress['id'] = r.json().get('id')
        else:
            requests.patch('https://api.github.com/repos/%s/comments/%s' % (repo, _progress['id']), json={'body': body}, headers=h, timeout=20)
    except Exception:
        pass


def log(*a):
    line = ' '.join(str(x) for x in a)
    print(line, file=sys.stderr, flush=True)
    _progress['lines'].append(line)
    _post_progress()


# --------------------------------------------------------------------------
class HttpFile(io.RawIOBase):
    """A seekable, read-only file over HTTP using Range requests, with a small chunk cache."""

    def __init__(self, url, session=None, chunk=4 * 1024 * 1024):
        self.url = url
        self.s = session or requests.Session()
        self.chunk = chunk
        self.pos = 0
        self.cache = {}
        r = self.s.head(url, allow_redirects=True, timeout=60)
        r.raise_for_status()
        self.url = r.url
        self.size = int(r.headers.get('Content-Length', 0))
        self.ranges = r.headers.get('Accept-Ranges', '').lower() == 'bytes'
        if not self.size:
            raise IOError('no Content-Length from server')
        if not self.ranges:
            # some servers only reveal range support on a GET
            t = self.s.get(self.url, headers={'Range': 'bytes=0-0'}, stream=True, timeout=60)
            self.ranges = t.status_code == 206
            t.close()
        if not self.ranges:
            raise IOError('server does not support HTTP range requests')
        self.bytes_fetched = 0

    def readable(self): return True
    def seekable(self): return True
    def tell(self): return self.pos

    def seek(self, off, whence=io.SEEK_SET):
        if whence == io.SEEK_SET: self.pos = off
        elif whence == io.SEEK_CUR: self.pos += off
        else: self.pos = self.size + off
        return self.pos

    def _get_chunk(self, idx):
        if idx in self.cache:
            return self.cache[idx]
        a = idx * self.chunk
        b = min(self.size, a + self.chunk) - 1
        for attempt in range(5):
            try:
                r = self.s.get(self.url, headers={'Range': 'bytes=%d-%d' % (a, b)}, timeout=120)
                if r.status_code != 206:
                    raise IOError('expected 206, got %d' % r.status_code)
                data = r.content
                break
            except Exception as e:
                if attempt == 4:
                    raise
                time.sleep(2 * (attempt + 1))
        self.bytes_fetched += len(data)
        if (self.bytes_fetched // (50 << 20)) != ((self.bytes_fetched - len(data)) // (50 << 20)):
            log('  %s fetched %.0f MB so far' % (time.strftime('%H:%M:%S'), self.bytes_fetched / 1e6))
        if len(self.cache) > 16:
            self.cache.pop(next(iter(self.cache)))
        self.cache[idx] = data
        return data

    def read(self, n=-1):
        if n < 0 or self.pos + n > self.size:
            n = self.size - self.pos
        out = bytearray()
        while n > 0:
            idx = self.pos // self.chunk
            data = self._get_chunk(idx)
            off = self.pos - idx * self.chunk
            take = min(n, len(data) - off)
            out += data[off:off + take]
            self.pos += take
            n -= take
        return bytes(out)

    def readinto(self, b):
        data = self.read(len(b))
        b[:len(data)] = data
        return len(data)


# --------------------------------------------------------------------------
def zenodo_files():
    r = requests.get(API, timeout=60)
    r.raise_for_status()
    files = r.json().get('files', [])
    out = {}
    for f in files:
        key = f.get('key') or f.get('filename')
        link = (f.get('links') or {}).get('self') or ('https://zenodo.org/records/%s/files/%s?download=1' % (RECORD, key))
        out[key] = {'key': key, 'size': f.get('size'), 'url': link}
    return out


def pick(files, specimen):
    for key, f in files.items():
        if specimen.lower() in key.lower():
            return f
    raise SystemExit('no file for specimen %r in %s' % (specimen, list(files)))


def classify(name):
    low = name.lower()
    parts = low.split('/')
    if any(SKIP_DIR.search(p) for p in parts[:-1]) and not re.search(r'\.(nrrd|nhdr)$', low):
        return None
    if re.search(r'\.(tiff?|png|jpe?g)$', low):
        return None                      # raw micro-slicing images: never needed
    if re.search(r'\.(dcm|dicom|ima)$', low) and NRRD_PRESENT.get('yes'):
        return None                      # raw DICOM is redundant when a final NRRD exists
    if VOLUME_EXT.search(low):
        return 'volume'
    if MESH_EXT.search(low):
        return 'mesh'
    if META_EXT.search(low) and len(parts) <= 3:
        return 'meta'
    return None


NRRD_PRESENT = {}


def summarize(zf):
    tops = {}
    for zi in zf.infolist():
        parts = zi.filename.split('/')
        top = '/'.join(parts[:2]) if len(parts) > 2 else parts[0]
        d = tops.setdefault(top, [0, 0, set()])
        d[0] += 1; d[1] += zi.file_size
        ext = os.path.splitext(zi.filename)[1].lower()
        if ext: d[2].add(ext)
    log('archive contents (folder: files, size, extensions):')
    for k, (n, sz, exts) in sorted(tops.items(), key=lambda kv: -kv[1][1]):
        log('  %-60s %6d files %8.1f MB  %s' % (k, n, sz / 1e6, ' '.join(sorted(exts))[:60]))
    big = sorted((zi for zi in zf.infolist() if not zi.is_dir()), key=lambda zi: -zi.file_size)[:15]
    log('largest members:')
    for zi in big:
        log('  %8.0f MB  %s' % (zi.file_size / 1e6, zi.filename))
    log('would extract:')
    for zi in choose_members(zf):
        log('  %8.0f MB  %s' % (zi.file_size / 1e6, zi.filename))


def choose_members(zf, prefer='embedded'):
    """Pick the archive members the atlas needs.

    OpenEar layout (verified on DELTA.zip):
      05_Registred_Slicer_Volumes/CBCT_EMBEDDED_<Name>.nrrd    125 um HiRes CBCT, registered  (~125 MB)
      05_Registred_Slicer_Volumes/CBCT_UNEMBEDDED_<Name>.nrrd  250 um CBCT of the unembedded bone (~320 MB)
      06_Segmentation/Segmentation.seg.nrrd                    label map (~35 MB)
      07_3D_Models/NN_<Structure>.ply                          surfaces (+ Bone.nrrd / 12_Bone.ply, large)
    Everything else (raw DICOM, micro-slicing TIFF and NRRD) is skipped.
    """
    members = [zi for zi in zf.infolist() if not zi.is_dir()]
    NRRD_PRESENT['yes'] = any(re.search(r'\.(nrrd|nhdr)$', zi.filename, re.I) for zi in members)
    def find(pattern):
        return [zi for zi in members if re.search(pattern, zi.filename, re.I)]
    emb = find(r'registr.*cbct_embedded.*\.nrrd$') or find(r'cbct_embedded.*\.nrrd$')
    unemb = find(r'registr.*cbct_unembedded.*\.nrrd$') or find(r'cbct_unembedded.*\.nrrd$')
    seg = (find(r'06_segmentation/segmentation\.seg\.nrrd$') or find(r'06_segmentation/.*\.seg\.nrrd$') or find(r'06_segmentation/.*\.nrrd$')
           or [zi for zi in find(r'segmentation.*\.seg\.nrrd$') if not re.search(r'(accuracy|outline)', zi.filename, re.I)])
    seg.sort(key=lambda zi: -zi.file_size)
    ply = [zi for zi in find(r'3d_models/.*\.(ply|stl|obj)$') if not re.search(r'(^|/)(12_)?bone\.(ply|stl|obj)$', zi.filename, re.I)]
    if not ply:
        ply = [zi for zi in find(r'\.(ply|stl|obj)$') if zi.file_size < 40e6]
    meta = find(r'(accuracy|readme|license|volumetric).*\.txt$')
    vols = []
    if prefer == 'unembedded' and unemb:
        vols = [unemb[0]]
    elif emb:
        vols = [emb[0]]
    elif unemb:
        vols = [unemb[0]]
    if not vols:
        # generic fallback: largest NRRD that is not a label map / micro-slicing volume
        cands = [zi for zi in find(r'\.(nrrd|nhdr|nii|nii\.gz|mha)$') if not re.search(r'(seg|label|mask|micro|slic|histo|bone\.nrrd)', zi.filename, re.I)]
        cands.sort(key=lambda zi: -zi.file_size)
        vols = cands[:1]
        if not vols:
            dicom = find(r'\.(dcm|dicom|ima)$')
            if dicom:
                # a whole series: take the folder with the most files
                folders = {}
                for zi in dicom:
                    folders.setdefault(os.path.dirname(zi.filename), []).append(zi)
                vols = max(folders.values(), key=len)
    log('CBCT volume: %s' % (', '.join('%s (%.0f MB)' % (zi.filename, zi.file_size / 1e6) for zi in vols[:1]) or 'NONE FOUND'))
    log('segmentation: %s' % (', '.join('%s (%.0f MB)' % (zi.filename, zi.file_size / 1e6) for zi in seg[:1]) or 'none'))
    log('surfaces: %d files' % len(ply))
    return vols + seg[:1] + ply + meta


def extract_needed(zf, dest, budget_bytes=9 * 1024 ** 3, prefer='embedded'):
    chosen = choose_members(zf, prefer)
    total = sum(zi.file_size for zi in chosen)
    log('extracting %d files (%.1f MB uncompressed)' % (len(chosen), total / 1e6))
    if total > budget_bytes:
        log('WARNING: selection exceeds the disk budget (%.1f GB); dropping meshes/metadata beyond the volume and segmentation' % (budget_bytes / 1e9))
    done = 0
    for zi in chosen:
        target = os.path.join(dest, zi.filename)
        os.makedirs(os.path.dirname(target), exist_ok=True)
        with zf.open(zi) as src, open(target, 'wb') as dst:
            while True:
                b = src.read(1 << 20)
                if not b:
                    break
                dst.write(b)
        done += zi.file_size
        log('  %s extracted %s (%.0f MB)' % (time.strftime('%H:%M:%S'), zi.filename, zi.file_size / 1e6))
        _post_progress(force=True)
    return chosen


def is_label_volume(path):
    """A segmentation NRRD: integer type with few distinct values, or a Slicer .seg.nrrd, or named like one."""
    base = os.path.basename(path).lower()
    if base.endswith('.seg.nrrd') or re.search(r'(segment|label|mask)', base):
        return True
    try:
        import SimpleITK as sitk
        r = sitk.ImageFileReader(); r.SetFileName(path); r.ReadImageInformation()
        pid = r.GetPixelIDTypeAsString()
        if 'float' in pid:
            return False
        # integer volume: decide from a sub-sampled read of a central slab (never the whole volume)
        import numpy as np
        size = r.GetSize()
        r.SetExtractIndex([0, 0, int(size[2] // 2)])
        r.SetExtractSize([int(size[0]), int(size[1]), 1])
        a = sitk.GetArrayViewFromImage(r.Execute())
        sample = a[:, ::4, ::4]
        return len(np.unique(sample)) <= 64
    except Exception:
        return False


def find_inputs(dest):
    """Locate the CT volume, the segmentation label volume (if any) and the folder with the surfaces."""
    vol_dirs, vol_files, mesh_dirs = {}, [], {}
    for root, _, files in os.walk(dest):
        for f in files:
            p = os.path.join(root, f)
            if re.search(r'\.(dcm|dicom|ima)$', f, re.I):
                vol_dirs[root] = vol_dirs.get(root, 0) + 1
            elif re.search(r'\.(nrrd|nhdr|nii|nii\.gz|mha|mhd)$', f, re.I):
                vol_files.append(p)
            elif MESH_EXT.search(f):
                mesh_dirs[root] = mesh_dirs.get(root, 0) + 1
    labels = [p for p in vol_files if re.search(r'(segmentation|\.seg\.nrrd$)', os.path.basename(p), re.I) and not re.search(r'(accuracy|outline)', p, re.I)]
    labels.sort(key=lambda p: (0 if re.search(r'06_segmentation', p, re.I) else 1, -os.path.getsize(p)))
    cts = [p for p in vol_files if p not in labels and re.search(r'cbct', os.path.basename(p), re.I)]
    if not cts:
        labels = [p for p in vol_files if is_label_volume(p)]
        cts = [p for p in vol_files if p not in labels and not re.search(r'(micro|slic|histo|color|colour|rgb|bone\.nrrd$)', p, re.I)]
    volume = None
    if cts:
        # prefer the high-resolution CBCT: name hints first, then finest spacing, then size
        def key(p):
            name = os.path.basename(p).lower()
            hint = 0 if re.search(r'(cbct_embedded|hires|hi-res|high)', name) else (1 if re.search(r'cbct', name) else 2)
            try:
                import SimpleITK as sitk
                r = sitk.ImageFileReader(); r.SetFileName(p); r.ReadImageInformation(); sp = min(r.GetSpacing())
            except Exception:
                sp = 9
            return (hint, sp, -os.path.getsize(p))
        cts.sort(key=key)
        volume = cts[0]
    elif vol_dirs:
        volume = max(vol_dirs.items(), key=lambda kv: kv[1])[0]
    meshes = None
    if mesh_dirs:
        # prefer PLY folders (OpenEar's native format) then the folder with the most files
        meshes = max(mesh_dirs.items(), key=lambda kv: (any(f.lower().endswith('.ply') for f in os.listdir(kv[0])), kv[1]))[0]
    label_vol = labels[0] if labels else None
    if len(labels) > 1:
        labels.sort(key=lambda p: -os.path.getsize(p)); label_vol = labels[0]
    return volume, meshes, label_vol


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--specimen', default='delta', help='alpha..theta, or all')
    ap.add_argument('--out', default='data', help='output folder for packs and datasets.json')
    ap.add_argument('--work', default='work', help='scratch folder for extracted files')
    ap.add_argument('--spacing', type=float, default=0.15, help='pack voxel size in mm (OpenEar CBCT is 0.125 mm)')
    ap.add_argument('--list', action='store_true', help='only print the archive structure')
    ap.add_argument('--full', action='store_true', help='download the whole archive instead of using range requests')
    ap.add_argument('--side', default='auto', help='R, L, or auto (from metadata if present)')
    ap.add_argument('--no-labels', action='store_true')
    ap.add_argument('--volume-choice', default='embedded', choices=['embedded', 'unembedded'], help='embedded = 125 um HiRes scan of the epoxy-embedded bone (default); unembedded = 250 um scan with a wider field')
    ap.add_argument('--url', help='use this archive URL (or local .zip path) instead of the Zenodo API')
    a = ap.parse_args()

    specs = SPECIMENS if a.specimen == 'all' else [a.specimen]
    files = None
    for spec in specs:
        log('=== %s ===' % spec)
        if a.url:
            src = a.url
        else:
            files = files or zenodo_files()
            f = pick(files, spec)
            src = f['url']
            log('archive %s (%.1f GB)' % (f['key'], (f['size'] or 0) / 1e9))
        dest = os.path.join(a.work, spec)
        os.makedirs(dest, exist_ok=True)
        if os.path.exists(src):
            zf = zipfile.ZipFile(src)
        elif a.full:
            local = os.path.join(a.work, spec + '.zip')
            if not os.path.exists(local):
                log('downloading whole archive to', local)
                with requests.get(src, stream=True, timeout=120) as r:
                    r.raise_for_status()
                    with open(local, 'wb') as fh:
                        for chunk in r.iter_content(1 << 22):
                            fh.write(chunk)
            zf = zipfile.ZipFile(local)
        else:
            try:
                hf = HttpFile(src)
                zf = zipfile.ZipFile(hf)
                log('remote zip opened with range requests (%.1f GB total, central directory read with %.1f MB)' % (hf.size / 1e9, hf.bytes_fetched / 1e6))
            except Exception as e:
                log('range requests failed (%s); use --full to download the archive' % e)
                raise SystemExit(2)
        summarize(zf)
        if a.list:
            continue
        extract_needed(zf, dest, prefer=a.volume_choice)
        _post_progress(force=True)
        volume, meshes, label_vol = find_inputs(dest)
        log('volume input: %s' % volume)
        log('label volume: %s' % label_vol)
        log('mesh folder : %s' % meshes)
        if not volume:
            raise SystemExit('no CBCT/volume found; run with --list and extend VOLUME_EXT / classify()')
        side = a.side
        if side == 'auto':
            side = 'L' if re.search(r'\b(left|links|sin)\b', ' '.join(os.listdir(dest)), re.I) else 'R'
        out_pack = os.path.join(a.out, 'openear_%s.tba' % spec)
        os.makedirs(a.out, exist_ok=True)
        cmd = [sys.executable, os.path.join(HERE, 'convert_openear.py'), '--volume', volume, '--spacing', str(a.spacing),
               '--intensity', 'auto', '--mesh-frame', 'auto', '--name', 'OpenEar %s' % spec.capitalize(), '--side', side,
               '--notes', 'OpenEar specimen %s (Sieber et al., Sci Data 2019, CC BY 4.0): cadaveric temporal bone, CBCT plus micro-slicing segmentation.' % spec.capitalize(),
               '--out', out_pack]
        if meshes:
            cmd += ['--meshes', meshes]
        if label_vol:
            cmd += ['--label-volume', label_vol]
        elif meshes and not a.no_labels:
            cmd.append('--labels')
        if not meshes and not label_vol:
            cmd += ['--crop', 'none']
        log('running:', ' '.join(cmd))
        _post_progress(force=True)
        proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, bufsize=1)
        for line in proc.stdout:
            log('  | ' + line.rstrip())
        proc.wait()
        _post_progress(force=True)
        if proc.returncode != 0:
            raise SystemExit('converter exited with %d' % proc.returncode)
        register(a.out, {'id': 'openear_%s' % spec, 'name': 'OpenEar %s' % spec.capitalize(), 'file': 'openear_%s.tba' % spec,
                         'side': side, 'kind': 'openear', 'bytes': os.path.getsize(out_pack),
                         'license': 'CC BY 4.0', 'source': 'Sieber D et al. The OpenEar library of 3D models of the human temporal bone. Sci Data 2019. Zenodo record 1473724.'})
    log('done')


def register(out_dir, entry):
    path = os.path.join(out_dir, 'datasets.json')
    lib = {'datasets': []}
    if os.path.exists(path):
        with open(path) as f:
            lib = json.load(f)
    lib['datasets'] = [d for d in lib['datasets'] if d['id'] != entry['id']] + [entry]
    lib['datasets'].sort(key=lambda d: d['id'])
    with open(path, 'w') as f:
        json.dump(lib, f, indent=1)
    log('registered %s in %s' % (entry['id'], path))


if __name__ == '__main__':
    main()
