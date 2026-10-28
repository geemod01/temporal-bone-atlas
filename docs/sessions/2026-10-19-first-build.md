# 2026-10-19 — first build (claude.ai session, 17–19 Oct; handoff written 19 Oct, Claude Code setup added 28 Oct)

**Goal:** one-shot the atlas with real OpenEar imaging, hosted, usable by residents. **Reached:** yes.

This note summarises a long session whose full account is `docs/HANDOFF.md`; read that for reasons and details.

## What changed
- Everything: the app (`src/`), the content (`content/`), the converter and fetch pipeline (`tools/`), the
  workflows, the hosted site with all eight OpenEar specimens.
- Late in the session: wide-field context volume, nav-style shared scrolling (sectioning optional, off),
  review-status flags removed, phantom removed from the site, packs served same-origin.

## Decisions and why
- See HANDOFF §4 (eleven numbered pitfalls/decisions). The ones most likely to be questioned: packs are in an
  estimated anatomical frame with the cochlea at the origin (OpenEar is in the scanner frame); bone is never a
  label; sinus+dura is a context surface; packs are served by the site, not from release URLs.

## Pitfalls met
- Runner/Colab OOM from reading the segmentation whole; scanner-frame orientation; per-specimen archive layouts
  and segment-name typos; Beta's unregistered scan; GitHub release downloads without CORS; `git pull --rebase` on
  the runner's dirty tree; the authoring session could not read Actions logs or artifacts (used commit comments).

## Verified how
- `tools/tests/test_nrrd_stream.py`, `test_rotated_labels.py`, `test_transform_chain.py`, `selftest_labels.py`
  (all pass); headless-browser screenshots of every specimen at the cochlea; lumen-vs-shell CT contrast per label
  across all eight packs (HANDOFF §5).

## Open / next
- See `docs/STATE.md`. First: run the Claude Code cycle once (`/resume` → change → `/handoff` → new session).
- Then the sigmoid sinus as its own structure (attending's note), then attending content review, then study
  instrumentation; patient-scan track only after governance (HANDOFF §6).
