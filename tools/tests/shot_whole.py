import sys
from playwright.sync_api import sync_playwright
url, out = sys.argv[1], sys.argv[2]
with sync_playwright() as p:
    b = p.chromium.launch(args=['--use-gl=angle', '--use-angle=swiftshader', '--enable-unsafe-swiftshader'])
    ctx = b.new_context(viewport={'width': 1440, 'height': 900})
    page = ctx.new_page()
    # a settings copy saved by the previous build, with sectioning on, must not keep it on
    page.add_init_script("try { localStorage.setItem('tba.settings.v1', JSON.stringify({settings: {section3d: true}})); } catch (e) {}")
    page.goto(url + '?data=openear_delta')
    page.wait_for_selector('.loading', state='hidden', timeout=240000)
    page.wait_for_timeout(800)
    box = page.query_selector('canvas.gl').bounding_box()
    page.mouse.move(box['x'] + box['width'] / 2, box['y'] + box['height'] / 2)
    for _ in range(40): page.mouse.wheel(0, -100)
    page.wait_for_timeout(600)
    print('sectionModel:', page.evaluate("() => window.__tba.store.state.settings.sectionModel"), '| z after scrolling:', page.evaluate("() => window.__tba.store.get('crosshair')[2].toFixed(1)"),
          '| meshes clipped:', page.evaluate("() => [...window.__tba.scene.meshes.values()].filter(m => (m.material.clippingPlanes||[]).length).length"))
    page.screenshot(path=out, clip={'x': 546, 'y': 478, 'width': 540, 'height': 420})
    b.close()
