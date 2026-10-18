// Guided tours: scripted walkthroughs that drive the cursor, the 3D camera, highlights and the card.
import { TOURS, STRUCTURE_BY_ID, structureName, resolveAnchor } from './content.js';
import { DEPTH_NAMES } from './state.js';

const esc = (s) => String(s).replace(/[&<>"]/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]));

export class TourRunner {
  constructor(store, barEl, scene3d, panes) {
    this.store = store; this.bar = barEl; this.scene = scene3d; this.panes = panes;
    this.tour = null; this.i = 0;
    this.bar.hidden = true;
    store.on('dataset', () => { if (this.tour) this.apply(); });
  }
  list() { return TOURS; }
  start(id) {
    const t = TOURS.find(x => x.id === id); if (!t) return;
    this.tour = t; this.i = 0;
    this.savedHidden = new Set(this.store.state.hidden);
    this.apply();
  }
  exit() {
    if (!this.tour) return;
    this.tour = null; this.bar.hidden = true;
    if (this.savedHidden) { this.store.state.hidden = new Set(this.savedHidden); this.store.emit('hidden', { id: '*', hidden: null }); }
    this.store.set('tour', null);
  }
  next() { if (!this.tour) return; if (this.i < this.tour.steps.length - 1) { this.i++; this.apply(); } else this.exit(); }
  prev() { if (!this.tour) return; if (this.i > 0) { this.i--; this.apply(); } }
  goto(i) { if (!this.tour) return; this.i = Math.max(0, Math.min(this.tour.steps.length - 1, i)); this.apply(); }
  apply() {
    const st = this.store.state, ds = st.dataset, step = this.tour.steps[this.i];
    // cursor
    let p = null;
    if (Array.isArray(step.focus)) p = step.focus;
    else if (ds) p = resolveAnchor(ds, step.focus);
    const highlight = step.highlight || (typeof step.focus === 'string' ? [step.focus] : []);
    // show highlighted meshes
    for (const id of highlight) if (ds && ds.meshById.has(id)) this.store.setHidden(id, false);
    this.store.set('tour', { tourId: this.tour.id, step: this.i, highlight, plane: step.plane || null }, 'tour');
    if (p) this.store.setCrosshair(p, 'tour');
    const primary = typeof step.focus === 'string' && STRUCTURE_BY_ID.has(step.focus) ? step.focus : (highlight.find(h => STRUCTURE_BY_ID.has(h)) || null);
    this.store.select(primary, { force: true });
    if (step.view && this.scene) this.scene.setView(step.view);
    if (this.scene && p) this.scene.centerOnCursor();
    if (step.plane) this.store.emit('focusplane', step.plane);
    this.renderBar();
  }
  renderBar() {
    const t = this.tour, step = t.steps[this.i], n = t.steps.length;
    this.bar.hidden = false;
    this.bar.innerHTML = `
      <div class="tour-head">
        <span class="tour-title">${esc(t.title)}</span>
        <span class="tour-progress">${this.i + 1} of ${n}</span>
        <button class="btn-ghost" data-act="exit" title="Exit tour (Esc)">Exit</button>
      </div>
      <div class="tour-step">
        <div class="tour-steptitle">${esc(step.title)}</div>
        <div class="tour-text">${esc(step.text)}</div>
      </div>
      <div class="tour-nav">
        <div class="tour-dots">${t.steps.map((s, i) => `<button class="dot-btn ${i === this.i ? 'cur' : i < this.i ? 'done' : ''}" data-goto="${i}" title="${esc(s.title)}"></button>`).join('')}</div>
        <div class="tour-btns">
          <button class="btn-ghost" data-act="prev" ${this.i === 0 ? 'disabled' : ''}>Back</button>
          <button class="btn-primary" data-act="next">${this.i === n - 1 ? 'Finish' : 'Next'}</button>
        </div>
      </div>`;
    this.bar.querySelector('[data-act="exit"]').addEventListener('click', () => this.exit());
    this.bar.querySelector('[data-act="prev"]').addEventListener('click', () => this.prev());
    this.bar.querySelector('[data-act="next"]').addEventListener('click', () => this.next());
    this.bar.querySelectorAll('[data-goto]').forEach(b => b.addEventListener('click', () => this.goto(+b.dataset.goto)));
  }
  pickerHtml(depth) {
    return `<div class="menu-title">Tours</div>` + TOURS.map(t => `
      <button class="menu-item tour-item" data-tour="${t.id}">
        <span class="tour-item-title">${esc(t.title)} <span class="lvl ${t.level > depth ? 'above' : ''}" title="${DEPTH_NAMES[t.level]} level">${DEPTH_NAMES[t.level]}</span></span>
        <span class="tour-item-sub">${t.steps.length} steps. ${esc(t.summary)}</span>
      </button>`).join('');
  }
}
export { structureName };
