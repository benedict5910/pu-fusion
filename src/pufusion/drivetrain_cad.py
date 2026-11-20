"""Representative electric-drive assembly used by the OB4 virtual testbed (single source of truth).

REPRESENTATIVE, NOT A RECONSTRUCTION. The Paderborn bearing data and the MCC5-THU gearbox data come from two
different laboratory test benches. This assembly is one plausible bench drivetrain that shows *where* each
dataset's sensors sit on a motor-shaft-bearing-coupling-gearbox line. Its dimensions are engineering choices made
for this project (see `design_checks`), not measurements of either test bench.

Everything here is plain Python (no FreeCAD), so the same numbers drive:
  * cad/build_freecad.py   - the editable FreeCAD model (FCStd), STEP exports and the FreeCAD self-check report
  * cad/make_drawings.py   - dimensioned orthographic views, exploded view, sensor-location map
  * the dashboard          - the CAD-linked testbed view (app/testbed_view.py)

Coordinates: millimetres. x along the drive axis (motor at small x), y horizontal across the bench, z up;
z = 0 is the top face of the base plate. Every dimension of a part is an arithmetic expression over PARAMS, so a
change in PARAMS (or in the FreeCAD spreadsheet `Params`, which holds the same names) moves the dependent parts.
"""
from __future__ import annotations

import ast
import math
import re

# --------------------------------------------------------------------------------------------- parameters
# name: (value in mm unless stated, description)
PARAMS = {
    "shaft_h": (140.0, "shaft centre height above the base plate"),
    "base_x0": (-30.0, "base plate start (x)"), "base_l": (1160.0, "base plate length"),
    "base_y0": (-140.0, "base plate start (y)"), "base_w": (340.0, "base plate width"),
    "base_t": (20.0, "base plate thickness"),
    # motor (IEC 90 frame proportions: 90 mm shaft height from the feet, 24 mm shaft)
    "mot_x0": (40.0, "motor body start (non-drive end)"), "mot_l": (240.0, "motor body length"),
    "mot_d": (180.0, "motor body diameter"), "mot_shaft_d": (24.0, "motor shaft diameter"),
    "es_t": (15.0, "drive-end shield thickness"), "es_d": (170.0, "drive-end shield diameter"),
    "riser_h": (50.0, "motor riser height (shaft centre height minus the 90 mm IEC shaft height)"),
    "tb_l": (90.0, "terminal box length"), "tb_w": (90.0, "terminal box width"), "tb_h": (60.0, "terminal box height"),
    "cable_d": (12.0, "motor supply cable diameter"), "cable_l": (75.0, "motor supply cable length shown"),
    # flexible jaw couplings
    "cpl_d": (65.0, "coupling hub diameter"), "cpl_hub": (30.0, "coupling hub length"),
    "cpl_gap": (10.0, "coupling spider (elastomer) length"), "spider_d": (55.0, "spider diameter"),
    # line shaft and bearings (6203: d 17, D 40, B 12)
    "brg_d": (17.0, "bearing bore = journal diameter"), "brg_od": (40.0, "bearing outer diameter"),
    "brg_b": (12.0, "bearing width"), "ball_d": (6.747, "ball diameter (6203)"), "ball_n": (8, "number of balls"),
    "shaft_d": (20.0, "line shaft diameter at the couplings"), "shoulder_d": (22.0, "line shaft diameter between bearings"),
    "brg_a_x": (450.0, "support bearing centre (x)"), "brg_b_x": (610.0, "test bearing centre (x)"),
    "hsg_t": (24.0, "bearing housing thickness (x)"), "hsg_w": (110.0, "bearing housing width (y)"),
    "hsg_top": (45.0, "bearing housing height above the shaft centre"),
    # gearbox: single-stage spur reduction, parallel shafts in a horizontal plane
    "gb_x0": (780.0, "gearbox housing start (x)"), "gb_l": (140.0, "gearbox housing length (x)"),
    "gb_wall": (12.0, "gearbox wall thickness (= bearing width)"), "gb_y0": (-45.0, "gearbox housing start (y)"),
    "gb_w": (182.0, "gearbox housing width (y)"), "gb_z0": (70.0, "gearbox housing bottom (z)"),
    "gb_top": (210.0, "gearbox housing top (z)"), "gb_cover_t": (12.0, "gearbox cover thickness"),
    "gear_m": (2.0, "gear module"), "z_pinion": (20, "pinion teeth"), "z_gear": (50, "gear teeth"),
    "gear_b": (20.0, "gear face width"), "gear_x": (840.0, "gear face start (x)"),
    # load (brake) unit
    "load_x0": (1030.0, "load unit start (x)"), "load_l": (70.0, "load unit length"), "load_d": (140.0, "load unit diameter"),
}
P = {k: v[0] for k, v in PARAMS.items()}
# derived values (also written to the FreeCAD spreadsheet as plain numbers)
DERIVED = {
    "centre_dist": "gear_m * (z_pinion + z_gear) / 2",
    "out_y": "gear_m * (z_pinion + z_gear) / 2",          # output shaft lies at y = centre distance
    "mot_x1": "mot_x0 + mot_l",
    "cpl1_x": "mot_x0 + mot_l + es_t + 35",              # first coupling hub start
    "cpl2_x": "690",
    "cpl3_x": "940",
}


def _names(expr):
    return {n.id for n in ast.walk(ast.parse(str(expr), mode="eval")) if isinstance(n, ast.Name)}


def ev(expr, params=None):
    """Evaluate an arithmetic expression over the parameters (no builtins, no attribute access)."""
    env = dict(P if params is None else params)
    for k, e in DERIVED.items():
        env.setdefault(k, None)
    for k, e in DERIVED.items():
        env[k] = eval(compile(ast.parse(e, mode="eval"), "<derived>", "eval"), {"__builtins__": {}}, env)
    tree = ast.parse(str(expr), mode="eval")
    for node in ast.walk(tree):
        if not isinstance(node, (ast.Expression, ast.BinOp, ast.UnaryOp, ast.Constant, ast.Name, ast.Load,
                                 ast.Add, ast.Sub, ast.Mult, ast.Div, ast.USub, ast.UAdd)):
            raise ValueError(f"unsupported expression element {type(node).__name__} in {expr!r}")
    unknown = _names(expr) - set(env)
    if unknown:
        raise KeyError(f"unknown parameter(s) {sorted(unknown)} in {expr!r}")
    return float(eval(compile(tree, "<expr>", "eval"), {"__builtins__": {}}, env))


def freecad_expr(expr):
    """Same expression for a FreeCAD property bound to the `Params` spreadsheet (aliases = parameter names)."""
    known = set(P) | set(DERIVED)
    return re.sub(r"\b([A-Za-z_][A-Za-z0-9_]*)\b",
                  lambda m: f"Params.{m.group(1)}" if m.group(1) in known else m.group(1), str(expr))


# --------------------------------------------------------------------------------------------- primitives
def box(x, y, z, L, W, H):
    return {"type": "box", "x": x, "y": y, "z": z, "L": L, "W": W, "H": H}


def cyl(axis, x, y, z, r, h):
    """Cylinder whose axis starts at (x, y, z) and runs h along +axis."""
    return {"type": "cyl", "axis": axis, "x": x, "y": y, "z": z, "r": r, "h": h}


def tube(axis, x, y, z, ro, ri, h):
    return {"type": "tube", "axis": axis, "x": x, "y": y, "z": z, "ro": ro, "ri": ri, "h": h}


def sphere(x, y, z, r):
    return {"type": "sphere", "x": x, "y": y, "z": z, "r": r}


def gear(x, y, z, teeth, module, width, bore, phase=0.0):
    return {"type": "gear", "axis": "x", "x": x, "y": y, "z": z, "teeth": teeth, "module": module,
            "width": width, "bore": bore, "phase": phase}


def prism(axis, x, y, z, poly, h):
    """Straight prism: the polygon `poly` [(u, v), ...] (plain numbers, mm, relative to (x, y, z)) extruded h along
    +axis. (u, v) are the two other axes in x-y-z order: axis x -> (y, z), axis y -> (x, z), axis z -> (x, y).
    Used for cooling fins, ribs, gussets and hexagon bolt heads. The position (x, y, z) and h are expressions, so a
    prism moves with the parameters; its cross-section is fixed."""
    return {"type": "prism", "axis": axis, "x": x, "y": y, "z": z, "poly": [(float(u), float(v)) for u, v in poly], "h": h}


def _involute(r_base, r):
    a = math.acos(min(1.0, r_base / r))
    return math.tan(a) - a


def gear_outline(teeth, module, phase=0.0, pressure_deg=20.0, backlash=0.10, n_flank=6):
    """Involute spur-gear tooth outline (standard addendum m, dedendum 1.25 m, 20 deg pressure angle) in the plane
    normal to the gear axis. Each flank is the involute of the base circle, sampled at n_flank radii; below the base
    circle (small tooth counts) the flank continues radially to the root circle. `backlash` (mm, on the pitch circle)
    thins every tooth so a correctly spaced pair does not touch. Returns [(u, v)] around the gear centre.
    Polygonal approximation for visualisation and clearance checks - not for load or contact analysis."""
    rp = module * teeth / 2
    ra, rf = rp + module, rp - 1.25 * module
    rb = rp * math.cos(math.radians(pressure_deg))
    pitch = 2 * math.pi / teeth
    half_pitch_angle = (math.pi * module / 2 - backlash) / (2 * rp)          # half tooth thickness at the pitch circle
    inv_p = _involute(rb, rp)
    r_start = max(rb, rf)
    radii = [r_start + (ra - r_start) * k / (n_flank - 1) for k in range(n_flank)]
    half = [half_pitch_angle + inv_p - _involute(rb, r) for r in radii]   # half-angle of the tooth at each radius
    pts = []
    for k in range(teeth):
        a0 = k * pitch + phase
        flank = []
        if rf < r_start:
            flank.append((rf, half[0]))
        flank += list(zip(radii, half))
        for r, h in flank:                                                 # one flank, root -> tip
            pts.append((r * math.cos(a0 - h), r * math.sin(a0 - h)))
        for r, h in reversed(flank):                                       # other flank, tip -> root
            pts.append((r * math.cos(a0 + h), r * math.sin(a0 + h)))
        root_mid = a0 + pitch / 2
        pts.append((rf * math.cos(root_mid), rf * math.sin(root_mid)))
    return pts


def hexagon(across_flats):
    """Regular hexagon [(u, v)] with the given width across flats (bolt heads and nuts)."""
    rc = across_flats / math.sqrt(3)
    return [(rc * math.cos(math.radians(30 + 60 * k)), rc * math.sin(math.radians(30 + 60 * k))) for k in range(6)]


def radial_fin(r0, r1, t, angle_deg):
    """Rectangular fin section [(u, v)] from radius r0 to r1, thickness t, at angle_deg around the origin."""
    a = math.radians(angle_deg)
    c, s_ = math.cos(a), math.sin(a)
    n = (-s_ * t / 2, c * t / 2)
    return [(r0 * c - n[0], r0 * s_ - n[1]), (r1 * c - n[0], r1 * s_ - n[1]),
            (r1 * c + n[0], r1 * s_ + n[1]), (r0 * c + n[0], r0 * s_ + n[1])]


def bolt_z(x, y, z_face, s=13.0, k=5.5, washer=True):
    """Hexagon bolt head (across flats s, height k) and washer standing on a horizontal face at z_face.
    Both are embedded 0.4 mm into the face so they fuse with the part they fasten."""
    out = []
    z0 = f"({z_face}) - 0.4"
    if washer:
        out.append(cyl("z", x, y, z0, 0.62 * s, 2.0))
        out.append(prism("z", x, y, f"({z_face}) + 1.3", hexagon(s), k))
    else:
        out.append(prism("z", x, y, z0, hexagon(s), k + 0.4))
    return out


def bolt_x(x_face, y, z, direction, s=8.0, k=4.0):
    """Hexagon bolt head on a face normal to x at x_face, protruding k in `direction` (+1 or -1)."""
    x0 = f"({x_face}) - 0.4" if direction > 0 else f"({x_face}) - {k}"
    return [prism("x", x0, y, z, hexagon(s), k + 0.4)]


def bolt_circle_x(x_face, yc, zc, pitch_r, n, direction, s=8.0, k=4.0, start_deg=45.0):
    out = []
    for i in range(n):
        a = math.radians(start_deg + 360.0 * i / n)
        out += bolt_x(x_face, f"({yc}) + ({pitch_r * math.cos(a):.4f})", f"({zc}) + ({pitch_r * math.sin(a):.4f})",
                      direction, s, k)
    return out


def axial_fins(x0, yc, zc, length, r0, r1, t, angles):
    """Axial cooling fins (prisms along x) around the axis through (yc, zc)."""
    r0, r1 = ev(r0), ev(r1)                    # fin section is fixed geometry (evaluated at the default parameters)
    return [prism("x", x0, yc, zc, radial_fin(r0, r1, t, a), length) for a in angles]


# --------------------------------------------------------------------------------------------- the assembly
def _bearing(prefix, comp, xc, yc, zc, purpose):
    """6203-proportioned deep-groove ball bearing: rings + balls (no grooves or cage: representative)."""
    parts = [
        {"name": f"{prefix}_outer_ring", "component": comp, "add": [tube("x", f"{xc} - brg_b / 2", yc, zc,
                                                                          "brg_od / 2", "brg_od / 2 - 2.5", "brg_b")]},
        {"name": f"{prefix}_inner_ring", "component": comp, "add": [tube("x", f"{xc} - brg_b / 2", yc, zc,
                                                                          "brg_d / 2 + 2", "brg_d / 2", "brg_b")]},
    ]
    n = int(P["ball_n"])
    rpitch = (P["brg_od"] / 2 - 2.5 + P["brg_d"] / 2 + 2) / 2
    for k in range(n):
        a = 2 * math.pi * k / n
        parts.append({"name": f"{prefix}_ball_{k + 1}", "component": comp,
                      "add": [sphere(xc, f"{yc} + ({rpitch * math.cos(a):.4f})", f"{zc} + ({rpitch * math.sin(a):.4f})",
                                     "ball_d / 2")]})
    for p in parts:
        p["purpose"] = purpose
    return parts


def _coupling(prefix, x0, yc, bore_in, bore_out):
    """Flanged jaw coupling: each hub is a neck plus a flange with six hexagon bolt heads; elastomer spider between.
    Overall length and diameter are unchanged (cpl_hub, cpl_gap, cpl_d)."""
    hub, z = "cpl_hub", "shaft_h"
    neck_r = "cpl_d / 2 - 10.5"
    bolts_in = bolt_circle_x(f"{x0} + 12", yc, z, 26.0, 6, -1, s=7.0, k=3.5, start_deg=30.0)
    bolts_out = bolt_circle_x(f"{x0} + {hub} + cpl_gap + {hub} - 12", yc, z, 26.0, 6, +1, s=7.0, k=3.5, start_deg=30.0)
    return [
        {"name": f"{prefix}_hub_in", "component": prefix, "finish": "black_oxide",
         "add": [tube("x", x0, yc, z, neck_r, bore_in, 12.5),
                 tube("x", f"{x0} + 12", yc, z, "cpl_d / 2", bore_in, f"{hub} - 12")] + bolts_in},
        {"name": f"{prefix}_spider", "component": prefix, "finish": "elastomer",
         "add": [cyl("x", f"{x0} + {hub}", yc, z, "spider_d / 2", "cpl_gap")]},
        {"name": f"{prefix}_hub_out", "component": prefix, "finish": "black_oxide",
         "add": [tube("x", f"{x0} + {hub} + cpl_gap", yc, z, "cpl_d / 2", bore_out, f"{hub} - 12"),
                 tube("x", f"{x0} + {hub} + cpl_gap + {hub} - 12.5", yc, z, neck_r, bore_out, 12.5)] + bolts_out},
    ]


# cooling-fin angles (degrees, 0 = +y, 90 = up), chosen to clear the terminal box, the feet and the pedestals
MOTOR_FIN_ANGLES = [a for a in range(-60, 61, 10)] + [a for a in range(120, 241, 10)]
LOAD_FIN_ANGLES = [-60, -40, -20, 0, 20, 40, 60, 120, 140, 160, 180, 200, 220, 240]


def _grille_holes(x0, yc, zc, length):
    """Ventilation holes of the fan cowl: concentric rings of round holes."""
    holes = [cyl("x", x0, yc, zc, 5.0, length)]
    for ring_r, n in ((19.0, 6), (34.0, 12), (49.0, 16), (64.0, 22)):
        for k in range(n):
            a = 2 * math.pi * (k + 0.5 * (n % 4 == 0)) / n
            holes.append(cyl("x", x0, f"({yc}) + ({ring_r * math.cos(a):.4f})", f"({zc}) + ({ring_r * math.sin(a):.4f})",
                             4.2, length))
    return holes


def parts():
    """Every solid of the assembly: {'name', 'component', 'add': [primitives], 'sub': [primitives], 'finish'}.

    Detail (fins, bolts, ribs, bosses) is fused into the part it belongs to, so every part stays ONE solid and the
    part list, names, components, sensor mounts and explode offsets keep their meaning."""
    P_ = []
    # ---- base plate: four anchor holes with nuts, six levelling feet
    corners = ((30, 30), (30, 310), (1130, 30), (1130, 310))
    feet = []
    for fx in ("base_x0 + 90", "base_x0 + base_l / 2", "base_x0 + base_l - 90"):
        for fy in ("base_y0 + 45", "base_y0 + base_w - 45"):
            feet += [cyl("z", fx, fy, "-base_t - 30", 22, 30.4), cyl("z", fx, fy, "-base_t - 36", 27, 6.4)]
    nuts = []
    for dx, dy in corners:
        nuts += [prism("z", f"base_x0 + {dx}", f"base_y0 + {dy}", -0.4, hexagon(19), 8.4),
                 cyl("z", f"base_x0 + {dx}", f"base_y0 + {dy}", 7.5, 6, 5.5)]
    P_ += [{"name": "base_plate", "component": "base", "finish": "plate",
            "add": [box("base_x0", "base_y0", "-base_t", "base_l", "base_w", "base_t")] + feet + nuts,
            "sub": [cyl("z", f"base_x0 + {dx}", f"base_y0 + {dy}", "-base_t - 1", 7, "base_t + 2") for dx, dy in corners]}]
    # ---- motor (IEC-style TEFC: finned frame, fan cowl with grille, terminal box with gland, lifting eye, feet)
    P_ += [{"name": "motor_riser", "component": "motor", "finish": "painted_dark",
            "add": [box("mot_x0", -90, 0, "mot_l", 180, "riser_h")]
            + [b for bx in ("mot_x0 + 10", "mot_x1 - 10") for by in (-80, 80) for b in bolt_z(bx, by, "riser_h")]},
           {"name": "motor_body", "component": "motor", "finish": "painted",
            "add": [cyl("x", "mot_x0", 0, "shaft_h", "mot_d / 2", "mot_l"),
                    box("mot_x0 + 20", -75, "riser_h", "mot_l - 40", 150, 12),            # feet pad
                    box("mot_x0 + 110", -30, "shaft_h + mot_d / 2 - 10", 70, 60, 10)]    # terminal-box seat
            + axial_fins("mot_x0 + 10", 0, "shaft_h", "mot_l - 20", "mot_d / 2 - 2", "mot_d / 2 + 10", 4, MOTOR_FIN_ANGLES)
            + [cyl("z", "mot_x0 + 40", 0, "shaft_h + mot_d / 2 - 3", 9, 10),                # lifting-eye boss
               tube("y", "mot_x0 + 40", -4, "shaft_h + mot_d / 2 + 18", 13, 7, 8)]},       # lifting eye
           {"name": "motor_fan_cowl", "component": "motor", "finish": "painted",
            "purpose": "fan cowl with ventilation grille (non-drive end)",
            "add": [tube("x", "mot_x0 - 46", 0, "shaft_h", "mot_d / 2 - 2", "mot_d / 2 - 6", 46),
                    cyl("x", "mot_x0 - 52", 0, "shaft_h", "mot_d / 2 - 2", 6.4)],
            "sub": _grille_holes("mot_x0 - 53", 0, "shaft_h", 8)},
           {"name": "motor_end_shield", "component": "motor", "finish": "painted",
            "add": [cyl("x", "mot_x1", 0, "shaft_h", "es_d / 2", "es_t"),
                    tube("x", "mot_x1 + es_t - 0.4", 0, "shaft_h", 32, "mot_shaft_d / 2 + 0.5", 8.4)]   # bearing cap
            + bolt_circle_x("mot_x1 + es_t", 0, "shaft_h", 72.0, 6, +1, s=10.0, k=5.0, start_deg=0.0)
            + bolt_circle_x("mot_x1 + es_t + 8", 0, "shaft_h", 25.0, 4, +1, s=6.0, k=3.0)},
           {"name": "motor_terminal_box", "component": "motor", "finish": "painted",
            "add": [box("mot_x0 + 100", "-tb_w / 2", "shaft_h + mot_d / 2", "tb_l", "tb_w", "tb_h"),
                    box("mot_x0 + 97", "-tb_w / 2 - 3", "shaft_h + mot_d / 2 + tb_h - 0.4", "tb_l + 6", "tb_w + 6", 5.4),
                    tube("y", "mot_x0 + 100 + tb_l / 2", "tb_w / 2 - 0.4", "shaft_h + mot_d / 2 + tb_h / 2", 10, "cable_d / 2", 8.4),
                    tube("y", "mot_x0 + 100 + tb_l / 2", "tb_w / 2 + 7.6", "shaft_h + mot_d / 2 + tb_h / 2", 8, "cable_d / 2", 5),
                    cyl("y", "mot_x0 + 100 + tb_l / 2", "-tb_w / 2 - 8", "shaft_h + mot_d / 2 + tb_h / 2", 9, 8.4)]  # blanking plug
            + [cyl("z", f"mot_x0 + 100 + {dx}", dy, "shaft_h + mot_d / 2 + tb_h + 4.6", 3.2, 2.4)
               for dx in (6, 84) for dy in (-39, 39)]},
           {"name": "motor_supply_cable", "component": "motor", "finish": "cable",
            "add": [cyl("y", "mot_x0 + 100 + tb_l / 2", "tb_w / 2", "shaft_h + mot_d / 2 + tb_h / 2", "cable_d / 2", "cable_l")]},
           {"name": "motor_shaft", "component": "motor", "finish": "machined",
            "add": [cyl("x", "mot_x1 + es_t", 0, "shaft_h", "mot_shaft_d / 2", "cpl1_x + cpl_hub - (mot_x1 + es_t)")]}]
    # coupling 1: motor shaft (24) -> line shaft (20); motor shaft ends at the spider
    P_ += _coupling("coupling_1", "cpl1_x", 0, "mot_shaft_d / 2", "shaft_d / 2")
    # ---- line shaft (stepped) between coupling 1 and coupling 2, with a locking collar either side of each bearing
    c1_end = "cpl1_x + 2 * cpl_hub + cpl_gap"
    collars = []
    for xc in ("brg_a_x", "brg_b_x"):
        for x0 in (f"{xc} - 24", f"{xc} + 14"):
            collars += [cyl("x", x0, 0, "shaft_h", 15, 10),                                  # collar + 2 set screws
                        cyl("y", f"{x0} + 5", 14, "shaft_h", 2.5, 3.5), cyl("y", f"{x0} + 5", -17.5, "shaft_h", 2.5, 3.5)]
    P_ += [{"name": "line_shaft", "component": "line_shaft", "finish": "machined", "add": [
        cyl("x", "cpl1_x + cpl_hub + cpl_gap", 0, "shaft_h", "shaft_d / 2", f"brg_a_x - brg_b / 2 - 4 - (cpl1_x + cpl_hub + cpl_gap)"),
        cyl("x", "brg_a_x - brg_b / 2 - 4", 0, "shaft_h", "brg_d / 2", "brg_b + 8"),
        cyl("x", "brg_a_x + brg_b / 2 + 4", 0, "shaft_h", "shoulder_d / 2", "brg_b_x - brg_a_x - brg_b - 8"),
        cyl("x", "brg_b_x - brg_b / 2 - 4", 0, "shaft_h", "brg_d / 2", "brg_b + 8"),
        cyl("x", "brg_b_x + brg_b / 2 + 4", 0, "shaft_h", "shaft_d / 2", "cpl2_x + cpl_hub - (brg_b_x + brg_b / 2 + 4)")]
        + collars}]
    assert ev(c1_end) <= P["brg_a_x"] - P["hsg_t"] / 2
    for tag, xc, purpose in (("support_bearing", "brg_a_x", "support bearing (drive end)"),
                             ("test_bearing", "brg_b_x", "monitored test bearing (Paderborn sensor analogue)")):
        gusset_l = [(-30.0, 13.6), (-11.6, 13.6), (-11.6, 70.0)]
        gusset_r = [(11.6, 13.6), (30.0, 13.6), (11.6, 70.0)]
        hsg = [box(f"{xc} - hsg_t / 2", "-hsg_w / 2", 0, "hsg_t", "hsg_w", "shaft_h + hsg_top"),
               box(f"{xc} - hsg_t / 2 - 18", "-hsg_w / 2", 0, "hsg_t + 36", "hsg_w", 14),           # foot flange
               cyl("x", f"{xc} - hsg_t / 2 - 4", 0, "shaft_h", 30, 4.4),                          # bore bosses
               cyl("x", f"{xc} + hsg_t / 2 - 0.4", 0, "shaft_h", 30, 4.4),
               cyl("z", xc, 30, "shaft_h + hsg_top - 0.4", 4, 8.4),                               # grease nipple
               cyl("z", xc, 30, "shaft_h + hsg_top + 6", 2.5, 4)]
        hsg += [prism("y", xc, y0, 0, g, 8) for y0 in ("-hsg_w / 2", "hsg_w / 2 - 8") for g in (gusset_l, gusset_r)]
        hsg += [b for bx in (f"{xc} - 22", f"{xc} + 22") for by in (-32, 32) for b in bolt_z(bx, by, 14, s=13, k=5.5)]
        hsg += bolt_circle_x(f"{xc} - hsg_t / 2 - 4", 0, "shaft_h", 25.0, 4, -1, s=5.5, k=3.0)
        hsg += bolt_circle_x(f"{xc} + hsg_t / 2 + 4", 0, "shaft_h", 25.0, 4, +1, s=5.5, k=3.0)
        P_ += [{"name": f"{tag}_housing", "component": tag, "purpose": purpose, "finish": "cast",
                "add": hsg,
                "sub": [cyl("x", f"{xc} - hsg_t / 2 - 19", 0, "shaft_h", "brg_od / 2", "hsg_t + 38")]}]
        P_ += _bearing(tag, tag, xc, 0, "shaft_h", purpose)
    # coupling 2: line shaft (20) -> gearbox input shaft (17)
    P_ += _coupling("coupling_2", "cpl2_x", 0, "shaft_d / 2", "brg_d / 2")
    # ---- gearbox: ribbed housing with split-line and foot flanges, bearing bosses / blind caps, inspection cover
    gx1 = "gb_x0 + gb_l"
    gb = [box("gb_x0", "gb_y0", "gb_z0", "gb_l", "gb_w", "gb_top - gb_z0"),
          box("gb_x0 - 10", "gb_y0 - 12", "gb_z0", "gb_l + 20", "gb_w + 24", 12),                 # foot flange
          box("gb_x0 - 6", "gb_y0 - 6", "gb_top - 12", "gb_l + 12", "gb_w + 12", 12)]             # split-line flange
    for xf, d in (("gb_x0", -1), (gx1, +1)):                         # bosses (open bore) and blind caps on both ends
        x0 = f"{xf} - 8" if d < 0 else f"{xf} - 0.4"
        open_y, cap_y = (0, "out_y") if d < 0 else ("out_y", 0)
        gb += [tube("x", x0, open_y, "shaft_h", 32, "brg_od / 2", 8.4), cyl("x", x0, cap_y, "shaft_h", 32, 8.4)]
        for yy in (0, "out_y"):
            gb += bolt_circle_x(f"{xf} - 8" if d < 0 else f"{xf} + 8", yy, "shaft_h", 26.0, 4, d, s=6.0, k=3.5)
            gb.append(box(f"{xf} - 8" if d < 0 else f"{xf} - 0.4", f"({yy}) - 4", "gb_z0 + 11.6", 8.4, 8,
                          "shaft_h - 32 - gb_z0 - 11.2"))                                           # rib under the boss
    for rx in (25, 55, 85, 115):                                       # vertical ribs, +y wall
        gb.append(box(f"gb_x0 + {rx} - 4", "gb_y0 + gb_w - 0.4", "gb_z0 + 11.6", 8, 8.4, "gb_top - gb_z0 - 23.2"))
    for rx in (55, 85, 115):                                           # -y wall (S4 sits at the input end)
        gb.append(box(f"gb_x0 + {rx} - 4", "gb_y0 - 8", "gb_z0 + 11.6", 8, 8.4, "gb_top - gb_z0 - 23.2"))
    gb += [b for bx in ("gb_x0 - 2", "gb_x0 + gb_l + 2") for by in ("gb_y0 - 6", "gb_y0 + gb_w + 6")
           for b in bolt_z(bx, by, "gb_z0 + 12", s=13, k=5.5)]
    cover = [box("gb_x0 - 6", "gb_y0 - 6", "gb_top", "gb_l + 12", "gb_w + 12", "gb_cover_t"),
             box("gb_x0 + 35", "gb_y0 + 40", "gb_top + gb_cover_t - 0.4", 70, 90, 5.4),            # inspection cover
             cyl("z", "gb_x0 + gb_l - 20", "gb_y0 + gb_w - 25", "gb_top + gb_cover_t - 0.4", 5, 12.4),   # breather
             cyl("z", "gb_x0 + gb_l - 20", "gb_y0 + gb_w - 25", "gb_top + gb_cover_t + 10", 8, 5)]
    for ex in ("gb_x0 + 12", "gb_x0 + gb_l - 12"):                    # lifting eyes
        cover += [cyl("z", ex, "gb_y0 + gb_w / 2", "gb_top + gb_cover_t - 0.4", 9, 8.4),
                  tube("x", f"{ex} - 4", "gb_y0 + gb_w / 2", "gb_top + gb_cover_t + 20", 13, 7, 8)]
    cover += [cyl("z", f"gb_x0 + {dx}", f"gb_y0 + {dy}", "gb_top + gb_cover_t + 4.6", 3, 2.4)
              for dx in (41, 99) for dy in (46, 124)]
    cover += [b for bx in ("gb_x0", "gb_x0 + gb_l / 2", "gb_x0 + gb_l") for by in ("gb_y0", "gb_y0 + gb_w")
              for b in bolt_z(bx, by, "gb_top + gb_cover_t", s=10, k=4.5, washer=False)]
    P_ += [{"name": "gearbox_plinth", "component": "gearbox", "finish": "painted_dark",
            "add": [box("gb_x0 + 10", "gb_y0 + 10", 0, "gb_l - 20", "gb_w - 20", "gb_z0"),
                    box("gb_x0 + 2", "gb_y0 + 2", 0, "gb_l - 4", "gb_w - 4", 10)]
            + [b for bx in ("gb_x0 + 6", "gb_x0 + gb_l - 6") for by in ("gb_y0 + 6", "gb_y0 + gb_w - 6")
               for b in bolt_z(bx, by, 10, s=10, k=4.5, washer=False)]},
           {"name": "gearbox_housing", "component": "gearbox", "finish": "cast",
            "add": gb,
            "sub": [box("gb_x0 + gb_wall", "gb_y0 + gb_wall", "gb_z0 + gb_wall", "gb_l - 2 * gb_wall",
                        "gb_w - 2 * gb_wall", "gb_top - gb_z0")]
            + [cyl("x", "gb_x0 - 1", yy, "shaft_h", "brg_od / 2", "gb_l + 2") for yy in (0, "out_y")]},
           {"name": "gearbox_cover", "component": "gearbox", "finish": "cast", "add": cover},
           {"name": "gearbox_input_shaft", "component": "gearbox", "finish": "machined",
            "add": [cyl("x", "cpl2_x + cpl_hub + cpl_gap", 0, "shaft_h", "brg_d / 2", f"{gx1} - (cpl2_x + cpl_hub + cpl_gap)")]},
           {"name": "gearbox_output_shaft", "component": "gearbox", "finish": "machined",
            "add": [cyl("x", "gb_x0", "out_y", "shaft_h", "brg_d / 2", "cpl3_x + cpl_hub - gb_x0")]},
           {"name": "pinion", "component": "gearbox", "finish": "gear", "purpose": "involute spur pinion (20 deg, visual)",
            "add": [gear("gear_x", 0, "shaft_h", "z_pinion", "gear_m", "gear_b", "brg_d", phase=0.0),
                    tube("x", "gear_x - 6", 0, "shaft_h", 14, "brg_d / 2", "gear_b + 12")]},
           {"name": "gear_wheel", "component": "gearbox", "finish": "gear", "purpose": "involute spur gear (20 deg, visual)",
            "add": [gear("gear_x", "out_y", "shaft_h", "z_gear", "gear_m", "gear_b", "brg_d", phase=math.pi + math.pi / 50),
                    tube("x", "gear_x - 6", "out_y", "shaft_h", 18, "brg_d / 2", "gear_b + 12")],
            "sub": [cyl("x", "gear_x - 1", f"out_y + ({31 * math.cos(2 * math.pi * k / 6):.4f})",
                        f"shaft_h + ({31 * math.sin(2 * math.pi * k / 6):.4f})", 7, "gear_b + 2") for k in range(6)]}]
    for tag, xc in (("gb_in_bearing_1", "gb_x0 + gb_wall / 2"), ("gb_in_bearing_2", f"{gx1} - gb_wall / 2")):
        P_ += _bearing(tag, "gearbox", xc, 0, "shaft_h", "gearbox input shaft bearing")
    for tag, xc in (("gb_out_bearing_1", "gb_x0 + gb_wall / 2"), ("gb_out_bearing_2", f"{gx1} - gb_wall / 2")):
        P_ += _bearing(tag, "gearbox", xc, "out_y", "shaft_h", "gearbox output shaft bearing")
    # ---- coupling 3 and load (brake) unit on the output axis
    P_ += _coupling("coupling_3", "cpl3_x", "out_y", "brg_d / 2", "shaft_d / 2")
    saddle = [(-29.8, -72.0)] + [(70.5 * math.cos(math.radians(a)), 70.5 * math.sin(math.radians(a)))
                                 for a in range(245, 296, 5)] + [(29.8, -72.0)]
    P_ += [{"name": "load_shaft", "component": "load", "finish": "machined",
            "add": [cyl("x", "cpl3_x + cpl_hub + cpl_gap", "out_y", "shaft_h", "shaft_d / 2", "load_x0 - (cpl3_x + cpl_hub + cpl_gap)")]},
           {"name": "load_unit", "component": "load", "purpose": "brake / load (representative)", "finish": "painted_load",
            "add": [cyl("x", "load_x0", "out_y", "shaft_h", "load_d / 2", "load_l"),
                    tube("x", "load_x0 - 6", "out_y", "shaft_h", "load_d / 2 - 10", "shaft_d / 2", 6.4),   # end bells
                    cyl("x", "load_x0 + load_l - 0.4", "out_y", "shaft_h", "load_d / 2 - 10", 6.4),
                    cyl("x", "load_x0 + load_l + 5.6", "out_y", "shaft_h", 30, 8),
                    box("load_x0 + 20", "out_y - 18", "shaft_h + load_d / 2 - 3", 30, 36, 22)]           # terminal box
            + axial_fins("load_x0 + 6", "out_y", "shaft_h", "load_l - 12", "load_d / 2 - 2", "load_d / 2 + 8", 4,
                         LOAD_FIN_ANGLES)
            + bolt_circle_x("load_x0 - 6", "out_y", "shaft_h", 45.0, 6, -1, s=7.0, k=3.5, start_deg=0.0)},
           {"name": "load_pedestal", "component": "load", "finish": "painted_dark",
            "add": [box("load_x0", "out_y - 60", 0, "load_l", 120, "shaft_h - load_d / 2"),
                    box("load_x0 - 8", "out_y - 68", 0, "load_l + 16", 136, 10),
                    prism("x", "load_x0 + 6", "out_y", "shaft_h", saddle, "load_l - 12")]
            + [b for bx in ("load_x0 - 2", "load_x0 + load_l + 2") for by in ("out_y - 62", "out_y + 62")
               for b in bolt_z(bx, by, 10, s=10, k=4.5)]}]
    for p in P_:
        p.setdefault("sub", [])
        p.setdefault("purpose", "")
        p.setdefault("finish", finish_of(p))
    return P_


def finish_of(part):
    """Surface finish class used by the 3D viewer's materials (display only)."""
    n = part["name"]
    if "_ball_" in n or n.endswith(("_outer_ring", "_inner_ring")):
        return "bearing_steel"
    return "painted"


# --------------------------------------------------------------------------------------------- sensors
# One entry per physical sensor. `channels` are the exact names the replay code reads; `code` maps the sensor to
# the dictionary key the monitoring code uses for that sensor's reliability, status and fusion weight.
SENSORS = [
    {"id": "S1", "name": "sensor_bearing_accel", "label": "Bearing accelerometer",
     "subsystem": "bearing", "code": "vib", "dataset": "Paderborn KAt (bearing bench)",
     "channels": ["vibration_1"], "quantity": "acceleration, 1 axis (radial, vertical)", "fs_hz": 64000,
     "mount": "test_bearing_housing", "where": "top face of the test-bearing housing, above the bearing",
     "geom": cyl("z", "brg_b_x", 0, "shaft_h + hsg_top", 8, 14), "axis": (0, 0, 1)},
    {"id": "S2", "name": "sensor_motor_current", "label": "Motor current sensors (phases 1, 2)",
     "subsystem": "bearing", "code": "cur", "dataset": "Paderborn KAt (bearing bench)",
     "channels": ["phase_current_1", "phase_current_2"], "quantity": "phase current, 2 phases", "fs_hz": 64000,
     "mount": "motor_supply_cable", "where": "clamp-on current transducers on the motor supply cable",
     "geom": tube("y", "mot_x0 + 100 + tb_l / 2", "tb_w / 2 + 20", "shaft_h + mot_d / 2 + tb_h / 2", "cable_d / 2 + 8",
                  "cable_d / 2", 36), "axis": (0, 1, 0)},
    {"id": "S3", "name": "sensor_motor_accel", "label": "Motor accelerometer (3-axis)",
     "subsystem": "gearbox", "code": "motor", "dataset": "MCC5-THU (gearbox bench)",
     "channels": ["motor_vibration_x", "motor_vibration_y", "motor_vibration_z"], "quantity": "acceleration, 3 axes",
     "fs_hz": 12800, "mount": "motor_body", "where": "top of the motor frame at the drive end",
     "geom": cyl("z", "mot_x1 - 20", 0, "shaft_h + mot_d / 2", 8, 14), "axis": (0, 0, 1)},
    {"id": "S4", "name": "sensor_gearbox_accel", "label": "Gearbox accelerometer (3-axis)",
     "subsystem": "gearbox", "code": "gearbox", "dataset": "MCC5-THU (gearbox bench)",
     "channels": ["gearbox_vibration_x", "gearbox_vibration_y", "gearbox_vibration_z"], "quantity": "acceleration, 3 axes",
     "fs_hz": 12800, "mount": "gearbox_housing", "where": "side wall of the gearbox housing, at the input-shaft bearing",
     "geom": cyl("y", "gb_x0 + 18", "gb_y0 - 14", "shaft_h", 8, 14), "axis": (0, -1, 0)},
]

# The component that a subsystem's health state colours in the views.
MONITORED = {"bearing": ["test_bearing"], "gearbox": ["gearbox"]}
COMPONENT_LABELS = {"base": "Base plate", "motor": "Electric motor", "coupling_1": "Coupling 1",
                    "line_shaft": "Line shaft", "support_bearing": "Support bearing", "test_bearing": "Test bearing",
                    "coupling_2": "Coupling 2", "gearbox": "Gearbox", "coupling_3": "Coupling 3", "load": "Load (brake)"}


# --------------------------------------------------------------------------------------------- evaluation helpers
def resolve(prim, params=None):
    """Primitive with every expression evaluated to a float (teeth stay int)."""
    out = {}
    for k, v in prim.items():
        if k in ("type", "axis"):
            out[k] = v
        elif k == "poly":
            out[k] = [(float(u), float(w)) for u, w in v]
        elif k == "teeth":
            out[k] = int(ev(v, params))
        elif k == "phase":
            out[k] = float(v)
        else:
            out[k] = ev(v, params)
    return out


def bbox(prim):
    """Axis-aligned bounding box (x0, y0, z0, x1, y1, z1) of a resolved primitive."""
    t = prim["type"]
    if t == "box":
        return (prim["x"], prim["y"], prim["z"], prim["x"] + prim["L"], prim["y"] + prim["W"], prim["z"] + prim["H"])
    if t == "sphere":
        r = prim["r"]
        return (prim["x"] - r, prim["y"] - r, prim["z"] - r, prim["x"] + r, prim["y"] + r, prim["z"] + r)
    r = prim.get("r", prim.get("ro"))
    h = prim.get("h", prim.get("width"))
    c = [prim["x"], prim["y"], prim["z"]]
    i = "xyz".index(prim["axis"])
    others = [k for k in range(3) if k != i]
    if t in ("gear", "prism"):                 # extents of the actual polygon (tooth outline / prism section)
        pts = gear_outline(prim["teeth"], prim["module"], prim["phase"]) if t == "gear" else prim["poly"]
        lo, hi = list(c), list(c)
        for k, j in enumerate(others):
            lo[j] = c[j] + min(p[k] for p in pts)
            hi[j] = c[j] + max(p[k] for p in pts)
    else:
        lo, hi = [c[0] - r, c[1] - r, c[2] - r], [c[0] + r, c[1] + r, c[2] + r]
    lo[i], hi[i] = c[i], c[i] + h
    return (*lo, *hi)


def part_bbox(part, params=None):
    boxes = [bbox(resolve(p, params)) for p in part["add"]]
    return (min(b[0] for b in boxes), min(b[1] for b in boxes), min(b[2] for b in boxes),
            max(b[3] for b in boxes), max(b[4] for b in boxes), max(b[5] for b in boxes))


def sensor_position(sensor, params=None):
    """Centre of the sensor body (mm)."""
    b = bbox(resolve(sensor["geom"], params))
    return ((b[0] + b[3]) / 2, (b[1] + b[4]) / 2, (b[2] + b[5]) / 2)


def sensor_map(params=None):
    """Machine-readable sensor map (also written to cad/out/sensor_map.json)."""
    by_name = {p["name"]: p for p in parts()}
    rows = []
    for s in SENSORS:
        mount_bb = part_bbox(by_name[s["mount"]], params)
        rows.append({k: s[k] for k in ("id", "name", "label", "subsystem", "code", "dataset", "channels",
                                       "quantity", "fs_hz", "mount", "where")}
                    | {"position_mm": [round(v, 3) for v in sensor_position(s, params)],
                       "sensing_axis": list(s["axis"]),
                       "mount_bbox_mm": [round(v, 3) for v in mount_bb]})
    return {"units": "mm", "frame": "x along the drive axis (motor -> load), y across the bench, z up; z=0 top of base",
            "note": ("Representative electric-drive assembly. Sensor positions show where each dataset's sensor is "
                     "mounted relative to the machine element it monitors. They are not the exact positions on the "
                     "Paderborn or MCC5-THU test benches, which are two different rigs."),
            "sensors": rows}


def design_checks(params=None):
    """Representative sizing checks for the chosen dimensions (textbook formulas; not a validated design).

    Assumed duty: 1.1 kW four-pole motor at 1500 rpm (IEC 90 frame size), 1000 N radial load on the test bearing
    (the Paderborn F10 setting, used only as a plausible order of magnitude)."""
    p = dict(P if params is None else params)
    power, rpm, radial_n = 1100.0, 1500.0, 1000.0
    torque = power / (2 * math.pi * rpm / 60)                         # N m
    tau = 16 * torque / (math.pi * (p["brg_d"] / 1000) ** 3) / 1e6     # MPa, smallest line-shaft section
    c_6203 = 9950.0                                                   # N, basic dynamic load rating (catalogue)
    l10_mrev = (c_6203 / radial_n) ** 3
    l10_h = l10_mrev * 1e6 / (60 * rpm)
    m = p["gear_m"] / 1000
    rp = m * p["z_pinion"] / 2
    ft = torque / rp                                                  # N, tangential tooth load on the pinion
    lewis_y = 0.32                                                    # Lewis form factor, 20 teeth, 20 deg
    sigma_b = ft / ((p["gear_b"] / 1000) * m * lewis_y) / 1e6         # MPa
    # first lateral critical speed of the shoulder section, simply supported between the bearings, with the
    # coupling hub mass lumped at mid-span (conservative)
    e_mod, rho = 210e9, 7850.0
    span = (p["brg_b_x"] - p["brg_a_x"]) / 1000
    d = p["shoulder_d"] / 1000
    inertia = math.pi * d ** 4 / 64
    k = 48 * e_mod * inertia / span ** 3
    m_shaft = rho * math.pi * d ** 2 / 4 * span
    m_hub = rho * math.pi * ((p["cpl_d"] / 1000) ** 2 - (p["shaft_d"] / 1000) ** 2) / 4 * p["cpl_hub"] / 1000
    n_crit = math.sqrt(k / (m_hub + 0.49 * m_shaft)) / (2 * math.pi) * 60
    gear_ratio = p["z_gear"] / p["z_pinion"]
    return {
        "assumptions": {"power_W": power, "speed_rpm": rpm, "test_bearing_radial_load_N": radial_n,
                        "bearing": "6203 deep-groove ball bearing, C = 9.95 kN (catalogue value)",
                        "material": "steel, E = 210 GPa, density 7850 kg/m3"},
        "motor_torque_Nm": round(torque, 2),
        "shaft_shear_stress_MPa_at_d17": round(tau, 1),
        "bearing_L10_million_rev": round(l10_mrev, 0), "bearing_L10_hours_at_1500rpm": round(l10_h, 0),
        "gear_ratio": gear_ratio, "centre_distance_mm": ev("centre_dist", params),
        "output_speed_rpm": round(rpm / gear_ratio, 0), "output_torque_Nm": round(torque * gear_ratio, 2),
        "pinion_tangential_load_N": round(ft, 0), "pinion_lewis_bending_stress_MPa": round(sigma_b, 1),
        "line_shaft_first_critical_speed_rpm": round(n_crit, -2),
        "critical_speed_margin": round(n_crit / rpm, 1),
    }


# --------------------------------------------------------------------------------------------- interference
def _inside_prim(pr, pts):
    """Strictly-inside test (boundary points excluded, so exact fits do not count as overlap)."""
    import numpy as np
    x, y, z = pts[:, 0], pts[:, 1], pts[:, 2]
    eps = 1e-9
    t = pr["type"]
    if t == "box":
        return ((x > pr["x"] + eps) & (x < pr["x"] + pr["L"] - eps) & (y > pr["y"] + eps) & (y < pr["y"] + pr["W"] - eps)
                & (z > pr["z"] + eps) & (z < pr["z"] + pr["H"] - eps))
    if t == "sphere":
        return (x - pr["x"]) ** 2 + (y - pr["y"]) ** 2 + (z - pr["z"]) ** 2 < pr["r"] ** 2 - eps
    i = "xyz".index(pr["axis"])
    c = (pr["x"], pr["y"], pr["z"])
    a = pts[:, i] - c[i]
    u, v = [pts[:, j] - c[j] for j in range(3) if j != i]
    r2 = u ** 2 + v ** 2
    h = pr.get("h", pr.get("width"))
    along = (a > eps) & (a < h - eps)
    if t == "cyl":
        return along & (r2 < pr["r"] ** 2 - eps)
    if t == "tube":
        return along & (r2 < pr["ro"] ** 2 - eps) & (r2 > pr["ri"] ** 2 + eps)
    if t == "gear":
        inpoly = _in_polygon(u, v, gear_outline(pr["teeth"], pr["module"], pr["phase"]))
        return along & inpoly & (r2 > (pr["bore"] / 2) ** 2 + eps)
    if t == "prism":
        return along & _in_polygon(u, v, pr["poly"])
    raise ValueError(t)


def _in_polygon(u, v, poly):
    """Even-odd ray casting (numpy only), so the check needs no plotting library."""
    import numpy as np
    pts = np.asarray(poly, float)
    x0, y0 = pts[:, 0], pts[:, 1]
    x1, y1 = np.roll(x0, -1), np.roll(y0, -1)
    inside = np.zeros(len(u), bool)
    for a, b, c, d in zip(x0, y0, x1, y1):
        cross = (b > v) != (d > v)
        with np.errstate(divide="ignore", invalid="ignore"):
            xint = a + (v - b) * (c - a) / (d - b)
        inside ^= cross & (u < xint)
    return inside


def inside(part, pts, params=None):
    import numpy as np
    add = np.zeros(len(pts), bool)
    for pr in part["add"]:
        add |= _inside_prim(resolve(pr, params), pts)
    for pr in part.get("sub", []):
        add &= ~_inside_prim(resolve(pr, params), pts)
    return add


# Contacts that are intended by design and therefore allowed to share volume in this simplified model.
INTENDED_OVERLAPS = {
    # kept as a safeguard: the involute pair with 0.1 mm backlash shows no shared volume (cad/out/interference_check.json)
    frozenset({"pinion", "gear_wheel"}): "polygonal involute teeth at the mesh",
}


def _cost(part):
    """Relative cost of the inside() test of a part (polygon edges dominate)."""
    n = 0
    for pr in part["add"] + part.get("sub", []):
        n += {"gear": 8 * int(ev(pr["teeth"])) if pr["type"] == "gear" else 0,
              "prism": len(pr.get("poly", []))}.get(pr["type"], 1)
    return n


def interference_check(step=0.5, params=None, min_volume_mm3=1.0, sensors=True):
    """Grid-sample every pair of parts whose bounding boxes overlap; report shared volume (mm^3).

    Parts of one component are checked against each other too (e.g. balls against rings). Returns
    {'pairs_checked', 'overlaps': [{'a', 'b', 'volume_mm3', 'intended'}], 'unexpected': [...]}."""
    import numpy as np
    items = list(parts())
    if sensors:
        items += [{"name": s["name"], "component": "sensors", "add": [s["geom"]], "sub": []} for s in SENSORS]
    boxes = [part_bbox(p, params) for p in items]
    overlaps, checked = [], 0
    for i in range(len(items)):
        for j in range(i + 1, len(items)):
            a, b = boxes[i], boxes[j]
            lo = [max(a[k], b[k]) for k in range(3)]
            hi = [min(a[k + 3], b[k + 3]) for k in range(3)]
            if any(h - l <= 1e-6 for l, h in zip(lo, hi)):
                continue
            checked += 1
            axes = [np.arange(l + step / 2, h, step) for l, h in zip(lo, hi)]
            if any(len(ax) == 0 for ax in axes):
                continue
            g = np.stack(np.meshgrid(*axes, indexing="ij"), -1).reshape(-1, 3)
            a_, b_ = items[i], items[j]
            if _cost(a_) > _cost(b_):
                a_, b_ = b_, a_
            in_a = inside(a_, g, params)
            vol = float(inside(b_, g[in_a], params).sum()) * step ** 3 if in_a.any() else 0.0
            if vol >= min_volume_mm3:
                key = frozenset({items[i]["name"], items[j]["name"]})
                overlaps.append({"a": items[i]["name"], "b": items[j]["name"], "volume_mm3": round(vol, 2),
                                 "intended": INTENDED_OVERLAPS.get(key)})
    return {"step_mm": step, "pairs_checked": checked, "overlaps": overlaps,
            "unexpected": [o for o in overlaps if not o["intended"]]}


# --------------------------------------------------------------------------------------------- 2-D views
# view name -> (horizontal axis, vertical axis, depth axis, depth sign: +1 = viewer at -depth looking +depth)
VIEWS = {"front": ("x", "z", "y", +1), "top": ("x", "y", "z", -1), "end": ("y", "z", "x", -1)}


def project(prim, view):
    """Outline of a resolved primitive in an orthographic view: list of shapes
    ('rect', u0, v0, u1, v1) | ('circle', uc, vc, r) | ('poly', [(u, v), ...])."""
    hu, hv, hd, _ = VIEWS[view]
    t = prim["type"]
    if t == "sphere":
        c = {"x": prim["x"], "y": prim["y"], "z": prim["z"]}
        return [("circle", c[hu], c[hv], prim["r"])]
    b = bbox(prim)
    lo, hi = dict(zip("xyz", b[:3])), dict(zip("xyz", b[3:]))
    if t == "box":
        return [("rect", lo[hu], lo[hv], hi[hu], hi[hv])]
    if prim["axis"] == hd:                     # looking along the axis: a circle (or the tooth outline)
        c = {"x": prim["x"], "y": prim["y"], "z": prim["z"]}
        if t == "gear":
            pts = gear_outline(prim["teeth"], prim["module"], prim["phase"])
            return [("poly", [(c[hu] + u, c[hv] + v) for u, v in pts]), ("circle", c[hu], c[hv], prim["bore"] / 2)]
        if t == "prism":
            # (u, v) of the prism are the two non-axis coordinates in x-y-z order; map them to the view axes
            others = [a for a in "xyz" if a != prim["axis"]]
            return [("poly", [(c[hu] + (u if others[0] == hu else v), c[hv] + (v if others[1] == hv else u))
                              for u, v in prim["poly"]])]
        out = [("circle", c[hu], c[hv], prim.get("r", prim.get("ro")))]
        if t == "tube":
            out.append(("circle", c[hu], c[hv], prim["ri"]))
        return out
    return [("rect", lo[hu], lo[hv], hi[hu], hi[hv])]


def depth(part_bb, view):
    """Sort key for painter's algorithm (far parts first), by each part's face nearest the viewer, so a housing
    hides what it encloses (bearings in their housings, gears inside the gearbox)."""
    hu, hv, hd, sign = VIEWS[view]
    i = "xyz".index(hd)
    return -part_bb[i] if sign > 0 else part_bb[i + 3]


def explode_offset(part):
    """Translation (mm) of a part in the exploded view: housings stay, inner parts lift out."""
    n, c = part["name"], part["component"]
    if n.startswith(("support_bearing_", "test_bearing_")) and not n.endswith("_housing"):
        return (0.0, 0.0, 170.0)
    if n.startswith("gb_in_bearing") or n.startswith("gb_out_bearing"):
        return (-60.0 if n.endswith(("_1_outer_ring", "_1_inner_ring")) or "_1_ball" in n else 60.0, 0.0, 330.0)
    table = {"motor": (-170.0, 0.0, 0.0), "coupling_1": (-40.0, 0.0, 130.0), "line_shaft": (0.0, 0.0, 300.0),
             "coupling_2": (0.0, 0.0, 130.0), "coupling_3": (40.0, 0.0, 130.0), "load": (170.0, 0.0, 0.0)}
    if n == "gearbox_cover":
        return (0.0, 0.0, 200.0)
    if n in ("pinion", "gear_wheel", "gearbox_input_shaft", "gearbox_output_shaft"):
        return (0.0, 0.0, 330.0)
    return table.get(c, (0.0, 0.0, 0.0))


def svg_view(view="front", part_fill=None, sensor_fill=None, highlight=None, width=900, labels=True,
             title=None, bg="#0d1626", line="#3b4c6b"):
    """SVG drawing of the assembly from the CAD parameter model (no FreeCAD needed).

    part_fill: {component: colour}; sensor_fill: {sensor id: colour}; highlight: component drawn with a glow."""
    part_fill = part_fill or {}
    sensor_fill = sensor_fill or {}
    hu, hv, _, _ = VIEWS[view]
    items = [(p, part_bbox(p)) for p in parts()]
    all_bb = [b for _, b in items]
    i_u, i_v = "xyz".index(hu), "xyz".index(hv)
    u0 = min(b[i_u] for b in all_bb) - 40
    u1 = max(b[i_u + 3] for b in all_bb) + 40
    v0 = min(b[i_v] for b in all_bb) - 40
    v1 = max(b[i_v + 3] for b in all_bb) + 70
    s = width / (u1 - u0)
    hgt = (v1 - v0) * s
    X = lambda u: (u - u0) * s  # noqa: E731
    Y = lambda v: (v1 - v) * s  # noqa: E731
    default = "#22324d"
    out = [f'<svg viewBox="0 0 {width:.0f} {hgt:.0f}" width="100%" xmlns="http://www.w3.org/2000/svg" '
           f'font-family="Inter,Segoe UI,sans-serif" style="display:block">',
           f'<rect x="0" y="0" width="{width:.0f}" height="{hgt:.0f}" rx="10" fill="{bg}"/>',
           '<defs><filter id="cadglow"><feGaussianBlur stdDeviation="3" result="b"/><feMerge><feMergeNode in="b"/>'
           '<feMergeNode in="SourceGraphic"/></feMerge></filter></defs>']

    def shape_svg(sh, fill, stroke, extra=""):
        if sh[0] == "rect":
            _, a, b, c, d = sh
            return (f'<rect x="{X(a):.1f}" y="{Y(d):.1f}" width="{(c - a) * s:.1f}" height="{(d - b) * s:.1f}" '
                    f'fill="{fill}" stroke="{stroke}" stroke-width="1" {extra}/>')
        if sh[0] == "circle":
            _, a, b, r = sh
            return f'<circle cx="{X(a):.1f}" cy="{Y(b):.1f}" r="{r * s:.1f}" fill="{fill}" stroke="{stroke}" stroke-width="1" {extra}/>'
        pts = " ".join(f"{X(a):.1f},{Y(b):.1f}" for a, b in sh[1])
        return f'<polygon points="{pts}" fill="{fill}" stroke="{stroke}" stroke-width="1" {extra}/>'

    for p, bb in sorted(items, key=lambda it: depth(it[1], view)):
        fill = part_fill.get(p["component"], default)
        glow = 'filter="url(#cadglow)"' if highlight and p["component"] in highlight else ""
        stroke = fill if glow else line
        for pr in p["add"]:
            for sh in project(resolve(pr), view):
                out.append(shape_svg(sh, fill, stroke, glow))
    # base line and ground hatch
    for sns in SENSORS:
        col = sensor_fill.get(sns["id"], "#94a3b8")
        for sh in project(resolve(sns["geom"]), view):
            out.append(shape_svg(sh, col, "#e2e8f0", 'filter="url(#cadglow)"'))
        if labels:
            c = dict(zip("xyz", sensor_position(sns)))
            out.append(f'<text x="{X(c[hu]):.1f}" y="{Y(c[hv]) - 16:.1f}" fill="{col}" font-size="13" '
                       f'font-weight="700" text-anchor="middle">{sns["id"]}</text>')
    if title:
        out.append(f'<text x="14" y="22" fill="#94a3b8" font-size="12" letter-spacing="1.2">{title}</text>')
    out.append("</svg>")
    return "".join(out)
