import sys
from playwright.sync_api import sync_playwright
url, out = sys.argv[1], sys.argv[2]
with sync_playwright() as p:
    b = p.chromium.launch(args=['--use-gl=angle', '--use-angle=swiftshader', '--enable-unsafe-swiftshader'])
    page = b.new_page(viewport={'width': 1440, 'height': 900})
    errs = []; page.on('pageerror', lambda e: errs.append(str(e)))
    page.goto(url)                                   # no ?data: must open the library default
    page.wait_for_selector('.loading', state='hidden', timeout=240000)
    page.wait_for_timeout(800)
    print('default dataset:', page.evaluate("() => window.__tba.store.get('dataset').name"), '| chip:', page.evaluate("() => document.querySelector('.dataset-chip').textContent"))
    page.click('.dataset-chip'); page.wait_for_timeout(300)
    print('menu has phantom item:', page.evaluate("() => !!document.querySelector('[data-ds=\"phantom\"]')"), '| library items:', page.evaluate("() => document.querySelectorAll('[data-lib]').length"))
    page.screenshot(path=out + '_menu.png')
    page.keyboard.press('Escape')
    # a failed download while a dataset is open: toast only
    page.evaluate("() => { const lib = window.__tbaLibrary.get(); const e = lib.find(x => x.id === 'openear_zeta'); e.url = 'http://127.0.0.1:9/nope.tba'; delete e.mirror; e.cached = false; }")
    page.evaluate("() => window.__tbaLibrary.loadLibraryEntry(window.__tbaLibrary.get().find(x => x.id === 'openear_zeta'))")
    page.wait_for_timeout(1500)
    print('toast after failed switch:', page.evaluate("() => document.querySelector('.toast').textContent"))
    # fresh boot with the remembered entry failing: the retry screen, then a successful retry
    page.evaluate("() => { try { localStorage.setItem('tba.lastDataset', 'openear_zeta'); } catch (e) {} }")
    page.route('**/openear_zeta.tba', lambda route: route.abort())
    page.goto(url)
    page.wait_for_selector('.empty-state', state='visible', timeout=120000)
    page.wait_for_timeout(500)
    page.screenshot(path=out + '_empty.png')
    print('empty state text:', page.evaluate("() => document.querySelector('.empty-state').innerText.slice(0, 220).replace(/\\n/g, ' | ')"))
    page.unroute('**/openear_zeta.tba')
    page.click('.empty-state [data-retry="openear_zeta"]')
    page.wait_for_selector('.loading', state='hidden', timeout=240000)
    print('after retry:', page.evaluate("() => window.__tba.store.get('dataset').name"))
    print('errors:', errs)
    b.close()
