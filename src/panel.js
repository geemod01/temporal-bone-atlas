// Right panel: structure list (grouped, searchable) and the structure card with depth-gated sections.
import { GROUPS, STRUCTURES, STRUCTURE_BY_ID, groupedStructures, sectionVisible, structureName, resolveAnchor, resolveBounds } from './content.js';
import { DEPTH_NAMES } from './state.js';

const esc = (s) => String(s).replace(/[&<>"]/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]));

export class Panel {
  constructor(store, el) {
    this.store = store; this.el = el;
    this.filter = '';
    this.mode = 'list'; // list | card | custom
    el.innerHTML = `
      <div class="panel-head">
        <input type="search" class="search" placeholder="Find a structure" aria-label="Find a structure" autocomplete="off">
        <button class="btn-ghost panel-close" title="Hide panel">Hide</button>
      </div>
      <div class="panel-body"></div>`;
    this.body = el.querySelector('.panel-body');
    this.search = el.querySelector('.search');
    this.search.addEventListener('input', () => { this.filter = this.search.value; if (this.mode !== 'custom') this.renderList(); });
    this.search.addEventListener('keydown', (e) => { if (e.key === 'Escape') { this.search.value = ''; this.filter = ''; this.renderList(); this.search.blur(); } if (e.key === 'Enter') { const g = groupedStructures(store.get('depth'), true, this.filter); if (g.length && g[0].items.length) this.open(g[0].items[0].id, true); } });
    el.querySelector('.panel-close').addEventListener('click', () => store.setting('panelOpen', false));
    store.on('selected', (id) => { if (this.mode === 'custom') return; if (id) this.renderCard(id); else this.renderList(); });
    store.on('depth', () => this.rerender());
    store.on('hidden', () => { if (this.mode === 'list') this.renderList(); });
    store.on('dataset', () => this.rerender());
    store.on('settings', (e) => { if (e.key === 'authorMode' || e.key === 'textSize' || e.key === '*') this.rerender(); });
    this.renderList();
  }
  rerender() { if (this.mode === 'card' && this.store.get('selectedId')) this.renderCard(this.store.get('selectedId')); else if (this.mode !== 'custom') this.renderList(); }
  setCustom(node) { this.mode = 'custom'; this.body.innerHTML = ''; this.body.appendChild(node); this.body.scrollTop = 0; }
  exitCustom() { this.mode = 'list'; const id = this.store.get('selectedId'); if (id) this.renderCard(id); else this.renderList(); }
  open(id, locate) {
    this.store.select(id);
    if (locate) { const ds = this.store.get('dataset'); const p = resolveAnchor(ds, id); if (p) this.store.setCrosshair(p, 'panel'); else this.store.emit('toast', 'This dataset has no location for that structure yet'); }
  }

  // ---------- list ----------
  renderList() {
    this.mode = 'list';
    const st = this.store.state, depth = st.depth;
    const showAll = st.showAllStructures || !!this.filter;
    const groups = groupedStructures(depth, showAll, this.filter);
    const ds = st.dataset;
    const total = STRUCTURES.length, shown = groups.reduce((n, g) => n + g.items.length, 0);
    let html = `<div class="list-meta"><span>${shown} of ${total} structures at ${DEPTH_NAMES[depth]} level</span>` +
      (shown < total && !this.filter ? `<button class="btn-link" data-action="showall">Show all</button>` : (st.showAllStructures && !this.filter ? `<button class="btn-link" data-action="showlevel">Only ${DEPTH_NAMES[depth]}</button>` : '')) + `</div>`;
    if (!groups.length) html += `<div class="empty">No structure matches "${esc(this.filter)}". Try an alias such as "attic" or "FN".</div>`;
    for (const g of groups) {
      html += `<div class="group"><div class="group-head"><span class="dot" style="--c:${g.meta.color}"></span>${g.meta.name}</div>`;
      for (const s of g.items) {
        const hasMesh = ds && ds.meshById.has(s.id);
        const hidden = st.hidden.has(s.id);
        html += `<div class="row ${s.id === st.selectedId ? 'sel' : ''}" data-id="${s.id}" role="button" tabindex="0">
          <span class="dot" style="--c:${s.color || g.meta.color}"></span>
          <span class="row-name">${esc(s.name)}</span>
          ${s.level > 1 ? `<span class="lvl" title="${DEPTH_NAMES[s.level]} level">${DEPTH_NAMES[s.level][0]}</span>` : ''}
          ${hasMesh ? `<button class="eye ${hidden ? 'off' : ''}" data-eye="${s.id}" title="${hidden ? 'Show in 3D' : 'Hide in 3D'}" aria-label="toggle 3D visibility"></button>` : '<span class="eye none" title="Landmark (no surface)"></span>'}
        </div>`;
      }
      html += `</div>`;
    }
    this.body.innerHTML = html;
    this.body.querySelectorAll('.row').forEach(r => {
      r.addEventListener('click', (e) => { if (e.target.closest('.eye')) return; this.open(r.dataset.id, true); });
      r.addEventListener('keydown', (e) => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); this.open(r.dataset.id, true); } });
    });
    this.body.querySelectorAll('[data-eye]').forEach(b => b.addEventListener('click', () => this.store.setHidden(b.dataset.eye, !this.store.state.hidden.has(b.dataset.eye))));
    const sa = this.body.querySelector('[data-action="showall"]'); if (sa) sa.addEventListener('click', () => { this.store.state.showAllStructures = true; this.renderList(); });
    const sl = this.body.querySelector('[data-action="showlevel"]'); if (sl) sl.addEventListener('click', () => { this.store.state.showAllStructures = false; this.renderList(); });
  }

  // ---------- card ----------
  renderCard(id) {
    const s = STRUCTURE_BY_ID.get(id);
    if (!s) { this.renderList(); return; }
    this.mode = 'card';
    const st = this.store.state, depth = st.depth, ds = st.dataset;
    const g = GROUPS[s.group];
    const hasMesh = ds && ds.meshById.has(s.id);
    const hidden = st.hidden.has(s.id);
    const list = (arr, cls) => arr && arr.length ? `<ul class="${cls || ''}">${arr.map(x => `<li>${esc(x)}</li>`).join('')}</ul>` : '';
    const sec = (key, title, inner) => (inner && sectionVisible(key, depth)) ? `<section class="card-sec sec-${key}"><h3>${title}</h3>${inner}</section>` : '';
    let html = `<div class="card">
      <div class="card-top">
        <button class="btn-link back">All structures</button>
        <div class="card-actions">
          <button class="btn-ghost" data-action="locate" title="Move the cursor to this structure">Locate</button>
          <button class="btn-ghost" data-action="zoom" title="Zoom the slice views in on this structure (double-click a view to zoom back out)">Zoom in</button>
          ${hasMesh ? `<button class="btn-ghost ${hidden ? '' : 'on'}" data-action="toggle3d">${hidden ? 'Show in 3D' : 'Shown in 3D'}</button>` : ''}
        </div>
      </div>
      <h2 class="card-title"><span class="dot" style="--c:${s.color || g.color}"></span>${esc(s.name)}</h2>
      <div class="card-meta">${esc(g.name)}${s.aliases && s.aliases.length ? ` <span class="aliases">also: ${esc(s.aliases.slice(0, 4).join(', '))}</span>` : ''}</div>
      <p class="summary">${esc(s.summary)}</p>`;
    if (s.find) {
      html += `<section class="card-sec sec-find"><h3>Find it on CT</h3><dl class="find">
        <dt><button class="btn-chip" data-plane="axial">Axial</button></dt><dd>${esc(s.find.axial)}</dd>
        <dt><button class="btn-chip" data-plane="coronal">Coronal</button></dt><dd>${esc(s.find.coronal)}</dd>
        <dt><button class="btn-chip" data-plane="sagittal">Sagittal</button></dt><dd>${esc(s.find.sagittal)}</dd></dl></section>`;
    }
    html += sec('relations', 'Relations', list(s.relations));
    const surgical = depth === 1 ? (s.surgical || []).slice(0, 2) : s.surgical;
    html += sec('surgical', 'Surgical significance', list(surgical));
    if (s.variants && s.variants.length) html += sec('variants', 'Variants', `<dl class="variants">${s.variants.map(v => `<dt>${esc(v.name)}${v.prevalence ? ` <span class="prev">${esc(v.prevalence)}</span>` : ''}</dt><dd>${esc(v.note)}</dd>`).join('')}</dl>`);
    html += sec('pitfalls', 'Pitfalls', list(s.pitfalls, 'pitfalls'));
    if (s.measurements && s.measurements.length) html += sec('measurements', 'Measurements', `<table class="measure">${s.measurements.map(m => `<tr><td>${esc(m.label)}</td><td>${esc(m.value)}</td></tr>`).join('')}</table>`);
    if (s.classification && s.classification.length) html += sec('classification', 'Classification', `<dl class="variants">${s.classification.map(c => `<dt>${esc(c.name)}</dt><dd>${esc(c.note)}</dd>`).join('')}</dl>`);
    html += sec('fellow', 'Approach-level notes', list(s.fellow));
    html += sec('pathology', 'Pathology correlates', list(s.pathology));
    // what the dial hides
    const hiddenSecs = [];
    if (depth < 2 && ((s.variants && s.variants.length) || (s.pitfalls && s.pitfalls.length) || (s.measurements && s.measurements.length) || (s.surgical && s.surgical.length > 2))) hiddenSecs.push('Senior adds variants, pitfalls, measurements and the full surgical list');
    if (depth < 3 && ((s.fellow && s.fellow.length) || (s.pathology && s.pathology.length))) hiddenSecs.push('Fellow adds approach-level notes and pathology correlates');
    if (hiddenSecs.length) html += `<div class="more-depth">${hiddenSecs.map(esc).join('. ')}. <button class="btn-link" data-action="deeper">Turn the dial up</button></div>`;
    html += `<section class="card-sec sec-sources"><h3>Sources</h3><ul class="sources">${(s.sources || []).map(x => `<li>${esc(x)}</li>`).join('')}</ul></section>`;
    html += `<div class="card-foot">
      <div class="review ${s.reviewed ? 'ok' : ''}">${s.reviewed ? `Reviewed by ${esc(s.reviewed)}` : 'Not yet reviewed by an attending'}</div>
      ${s.curriculum && s.curriculum.length ? `<div class="curric">${s.curriculum.map(c => `<span>${esc(c)}</span>`).join('')}</div>` : ''}
      ${st.settings.authorMode ? `<div class="author"><button class="btn-ghost" data-action="setloc">Set location to cursor</button><span class="author-note">${ds && ds.landmarks && ds.landmarks[s.anchor] ? 'Location set' : 'No location yet'}</span></div>` : ''}
    </div></div>`;
    this.body.innerHTML = html;
    this.body.scrollTop = 0;
    this.body.querySelector('.back').addEventListener('click', () => { this.store.select(null); });
    this.body.querySelector('[data-action="locate"]').addEventListener('click', () => this.open(id, true));
    this.body.querySelector('[data-action="zoom"]').addEventListener('click', () => { this.open(id, true); this.store.emit('zoomto', id); });
    const t3 = this.body.querySelector('[data-action="toggle3d"]'); if (t3) t3.addEventListener('click', () => this.store.setHidden(id, !this.store.state.hidden.has(id)));
    this.body.querySelectorAll('[data-plane]').forEach(b => b.addEventListener('click', () => { this.open(id, true); this.store.emit('focusplane', b.dataset.plane); }));
    const deeper = this.body.querySelector('[data-action="deeper"]'); if (deeper) deeper.addEventListener('click', () => this.store.setDepth(Math.min(3, depth + 1)));
    const setloc = this.body.querySelector('[data-action="setloc"]'); if (setloc) setloc.addEventListener('click', () => {
      const c = this.store.get('crosshair').slice();
      ds.landmarks[s.anchor] = c; ds.dirty = true;
      this.store.emit('toast', `Location of ${s.name} set to the cursor`);
      this.renderCard(id);
    });
  }
}
