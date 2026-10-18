// Temporal Bone Atlas: application shell.
import './app.css';
import { Store, DEPTH_NAMES } from './state.js';
import { parsePack, base64ToBytes, buildDataset } from './pack.js';
import { parseNifti } from './nifti.js';
import { parseSTL } from './stl.js';
import { SlicePane } from './view2d.js';
import { Scene3D } from './view3d.js';
import { Panel } from './panel.js';
import { TourRunner } from './tours.js';
import { QuizRunner } from './quiz.js';
import { openSettings, openHelp, openAbout } from './settings.js';
import { DEFAULT_HIDDEN, STRUCTURE_BY_ID } from './content.js';

const esc = (s) => String(s).replace(/[&<>"]/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]));

const store = new Store();
const app = document.getElementById('app');
app.innerHTML = `
  <header class="topbar">
    <div class="brand"><span class="wordmark">Temporal Bone Atlas</span><button class="chip dataset-chip" data-menu="dataset" title="Dataset">Loading</button></div>
    <div class="dial" role="radiogroup" aria-label="Depth">
      <button class="dial-btn" data-depth="1" role="radio">Junior</button>
      <button class="dial-btn" data-depth="2" role="radio">Senior</button>
      <button class="dial-btn" data-depth="3" role="radio">Fellow</button>
    </div>
    <div class="top-actions">
      <button class="btn-top" data-menu="tours">Tours</button>
      <button class="btn-top" data-menu="quiz">Quiz</button>
      <button class="btn-top" data-act="panel" title="Show or hide the structure panel">Structures</button>
      <button class="btn-top icon" data-act="settings" title="Settings" aria-label="Settings">Settings</button>
      <button class="btn-top icon" data-act="help" title="Help (?)" aria-label="Help">?</button>
    </div>
    <div class="menu" hidden></div>
  </header>
  <main class="main">
    <div class="viewer" data-layout="grid">
      <div class="pane-slot" data-slot="axial"></div>
      <div class="pane-slot" data-slot="coronal"></div>
      <div class="pane-slot" data-slot="sagittal"></div>
      <div class="pane-slot" data-slot="3d"></div>
      <div class="tourbar" hidden></div>
    </div>
    <aside class="panel"></aside>
  </main>
  <div class="toast" hidden></div>
  <div class="loading"><div class="loading-box"><div class="spinner"></div><div class="loading-text">Decoding the built-in phantom</div></div></div>
  <input type="file" class="file-input" multiple accept=".tba,.nii,.nii.gz,.gz,.json,.stl" hidden>`;

const viewer = app.querySelector('.viewer');
const panes = {
  axial: new SlicePane('axial', store, viewer.querySelector('[data-slot="axial"]')),
  coronal: new SlicePane('coronal', store, viewer.querySelector('[data-slot="coronal"]')),
  sagittal: new SlicePane('sagittal', store, viewer.querySelector('[data-slot="sagittal"]'))
};
const scene = new Scene3D(store, viewer.querySelector('[data-slot="3d"]'), panes);
const panel = new Panel(store, app.querySelector('.panel'));
const tours = new TourRunner(store, viewer.querySelector('.tourbar'), scene, panes);
const quiz = new QuizRunner(store, panel, scene);
const menuEl = app.querySelector('.menu');
const toastEl = app.querySelector('.toast');
const fileInput = app.querySelector('.file-input');

// ---------- layout ----------
function applyLayout() {
  const s = store.get('settings');
  viewer.dataset.layout = s.layout === 'single' ? 'single' : s.layout;
  viewer.dataset.max = s.maximized || '';
  app.classList.toggle('panel-closed', !s.panelOpen);
  app.dataset.textsize = s.textSize;
  const rm = s.reducedMotion === null ? window.matchMedia('(prefers-reduced-motion: reduce)').matches : s.reducedMotion;
  app.classList.toggle('reduced-motion', !!rm);
  requestAnimationFrame(() => { for (const p of Object.values(panes)) p.resize(); scene.resize(); });
}
function toggleMaximize(id) {
  const s = store.get('settings');
  if (s.layout === 'single' && s.maximized === id) { store.state.settings.layout = store.state.settings.prevLayout || 'grid'; store.state.settings.maximized = null; }
  else { if (s.layout !== 'single') store.state.settings.prevLayout = s.layout; store.state.settings.layout = 'single'; store.state.settings.maximized = id; }
  store.saveSettings(); store.emit('settings', { key: 'layout', value: store.state.settings.layout }); applyLayout();
}
store.on('settings', (e) => { if (['layout', 'panelOpen', 'textSize', 'reducedMotion', '*'].includes(e.key)) applyLayout(); });
store.on('focusplane', (plane) => {
  const s = store.get('settings');
  if (s.layout === 'single' && s.maximized !== plane) { store.state.settings.maximized = plane; store.saveSettings(); applyLayout(); }
  const el = viewer.querySelector(`[data-slot="${plane}"]`);
  if (el && !app.classList.contains('reduced-motion')) { el.classList.remove('flash'); void el.offsetWidth; el.classList.add('flash'); setTimeout(() => el.classList.remove('flash'), 900); }
});
viewer.querySelectorAll('.pane-slot').forEach(el => el.addEventListener('dblclick', (e) => { if (e.target.closest('.pane-corner')) toggleMaximize(el.dataset.slot); }));

// ---------- depth dial ----------
function renderDial() {
  const d = store.get('depth');
  app.querySelectorAll('.dial-btn').forEach(b => { const on = +b.dataset.depth === d; b.classList.toggle('on', on); b.setAttribute('aria-checked', on ? 'true' : 'false'); });
}
app.querySelectorAll('.dial-btn').forEach(b => b.addEventListener('click', () => store.setDepth(+b.dataset.depth)));
store.on('depth', renderDial);
renderDial();

// ---------- menus ----------
let menuOpen = null;
function closeMenu() { menuEl.hidden = true; menuOpen = null; }
function openMenu(kind, anchor) {
  if (menuOpen === kind) { closeMenu(); return; }
  menuOpen = kind;
  const depth = store.get('depth');
  if (kind === 'tours') menuEl.innerHTML = tours.pickerHtml(depth);
  else if (kind === 'quiz') menuEl.innerHTML = quiz.pickerHtml(depth);
  else if (kind === 'dataset') {
    const ds = store.get('dataset');
    const lib = library.map(e => `<button class="menu-item lib-item" data-lib="${esc(e.id)}">${esc(e.name)} <span class="lvl">${e.side === 'L' ? 'left' : 'right'}</span> <span class="lvl ${e.cached ? 'above' : ''}" data-libstate="${esc(e.id)}">${e.cached ? 'on this device' : fmtMB(e.bytes)}</span><span class="tour-item-sub">${esc(e.source || e.kind || '')}</span></button>`).join('');
    menuEl.innerHTML = `<div class="menu-title">Dataset</div>
      <button class="menu-item" data-ds="phantom">Built-in phantom<span class="tour-item-sub">Synthetic right temporal bone with every structure labelled. Not patient anatomy.</span></button>
      ${lib ? `<div class="menu-title">Real imaging (downloads once, then stays on this device)</div>${lib}` : ''}
      <button class="menu-item" data-ds="open">Open a data pack or NIfTI<span class="tour-item-sub">A .tba pack from the converter, or a .nii/.nii.gz volume; add a landmarks .json alongside if you have one.</span></button>
      <button class="menu-item" data-ds="about">About this dataset<span class="tour-item-sub">${ds ? esc(ds.name) : ''}</span></button>`;
  }
  menuEl.hidden = false;
  const r = anchor.getBoundingClientRect();
  menuEl.style.left = Math.min(r.left, window.innerWidth - 360) + 'px';
  menuEl.querySelectorAll('[data-tour]').forEach(b => b.addEventListener('click', () => { closeMenu(); quiz.session && quiz.exit(); tours.start(b.dataset.tour); }));
  menuEl.querySelectorAll('[data-quiz]').forEach(b => b.addEventListener('click', () => { closeMenu(); tours.exit(); store.setting('panelOpen', true); quiz.start(b.dataset.quiz); }));
  menuEl.querySelectorAll('[data-lib]').forEach(b => b.addEventListener('click', () => { closeMenu(); loadLibraryEntry(library.find(e => e.id === b.dataset.lib)); }));
  menuEl.querySelectorAll('[data-ds]').forEach(b => b.addEventListener('click', () => {
    closeMenu();
    if (b.dataset.ds === 'phantom') loadEmbedded();
    else if (b.dataset.ds === 'open') fileInput.click();
    else openAbout(store, app);
  }));
}
app.querySelectorAll('[data-menu]').forEach(b => b.addEventListener('click', (e) => { e.stopPropagation(); openMenu(b.dataset.menu, b); }));
document.addEventListener('click', (e) => { if (!menuEl.hidden && !menuEl.contains(e.target)) closeMenu(); });
app.querySelector('[data-act="settings"]').addEventListener('click', () => openSettings(store, app));
app.querySelector('[data-act="help"]').addEventListener('click', () => openHelp(app));
app.querySelector('[data-act="panel"]').addEventListener('click', () => store.setting('panelOpen', !store.get('settings').panelOpen));

// ---------- toast ----------
let toastTimer = null;
store.on('toast', (msg) => { toastEl.textContent = msg; toastEl.hidden = false; clearTimeout(toastTimer); toastTimer = setTimeout(() => { toastEl.hidden = true; }, 2600); });

// ---------- keyboard ----------
document.addEventListener('keydown', (e) => {
  const tag = (e.target.tagName || '').toLowerCase();
  if (e.key === 'Escape') {
    const modal = app.querySelector('.modal-back');
    if (modal) { modal.remove(); return; }
    if (!menuEl.hidden) { closeMenu(); return; }
  }
  if (tag === 'input' || tag === 'select' || tag === 'textarea') { if (e.key === 'Escape') e.target.blur(); return; }
  const s = store.state;
  const active = s.activePane;
  const stepActive = (d) => { if (active && panes[active]) panes[active].stepSlice(d); };
  switch (e.key) {
    case 'ArrowUp': stepActive(1); e.preventDefault(); break;
    case 'ArrowDown': stepActive(-1); e.preventDefault(); break;
    case 'PageUp': stepActive(5); e.preventDefault(); break;
    case 'PageDown': stepActive(-5); e.preventDefault(); break;
    case 'ArrowRight': if (tours.tour) { tours.next(); e.preventDefault(); } break;
    case 'ArrowLeft': if (tours.tour) { tours.prev(); e.preventDefault(); } break;
    case ' ': if (tours.tour) { tours.next(); e.preventDefault(); } break;
    case 'Escape': if (!menuEl.hidden) closeMenu(); else if (app.querySelector('.modal-back')) app.querySelector('.modal-back').remove(); else if (tours.tour) tours.exit(); else if (quiz.session) quiz.exit(); else store.select(null); break;
    case '1': toggleMaximize('axial'); break;
    case '2': toggleMaximize('coronal'); break;
    case '3': toggleMaximize('sagittal'); break;
    case '4': toggleMaximize('3d'); break;
    case 'l': case 'L': { const order = ['off', 'selected', 'auto', 'all']; const cur = order.indexOf(s.settings.sliceLabels); store.setting('sliceLabels', order[(cur + 1) % order.length]); store.emit('toast', `Slice labels: ${order[(cur + 1) % order.length]}`); break; }
    case 'k': case 'K': { const order = ['off', 'selected', 'auto', 'all']; const cur = order.indexOf(s.settings.labels3d); store.setting('labels3d', order[(cur + 1) % order.length]); store.emit('toast', `3D labels: ${order[(cur + 1) % order.length]}`); break; }
    case 'p': case 'P': store.setting('planes3d', !s.settings.planes3d); break;
    case 'b': case 'B': store.setting('boneShell', !s.settings.boneShell); break;
    case 'c': case 'C': scene.centerOnCursor(); break;
    case 'r': case 'R': if (active && panes[active]) panes[active].resetView(); else scene.fitCamera('lateral'); break;
    case '/': e.preventDefault(); store.setting('panelOpen', true); panel.search.focus(); break;
    case '?': openHelp(app); break;
    default: return;
  }
});

// ---------- dataset loading ----------
function showLoading(text) { const l = app.querySelector('.loading'); l.hidden = false; l.querySelector('.loading-text').textContent = text; }
function hideLoading() { app.querySelector('.loading').hidden = true; }
function setDataset(ds) {
  store.state.hidden = new Set([...DEFAULT_HIDDEN].filter(id => ds.meshById.has(id)));
  store.state.selectedId = null;
  store.set('dataset', ds);
  // start the cursor on the vestibule if we know where it is, else the volume centre
  const start = ds.anchorOf('vestibule') || ds.volume.center;
  store.setCrosshair(start, 'load');
  const chip = app.querySelector('.dataset-chip');
  chip.textContent = ds.kind === 'phantom' ? 'Synthetic phantom' : ds.name;
  chip.classList.toggle('warn', ds.kind === 'phantom');
  chip.title = ds.kind === 'phantom' ? 'Synthetic phantom: correct relationships, not patient anatomy. Open a data pack for real imaging.' : ds.name;
  store.emit('toast', ds.kind === 'phantom' ? 'Synthetic phantom loaded (not patient anatomy). Click any structure; press ? for help.' : `Loaded ${ds.name}`);
  hideLoading();
}
async function loadEmbedded() {
  const b64 = window.__TBA_PACK__;
  if (!b64) { hideLoading(); store.emit('toast', 'No built-in dataset in this build. Open a data pack.'); return; }
  showLoading('Decoding the built-in phantom');
  try {
    const ds = await parsePack(base64ToBytes(b64));
    setDataset(ds);
  } catch (err) {
    hideLoading();
    console.error(err);
    store.emit('toast', 'Could not decode the built-in phantom: ' + err.message);
  }
}
async function loadFiles(files) {
  const list = [...files];
  if (!list.length) return;
  showLoading('Reading ' + list.map(f => f.name).join(', '));
  try {
    let ds = null; let landmarks = null; const stls = [];
    for (const f of list) {
      const name = f.name.toLowerCase();
      const bytes = new Uint8Array(await f.arrayBuffer());
      if (name.endsWith('.tba')) ds = await parsePack(bytes);
      else if (name.endsWith('.nii') || name.endsWith('.nii.gz')) {
        const vol = await parseNifti(bytes);
        ds = buildDataset({ name: f.name, kind: 'volume', side: 'R', notes: 'Plain volume: no surfaces or labels. Use author mode to set structure locations, or build a .tba pack with the converter.', volume: vol, labels: null, labelIds: {}, meshes: [], landmarks: {} });
      } else if (name.endsWith('.json')) {
        try { const j = JSON.parse(new TextDecoder().decode(bytes)); landmarks = j.landmarks || j; } catch (e) { /* ignore */ }
      } else if (name.endsWith('.stl')) {
        const m = parseSTL(bytes); m.id = f.name.replace(/\.stl$/i, '').toLowerCase().replace(/[^a-z0-9]+/g, '_'); stls.push(m);
      }
    }
    if (!ds) throw new Error('Choose a .tba pack or a NIfTI volume (optionally with a landmarks .json or STL meshes).');
    if (stls.length) { for (const m of stls) { ds.meshes.push(m); } ds = buildDataset(ds); }
    if (landmarks) { Object.assign(ds.landmarks, landmarks); ds = buildDataset(ds); }
    setDataset(ds);
  } catch (err) {
    hideLoading();
    console.error(err);
    store.emit('toast', 'Could not load: ' + err.message);
  }
}
fileInput.addEventListener('change', () => { loadFiles(fileInput.files); fileInput.value = ''; });
app.addEventListener('dragover', (e) => { e.preventDefault(); app.classList.add('dragging'); });
app.addEventListener('dragleave', () => app.classList.remove('dragging'));
app.addEventListener('drop', (e) => { e.preventDefault(); app.classList.remove('dragging'); if (e.dataTransfer.files.length) loadFiles(e.dataTransfer.files); });

// ---------- dataset library (data/datasets.json next to the page) ----------
let library = [];
const fmtMB = (b) => b ? `${(b / 1e6).toFixed(b < 10e6 ? 1 : 0)} MB` : '';
async function cacheOpen() { try { if (typeof caches === 'undefined' || !location.protocol.startsWith('http')) return null; return await caches.open('tba-packs-v1'); } catch (e) { return null; } }
async function loadLibrary() {
  if (!location.protocol.startsWith('http')) return;
  try {
    const url = new URL('data/datasets.json', location.href);
    const r = await fetch(url, { cache: 'no-cache' });
    if (!r.ok) return;
    const j = await r.json();
    library = (j.datasets || []).map(e => ({ ...e, url: new URL(e.file, url).href }));
    const c = await cacheOpen();
    if (c) for (const e of library) e.cached = !!(await c.match(e.url));
  } catch (e) { /* no library: file:// or not hosted with data */ }
}
async function fetchWithProgress(url, onProgress) {
  const r = await fetch(url);
  if (!r.ok) throw new Error(`${r.status} ${r.statusText}`);
  const total = +(r.headers.get('Content-Length') || 0);
  if (!r.body) return new Uint8Array(await r.arrayBuffer());
  const reader = r.body.getReader(); const chunks = []; let got = 0;
  for (;;) { const { done, value } = await reader.read(); if (done) break; chunks.push(value); got += value.length; onProgress(got, total); }
  const out = new Uint8Array(got); let o = 0; for (const ch of chunks) { out.set(ch, o); o += ch.length; }
  return out;
}
async function loadLibraryEntry(e) {
  if (!e) return;
  showLoading(`Opening ${e.name}`);
  try {
    const c = await cacheOpen();
    let bytes = null;
    if (c) { const hit = await c.match(e.url); if (hit) bytes = new Uint8Array(await hit.arrayBuffer()); }
    if (!bytes) {
      bytes = await fetchWithProgress(e.url, (got, total) => showLoading(`Downloading ${e.name}: ${fmtMB(got)}${total ? ` of ${fmtMB(total)}` : ''}`));
      if (c) { try { await c.put(e.url, new Response(bytes, { headers: { 'Content-Type': 'application/octet-stream' } })); e.cached = true; } catch (err) { /* storage full or disallowed */ } }
    }
    const ds = await parsePack(bytes);
    ds.name = ds.name || e.name; ds.libraryId = e.id;
    setDataset(ds);
    if (e.cached) store.emit('toast', `${e.name} is saved on this device; it opens offline from now on.`);
  } catch (err) { hideLoading(); console.error(err); store.emit('toast', `Could not load ${e.name}: ${err.message}`); }
}
async function removeCached(e) { const c = await cacheOpen(); if (c) { await c.delete(e.url); e.cached = false; } }
window.__tbaLibrary = { loadLibrary, loadLibraryEntry, removeCached, get: () => library };

// ---------- URL parameters: ?data=url ----------
async function boot() {
  applyLayout();
  const params = new URLSearchParams(location.search);
  await loadLibrary();
  const url = params.get('data');
  if (url && library.find(e => e.id === url)) { await loadLibraryEntry(library.find(e => e.id === url)); return; }
  if (url) {
    showLoading('Fetching ' + url);
    try { const r = await fetch(url); const bytes = new Uint8Array(await r.arrayBuffer()); const ds = url.toLowerCase().includes('.nii') ? buildDataset({ name: url, kind: 'volume', side: 'R', notes: '', volume: await parseNifti(bytes), labels: null, labelIds: {}, meshes: [], landmarks: {} }) : await parsePack(bytes); setDataset(ds); return; }
    catch (err) { console.error(err); store.emit('toast', 'Could not fetch ' + url + '; loading the phantom instead.'); }
  }
  await loadEmbedded();
}
boot();

// expose for debugging / tests
window.__tba = { store, panes, scene, panel, tours, quiz, STRUCTURE_BY_ID, DEPTH_NAMES };
