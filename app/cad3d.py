"""Interactive 3D view of the representative drivetrain for the Virtual Testbed (OB4).

Geometry: cad/out/ivhm_drivetrain.glb, written by cad/export_glb.py from the verified STEP export of the parametric
FreeCAD model. The viewer (app/cad3d_component/, plain WebGL, no third-party code) runs as a local Streamlit custom
component; its iframe persists across reruns, so the camera stays where the user put it while the replay runs.

Everything the viewer shows about health - state, rule, probabilities, sensor quality, scores, reasons and fusion
weights - is passed in by testbed_view.cad3d_args() from the replay frame. The viewer computes nothing.
"""
from __future__ import annotations

import hashlib
import shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SOURCE_GLB = ROOT / "cad" / "out" / "ivhm_drivetrain.glb"
COMPONENT_DIR = Path(__file__).resolve().parent / "cad3d_component"
SERVED_GLB = COMPONENT_DIR / "model" / "ivhm_drivetrain.glb"     # generated copy (git-ignored)
_cache: dict = {}
_component = None


def model_url():
    """URL of the GLB inside the component folder (copied from cad/out when it changed), or (None, reason)."""
    if not SOURCE_GLB.exists():
        return None, ("No 3D model yet: run scripts\\windows\\export_glb.bat (FreeCAD) to convert "
                      "cad/out/ivhm_drivetrain.step into cad/out/ivhm_drivetrain.glb. The 2D views still work.")
    st_ = SOURCE_GLB.stat()
    key = (st_.st_size, st_.st_mtime_ns)
    if _cache.get("key") != key:
        sha = hashlib.sha256(SOURCE_GLB.read_bytes()).hexdigest()
        if not SERVED_GLB.exists() or hashlib.sha256(SERVED_GLB.read_bytes()).hexdigest() != sha:
            SERVED_GLB.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(SOURCE_GLB, SERVED_GLB)
        _cache.update(key=key, sha=sha)
    return f"model/ivhm_drivetrain.glb?v={_cache['sha'][:12]}", None


def _get_component():
    global _component
    if _component is None:
        import streamlit.components.v1 as components
        _component = components.declare_component("ivhm_cad3d", path=str(COMPONENT_DIR))
    return _component


def viewer(args: dict, key: str = "tb_cad3d"):
    """Render the 3D viewer with `args` (JSON-serialisable). Returns nothing (the viewer sends no value back)."""
    _get_component()(**args, key=key, default=None)
