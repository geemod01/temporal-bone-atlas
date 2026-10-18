// Knowledge graph: structure cards, tours and quiz sets, plus group metadata and depth gating.
import inner from '../content/structures_inner.json';
import facial from '../content/structures_facial.json';
import middle from '../content/structures_middle.json';
import vascular from '../content/structures_vascular_landmarks.json';
import toursJson from '../content/tours.json';
import quizJson from '../content/quiz.json';

export const GROUPS = {
  inner: { name: 'Inner ear', order: 1, color: '#52c7bd' },
  facial: { name: 'Facial nerve', order: 2, color: '#f0c54a' },
  middle: { name: 'Middle ear and mastoid spaces', order: 3, color: '#8ea5bc' },
  vascular: { name: 'Vessels', order: 4, color: '#d9534f' },
  mastoid: { name: 'Bone, dura and surfaces', order: 5, color: '#c9b99a' },
  landmark: { name: 'Landmarks and variants', order: 6, color: '#a0a7ae' }
};

// Which structures are air spaces (drawn translucent in 3D) and which are off by default.
export const AIR_IDS = new Set(['eac', 'tympanic_cavity', 'epitympanum', 'aditus', 'antrum', 'mastoid_cells', 'eustachian_tube', 'sinus_tympani', 'facial_recess', 'prussak_space']);
export const DEFAULT_HIDDEN = new Set(['eac', 'mastoid_cells', 'tympanic_cavity', 'epitympanum', 'aditus', 'antrum', 'eustachian_tube', 'tegmen', 'petrous_apex', 'tmj', 'styloid', 'digastric_ridge', 'emissary_vein', 'bone_shell', 'prussak_space', 'stapedius', 'endolymphatic_sac']);

export const STRUCTURES = [...inner, ...facial, ...middle, ...vascular].map(s => ({ ...s, mesh: s.mesh !== false, anchor: s.anchor || s.id }));
export const STRUCTURE_BY_ID = new Map(STRUCTURES.map(s => [s.id, s]));
export const TOURS = toursJson;
export const QUIZ = quizJson;

export function structureName(id) {
  const s = STRUCTURE_BY_ID.get(id);
  if (s) return s.name;
  if (id === 'bone_shell') return 'Bone (context surface)';
  return id.replace(/_/g, ' ');
}
export function structureColor(id) {
  const s = STRUCTURE_BY_ID.get(id);
  if (s && s.color) return s.color;
  if (id === 'bone_shell') return '#cfc3b0';
  return '#9aa3ad';
}

// Depth gating: 1 junior, 2 senior, 3 fellow.
export function visibleAtDepth(s, depth) { return (s.level || 1) <= depth; }

export function groupedStructures(depth, showAll, filter) {
  const q = (filter || '').trim().toLowerCase();
  const groups = new Map();
  for (const s of STRUCTURES) {
    if (!showAll && !visibleAtDepth(s, depth)) continue;
    if (q) {
      const hay = [s.name, ...(s.aliases || []), s.id.replace(/_/g, ' ')].join(' ').toLowerCase();
      if (!hay.includes(q)) continue;
    }
    if (!groups.has(s.group)) groups.set(s.group, []);
    groups.get(s.group).push(s);
  }
  return [...groups.entries()].sort((a, b) => GROUPS[a[0]].order - GROUPS[b[0]].order).map(([g, items]) => ({ group: g, meta: GROUPS[g], items }));
}

export function searchStructures(q) {
  const s = (q || '').trim().toLowerCase();
  if (!s) return [];
  return STRUCTURES.filter(x => [x.name, ...(x.aliases || []), x.id.replace(/_/g, ' ')].join(' ').toLowerCase().includes(s)).slice(0, 12);
}

// Which card sections appear at which depth
export const SECTION_DEPTH = {
  summary: 1, find: 1, relations: 1, surgical: 1, sources: 1,
  variants: 2, pitfalls: 2, measurements: 2, classification: 2,
  fellow: 3, pathology: 3
};
export function sectionVisible(section, depth) { return (SECTION_DEPTH[section] || 1) <= depth; }

// Resolve where the cursor should go for a structure on the current dataset:
// its own mesh or landmark, then its declared anchor, then listed fallbacks (e.g. a whole-nerve mesh).
export function resolveAnchor(ds, id) {
  if (!ds || !id) return null;
  const def = STRUCTURE_BY_ID.get(id);
  const tried = new Set();
  const tryId = (x) => { if (!x || tried.has(x)) return null; tried.add(x); return ds.anchorOf(x); };
  let p = tryId(id);
  if (!p && def) p = tryId(def.anchor);
  if (!p && def && def.fallback) for (const f of def.fallback) { p = tryId(f); if (p) break; const fd = STRUCTURE_BY_ID.get(f); if (fd && fd.anchor) { p = tryId(fd.anchor); if (p) break; } }
  return p;
}
export function resolveBounds(ds, id) {
  if (!ds || !id) return null;
  const def = STRUCTURE_BY_ID.get(id);
  let b = ds.boundsOf(id);
  if (!b && def) b = ds.boundsOf(def.anchor);
  if (!b && def && def.fallback) for (const f of def.fallback) { b = ds.boundsOf(f); if (b) break; }
  return b;
}
