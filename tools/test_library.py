#!/usr/bin/env python3
"""Load a hosted pack through the dataset library in headless Chromium and report what the app sees.

Usage: python3 tools/test_library.py http://127.0.0.1:8766/index.html openear_delta [screenshot.png]
"""
import sys
import time

from playwright.sync_api import sync_playwright

url, ds_id = sys.argv[1], sys.argv[2]
shot = sys.argv[3] if len(sys.argv) > 3 else None
with sync_playwright() as p:
    b = p.chromium.launch(args=['--use-gl=angle', '--use-angle=swiftshader', '--enable-unsafe-swiftshader'])
    page = b.new_page(viewport={'width': 1440, 'height': 900})
    errs = []
    page.on('pageerror', lambda e: errs.append(str(e)))
    page.on('console', lambda m: errs.append(m.text) if m.type == 'error' else None)
    page.goto(url + '?data=' + ds_id)
    t = time.time()
    page.wait_for_selector('.loading', state='hidden', timeout=180000)
    print('loaded in %.1fs:' % (time.time() - t), page.evaluate(
        "() => { const ds = window.__tba.store.get('dataset'); return JSON.stringify({name: ds.name, dims: ds.volume.dims, spacing: ds.volume.spacing[0], meshes: ds.meshes.map(m => m.id), labels: Object.values(ds.labelIds)}); }"))
    page.evaluate("() => { window.__tba.panel.open('facial_nerve', true); window.__tba.scene.centerOnCursor(); }")
    page.wait_for_timeout(800)
    if shot:
        page.screenshot(path=shot)
    page.evaluate("() => { window.__tba.panel.open('fn_mastoid', true); }")
    page.wait_for_timeout(500)
    print('fn_mastoid cursor:', page.evaluate("() => window.__tba.store.get('crosshair').map(x => x.toFixed(1))"),
          '| label under cursor:', page.evaluate("() => window.__tba.store.get('dataset').labelAt(window.__tba.store.get('crosshair'))"))
    print('errors:', errs)
    b.close()
