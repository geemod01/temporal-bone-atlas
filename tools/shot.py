#!/usr/bin/env python3
"""Screenshot / smoke-test the built HTML with Playwright (Chromium, software WebGL)."""
import sys
import time
from playwright.sync_api import sync_playwright

html = sys.argv[1] if len(sys.argv) > 1 else 'dist/TemporalBoneAtlas.html'
out = sys.argv[2] if len(sys.argv) > 2 else '/tmp/shot.png'
actions = sys.argv[3] if len(sys.argv) > 3 else ''
width = int(sys.argv[4]) if len(sys.argv) > 4 else 1440
height = int(sys.argv[5]) if len(sys.argv) > 5 else 900

with sync_playwright() as p:
    b = p.chromium.launch(args=['--use-gl=angle', '--use-angle=swiftshader', '--enable-unsafe-swiftshader', '--ignore-gpu-blocklist'])
    page = b.new_page(viewport={'width': width, 'height': height}, device_scale_factor=1)
    errors = []
    page.on('console', lambda m: errors.append(f'[{m.type}] {m.text}') if m.type in ('error', 'warning') else None)
    page.on('pageerror', lambda e: errors.append('[pageerror] ' + str(e)))
    import os
    page.goto('file://' + os.path.abspath(html))
    try:
        page.wait_for_selector('.loading', state='hidden', timeout=30000)
    except Exception as e:
        errors.append('loading never finished: ' + str(e))
    page.wait_for_timeout(600)
    if actions:
        page.evaluate(actions)
        page.wait_for_timeout(700)
    page.screenshot(path=out)
    info = page.evaluate("() => { const t = window.__tba; if (!t) return 'no __tba'; const ds = t.store.get('dataset'); return JSON.stringify({dataset: ds && ds.name, meshes: ds && ds.meshes.length, crosshair: t.store.get('crosshair'), selected: t.store.get('selectedId'), depth: t.store.get('depth')}); }")
    print('state:', info)
    print('console errors/warnings:', len(errors))
    for e in errors[:30]:
        print('  ', e[:400])
    b.close()
