// Quiz: point-and-identify, name-the-highlight, find-the-level and multiple choice, run inside the panel.
import { QUIZ, STRUCTURES, STRUCTURE_BY_ID, structureName, resolveAnchor, resolveBounds } from './content.js';
import { DEPTH_NAMES } from './state.js';

const esc = (s) => String(s).replace(/[&<>"]/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]));
const PLANE_AXIS = { axial: 2, coronal: 1, sagittal: 0 };
const PLANE_NAME = { axial: 'axial', coronal: 'coronal', sagittal: 'sagittal' };

function shuffle(a) { const b = a.slice(); for (let i = b.length - 1; i > 0; i--) { const j = Math.floor(Math.random() * (i + 1)); [b[i], b[j]] = [b[j], b[i]]; } return b; }

export class QuizRunner {
  constructor(store, panel, scene3d) {
    this.store = store; this.panel = panel; this.scene = scene3d;
    this.session = null;
    this.root = document.createElement('div');
    this.root.className = 'quiz';
    store.on('paneclick', () => { if (this.session && this.current && this.current.type === 'identify' && !this.answered) this.updateIdentifyHint(); });
  }
  list() { return QUIZ.sets; }
  pickerHtml(depth) {
    return `<div class="menu-title">Quiz</div>` + QUIZ.sets.map(s => `
      <button class="menu-item tour-item" data-quiz="${s.id}">
        <span class="tour-item-title">${esc(s.title)} <span class="lvl ${s.level > depth ? 'above' : ''}">${DEPTH_NAMES[s.level]}</span></span>
        <span class="tour-item-sub">${s.questions.length} questions. ${esc(s.description)}</span>
      </button>`).join('');
  }
  start(setId) {
    const set = QUIZ.sets.find(s => s.id === setId); if (!set) return;
    const ds = this.store.get('dataset');
    const qs = set.questions.filter(q => {
      if (q.type === 'mcq') return true;
      // need an anchor for the target
      return ds && resolveAnchor(ds, q.target);
    });
    this.session = { set, qs, i: 0, results: [], started: Date.now() };
    this.store.set('quiz', { active: true, setId, hideNames: false }, 'quiz');
    this.store.select(null);
    this.show();
  }
  get current() { return this.session ? this.session.qs[this.session.i] : null; }
  exit() {
    this.session = null;
    this.store.set('quiz', null, 'quiz');
    this.panel.exitCustom();
    this.store.select(null);
  }
  targetDef(q) { return STRUCTURE_BY_ID.get(q.target); }
  anchor(q) { return resolveAnchor(this.store.get('dataset'), q.target); }
  show() {
    const s = this.session, q = this.current;
    this.answered = false; this.qStart = Date.now();
    const hideNames = q.type === 'name' || q.type === 'identify' || q.type === 'level';
    this.store.set('quiz', { active: true, setId: s.set.id, hideNames }, 'quiz');
    const head = `<div class="quiz-head"><span class="quiz-title">${esc(s.set.title)}</span><span class="quiz-progress">${s.i + 1} of ${s.qs.length}</span><button class="btn-ghost" data-act="exit">Exit</button></div>`;
    let body = '';
    if (q.type === 'identify') {
      body = `<div class="quiz-q">Find the <strong>${esc(structureName(q.target))}</strong>. Click it in any view (2D or 3D) so the cursor sits on it, then check.</div>
        <div class="quiz-hint" data-hint></div>
        <div class="quiz-actions"><button class="btn-primary" data-act="check">Check cursor</button></div>`;
    } else if (q.type === 'name') {
      const p = this.anchor(q);
      if (p) this.store.setCrosshair(p, 'quiz');
      this.store.select(q.target, { force: true });
      if (this.scene) this.scene.centerOnCursor();
      const pool = STRUCTURES.filter(x => x.id !== q.target && x.group === this.targetDef(q)?.group);
      const alt = shuffle(pool.length >= 3 ? pool : STRUCTURES.filter(x => x.id !== q.target)).slice(0, 3).map(x => x.id);
      this.options = shuffle([q.target, ...alt]);
      body = `<div class="quiz-q">The highlighted structure (amber in every view) is:</div>
        <div class="quiz-opts">${this.options.map((id, i) => `<button class="opt" data-opt="${i}">${esc(structureName(id))}</button>`).join('')}</div>`;
    } else if (q.type === 'level') {
      body = `<div class="quiz-q">Scroll the <strong>${PLANE_NAME[q.plane]}</strong> view to the slice that best shows the <strong>${esc(structureName(q.target))}</strong>, then check.</div>
        <div class="quiz-actions"><button class="btn-primary" data-act="check">Check slice</button></div>`;
    } else {
      this.options = q.options.map((o, i) => ({ o, i }));
      if (q.focus) { const p = resolveAnchor(this.store.get('dataset'), q.focus); if (p) this.store.setCrosshair(p, 'quiz'); }
      body = `<div class="quiz-q">${esc(q.question)}</div>
        <div class="quiz-opts">${shuffle(this.options).map(x => `<button class="opt" data-opt="${x.i}">${esc(x.o)}</button>`).join('')}</div>`;
    }
    this.root.innerHTML = head + body + `<div class="quiz-feedback" data-fb hidden></div><div class="quiz-nav" hidden><button class="btn-primary" data-act="next">${s.i === s.qs.length - 1 ? 'See results' : 'Next'}</button></div>`;
    this.panel.setCustom(this.root);
    this.root.querySelector('[data-act="exit"]').addEventListener('click', () => this.exit());
    const chk = this.root.querySelector('[data-act="check"]'); if (chk) chk.addEventListener('click', () => this.check());
    this.root.querySelectorAll('[data-opt]').forEach(b => b.addEventListener('click', () => this.choose(+b.dataset.opt, b)));
    this.root.querySelector('[data-act="next"]').addEventListener('click', () => this.next());
    this.updateIdentifyHint();
  }
  updateIdentifyHint() {
    const h = this.root.querySelector('[data-hint]'); if (!h) return;
    const c = this.store.get('crosshair');
    h.textContent = `Cursor at x ${c[0].toFixed(1)}, y ${c[1].toFixed(1)}, z ${c[2].toFixed(1)} mm`;
  }
  check() {
    if (this.answered) return;
    const q = this.current, ds = this.store.get('dataset'), c = this.store.get('crosshair');
    let ok = false, detail = '';
    if (q.type === 'identify') {
      const lab = ds.labelAt(c);
      if (lab && lab === q.target) ok = true;
      else {
        const a = this.anchor(q);
        const dist = a ? Math.hypot(c[0] - a[0], c[1] - a[1], c[2] - a[2]) : Infinity;
        const tol = ds.meshById.has(q.target) ? 2.5 : 3.5;
        ok = dist <= tol;
        if (!ok) detail = lab && lab !== q.target ? `The cursor is on the ${structureName(lab)}, ${dist.toFixed(1)} mm away.` : (isFinite(dist) ? `The cursor is ${dist.toFixed(1)} mm from the ${structureName(q.target)}.` : '');
      }
    } else if (q.type === 'level') {
      const b = resolveBounds(ds, q.target), a = this.anchor(q), ax = PLANE_AXIS[q.plane];
      if (b) { const pad = 0.6; ok = c[ax] >= b.min[ax] - pad && c[ax] <= b.max[ax] + pad; detail = ok ? '' : `The structure spans ${b.min[ax].toFixed(1)} to ${b.max[ax].toFixed(1)} mm on this axis; your slice is at ${c[ax].toFixed(1)} mm.`; }
      else if (a) { ok = Math.abs(c[ax] - a[ax]) <= 2.0; detail = ok ? '' : `The structure is centred at ${a[ax].toFixed(1)} mm on this axis.`; }
    }
    this.finish(ok, detail);
  }
  choose(i, btn) {
    if (this.answered) return;
    const q = this.current;
    let ok;
    if (q.type === 'name') ok = this.options[i] === q.target;
    else ok = i === q.answer;
    this.root.querySelectorAll('.opt').forEach(b => {
      const idx = +b.dataset.opt;
      const isRight = q.type === 'name' ? this.options[idx] === q.target : idx === q.answer;
      b.classList.toggle('right', isRight);
      b.classList.toggle('wrong', b === btn && !ok);
      b.disabled = true;
    });
    this.finish(ok, q.explain || '');
  }
  finish(ok, detail) {
    this.answered = true;
    const q = this.current, s = this.session;
    const ms = Date.now() - this.qStart;
    s.results.push({ index: s.i, type: q.type, target: q.target || q.focus || null, question: q.question || null, correct: ok, ms });
    const fb = this.root.querySelector('[data-fb]');
    fb.hidden = false;
    fb.className = 'quiz-feedback ' + (ok ? 'ok' : 'bad');
    const name = q.target ? structureName(q.target) : '';
    fb.innerHTML = (ok ? `<strong>Correct.</strong> ` : `<strong>Not quite.</strong> `) + esc(detail || '') +
      ((q.type === 'identify' || q.type === 'level' || q.type === 'name') ? ` <button class="btn-link" data-act="showme">Show me the ${esc(name)}</button>` : '') +
      (q.type !== 'mcq' && q.target ? ` <button class="btn-link" data-act="card">Open card</button>` : (q.focus ? ` <button class="btn-link" data-act="card">Open related card</button>` : ''));
    this.store.set('quiz', { active: true, setId: s.set.id, hideNames: false }, 'quiz');
    const sm = fb.querySelector('[data-act="showme"]'); if (sm) sm.addEventListener('click', () => { const p = this.anchor(q); if (p) this.store.setCrosshair(p, 'quiz'); this.store.select(q.target, { force: true }); if (this.scene) this.scene.centerOnCursor(); this.panel.setCustom(this.root); });
    const cd = fb.querySelector('[data-act="card"]'); if (cd) cd.addEventListener('click', () => { const id = q.target || q.focus; this.pausedRoot = this.root; this.store.set('quiz', { active: true, setId: s.set.id, hideNames: false, paused: true }, 'quiz'); this.panel.mode = 'list'; this.store.select(id, { force: true }); this.injectReturn(); });
    this.root.querySelector('.quiz-nav').hidden = false;
    const a = this.root.querySelector('.quiz-actions'); if (a) a.hidden = true;
  }
  injectReturn() {
    // Add a "Back to quiz" control on top of the card the user opened
    setTimeout(() => {
      const card = this.panel.body.querySelector('.card');
      if (!card) return;
      const b = document.createElement('button'); b.className = 'btn-primary back-to-quiz'; b.textContent = 'Back to the quiz';
      b.addEventListener('click', () => this.panel.setCustom(this.root));
      card.prepend(b);
    }, 0);
  }
  next() {
    const s = this.session;
    if (s.i < s.qs.length - 1) { s.i++; this.show(); } else this.results();
  }
  results() {
    const s = this.session;
    const n = s.results.length, right = s.results.filter(r => r.correct).length;
    const pct = n ? Math.round(100 * right / n) : 0;
    this.store.set('quiz', { active: true, setId: s.set.id, hideNames: false }, 'quiz');
    this.store.select(null);
    this.root.innerHTML = `<div class="quiz-head"><span class="quiz-title">${esc(s.set.title)}</span><button class="btn-ghost" data-act="exit">Close</button></div>
      <div class="quiz-score"><div class="big">${pct}%</div><div>${right} of ${n} correct</div></div>
      <ul class="quiz-list">${s.results.map(r => `<li class="${r.correct ? 'ok' : 'bad'}"><span>${esc(r.target ? structureName(r.target) : (r.question || '').slice(0, 60))}</span><span>${r.correct ? 'correct' : 'missed'} in ${(r.ms / 1000).toFixed(0)} s</span></li>`).join('')}</ul>
      <div class="quiz-actions"><button class="btn-ghost" data-act="export">Download results (JSON)</button><button class="btn-ghost" data-act="again">Run again</button></div>
      <p class="quiz-note">Results include per-question timing so they can be used as a study instrument. Nothing is sent anywhere; the file downloads to your computer.</p>`;
    this.panel.setCustom(this.root);
    this.root.querySelector('[data-act="exit"]').addEventListener('click', () => this.exit());
    this.root.querySelector('[data-act="again"]').addEventListener('click', () => this.start(s.set.id));
    this.root.querySelector('[data-act="export"]').addEventListener('click', () => this.export());
  }
  export() {
    const s = this.session, st = this.store.state;
    const payload = { app: 'Temporal Bone Atlas', set: s.set.id, title: s.set.title, dataset: st.dataset ? st.dataset.name : null, depth: DEPTH_NAMES[st.depth], started: new Date(s.started).toISOString(), finished: new Date().toISOString(), results: s.results, score: s.results.filter(r => r.correct).length, total: s.results.length };
    const blob = new Blob([JSON.stringify(payload, null, 2)], { type: 'application/json' });
    const a = document.createElement('a'); a.href = URL.createObjectURL(blob); a.download = `tba-quiz-${s.set.id}-${new Date().toISOString().slice(0, 19).replace(/[:T]/g, '-')}.json`; a.click();
    setTimeout(() => URL.revokeObjectURL(a.href), 2000);
  }
}
