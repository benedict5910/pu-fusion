"""Dimensioned engineering drawings of the representative IVHM drivetrain (no FreeCAD needed).

    python cad/make_drawings.py            ->  cad/out/drawings/ivhm_drivetrain_drawings.pdf (4 A3 sheets)
                                               + one PNG per sheet, cad/out/sensor_map.json, design_checks.json,
                                               cad/out/interference_check.json, cad/out/iso_assembled.png

Drawn from src/pufusion/drivetrain_cad.py, the parameter model that also builds the FreeCAD assembly; the FreeCAD
self-check (cad/out/freecad_report.json) compares the FreeCAD solids with this model. Third-angle projection,
millimetres. Hidden lines are not shown; holes and bores appear only in the views that cut through them.
REPRESENTATIVE assembly - not a reconstruction of the Paderborn or MCC5-THU test benches.
"""
import json
import math
import os
import sys
import time
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
from matplotlib.backends.backend_pdf import PdfPages  # noqa: E402
from matplotlib.patches import Circle, Polygon, Rectangle  # noqa: E402
from mpl_toolkits.mplot3d.art3d import Poly3DCollection  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from pufusion import drivetrain_cad as D  # noqa: E402

OUT = ROOT / "cad" / "out"
DRW = OUT / "drawings"
A3 = (16.54, 11.69)                       # inches
INK, FILL, SENS = "#111827", "#f3f4f6", "#dc2626"
COMP_FILL = {"motor": "#dbeafe", "gearbox": "#fde68a", "test_bearing": "#fecaca", "support_bearing": "#e5e7eb",
             "load": "#d1fae5", "line_shaft": "#e5e7eb", "base": "#f9fafb"}
REV = "A"
TOP = 50_000                              # z-order for dimensions, centre lines and labels


def _patch(sh, fc, ec=INK, lw=0.6, ls="-", z=1):
    if sh[0] == "rect":
        _, a, b, c, d = sh
        return Rectangle((a, b), c - a, d - b, fc=fc, ec=ec, lw=lw, ls=ls, zorder=z)
    if sh[0] == "circle":
        _, a, b, r = sh
        return Circle((a, b), r, fc=fc, ec=ec, lw=lw, ls=ls, zorder=z)
    return Polygon(sh[1], closed=True, fc=fc, ec=ec, lw=lw, ls=ls, zorder=z)


def draw_view(ax, view, offset=(0, 0), colour=True, sensors=True, only=None, sens_labels=True):
    """Painter's-algorithm orthographic view of the assembly (far parts first)."""
    items = [(p, D.part_bbox(p)) for p in D.parts() if only is None or p["component"] in only]
    zo = 1
    for p, bb in sorted(items, key=lambda it: D.depth(it[1], view)):
        fc = COMP_FILL.get(p["component"], FILL) if colour else "white"
        for pr in p["add"]:
            for sh in D.project(D.resolve(pr), view):
                sh = _shift(sh, offset)
                ax.add_patch(_patch(sh, fc, z=zo))
                zo += 1
    if sensors:
        hu, hv, _, _ = D.VIEWS[view]
        for s in D.SENSORS:
            for sh in D.project(D.resolve(s["geom"]), view):
                ax.add_patch(_patch(_shift(sh, offset), SENS, ec="#7f1d1d", lw=0.8, z=10_000))
            if sens_labels:
                c = dict(zip("xyz", D.sensor_position(s)))
                ax.annotate(s["id"], (c[hu] + offset[0], c[hv] + offset[1]),
                            (c[hu] + offset[0] + 25, c[hv] + offset[1] + 45), fontsize=8, color=SENS,
                            fontweight="bold", arrowprops=dict(arrowstyle="-", color=SENS, lw=0.6), zorder=10_001)


def _shift(sh, off):
    du, dv = off
    if sh[0] == "rect":
        return ("rect", sh[1] + du, sh[2] + dv, sh[3] + du, sh[4] + dv)
    if sh[0] == "circle":
        return ("circle", sh[1] + du, sh[2] + dv, sh[3])
    return ("poly", [(u + du, v + dv) for u, v in sh[1]])


def dim_h(ax, x0, x1, y, text=None, ext_from=None, fs=7):
    text = text or f"{abs(x1 - x0):.0f}"
    ax.annotate("", (x0, y), (x1, y), arrowprops=dict(arrowstyle="<->", lw=0.5, color=INK, shrinkA=0, shrinkB=0),
                zorder=TOP)
    ax.text((x0 + x1) / 2, y + 6, text, ha="center", va="bottom", fontsize=fs, zorder=TOP,
            bbox=dict(fc="white", ec="none", pad=0.6))
    if ext_from is not None:
        for x, y0 in zip((x0, x1), ext_from):
            ax.plot([x, x], [y0, y + (4 if y > y0 else -4)], lw=0.35, color=INK, zorder=TOP)


def dim_v(ax, x, y0, y1, text=None, ext_from=None, fs=7):
    text = text or f"{abs(y1 - y0):.0f}"
    ax.annotate("", (x, y0), (x, y1), arrowprops=dict(arrowstyle="<->", lw=0.5, color=INK, shrinkA=0, shrinkB=0),
                zorder=TOP)
    ax.text(x - 6, (y0 + y1) / 2, text, ha="right", va="center", fontsize=fs, rotation=90, zorder=TOP,
            bbox=dict(fc="white", ec="none", pad=0.6))
    if ext_from is not None:
        for y, x0 in zip((y0, y1), ext_from):
            ax.plot([x0, x + (4 if x > x0 else -4)], [y, y], lw=0.35, color=INK, zorder=TOP)


def centreline(ax, x0, x1, y, vertical=False):
    if vertical:
        ax.plot([y, y], [x0, x1], lw=0.4, color="#2563eb", ls=(0, (12, 3, 2, 3)), zorder=TOP)
    else:
        ax.plot([x0, x1], [y, y], lw=0.4, color="#2563eb", ls=(0, (12, 3, 2, 3)), zorder=TOP)


def sheet(title, number, total, scale_note):
    fig = plt.figure(figsize=A3)
    fig.patch.set_facecolor("white")
    frame = fig.add_axes([0.012, 0.015, 0.976, 0.97])
    frame.set_xticks([]); frame.set_yticks([])
    for s_ in frame.spines.values():
        s_.set_linewidth(1.2)
    # title block
    tb = fig.add_axes([0.60, 0.022, 0.383, 0.135])
    tb.set_xlim(0, 100); tb.set_ylim(0, 40); tb.set_xticks([]); tb.set_yticks([])
    for y in (10, 20, 30):
        tb.plot([0, 100], [y, y], lw=0.5, color=INK)
    tb.plot([60, 60], [0, 20], lw=0.5, color=INK); tb.plot([80, 80], [0, 10], lw=0.5, color=INK)
    tb.text(2, 34.5, "IVHM representative electric-drive assembly", fontsize=10, fontweight="bold", va="center")
    tb.text(2, 25, title, fontsize=9, va="center")
    tb.text(2, 15, "REPRESENTATIVE - not a reconstruction of the Paderborn or MCC5-THU test benches",
            fontsize=6.6, va="center", color="#b91c1c")
    tb.text(2, 5, f"Units mm  |  {scale_note}  |  third-angle projection", fontsize=7, va="center")
    tb.text(62, 15, f"Rev {REV}  |  {time.strftime('%d %b %Y', time.gmtime(time.time() + 5.5 * 3600))}", fontsize=7, va="center")
    tb.text(62, 5, "B.Tech 26PB40 (MSRUAS)", fontsize=6.5, va="center")
    tb.text(82, 5, f"Sheet {number}/{total}", fontsize=7, va="center")
    fig.text(0.02, 0.165, "Generated by cad/make_drawings.py from src/pufusion/drivetrain_cad.py (same parameter model "
             "as cad/out/ivhm_drivetrain.FCStd).", fontsize=6.5, color="#4b5563")
    return fig


def _view_axes(fig, rect, xlim, ylim, label):
    ax = fig.add_axes(rect)
    ax.set_xlim(*xlim); ax.set_ylim(*ylim); ax.set_aspect("equal"); ax.axis("off")
    ax.text(xlim[0], ylim[1] - 5, label, fontsize=8, fontweight="bold", va="top")
    return ax


# --------------------------------------------------------------------------------------------- sheet 1: GA
def sheet_ga(pdf):
    fig = sheet("General arrangement", 1, 4, "scale 1:5 on A3")
    P = D.P
    x0, x1 = P["base_x0"], P["base_x0"] + P["base_l"]
    front = _view_axes(fig, [0.04, 0.17, 0.92, 0.42], (x0 - 100, x1 + 40), (-95, 340), "FRONT VIEW")
    draw_view(front, "front")
    centreline(front, x0 - 20, x1 + 20, P["shaft_h"])
    dim_h(front, x0, x1, -80, ext_from=(-20, -20))
    dim_v(front, x0 - 75, -20, 290, ext_from=(x0, P["mot_x0"] + 100))
    dim_v(front, x0 - 25, 0, P["shaft_h"], f"{P['shaft_h']:.0f} (shaft centre height)", ext_from=(x0, x0))
    dim_h(front, P["brg_a_x"], P["brg_b_x"], 230, f"bearing span {P['brg_b_x'] - P['brg_a_x']:.0f}",
          ext_from=(185, 185))
    dim_h(front, P["mot_x0"], P["mot_x0"] + P["mot_l"], 310, ext_from=(230, 290))
    dim_h(front, P["gb_x0"], P["gb_x0"] + P["gb_l"], 250, ext_from=(222, 222))
    for name, xc in (("SUPPORT BEARING 6203", P["brg_a_x"]), ("TEST BEARING 6203", P["brg_b_x"])):
        front.text(xc, -46, name, fontsize=6, ha="center", va="top", color="#374151", zorder=TOP)
    for name, xc in (("MOTOR (IEC 90 proportions)", P["mot_x0"] + P["mot_l"] / 2), ("COUPLING", 365),
                     ("COUPLING", 725), ("GEARBOX 1:2.5", P["gb_x0"] + P["gb_l"] / 2), ("LOAD", P["load_x0"] + 35)):
        front.text(xc, -28, name, fontsize=6, ha="center", va="top", color="#374151", zorder=TOP)

    top = _view_axes(fig, [0.04, 0.60, 0.92, 0.36], (x0 - 90, x1 + 40), (-160, 230), "TOP VIEW")
    draw_view(top, "top")
    centreline(top, x0 - 20, P["gb_x0"] + 10, 0)
    centreline(top, P["gb_x0"] - 10, x1 + 20, D.ev("out_y"))
    dim_v(top, x0 - 30, P["base_y0"], P["base_y0"] + P["base_w"], ext_from=(x0, x0))
    dim_v(top, P["gb_x0"] + P["gb_l"] + 10, 0, D.ev("out_y"), f"a = {D.ev('centre_dist'):.0f}",
          ext_from=(P["gb_x0"] + P["gb_l"], P["gb_x0"] + P["gb_l"]))
    pdf.savefig(fig); fig.savefig(DRW / "sheet1_general_arrangement.png", dpi=110); plt.close(fig)


# --------------------------------------------------------------------------------------------- sheet 2: sensors
def sheet_sensors(pdf):
    fig = sheet("Sensor location map", 2, 4, "views not to scale with each other")
    P = D.P
    x0, x1 = P["base_x0"], P["base_x0"] + P["base_l"]
    front = _view_axes(fig, [0.03, 0.55, 0.55, 0.40], (x0 - 30, x1 + 30), (-40, 330), "FRONT VIEW - sensors in red")
    draw_view(front, "front", colour=False)
    top = _view_axes(fig, [0.03, 0.17, 0.55, 0.36], (x0 - 30, x1 + 30), (-160, 230), "TOP VIEW")
    draw_view(top, "top", colour=False)
    tab = fig.add_axes([0.60, 0.17, 0.385, 0.78]); tab.axis("off")
    m = D.sensor_map()
    y = 0.98
    tab.text(0, y, "Sensor map (cad/out/sensor_map.json)", fontsize=10, fontweight="bold", va="top")
    y -= 0.045
    for s in m["sensors"]:
        tab.text(0, y, f"{s['id']}  {s['label']}", fontsize=8.5, fontweight="bold", color=SENS, va="top")
        lines = [f"subsystem: {s['subsystem']}   code key: '{s['code']}'",
                 f"dataset: {s['dataset']}",
                 f"channels: {', '.join(s['channels'])}",
                 f"quantity: {s['quantity']}, {s['fs_hz'] / 1000:g} kHz",
                 f"mounted on: {s['mount']} - {s['where']}",
                 f"position (x, y, z) mm: {tuple(round(v, 1) for v in s['position_mm'])}"]
        for ln in lines:
            y -= 0.028
            tab.text(0.02, y, ln, fontsize=7, va="top", wrap=True)
        y -= 0.045
    tab.text(0, y, "\n".join([
        "S1/S2 replay Paderborn KAt recordings (bearing subsystem).",
        "S3/S4 replay MCC5-THU recordings (gearbox subsystem).",
        "The two datasets were recorded on two different test benches;",
        "positions here are representative mounting locations on this",
        "assembly, not the benches' measured sensor positions."]), fontsize=7, va="top", color="#b91c1c")
    pdf.savefig(fig); fig.savefig(DRW / "sheet2_sensor_map.png", dpi=110); plt.close(fig)


# --------------------------------------------------------------------------------------------- 3-D helpers
def _box_faces(b):
    x0, y0, z0, x1, y1, z1 = b
    v = [(x0, y0, z0), (x1, y0, z0), (x1, y1, z0), (x0, y1, z0), (x0, y0, z1), (x1, y0, z1), (x1, y1, z1), (x0, y1, z1)]
    idx = [(0, 1, 2, 3), (4, 5, 6, 7), (0, 1, 5, 4), (2, 3, 7, 6), (1, 2, 6, 5), (0, 3, 7, 4)]
    return [[v[i] for i in f] for f in idx]


def _cyl_faces(pr, n=28):
    r = pr.get("r", pr.get("ro"))
    if pr["type"] == "gear":
        r = pr["module"] * pr["teeth"] / 2 + pr["module"]
    h = pr.get("h", pr.get("width"))
    i = "xyz".index(pr["axis"])
    c = [pr["x"], pr["y"], pr["z"]]
    others = [k for k in range(3) if k != i]
    ring = []
    for k in range(n):
        a = 2 * math.pi * k / n
        p = list(c)
        p[others[0]] += r * math.cos(a)
        p[others[1]] += r * math.sin(a)
        ring.append(p)
    top = []
    for p in ring:
        q = list(p); q[i] += h; top.append(q)
    faces = [[ring[k], ring[(k + 1) % n], top[(k + 1) % n], top[k]] for k in range(n)]
    return faces + [ring, top]


def draw3d(ax, exploded=False, alpha=1.0):
    """All faces in ONE Poly3DCollection, so matplotlib depth-sorts faces across parts (painter's algorithm)."""
    faces, fcs, ecs, labels = [], [], [], []
    for p in D.parts():
        if "_ball_" in p["name"]:
            continue
        off = D.explode_offset(p) if exploded else (0, 0, 0)
        fc = COMP_FILL.get(p["component"], FILL)
        for pr in p["add"]:
            r = D.resolve(pr)
            r = {**r, "x": r["x"] + off[0], "y": r["y"] + off[1], "z": r["z"] + off[2]}
            fs = _box_faces(D.bbox(r)) if r["type"] == "box" else _cyl_faces(r) if r["type"] != "sphere" else []
            faces += fs; fcs += [fc] * len(fs); ecs += ["#6b7280"] * len(fs)
    for s in D.SENSORS:
        mount = next(p for p in D.parts() if p["name"] == s["mount"])
        off = [a + b * 40 for a, b in zip(D.explode_offset(mount), s["axis"])] if exploded else (0, 0, 0)
        r = D.resolve(s["geom"])
        r = {**r, "x": r["x"] + off[0], "y": r["y"] + off[1], "z": r["z"] + off[2]}
        fs = _box_faces(D.bbox(r)) if r["type"] == "box" else _cyl_faces(r)
        faces += fs; fcs += [SENS] * len(fs); ecs += ["#7f1d1d"] * len(fs)
        c = [(a + b) / 2 for a, b in zip(D.bbox(r)[:3], D.bbox(r)[3:])]
        labels.append((c, s["id"]))
    ax.add_collection3d(Poly3DCollection(faces, facecolors=fcs, edgecolors=ecs, linewidths=0.15, alpha=alpha))
    ax.computed_zorder = False
    for c, t in labels:
        ax.text(c[0], c[1], c[2] + 50, t, color=SENS, fontsize=9, fontweight="bold", zorder=TOP)
    xl = (-230, 1310) if exploded else (-60, 1160)
    ax.set_xlim(*xl); ax.set_ylim(-300, 340); ax.set_zlim(-30, 600 if exploded else 330)
    ax.set_box_aspect((xl[1] - xl[0], 640, 630 if exploded else 360), zoom=1.2 if exploded else 1.25)
    ax.view_init(elev=24, azim=-58)
    ax.set_proj_type("ortho")
    ax.axis("off")


def sheet_exploded(pdf):
    fig = sheet("Exploded view (illustrative, painter-sorted 3-D)", 3, 4, "not to scale")
    ax = fig.add_axes([0.02, 0.17, 0.96, 0.80], projection="3d")
    draw3d(ax, exploded=True)
    for name, xyz in (("motor", (-10, 0, 300)), ("couplings", (365, 0, 330)), ("line shaft", (520, 0, 500)),
                      ("6203 bearings", (530, 0, 380)), ("housings", (450, -60, 230)),
                      ("gearbox internals", (850, 40, 560)), ("cover", (850, 46, 470)),
                      ("gearbox housing", (850, 140, 260)), ("load", (1240, 70, 260))):
        ax.text(*xyz, name, fontsize=8, color="#374151", zorder=TOP)
    pdf.savefig(fig); fig.savefig(DRW / "sheet3_exploded.png", dpi=110); plt.close(fig)


# --------------------------------------------------------------------------------------------- sheet 4: details
def sheet_details(pdf, checks):
    fig = sheet("Details: test-bearing support, gear mesh, sizing checks", 4, 4, "details 1:1 on A3")
    P = D.P
    h = P["shaft_h"]
    # detail A: test bearing support, looking along the shaft
    ax = _view_axes(fig, [0.03, 0.30, 0.30, 0.66], (-110, 110), (-30, 250), "DETAIL A - TEST BEARING SUPPORT (end view)")
    only = [p for p in D.parts() if p["component"] == "test_bearing" or p["name"] in ("line_shaft",)]
    for p in sorted(only, key=lambda p: 0 if p["name"].endswith("housing") else 1):
        fc = COMP_FILL.get(p["component"], FILL)
        for pr in p["add"]:
            r = D.resolve(pr)
            if p["name"] == "line_shaft" and abs(r["r"] - P["brg_d"] / 2) > 1e-6:
                continue
            for sh in D.project(r, "end"):
                ax.add_patch(_patch(sh, "white" if (sh[0] == "circle" and pr["type"] == "tube" and sh is D.project(r, "end")[-1]) else fc))
        for pr in p["sub"]:
            for sh in D.project(D.resolve(pr), "end"):
                ax.add_patch(_patch(sh, "white", lw=0.6))
    layer = {"outer_ring": 5, "ball": 7, "inner_ring": 8}
    for p in only:                                       # rings and balls on top of the bore
        kind = next((k for k in layer if k in p["name"]), None)
        if kind is None:
            continue
        for pr in p["add"]:
            shs = D.project(D.resolve(pr), "end")
            ax.add_patch(_patch(shs[0], "#94a3b8" if kind == "ball" else COMP_FILL["test_bearing"], z=layer[kind]))
            if len(shs) > 1:
                ax.add_patch(_patch(shs[1], "white", z=layer[kind] + 0.5))
    ax.add_patch(Circle((0, h), P["brg_d"] / 2, fc="#d1d5db", ec=INK, lw=0.6, zorder=9))
    s1 = next(s for s in D.SENSORS if s["id"] == "S1")
    for sh in D.project(D.resolve(s1["geom"]), "end"):
        ax.add_patch(_patch(sh, SENS, z=8))
    ax.text(14, h + P["hsg_top"] + 8, "S1 accelerometer", color=SENS, fontsize=7)
    centreline(ax, -70, 70, h); centreline(ax, -20, 200, 0, vertical=True)
    dim_v(ax, -80, 0, h, f"{h:.0f}", ext_from=(-55, -10))
    dim_v(ax, 80, 0, h + P["hsg_top"], ext_from=(55, 55))
    dim_h(ax, -P["hsg_w"] / 2, P["hsg_w"] / 2, -18, ext_from=(0, 0))
    ax.annotate(f"bore Ø{P['brg_od']:.0f} H7 / bearing 6203\n(d {P['brg_d']:.0f}, D {P['brg_od']:.0f}, "
                f"B {P['brg_b']:.0f}, {int(P['ball_n'])} balls Ø{P['ball_d']})", (P["brg_od"] / 2 * 0.7, h + 14),
                (20, 228), fontsize=6.5, arrowprops=dict(arrowstyle="-", lw=0.5), zorder=TOP)
    # detail B: gear mesh
    ax = _view_axes(fig, [0.35, 0.30, 0.30, 0.66], (-40, 140), (40, 250), "DETAIL B - GEAR MESH (end view)")
    for nm in ("gear_wheel", "pinion"):
        p = next(q for q in D.parts() if q["name"] == nm)
        for sh in D.project(D.resolve(p["add"][0]), "end"):
            ax.add_patch(_patch(sh, COMP_FILL["gearbox"] if sh[0] == "poly" else "white", lw=0.5))
    ay = D.ev("out_y")
    centreline(ax, -30, 130, h); centreline(ax, 80, 200, 0, vertical=True); centreline(ax, 80, 200, ay, vertical=True)
    dim_h(ax, 0, ay, 212, f"a = {D.ev('centre_dist'):.0f}", ext_from=(h + 30, h + 60))
    ax.text(-35, 60, "\n".join([f"module m = {P['gear_m']:g}", f"pinion z = {int(P['z_pinion'])}, gear z = {int(P['z_gear'])}",
                                f"ratio {P['z_gear'] / P['z_pinion']:g} : 1, face width {P['gear_b']:.0f}",
                                "tooth form simplified (trapezoidal),", "not involute - visual only"]), fontsize=7)
    # checks table
    tab = fig.add_axes([0.67, 0.30, 0.31, 0.66]); tab.axis("off")
    tab.text(0, 0.98, "Representative sizing checks", fontsize=10, fontweight="bold", va="top")
    rows = [("Assumed duty", "1.1 kW, 1500 rpm; 1000 N radial on test bearing"),
            ("Motor torque", f"{checks['motor_torque_Nm']} N m"),
            ("Shaft shear stress (Ø17)", f"{checks['shaft_shear_stress_MPa_at_d17']} MPa"),
            ("Bearing L10 (6203, C 9.95 kN)", f"{checks['bearing_L10_million_rev']:.0f} Mrev "
                                              f"= {checks['bearing_L10_hours_at_1500rpm']:.0f} h"),
            ("Gear ratio / centre distance", f"{checks['gear_ratio']} / {checks['centre_distance_mm']:.0f} mm"),
            ("Output speed / torque", f"{checks['output_speed_rpm']:.0f} rpm / {checks['output_torque_Nm']} N m"),
            ("Pinion tangential load", f"{checks['pinion_tangential_load_N']:.0f} N"),
            ("Pinion Lewis bending stress", f"{checks['pinion_lewis_bending_stress_MPa']} MPa"),
            ("Line-shaft 1st critical speed", f"~{checks['line_shaft_first_critical_speed_rpm']:.0f} rpm "
                                              f"({checks['critical_speed_margin']}x running speed)")]
    y = 0.92
    for k, v in rows:
        tab.text(0, y, k, fontsize=7.5, va="top"); tab.text(0.55, y, v, fontsize=7.5, va="top", fontweight="bold")
        y -= 0.05
    tab.text(0, y - 0.02, "\n".join([
        "Textbook formulas (Lewis, L10 = (C/P)^3, Dunkerley-type lumped mass).",
        "They show the chosen dimensions are plausible for the assumed duty.",
        "They are not a validated design and were not compared with either",
        "dataset's test bench."]), fontsize=7, va="top", color="#4b5563")
    pdf.savefig(fig); fig.savefig(DRW / "sheet4_details.png", dpi=110); plt.close(fig)


def main():
    DRW.mkdir(parents=True, exist_ok=True)
    checks = D.design_checks()
    inter = D.interference_check(step=0.5)
    (OUT / "design_checks.json").write_text(json.dumps(checks, indent=2))
    (OUT / "interference_check.json").write_text(json.dumps(inter, indent=2))
    (OUT / "sensor_map.json").write_text(json.dumps(D.sensor_map(), indent=2))
    with PdfPages(DRW / "ivhm_drivetrain_drawings.pdf") as pdf:
        sheet_ga(pdf)
        sheet_sensors(pdf)
        sheet_exploded(pdf)
        sheet_details(pdf, checks)
        meta = pdf.infodict()
        meta["Title"] = "IVHM representative drivetrain - drawings"
        meta["Subject"] = "Representative assembly; not a reconstruction of the Paderborn or MCC5-THU benches"
    fig = plt.figure(figsize=(12, 4.6))
    ax = fig.add_axes([0, 0, 1, 1], projection="3d")
    draw3d(ax, exploded=False)
    fig.savefig(OUT / "iso_assembled.png", dpi=130, facecolor="white", bbox_inches="tight", pad_inches=0.05); plt.close(fig)
    print(f"drawings: {DRW / 'ivhm_drivetrain_drawings.pdf'}")
    print(f"interference: {len(inter['overlaps'])} overlaps among {inter['pairs_checked']} pairs; "
          f"unexpected {len(inter['unexpected'])}")
    return 0 if not inter["unexpected"] else 1


if __name__ == "__main__":
    sys.exit(main())
