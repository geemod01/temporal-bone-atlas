#!/usr/bin/env python3
"""
Synthetic RIGHT temporal bone phantom for the Temporal Bone Atlas.

This is NOT patient anatomy. It is a procedurally generated volume whose
structures have the correct topology and spatial relationships (facial nerve
segments relative to the oval window and lateral canal, cochlea anterior to the
vestibule, sigmoid sinus posterior to the mastoid cells, jugular bulb below the
hypotympanum, carotid canal anterior to the cochlea, etc.) so that the viewer,
cards, tours and quiz can be evaluated before real imaging (OpenEar) is loaded.

Outputs (default ./phantom and ./dist):
    phantom/volume.nii.gz      CT-like int16 volume, RAS, 0.375 mm isotropic
    phantom/labels.nii.gz      uint8 label volume (same grid)
    phantom/meshes/<id>.stl    surface per structure (RAS mm, binary STL)
    phantom/manifest.json      label ids, names, landmarks
    dist/phantom.tba           the single data pack the app loads

Coordinate frame: RAS millimetres. Vestibule centre at the origin.
+x lateral (right ear), +y anterior, +z superior.
"""
import json
import math
import os
import sys

import numpy as np
from scipy import ndimage as ndi

sys.path.insert(0, os.path.dirname(__file__))
from tbapack import write_pack, delta_encode_int16  # noqa: E402

try:
    import nibabel as nib
except ImportError:  # optional
    nib = None
try:
    from skimage import measure
except ImportError:
    measure = None
try:
    import fast_simplification
except ImportError:
    fast_simplification = None
try:
    import trimesh
except ImportError:
    trimesh = None

RNG = np.random.default_rng(7)

# --------------------------------------------------------------------------
# Grid definitions
# --------------------------------------------------------------------------
FOV = 48.0                 # mm cube
N_CT = 128                 # CT grid (0.375 mm)
N_LAB = 256                # label grid (0.1875 mm) used for mesh extraction
ORIGIN = np.array([-26.0, -24.0, -24.0], dtype=np.float32)   # RAS mm of voxel (0,0,0)
H_CT = FOV / N_CT
H_LAB = FOV / N_LAB

# --------------------------------------------------------------------------
# Structure table: id -> (label, name, group, HU, mesh?)
#   group drives default colour/visibility in the app (content json overrides)
# --------------------------------------------------------------------------
STRUCTS = [
    # id, name, HU, extract mesh
    ("eac", "External auditory canal", -1000, True),
    ("tympanic_cavity", "Tympanic cavity (meso- and hypotympanum)", -1000, True),
    ("epitympanum", "Epitympanum (attic)", -1000, True),
    ("aditus", "Aditus ad antrum", -1000, True),
    ("antrum", "Mastoid antrum", -1000, True),
    ("mastoid_cells", "Mastoid air cells", -1000, True),
    ("eustachian_tube", "Eustachian tube (bony portion)", -1000, True),
    ("sinus_tympani", "Sinus tympani", -1000, True),
    ("facial_recess", "Facial recess", -1000, True),
    ("prussak_space", "Prussak's space", -1000, True),
    ("middle_fossa", "Middle cranial fossa (dura/temporal lobe)", 35, False),
    ("posterior_fossa", "Posterior cranial fossa (dura/cerebellum)", 25, False),
    ("tmj", "Mandibular condyle (TMJ)", 1300, True),
    ("petrous_apex", "Petrous apex (marrow)", 160, True),
    ("tegmen", "Tegmen tympani / mastoideum", 1700, True),
    ("digastric_ridge", "Digastric ridge", 1750, True),
    ("styloid", "Styloid process", 1500, True),
    ("sigmoid_sinus", "Sigmoid sinus", 60, True),
    ("jugular_bulb", "Jugular bulb", 60, True),
    ("emissary_vein", "Mastoid emissary vein", 60, True),
    ("carotid_canal", "Carotid canal (petrous ICA)", 70, True),
    ("iac", "Internal auditory canal", 12, True),
    ("cochlea", "Cochlea", 18, True),
    ("vestibule", "Vestibule", 18, True),
    ("scc_lateral", "Lateral semicircular canal", 18, True),
    ("scc_superior", "Superior semicircular canal", 18, True),
    ("scc_posterior", "Posterior semicircular canal", 18, True),
    ("vestibular_aqueduct", "Vestibular aqueduct", 15, True),
    ("cochlear_aqueduct", "Cochlear aqueduct", 15, True),
    ("endolymphatic_sac", "Endolymphatic sac", 35, True),
    ("round_window", "Round window membrane", 45, True),
    ("fn_meatal", "Facial nerve, meatal segment", 42, True),
    ("fn_labyrinthine", "Facial nerve, labyrinthine segment", 42, True),
    ("geniculate", "Geniculate ganglion", 44, True),
    ("gspn", "Greater superficial petrosal nerve", 42, True),
    ("fn_tympanic", "Facial nerve, tympanic segment", 42, True),
    ("fn_mastoid", "Facial nerve, mastoid segment", 42, True),
    ("chorda_tympani", "Chorda tympani", 42, True),
    ("stylomastoid_foramen", "Stylomastoid foramen", 40, True),
    ("tensor_tympani", "Tensor tympani muscle", 55, True),
    ("stapedius", "Stapedius tendon", 50, True),
    ("tympanic_membrane", "Tympanic membrane", 45, True),
    ("malleus", "Malleus", 1900, True),
    ("incus", "Incus", 1900, True),
    ("stapes", "Stapes", 1850, True),
    ("pyramidal_eminence", "Pyramidal eminence", 1800, True),
    ("cochleariform_process", "Cochleariform process", 1800, True),
    ("scutum", "Scutum", 1800, True),
]
LABEL_OF = {sid: i + 1 for i, (sid, _, _, _) in enumerate(STRUCTS)}
NAME_OF = {sid: n for sid, n, _, _ in STRUCTS}
HU_OF = {sid: hu for sid, _, hu, _ in STRUCTS}
MESH_OF = {sid: m for sid, _, _, m in STRUCTS}

# Point landmarks for card-only structures (RAS mm)
LANDMARKS = {
    "oval_window": [3.25, 0.5, 1.2],
    "promontory": [4.6, 4.2, -2.4],
    "hypotympanum": [7.4, 1.5, -5.5],
    "mesotympanum": [7.6, 1.2, -1.0],
    "fossa_incudis": [7.3, -3.3, 3.9],
    "second_genu": [5.4, -3.6, 0.2],
    "fundus_iac": [-4.5, 2.8, 1.6],
    "porus_acusticus": [-21.0, 1.0, 1.2],
    "bill_bar": [-5.0, 3.2, 2.6],
    "transverse_crest": [-5.0, 2.8, 1.6],
    "cochlear_aperture": [-2.6, 4.2, -0.4],
    "modiolus": [1.35, 5.95, 0.55],
    "common_crus": [-1.0, -3.6, 2.6],
    "solid_angle": [0.6, -3.2, 2.2],
    "macewen_triangle": [13.8, -4.2, 4.2],
    "sinodural_angle": [5.5, -17.8, 9.0],
    "trautmann_triangle": [-0.5, -14.0, 3.0],
    "donaldson_line": [-3.0, -8.0, 0.4],
    "arcuate_eminence": [0.3, -0.8, 8.6],
    "mastoid_tip": [9.0, -12.0, -21.0],
    "carotid_genu": [-3.5, 11.0, -7.5],
    "jugular_dome": [1.5, -9.0, -7.7],
    "korner_septum": [8.5, -11.0, -1.0],
    "hyrtl_fissure": [2.0, 0.5, -5.5],
    "lateral_attic_wall": [9.6, 0.4, 5.0],
    "cog": [6.4, 2.6, 6.8],
    "protympanum": [7.4, 5.5, -3.5],
    "iter_chordae_posterius": [7.3, -3.9, -2.0],
    "petrotympanic_fissure": [6.6, 6.2, -0.8],
}

# --------------------------------------------------------------------------
# SDF helpers on a sub-grid
# --------------------------------------------------------------------------
class Grid:
    def __init__(self, n, h, origin):
        self.n, self.h, self.origin = n, h, origin
        self.L = np.zeros((n, n, n), dtype=np.uint8)

    def sub(self, bbox, margin=1.0):
        """bbox = (xmin,xmax,ymin,ymax,zmin,zmax) mm -> slices and broadcastable coords"""
        lo = np.array([bbox[0], bbox[2], bbox[4]]) - margin
        hi = np.array([bbox[1], bbox[3], bbox[5]]) + margin
        i0 = np.clip(np.floor((lo - self.origin) / self.h).astype(int), 0, self.n - 1)
        i1 = np.clip(np.ceil((hi - self.origin) / self.h).astype(int) + 1, 0, self.n)
        sl = (slice(i0[2], i1[2]), slice(i0[1], i1[1]), slice(i0[0], i1[0]))
        xs = (self.origin[0] + np.arange(i0[0], i1[0]) * self.h).astype(np.float32)
        ys = (self.origin[1] + np.arange(i0[1], i1[1]) * self.h).astype(np.float32)
        zs = (self.origin[2] + np.arange(i0[2], i1[2]) * self.h).astype(np.float32)
        X = xs[None, None, :]
        Y = ys[None, :, None]
        Z = zs[:, None, None]
        return sl, X, Y, Z

    def paint(self, sid, sdf_fn, bbox, margin=1.0, only_where=None):
        sl, X, Y, Z = self.sub(bbox, margin)
        d = sdf_fn(X, Y, Z)
        m = d < 0
        if only_where is not None:
            m &= only_where(self.L[sl])
        self.L[sl][m] = LABEL_OF[sid] if sid in LABEL_OF else sid

    def paint_bone(self, sdf_fn, bbox, margin=1.0):
        """paint background bone (label 0) = used for protective sleeves"""
        sl, X, Y, Z = self.sub(bbox, margin)
        m = sdf_fn(X, Y, Z) < 0
        self.L[sl][m] = 0


def sphere(c, r):
    return lambda X, Y, Z: np.sqrt((X - c[0]) ** 2 + (Y - c[1]) ** 2 + (Z - c[2]) ** 2) - r


def ellipsoid(c, rr):
    rmin = min(rr)
    return lambda X, Y, Z: (np.sqrt(((X - c[0]) / rr[0]) ** 2 + ((Y - c[1]) / rr[1]) ** 2 + ((Z - c[2]) / rr[2]) ** 2) - 1.0) * rmin


def capsule(a, b, ra, rb=None):
    a = np.asarray(a, np.float32)
    b = np.asarray(b, np.float32)
    if rb is None:
        rb = ra
    ab = b - a
    L2 = float(ab @ ab) + 1e-9

    def f(X, Y, Z):
        px, py, pz = X - a[0], Y - a[1], Z - a[2]
        t = (px * ab[0] + py * ab[1] + pz * ab[2]) / L2
        t = np.clip(t, 0.0, 1.0)
        dx = px - t * ab[0]
        dy = py - t * ab[1]
        dz = pz - t * ab[2]
        r = ra + t * (rb - ra)
        return np.sqrt(dx * dx + dy * dy + dz * dz) - r
    return f


def polyline(points, radii):
    """tube along a polyline; radii per point (linear interpolation per segment)"""
    segs = []
    for i in range(len(points) - 1):
        segs.append(capsule(points[i], points[i + 1], radii[i], radii[i + 1]))

    def f(X, Y, Z):
        d = segs[0](X, Y, Z)
        for s in segs[1:]:
            d = np.minimum(d, s(X, Y, Z))
        return d
    return f


def union(*fns):
    def f(X, Y, Z):
        d = fns[0](X, Y, Z)
        for g in fns[1:]:
            d = np.minimum(d, g(X, Y, Z))
        return d
    return f


def torus(c, normal, R, r):
    c = np.asarray(c, np.float32)
    n = np.asarray(normal, np.float32)
    n = n / np.linalg.norm(n)

    def f(X, Y, Z):
        qx, qy, qz = X - c[0], Y - c[1], Z - c[2]
        h = qx * n[0] + qy * n[1] + qz * n[2]
        px, py, pz = qx - h * n[0], qy - h * n[1], qz - h * n[2]
        rad = np.sqrt(px * px + py * py + pz * pz)
        return np.sqrt((rad - R) ** 2 + h * h) - r
    return f


def disk(c, normal, R, thickness):
    c = np.asarray(c, np.float32)
    n = np.asarray(normal, np.float32)
    n = n / np.linalg.norm(n)

    def f(X, Y, Z):
        qx, qy, qz = X - c[0], Y - c[1], Z - c[2]
        h = qx * n[0] + qy * n[1] + qz * n[2]
        px, py, pz = qx - h * n[0], qy - h * n[1], qz - h * n[2]
        rad = np.sqrt(px * px + py * py + pz * pz)
        return np.maximum(np.abs(h) - thickness / 2, rad - R)
    return f


def halfspace(normal, point):
    """negative on the side the normal points to"""
    n = np.asarray(normal, np.float32)
    n = n / np.linalg.norm(n)
    p = np.asarray(point, np.float32)
    return lambda X, Y, Z: -((X - p[0]) * n[0] + (Y - p[1]) * n[1] + (Z - p[2]) * n[2])


def box(lo, hi):
    def f(X, Y, Z):
        dx = np.maximum(lo[0] - X, X - hi[0])
        dy = np.maximum(lo[1] - Y, Y - hi[1])
        dz = np.maximum(lo[2] - Z, Z - hi[2])
        return np.maximum(np.maximum(dx, dy), dz)
    return f


def intersect(*fns):
    def f(X, Y, Z):
        d = fns[0](X, Y, Z)
        for g in fns[1:]:
            d = np.maximum(d, g(X, Y, Z))
        return d
    return f


def helix_points(center, axis, R0, R1, turns, pitch, n=320, start_dir=None):
    """points along a tapering helix (cochlea). start_dir = in-plane direction of the basal end"""
    c = np.asarray(center, np.float32)
    a = np.asarray(axis, np.float32)
    a = a / np.linalg.norm(a)
    if start_dir is None:
        start_dir = np.array([0, 0, 1.0], np.float32)
    u = np.asarray(start_dir, np.float32)
    u = u - (u @ a) * a
    u = u / np.linalg.norm(u)
    v = np.cross(a, u)
    ts = np.linspace(0, turns * 2 * math.pi, n)
    pts = []
    for t in ts:
        frac = t / (turns * 2 * math.pi)
        R = R0 + (R1 - R0) * frac
        hgt = pitch * t / (2 * math.pi)
        p = c + R * (math.cos(t) * u + math.sin(t) * v) + hgt * a
        pts.append(p)
    return np.array(pts, np.float32)


def bbox_of(points, r):
    p = np.asarray(points, np.float32).reshape(-1, 3)
    return (p[:, 0].min() - r, p[:, 0].max() + r, p[:, 1].min() - r, p[:, 1].max() + r, p[:, 2].min() - r, p[:, 2].max() + r)


# --------------------------------------------------------------------------
# Build labels
# --------------------------------------------------------------------------
def build_labels():
    G = Grid(N_LAB, H_LAB, ORIGIN)
    whole = (-26, 22, -24, 24, -24, 24)

    # ---- soft tissue around the bone (fossae, surfaces) -------------------
    # middle fossa above the tegmen plane
    G.paint("middle_fossa", halfspace((0, 0, 1), (0, 0, 8.8)), whole)
    # posterior fossa: slanted posterior petrous surface + behind sigmoid + medial to porus
    post = union(halfspace((-0.669, -0.743, 0), (-10, -9, 0)),   # y - (-9) < -0.9 (x + 10)
                 halfspace((-1, 0, 0), (-22, 0, 0)),
                 intersect(halfspace((0, -1, 0), (0, -21.0, 0)), halfspace((0, 0, 1), (0, 0, -12))))
    G.paint("posterior_fossa", post, whole)
    # inferior skull base surface: soft tissue below z=-16 anterior of the mastoid tip
    inf_soft = intersect(halfspace((0, 0, -1), (0, 0, -16)), halfspace((0, 1, 0), (0, -6, 0)), halfspace((1, 0, 0), (-6, 0, 0)))
    G.paint("posterior_fossa", inf_soft, whole)  # reuse soft-tissue label (parotid/neck), HU similar
    # mastoid tip region keeps bone down to z=-22 between y -16..-8, x 5..13; below that soft
    G.paint("posterior_fossa", intersect(halfspace((0, 0, -1), (0, 0, -16)), halfspace((0, -1, 0), (0, -6, 0)),
                                         union(halfspace((0, 0, -1), (0, 0, -22)), halfspace((-1, 0, 0), (4.5, 0, 0)), halfspace((1, 0, 0), (13.5, 0, 0)),
                                               halfspace((0, -1, 0), (0, -16.5, 0)))), whole)
    # lateral soft tissue: x > 14 posterior to the canal; x > 17 around the bony canal
    lat1 = intersect(halfspace((1, 0, 0), (14, 0, 0)), halfspace((0, -1, 0), (0, -3, 0)))
    lat2 = intersect(halfspace((1, 0, 0), (17, 0, 0)), halfspace((0, 1, 0), (0, -3, 0)))
    G.paint("posterior_fossa", union(lat1, lat2), whole)
    # anterior: TMJ / glenoid soft tissue anterior to the canal (y > 7.5, x > 8.5, z < 4)
    G.paint("posterior_fossa", intersect(halfspace((0, 1, 0), (0, 7.5, 0)), halfspace((1, 0, 0), (8.5, 0, 0)), halfspace((0, 0, -1), (0, 0, 4.0))), whole)
    # outside air lateral to the skin: x > 20.5
    G.paint("eac", halfspace((1, 0, 0), (20.5, 0, 0)), whole)
    # condyle (bone) inside the TMJ soft tissue
    G.paint("tmj", ellipsoid((12.5, 12.5, -3.0), (3.4, 3.8, 4.6)), (8, 17, 8, 17, -8, 2))
    # petrous apex marrow
    G.paint("petrous_apex", ellipsoid((-16.5, 7.5, -2.5), (5.0, 6.0, 5.0)), (-22, -11, 1, 14, -8, 3))
    # digastric groove (soft) and ridge (bone label just medial to it)
    G.paint("posterior_fossa", polyline([(7.2, -6.5, -17.3), (7.6, -12.0, -18.3), (8.0, -18.0, -19.6)], [1.3, 1.4, 1.4]), (4, 11, -20, -4, -22, -15))
    G.paint("digastric_ridge", polyline([(5.3, -6.5, -16.6), (5.6, -12.0, -17.4), (5.9, -18.0, -18.4)], [0.8, 0.8, 0.8]), (3, 8, -20, -4, -20, -14))
    # tegmen plate (bone label) above the attic and antrum
    G.paint("tegmen", box((1.5, -17.0, 8.0), (12.5, 6.5, 8.8)), (0, 14, -18, 8, 7, 10))
    # styloid process
    G.paint("styloid", capsule((4.4, -1.2, -16.0), (3.2, 3.0, -24.0), 1.0, 0.7), (1, 7, -3, 5, -24, -15))

    # ---- external and middle ear air ----------------------------------------
    tm_center = np.array([9.2, 0.3, 0.0], np.float32)
    tm_normal = np.array([0.78, 0.25, -0.58], np.float32)
    tm_normal /= np.linalg.norm(tm_normal)
    eac_axis_end = np.array([25.0, 2.2, 1.8], np.float32)
    eac = intersect(capsule(tm_center - 0.5 * tm_normal, eac_axis_end, 3.7, 4.2), halfspace(tm_normal, tm_center))
    G.paint("eac", eac, (8, 22, -5, 7, -5, 7))

    cavity = union(ellipsoid((7.6, 1.2, -1.0), (2.6, 5.6, 4.6)),      # mesotympanum
                   ellipsoid((7.4, 1.5, -5.6), (2.4, 4.0, 2.3)))      # hypotympanum
    G.paint("tympanic_cavity", cavity, (4, 11, -5, 8, -9, 5))
    G.paint("epitympanum", ellipsoid((7.3, 0.4, 5.0), (2.3, 3.7, 2.7)), (4, 10, -4, 5, 2, 8))
    G.paint("aditus", capsule((7.0, -3.0, 5.0), (6.8, -7.6, 5.4), 1.6, 1.8), (4, 10, -9, -1, 3, 8))
    G.paint("antrum", ellipsoid((6.6, -10.6, 5.6), (2.9, 3.5, 3.0)), (3, 10, -15, -7, 2, 9))
    G.paint("eustachian_tube", polyline([(7.6, 5.6, -3.4), (3.5, 12.0, -6.5), (-1.5, 17.6, -9.6)], [1.3, 1.2, 1.3]), (-3, 9, 5, 19, -11, -2))
    # mastoid air cells (random spheres), bone sleeves protect vessels / nerve later
    cells = []
    for _ in range(170):
        c = (RNG.uniform(3.0, 13.5), RNG.uniform(-21.0, -5.5), RNG.uniform(-15.5, 7.0))
        r = RNG.uniform(0.6, 2.1)
        # keep away from sigmoid path (rough) and facial nerve mastoid segment (x~6, y~-4.5)
        if c[1] < -15.5 and 3.0 < c[0] < 9.0:
            continue
        if abs(c[0] - 6.0) < 2.2 and abs(c[1] + 4.6) < 2.6:
            continue
        cells.append(sphere(c, r))
    # make the cells coalesce more: a few larger elongated ones
    for _ in range(12):
        a = (RNG.uniform(4, 12), RNG.uniform(-18, -8), RNG.uniform(-12, 5))
        b = (a[0] + RNG.uniform(-3, 3), a[1] + RNG.uniform(-3, 3), a[2] + RNG.uniform(-3, 3))
        cells.append(capsule(a, b, RNG.uniform(0.8, 1.4)))
    G.paint("mastoid_cells", union(*cells), (2, 15, -22, -4, -17, 8),
            only_where=lambda L: (L == 0) | (L == LABEL_OF["tegmen"]) | (L == LABEL_OF["antrum"]))
    # sinus tympani (medial to the pyramidal eminence / facial nerve) and facial recess (lateral)
    G.paint("sinus_tympani", polyline([(5.3, -2.2, -0.5), (3.6, -3.6, -1.5)], [1.0, 0.8]), (2, 7, -6, 0, -4, 2))
    G.paint("facial_recess", ellipsoid((6.9, -3.4, 0.4), (0.8, 1.2, 2.0)), (5, 9, -6, -1, -2, 3))
    G.paint("prussak_space", ellipsoid((8.4, 1.0, 3.1), (0.55, 0.8, 0.8)), (7, 10, -1, 3, 2, 5))

    # ---- vessels (with bone sleeves) ----------------------------------------
    sig_pts = [(5.5, -18.6, 11.5), (6.0, -18.6, 4.0), (5.0, -17.2, -3.0), (3.0, -13.6, -9.0), (1.5, -9.6, -11.5)]
    G.paint_bone(polyline(sig_pts, [3.9] * 5), bbox_of(sig_pts, 4.5))
    G.paint("sigmoid_sinus", polyline(sig_pts, [3.0, 3.0, 3.0, 2.9, 2.8]), bbox_of(sig_pts, 3.5))
    G.paint_bone(ellipsoid((1.5, -9.0, -11.5), (4.0, 4.4, 4.6)), (-4, 7, -15, -4, -17, -6))
    G.paint("jugular_bulb", ellipsoid((1.5, -9.0, -11.5), (3.2, 3.6, 3.8)), (-3, 6, -14, -5, -16, -7))
    G.paint("jugular_bulb", capsule((1.5, -9.0, -11.5), (0.5, -8.0, -25.0), 3.0), (-4, 6, -13, -4, -25, -10))
    G.paint("emissary_vein", capsule((6.0, -18.6, 4.0), (14.0, -20.5, 1.0), 0.8), (5, 15, -22, -17, 0, 5))
    car_pts = [(-3.5, 11.0, -25.0), (-3.5, 11.0, -7.5), (-19.5, 16.0, -6.0)]
    G.paint_bone(polyline(car_pts, [3.3, 3.3, 3.3]), bbox_of(car_pts, 3.8))
    G.paint("carotid_canal", polyline(car_pts, [2.6, 2.6, 2.6]), bbox_of(car_pts, 3.0))

    # ---- inner ear ----------------------------------------------------------
    G.paint("iac", capsule((-21.0, 1.0, 1.2), (-4.5, 2.8, 1.6), 2.3, 2.1), (-23, -2, -2, 6, -2, 5))
    G.paint("vestibule", ellipsoid((0, 0, 0), (1.6, 2.4, 2.6)), (-3, 3, -4, 4, -4, 4))
    # lateral canal: plane tilted 20 deg, anterior end higher
    lat_c = (1.2, -2.6, 2.0)
    G.paint("scc_lateral", union(torus(lat_c, (0, -0.342, 0.94), 3.2, 0.45), ellipsoid((1.4, 0.6, 2.4), (0.75, 0.9, 0.8))), (-3, 6, -7, 2, -1, 5))
    sup_c = (0.3, -0.8, 3.6)
    G.paint("scc_superior", union(torus(sup_c, (0.707, -0.707, 0), 3.3, 0.45), ellipsoid((0.9, 1.6, 2.4), (0.75, 0.85, 0.85))), (-4, 4, -5, 3, 0, 8))
    pos_c = (-0.8, -3.6, -0.6)
    G.paint("scc_posterior", union(torus(pos_c, (0.707, 0.707, 0), 3.4, 0.45), ellipsoid((-0.3, -1.9, -2.6), (0.75, 0.85, 0.85))), (-5, 4, -8, 0, -5, 4))
    # cochlea: tapering helix anterior to the vestibule, axis anterolateral + inferior
    coch_axis = np.array([0.42, 0.38, 0.82], np.float32)
    coch_pts = helix_points((0.3, 5.0, -1.5), coch_axis, 3.3, 1.5, 2.5, 2.0, n=400, start_dir=(0.5, -0.8, -0.2))
    coch_r = np.linspace(0.85, 0.5, len(coch_pts))
    G.paint("cochlea", polyline(coch_pts.tolist(), coch_r.tolist()), bbox_of(coch_pts, 1.2))
    # round window membrane at the basal end of the cochlea
    rw_c = coch_pts[0]
    G.paint("round_window", disk(rw_c + np.array([0.6, -0.3, -0.5], np.float32), (0.7, -0.4, -0.6), 1.0, 0.35), bbox_of([rw_c], 2.0))
    # aqueducts
    G.paint("vestibular_aqueduct", polyline([(-1.2, -1.6, -0.4), (-6.0, -6.0, -1.0), (-10.6, -10.6, -1.8)], [0.35, 0.4, 0.5]), (-12, 0, -12, 0, -3, 1))
    G.paint("endolymphatic_sac", disk((-9.6, -10.2, -2.2), (-0.669, -0.743, 0), 2.0, 0.6), (-13, -7, -13, -7, -5, 1))
    G.paint("cochlear_aqueduct", polyline([(3.0, 2.2, -2.8), (-6.0, -1.0, -6.0), (-17.5, -5.8, -9.2)], [0.3, 0.3, 0.45]), (-19, 4, -7, 3, -10, -2))

    # ---- facial nerve (with sleeve), chorda, GSPN ---------------------------
    fn_meatal = [(-21.0, 1.9, 2.1), (-4.5, 3.7, 2.5)]
    fn_lab = [(-4.5, 3.7, 2.5), (-0.6, 6.6, 3.8)]
    fn_tymp = [(-0.6, 6.6, 3.8), (3.4, 3.2, 2.9), (4.0, 0.5, 2.6), (4.8, -2.0, 1.3), (5.4, -3.6, 0.2)]
    fn_mast = [(5.4, -3.6, 0.2), (5.8, -4.2, -6.0), (6.2, -4.8, -15.5), (6.4, -5.0, -18.5)]
    for pts, r in ((fn_lab, 0.4), (fn_tymp, 0.6), (fn_mast, 0.7)):
        G.paint_bone(polyline(pts, [r + 0.55] * len(pts)), bbox_of(pts, r + 1.0))
    G.paint("fn_meatal", polyline(fn_meatal, [0.55, 0.55]), bbox_of(fn_meatal, 1.0))
    G.paint("fn_labyrinthine", polyline(fn_lab, [0.4, 0.45]), bbox_of(fn_lab, 1.0))
    G.paint("geniculate", ellipsoid((-0.6, 6.6, 3.8), (0.9, 1.1, 0.7)), (-3, 2, 5, 9, 2, 6))
    G.paint("gspn", polyline([(-0.6, 6.6, 3.8), (-5.0, 9.8, 3.6), (-9.5, 12.8, 3.2)], [0.3, 0.3, 0.3]), (-11, 1, 5, 14, 2, 6))
    G.paint("fn_tympanic", polyline(fn_tymp, [0.55, 0.6, 0.6, 0.6, 0.65]), bbox_of(fn_tymp, 1.0))
    G.paint("fn_mastoid", polyline(fn_mast, [0.65, 0.7, 0.75, 0.75]), bbox_of(fn_mast, 1.0))
    G.paint("stylomastoid_foramen", torus((6.25, -4.85, -16.0), (0.08, -0.08, 1), 1.15, 0.3), (4, 9, -7, -2, -17, -15))
    chorda = [(5.9, -4.4, -10.5), (7.0, -3.8, -3.0), (7.9, -2.2, 0.2), (7.7, 0.8, 2.0), (7.2, 3.6, 1.2), (6.6, 6.2, -0.8)]
    G.paint("chorda_tympani", polyline(chorda, [0.3] * 6), bbox_of(chorda, 0.8))

    # ---- muscles, membrane, ossicles ----------------------------------------
    G.paint("tensor_tympani", polyline([(4.3, 3.6, 2.6), (3.0, 8.0, 1.6), (0.0, 13.5, -1.0)], [0.6, 0.85, 0.85]), (-2, 6, 2, 15, -3, 4))
    G.paint("tensor_tympani", capsule((4.6, 3.9, 2.3), (7.5, 0.9, 2.8), 0.25), (3, 9, 0, 5, 1, 4))
    G.paint("cochleariform_process", sphere((4.6, 3.9, 2.3), 0.55), (3, 6, 2, 6, 1, 4))
    G.paint("pyramidal_eminence", ellipsoid((6.3, -2.4, 0.6), (0.5, 0.6, 0.85)), (5, 8, -4, -1, -1, 2))
    G.paint("stapedius", capsule((6.3, -2.4, 0.6), (5.0, 0.0, 1.3), 0.25), (4, 7, -3, 1, 0, 2))
    G.paint("tympanic_membrane", disk(tm_center, tm_normal, 4.6, 0.32), (4, 14, -5, 6, -6, 6),
            only_where=lambda L: (L == LABEL_OF["eac"]) | (L == LABEL_OF["tympanic_cavity"]) | (L == LABEL_OF["epitympanum"]) | (L == LABEL_OF["prussak_space"]) | (L == 0))
    G.paint("scutum", ellipsoid((9.55, 0.45, 3.5), (0.6, 0.8, 0.5)), (8, 11, -1, 2, 2, 5))
    # malleus
    G.paint("malleus", union(ellipsoid((7.2, 1.4, 4.6), (1.0, 1.2, 1.3)), capsule((7.4, 1.0, 3.4), (7.6, 0.8, 2.6), 0.5),
                             capsule((7.6, 0.8, 2.6), (8.6, 0.0, -1.6), 0.42, 0.3), sphere((8.1, 0.9, 2.2), 0.5)), (5, 10, -2, 3, -3, 7))
    # incus
    G.paint("incus", union(ellipsoid((7.0, -0.9, 4.4), (1.1, 1.1, 1.2)), capsule((7.0, -0.9, 4.4), (7.3, -3.2, 3.9), 0.5, 0.35),
                           capsule((6.9, -0.9, 4.4), (6.3, -0.3, 1.6), 0.42, 0.35), sphere((6.1, -0.1, 1.4), 0.36)), (4, 9, -5, 1, 0, 7))
    # stapes
    G.paint("stapes", union(sphere((5.5, 0.2, 1.3), 0.42), capsule((5.5, 0.2, 1.3), (3.5, 1.7, 1.25), 0.24),
                            capsule((5.5, 0.2, 1.3), (3.5, -0.7, 1.15), 0.24), ellipsoid((3.25, 0.5, 1.2), (0.28, 1.5, 0.78))), (2, 7, -2, 3, 0, 3))
    return G


# --------------------------------------------------------------------------
# HU synthesis on the CT grid
# --------------------------------------------------------------------------
def labels_to_ct(L256):
    """Compute HU on the 256 grid, then block-average to 128 for partial volume."""
    hu = np.full(L256.shape, 1500.0, dtype=np.float32)
    for sid, lab in LABEL_OF.items():
        hu[L256 == lab] = HU_OF[sid]
    # otic capsule: denser bone near the labyrinth
    lab_mask = np.isin(L256, [LABEL_OF[s] for s in ("cochlea", "vestibule", "scc_lateral", "scc_superior", "scc_posterior")])
    small = lab_mask[::2, ::2, ::2]
    d = ndi.distance_transform_edt(~small, sampling=(H_CT, H_CT, H_CT)).astype(np.float32)
    capsule_boost = 650.0 * np.exp(-(d / 2.6) ** 2)
    boost256 = np.repeat(np.repeat(np.repeat(capsule_boost, 2, 0), 2, 1), 2, 2)
    bone = (L256 == 0)
    hu[bone] += boost256[bone]
    # trabecular texture in bone: low frequency noise
    tex = RNG.normal(0, 1, size=(N_CT, N_CT, N_CT)).astype(np.float32)
    tex = ndi.gaussian_filter(tex, 1.2)
    tex = tex / (tex.std() + 1e-6) * 240.0
    tex256 = np.repeat(np.repeat(np.repeat(tex, 2, 0), 2, 1), 2, 2)
    hu[bone] += tex256[bone] * (1.0 - np.clip(boost256[bone] / 650.0, 0, 1))  # capsule is homogeneous
    # block average 2x2x2 -> 128
    ct = hu.reshape(N_CT, 2, N_CT, 2, N_CT, 2).mean(axis=(1, 3, 5))
    ct = ndi.gaussian_filter(ct, 0.45)
    ct += RNG.normal(0, 16, size=ct.shape).astype(np.float32)
    ct = np.clip(ct, -1024, 3071).astype(np.int16)
    return ct


# --------------------------------------------------------------------------
# Mesh extraction
# --------------------------------------------------------------------------
def extract_mesh(mask, grid_h, origin, sigma, level, target_faces):
    if measure is None:
        raise RuntimeError("scikit-image required for mesh extraction")
    idx = np.argwhere(mask)
    if len(idx) == 0:
        return None
    lo = np.maximum(idx.min(0) - 4, 0)
    hi = np.minimum(idx.max(0) + 5, np.array(mask.shape))
    sub = mask[lo[0]:hi[0], lo[1]:hi[1], lo[2]:hi[2]].astype(np.float32)
    sub = ndi.gaussian_filter(sub, sigma)
    if sub.max() <= level:
        level = sub.max() * 0.6
    verts, faces, _, _ = measure.marching_cubes(sub, level=level)
    verts = verts + lo  # (z,y,x) index
    # to RAS mm: x = origin + i*h with verts columns (z,y,x)
    xyz = np.stack([origin[0] + verts[:, 2] * grid_h, origin[1] + verts[:, 1] * grid_h, origin[2] + verts[:, 0] * grid_h], 1).astype(np.float32)
    faces = faces.astype(np.int64)
    # marching_cubes from skimage returns outward-facing normals for the "positive inside" convention; flip to standard CCW
    faces = faces[:, ::-1]
    if fast_simplification is not None and len(faces) > target_faces:
        red = 1.0 - target_faces / len(faces)
        xyz, faces = fast_simplification.simplify(xyz.astype(np.float32), faces.astype(np.int32), target_reduction=float(red))
        xyz = np.asarray(xyz, np.float32)
        faces = np.asarray(faces, np.int64)
    # drop degenerate / unused vertices
    used = np.unique(faces)
    remap = -np.ones(len(xyz), np.int64)
    remap[used] = np.arange(len(used))
    xyz = xyz[used]
    faces = remap[faces]
    return xyz.astype(np.float32), faces.astype(np.uint32)


MESH_PARAMS = {  # sigma (voxels on 256 grid), level, target faces
    "default": (1.0, 0.5, 6000),
    "fn_labyrinthine": (0.7, 0.42, 2500), "chorda_tympani": (0.6, 0.4, 3000), "gspn": (0.6, 0.4, 2500),
    "stapedius": (0.5, 0.38, 1500), "cochlear_aqueduct": (0.6, 0.4, 2500), "vestibular_aqueduct": (0.6, 0.4, 2500),
    "stapes": (0.55, 0.4, 3500), "incus": (0.8, 0.45, 3500), "malleus": (0.8, 0.45, 3500),
    "mastoid_cells": (1.0, 0.5, 16000), "tympanic_cavity": (1.2, 0.5, 8000), "sigmoid_sinus": (1.2, 0.5, 5000),
    "cochlea": (0.9, 0.5, 8000), "scc_lateral": (0.8, 0.45, 4000), "scc_superior": (0.8, 0.45, 4000), "scc_posterior": (0.8, 0.45, 4000),
    "round_window": (0.6, 0.4, 1200), "scutum": (0.6, 0.4, 1200), "cochleariform_process": (0.6, 0.4, 1000),
    "pyramidal_eminence": (0.6, 0.4, 1200), "stylomastoid_foramen": (0.6, 0.4, 2000), "tympanic_membrane": (0.7, 0.42, 3000),
    "tegmen": (1.0, 0.5, 4000), "digastric_ridge": (0.8, 0.45, 2500), "prussak_space": (0.6, 0.4, 1000),
    "emissary_vein": (0.7, 0.42, 2000), "endolymphatic_sac": (0.7, 0.42, 1500), "eac": (1.2, 0.5, 6000),
}


def write_stl(path, verts, faces):
    import struct as st
    with open(path, "wb") as f:
        f.write(b"TBA phantom".ljust(80, b"\x00"))
        f.write(st.pack("<I", len(faces)))
        v = verts[faces]  # (nf,3,3)
        n = np.cross(v[:, 1] - v[:, 0], v[:, 2] - v[:, 0])
        n /= (np.linalg.norm(n, axis=1, keepdims=True) + 1e-12)
        rec = np.zeros(len(faces), dtype=np.dtype([("n", "<f4", 3), ("v", "<f4", (3, 3)), ("a", "<u2")]))
        rec["n"] = n
        rec["v"] = v
        f.write(rec.tobytes())


def main(out_phantom="phantom", out_pack="dist/phantom.tba"):
    print("building labels on %d^3 grid ..." % N_LAB)
    G = build_labels()
    L = G.L
    print("synthesising CT ...")
    ct = labels_to_ct(L)
    L128 = L[::2, ::2, ::2].copy()

    # diagnostics: voxel counts
    counts = {sid: int((L == lab).sum()) for sid, lab in LABEL_OF.items()}
    missing = [s for s, c in counts.items() if c == 0]
    if missing:
        print("WARNING: empty labels:", missing)

    os.makedirs(os.path.join(out_phantom, "meshes"), exist_ok=True)
    os.makedirs(os.path.dirname(out_pack) or ".", exist_ok=True)

    meshes = {}
    for sid, lab in LABEL_OF.items():
        if not MESH_OF[sid]:
            continue
        sig, lev, tf = MESH_PARAMS.get(sid, MESH_PARAMS["default"])
        m = extract_mesh(L == lab, H_LAB, ORIGIN, sig, lev, tf)
        if m is None:
            print("  no mesh for", sid)
            continue
        meshes[sid] = m
        write_stl(os.path.join(out_phantom, "meshes", sid + ".stl"), *m)
        print("  mesh %-24s %6d verts %6d faces" % (sid, len(m[0]), len(m[1])))
    # bone shell (context) from CT
    bone_mask = ct > 900
    bone_mask = ndi.binary_opening(bone_mask, iterations=1)
    bm = extract_mesh(bone_mask, H_CT, ORIGIN, 1.0, 0.5, 30000)
    if bm is not None:
        meshes["bone_shell"] = bm
        write_stl(os.path.join(out_phantom, "meshes", "bone_shell.stl"), *bm)
        print("  mesh %-24s %6d verts %6d faces" % ("bone_shell", len(bm[0]), len(bm[1])))

    # NIfTI export (RAS affine)
    if nib is not None:
        aff = np.diag([H_CT, H_CT, H_CT, 1.0])
        aff[:3, 3] = ORIGIN
        # nibabel expects (x,y,z) array order
        nib.save(nib.Nifti1Image(np.ascontiguousarray(ct.transpose(2, 1, 0)), aff), os.path.join(out_phantom, "volume.nii.gz"))
        nib.save(nib.Nifti1Image(np.ascontiguousarray(L128.transpose(2, 1, 0)), aff), os.path.join(out_phantom, "labels.nii.gz"))

    # landmarks: mesh centroids + explicit points
    landmarks = {k: [float(x) for x in v] for k, v in LANDMARKS.items()}
    mesh_table = []
    blobs = [("volume", delta_encode_int16(ct).astype("<i2").tobytes()), ("labels", L128.astype(np.uint8).tobytes())]
    for sid, (v, f) in meshes.items():
        cen = v.mean(0).tolist()
        bb = [float(v[:, 0].min()), float(v[:, 1].min()), float(v[:, 2].min()), float(v[:, 0].max()), float(v[:, 1].max()), float(v[:, 2].max())]
        mesh_table.append({"id": sid, "nv": int(len(v)), "nf": int(len(f)), "centroid": [float(c) for c in cen], "bbox": bb, "v": "mesh:%s:v" % sid, "f": "mesh:%s:f" % sid})
        blobs.append(("mesh:%s:v" % sid, v.astype("<f4").tobytes()))
        blobs.append(("mesh:%s:f" % sid, f.astype("<u4").tobytes()))
    # label centroids on the 128 grid as landmarks for labelled structures
    for sid, lab in LABEL_OF.items():
        idx = np.argwhere(L128 == lab)
        if len(idx):
            c = idx.mean(0)
            # representative point: the labelled voxel nearest the centroid (centroids of rings and tubes fall outside them)
            d2 = ((idx - c) ** 2).sum(1)
            c = idx[int(np.argmin(d2))]
            landmarks.setdefault(sid, [float(ORIGIN[0] + c[2] * H_CT), float(ORIGIN[1] + c[1] * H_CT), float(ORIGIN[2] + c[0] * H_CT)])

    header = {
        "format": "tba",
        "version": 1,
        "name": "Synthetic right temporal bone (phantom)",
        "kind": "phantom",
        "side": "R",
        "notes": "Procedurally generated. Correct topology and relationships, not patient anatomy. Replace with an OpenEar specimen or an institutional CT for real imaging.",
        "volume": {"blob": "volume", "dims": [N_CT, N_CT, N_CT], "spacing": [H_CT, H_CT, H_CT], "origin": [float(x) for x in ORIGIN], "dtype": "int16", "units": "HU", "encoding": "delta-x"},
        "labels": {"blob": "labels", "dims": [N_CT, N_CT, N_CT], "spacing": [H_CT, H_CT, H_CT], "origin": [float(x) for x in ORIGIN], "dtype": "uint8"},
        "labelIds": {str(lab): sid for sid, lab in LABEL_OF.items()},
        "meshes": mesh_table,
        "landmarks": landmarks,
    }
    n = write_pack(out_pack, header, blobs)
    print("pack written: %s (%.1f MB raw, %.1f MB gz)" % (out_pack, n / 1e6, os.path.getsize(out_pack) / 1e6))
    with open(os.path.join(out_phantom, "manifest.json"), "w") as f:
        json.dump({"name": header["name"], "side": "R", "kind": "phantom", "labelIds": header["labelIds"], "names": NAME_OF, "landmarks": landmarks,
                   "meshes": [{"id": m["id"], "file": "meshes/%s.stl" % m["id"]} for m in mesh_table]}, f, indent=1)
    print("done.")


if __name__ == "__main__":
    main(*(sys.argv[1:3] if len(sys.argv) > 2 else ()))
