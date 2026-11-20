"""OB4: convert the verified STEP export into a browser-friendly GLB for the dashboard's 3D viewer.

Run with FreeCAD's command-line interpreter (scripts\\windows\\export_glb.bat):
    freecadcmd cad/export_glb.py            (IVHM_ROOT = project folder)

Geometry source: cad/out/ivhm_drivetrain.step (written by cad/build_freecad.py from the parametric FCStd).
Nothing is modelled or changed here: every solid of the STEP file is matched to its part by label, checked
against the parametric model (pufusion.drivetrain_cad bounding boxes), and tessellated face by face
(normals smooth within a face, sharp across B-rep edges). The B-rep feature edges are exported as lines.

Outputs
  cad/out/ivhm_drivetrain.glb          one node per solid (every part + 4 sensors) with its identity and surface finish
                                       in node.extras
  cad/out/glb_export_report.json       matching, bbox agreement, triangle counts, size, SHA-256, verdict
"""
import hashlib
import json
import math
import os
import sys
import time
import traceback
from pathlib import Path

ROOT = Path(os.environ.get("IVHM_ROOT", os.getcwd())).resolve()
sys.path.insert(0, str(ROOT / "src"))
OUT = ROOT / "cad" / "out"
STEP = OUT / "ivhm_drivetrain.step"
GLB = OUT / "ivhm_drivetrain.glb"
REPORT_PATH = OUT / "glb_export_report.json"
LIN_DEFLECTION = float(os.environ.get("IVHM_GLB_DEFLECTION", "0.15"))     # mm
ANG_DEFLECTION = float(os.environ.get("IVHM_GLB_ANGULAR", "0.3"))          # rad (about 17 degrees)
BBOX_TOL = 0.05                                                            # mm, same as the FreeCAD build check

from pufusion import drivetrain_cad as D  # noqa: E402
from pufusion import glb  # noqa: E402

REPORT = {"step": str(STEP), "glb": str(GLB), "linear_deflection_mm": LIN_DEFLECTION,
          "angular_deflection_rad": ANG_DEFLECTION, "errors": [],
          "started": time.strftime("%Y-%m-%d %H:%M:%S")}

# component colours (same palette as the FreeCAD renders, cad/freecad_gui_snapshots.py)
COLOURS = {"base": (0.85, 0.85, 0.85), "motor": (0.36, 0.55, 0.85), "coupling_1": (0.25, 0.25, 0.28),
           "coupling_2": (0.25, 0.25, 0.28), "coupling_3": (0.25, 0.25, 0.28), "line_shaft": (0.75, 0.75, 0.78),
           "support_bearing": (0.62, 0.66, 0.72), "test_bearing": (0.93, 0.45, 0.35), "gearbox": (0.95, 0.75, 0.25),
           "load": (0.35, 0.72, 0.52), "sensors": (0.86, 0.10, 0.10)}


def finish(code):
    REPORT["finished"] = time.strftime("%Y-%m-%d %H:%M:%S")
    REPORT_PATH.write_text(json.dumps(REPORT, indent=2), encoding="utf-8")
    print(json.dumps({k: REPORT[k] for k in ("passed", "nodes", "triangles", "glb_bytes") if k in REPORT}))
    sys.stdout.flush()
    os._exit(code)


def expected_nodes():
    """name -> identity, from the parametric model (the STEP labels are these names; sensors 'S1 <label>')."""
    exp = {}
    sub_of = {c: s for s, comps in D.MONITORED.items() for c in comps}
    for p in D.parts():
        exp[p["name"]] = {"kind": "part", "part": p["name"], "component": p["component"],
                          "component_label": D.COMPONENT_LABELS.get(p["component"], p["component"]),
                          "monitored_by": sub_of.get(p["component"]), "purpose": p.get("purpose", ""),
                          "finish": p.get("finish", ""), "explode": list(D.explode_offset(p)), "bbox": list(D.part_bbox(p))}
    by_name = {p["name"]: p for p in D.parts()}
    for s in D.SENSORS:
        ex = [a + 40 * b for a, b in zip(D.explode_offset(by_name[s["mount"]]), s["axis"])]
        exp[f"{s['id']} {s['label']}"] = {
            "kind": "sensor", "part": s["name"], "component": "sensors", "component_label": "Sensors",
            "sensor_id": s["id"], "subsystem": s["subsystem"], "code": s["code"], "mount": s["mount"], "finish": "sensor",
            "explode": ex, "bbox": list(D.bbox(D.resolve(s["geom"]))),
            "position_mm": [round(v, 3) for v in D.sensor_position(s)]}
    return exp


def _smooth_per_face(points, facets, segments):
    """Vertices duplicated per B-rep face (segment); normals averaged within a face only (sharp CAD edges)."""
    pos, nrm, idx = [], [], []
    for seg in segments:
        local, acc = {}, []
        for f in seg:
            tri = facets[f]
            pa, pb, pc = (points[k] for k in tri)
            ux, uy, uz = pb[0] - pa[0], pb[1] - pa[1], pb[2] - pa[2]
            vx, vy, vz = pc[0] - pa[0], pc[1] - pa[1], pc[2] - pa[2]
            n = (uy * vz - uz * vy, uz * vx - ux * vz, ux * vy - uy * vx)      # area-weighted
            for k in tri:
                if k not in local:
                    local[k] = len(pos) // 3
                    pos += points[k]
                    acc.append([0.0, 0.0, 0.0])
                a = acc[local[k] - (len(pos) // 3 - len(acc))]
                a[0] += n[0]
                a[1] += n[1]
                a[2] += n[2]
            idx += (local[tri[0]], local[tri[1]], local[tri[2]])
        for n in acc:
            ln = math.sqrt(n[0] ** 2 + n[1] ** 2 + n[2] ** 2) or 1.0
            nrm += (n[0] / ln, n[1] / ln, n[2] / ln)
    return pos, nrm, idx


def tessellate(shape):
    """Triangulation of a solid in global coordinates, one segment per B-rep face.
    -> (positions, normals, indices, edge_line_positions) as flat lists."""
    import Part
    import MeshPart
    m = MeshPart.meshFromShape(Shape=shape, LinearDeflection=LIN_DEFLECTION, AngularDeflection=ANG_DEFLECTION,
                               Relative=False, Segments=True)
    pts, facets = m.Topology
    points = [(p.x, p.y, p.z) for p in pts]
    segments = [list(m.getSegment(i)) for i in range(m.countSegments())]
    if sum(len(sg) for sg in segments) != len(facets):           # segmentation unavailable: one smooth group
        REPORT.setdefault("warnings", []).append("mesh segments did not cover all facets; normals smoothed per solid")
        segments = [list(range(len(facets)))]
    pos, nrm, idx = _smooth_per_face(points, facets, segments)
    lines = []
    for e in shape.Edges:
        if e.Degenerated:
            continue
        try:
            if len(shape.ancestorsOfType(e, Part.Face)) < 2:   # seam of a cylinder/sphere: not a feature edge
                continue
        except Exception:  # noqa: BLE001
            pass
        ps = e.discretize(Deflection=LIN_DEFLECTION)
        for p0, p1 in zip(ps[:-1], ps[1:]):
            lines += (p0.x, p0.y, p0.z, p1.x, p1.y, p1.z)
    return pos, nrm, idx, lines


try:
    import FreeCAD as App
    import Import
    REPORT["freecad_version"] = list(App.Version())[:4]
    if not STEP.exists():
        raise FileNotFoundError(f"{STEP} not found - run the CAD build first")
    REPORT["step_sha256"] = hashlib.sha256(STEP.read_bytes()).hexdigest()
    exp = expected_nodes()
    doc = App.newDocument("GLB_Import")
    Import.insert(str(STEP), doc.Name)
    doc.recompute()

    found = {}
    for o in doc.Objects:
        shp = getattr(o, "Shape", None)
        if o.TypeId == "App::Part" or shp is None or shp.isNull() or len(shp.Solids) != 1:
            continue
        label = o.Label
        if label not in exp:
            # FreeCAD may add a numeric suffix to a label it considers duplicate
            stem = label.rstrip("0123456789")
            label = stem if stem in exp else label
        if label not in exp:
            continue
        s = shp.copy()
        s.Placement = o.getGlobalPlacement()
        found.setdefault(label, []).append(s)

    missing = sorted(set(exp) - set(found))
    dup = sorted(k for k, v in found.items() if len(v) > 1)
    REPORT["matching"] = {"expected": len(exp), "matched": len(found), "missing": missing, "duplicated": dup}
    if missing or dup:
        raise RuntimeError(f"STEP labels do not match the model: missing {missing}, duplicated {dup}")

    comps = sorted({e["component"] for e in exp.values()})
    materials = [{"name": c, "rgb": COLOURS.get(c, (0.7, 0.7, 0.7))} for c in comps]
    mat_of = {c: i for i, c in enumerate(comps)}
    nodes, worst, tri_total, line_total, per_node = [], 0.0, 0, 0, {}
    for name, ident in exp.items():
        shape = found[name][0]
        bb = shape.BoundBox
        got = [bb.XMin, bb.YMin, bb.ZMin, bb.XMax, bb.YMax, bb.ZMax]
        dev = max(abs(a - b) for a, b in zip(got, ident["bbox"]))
        worst = max(worst, dev)
        pos, nrm, idx, lines = tessellate(shape)
        # tessellation must stay on the solid: vertex extents equal the B-rep extents (to within the deflection)
        vb = [min(pos[0::3]), min(pos[1::3]), min(pos[2::3]), max(pos[0::3]), max(pos[1::3]), max(pos[2::3])]
        vdev = max(abs(a - b) for a, b in zip(vb, got))
        tri_total += len(idx) // 3
        line_total += len(lines) // 6
        per_node[name] = {"bbox_dev_mm": round(dev, 4), "mesh_vs_brep_dev_mm": round(vdev, 4),
                          "triangles": len(idx) // 3, "edge_segments": len(lines) // 6,
                          "volume_mm3": round(shape.Volume, 2)}
        extras = {k: v for k, v in ident.items() if k != "bbox"} | {"bbox": [round(v, 3) for v in got]}
        nodes.append({"name": name, "extras": extras, "material": mat_of[ident["component"]],
                      "positions": pos, "normals": nrm, "indices": idx, "lines": lines})

    asset = {"source": "cad/out/ivhm_drivetrain.step (FreeCAD build of the parametric model)",
             "step_sha256": REPORT["step_sha256"], "units": "mm", "frame": "x drive axis, y across, z up",
             "linear_deflection_mm": LIN_DEFLECTION,
             "note": ("Representative electric-drive assembly; not the Paderborn or MCC5-THU bench. "
                      "Geometry only: the viewer colours it from the replay output; it does not simulate physics."),
             "monitored": D.MONITORED, "component_labels": D.COMPONENT_LABELS,
             "colours": {c: list(v) for c, v in COLOURS.items()}}
    size = glb.write_glb(str(GLB), nodes, materials, asset)

    # read back and confirm what the viewer will load
    gdoc, gbin = glb.read_glb(str(GLB))
    names_back = [n["name"] for n in gdoc["nodes"] if "mesh" in n]
    REPORT.update(nodes=len(nodes), triangles=tri_total, edge_segments=line_total, glb_bytes=size,
                  glb_sha256=hashlib.sha256(GLB.read_bytes()).hexdigest(),
                  max_bbox_dev_mm=round(worst, 4),
                  max_mesh_vs_brep_dev_mm=round(max(v["mesh_vs_brep_dev_mm"] for v in per_node.values()), 4),
                  readback_nodes=len(names_back), per_node=per_node)
    REPORT["expected_nodes"] = len(D.parts()) + len(D.SENSORS)
    REPORT["passed"] = (not REPORT["errors"] and len(names_back) == len(exp) == REPORT["expected_nodes"] and worst <= BBOX_TOL
                        and REPORT["max_mesh_vs_brep_dev_mm"] <= LIN_DEFLECTION + BBOX_TOL)
    finish(0 if REPORT["passed"] else 2)
except Exception:  # noqa: BLE001
    REPORT["errors"].append(traceback.format_exc())
    REPORT["passed"] = False
    finish(1)
