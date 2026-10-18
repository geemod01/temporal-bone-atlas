#!/usr/bin/env python3
"""
Builds dist/TemporalBoneAtlas.html: a single self-contained file (CSS, JS, fonts and the
built-in phantom data pack inlined). Also leaves dist/app.js and dist/app.css for development.

Usage: python3 build.py [--pack dist/phantom.tba] [--no-pack] [--dev]
"""
import argparse
import base64
import os
import subprocess
import sys

ROOT = os.path.dirname(os.path.abspath(__file__))
FONT_DIR = os.path.join(ROOT, 'node_modules', '@fontsource', 'ibm-plex-sans', 'files')
FONTS = [
    ('ibm-plex-sans-latin-400-normal.woff2', 400, 'normal'),
    ('ibm-plex-sans-latin-400-italic.woff2', 400, 'italic'),
    ('ibm-plex-sans-latin-500-normal.woff2', 500, 'normal'),
    ('ibm-plex-sans-latin-600-normal.woff2', 600, 'normal'),
]


def run_esbuild(dev=False):
    cmd = ['npx', 'esbuild', 'src/main.js', '--bundle', '--format=iife', '--target=es2020', '--loader:.json=json',
           '--outfile=dist/app.js', '--log-level=warning']
    if not dev:
        cmd.append('--minify')
    else:
        cmd.append('--sourcemap=inline')
    subprocess.run(cmd, cwd=ROOT, check=True)


def fonts_css():
    out = []
    for fname, weight, style in FONTS:
        path = os.path.join(FONT_DIR, fname)
        if not os.path.exists(path):
            continue
        b64 = base64.b64encode(open(path, 'rb').read()).decode('ascii')
        out.append("@font-face{font-family:'IBM Plex Sans';font-style:%s;font-weight:%d;font-display:swap;src:url(data:font/woff2;base64,%s) format('woff2');}" % (style, weight, b64))
    return '\n'.join(out)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--pack', default='dist/phantom.tba')
    ap.add_argument('--no-pack', action='store_true')
    ap.add_argument('--dev', action='store_true')
    ap.add_argument('--out', default='dist/TemporalBoneAtlas.html')
    ap.add_argument('--site', action='store_true', help='also assemble site/ (index.html + data/) for static hosting')
    a = ap.parse_args()
    os.makedirs(os.path.join(ROOT, 'dist'), exist_ok=True)
    run_esbuild(dev=a.dev)
    js = open(os.path.join(ROOT, 'dist', 'app.js'), encoding='utf-8').read()
    css = open(os.path.join(ROOT, 'dist', 'app.css'), encoding='utf-8').read()
    tpl = open(os.path.join(ROOT, 'index.template.html'), encoding='utf-8').read()
    pack_b64 = ''
    if not a.no_pack and os.path.exists(os.path.join(ROOT, a.pack)):
        pack_b64 = base64.b64encode(open(os.path.join(ROOT, a.pack), 'rb').read()).decode('ascii')
    # guard against the JS containing the closing script tag sequence
    js = js.replace('</script', '<\\/script')
    html = tpl.replace('/*__FONTS_CSS__*/', fonts_css()).replace('/*__APP_CSS__*/', css).replace('__PACK_B64__', pack_b64).replace('/*__APP_JS__*/', js)
    out = os.path.join(ROOT, a.out)
    with open(out, 'w', encoding='utf-8') as f:
        f.write(html)
    print('wrote %s (%.1f MB)' % (out, os.path.getsize(out) / 1e6))
    if a.site:
        import shutil
        site = os.path.join(ROOT, 'site')
        os.makedirs(os.path.join(site, 'data'), exist_ok=True)
        shutil.copyfile(out, os.path.join(site, 'index.html'))
        data = os.path.join(ROOT, 'data')
        if os.path.isdir(data):
            for f in os.listdir(data):
                if f.endswith('.tba') or f == 'datasets.json':
                    shutil.copyfile(os.path.join(data, f), os.path.join(site, 'data', f))
        if not os.path.exists(os.path.join(site, 'data', 'datasets.json')):
            with open(os.path.join(site, 'data', 'datasets.json'), 'w') as f:
                f.write('{"datasets": []}\n')
        open(os.path.join(site, '.nojekyll'), 'w').close()
        print('site assembled in %s' % site)


if __name__ == '__main__':
    main()
