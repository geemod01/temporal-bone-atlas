import sys
from playwright.sync_api import sync_playwright
url, out, px, py, pz = sys.argv[1], sys.argv[2], float(sys.argv[3]), float(sys.argv[4]), float(sys.argv[5])
with sync_playwright() as p:
    b = p.chromium.launch(args=['--use-gl=angle', '--use-angle=swiftshader', '--enable-unsafe-swiftshader'])
    page = b.new_page(viewport={'width': 1440, 'height': 900})
    page.goto(url + '?data=' + (sys.argv[6] if len(sys.argv) > 6 else 'openear_delta') + '')
    page.wait_for_selector('.loading', state='hidden', timeout=180000)
    page.wait_for_timeout(1000)
    page.evaluate("([x,y,z]) => { window.__tba.store.setCrosshair([x,y,z], 'test'); }", [px, py, pz])
    page.wait_for_timeout(600)
    page.screenshot(path=out)
    b.close()
