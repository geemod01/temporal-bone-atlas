# Temporal Bone Atlas — handoff

Written 19 Oct 2026 at the end of the first build session (a claude.ai session that compacted twice). Everything
below is what a new session needs to continue without re-deriving anything. The repository is the source of
truth for code; this document is the source of truth for *why*.

Live site: https://geemod01.github.io/temporal-bone-atlas/ · Repo: https://github.com/geemod01/temporal-bone-atlas

---

## 1. The brief (the owner's words, condensed)

The owner is an ENT resident. The spark was a cardiology fellow who used an LLM to build a 3D model synced with an
angiogram. Requirements as stated over the conversation:

- Three synced orthogonal CT views plus a synced 3D model, "like a surgical nav system": one cursor, scroll through
  slices, see where you are on the model.
- Content "extremely COMPREHENSIVE in terms of anatomy", pitched at attending and fellow level as well as junior,
  with variants and pitfalls, mapped to the officially recognised curriculum — but the UI "not bloated", a few settings.
- Guided tours; a quiz usable as a study instrument (the owner plans a small study on objective teaching metrics).
- Ear first; the frontal sinus later, as a content pack or a sibling app.
- "The best and most accurate imaging/modeling available" — real imaging, not synthetic: the OpenEar library
  (Sieber et al., Sci Data 2019, CC BY 4.0, Zenodo record 1473724). The owner's involvement in the data pipeline
  must be "the bare minimum".
- Website rather than an .exe (decided; nothing precludes Electron/PWA later).
- Rejected: the synthetic phantom as a product ("useless"); any UI hint that the product is unfinished
  ("not yet reviewed by an attending" flags were removed).
- Wanted and delivered late in the session: the whole bone visible rather than a tight crop; scrolling anywhere
  moves everyone; the 3D model stays whole while scrolling (a sectioning mode exists but is off by default).

## 2. Current state (what is live)

- The site opens on OpenEar Delta (or the last specimen used) with no download step for the owner; eight specimens
  in the dataset menu (Alpha R, Beta R, Gamma L, Delta R, Epsilon L, Zeta R, Eta L, Theta R), 32–52 MB each, downloaded
  once and kept in Cache Storage. No synthetic data on the site; a retry screen if a download fails.
- Each pack: the ear at 0.15 mm (core, ~52×49×55 mm around the cochlea) inside the whole scanned block at 0.3 mm
  (context), lossless delta-encoded int16; a uint8 label volume (11–13 structures); decimated surfaces (12k faces,
  90k for the bone block); landmarks; provenance (orientation estimate with residuals, registration note, original
  segment names). All in the anatomical RAS frame with the cochlea at the origin.
- Structures available in OpenEar: cochlea (scala tympani + vestibuli merged), malleus, incus, stapes, facial nerve
  (whole course), chorda tympani, cochleovestibular nerve (IAC), tympanic membrane, EAC, petrous carotid, "sinus +
  dura" (one 24 cm³ piece: sigmoid sinus and the dura of both fossae — a context surface, hidden by default), bone
  block (context surface), round window (Alpha only). NOT segmented in OpenEar: vestibule, semicircular canals,
  IAC as bone, jugular bulb, mastoid cells, tegmen, middle/posterior fossa plates — those cards exist and fall back
  to related surfaces for *Locate*, and the CT shows them.
- Content: 68 cards (facial 10, inner 13, middle 21, vascular/landmarks 24), levels 1–3 (junior/senior/fellow dial
  gates sections), 8 tours (65 steps), 5 quiz sets (50 questions: identify/name/level/mcq). Cards have `sources`,
  `curriculum`, `variants`, `pitfalls`, `measurements`, `pathology`, `fellow` notes; `reviewed` is null everywhere
  (the flag is no longer displayed). The quiz filters questions to structures the loaded dataset can resolve and
  records per-question results (type, target, correct, ms) with an export at the end.
- App features: window/level presets and shift-drag, zoom/pan per pane, maximize (1–4), slice labels and 3D labels
  (off/selected/auto/all), depth dial, mirror a left ear, click-to-select from labels, Locate / Zoom-in / Shown-in-3D
  per card, Layers menu (groups, bone+dura context, CT planes, plane opacity, optional sectioning), author mode
  (set a structure's location to the cursor; landmarks.json alongside a pack), drag-and-drop of .tba/.nii, help (?).

## 3. Architecture

### App (`src/`, vanilla JS + three.js 0.186, esbuild)
- `state.js`: the store. Settings persist in `localStorage['tba.settings.v1']` (merge over defaults — rename a key
  when a default must change for existing users, as was done for `sectionModel`). State: dataset, crosshair (RAS mm),
  selectedId, hoverId, depth, hidden (3D), tour, quiz, activePane, scrollPlane (the plane the wheel moves),
  sectionArmed.
- `view2d.js`: each pane extracts its slice from `ds.volume` into a canvas at the volume's grid resolution and draws it
  scaled; labels come from `ds.labels` on the same grid; outlines/masks for selected/hovered; wheel = slice, ctrl-wheel
  = zoom; sets `scrollPlane`. The 3D scene reuses the pane canvases as textures (`CanvasTexture`), refreshed on the
  pane's `slice` event.
- `view3d.js`: meshes with per-structure colours (`content.js`), context surfaces translucent and hidden unless
  `boneShell`, CT planes positioned at the crosshair, camera presets, picking (click puts the cursor on a surface or a
  plane), optional sectioning (clipping plane at the scrolled plane + flat back-face "caps"), wheel over the scene
  steps `scrollPlane` (ctrl-wheel zooms).
- `volume.js`: `Volume` (C-order [z][y][x], RAS), `CompositeVolume` (presents core + context as one grid at the core's
  spacing: core copied over its rectangle, context sampled bilinearly; nothing materialised), `OffsetLabels` (labels
  on the core grid presented on the union grid).
- `pack.js`: `.tba` parser; builds `dataset` with `meshById`, `labelValueOf/labelIdOf`, `anchorOf(id)` (landmark →
  mesh centroid), `boundsOf(id)` (mesh bbox or label bounds), `labelAt(p)`.
- `content.js`: loads JSON, `STRUCTURE_BY_ID`, groups, `DEFAULT_HIDDEN`, `CONTEXT_IDS` (bone_shell, sinus_dura, dura),
  `resolveAnchor/resolveBounds` with per-card `fallback` chains (e.g. fn segments → facial_nerve, canals → labyrinth →
  cochlea), depth gating.
- `main.js`: markup, menus, keyboard, library (`data/datasets.json` next to the page; entries `{id, name, file, side,
  kind, bytes, license, source, mirror?}` + top-level `default`), Cache Storage `tba-packs-v1`, boot order
  (`?data=<id|url>` → library default/last → embedded pack → empty state), file open/drop, retry screen.

### Pack format (`tools/tbapack.py`)
gzip of: `TBA1` + uint32 header length + JSON header + 4-byte-aligned blobs. Header: `volume` {blob, dims, spacing,
origin, dtype int16, units HU, encoding "delta-x"}, optional `context` (same, coarser), optional `labels` {uint8,
same grid as volume}, `labelIds` {value: id}, `labelSources` {id: [original segment names]}, `meshes` [{id, nv, nf,
centroid, bbox, v, f}], `landmarks` {id: [x,y,z]}, `side`, `kind`, `notes`, `orientation` {R rows, centre, rotation_deg,
report}, `registration`. "delta-x" = differences along x stored as int16 with 16-bit wrap (lossless; decoder in
`pack.js` and `tbapack.delta_decode_int16`).

### Converter (`tools/convert_openear.py`) — the pipeline per specimen
1. Read the volume header lazily (`LazyVolume`: ITK header + `NrrdStream` for data). NRRD data is streamed slice by
   slice (gzip/raw, 3-D or Slicer 4-D) so the whole file is never in memory.
2. Load surfaces (trimesh; large files without processing), decide their frame (RAS/LPS) by the fraction of vertices
   inside the volume, tie-broken by edge strength at the vertices; refuse if < 85 % inside (misregistered inputs).
3. `--transforms DIR` (raw scans): try every composition/inversion/order of the shipped ITK `.h5` transforms and keep
   the one that lands the surfaces on bone edges (used for Beta: `CBCT_BrainsFit then CBCT_InitialGuess`).
4. `estimate_anatomical_frame`: superior from the facial nerve's mastoid segment (vertical, inferior end farthest
   from the cochlea), malleus and incus long axes (heavy end up), horizontal cues EAC axis, IAC axis, cochlea→TM;
   lateral from cochlea→TM, IAC axis, EAC axis; side from carotid (anterior) vs sinus/dura (posterior). Eigen-solve,
   then rotate everything; cochlea at the origin. Residuals are logged and stored. Validation: the anatomically built
   phantom comes out 9° from identity, right ear; on real data the malleus lands anterior to the incus, the stapes
   between cochlea and TM, the carotid anteromedial-inferior — none of which the estimator uses.
5. Crop = core structures' bbox + 14 mm (`CORE` set; context surfaces excluded); resample the CT with ITK (linear)
   through the rotation (+ pre-transform) at `--spacing` (0.15); the whole scan again at `--context-spacing` (0.3),
   trimmed to content (> −900).
6. Labels: `sample_label_layers` streams the segmentation and samples every layer onto the pack grid — separable fast
   path when grids are aligned, otherwise output voxels bucketed by source slice (≈20 B/voxel of index arrays);
   names from Slicer header fields (post-4.11 `LabelValue/Layer`, or pre-4.11 one-layer-per-segment), mapped through
   `openear_map.json` + card ids; names that match nothing (or nerves that match a non-nerve) are matched by surface
   overlap; a segment bigger than every surface that matches none is treated as bone. Bone is dropped (it would catch
   every click); where segments overlap the smaller structure wins.
7. Landmarks = vertex nearest the centroid per mesh (context surfaces excluded); pack written.
Memory: ~1.1–1.3 GB peak at 0.15 mm regardless of input size; ~2 min per specimen on a GitHub runner.

### Fetch (`tools/fetch_openear.py`)
Opens the Zenodo zip with HTTP range requests (central directory only), picks the registered embedded CBCT (three
spellings across specimens), the segmentation (`06_Segmentation/Segmentation.seg.nrrd`, never the Accuracy-Analysis
outline), every PLY (bone block included), the transforms when only DICOM exists, small text notes; streams adjacent
members in one request per run (a 482-slice DICOM series = 1 request; Zenodo rate-limits bursts with 429); converts;
registers in `data/datasets.json` with the side read from the pack header; continues past failed specimens and writes
`failed.json` (the workflow then removes stale assets and entries). `--list` / workflow `probe_only` prints every
non-slice member and small text files.

### CI (`.github/workflows/`)
- `openear.yml` (dispatch): probe → fetch+convert → log posted as a commit comment (readable without the Actions UI,
  which this session could not reach) → upload packs to release `data` → register via the contents API
  (`publish_openear_anywhere.py --register-only`, merge-safe) → deploy site. 16 GB runners cope since streaming.
- `pages.yml` (push to main except `*.md`, dispatch, workflow_call): `gh release download data` into `data/`,
  `build.py --site --no-pack`, upload (≈ 290 MB artifact), deploy. Pages Source must be "GitHub Actions" (set).
- `selftest.yml` (dispatch): phantom → converter with `--labels` and with a gzip NRRD through the lazy reader →
  `selftest_labels.py` (two-layer seg, orientation < 20°, Dice > 0.97 vs ITK).

## 4. Decisions and the pitfalls behind them (do not re-learn these)

1. **Runner/Colab deaths were OOM.** Every early GitHub run died with "runner has received a shutdown signal"; a
   Colab run died with SIGKILL at "reading label volume". Cause: the segmentation is 1202×1208×952 voxels in 13
   layers (18 GB raw) and was being read whole. Fix: `NrrdStream`. Keep everything streaming.
2. **OpenEar volumes are in the scanner frame**, not anatomical (Delta's lateral direction was ~45° off every axis).
   The panes were oblique sections until the orientation estimate was added. Specimens rotate 100–179°.
3. **Archive layouts differ per specimen** (file names, bone file size 7–209 MB, segment names with typos such as
   "Vestibucochlear Nerve", "Outer ear Canal", "Tympanic Drum", "Scala_Tympany", "Bone 1300", "Sinus-Dura").
   `openear_map.json` covers all eight; unknown names go to overlap matching. A substring matcher once folded the
   nerve into the cochlea — hence the nerve rule.
4. **Beta has no registered CBCT** (raw DICOM + transform chain); applying the chain blind is wrong, so the converter
   searches compositions and scores them by edge strength (934 vs 133 untransformed). Lumen-vs-shell CT contrast
   inside its labels matches the author-registered specimens.
5. **"Sinus_Dura" cannot be split** into sigmoid sinus and dura morphologically (thick throughout; opening at r = 5 mm
   keeps 57 %). It is a context surface; the sigmoid card has no own location in OpenEar packs (the attending noticed).
6. **GitHub release downloads cannot be fetched from a page**: the 302 from github.com carries no CORS header. The
   site serves the packs itself (same origin). Release assets remain the storage and the mirror.
7. **The contents API is the only safe way to register packs from a run**; `git pull --rebase` on the runner's dirty
   tree failed when commits arrived mid-run. Writes to the contents API were blocked from the authoring session's
   proxy but work on the runner.
8. **Commit comments carry the logs** because the authoring session could not read Actions logs or artifacts (blob
   storage was blocked). Claude Code on a normal machine can simply use `gh run view --log`.
9. **The phantom** (`tools/make_phantom.py`, 48 mm core in a 96 mm field, 47 labelled structures) remains the ground
   truth for tests and the only data in the single-file build; it is not on the site.
10. **History bloat**: `dist/*.html` (29–35 MB) was committed 12 times (~300 MB of objects). As of this handoff the
    build artifacts are untracked; if the clone is still heavy, rewrite history with `git filter-repo --path dist
    --invert-paths` (no collaborators yet).
11. Settings persist per browser; a changed default needs a new key (done for `sectionModel`).

## 5. Verification habits that worked
- Headless Chromium (Playwright, `--use-gl=angle --use-angle=swiftshader`) against a locally served `site/` with
  `window.__tba` (store, panes, scene, panel) and `window.__tbaLibrary` exposed for assertions; screenshots judged
  by eye for anatomy (planes through the cochlea: IAC medial, EAC lateral, mastoid posterior).
- Pack QA without the sources: read the header (`tbapack.read_header`) for side/orientation residuals/label
  provenance; CT contrast between a label's lumen and the 0.45–0.9 mm shell outside it (cochlea ~1000 in / ~2900
  shell on every specimen) catches misregistration.
- Converter correctness: streamed reads vs SimpleITK (exact), rotated sampling vs ITK affine (exact), phantom
  round-trip Dice ≥ 0.99, transform-chain recovery with a decoy.

## 6. Attending feedback (neurotology, 19 Oct 2026)
"This is very cool, the sigmoid is not highlighted in the 3D version but that's ok. The next move is to incorporate
patient scans into this, and for the algo to detect the anomalies. Do you think this is possible to teach it?"

Assessment and a staged plan (nothing started; the owner asked for no action yet):

- **Patient scans into the viewer — straightforward, with governance first.** The converter already takes DICOM
  (ITK series reader), applies HU as stored, and builds a pack with `--crop none` and no labels (tri-planar reading
  works; cards resolve only what has a landmark or a label). Required before any scan enters: IRB/ethics approval or
  a QI/education exemption as the institution defines it, de-identification (pixel data rarely carries PHI, headers
  always do; burned-in text must be checked), and a private host — never this public repo, release or Pages site.
  A self-hosted copy of `site/` behind institutional login (or the single-file build on a workstation) is enough.
- **Anatomy on patient scans needs segmentation.** Nothing in the current packs transfers automatically. Options in
  order of effort: (a) manual Slicer segmentation of the ~12 OpenEar structures per case (hours each; an attending-
  verified case set is also the study material), (b) a learned segmenter: nnU-Net-style 3D U-Net trained on OpenEar's
  eight (125 µm, cadaveric, epoxy-embedded — a domain gap to clinical 0.4–0.6 mm scans) plus every manually labelled
  clinical case; published temporal-bone segmentation models exist for the labyrinth, ossicles and facial nerve and
  could be fine-tuned. Expect to need on the order of 30–60 labelled clinical scans for robust inference on new
  patients. Because packs carry the anatomical frame, measurements become comparable across cases.
- **"Detecting anomalies" splits into two very different problems.**
  1. *Measurable variants and findings* — computable from a segmentation plus the anatomical frame with rules a
     neurotologist can read and audit: anterior sigmoid (distance sinus → posterior EAC wall), high-riding or dehiscent
     jugular bulb (height relative to the basal turn / round window niche), low tegmen (tegmen height above the EAC
     roof), facial canal dehiscence (bone thickness over the tympanic segment), SSCD (bone over the superior canal
     apex), enlarged vestibular aqueduct (midpoint width > 1 mm), cochlear malformations by turn count and modiolar
     presence (IP-I/II/III, common cavity), aberrant/dehiscent carotid, Körner's septum, mastoid pneumatisation
     class. This is feasible with the current stack once the structures involved are segmented (several are not in
     OpenEar: canals, jugular bulb, tegmen), and it produces exactly the content the variants tour teaches.
  2. *Learned detection of pathology* (cholesteatoma, otosclerosis, fractures, erosion) — supervised models need
     hundreds of labelled positive cases per finding; one institution's archive over a few years can reach that for
     common findings only. Unsupervised "anomaly" detection on temporal bone CT is research-grade and not something
     to promise. Treat as a later research line with its own IRB, held-out validation and attending adjudication.
- **Regulatory framing.** As a teaching tool that flags findings for a trainee to confirm, with no clinical decision
  claim, this stays research/education. Anything described as detection on patient care data is a different category.
- Suggested order: governance → a de-identified case set (10–20 scans, attending-read) → manual segmentation of
  those → rule-based measurements with the cards' variant thresholds → compare rule outputs with attending reads →
  only then a segmentation model to scale.

## 7. Roadmap (owner's and mine)
- Attending review of card content, tours and quiz distractors; the `reviewed` field exists per card.
- Frontal sinus / sinonasal pack (content + a dataset; the viewer is organ-agnostic, the content schema is not).
- Study instrumentation: quiz export already produces per-question results; add session ids and a results sink.
- Sigmoid sinus and the unsegmented structures: segment them on one or two specimens in Slicer (the converter maps
  Slicer exports by name) — this also answers the attending's note.
- Smaller: W/L presets tuned for CBCT, mobile layout polish, a measurement tool (distances/angles in a pane),
  landmark packs for the unsegmented cards.

## 8. Starting in Claude Code
```
git clone https://github.com/geemod01/temporal-bone-atlas && cd temporal-bone-atlas
npm ci
pip install numpy SimpleITK trimesh fast-simplification requests scipy scikit-image nibabel playwright && playwright install chromium
python3 tools/tests/test_nrrd_stream.py && python3 tools/tests/test_rotated_labels.py
python3 tools/make_phantom.py && python3 tools/selftest_labels.py phantom /tmp/selftest.tba
python3 build.py --site --no-pack && (cd site && python3 -m http.server 8772)
```
`gh auth login` for Actions dispatch (`gh workflow run openear.yml -f specimen=delta`) and logs (`gh run view --log`).
The Zenodo archives are 4–14 GB; never download them whole — `fetch_openear.py` reads ~250 MB per specimen by ranges.
