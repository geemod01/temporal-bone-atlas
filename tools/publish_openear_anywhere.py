#!/usr/bin/env python3
"""
One-command OpenEar pack build + publish from ANY machine (laptop, Colab, any VM).

What it does
  1. installs the Python dependencies (unless --no-install)
  2. streams only the needed members of the Zenodo archive (CBCT, segmentation, surfaces; ~160 MB)
  3. converts them to a .tba pack at the requested voxel size
  4. uploads the pack to the GitHub release "data" of the repository and registers it in
     data/datasets.json on the main branch (so the site lists it automatically)

Usage
  python3 tools/publish_openear_anywhere.py --specimen delta --token ghp_xxx
  python3 tools/publish_openear_anywhere.py --specimen all --token ghp_xxx --spacing 0.15

The token needs "contents: write" on the repository (a classic token with the "repo" scope, or a
fine-grained token with Contents: Read and write). Create one at https://github.com/settings/tokens.

On Google Colab (free, no install on your computer):
  !git clone https://github.com/geemod01/temporal-bone-atlas && cd temporal-bone-atlas && \\
   python3 tools/publish_openear_anywhere.py --specimen delta --token YOUR_TOKEN
"""
import argparse
import base64
import json
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)


def sh(cmd, **kw):
    print('+', ' '.join(cmd), flush=True)
    return subprocess.run(cmd, check=True, **kw)


def gh_api(method, url, token, data=None, raw=None, content_type=None):
    import requests
    h = {'Authorization': 'Bearer ' + token, 'Accept': 'application/vnd.github+json', 'X-GitHub-Api-Version': '2022-11-28'}
    if content_type:
        h['Content-Type'] = content_type
    r = requests.request(method, url, headers=h, json=data, data=raw, timeout=600)
    if r.status_code >= 300:
        raise SystemExit('GitHub API %s %s -> %d %s' % (method, url, r.status_code, r.text[:300]))
    return r.json() if r.text else {}


def ensure_release(repo, token):
    import requests
    h = {'Authorization': 'Bearer ' + token, 'Accept': 'application/vnd.github+json'}
    r = requests.get('https://api.github.com/repos/%s/releases/tags/data' % repo, headers=h, timeout=60)
    if r.status_code == 200:
        return r.json()
    return gh_api('POST', 'https://api.github.com/repos/%s/releases' % repo, token, data={
        'tag_name': 'data', 'name': 'Data packs', 'target_commitish': 'main',
        'body': 'Temporal bone data packs (.tba) served to the atlas. OpenEar packs: Sieber D et al., Sci Data 2019, CC BY 4.0 (Zenodo 1473724).'})


def upload_asset(release, path, repo, token):
    import requests
    name = os.path.basename(path)
    for a in release.get('assets', []):
        if a['name'] == name:
            gh_api('DELETE', a['url'], token)
    url = release['upload_url'].split('{')[0] + '?name=' + name
    h = {'Authorization': 'Bearer ' + token, 'Accept': 'application/vnd.github+json', 'Content-Type': 'application/octet-stream'}
    with open(path, 'rb') as f:
        r = requests.post(url, headers=h, data=f, timeout=1800)
    if r.status_code >= 300:
        raise SystemExit('upload failed: %d %s' % (r.status_code, r.text[:300]))
    print('uploaded', name, '->', r.json().get('browser_download_url'))
    return r.json().get('browser_download_url')


def update_datasets_json(repo, token, entries):
    """Merge entries into data/datasets.json on main through the contents API (no git needed)."""
    import requests
    h = {'Authorization': 'Bearer ' + token, 'Accept': 'application/vnd.github+json'}
    url = 'https://api.github.com/repos/%s/contents/data/datasets.json' % repo
    r = requests.get(url, headers=h, params={'ref': 'main'}, timeout=60)
    sha = None
    lib = {'datasets': []}
    if r.status_code == 200:
        j = r.json(); sha = j['sha']
        lib = json.loads(base64.b64decode(j['content']).decode('utf-8'))
    ids = {e['id'] for e in entries}
    lib['datasets'] = [d for d in lib['datasets'] if d['id'] not in ids] + entries
    lib['datasets'].sort(key=lambda d: d['id'])
    body = {'message': 'Register pack(s): ' + ', '.join(sorted(ids)), 'content': base64.b64encode(json.dumps(lib, indent=1).encode()).decode(), 'branch': 'main'}
    if sha:
        body['sha'] = sha
    gh_api('PUT', url, token, data=body)
    print('datasets.json updated on main (the site redeploys automatically)')


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--specimen', default='delta')
    ap.add_argument('--spacing', type=float, default=0.15)
    ap.add_argument('--repo', default='geemod01/temporal-bone-atlas')
    ap.add_argument('--token', default=os.environ.get('GITHUB_TOKEN') or os.environ.get('GH_TOKEN'))
    ap.add_argument('--no-install', action='store_true')
    ap.add_argument('--no-upload', action='store_true', help='build the pack(s) only')
    ap.add_argument('--register-only', action='store_true', help='skip building/uploading: merge the entries of --out/datasets.json (files already on the release) into data/datasets.json on main')
    ap.add_argument('--work', default=os.path.join(ROOT, 'work'))
    ap.add_argument('--out', default=os.path.join(ROOT, 'data'))
    a = ap.parse_args()
    if a.register_only:
        if not a.token:
            raise SystemExit('a GitHub token is required: --token or GITHUB_TOKEN')
        lib = json.load(open(os.path.join(a.out, 'datasets.json')))
        entries = []
        for d in lib['datasets']:
            d = dict(d)
            d['file'] = 'https://github.com/%s/releases/download/data/%s' % (a.repo, os.path.basename(d['file']))
            entries.append(d)
        update_datasets_json(a.repo, a.token, entries)
        print('registered:', ', '.join(e['id'] for e in entries)); return
    if not a.no_install:
        sh([sys.executable, '-m', 'pip', 'install', '-q', 'numpy', 'SimpleITK', 'trimesh', 'fast-simplification', 'requests'])
    sh([sys.executable, os.path.join(HERE, 'fetch_openear.py'), '--specimen', a.specimen, '--spacing', str(a.spacing), '--out', a.out, '--work', a.work])
    if a.no_upload:
        print('packs built in', a.out); return
    if not a.token:
        raise SystemExit('a GitHub token is required to publish: --token or GITHUB_TOKEN')
    lib = json.load(open(os.path.join(a.out, 'datasets.json')))
    rel = ensure_release(a.repo, a.token)
    entries = []
    for d in lib['datasets']:
        local = os.path.join(a.out, os.path.basename(d['file']))
        if not os.path.exists(local):
            continue
        url = upload_asset(rel, local, a.repo, a.token)
        d = dict(d); d['file'] = url; d['bytes'] = os.path.getsize(local)
        entries.append(d)
    update_datasets_json(a.repo, a.token, entries)
    print('done:', ', '.join(e['id'] for e in entries))


if __name__ == '__main__':
    main()
