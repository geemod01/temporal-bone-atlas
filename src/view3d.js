// Scene3D: structure surfaces plus the three CT slice planes at the crosshair, with a 3D cursor.
import * as THREE from 'three';
import { OrbitControls } from 'three/examples/jsm/controls/OrbitControls.js';
import { structureName, structureColor, STRUCTURE_BY_ID, visibleAtDepth, AIR_IDS, resolveAnchor, isContext } from './content.js';

const ACCENT = new THREE.Color('#e6b042');

export class Scene3D {
  constructor(store, el, panes) {
    this.store = store; this.el = el; this.panes = panes; // panes: {axial, coronal, sagittal} for shared slice canvases
    el.classList.add('pane', 'pane-3d');
    el.dataset.pane = '3d';
    el.innerHTML = `
      <canvas class="gl"></canvas>
      <div class="labels3d"></div>
      <div class="pane-corner tl"><span class="pane-name">3D</span></div>
      <div class="pane-corner tr pane-tools">
        <button class="btn-ghost" data-view="lateral" title="Lateral (surgeon's view)">Lateral</button>
        <button class="btn-ghost" data-view="medial" title="Medial (from the posterior fossa)">Medial</button>
        <button class="btn-ghost" data-view="superior" title="From above (middle fossa)">Superior</button>
        <button class="btn-ghost" data-view="posterior" title="From behind">Posterior</button>
        <button class="btn-ghost" data-action="center" title="Centre the view on the cursor (C)">Centre</button>
        <button class="btn-ghost" data-action="layers" title="Show or hide groups">Layers</button>
      </div>
      <div class="layers-pop" hidden></div>
      <div class="pane-tip" hidden></div>`;
    this.canvas = el.querySelector('canvas.gl');
    this.labelsEl = el.querySelector('.labels3d');
    this.tip = el.querySelector('.pane-tip');
    this.layersPop = el.querySelector('.layers-pop');
    this.renderer = new THREE.WebGLRenderer({ canvas: this.canvas, antialias: true, alpha: false, powerPreference: 'high-performance' });
    this.renderer.setClearColor(0x06080a, 1);
    this.renderer.localClippingEnabled = true;
    this.clipPlane = new THREE.Plane(new THREE.Vector3(0, 0, -1), 0);   // section plane (see updateClip)
    this.renderer.setPixelRatio(Math.min(2, window.devicePixelRatio || 1));
    this.scene = new THREE.Scene();
    this.camera = new THREE.PerspectiveCamera(32, 1, 0.5, 2000);
    this.camera.up.set(0, 0, 1);
    this.controls = new OrbitControls(this.camera, this.canvas);
    this.controls.enableDamping = false;
    this.controls.rotateSpeed = 0.8;
    this.controls.zoomSpeed = 0.9;
    this.controls.addEventListener('change', () => { this.updateClip(); this.requestRender(); });
    this.scene.add(new THREE.HemisphereLight(0xe3e9f0, 0x1b1f25, 0.85));
    this.scene.add(new THREE.AmbientLight(0xffffff, 0.22));
    this.key = new THREE.DirectionalLight(0xffffff, 1.1);
    this.key.position.set(1, 0.6, 1.2);
    this.camera.add(this.key); this.scene.add(this.camera);
    this.meshes = new Map();   // id -> Mesh
    this.planes = {};
    this.labelDivs = new Map();
    this.raycaster = new THREE.Raycaster();
    this.ds = null;
    this.needRender = false;
    this.ro = new ResizeObserver(() => this.resize());
    this.ro.observe(el);
    this.bindEvents();
    store.on('dataset', ds => this.setDataset(ds));
    store.on('crosshair', () => { this.updatePlanes(); this.updateCursor(); this.updateClip(); this.requestRender(); });
    store.on('scrollPlane', () => { this.updateClip(); this.updatePlaneOpacity(); this.requestRender(); });
    store.on('sectionArmed', (on) => { this.updateClip(); this.updatePlaneOpacity(); this.requestRender(); if (on && this.store.get('settings').section3d && !this._sectionHint) { this._sectionHint = true; this.store.emit('toast', 'The 3D model is now sectioned at the slice you scroll; Layers turns this off.'); } });
    store.on('selected', () => this.updateMaterials());
    store.on('hover', () => this.updateMaterials());
    store.on('hidden', () => this.updateVisibility());
    store.on('settings', (e) => { this.updateVisibility(); this.updatePlaneOpacity(); this.updateClip(); if (e.key === 'window' || e.key === '*') this.refreshTextures(); });
    store.on('depth', () => this.updateLabels());
    store.on('tour', () => { this.updateMaterials(); this.updatePlaneOpacity(); });
    store.on('quiz', () => this.updateMaterials());
    // slice textures update when the panes re-render
    for (const k of ['axial', 'coronal', 'sagittal']) panes[k].el.addEventListener('slice', () => { if (this.planes[k]) { this.planes[k].material.map.needsUpdate = true; this.requestRender(); } });
  }

  // ---------- data ----------
  setDataset(ds) {
    for (const m of this.meshes.values()) { this.scene.remove(m); m.geometry.dispose(); m.material.dispose(); }
    this.meshes.clear();
    for (const d of this.labelDivs.values()) d.remove();
    this.labelDivs.clear();
    for (const p of Object.values(this.planes)) { this.scene.remove(p); p.geometry.dispose(); p.material.map.dispose(); p.material.dispose(); }
    this.planes = {};
    if (this.cursor) { this.scene.remove(this.cursor); this.cursor = null; }
    this.ds = ds;
    if (!ds) { this.requestRender(); return; }
    for (const m of ds.meshes) {
      const g = new THREE.BufferGeometry();
      g.setAttribute('position', new THREE.BufferAttribute(m.positions, 3));
      g.setIndex(new THREE.BufferAttribute(m.indices, 1));
      g.computeVertexNormals();
      const air = AIR_IDS.has(m.id), shell = isContext(m.id), membrane = m.id === 'tympanic_membrane';
      const mat = new THREE.MeshStandardMaterial({
        color: new THREE.Color(structureColor(m.id)), roughness: shell ? 0.9 : 0.55, metalness: 0.0,
        transparent: air || shell || membrane, opacity: shell ? 0.16 : air ? 0.22 : membrane ? 0.45 : 1.0, depthWrite: !(air || shell || membrane), side: THREE.DoubleSide
      });
      mat.clippingPlanes = [];
      const mesh = new THREE.Mesh(g, mat);
      mesh.userData.id = m.id;
      mesh.userData.baseOpacity = mat.opacity;
      if (!air && !shell && !membrane) {
        // section cap: the inside walls of a cut closed surface, drawn flat and darker, fill the cut exactly
        const capMat = new THREE.MeshBasicMaterial({ color: new THREE.Color(structureColor(m.id)).multiplyScalar(0.62), side: THREE.BackSide, clippingPlanes: [], polygonOffset: true, polygonOffsetFactor: -2, polygonOffsetUnits: -2 });
        const cap = new THREE.Mesh(g, capMat);
        cap.visible = false; cap.renderOrder = 0;
        mesh.add(cap);
        mesh.userData.cap = cap;
      }
      mesh.renderOrder = shell ? 3 : air ? 2 : 0;
      this.scene.add(mesh);
      this.meshes.set(m.id, mesh);
    }
    this.buildPlanes();
    this.buildCursor();
    this.updateVisibility();
    this.updateMaterials();
    this.fitCamera('lateral');
    this.updateLabels();
    this.requestRender();
  }
  buildPlanes() {
    const vol = this.ds.volume, e = vol.extent, c = vol.center;
    const size = { axial: [e[3] - e[0] + vol.spacing[0], e[4] - e[1] + vol.spacing[1]], coronal: [e[3] - e[0] + vol.spacing[0], e[5] - e[2] + vol.spacing[2]], sagittal: [e[4] - e[1] + vol.spacing[1], e[5] - e[2] + vol.spacing[2]] };
    for (const k of ['axial', 'coronal', 'sagittal']) {
      const tex = new THREE.CanvasTexture(this.panes[k].img);
      tex.flipY = false; tex.minFilter = THREE.LinearFilter; tex.magFilter = THREE.LinearFilter; tex.colorSpace = THREE.SRGBColorSpace;
      const mat = new THREE.MeshBasicMaterial({ map: tex, side: THREE.DoubleSide, transparent: true, opacity: this.store.get('settings').planeOpacity, depthWrite: true });
      const geo = new THREE.PlaneGeometry(size[k][0], size[k][1]);
      const mesh = new THREE.Mesh(geo, mat);
      mesh.matrixAutoUpdate = false;
      mesh.userData.plane = k;
      mesh.renderOrder = 1;
      this.scene.add(mesh);
      this.planes[k] = mesh;
      // a thin frame marks the plane the wheel is moving
      const frame = new THREE.LineSegments(new THREE.EdgesGeometry(geo), new THREE.LineBasicMaterial({ color: 0xe6b042, transparent: true, opacity: 0.85 }));
      frame.matrixAutoUpdate = false; frame.renderOrder = 4; frame.userData.frameOf = k;
      mesh.userData.frame = frame;
      this.scene.add(frame);
    }
    this.volCenter = c;
    this.updatePlanes();
    this.updateClip();
  }
  // Section: everything between the camera and the plane being scrolled is cut away, so scrolling a slice
  // moves a cut through the 3D model exactly as it moves through the CT.
  updateClip() {
    if (!this.ds) return;
    const s = this.store.get('settings');
    const on = !!s.section3d && !!this.store.get('sectionArmed');
    for (const m of this.meshes.values()) {
      const want = on ? [this.clipPlane] : [];
      for (const mat of [m.material, m.userData.cap && m.userData.cap.material]) {
        if (mat && (mat.clippingPlanes || []).length !== want.length) { mat.clippingPlanes = want; mat.needsUpdate = true; }
      }
      if (m.userData.cap) m.userData.cap.visible = on;
    }
    if (!on) return;
    const plane = this.store.get('scrollPlane');
    const a = plane === 'axial' ? 2 : plane === 'coronal' ? 1 : 0;
    const w = this.store.get('crosshair')[a];
    const camA = this.camera.position.getComponent(a);
    const sgn = camA >= w ? 1 : -1;                       // the camera's side of the plane is the one removed
    const n = new THREE.Vector3(); n.setComponent(a, -sgn);
    this.clipPlane.normal.copy(n);
    this.clipPlane.constant = sgn * (w + sgn * 0.08);    // keep the structures lying in the plane itself
  }
  updatePlanes() {
    if (!this.ds || !this.planes.axial) return;
    const ch = this.store.get('crosshair'), c = this.volCenter;
    const X = new THREE.Vector3(1, 0, 0), Y = new THREE.Vector3(0, 1, 0), Z = new THREE.Vector3(0, 0, 1);
    const set = (m, basisX, basisY, basisZ, pos) => { m.matrix.makeBasis(basisX, basisY, basisZ); m.matrix.setPosition(pos.x, pos.y, pos.z); m.matrixWorldNeedsUpdate = true; };
    set(this.planes.axial, X, Y, Z, new THREE.Vector3(c[0], c[1], ch[2]));
    set(this.planes.coronal, X, Z, new THREE.Vector3(0, -1, 0), new THREE.Vector3(c[0], ch[1], c[2]));
    set(this.planes.sagittal, Y, Z, X, new THREE.Vector3(ch[0], c[1], c[2]));
    for (const p of Object.values(this.planes)) if (p.userData.frame) { p.userData.frame.matrix.copy(p.matrix); p.userData.frame.matrixWorldNeedsUpdate = true; }
  }
  updatePlaneOpacity() {
    const s = this.store.get('settings'), tour = this.store.get('tour');
    const active = this.store.get('scrollPlane');
    for (const [k, p] of Object.entries(this.planes)) {
      p.visible = !!s.planes3d;
      if (p.userData.frame) p.userData.frame.visible = !!s.planes3d && !!s.section3d && !!this.store.get('sectionArmed') && k === active;
      p.material.opacity = (tour && tour.plane && tour.plane !== k) ? Math.min(s.planeOpacity, 0.22) : s.planeOpacity;
    }
    this.requestRender();
  }
  refreshTextures() { for (const p of Object.values(this.planes)) p.material.map.needsUpdate = true; this.requestRender(); }
  buildCursor() {
    const g = new THREE.Group();
    const sph = new THREE.Mesh(new THREE.SphereGeometry(0.45, 16, 12), new THREE.MeshBasicMaterial({ color: ACCENT }));
    g.add(sph);
    const lineMat = new THREE.LineBasicMaterial({ color: ACCENT, transparent: true, opacity: 0.8 });
    const L = 3.5;
    for (const d of [[L, 0, 0], [0, L, 0], [0, 0, L]]) {
      const geo = new THREE.BufferGeometry().setFromPoints([new THREE.Vector3(-d[0], -d[1], -d[2]), new THREE.Vector3(d[0], d[1], d[2])]);
      g.add(new THREE.Line(geo, lineMat));
    }
    g.renderOrder = 10;
    this.cursor = g; this.scene.add(g);
    this.updateCursor();
  }
  updateCursor() { if (this.cursor) { const c = this.store.get('crosshair'); this.cursor.position.set(c[0], c[1], c[2]); } }

  // ---------- appearance ----------
  updateVisibility() {
    const st = this.store.state, hidden = st.hidden, s = st.settings;
    for (const [id, m] of this.meshes) {
      if (isContext(id)) m.visible = !!s.boneShell && !hidden.has(id);
      else m.visible = !hidden.has(id);
    }
    this.updatePlaneOpacity();
    this.updateLabels();
    this.requestRender();
  }
  updateMaterials() {
    const st = this.store.state;
    const sel = st.selectedId, hov = st.hoverId;
    const tour = st.tour;
    const focus = tour && tour.highlight ? new Set(tour.highlight) : null;
    const quizHide = st.quiz && st.quiz.hideNames;
    for (const [id, m] of this.meshes) {
      const mat = m.material;
      const isSel = id === sel, isHov = id === hov && !quizHide;
      mat.emissive.copy(isSel ? ACCENT : isHov ? ACCENT : new THREE.Color(0x000000));
      mat.emissiveIntensity = isSel ? 0.55 : isHov ? 0.22 : 0;
      let op = m.userData.baseOpacity;
      const wasTransparent = mat.transparent;
      if (focus && !focus.has(id) && !isSel) { op = Math.min(op, 0.18); mat.transparent = true; mat.depthWrite = false; }
      else if (!AIR_IDS.has(id) && !isContext(id) && id !== 'tympanic_membrane') { mat.transparent = false; mat.depthWrite = true; }
      mat.opacity = op;
      if (wasTransparent !== mat.transparent) mat.needsUpdate = true;
    }
    this.updateLabels();
    this.requestRender();
  }
  updateLabels() {
    const st = this.store.state, mode = st.settings.labels3d;
    const quizHide = st.quiz && st.quiz.hideNames;
    const want = new Set();
    if (mode !== 'off' && !quizHide) {
      for (const [id, m] of this.meshes) {
        if (!m.visible || isContext(id)) continue;
        const def = STRUCTURE_BY_ID.get(id); if (!def) continue;
        if (id === st.selectedId || mode === 'all' || (mode === 'auto' && visibleAtDepth(def, st.depth) && !AIR_IDS.has(id))) want.add(id);
        if (mode === 'selected' && id !== st.selectedId) want.delete(id);
      }
    }
    for (const [id, d] of this.labelDivs) if (!want.has(id)) { d.remove(); this.labelDivs.delete(id); }
    for (const id of want) if (!this.labelDivs.has(id)) {
      const d = document.createElement('div'); d.className = 'label3d'; d.textContent = structureName(id).split(',')[0];
      d.style.setProperty('--c', structureColor(id));
      d.addEventListener('click', () => { this.store.select(id); this.locate(id); });
      this.labelsEl.appendChild(d); this.labelDivs.set(id, d);
    }
    for (const [id, d] of this.labelDivs) d.classList.toggle('sel', id === st.selectedId);
    this.requestRender();
  }
  placeLabels() {
    if (!this.ds) return;
    const w = this.w, h = this.h;
    const v = new THREE.Vector3();
    for (const [id, d] of this.labelDivs) {
      const m = this.ds.meshById.get(id); if (!m) continue;
      v.set(m.centroid[0], m.centroid[1], m.centroid[2]).project(this.camera);
      if (v.z > 1 || v.z < -1) { d.style.display = 'none'; continue; }
      d.style.display = '';
      d.style.transform = `translate(${((v.x + 1) / 2 * w).toFixed(1)}px, ${((1 - v.y) / 2 * h).toFixed(1)}px)`;
    }
  }
  locate(id) {
    const p = resolveAnchor(this.ds, id);
    if (p) this.store.setCrosshair(p, '3d');
  }

  // ---------- camera ----------
  fitCamera(view) {
    if (!this.ds) return;
    const vol = this.ds.volume;
    let e = null;
    for (const [id, m] of this.meshes) {
      if (!m.visible || isContext(id) || AIR_IDS.has(id)) continue;
      const def = STRUCTURE_BY_ID.get(id); if (def && def.group === 'vascular') continue;
      const b = this.ds.meshById.get(id).bbox;
      e = e ? [Math.min(e[0], b[0]), Math.min(e[1], b[1]), Math.min(e[2], b[2]), Math.max(e[3], b[3]), Math.max(e[4], b[4]), Math.max(e[5], b[5])] : b.slice();
    }
    if (!e) e = vol.extent;
    const c = [(e[0] + e[3]) / 2, (e[1] + e[4]) / 2, (e[2] + e[5]) / 2];
    const span = Math.max(e[3] - e[0], e[4] - e[1], e[5] - e[2]);
    const dist = span * 1.45;
    const side = this.ds.side === 'L' ? -1 : 1;
    const dirs = {
      lateral: [side, -0.15, 0.1], medial: [-side, 0.1, 0.1], superior: [0.02 * side, -0.25, 1], inferior: [0.02 * side, 0.25, -1],
      anterior: [0.1 * side, 1, 0.12], posterior: [0.1 * side, -1, 0.12]
    };
    const d = dirs[view] || dirs.lateral;
    const n = Math.hypot(d[0], d[1], d[2]);
    const target = this.controls.target;
    target.set(c[0], c[1], c[2]);
    this.camera.position.set(c[0] + d[0] / n * dist, c[1] + d[1] / n * dist, c[2] + d[2] / n * dist);
    this.camera.near = 0.5; this.camera.far = dist * 6; this.camera.updateProjectionMatrix();
    this.controls.update();
    this.requestRender();
  }
  centerOnCursor() {
    const c = this.store.get('crosshair');
    const off = new THREE.Vector3().subVectors(this.camera.position, this.controls.target);
    this.controls.target.set(c[0], c[1], c[2]);
    this.camera.position.copy(this.controls.target).add(off);
    this.controls.update();
    this.requestRender();
  }
  setView(view) {
    const keepTarget = this.controls.target.clone();
    this.fitCamera(view);
    this.controls.target.copy(keepTarget);
    this.controls.update();
    this.requestRender();
  }

  // ---------- rendering ----------
  resize() {
    const r = this.el.getBoundingClientRect();
    this.w = Math.max(1, Math.floor(r.width)); this.h = Math.max(1, Math.floor(r.height));
    this.renderer.setSize(this.w, this.h, false);
    this.canvas.style.width = this.w + 'px'; this.canvas.style.height = this.h + 'px';
    this.camera.aspect = this.w / this.h; this.camera.updateProjectionMatrix();
    this.requestRender();
  }
  requestRender() {
    if (this.needRender) return;
    this.needRender = true;
    requestAnimationFrame(() => { this.needRender = false; this.render(); });
  }
  render() {
    if (!this.w) return;
    this.renderer.render(this.scene, this.camera);
    this.placeLabels();
  }

  // ---------- interaction ----------
  bindEvents() {
    const el = this.el;
    el.addEventListener('pointerenter', () => this.store.set('activePane', '3d'));
    // the wheel scrolls slices here too, like in the CT panes; Ctrl/Cmd+wheel (and pinch) zooms
    el.addEventListener('wheel', (e) => {
      if (e.ctrlKey || e.metaKey || !this.ds) return;
      e.preventDefault(); e.stopPropagation();
      const dir = Math.sign(e.deltaY) || Math.sign(e.deltaX);
      const pane = this.panes[this.store.get('scrollPlane')] || this.panes.axial;
      if (!this.store.get('sectionArmed')) this.store.set('sectionArmed', true);
      if (dir && pane) pane.stepSlice(dir > 0 ? -1 : 1);
    }, { capture: true, passive: false });
    el.querySelectorAll('[data-view]').forEach(b => b.addEventListener('click', () => this.setView(b.dataset.view)));
    el.querySelector('[data-action="center"]').addEventListener('click', () => this.centerOnCursor());
    el.querySelector('[data-action="layers"]').addEventListener('click', (e) => { e.stopPropagation(); this.toggleLayers(); });
    document.addEventListener('click', (e) => { if (!this.layersPop.hidden && !this.layersPop.contains(e.target)) this.layersPop.hidden = true; });
    let down = null;
    this.canvas.addEventListener('pointerdown', e => { down = { x: e.clientX, y: e.clientY, b: e.button, t: performance.now() }; this.tip.hidden = true; });
    this.canvas.addEventListener('pointerup', e => {
      if (!down) return;
      const moved = Math.hypot(e.clientX - down.x, e.clientY - down.y) > 3;
      if (!moved && down.b === 0) this.pick(e, true);
      down = null;
    });
    let lastHover = 0;
    this.canvas.addEventListener('pointermove', e => {
      if (down) return;
      const now = performance.now(); if (now - lastHover < 40) return; lastHover = now;
      this.pick(e, false);
    });
    this.canvas.addEventListener('pointerleave', () => { this.tip.hidden = true; this.store.hover(null); });
  }
  pick(e, click) {
    if (!this.ds) return;
    const r = this.canvas.getBoundingClientRect();
    const nd = new THREE.Vector2(((e.clientX - r.left) / r.width) * 2 - 1, -((e.clientY - r.top) / r.height) * 2 + 1);
    this.raycaster.setFromCamera(nd, this.camera);
    const st = this.store.state;
    const quizHide = st.quiz && st.quiz.hideNames;
    const candidates = [];
    for (const m of this.meshes.values()) if (m.visible && !isContext(m.userData.id) && m.material.opacity > 0.3) candidates.push(m);
    if (st.settings.boneShell) for (const m of this.meshes.values()) if (isContext(m.userData.id) && m.visible) candidates.push(m);
    if (st.settings.planes3d) for (const p of Object.values(this.planes)) candidates.push(p);
    const hits = this.raycaster.intersectObjects(candidates, false);
    if (!hits.length) { if (!click) { this.store.hover(null); this.tip.hidden = true; } return; }
    const h = hits[0];
    const id = h.object.userData.id;
    if (click) {
      this.store.setCrosshair([h.point.x, h.point.y, h.point.z], '3d');
      if (id && STRUCTURE_BY_ID.has(id) && !(st.quiz && st.quiz.active)) this.store.select(id);
      else if (h.object.userData.plane && this.ds.labels && st.settings.clickSelects && !(st.quiz && st.quiz.active)) {
        const lid = this.ds.labelAt([h.point.x, h.point.y, h.point.z]);
        if (lid && STRUCTURE_BY_ID.has(lid)) this.store.select(lid);
      }
      this.store.emit('paneclick', { plane: '3d' });
    } else {
      let label = null;
      if (id && STRUCTURE_BY_ID.has(id)) label = id;
      else if (h.object.userData.plane && this.ds.labels) { const lid = this.ds.labelAt([h.point.x, h.point.y, h.point.z]); if (lid && STRUCTURE_BY_ID.has(lid)) label = lid; }
      if (label && !quizHide) {
        this.store.hover(label);
        this.tip.textContent = structureName(label); this.tip.hidden = false;
        this.tip.style.left = Math.min(e.clientX - r.left + 14, r.width - 160) + 'px'; this.tip.style.top = (e.clientY - r.top + 16) + 'px';
      } else { this.store.hover(null); this.tip.hidden = true; }
    }
  }
  toggleLayers() {
    const pop = this.layersPop;
    if (!pop.hidden) { pop.hidden = true; return; }
    const st = this.store.state;
    const groups = [
      { key: 'inner', name: 'Inner ear', ids: [...this.meshes.keys()].filter(id => (STRUCTURE_BY_ID.get(id) || {}).group === 'inner') },
      { key: 'facial', name: 'Facial nerve', ids: [...this.meshes.keys()].filter(id => (STRUCTURE_BY_ID.get(id) || {}).group === 'facial') },
      { key: 'ossicles', name: 'Ossicles and membrane', ids: ['malleus', 'incus', 'stapes', 'tympanic_membrane', 'stapedius', 'tensor_tympani', 'pyramidal_eminence', 'cochleariform_process', 'scutum'].filter(id => this.meshes.has(id)) },
      { key: 'vascular', name: 'Vessels', ids: [...this.meshes.keys()].filter(id => (STRUCTURE_BY_ID.get(id) || {}).group === 'vascular') },
      { key: 'air', name: 'Air spaces', ids: [...this.meshes.keys()].filter(id => AIR_IDS.has(id)) },
      { key: 'bone', name: 'Bone, dura and surfaces', ids: ['tegmen', 'petrous_apex', 'tmj', 'styloid', 'digastric_ridge'].filter(id => this.meshes.has(id)) }
    ];
    pop.innerHTML = `<div class="layers-title">Layers</div>` + groups.map(g => {
      const on = g.ids.some(id => !st.hidden.has(id));
      return `<label class="layer-row"><input type="checkbox" data-group="${g.key}" ${on ? 'checked' : ''}><span>${g.name}</span></label>`;
    }).join('') +
      `<label class="layer-row"><input type="checkbox" data-setting="boneShell" ${st.settings.boneShell ? 'checked' : ''}><span>Bone and dura (context surfaces)</span></label>` +
      `<label class="layer-row"><input type="checkbox" data-setting="section3d" ${st.settings.section3d ? 'checked' : ''}><span>Section the model at the slice being scrolled</span></label>` +
      `<label class="layer-row"><input type="checkbox" data-setting="planes3d" ${st.settings.planes3d ? 'checked' : ''}><span>CT slice planes</span></label>` +
      `<label class="layer-row range"><span>Plane opacity</span><input type="range" min="0.2" max="1" step="0.05" value="${st.settings.planeOpacity}" data-setting="planeOpacity"></label>`;
    pop.hidden = false;
    pop.querySelectorAll('input[data-group]').forEach(inp => inp.addEventListener('change', () => {
      const g = groups.find(x => x.key === inp.dataset.group);
      for (const id of g.ids) this.store.setHidden(id, !inp.checked);
    }));
    pop.querySelectorAll('input[data-setting]').forEach(inp => inp.addEventListener('input', () => {
      const k = inp.dataset.setting;
      this.store.setting(k, inp.type === 'checkbox' ? inp.checked : parseFloat(inp.value));
    }));
  }
}
