// Tiny observable store. Everything the four panes and the panel agree on lives here.
const DEFAULT_SETTINGS = {
  layout: 'grid',          // grid | three | slices | single
  maximized: null,         // pane id when layout === 'single'
  window: { w: 4000, l: 700 },
  windowPreset: 'bone',    // bone | soft | custom
  mirror: false,           // display a left ear as a right ear (or vice versa)
  sliceLabels: 'selected', // off | selected | auto | all
  labels3d: 'selected',    // off | selected | auto | all
  planes3d: true,
  planeOpacity: 0.6,
  boneShell: false,
  textSize: 'm',           // s | m | l
  reducedMotion: null,     // null = follow system
  authorMode: false,
  clickSelects: true,      // clicking a labelled voxel in 2D selects that structure
  panelOpen: true,
  theme: 'dark'
};

export class Store {
  constructor() {
    this.listeners = new Map();
    this.state = {
      dataset: null,
      crosshair: [0, 0, 0],
      selectedId: null,
      hoverId: null,
      depth: 1,                 // 1 junior, 2 senior, 3 fellow
      settings: { ...DEFAULT_SETTINGS },
      hidden: new Set(),        // mesh ids hidden in 3D
      tour: null,               // { tourId, step }
      quiz: null,               // active quiz session
      activePane: 'axial',
      showAllStructures: false
    };
    this.loadSettings();
  }
  on(evt, fn) {
    if (!this.listeners.has(evt)) this.listeners.set(evt, new Set());
    this.listeners.get(evt).add(fn);
    return () => this.listeners.get(evt).delete(fn);
  }
  emit(evt, payload) {
    const l = this.listeners.get(evt);
    if (l) for (const fn of [...l]) fn(payload);
    const all = this.listeners.get('*');
    if (all) for (const fn of [...all]) fn(evt, payload);
  }
  get(k) { return this.state[k]; }
  set(k, v, evt) {
    this.state[k] = v;
    this.emit(evt || k, v);
  }
  setCrosshair(p, source) {
    const s = this.state;
    if (s.dataset) {
      const e = s.dataset.volume.extent;
      p = [Math.min(e[3], Math.max(e[0], p[0])), Math.min(e[4], Math.max(e[1], p[1])), Math.min(e[5], Math.max(e[2], p[2]))];
    }
    s.crosshair = p;
    this.emit('crosshair', { p, source });
  }
  select(id, opts = {}) {
    const s = this.state;
    if (s.selectedId === id && !opts.force) { this.emit('selected', id); return; }
    s.selectedId = id;
    this.emit('selected', id);
  }
  hover(id) {
    if (this.state.hoverId === id) return;
    this.state.hoverId = id;
    this.emit('hover', id);
  }
  setDepth(d) { this.state.depth = d; this.saveSettings(); this.emit('depth', d); }
  setting(k, v) {
    this.state.settings[k] = v;
    this.saveSettings();
    this.emit('settings', { key: k, value: v });
  }
  setHidden(id, hidden) {
    const h = this.state.hidden;
    if (hidden) h.add(id); else h.delete(id);
    this.emit('hidden', { id, hidden });
  }
  loadSettings() {
    try {
      const raw = localStorage.getItem('tba.settings.v1');
      if (raw) {
        const saved = JSON.parse(raw);
        this.state.settings = { ...DEFAULT_SETTINGS, ...(saved.settings || {}) };
        if (saved.depth) this.state.depth = saved.depth;
      }
    } catch (e) { /* storage unavailable: run with defaults */ }
  }
  saveSettings() {
    try { localStorage.setItem('tba.settings.v1', JSON.stringify({ settings: this.state.settings, depth: this.state.depth })); } catch (e) { /* ignore */ }
  }
  resetSettings() {
    this.state.settings = { ...DEFAULT_SETTINGS };
    this.saveSettings();
    this.emit('settings', { key: '*', value: null });
  }
}

export const DEPTH_NAMES = { 1: 'Junior', 2: 'Senior', 3: 'Fellow' };
export const PRESETS = {
  bone: { w: 4000, l: 700 },
  soft: { w: 400, l: 40 },
  stapes: { w: 2500, l: 900 }
};
