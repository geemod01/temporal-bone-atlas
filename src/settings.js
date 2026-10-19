// Settings dialog (one screen) and the help overlay.
import { PRESETS } from './state.js';

const esc = (s) => String(s).replace(/[&<>"]/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]));

export function openSettings(store, host) {
  const s = store.get('settings');
  const dlg = document.createElement('div');
  dlg.className = 'modal-back';
  dlg.innerHTML = `<div class="modal settings" role="dialog" aria-label="Settings">
    <div class="modal-head"><h2>Settings</h2><button class="btn-ghost" data-act="close">Close</button></div>
    <div class="settings-grid">
      <label>Layout
        <select data-k="layout">
          <option value="grid" ${s.layout === 'grid' ? 'selected' : ''}>Four panes (2 x 2)</option>
          <option value="three" ${s.layout === 'three' ? 'selected' : ''}>3D large, slices stacked</option>
          <option value="slices" ${s.layout === 'slices' ? 'selected' : ''}>Slices only</option>
        </select></label>
      <label>Window preset
        <select data-k="windowPreset">
          <option value="bone" ${s.windowPreset === 'bone' ? 'selected' : ''}>Bone (W 4000, L 700)</option>
          <option value="stapes" ${s.windowPreset === 'stapes' ? 'selected' : ''}>Ossicles (W 2500, L 900)</option>
          <option value="soft" ${s.windowPreset === 'soft' ? 'selected' : ''}>Soft tissue (W 400, L 40)</option>
          <option value="custom" ${s.windowPreset === 'custom' ? 'selected' : ''}>Custom</option>
        </select></label>
      <label>Window width <input type="number" data-k="window.w" value="${Math.round(s.window.w)}" step="50"></label>
      <label>Window level <input type="number" data-k="window.l" value="${Math.round(s.window.l)}" step="50"></label>
      <label>Display
        <select data-k="mirror">
          <option value="false" ${!s.mirror ? 'selected' : ''}>As scanned (radiological convention)</option>
          <option value="true" ${s.mirror ? 'selected' : ''}>Mirrored (view a left ear as a right ear)</option>
        </select></label>
      <label>Labels on slices
        <select data-k="sliceLabels">
          <option value="off" ${s.sliceLabels === 'off' ? 'selected' : ''}>Off</option>
          <option value="selected" ${s.sliceLabels === 'selected' ? 'selected' : ''}>Selected structure only</option>
          <option value="auto" ${s.sliceLabels === 'auto' ? 'selected' : ''}>Structures at the current level</option>
          <option value="all" ${s.sliceLabels === 'all' ? 'selected' : ''}>All labelled structures</option>
        </select></label>
      <label>Labels in 3D
        <select data-k="labels3d">
          <option value="off" ${s.labels3d === 'off' ? 'selected' : ''}>Off</option>
          <option value="selected" ${s.labels3d === 'selected' ? 'selected' : ''}>Selected structure only</option>
          <option value="auto" ${s.labels3d === 'auto' ? 'selected' : ''}>Structures at the current level</option>
          <option value="all" ${s.labels3d === 'all' ? 'selected' : ''}>All visible structures</option>
        </select></label>
      <label>CT planes in 3D
        <select data-k="planes3d">
          <option value="true" ${s.planes3d ? 'selected' : ''}>Shown</option>
          <option value="false" ${!s.planes3d ? 'selected' : ''}>Hidden</option>
        </select></label>
      <label>Plane opacity <input type="range" min="0.2" max="1" step="0.05" data-k="planeOpacity" value="${s.planeOpacity}"></label>
      <label>Bone and dura surfaces in 3D (context)
        <select data-k="boneShell">
          <option value="false" ${!s.boneShell ? 'selected' : ''}>Hidden</option>
          <option value="true" ${s.boneShell ? 'selected' : ''}>Shown (translucent)</option>
        </select></label>
      <label>Click on a slice
        <select data-k="clickSelects">
          <option value="true" ${s.clickSelects ? 'selected' : ''}>Moves the cursor and opens the structure under it</option>
          <option value="false" ${!s.clickSelects ? 'selected' : ''}>Moves the cursor only</option>
        </select></label>
      <label>Text size
        <select data-k="textSize">
          <option value="s" ${s.textSize === 's' ? 'selected' : ''}>Small</option>
          <option value="m" ${s.textSize === 'm' ? 'selected' : ''}>Medium</option>
          <option value="l" ${s.textSize === 'l' ? 'selected' : ''}>Large</option>
        </select></label>
      <label>Motion
        <select data-k="reducedMotion">
          <option value="null" ${s.reducedMotion === null ? 'selected' : ''}>Follow system setting</option>
          <option value="true" ${s.reducedMotion === true ? 'selected' : ''}>Reduced</option>
          <option value="false" ${s.reducedMotion === false ? 'selected' : ''}>Full</option>
        </select></label>
      <label>Author mode
        <select data-k="authorMode">
          <option value="false" ${!s.authorMode ? 'selected' : ''}>Off</option>
          <option value="true" ${s.authorMode ? 'selected' : ''}>On (set structure locations on real scans)</option>
        </select></label>
    </div>
    <div class="settings-foot">
      <button class="btn-ghost" data-act="landmarks">Download landmarks (JSON)</button>
      <button class="btn-ghost" data-act="clearcache">Remove datasets saved on this device</button>
      <button class="btn-ghost" data-act="reset">Reset to defaults</button>
    </div>
  </div>`;
  host.appendChild(dlg);
  const close = () => dlg.remove();
  dlg.addEventListener('click', (e) => { if (e.target === dlg) close(); });
  dlg.querySelector('[data-act="close"]').addEventListener('click', close);
  dlg.querySelector('[data-act="reset"]').addEventListener('click', () => { store.resetSettings(); close(); openSettings(store, host); });
  dlg.querySelector('[data-act="clearcache"]').addEventListener('click', async () => {
    const lib = window.__tbaLibrary; if (!lib) return;
    for (const e of lib.get()) if (e.cached) await lib.removeCached(e);
    store.emit('toast', 'Downloaded datasets removed from this device');
  });
  dlg.querySelector('[data-act="landmarks"]').addEventListener('click', () => {
    const ds = store.get('dataset'); if (!ds) return;
    const blob = new Blob([JSON.stringify({ dataset: ds.name, landmarks: ds.landmarks }, null, 2)], { type: 'application/json' });
    const a = document.createElement('a'); a.href = URL.createObjectURL(blob); a.download = 'landmarks.json'; a.click();
    setTimeout(() => URL.revokeObjectURL(a.href), 2000);
  });
  const parse = (k, v) => {
    if (v === 'true') return true; if (v === 'false') return false; if (v === 'null') return null;
    if (k === 'planeOpacity') return parseFloat(v);
    return v;
  };
  dlg.querySelectorAll('[data-k]').forEach(inp => inp.addEventListener(inp.type === 'range' ? 'input' : 'change', () => {
    const k = inp.dataset.k;
    if (k === 'windowPreset') {
      store.state.settings.windowPreset = inp.value;
      if (PRESETS[inp.value]) { store.setting('window', { ...PRESETS[inp.value] }); dlg.querySelector('[data-k="window.w"]').value = PRESETS[inp.value].w; dlg.querySelector('[data-k="window.l"]').value = PRESETS[inp.value].l; }
      return;
    }
    if (k.startsWith('window.')) {
      const w = parseFloat(dlg.querySelector('[data-k="window.w"]').value) || 1, l = parseFloat(dlg.querySelector('[data-k="window.l"]').value) || 0;
      store.state.settings.windowPreset = 'custom'; dlg.querySelector('[data-k="windowPreset"]').value = 'custom';
      store.setting('window', { w: Math.max(1, w), l });
      return;
    }
    store.setting(k, parse(k, inp.value));
  }));
  dlg.querySelector('select, input').focus();
  return dlg;
}

export function openHelp(host) {
  const dlg = document.createElement('div');
  dlg.className = 'modal-back';
  dlg.innerHTML = `<div class="modal help" role="dialog" aria-label="Help">
    <div class="modal-head"><h2>How to use the atlas</h2><button class="btn-ghost" data-act="close">Close</button></div>
    <div class="help-cols">
      <div>
        <h3>In a slice</h3>
        <ul>
          <li><b>Click or drag</b> moves the cursor; every other view follows.</li>
          <li><b>Click a labelled structure</b> to open its card.</li>
          <li><b>Scroll</b> to change slice. <b>Ctrl + scroll</b> (or pinch) zooms around the pointer.</li>
          <li><b>Shift + drag</b> adjusts window and level. <b>Right-drag</b> or <b>Alt + drag</b> pans.</li>
          <li><b>Double-click</b> zooms back out to the whole scan. <b>Zoom in</b> on a structure's card frames that structure.</li>
          <li><b>Arrow up / down</b> step slices in the pane under the pointer.</li>
        </ul>
        <h3>In 3D</h3>
        <ul>
          <li><b>Drag</b> orbits, <b>scroll</b> zooms, <b>right-drag</b> pans.</li>
          <li><b>Click a structure or a CT plane</b> to put the cursor there.</li>
          <li><b>Layers</b> shows or hides groups, the bone surface and the CT planes.</li>
        </ul>
      </div>
      <div>
        <h3>Keyboard</h3>
        <ul>
          <li><b>1 2 3 4</b> maximise a pane (axial, coronal, sagittal, 3D); press again to restore.</li>
          <li><b>L</b> cycle slice labels, <b>K</b> cycle 3D labels, <b>P</b> toggle CT planes in 3D, <b>B</b> bone surface.</li>
          <li><b>C</b> centre the 3D view on the cursor. <b>R</b> reset the pane under the pointer.</li>
          <li><b>Space</b> or <b>Right arrow</b> next tour step, <b>Left arrow</b> previous, <b>Esc</b> exit tour or clear.</li>
          <li><b>/</b> focus the search box. <b>?</b> this help.</li>
        </ul>
        <h3>The depth dial</h3>
        <p>Junior shows the essentials. Senior adds variants, pitfalls and measurements. Fellow adds approach-level notes and pathology correlates. The dial also decides which labels appear by default.</p>
        <h3>Real imaging</h3>
        <p>Open a <b>.tba</b> pack made with the included converter (OpenEar or any temporal bone CT with STL meshes) or a plain NIfTI volume from the dataset menu. Author mode lets an attending set structure locations on a scan that has no segmentation.</p>
      </div>
    </div>
  </div>`;
  host.appendChild(dlg);
  const close = () => dlg.remove();
  dlg.addEventListener('click', (e) => { if (e.target === dlg) close(); });
  dlg.querySelector('[data-act="close"]').addEventListener('click', close);
  return dlg;
}

export function openAbout(store, host) {
  const ds = store.get('dataset');
  const dlg = document.createElement('div');
  dlg.className = 'modal-back';
  dlg.innerHTML = `<div class="modal about" role="dialog" aria-label="About this dataset">
    <div class="modal-head"><h2>About this dataset</h2><button class="btn-ghost" data-act="close">Close</button></div>
    ${ds ? `<p><b>${esc(ds.name)}</b></p><p>${esc(ds.notes || '')}</p>
    <table class="measure">
      <tr><td>Kind</td><td>${esc(ds.kind || '')}</td></tr>
      <tr><td>Side</td><td>${ds.side === 'L' ? 'Left' : 'Right'} ear</td></tr>
      <tr><td>Volume</td><td>${ds.volume.dims.join(' x ')} voxels at ${ds.volume.spacing.map(x => x.toFixed(3)).join(' x ')} mm</td></tr>
      <tr><td>Surfaces</td><td>${ds.meshes.length}</td></tr>
      <tr><td>Labels</td><td>${ds.labels ? Object.keys(ds.labelIds).length + ' labelled structures' : 'none (landmarks only)'}</td></tr>
    </table>` : '<p>No dataset loaded.</p>'}
    <h3>About the content</h3>
    <p>Structure cards, tours and quiz questions were drafted from standard references (Gulya and Schuknecht; Swartz and Loevner; Harnsberger; Sanna; Brackmann, Shelton and Arriaga) and the primary papers cited on each card. Every card carries a review status; nothing here replaces attending review before educational use.</p>
  </div>`;
  host.appendChild(dlg);
  const close = () => dlg.remove();
  dlg.addEventListener('click', (e) => { if (e.target === dlg) close(); });
  dlg.querySelector('[data-act="close"]').addEventListener('click', close);
  return dlg;
}
