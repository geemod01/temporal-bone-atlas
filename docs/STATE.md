# State — read this first (kept current by `/handoff`)

Updated: 2026-10-27 · Last session note: `docs/sessions/2026-10-27-claude-code-windows.md`

## Where things stand
- Live: https://geemod01.github.io/temporal-bone-atlas/ — all eight OpenEar specimens, anatomical planes, wide-field
  context, 68 cards, 8 tours, 5 quiz sets. Deploys from `main` (push) and after each pack build.
- The owner works on Windows 11 + VS Code + Claude Code (clone with `--filter=blob:none`, all deps, `gh` logged in).
  `python3` is the Store alias there: use `python` (CLAUDE.md). The site builds there since the `build.py` npx fix.
- `.claude/settings.json` (hooks + allowlist) is committed; the hook that prints this file works on Windows.
- Last green runs: site deploy for a708c57; "Build OpenEar packs" `all` with the context layer. The 2026-10-27
  handoff commit changed `build.py`, so it deploys: check that run first.
- Nothing is half-done in the code.
- Attending feedback received (see `docs/HANDOFF.md` §6): sigmoid not highlighted in 3D; wants patient scans and
  anomaly detection next. Owner has asked for NO work on that yet beyond planning.

## Next steps, in order
1. Close the workflow check: this `/resume` is the last leg (clone → `/resume` → change → `/handoff` → new session →
   `/resume`). Expect a clean tree and a green deploy of the 2026-10-27 handoff commit. Same session, if wanted: the
   stale hint at `src/main.js:320` ("a pack is 27-43 MB"; the packs are 33–52 MB).
2. Sigmoid sinus as its own structure (attending's note): try the bone-enclosure extraction from the `sinus_dura`
   segment on Delta (the pack's CT + label volume are enough to prototype; `tools/tbapack.read_pack`), validate by eye
   in the viewer, fall back to a Slicer tracing for specimens where it fails. Jugular bulb the same way if feasible.
3. Attending review pass over cards/tours/quiz (the `reviewed` field per card; the flag is not displayed).
4. Study instrumentation: session ids + a results sink for quiz exports (`src/quiz.js` `results()`).
5. Patient-scan track — governance first (IRB/QI, de-identification, private host); plan in HANDOFF §6. Do not start
   without the owner's go-ahead.

## Blocked / caveats
- The git history still carries ~300 MB of old build artifacts; clone with `--filter=blob:none` or rewrite history
  with `git filter-repo --path dist --invert-paths` (owner's call; needs a force-push, which the shared settings deny).

## Verify in one line each (Windows: `python` for `python3`)
- `python3 tools/tests/test_nrrd_stream.py && python3 tools/tests/test_rotated_labels.py` → `FAILS: 0`
- `python3 build.py --site --no-pack` → "site assembled"
- `gh run list --limit 3` → green
