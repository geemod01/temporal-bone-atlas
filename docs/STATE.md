# State — read this first (kept current by `/handoff`)

Updated: 2026-10-28 · Last session note: `docs/sessions/2026-10-19-first-build.md`

## Where things stand
- Live: https://geemod01.github.io/temporal-bone-atlas/ — all eight OpenEar specimens, anatomical planes, wide-field
  context, 68 cards, 8 tours, 5 quiz sets. Deploys from `main` (push) and after each pack build.
- Last green runs: site deploy (commit da11df2 + handoff commits), "Build OpenEar packs" `all` with the context layer.
- Nothing is half-done in the code. The working tree should be clean after `/resume`'s check.
- Attending feedback received (see `docs/HANDOFF.md` §6): sigmoid not highlighted in 3D; wants patient scans and
  anomaly detection next. Owner has asked for NO work on that yet beyond planning.

## Next steps, in order
1. Set up the owner's local Claude Code + VS Code workflow (this file, `/resume`, `/handoff`, `docs/claude-code/SETUP.md`)
   and confirm a full cycle works: clone → `/resume` → small change → `/handoff` → new session → `/resume`.
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
- The claude.ai session that built this could not read Actions logs; Claude Code can (`gh run view <id> --log`).

## Verify in one line each
- `python3 tools/tests/test_nrrd_stream.py && python3 tools/tests/test_rotated_labels.py` → `FAILS: 0`
- `python3 build.py --site --no-pack` → "site assembled"
- `gh run list --limit 3` → green
