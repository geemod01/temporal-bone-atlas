# 2026-10-28 — multi-machine workflow and the Windows permission rules

**Goal:** add the `python` permission rules the owner approved, and make the workflow safe across two machines
(Windows PC, Mac) sharing the GitHub repo. **Reached:** yes.

Continues `2026-10-27-claude-code-windows.md` (same conversation, after its handoff).

## What changed
- `.claude/settings.json`: six `python …` allow rules, twins of the `python3 …` ones, added at the owner's explicit
  request; the `_comment` says so (commit 8269088).
- `.claude/commands/resume.md`: new step 1 `git pull --ff-only origin main`; if it fails, stop and report (no merge or
  discard without the owner). The STATE the startup hook printed predates the pull, so the files are read fresh.
  The old steps are renumbered 2–5.
- `docs/claude-code/SETUP.md`: section "Working from more than one machine" (the repo is the memory; `/handoff` at
  the end, one machine at a time; what stays local; Homebrew Python needs a venv).
- `CLAUDE.md`: the session protocol says `/resume` pulls; the permission rule now allows writing rules on the owner's
  explicit go-ahead. `docs/HANDOFF.md` §4: item 13 updated, item 14 (two machines) new.
- `docs/STATE.md`: the resolved "Waiting on the owner" item removed.

## Decisions and why
- **`--ff-only` in `/resume`, not `--rebase`:** at session start the clone should be clean and level; anything else
  (commits from a session that skipped `/handoff`, edits in the way) is a surprise the owner should see, not
  something to merge automatically. `/handoff` keeps `pull --rebase --autostash` because it has a commit to land.
- **The pull is in `/resume`, not in the SessionStart hook:** a hook that changes the tree on every startup and
  `/clear` would act before the owner sees anything; the hook stays read-only.
- **One machine at a time:** two sessions rewriting STATE.md conflict at the second `/handoff` (7329cc4 nearly did).

## Pitfalls met
- Auto mode refused Claude adding allow rules on its own (27 Oct) and accepted the same edit after the owner's
  explicit go-ahead in the chat.
- On a machine that is behind, the startup hook shows the stale local STATE.md before `/resume` pulls; harmless, as
  `/resume` rereads after the pull.

## Verified how
- `.claude/settings.json` parses: 25 allow rules, 6 of them `python …`.
- `git pull --rebase --autostash origin main` → "Already up to date"; push `f4d4db1..8269088`.
- Deploy of f4d4db1 (run 40625917824) green in 54 s, so `build.py`'s `shutil.which('npx')` works on the Linux
  runner. Deploy of 8269088 (run 40726081625) was in progress at this handoff.
- Not yet seen: the pull step running (it first runs in the next `/resume`), and the `python` rules suppressing
  prompts (this session ran in auto mode; a normal-mode session shows it).

## Open / next
- Next session: `/clear`, then `/resume` — the first run of the pull step; expect "Already up to date", a clean
  tree, and a green deploy for 8269088 (this handoff commit is Markdown-only, so it does not deploy).
- Owner, when convenient: one-time Mac setup per `docs/claude-code/SETUP.md`, then `/resume` there to confirm the
  cross-machine leg.
- Then: the stale hint at `src/main.js:320` ("a pack is 27-43 MB"; the packs are 33–52 MB), and STATE's sigmoid step.
