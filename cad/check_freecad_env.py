"""Report the FreeCAD version and the modules/functions the OB4 CAD build relies on (run with freecadcmd).

Writes JSON to the path in IVHM_FC_CHECK_OUT (default: cad/out/freecad_env.json) and exits.
"""
import json
import os
import sys
import traceback

out = {"python": sys.version.split()[0], "executable": sys.executable, "modules": {}, "functions": {}}
try:
    import FreeCAD as App
    out["freecad_version"] = list(App.Version())
    out["resource_dir"] = App.getResourceDir()
except Exception as ex:  # noqa: BLE001
    out["freecad_version"] = f"{type(ex).__name__}: {ex}"
for mod in ("Part", "Import", "Mesh", "MeshPart", "TechDraw", "Spreadsheet"):
    try:
        m = __import__(mod)
        out["modules"][mod] = True
        if mod == "TechDraw":
            for fn in ("projectToSVG", "writeDXFPage"):
                out["functions"][f"TechDraw.{fn}"] = hasattr(m, fn)
        if mod == "Import":
            out["functions"]["Import.export"] = hasattr(m, "export")
    except Exception as ex:  # noqa: BLE001
        out["modules"][mod] = f"{type(ex).__name__}: {ex}"
try:                                   # smoke test: a solid, a boolean, a STEP round trip
    import tempfile

    import Part
    b = Part.makeBox(10, 10, 10).cut(Part.makeCylinder(3, 12))
    p = os.path.join(tempfile.gettempdir(), "ivhm_fc_smoke.step")
    b.exportStep(p)
    s = Part.Shape()
    s.read(p)
    out["smoke_step_roundtrip_volume_ok"] = abs(s.Volume - b.Volume) < 1e-6
except Exception:  # noqa: BLE001
    out["smoke_error"] = traceback.format_exc(limit=2)
dest = os.environ.get("IVHM_FC_CHECK_OUT") or os.path.join(os.getcwd(), "cad", "out", "freecad_env.json")
os.makedirs(os.path.dirname(dest), exist_ok=True)
with open(dest, "w") as f:
    json.dump(out, f, indent=2)
print(json.dumps(out, indent=2))
sys.stdout.flush()
os._exit(0)
