# Tests and rehearsal tools

Everything here runs offline against synthetic fixtures; nothing needs Zenodo.

| Script | What it checks | Run |
| --- | --- | --- |
| `test_nrrd_stream.py` | `NrrdStream` block reads equal SimpleITK's for gzip/raw, 3-D and 4-D (Slicer layers, interleaved and planar), flipped and RAS-space files; the streaming label sampler equals ITK nearest-neighbour resampling; old-Slicer headers (one layer per segment, names only); overlap matching with a bone layer | `python3 tools/tests/test_nrrd_stream.py` |
| `test_rotated_labels.py` | the rotated (bucketed) label sampler equals ITK's affine resampling | `python3 tools/tests/test_rotated_labels.py` |
| `make_fullsize_fixture.py DIR` | writes a 632x617x668 CT + two-layer `.seg.nrrd` + PLY surfaces shaped like an OpenEar archive (5 min, streamed) | `python3 tools/tests/make_fullsize_fixture.py tools/tests/_work/fullsize` |
| `test_transform_chain.py` | needs the full-size fixture: a raw-frame copy of its CT plus a split, partly inverted transform chain and a decoy; the converter must recover the chain (pack correlation > 0.97 with the registered conversion) | `python3 tools/tests/test_transform_chain.py` |
| `peakrss.py CMD...` | runs a command and prints its children's peak RSS (converter memory budget) | `python3 tools/tests/peakrss.py python3 tools/convert_openear.py ...` |
| `rangeserver.py DIR` | an HTTP server with Range support on :8768, to rehearse `fetch_openear.py --url http://127.0.0.1:8768/X.zip` against a local zip | |
| `shot_*.py URL OUT ...` | Playwright (headless Chromium) checks of the built site: boot flow and retry screen (`shot_boot`), context volume + sectioning (`shot_ctx`), planes at a cursor position (`shot_planes URL OUT x y z [dataset]`), whole-model scrolling (`shot_whole`) | serve `site/` first: `cd site && python3 -m http.server 8772` |

`tools/selftest_labels.py phantom/ OUT.tba` (phantom from `tools/make_phantom.py`) is the end-to-end converter check used by the GitHub self-test workflow: two-layer segmentation, anatomical-frame estimate (must be < 20 deg from identity, right ear), Dice > 0.97 against ITK.
