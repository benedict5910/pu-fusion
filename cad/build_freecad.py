"""Build the editable FreeCAD model of the representative IVHM drivetrain and export it.

Run from the repository root with FreeCAD's command-line interpreter (no GUI needed):

    "C:\\Program Files\\FreeCAD 1.0\\bin\\freecadcmd.exe" cad\\build_freecad.py

Writes (cad/out/):
  ivhm_drivetrain.FCStd         editable, parametric model: spreadsheet `Params` drives every primitive through
                                expressions; one App::Part per component; sensors carry their data-channel metadata
  ivhm_drivetrain.step          assembly (AP214), component structure kept
  step/<component>.step         one STEP file per component
  ivhm_drivetrain_exploded.step exploded arrangement (same solids, translated)
  ivhm_drivetrain.stl           tessellated assembly (viewing only)
  drawings/techdraw_*.dxf/.svg  TechDraw / projection outputs, only if those facilities work headless (see report)
  freecad_report.json           FreeCAD version, module availability, validity, volumes, bounding boxes compared
                                with the Python parameter model, sensor positions, BRep interference check, a
                                spreadsheet edit test, and the outcome of every export.

Geometry comes from src/pufusion/drivetrain_cad.py (the same model used for the drawings and the dashboard).
REPRESENTATIVE assembly - not a reconstruction of the Paderborn or MCC5-THU test benches.
"""
import json
import math
import os
import sys
import time
import traceback
from pathlib import Path

ROOT = Path(os.environ.get("IVHM_ROOT", os.getcwd())).resolve()
if not (ROOT / "src" / "pufusion" / "drivetrain_cad.py").exists():
    raise SystemExit(f"Run from the repository root (or set IVHM_ROOT); not found under {ROOT}")
sys.path.insert(0, str(ROOT / "src"))

import FreeCAD as App  # noqa: E402
import Part  # noqa: E402

from pufusion import drivetrain_cad as D  # noqa: E402

OUT = ROOT / "cad" / "out"
(OUT / "step").mkdir(parents=True, exist_ok=True)
(OUT / "drawings").mkdir(parents=True, exist_ok=True)
REPORT = {"generated": time.strftime("%Y-%m-%d %H:%M:%S"), "freecad_version": list(App.Version()),
          "python": sys.version.split()[0], "modules": {}, "exports": {}, "errors": []}


def note_error(where, ex):
    REPORT["errors"].append({"where": where, "error": f"{type(ex).__name__}: {ex}",
                             "trace": traceback.format_exc(limit=3)})


for mod in ("Part", "Import", "Mesh", "MeshPart", "TechDraw", "Spreadsheet"):
    try:
        __import__(mod)
        REPORT["modules"][mod] = True
    except Exception as ex:  # noqa: BLE001
        REPORT["modules"][mod] = f"{type(ex).__name__}: {ex}"

V = App.Vector
ROT = {"x": App.Rotation(V(0, 1, 0), 90), "y": App.Rotation(V(1, 0, 0), -90), "z": App.Rotation()}

doc = App.newDocument("IVHM_Drivetrain")

# ----------------------------------------------------------------------------- parameter spreadsheet
sheet = doc.addObject("Spreadsheet::Sheet", "Params")
sheet.Label = "Params (edit here)"
sheet.set("A1", "parameter")
sheet.set("B1", "value (mm unless stated)")
sheet.set("C1", "description")
row = 2
for name, (value, desc) in D.PARAMS.items():
    sheet.set(f"A{row}", name)
    sheet.set(f"B{row}", str(value))
    sheet.setAlias(f"B{row}", name)
    sheet.set(f"C{row}", desc)
    row += 1
for name, expr in D.DERIVED.items():
    sheet.set(f"A{row}", name)
    sheet.set(f"B{row}", "=" + expr)            # same-sheet formula: aliases referenced directly
    sheet.setAlias(f"B{row}", name)
    sheet.set(f"C{row}", "derived: " + expr)
    row += 1
doc.recompute()


# ----------------------------------------------------------------------------- primitive features
def bind(obj, prop, expr):
    """Numeric value now, expression binding for later edits (plain numbers are left unbound)."""
    try:
        float(expr)
        return
    except (TypeError, ValueError):
        obj.setExpression(prop, D.freecad_expr(expr))


def hidden(obj):
    try:
        obj.Visibility = False
    except Exception:  # noqa: BLE001
        pass
    return obj


def make_prim(prim, name, container):
    """Parametric feature for one primitive (expressions bound to Params). Returns the feature."""
    r = D.resolve(prim)
    t = prim["type"]
    if t == "box":
        o = doc.addObject("Part::Box", name)
        o.Length, o.Width, o.Height = r["L"], r["W"], r["H"]
        o.Placement = App.Placement(V(r["x"], r["y"], r["z"]), App.Rotation())
        for prop, key in (("Length", "L"), ("Width", "W"), ("Height", "H"), ("Placement.Base.x", "x"),
                          ("Placement.Base.y", "y"), ("Placement.Base.z", "z")):
            bind(o, prop, prim[key])
    elif t in ("cyl", "tube"):
        rad_key = "r" if t == "cyl" else "ro"
        o = doc.addObject("Part::Cylinder", name if t == "cyl" else name + "_outer")
        o.Radius, o.Height = r[rad_key], r["h"]
        o.Placement = App.Placement(V(r["x"], r["y"], r["z"]), ROT[prim["axis"]])
        for prop, key in (("Radius", rad_key), ("Height", "h"), ("Placement.Base.x", "x"),
                          ("Placement.Base.y", "y"), ("Placement.Base.z", "z")):
            bind(o, prop, prim[key])
        if t == "tube":
            inner = doc.addObject("Part::Cylinder", name + "_bore")
            inner.Radius, inner.Height = r["ri"], r["h"] + 1.0
            d = {"x": V(-0.5, 0, 0), "y": V(0, -0.5, 0), "z": V(0, 0, -0.5)}[prim["axis"]]
            inner.Placement = App.Placement(V(r["x"], r["y"], r["z"]) + d, ROT[prim["axis"]])
            bind(inner, "Radius", prim["ri"])
            bind(inner, "Height", f"({prim['h']}) + 1")
            for k, ax in (("x", "x"), ("y", "y"), ("z", "z")):
                off = " - 0.5" if prim["axis"] == ax else ""
                if not _is_number(prim[k]) or off:
                    inner.setExpression(f"Placement.Base.{ax}", D.freecad_expr(f"({prim[k]}){off}"))
            container.addObject(hidden(o))
            container.addObject(hidden(inner))
            cut = doc.addObject("Part::Cut", name)
            cut.Base, cut.Tool = o, inner
            o = cut
    elif t == "sphere":
        o = doc.addObject("Part::Sphere", name)
        o.Radius = r["r"]
        o.Placement = App.Placement(V(r["x"], r["y"], r["z"]), App.Rotation())
        for prop, key in (("Radius", "r"), ("Placement.Base.x", "x"), ("Placement.Base.y", "y"),
                          ("Placement.Base.z", "z")):
            bind(o, prop, prim[key])
    elif t == "gear":
        # involute tooth outline (see drivetrain_cad.gear_outline); shape built at the origin, placement bound
        pts = [V(0, u, v) for u, v in D.gear_outline(r["teeth"], r["module"], r["phase"])]
        face = Part.Face(Part.makePolygon(pts + [pts[0]]))
        solid = face.extrude(V(r["width"], 0, 0))
        bore = Part.makeCylinder(r["bore"] / 2, r["width"] + 2, V(-1, 0, 0), V(1, 0, 0))
        o = doc.addObject("Part::Feature", name)
        o.Shape = solid.cut(bore)
        o.Placement = App.Placement(V(r["x"], r["y"], r["z"]), App.Rotation())
        for prop, key in (("Placement.Base.x", "x"), ("Placement.Base.y", "y"), ("Placement.Base.z", "z")):
            bind(o, prop, prim[key])
        for prop, val in (("Teeth", r["teeth"]), ("Module_mm", r["module"])):
            o.addProperty("App::PropertyFloat", prop, "Gear", "involute tooth form, 20 deg (polygonal, visual)")
            setattr(o, prop, val)
    elif t == "prism":
        # fins, ribs, gussets, hexagon heads: polygon section (fixed) extruded along the axis; position bound to Params
        i = "xyz".index(prim["axis"])
        others = [k for k in range(3) if k != i]

        def p3(u, v):
            q = [0.0, 0.0, 0.0]
            q[others[0]], q[others[1]] = u, v
            return V(*q)
        pts = [p3(u, v) for u, v in r["poly"]]
        d = [0.0, 0.0, 0.0]
        d[i] = r["h"]
        o = doc.addObject("Part::Feature", name)
        o.Shape = Part.Face(Part.makePolygon(pts + [pts[0]])).extrude(V(*d))
        o.Placement = App.Placement(V(r["x"], r["y"], r["z"]), App.Rotation())
        for prop, key in (("Placement.Base.x", "x"), ("Placement.Base.y", "y"), ("Placement.Base.z", "z")):
            bind(o, prop, prim[key])
    else:
        raise ValueError(t)
    return o


def _is_number(v):
    try:
        float(v)
        return True
    except (TypeError, ValueError):
        return False


def fuse(objs, name, container):
    if len(objs) == 1:
        return objs[0]
    for o in objs:
        container.addObject(hidden(o))
    f = doc.addObject("Part::MultiFuse", name)
    f.Shapes = objs
    f.Refine = True
    return f


def build_part(part, container):
    adds = [make_prim(p, f"{part['name']}_add{k}", container) for k, p in enumerate(part["add"])]
    if len(adds) == 1 and not part["sub"]:
        final = adds[0]
        final.Label = part["name"]
    else:
        body = fuse(adds, f"{part['name']}_body", container)
        if part["sub"]:
            subs = [make_prim(p, f"{part['name']}_sub{k}", container) for k, p in enumerate(part["sub"])]
            tool = fuse(subs, f"{part['name']}_tools", container)
            container.addObject(hidden(body))
            container.addObject(hidden(tool))
            final = doc.addObject("Part::Cut", part["name"])
            final.Base, final.Tool = body, tool
        else:
            final = body
        final.Label = part["name"]
    final.addProperty("App::PropertyString", "Component", "IVHM", "assembly component")
    final.Component = part["component"]
    final.addProperty("App::PropertyString", "Finish", "IVHM", "surface finish class (3D viewer materials)")
    final.Finish = part.get("finish", "")
    if part.get("purpose"):
        final.addProperty("App::PropertyString", "Purpose", "IVHM", "role in the assembly")
        final.Purpose = part["purpose"]
    container.addObject(final)
    return final


# ----------------------------------------------------------------------------- assembly tree
top = doc.addObject("App::Part", "Drivetrain")
top.Label = "IVHM representative drivetrain"
groups, finals = {}, {}
for part in D.parts():
    comp = part["component"]
    if comp not in groups:
        g = doc.addObject("App::Part", f"C_{comp}")
        g.Label = D.COMPONENT_LABELS.get(comp, comp)
        top.addObject(g)
        groups[comp] = g
    finals[part["name"]] = build_part(part, groups[comp])

sensor_group = doc.addObject("App::Part", "C_sensors")
sensor_group.Label = "Sensors"
top.addObject(sensor_group)
sensor_objs = {}
for s in D.SENSORS:
    o = build_part({"name": s["name"], "component": "sensors", "add": [s["geom"]], "sub": [],
                    "purpose": s["label"]}, sensor_group)
    for prop, val in (("SensorId", s["id"]), ("Dataset", s["dataset"]), ("CodeKey", s["code"]),
                      ("Subsystem", s["subsystem"]), ("DataChannels", ", ".join(s["channels"])),
                      ("Quantity", s["quantity"]), ("MountedOn", s["mount"]), ("Where", s["where"])):
        o.addProperty("App::PropertyString", prop, "Sensor", "sensor metadata (see cad/out/sensor_map.json)")
        setattr(o, prop, val)
    sensor_objs[s["id"]] = o

doc.recompute()

# ----------------------------------------------------------------------------- validation
invalid = [o.Name for o in doc.Objects if "Invalid" in o.State or "Error" in o.State]
REPORT["recompute_invalid_objects"] = invalid
parts_report, max_dev = [], 0.0
for part in D.parts():
    o = finals[part["name"]]
    sh = o.Shape
    bb = sh.BoundBox
    fc_bb = [bb.XMin, bb.YMin, bb.ZMin, bb.XMax, bb.YMax, bb.ZMax]
    py_bb = list(D.part_bbox(part))
    dev = max(abs(a - b) for a, b in zip(fc_bb, py_bb))
    max_dev = max(max_dev, dev)
    parts_report.append({"name": part["name"], "component": part["component"], "valid": sh.isValid(),
                         "primitives": len(part["add"]) + len(part["sub"]), "faces": len(sh.Faces),
                         "solids": len(sh.Solids), "volume_mm3": round(sh.Volume, 1),
                         "bbox_freecad": [round(v, 3) for v in fc_bb], "bbox_model": [round(v, 3) for v in py_bb],
                         "bbox_max_dev_mm": round(dev, 4)})
REPORT["parts"] = parts_report
REPORT["bbox_max_deviation_mm"] = round(max_dev, 4)
REPORT["all_parts_valid"] = all(p["valid"] and p["solids"] >= 1 for p in parts_report)
REPORT["parts_not_single_solid"] = [p["name"] for p in parts_report if p["solids"] != 1]
REPORT["parts_count"] = len(parts_report)
REPORT["faces_total"] = sum(p["faces"] for p in parts_report)

sens_report = []
for s in D.SENSORS:
    bb = sensor_objs[s["id"]].Shape.BoundBox
    c = [(bb.XMin + bb.XMax) / 2, (bb.YMin + bb.YMax) / 2, (bb.ZMin + bb.ZMax) / 2]
    m = D.sensor_position(s)
    mount = finals[s["mount"]].Shape
    dist = mount.distToShape(sensor_objs[s["id"]].Shape)[0]
    sens_report.append({"id": s["id"], "name": s["name"], "centre_freecad": [round(v, 3) for v in c],
                        "centre_model": [round(v, 3) for v in m],
                        "dev_mm": round(max(abs(a - b) for a, b in zip(c, m)), 4),
                        "mount": s["mount"], "gap_to_mount_mm": round(dist, 4)})
REPORT["sensors"] = sens_report

# BRep interference: common volume between every pair whose bounding boxes intersect
allowed = {tuple(sorted(k)): v for k, v in D.INTENDED_OVERLAPS.items()}
named = [(n, finals[n].Shape) for n in finals] + [(s["name"], sensor_objs[s["id"]].Shape) for s in D.SENSORS]
clashes, checked = [], 0
t0 = time.time()
for i in range(len(named)):
    for j in range(i + 1, len(named)):
        (na, sa), (nb, sb) = named[i], named[j]
        if not sa.BoundBox.intersect(sb.BoundBox):
            continue
        checked += 1
        try:
            vol = sa.common(sb).Volume
        except Exception as ex:  # noqa: BLE001
            note_error(f"common {na}/{nb}", ex)
            continue
        if vol > 1.0:
            clashes.append({"a": na, "b": nb, "volume_mm3": round(vol, 2),
                            "intended": allowed.get(tuple(sorted((na, nb))))})
REPORT["interference"] = {"pairs_checked": checked, "overlaps": clashes,
                          "unexpected": [c for c in clashes if not c["intended"]], "seconds": round(time.time() - t0, 1)}

# ----------------------------------------------------------------------------- save + STEP / STL exports
fcstd = OUT / "ivhm_drivetrain.FCStd"
doc.saveAs(str(fcstd))
REPORT["exports"]["FCStd"] = str(fcstd.relative_to(ROOT))


def export(what, fn):
    try:
        fn()
        REPORT["exports"][what] = "ok"
    except Exception as ex:  # noqa: BLE001
        REPORT["exports"][what] = f"{type(ex).__name__}: {ex}"
        note_error(f"export {what}", ex)


EXPORT = {}


def _export_doc():
    """Separate document holding ONLY the final solids (the parametric document also contains hidden construction
    solids - outer cylinders, pre-cut bodies - which Import.export of an App::Part would include)."""
    if EXPORT:
        return EXPORT
    ex = App.newDocument("IVHM_Export")
    etop = ex.addObject("App::Part", "Drivetrain")
    etop.Label = top.Label
    comps = {}
    for part in D.parts():
        c = part["component"]
        if c not in comps:
            g = ex.addObject("App::Part", f"C_{c}")
            g.Label = groups[c].Label
            etop.addObject(g)
            comps[c] = g
        f = ex.addObject("Part::Feature", part["name"])
        f.Shape = finals[part["name"]].Shape.copy()
        f.Label = part["name"]
        comps[c].addObject(f)
    sg = ex.addObject("App::Part", "C_sensors")
    sg.Label = "Sensors"
    etop.addObject(sg)
    for s_ in D.SENSORS:
        f = ex.addObject("Part::Feature", s_["name"])
        f.Shape = sensor_objs[s_["id"]].Shape.copy()
        f.Label = f"{s_['id']} {s_['label']}"
        sg.addObject(f)
    ex.recompute()
    EXPORT.update(doc=ex, top=etop, comps=comps, sensors=sg)
    return EXPORT


def _step_assembly():
    import Import
    e = _export_doc()
    Import.export([e["top"]], str(OUT / "ivhm_drivetrain.step"))


def _step_components():
    import Import
    e = _export_doc()
    for comp, g in e["comps"].items():
        Import.export([g], str(OUT / "step" / f"{comp}.step"))
    Import.export([e["sensors"]], str(OUT / "step" / "sensors.step"))


def _step_exploded():
    shapes = []
    for part in D.parts():
        sh = finals[part["name"]].Shape.copy()
        sh.translate(V(*D.explode_offset(part)))
        shapes.append(sh)
    for s in D.SENSORS:
        sh = sensor_objs[s["id"]].Shape.copy()
        mount = next(p for p in D.parts() if p["name"] == s["mount"])
        sh.translate(V(*D.explode_offset(mount)) + V(*s["axis"]) * 40)
        shapes.append(sh)
    Part.makeCompound(shapes).exportStep(str(OUT / "ivhm_drivetrain_exploded.step"))


def _stl():
    import MeshPart
    shapes = [finals[n].Shape for n in finals] + [o.Shape for o in sensor_objs.values()]
    mesh = MeshPart.meshFromShape(Shape=Part.makeCompound(shapes), LinearDeflection=0.3, AngularDeflection=0.35)
    mesh.write(str(OUT / "ivhm_drivetrain.stl"))


export("STEP assembly", _step_assembly)
export("STEP per component", _step_components)
export("STEP exploded", _step_exploded)
if os.environ.get("IVHM_STL"):               # optional: tessellated copy for viewers (can be tens of MB)
    export("STL", _stl)
else:
    REPORT["exports"]["STL"] = "skipped (set IVHM_STL=1 to export)"

# re-import check: the assembly STEP must load and contain the same total volume
try:
    st = Part.Shape()
    st.read(str(OUT / "ivhm_drivetrain.step"))
    vol_step = st.Volume
    vol_doc = sum(finals[n].Shape.Volume for n in finals) + sum(o.Shape.Volume for o in sensor_objs.values())
    REPORT["step_reimport"] = {"solids": len(st.Solids), "solids_expected": len(finals) + len(sensor_objs),
                               "volume_mm3": round(vol_step, 1),
                               "volume_model_mm3": round(vol_doc, 1),
                               "relative_difference": round(abs(vol_step - vol_doc) / vol_doc, 6)}
except Exception as ex:  # noqa: BLE001
    note_error("STEP re-import", ex)

# ----------------------------------------------------------------------------- drawings (only if available)
def _projection_svgs():
    import TechDraw
    comp = Part.makeCompound([finals[n].Shape for n in finals] + [o.Shape for o in sensor_objs.values()])
    for nm, d in (("front", V(0, -1, 0)), ("top", V(0, 0, 1)), ("end", V(1, 0, 0))):
        svg = TechDraw.projectToSVG(comp, d)
        (OUT / "drawings" / f"techdraw_projection_{nm}.svg").write_text(
            f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="-100 -400 1400 700">{svg}</svg>')


def _techdraw_page():
    import glob
    import TechDraw
    tdir = Path(App.getResourceDir()) / "Mod" / "TechDraw" / "Templates"
    cands = sorted(glob.glob(str(tdir / "**" / "A3_Landscape*.svg"), recursive=True))
    if not cands:
        raise FileNotFoundError(f"no A3 landscape template under {tdir}")
    page = doc.addObject("TechDraw::DrawPage", "GA_Drawing")
    tpl = doc.addObject("TechDraw::DrawSVGTemplate", "Template")
    tpl.Template = cands[0]
    page.Template = tpl
    # A3 = 420 x 297 mm; at 1:5 the 1160 mm base is 232 mm wide, the 340 mm width 68 mm (views do not overlap)
    for nm, d, xd, x, y in (("Front", V(0, -1, 0), V(1, 0, 0), 160, 110), ("Top", V(0, 0, 1), V(1, 0, 0), 160, 215),
                            ("Right", V(1, 0, 0), V(0, 1, 0), 345, 110)):
        v = doc.addObject("TechDraw::DrawViewPart", nm)
        page.addView(v)
        v.Source = [top]
        v.Direction = d
        v.XDirection = xd
        v.Scale = 0.2
        v.X, v.Y = x, y
    doc.recompute()
    TechDraw.writeDXFPage(page, str(OUT / "drawings" / "techdraw_GA.dxf"))
    doc.save()


export("TechDraw projectToSVG", _projection_svgs)
export("TechDraw page + DXF", _techdraw_page)
REPORT["exports"]["PDF"] = ("not attempted headless: TechDraw PDF export is a GUI function. Open "
                            "ivhm_drivetrain.FCStd in FreeCAD and use File > Export PDF on the GA_Drawing page, "
                            "or use the dimensioned PDF drawings from cad/make_drawings.py.")

# ----------------------------------------------------------------------------- parametric edit test
try:
    probe = finals["motor_shaft"]
    z_before = probe.Shape.BoundBox.ZMin
    cell = sheet.getCellFromAlias("shaft_h")
    sheet.set(cell, "150")
    doc.recompute()
    z_after = probe.Shape.BoundBox.ZMin
    gear_after = finals["gear_wheel"].Shape.BoundBox.ZMin
    sheet.set(cell, str(D.P["shaft_h"]))
    doc.recompute()
    REPORT["edit_test"] = {"changed": "Params.shaft_h 140 -> 150", "motor_shaft_zmin_before": round(z_before, 3),
                           "motor_shaft_zmin_after": round(z_after, 3), "gear_wheel_zmin_after": round(gear_after, 3),
                           "moved_by_mm": round(z_after - z_before, 3),
                           "restored_zmin": round(probe.Shape.BoundBox.ZMin, 3)}
except Exception as ex:  # noqa: BLE001
    note_error("edit test", ex)

# ----------------------------------------------------------------------------- sensor map + summary
(OUT / "sensor_map.json").write_text(json.dumps(D.sensor_map(), indent=2))
REPORT["passed"] = bool(
    not invalid and REPORT["all_parts_valid"] and not REPORT["parts_not_single_solid"] and max_dev < 0.05
    and all(s["dev_mm"] < 0.05 and s["gap_to_mount_mm"] < 0.05 for s in sens_report)
    and not REPORT["interference"]["unexpected"]
    and REPORT["exports"].get("STEP assembly") == "ok"
    and REPORT.get("step_reimport", {}).get("solids") == REPORT.get("step_reimport", {}).get("solids_expected")
    and REPORT.get("step_reimport", {}).get("relative_difference", 1) < 1e-3
    and REPORT.get("edit_test", {}).get("moved_by_mm") == 10.0)
(OUT / "freecad_report.json").write_text(json.dumps(REPORT, indent=2))
print(json.dumps({k: REPORT[k] for k in ("freecad_version", "modules", "exports", "bbox_max_deviation_mm",
                                         "all_parts_valid", "passed")}, indent=2))
print(f"interference: {len(REPORT['interference']['overlaps'])} overlaps, "
      f"{len(REPORT['interference']['unexpected'])} unexpected; errors: {len(REPORT['errors'])}")
App.closeDocument(doc.Name)
if os.environ.get("IVHM_EXIT_AFTER"):        # freecadcmd may otherwise wait at its console after the script
    sys.stdout.flush()
    os._exit(0 if REPORT["passed"] else 2)
