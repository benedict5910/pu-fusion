"""Open the built FCStd in the FreeCAD GUI, colour it by component, save renders and the TechDraw PDF, then exit.

Run with the GUI executable from the repository root (or IVHM_ROOT set), after cad/build_freecad.py:

    "<FreeCAD>\\bin\\FreeCAD.exe" cad\\freecad_gui_snapshots.py

Writes cad/out/renders/{iso,front,top,right,exploded_iso}.png (rendered from the exported STEP files, coloured by
component; each image's non-white pixel fraction is recorded, blank images are reported as errors),
cad/out/drawings/techdraw_GA.pdf (if the page exists) and cad/out/gui_snapshot_report.json.
Component colours are saved into the FCStd (GUI-only property).
"""
import json
import os
import sys
import time
import traceback
from pathlib import Path

ROOT = Path(os.environ.get("IVHM_ROOT", os.getcwd())).resolve()
OUT = ROOT / "cad" / "out"
REN = OUT / "renders"
REN.mkdir(parents=True, exist_ok=True)
REPORT = {"started": time.strftime("%Y-%m-%d %H:%M:%S"), "images": {}, "errors": []}
COLOURS = {"base": (0.85, 0.85, 0.85), "motor": (0.36, 0.55, 0.85), "coupling_1": (0.25, 0.25, 0.28),
           "coupling_2": (0.25, 0.25, 0.28), "coupling_3": (0.25, 0.25, 0.28), "line_shaft": (0.75, 0.75, 0.78),
           "support_bearing": (0.62, 0.66, 0.72), "test_bearing": (0.93, 0.45, 0.35), "gearbox": (0.95, 0.75, 0.25),
           "load": (0.35, 0.72, 0.52), "sensors": (0.86, 0.10, 0.10)}


def err(where):
    REPORT["errors"].append({"where": where, "trace": traceback.format_exc(limit=3)})


def non_white_fraction(path):
    """Fraction of sampled pixels that are not white (a blank render scores 0)."""
    from PySide import QtGui
    img = QtGui.QImage(str(path))
    if img.isNull():
        return 0.0
    n = hit = 0
    for y in range(0, img.height(), 8):
        for x in range(0, img.width(), 8):
            c = QtGui.QColor(img.pixel(x, y))
            n += 1
            hit += (c.red() < 245 or c.green() < 245 or c.blue() < 245)
    return round(hit / max(n, 1), 4)


def finish(code=0):
    REPORT["finished"] = time.strftime("%Y-%m-%d %H:%M:%S")
    (OUT / "gui_snapshot_report.json").write_text(json.dumps(REPORT, indent=2))
    sys.stdout.flush()
    os._exit(code)


try:
    import FreeCAD as App
    import FreeCADGui as Gui
    REPORT["freecad_version"] = list(App.Version())
    doc = App.openDocument(str(OUT / "ivhm_drivetrain.FCStd"))
    Gui.updateGui()
    gdoc = Gui.getDocument(doc.Name)
    for o in doc.Objects:
        comp = getattr(o, "Component", None)
        if comp and hasattr(o, "ViewObject") and o.ViewObject is not None and o.Visibility:
            try:
                o.ViewObject.ShapeColor = COLOURS.get(comp, (0.7, 0.7, 0.7))
            except Exception:  # noqa: BLE001
                err(f"colour {o.Name}")
    Gui.setActiveDocument(doc.Name)
    Gui.updateGui()
    try:
        doc.save()
        REPORT["fcstd_saved_with_colours"] = True
    except Exception:  # noqa: BLE001
        err("save colours")
    page = doc.getObject("GA_Drawing")
    if page is not None:
        try:
            import TechDrawGui
            doc.recompute()
            Gui.updateGui()
            pdf = OUT / "drawings" / "techdraw_GA.pdf"
            TechDrawGui.exportPageAsPdf(page, str(pdf))
            REPORT["techdraw_pdf"] = pdf.exists()
        except Exception:  # noqa: BLE001
            err("TechDraw PDF")
    else:
        REPORT["techdraw_pdf"] = "no GA_Drawing page in the FCStd (headless TechDraw page step failed or skipped)"
    # renders from the exported STEP files (exactly the delivered geometry), coloured by component
    import Import
    sys.path.insert(0, str(ROOT / "src"))
    from pufusion import drivetrain_cad as D
    comp_of = {p["name"]: p["component"] for p in D.parts()}
    comp_of.update({f"{s_['id']} {s_['label']}": "sensors" for s_ in D.SENSORS})
    for step_name, shots in (("ivhm_drivetrain.step", ("iso", "front", "top", "right")),
                             ("ivhm_drivetrain_exploded.step", ("exploded_iso",))):
        try:
            ex = App.newDocument("Render")
            Import.insert(str(OUT / step_name), ex.Name)
            Gui.updateGui()
            for o in ex.Objects:
                vo = getattr(o, "ViewObject", None)
                if vo is not None and hasattr(vo, "ShapeColor"):
                    comp = comp_of.get(o.Label) or comp_of.get(o.Name)
                    if comp:
                        vo.ShapeColor = COLOURS.get(comp, (0.7, 0.7, 0.7))
            v2 = Gui.getDocument(ex.Name).activeView()
            for name in shots:
                {"iso": v2.viewIsometric, "front": v2.viewFront, "top": v2.viewTop, "right": v2.viewRight,
                 "exploded_iso": v2.viewIsometric}[name]()
                v2.fitAll()
                Gui.updateGui()
                p = REN / f"{name}.png"
                v2.saveImage(str(p), 1800, 1000, "White")
                REPORT["images"][name] = non_white_fraction(p)
            App.closeDocument(ex.Name)
        except Exception:  # noqa: BLE001
            err(f"render {step_name}")
    blank = [k for k, v in REPORT["images"].items() if not v or v < 0.005]
    if blank:
        REPORT["errors"].append({"where": "renders", "trace": f"blank or missing images: {blank}"})
    App.closeDocument(doc.Name)
    finish(0)
except Exception:  # noqa: BLE001
    err("top level")
    finish(1)
