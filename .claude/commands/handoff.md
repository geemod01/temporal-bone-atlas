---
description: End-of-session handoff — write the session note, refresh docs/STATE.md, commit and push, so the next session starts fresh
---
We are ending this session. Produce the handoff that lets a brand-new session (fresh context, no memory of this one) continue without re-deriving anything. Do all of the following, in order:

1. Run `git status --short` and `git diff --stat` to see what changed in this session. Run the quick tests if code under `tools/` or `src/` changed: `python3 tools/tests/test_nrrd_stream.py && python3 tools/tests/test_rotated_labels.py` (and `python3 build.py --site --no-pack` if `src/` changed).

2. Write a session note at `docs/sessions/YYYY-MM-DD-<short-topic>.md` (today's date; copy the structure of `docs/sessions/TEMPLATE.md`). It must contain, concretely and without filler:
   - **Goal** of the session (one line) and whether it was reached.
   - **What changed**: files and behaviour, as a reader of the diff would need it explained.
   - **Decisions and why** — anything a future session might be tempted to undo.
   - **Pitfalls met** — errors, dead ends, things that looked like bugs but were not.
   - **Verified how** — the exact commands and what they printed, screenshots taken, what was checked by eye.
   - **Open / next** — the precise next steps, including anything half-done, with file paths and function names.

3. Rewrite `docs/STATE.md` so it reflects the state NOW (it is the first thing the next session sees): current status in a few lines, the ordered next steps (the top one being what to do first), anything blocked and why, and the one-line verify commands. Keep it under ~60 lines; it is a dashboard, not a diary.

4. If any build, test or deploy command changed, or a new rule-with-a-reason was learned, update `CLAUDE.md` (short) and the relevant section of `docs/HANDOFF.md` (reasons). Do not duplicate the session note there.

5. Commit everything with a descriptive message and push to `origin main` (`git pull --rebase --autostash origin main` first). If the push fails, say so and leave the commit in place.

6. Finish with a 5-line summary for the user: what was done, what is next, and the exact phrase to open the next session with (normally just `/resume`).

Do not start new work in this session after the handoff. If something is mid-change and cannot be finished, leave it in a state that builds, describe it under "Open / next", and say so.
