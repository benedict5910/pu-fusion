"""Minimal binary glTF 2.0 (GLB) writer/reader for the OB4 CAD viewer. Pure Python, no dependencies.

Written by cad/export_glb.py (FreeCAD tessellation of the verified STEP export) and read by the dashboard viewer
(app/cad3d_component/viewer.js) and by tests/test_cad3d.py.

Conventions of the file written here:
* vertex positions in millimetres in the CAD frame (x along the drive axis, y across, z up), each part already in
  its assembled position (node transforms are identity);
* a root node carries the standard glTF conversion (mm -> m, z-up -> y-up), so generic glTF viewers show the
  assembly the right way up; the OB4 viewer works in the CAD frame directly;
* one node per solid, named after the part (or sensor) in pufusion.drivetrain_cad; node.extras holds its identity
  (kind, part, component, subsystem, sensor id, explode offset);
* each mesh has a TRIANGLES primitive (POSITION, NORMAL, indices) and, if present, a LINES primitive with the
  B-rep feature edges.
"""
from __future__ import annotations

import json
import struct
from array import array

GLB_MAGIC, JSON_CHUNK, BIN_CHUNK = 0x46546C67, 0x4E4F534A, 0x004E4942
FLOAT, UINT32 = 5126, 5125
TRIANGLES, LINES = 4, 1
ROOT_MATRIX = [0.001, 0, 0, 0,  0, 0, -0.001, 0,  0, 0.001, 0, 0,  0, 0, 0, 1]   # column-major: z-up mm -> y-up m


class _Bin:
    def __init__(self):
        self.data = bytearray()
        self.views, self.accessors = [], []

    def _view(self, payload: bytes, target=None):
        while len(self.data) % 4:
            self.data.append(0)
        v = {"buffer": 0, "byteOffset": len(self.data), "byteLength": len(payload)}
        if target:
            v["target"] = target
        self.data += payload
        self.views.append(v)
        return len(self.views) - 1

    def vec3(self, flat):
        a = array("f", flat)
        n = len(a) // 3
        mins = [min(a[i::3]) for i in range(3)] if n else [0, 0, 0]
        maxs = [max(a[i::3]) for i in range(3)] if n else [0, 0, 0]
        view = self._view(a.tobytes() if struct.pack("=I", 1) == struct.pack("<I", 1) else _le(a), 34962)
        self.accessors.append({"bufferView": view, "componentType": FLOAT, "count": n, "type": "VEC3",
                               "min": mins, "max": maxs})
        return len(self.accessors) - 1

    def indices(self, flat):
        a = array("I", flat)
        if a.itemsize != 4:
            a = array("L", flat)
        view = self._view(a.tobytes(), 34963)
        self.accessors.append({"bufferView": view, "componentType": UINT32, "count": len(a), "type": "SCALAR"})
        return len(self.accessors) - 1


def _le(a):
    b = array(a.typecode, a)
    b.byteswap()
    return b.tobytes()


def write_glb(path, nodes, materials, asset_extras=None):
    """nodes: list of dicts with name, extras, material (index), positions, normals, indices, lines (flat lists).
    materials: list of dicts with name and rgb (0..1)."""
    b = _Bin()
    gl_nodes, meshes = [], []
    for nd in nodes:
        prims = []
        if nd.get("indices"):
            prims.append({"attributes": {"POSITION": b.vec3(nd["positions"]), "NORMAL": b.vec3(nd["normals"])},
                          "indices": b.indices(nd["indices"]), "material": nd["material"], "mode": TRIANGLES})
        if nd.get("lines"):
            prims.append({"attributes": {"POSITION": b.vec3(nd["lines"])}, "material": nd["material"], "mode": LINES})
        meshes.append({"name": nd["name"], "primitives": prims})
        gl_nodes.append({"name": nd["name"], "mesh": len(meshes) - 1, "extras": nd.get("extras", {})})
    root = {"name": "IVHM_Drivetrain", "matrix": ROOT_MATRIX, "children": list(range(len(gl_nodes))),
            "extras": {"note": "children in mm, CAD frame (z up); this matrix converts to glTF metres, y up"}}
    gl_nodes.append(root)
    doc = {
        "asset": {"version": "2.0", "generator": "IVHM OB4 cad/export_glb.py", "extras": asset_extras or {}},
        "scene": 0, "scenes": [{"name": "IVHM", "nodes": [len(gl_nodes) - 1]}],
        "nodes": gl_nodes, "meshes": meshes,
        "materials": [{"name": m["name"], "doubleSided": True,
                       "pbrMetallicRoughness": {"baseColorFactor": [*m["rgb"], 1.0], "metallicFactor": 0.3,
                                                "roughnessFactor": 0.55}} for m in materials],
        "accessors": b.accessors, "bufferViews": b.views, "buffers": [{"byteLength": len(b.data)}],
    }
    js = json.dumps(doc, separators=(",", ":")).encode("utf-8")
    js += b" " * (-len(js) % 4)
    binary = bytes(b.data) + b"\0" * (-len(b.data) % 4)
    total = 12 + 8 + len(js) + 8 + len(binary)
    with open(path, "wb") as f:
        f.write(struct.pack("<III", GLB_MAGIC, 2, total))
        f.write(struct.pack("<II", len(js), JSON_CHUNK) + js)
        f.write(struct.pack("<II", len(binary), BIN_CHUNK) + binary)
    return total


def read_glb(path):
    """-> (gltf json dict, binary chunk bytes)."""
    with open(path, "rb") as f:
        data = f.read()
    magic, version, total = struct.unpack_from("<III", data, 0)
    if magic != GLB_MAGIC or version != 2 or total != len(data):
        raise ValueError(f"not a valid GLB 2.0 file: {path}")
    jlen, jtype = struct.unpack_from("<II", data, 12)
    if jtype != JSON_CHUNK:
        raise ValueError("first GLB chunk is not JSON")
    doc = json.loads(data[20:20 + jlen])
    off = 20 + jlen
    blen, btype = struct.unpack_from("<II", data, off)
    if btype != BIN_CHUNK:
        raise ValueError("second GLB chunk is not BIN")
    return doc, data[off + 8: off + 8 + blen]


def accessor(doc, binary, idx):
    """Flat list of the values of accessor idx (float32 or uint32)."""
    acc = doc["accessors"][idx]
    view = doc["bufferViews"][acc["bufferView"]]
    n = acc["count"] * {"SCALAR": 1, "VEC3": 3}[acc["type"]]
    code = "f" if acc["componentType"] == FLOAT else "I"
    start = view["byteOffset"] + acc.get("byteOffset", 0)
    return list(struct.unpack_from(f"<{n}{code}", binary, start))


def node_geometry(doc, binary, node):
    """(positions, normals, indices, line_positions) of one node's mesh (flat lists; empty when absent)."""
    pos = nrm = idx = lines = []
    for p in doc["meshes"][node["mesh"]]["primitives"]:
        if p.get("mode", TRIANGLES) == TRIANGLES:
            pos = accessor(doc, binary, p["attributes"]["POSITION"])
            nrm = accessor(doc, binary, p["attributes"]["NORMAL"])
            idx = accessor(doc, binary, p["indices"])
        elif p["mode"] == LINES:
            lines = accessor(doc, binary, p["attributes"]["POSITION"])
    return pos, nrm, idx, lines
