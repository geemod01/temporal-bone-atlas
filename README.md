# Temporal Bone Atlas

A single-file, browser-based temporal bone CT atlas for otolaryngology training: three synced orthogonal CT views and a 3D scene driven by one cursor, with a structure card for everything the cursor touches, guided tours that follow the curriculum, and a quiz that doubles as a study instrument.

Open `dist/TemporalBoneAtlas.html` in a current browser (Chrome, Edge, Safari 16.4+, Firefox 113+). It works offline from the file; nothing is sent anywhere.

The file ships with a **synthetic phantom**: a procedurally generated right temporal bone with the correct topology and relationships (facial nerve segments, ossicles, labyrinth, IAC, sigmoid, jugular bulb, carotid, mastoid cells), every structure labelled. It is not patient anatomy. Real imaging is loaded as a data pack made with `tools/convert_openear.py` (see below).

## What is in the box

| Path | What it is |
| --- | --- |
| `dist/TemporalBoneAtlas.html` | The app, self-contained (fonts, code and phantom data inlined). |
| `src/` | Application source: viewer (`view2d.js`, `view3d.js`), store, panel, tours, quiz, settings, loaders (`pack.js`, `nifti.js`, `stl.js`). |
| `content/` | The knowledge graph: 67 structure cards, 8 tours (65 steps), 5 quiz sets (50 questions). Plain JSON, edited by hand. |
| `tools/make_phantom.py` | Generates the synthetic phantom (volume, labels, meshes, data pack). |
| `tools/convert_openear.py` | Converts an OpenEar specimen or any CT + meshes into a `.tba` data pack. |
| `tools/openear_map.json` | File-name to structure-id map used by the converter. |
| `tools/tbapack.py` | Pack writer/reader (format below). |
| `tools/shot.py` | Headless screenshot and smoke test (Playwright). |
| `build.py` | Bundles `src/` + `content/` + fonts + phantom into the single HTML file. |

## Design principles (the brief)

Comprehensive content, few features, everything reachable from the cursor.

1. **The viewer is the whole app.** No module home screen. Reading, tours, quiz and settings are panels docked to the tri-planar + 3D view.
2. **Anatomy is the table of contents.** Each structure is a node with one card: summary, how to find it on each plane, relations, surgical significance, variants, pitfalls, measurements, classification, approach-level notes, pathology correlates, sources, review status, curriculum tags. Clicking it anywhere opens the card and moves the cursor.
3. **One depth dial.** Junior shows the essentials; Senior adds variants, pitfalls, measurements and the full surgical list; Fellow adds approach-level notes and pathology correlates. The dial also decides which labels show by default.
4. **Tours are the curriculum.** Scripted walkthroughs drive the cursor, the highlighted structures, the 3D camera and the pane of interest. Adding a tour adds content; the interface does not grow.
5. **The quiz lives in the same viewer** (point-and-identify, name-the-highlight, find-the-level, multiple choice) and exports per-question results with timing as JSON.
6. **Settings fit on one screen.** Layout, window presets, laterality mirror, label density (2D and 3D), CT planes in 3D, bone surface, click behaviour, text size, motion, author mode.
7. **Governance is visible.** Every card lists sources and a review status (all cards currently *Not yet reviewed by an attending*). Reviewing a card means setting its `reviewed` field in `content/*.json`.

## Using the app

* **Slices**: click or drag moves the cursor in all views; scroll changes slice; Ctrl+scroll or pinch zooms; Shift+drag adjusts window/level; right-drag or Alt+drag pans; double-click resets.
* **3D**: drag orbits, scroll zooms, right-drag pans; click a structure or a CT plane to put the cursor there; *Layers* toggles groups, the translucent bone surface and the CT planes.
* **Keyboard**: 1-4 maximise a pane, L/K cycle slice/3D labels, P toggles CT planes in 3D, B the bone surface, C centres 3D on the cursor, R resets the pane under the pointer, Space/arrows step tours, Esc exits, / focuses search, ? opens help.
* **Dataset menu** (the chip next to the title): built-in phantom, open a `.tba` pack or a NIfTI volume (drag-and-drop works too), about this dataset.
* **Author mode** (Settings): on a real scan without a segmentation, open a card, put the cursor on the structure and press *Set location to cursor*; export all locations as `landmarks.json` and load it alongside the volume next time (or pass it to the converter with `--landmarks`).

## Loading real imaging

The app reads one file format, the `.tba` pack: a gzip container with a header (JSON), an int16 volume in RAS millimetres, an optional uint8 label volume, mesh tables and landmark points (`tools/tbapack.py` documents the layout). Build one with the converter, or let GitHub build it for you.

### The no-download path: GitHub does the work

Nobody needs the 4-14 GB archives on their computer.

1. Create a GitHub repository and push this folder to it (`main` branch).
2. In the repository settings, Pages -> Build and deployment -> Source: **GitHub Actions** (one click).
3. Actions -> **Build OpenEar packs** -> Run workflow -> choose a specimen (start with `delta`) -> Run.

The runner reads the Zenodo archive with HTTP range requests, so only the 125 µm CBCT, the segmentation and the surfaces come down (hundreds of MB, not gigabytes), converts them to a ~30 MB pack at 0.15 mm (lossless delta-encoded CT, label volume, decimated surfaces), commits it to `data/`, and deploys the site. Open the Pages URL; the dataset menu now lists *OpenEar Delta* under "Real imaging". The first open downloads the pack once and keeps it in the browser (Cache Storage), so later visits load instantly and offline; Settings has a button to remove saved packs. Run the workflow again for the other specimens or with `all`.

If Zenodo ever refuses range requests, run the workflow with "full download" ticked; the runner then downloads the whole archive (fine for the specimens under ~10 GB).

### If GitHub's runners refuse the job: build the pack elsewhere (Colab or a laptop)

`tools/publish_openear_anywhere.py` does the whole thing from any machine that can reach Zenodo and
GitHub: fetch the needed members, convert, upload the pack to the repository's `data` release, and
register it in `data/datasets.json` (the site redeploys itself).

Google Colab (free, nothing to install): open https://colab.research.google.com, New notebook, paste

```
!git clone https://github.com/geemod01/temporal-bone-atlas
%cd temporal-bone-atlas
!python3 tools/publish_openear_anywhere.py --specimen delta --token PASTE_YOUR_TOKEN
```

and run the cell (about 10 minutes). The token is a GitHub personal access token with **Contents:
read and write** on the repository (https://github.com/settings/tokens). Repeat with `--specimen all`
for every specimen.

### OpenEar on your own machine

1. Download a specimen archive from Zenodo (record 1473724; 4-14 GB each; CC BY). Unpack it.
2. Find the CBCT (DICOM folder or a volume file) and the segmentation surfaces (STL per structure). Folder names differ by specimen; the converter prints every mesh it finds and how it mapped it.
3. Run, for example:

```
pip install SimpleITK trimesh fast-simplification numpy
python3 tools/convert_openear.py --volume Delta/CBCT --meshes Delta/Models \
    --mesh-frame LPS --intensity auto --spacing 0.3 --labels \
    --name "OpenEar Delta" --out dist/openear_delta.tba
```

   * `--mesh-frame`: STL files exported from 3D Slicer are in LPS; most research datasets are RAS. If the surfaces land mirrored or displaced relative to the CT in the app, switch this flag.
   * `--intensity auto` rescales CBCT grey values to a HU-like range when they are not HU already.
   * `--label-volume seg.nrrd` resamples a real segmentation (OpenEar ships one at 125 µm; 3D Slicer exports `.seg.nrrd`, including multi-layer ones with overlapping segments) onto the pack grid and reads structure names from its header. Prefer it over `--labels`, which voxelises meshes and needs closed surfaces. Where segments overlap the smaller structure wins, and a "Bone" segment is dropped (the CT already shows bone; as a label it would catch every click).
   * NRRD volumes (CT and segmentation) are streamed slice by slice, so the converter needs about 1.3 GB of RAM at 0.15 mm whatever the size of the input files (OpenEar's segmentation is 1202x1208x952 voxels in 13 layers, 18 GB uncompressed); NIfTI inputs are read whole.
   * `--orient auto` (default) puts the pack into the anatomical frame. Research volumes such as OpenEar's embedded blocks sit in the scanner frame, so their axes are not the patient's; the converter recovers true axial/coronal/sagittal planes from the segmented structures (the facial nerve's mastoid segment and the ossicles hang vertically, the EAC and IAC are horizontal, the cochlea-to-TM line is lateral), reads the side off the anatomy (carotid anterior, sigmoid sinus posterior) and puts the cochlea at the origin. The estimate, with each cue's residual, is logged and stored in the pack header under `orientation`. `--orient none --side R|L` keeps the volume's own axes.
   * Large wrapping surfaces (`12_Bone.ply`, OpenEar's combined "Sinus_Dura", a dura) become *context surfaces*: translucent, off by default (toggle them in the 3D Layers menu or with B), never used for camera fitting, picking or Locate. OpenEar's sigmoid sinus is not separable from its dura in that segment (the piece is 24 cm3 and thick throughout), so the *Sigmoid sinus* card has no location in OpenEar packs; the CT shows it.
   * Unmatched file names are listed at the end; add them to `tools/openear_map.json` so they map onto atlas cards. Datasets that segment the whole facial nerve or the whole labyrinth as one surface map onto the *Facial nerve (whole course)* and *Bony labyrinth* overview cards, and the per-segment cards fall back to those surfaces for *Locate*.
4. Open the pack from the dataset menu. The pack round-trips exactly: the phantom's NIfTI + STL export converted with this script reproduces the built-in pack (volume identical, labels Dice > 0.95 for closed meshes).

### An institutional CT (for the study)

De-identify (3D Slicer's DICOM module or `dicom-anonymizer`), segment the structures you will test in Slicer's Segment Editor, export the models as STL, and convert as above. Volume-only packs (`--crop none`, no meshes) work for tri-planar reading; add locations in author mode.

### Hosting

`python3 build.py --site` assembles `site/` (index.html + `data/`) for any static host. The app reads `data/datasets.json` next to the page and lists each pack in the dataset menu; `?data=<id>` (a library id) or `?data=<url>` opens one directly. Packs stay separate from the page, so adding data never means rebuilding the app.

## Content model

`content/structures_*.json` hold the cards. Fields and the depth at which they show:

| Field | Depth | Notes |
| --- | --- | --- |
| `summary`, `find` (axial/coronal/sagittal), `relations`, `surgical` (first two), `sources` | Junior | |
| `surgical` (all), `variants` (name, note, prevalence), `pitfalls`, `measurements`, `classification` | Senior | |
| `fellow` (approach-level notes), `pathology` | Fellow | |
| `level` | | Lowest dial level at which the structure is listed and auto-labelled. |
| `mesh`, `anchor`, `fallback` | | Where *Locate* puts the cursor on datasets with or without that surface. |
| `reviewed`, `curriculum`, `aliases`, `color` | | Governance, mapping to curriculum headings, search terms, palette. |

`content/tours.json`: steps with `focus` (structure id or RAS point), `highlight` (ids kept opaque while the rest fade), `plane` (the pane that flashes and stays opaque in 3D), `view` (3D camera preset), and `level`.

`content/quiz.json`: sets of `identify`, `name`, `level` and `mcq` questions. Identify checks use the label under the cursor when a label volume exists, otherwise the distance to the structure's location (2.5-3.5 mm tolerance). Level checks use the structure's extent on that axis.

Content was drafted from the references cited on each card (Gulya and Schuknecht; Swartz and Loevner; Harnsberger; Sanna; Brackmann, Shelton and Arriaga; and the primary papers for prevalence figures). It is a draft for attending review, not a reviewed resource; the review status on every card says so.

## Developing

```
npm install                 # three, esbuild, IBM Plex Sans
pip install numpy scipy scikit-image nibabel fast-simplification   # phantom
python3 tools/make_phantom.py        # writes phantom/ and dist/phantom.tba
python3 build.py                     # writes dist/TemporalBoneAtlas.html (minified)
python3 build.py --dev               # readable bundle with source maps
python3 tools/shot.py dist/TemporalBoneAtlas.html /tmp/shot.png   # headless smoke test (pip install playwright; playwright install chromium)
```

The app is plain ES modules bundled by esbuild; the only runtime dependency is three.js. The 2D views are canvas 2D (window/level, outlines, labels); the 3D view is three.js with CanvasTextures of the same slice canvases placed at the cursor.

## Roadmap (what the next passes should add)

* **Attending review workflow**: a reviewed-by field with date on each card, surfaced on the card; a changelog.
* **Oblique reformats** (Poschl and Stenvers through the superior canal) in the slice panes.
* **Multi-case variants**: the other OpenEar specimens as additional packs, with the "Dangerous variants" tour pointing at real examples (high jugular bulb, anterior sigmoid, pneumatisation differences).
* **Study mode**: pre/post test sets with fixed question order, a participant id in the export, and delayed-retention sets.
* **Second region**: the shell is region-agnostic (volume + meshes + labels + landmarks + cards + tours). A frontal recess module is a content pack and a converter run, not a second app.

## Licences and attribution

Code: MIT. IBM Plex Sans: SIL Open Font License. three.js: MIT. OpenEar data: Sieber D et al., *The OpenEar library of 3D models of the human temporal bone based on computed tomography and micro-slicing*, Sci Data 2019 (CC BY 4.0); attribute when distributing packs made from it.
