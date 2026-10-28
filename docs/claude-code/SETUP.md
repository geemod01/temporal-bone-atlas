# Working on this project in VS Code with Claude Code

The idea: every session starts with a fresh context window and gets its bearings from three small files, and
every session ends by refreshing those files. Nothing is ever left to compaction.

```
docs/STATE.md              what is true now + the ordered next steps   (dashboard, ~60 lines)
docs/sessions/<date>-*.md  one note per session: what changed, why, how verified, what is open
docs/HANDOFF.md            the long-form reasons, pitfalls and roadmap (rarely changes)
CLAUDE.md                  loaded automatically by Claude Code: layout, commands, rules
```

Two slash commands drive it (they live in `.claude/commands/` and are committed, so every clone has them):
- `/resume` — reads STATE + the last session note, checks git and the last CI runs, runs the quick tests, then continues.
- `/handoff` — writes the session note, rewrites STATE, updates CLAUDE.md/HANDOFF if a rule changed, commits, pushes.
- `/verify` — the offline checks on demand.

## One-time setup (about 10 minutes)
1. Install VS Code and the **Claude Code** extension (Extensions → search "Claude Code", publisher Anthropic); sign in.
   Also install Node 20+, Python 3.11+, git, and the GitHub CLI (`gh`). On Windows, read the notes after step 4 first.
2. Clone without the heavy history:
   ```
   git clone --filter=blob:none https://github.com/geemod01/temporal-bone-atlas
   cd temporal-bone-atlas
   npm ci
   pip install numpy SimpleITK trimesh fast-simplification requests scipy scikit-image nibabel playwright
   playwright install chromium
   gh auth login        # for Actions logs/dispatch; VS Code's GitHub sign-in covers git push
   ```
3. The project's Claude Code settings come with the clone in `.claude/settings.json`: hooks that print STATE into
   every new session and warn before compaction; permissions so routine commands don't prompt; force-push refused.
   Claude Code asks you once to trust the folder and its hooks; review the file first, it is short. Personal
   additions go in `.claude/settings.local.json`, which git ignores.
4. Open the folder in VS Code (File → Open Folder). Claude Code treats the folder as the project and reads
   `CLAUDE.md` on its own.

### Windows notes
- "running scripts is disabled on this system" when typing `npm ...`: PowerShell's execution policy. Run
  `Set-ExecutionPolicy -Scope CurrentUser RemoteSigned` once (no admin), or use `npm.cmd`, or switch the terminal
  to Command Prompt / Git Bash.
- `python3` is not a command on Windows: use `python` (or `py -3`) wherever this project's docs say `python3`, and
  `python -m pip install ...` for pip. `CLAUDE.md` says the same, so Claude Code needs no reminder after `/resume`.
- Install Python from python.org and Git for Windows: Claude Code runs its shell commands and this project's hooks
  in Git for Windows' Git Bash.
- `playwright install chromium` and `gh auth login` work as written.

## Every session
1. Open Claude Code (the panel, or `claude` in the VS Code terminal). Type `/resume`. It reports where things stand
   and starts the top item in STATE, or the task you add after `/resume` (e.g. `/resume sigmoid extraction`).
2. Keep the session to one goal. Watch `/context`; around 60 % used, or when the goal is reached, type `/handoff`.
3. Start the next session fresh: `/clear` (or close the panel and open a new session), then `/resume`.
   Never accept compaction — if Claude Code says it is compacting, `/handoff` first.
4. The site deploys itself on push to `main` (not for `*.md`-only changes). Pack rebuilds: Actions → "Build OpenEar
   packs" (or `gh workflow run openear.yml -f specimen=delta`), ~2 min per specimen, ~30 min for `all`.

## Habits that keep sessions cheap
- Ask for `/verify` only when something changed; its browser step takes a minute.
- Point Claude at files rather than letting it search: the layout in `CLAUDE.md` is accurate.
- For long investigations, ask for a plan first (Claude Code's plan mode) so the context holds decisions, not dumps.
- Logs: `gh run view <id> --log | grep -i "error\|wrote data\|FAILED"` rather than the whole log.
