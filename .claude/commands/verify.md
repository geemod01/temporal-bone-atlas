---
description: Run the project's offline checks (converter tests, site build, headless browser smoke test) and report
---
Verify the project in its current state and report pass/fail per step with the key line of output for each. Do not fix anything unless asked; just report.

1. `python3 tools/tests/test_nrrd_stream.py` and `python3 tools/tests/test_rotated_labels.py` (streaming reader and label samplers vs SimpleITK; both print `FAILS: 0` / `FAILS 0`).
2. `python3 tools/selftest_labels.py phantom /tmp/selftest.tba` — needs the phantom (`python3 tools/make_phantom.py`, ~5 min, once); expects the anatomical-frame estimate < 20°, right ear, Dice > 0.97.
3. `npm ci` (once) then `python3 build.py --site --no-pack` — the hosted page into `site/`; note the line "site assembled ... N pack(s)". Packs in `data/*.tba` are optional locally; download one with `gh release download data --pattern openear_delta.tba --dir data` if a browser check needs real imaging.
4. Headless browser (needs `pip install playwright && playwright install chromium`): serve `site/` with `python3 -m http.server 8772` in the background, then `python3 tools/tests/shot_boot.py http://127.0.0.1:8772/index.html /tmp/boot` — prints the default dataset, that the menu has no phantom item, the toast on a failed download and the retry outcome; look at `/tmp/boot_empty.png` with the Read tool.
5. `gh run list --limit 5` — the last "Build and deploy the site" and "Build OpenEar packs" runs should be green.

End with a one-paragraph verdict and anything that looks off.

$ARGUMENTS
