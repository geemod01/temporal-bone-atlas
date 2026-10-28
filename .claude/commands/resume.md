---
description: Start-of-session resume — load the current state and the last session note, verify the tree builds, then continue with the top next step
---
This is a fresh session on the Temporal Bone Atlas. Get up to speed without reading more than needed:

1. Read `docs/STATE.md` (current state and ordered next steps) and the most recent file in `docs/sessions/` (what the last session did, how it verified it, what it left open). Read `docs/HANDOFF.md` only for the sections that the next step touches (it is long; its table of contents is in the headings). `CLAUDE.md` is already loaded.

2. Check the ground truth matches the notes: `git status --short`, `git log --oneline -5`, and `gh run list --limit 3` (were the last deploy/pack builds green?). If the working tree is dirty or a run failed, report it before anything else.

3. Run the quick checks appropriate to the top next step (tests in `tools/tests/`, `python3 build.py --site --no-pack`, or nothing if the step is content-only).

4. Tell the user in a few lines: where the project stands, what the top next step is, and any discrepancy found. Then, if the user's message after `/resume` names a task, do that; otherwise start the top next step from `docs/STATE.md`.

Session discipline for this project: keep one session to one goal; before the context gets heavy (the `/context` command shows it; stop around 60% at the latest), run `/handoff` and start a new session rather than letting Claude Code compact. Never push patient data; never force-push.

$ARGUMENTS
