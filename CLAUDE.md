# Temporal Bone Atlas — working notes for Claude Code

## Session protocol (fresh context every session, no compaction)
- Start: `/resume` — pulls `origin main` (the owner works from a Windows PC and a Mac), reads `docs/STATE.md` (current state + ordered next steps) and the latest `docs/sessions/*.md`,
  checks git and CI, runs the quick tests, continues with the top step or the task given after `/resume`.
- End, or when `/context` passes ~60 %: `/handoff` — writes the session note, rewrites `docs/STATE.md`, commits, pushes.
  Then the next session starts clean. If compaction is ever about to happen, `/handoff` first.
- `docs/HANDOFF.md` holds the complete history, decisions and reasons, pitfalls, and the roadmap: read the sections
  the current step touches, not the whole file. `docs/claude-code/SETUP.md` is the owner's VS Code guide.
- One session, one goal. Mid-change work is never left unexplained: it goes under "Open / next" in the session note.

## What this is
A browser-based temporal bone CT atlas for ENT training: three synced orthogonal CT panes + a 3D scene driven by
one cursor, a structure card for everything the cursor touches, curriculum-mapped tours, a quiz that doubles as a
study instrument. Live at https://geemod01.github.io/temporal-bone-atlas/ with all eight OpenEar specimens
(real 125 µm CBCT + published segmentation, CC BY 4.0) resliced into true anatomical planes.

Owner: an ENT resident (the user). A neurotology attending has reviewed it once (see HANDOFF, "Attending feedback").

## Layout
- `src/` — the app (vanilla JS + three.js, bundled by esbuild). `main.js` boot/menus/library, `view2d.js` slice panes,
  `view3d.js` scene, `state.js` store + settings, `panel.js` cards, `tours.js`, `quiz.js`, `settings.js` (settings/help/about),
  `content.js` (loads `content/*.json`, structure metadata helpers), `volume.js` (Volume, CompositeVolume, OffsetLabels),
  `pack.js` (.tba parser), `nifti.js`, `stl.js`, `app.css`.
- `content/` — the knowledge graph: 68 structure cards (`structures_*.json`), 8 tours, 5 quiz sets. Plain JSON, hand-edited.
- `tools/` — `convert_openear.py` (any CT + segmentation/surfaces → `.tba` pack; the heart of the data pipeline),
  `fetch_openear.py` (Zenodo range-request fetch + convert + register), `publish_openear_anywhere.py` (Colab/laptop route and
  the `--register-only` step the workflow uses), `tbapack.py` (pack format), `make_phantom.py` (synthetic test anatomy),
  `selftest_labels.py`, `tests/` (offline tests and Playwright checks; see `tools/tests/README.md`), `openear_map.json` (names → ids).
- `build.py` — esbuild + inlining → `dist/TemporalBoneAtlas.html` (single file, embeds the phantom) and, with
  `--site --no-pack`, `site/` (the hosted page, no phantom, packs served next to it).
- `.github/workflows/` — `pages.yml` (deploy: pulls packs from the `data` release into `site/data`), `openear.yml`
  (build packs on the runner; inputs: specimen, spacing, probe_only, full_download), `selftest.yml` (converter self-test, no Zenodo).
- `data/datasets.json` — the library (ids, names, sides, sizes, release URLs, `default`). The packs themselves are release
  assets (`data` tag), never committed.

## Build, test, deploy
```
npm ci && python3 build.py                 # single-file build (needs dist/phantom.tba: python3 tools/make_phantom.py, ~5 min)
python3 build.py --site --no-pack          # the hosted page into site/ (fast; copies data/*.tba if present)
python3 tools/tests/test_nrrd_stream.py && python3 tools/tests/test_rotated_labels.py
python3 tools/selftest_labels.py phantom /tmp/selftest.tba
cd site && python3 -m http.server 8772     # then: python3 tools/tests/shot_boot.py http://127.0.0.1:8772/index.html out
```
Push to `main` deploys the site (README-only pushes are ignored). Packs are rebuilt with Actions → "Build OpenEar packs"
(`specimen=all` ≈ 30 min; registration goes through the contents API, so pushing during a run is safe).
Python deps for the tools: `numpy SimpleITK trimesh fast-simplification requests` (+ `scipy scikit-image nibabel` for the phantom).
Windows (the owner's machine): `python3` there is the Microsoft Store alias, so run every `python3` above as `python` and
pip as `python -m pip`; the Bash tool and the hooks in `.claude/settings.json` run in Git Bash.

## Rules that exist for a reason (details in HANDOFF)
- Never put PHI or patient imaging in this repo, in the release or on the Pages site. Institutional scans need
  de-identification and a private host; the pack format supports that path.
- Never serve packs from GitHub release URLs to the browser: the redirect has no CORS header. The site serves them itself.
- The converter must stay streaming (NrrdStream): OpenEar's segmentations are up to 18 GB uncompressed.
- Packs are in the anatomical frame (estimated from structures) with the cochlea at the origin; keep that contract.
- Don't commit build artifacts (`dist/*.html`, `*.tba`) — the history once carried 300 MB of them.
- Content claims come from standard references and the papers cited on each card; keep `sources` per card.
- Permission rules in `.claude/settings.json` are the owner's: propose additions; write them only on the owner's
  explicit go-ahead (auto mode refuses otherwise).
- One machine at a time (Windows PC, Mac): two sessions rewriting STATE.md conflict at the second `/handoff`.
