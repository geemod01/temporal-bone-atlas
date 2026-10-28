# 2026-10-27 — Claude Code on the owner's Windows machine (first local cycle)

**Goal:** run STATE step 1 on the owner's Windows 11 + VS Code + Claude Code setup (clone → `/resume` → small change →
`/handoff` → new session → `/resume`) and make the workflow work there. **Reached:** yes up to this `/handoff`; the
closing `/resume` is the next session's first act.

## What changed
- `build.py` `run_esbuild()`: starts `shutil.which('npx') or 'npx'` instead of the bare `'npx'`. On Windows npx is
  `npx.cmd`, which `subprocess` (CreateProcess) cannot start by its bare name: the build died with
  `FileNotFoundError: [WinError 2]`. Unchanged on Linux; with npx missing it fails as before. `import shutil` moved
  to the top of the file.
- `build.py` `main()`: `data/datasets.json` is read with `encoding='utf-8'` (Windows defaults to cp1252). The file is
  ASCII today, so the output is unchanged; the write side was already ASCII (`json.dump` escapes).
- `.claude/settings.json` is committed (shared): the SessionStart/PreCompact hooks, the allowlist and the force-push
  deny, identical to the old template except its `_comment`. `docs/claude-code/settings.example.json` is deleted;
  `.gitignore` gains `.claude/settings.local.json`.
- `CLAUDE.md`: a Windows line under "Build, test, deploy" (`python` for `python3`, `python -m pip`, Git Bash) and a
  rule that permission rules are the owner's to add.
- `docs/claude-code/SETUP.md`: step 3 now says the settings come with the clone (trust prompt once; personal
  additions in `.claude/settings.local.json`). Its "Windows notes" section came from a concurrent commit (7329cc4,
  pulled during this handoff) and is the one Windows place: this session added the Git Bash bullet, pointed step 1 at
  it, and replaced "tell Claude Code this once per machine" (CLAUDE.md now carries the rule).
- `docs/HANDOFF.md` §4: pitfalls 12 (Windows) and 13 (the allowlist); §8 points to SETUP.md.

## Decisions and why
- **Commit `.claude/settings.json` instead of a copy-me template.** The copy showed as untracked, so every `/resume`
  reported a dirty tree, and `/handoff`'s "commit everything" would have committed it anyway, leaving two copies to
  drift. It is Claude Code's conventional shared file; the hooks still need the one-time folder-trust prompt.
- **Docs keep `python3`** (Linux/macOS, the runner) plus one Windows rule in CLAUDE.md, rather than rewriting every
  command: no single name works everywhere (`python` is absent on stock macOS/Ubuntu, `python3` is a stub on
  Windows), and CLAUDE.md is loaded every session.
- **`shutil.which`, not `shell=True`**: no shell parsing of the arguments. The esbuild arguments contain no cmd.exe
  metacharacters, and the `npx.cmd` shim passes `%*` through.

## Pitfalls met
- `python3` here is `AppData/Local/Microsoft/WindowsApps/python3` and prints "Python was not found …"; `python` is
  3.12.10 from python.org.
- Auto mode refused Claude adding `Bash(python …)` rules to `.claude/settings.json` ("Self-Modification"); the owner
  decides (lines under Open / next). The `_comment` edit went through and was reworded to claim nothing about them.
- With `core.autocrlf=true` and no `.gitattributes`, edited files end up CRLF in the working tree; git normalizes on
  staging, so `git diff` shows only real changes, but a plain `diff` against an LF file shows every line changed
  (use `diff --strip-trailing-cr`).
- One Edit lost a trailing space (`site =os.path…`); caught in the diff and fixed. Read the diff before committing.
- `tools/tests/shot_boot.py` needs both `openear_delta.tba` and `openear_zeta.tba` in `data/` (it fails and retries
  Zeta); without local packs the page fetches release URLs, which fail on CORS.
- `git pull --rebase --autostash` during the handoff brought in 7329cc4 (SETUP.md "Windows notes", including the
  PowerShell execution-policy fix for `npm`), written in parallel; the autostash applied cleanly, and the
  duplicate Windows lines were merged by hand.
- Dates: the previous STATE was stamped 2026-10-28 (UTC); this session is dated by local time, 2026-10-27, and is
  still the newer one.

## Verified how
- Start: `gh run list --limit 3` → three green "Build and deploy the site" runs (latest 40618876601, for a708c57);
  tree clean apart from the untracked settings copy; `main` level with `origin/main`.
- `python tools/tests/test_nrrd_stream.py` → `FAILS: 0`; `python tools/tests/test_rotated_labels.py` → `FAILS 0`.
- `python build.py --site --no-pack`: before the fix `FileNotFoundError: [WinError 2]` in `run_esbuild`; after it
  `site assembled in …\site: 2 pack(s) served locally, 8 entries in the library` (Delta and Zeta fetched with
  `gh release download data --pattern openear_delta.tba --pattern openear_zeta.tba --dir data`).
- `python -m http.server 8772 --bind 127.0.0.1 --directory site` and `python tools/tests/shot_boot.py
  http://127.0.0.1:8772/index.html <scratch>/boot` → `default dataset: OpenEar Delta`, `menu has phantom item: False
  | library items: 8`, the Zeta failure toast, the "Real imaging could not be loaded" screen, `after retry: OpenEar
  Zeta`, `errors: []`. `boot_menu.png` by eye: three panes in anatomical planes, the 3D labyrinth and facial nerve,
  the library with sizes 33–52 MB.
- `/verify` right before the commit (`python` for `python3`, the scratchpad for `/tmp`, `npm ci` skipped as
  `node_modules` exists): tests `FAILS: 0` / `FAILS 0`; `python tools/make_phantom.py` (first run on this machine,
  ~5 min, `pack written: dist/phantom.tba`), then `python tools/selftest_labels.py phantom <scratch>/selftest.tba` →
  `estimated anatomical frame: rotated by 9.5 deg, side R`, `worst per-structure Dice … 0.9988 (scc_lateral)`,
  `selftest_labels OK` (`middle_fossa` missing from the pack: 47 labels, as in HANDOFF §4.9); site build as above;
  `shot_boot.py` as above with `errors: []`, `boot_empty.png` by eye (the retry screen lists every specimen, Delta
  "on this device"); `gh run list --limit 5` → the last site deploy and the last "Build OpenEar packs"
  (39192449432) green.

## Open / next
- Next session: `/clear`, then `/resume`. Expect a clean tree and a green "Build and deploy the site" run for this
  handoff commit (`build.py` changed, so it deploys; that also exercises `shutil.which('npx')` on the Linux runner).
  That closes STATE step 1.
- Owner's decision: `python` twins of the `python3` allow rules, so routine commands stop prompting on Windows. Add
  them after `"Bash(python3 -m http.server*)",` in `.claude/settings.json`:
  `"Bash(python build.py*)", "Bash(python tools/tests/*)", "Bash(python tools/selftest_labels.py*)",`
  `"Bash(python tools/make_phantom.py*)", "Bash(python tools/convert_openear.py*)", "Bash(python -m http.server*)",`
- Small app fix: `src/main.js:320` (the boot-failure screen's hint) says "a pack is 27-43 MB"; the packs are
  33–52 MB (`data/datasets.json`). Drop the number or take the range from the library sizes.
- Local only (gitignored): `data/openear_delta.tba`, `data/openear_zeta.tba`, `phantom/`, `dist/phantom.tba`.
- Then STATE step 2, the sigmoid sinus.
