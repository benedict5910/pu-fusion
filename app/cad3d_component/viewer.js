/* IVHM OB4 - interactive 3D view of the representative drivetrain (Streamlit custom component, no dependencies).
 *
 * Geometry: model/ivhm_drivetrain.glb, written by cad/export_glb.py from the verified STEP export of the parametric
 * FreeCAD model. One node per solid; node.extras carries the part / component / sensor identity and the explode
 * offset (the same offsets that produce ivhm_drivetrain_exploded.step). Positions are mm, CAD frame, z up.
 *
 * Data: every colour, state, probability, quality status and fusion weight shown here arrives in the component
 * args from app/testbed_view.py (cad3d_args), which derives them from the replay frame of
 * pufusion.testbed_session.ReplaySession. The viewer computes nothing about health; it only displays.
 */
"use strict";
(function () {
  // ------------------------------------------------------------------ Streamlit component protocol (v1)
  function send(type, data) {
    window.parent.postMessage(Object.assign({ isStreamlitMessage: true, type: type }, data || {}), "*");
  }
  window.addEventListener("message", function (ev) {
    var d = ev.data;
    if (d && d.type === "streamlit:render") onArgs(d.args || {});
  });

  var $ = function (id) { return document.getElementById(id); };
  var canvas = $("gl"), msg = $("msg"), tagsEl = $("tags"), tip = $("tip");
  var gl = canvas.getContext("webgl2", { antialias: true, alpha: true, premultipliedAlpha: false }) ||
           canvas.getContext("webgl", { antialias: true, alpha: true, premultipliedAlpha: false });

  // ------------------------------------------------------------------ state
  var A = null;                 // latest args
  var model = null;             // {nodes, comps, labels, bounds}
  var modelUrl = null;
  var selected = null;          // {type: "component"|"sensor", id, part}
  var autoSel = true;           // selection follows the monitored component until the user clicks
  var hover = null;
  var xray = false, edges = true;
  var explodeT = 0, explodeTarget = 0;
  var cam = { az: -1.13, el: 0.42, dist: 1600, tx: 560, ty: 0, tz: 100, fov: 32 * Math.PI / 180 };
  var camAnim = null, dirty = true, VP = null, eye = [0, 0, 0];

  var PALETTE = {
    base: "#3b4452", motor: "#53687f", coupling: "#2c333d", line_shaft: "#aab3bf", support_bearing: "#9aa3af",
    test_bearing: "#9aa3af", gearbox: "#7d8897", load: "#4f6559", gear: "#b08d57", steel: "#b4bcc7",
    shaft: "#aab3bf", housing: "#7d8897", sensor: "#94a3b8"
  };
  var ACCENT = [0.22, 0.74, 0.97];

  function hex(c) {
    c = (c || "#94a3b8").replace("#", "");
    return [parseInt(c.substr(0, 2), 16) / 255, parseInt(c.substr(2, 2), 16) / 255, parseInt(c.substr(4, 2), 16) / 255];
  }
  function mix(a, b, t) { return [a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t, a[2] + (b[2] - a[2]) * t]; }
  function esc(s) { return String(s == null ? "" : s).replace(/[&<>"]/g, function (c) { return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]; }); }
  function fmt(v, d) { return v == null || isNaN(v) ? "n/a" : Number(v).toFixed(d == null ? 2 : d); }
  function pretty(s) { return String(s || "").replace(/_/g, " "); }

  // ------------------------------------------------------------------ math (column-major mat4)
  function persp(fovy, asp, n, f) {
    var t = 1 / Math.tan(fovy / 2), nf = 1 / (n - f);
    return [t / asp, 0, 0, 0, 0, t, 0, 0, 0, 0, (f + n) * nf, -1, 0, 0, 2 * f * n * nf, 0];
  }
  function sub(a, b) { return [a[0] - b[0], a[1] - b[1], a[2] - b[2]]; }
  function cross(a, b) { return [a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2], a[0] * b[1] - a[1] * b[0]]; }
  function dot(a, b) { return a[0] * b[0] + a[1] * b[1] + a[2] * b[2]; }
  function norm(a) { var l = Math.hypot(a[0], a[1], a[2]) || 1; return [a[0] / l, a[1] / l, a[2] / l]; }
  function lookAt(e, c, up) {
    var f = norm(sub(c, e)), s = norm(cross(f, up)), u = cross(s, f);
    return [s[0], u[0], -f[0], 0, s[1], u[1], -f[1], 0, s[2], u[2], -f[2], 0, -dot(s, e), -dot(u, e), dot(f, e), 1];
  }
  function mul(a, b) {
    var o = new Array(16);
    for (var i = 0; i < 4; i++) for (var j = 0; j < 4; j++) {
      var s = 0;
      for (var k = 0; k < 4; k++) s += a[k * 4 + j] * b[i * 4 + k];
      o[i * 4 + j] = s;
    }
    return o;
  }
  function camBasis() {
    var ce = Math.cos(cam.el), dir = [ce * Math.cos(cam.az), ce * Math.sin(cam.az), Math.sin(cam.el)];
    var e = [cam.tx + dir[0] * cam.dist, cam.ty + dir[1] * cam.dist, cam.tz + dir[2] * cam.dist];
    var f = norm(sub([cam.tx, cam.ty, cam.tz], e));
    var r = norm(cross(f, [0, 0, 1])), u = cross(r, f);
    return { eye: e, f: f, r: r, u: u };
  }

  // ------------------------------------------------------------------ shaders
  var VS = "attribute vec3 aPos; attribute vec3 aNrm; uniform mat4 uVP; uniform vec3 uOff;" +
    "varying vec3 vW; varying vec3 vN; void main(){ vec3 w=aPos+uOff; vW=w; vN=aNrm; gl_Position=uVP*vec4(w,1.0); }";
  var FS = "precision highp float; varying vec3 vW; varying vec3 vN; uniform vec3 uEye; uniform vec3 uColor;" +
    "uniform vec3 uEmis; uniform float uAlpha;" +
    "void main(){ vec3 n=normalize(vN); vec3 v=normalize(uEye-vW); if(dot(n,v)<0.0) n=-n;" +
    " vec3 L1=normalize(vec3(-0.35,-0.6,0.72)); vec3 L2=normalize(vec3(0.65,0.45,0.3));" +
    " float d1=max(dot(n,L1),0.0); float d2=max(dot(n,L2),0.0); float hemi=0.5+0.5*n.z;" +
    " vec3 amb=mix(vec3(0.13,0.14,0.17),vec3(0.36,0.40,0.47),hemi);" +
    " vec3 h=normalize(L1+v); float sp=pow(max(dot(n,h),0.0),56.0)*0.32;" +
    " float rim=pow(1.0-max(dot(n,v),0.0),3.0)*0.16;" +
    " vec3 c=uColor*(amb+d1*vec3(1.0,0.97,0.93)*0.9+d2*vec3(0.5,0.6,0.78)*0.32)+vec3(sp)+rim*vec3(0.5,0.68,0.9)+uEmis;" +
    " c=c/(c+vec3(0.9))*1.6; gl_FragColor=vec4(c,uAlpha); }";
  var LVS = "attribute vec3 aPos; uniform mat4 uVP; uniform vec3 uOff; void main(){ gl_Position=uVP*vec4(aPos+uOff,1.0); }";
  var LFS = "precision mediump float; uniform vec4 uRGBA; void main(){ gl_FragColor=uRGBA; }";
  var GVS = "attribute vec3 aPos; uniform mat4 uVP; varying vec2 vL; uniform vec4 uRect;" +
    "void main(){ vL=(aPos.xy-uRect.xy)/uRect.zw; gl_Position=uVP*vec4(aPos,1.0); }";
  var GFS = "precision mediump float; varying vec2 vL; void main(){ float r=length(vL); float a=0.42*(1.0-smoothstep(0.25,1.0,r));" +
    " gl_FragColor=vec4(0.0,0.0,0.0,a); }";

  function program(vs, fs) {
    function sh(t, s) {
      var o = gl.createShader(t); gl.shaderSource(o, s); gl.compileShader(o);
      if (!gl.getShaderParameter(o, gl.COMPILE_STATUS)) throw new Error(gl.getShaderInfoLog(o));
      return o;
    }
    var p = gl.createProgram();
    gl.attachShader(p, sh(gl.VERTEX_SHADER, vs)); gl.attachShader(p, sh(gl.FRAGMENT_SHADER, fs));
    gl.bindAttribLocation(p, 0, "aPos"); gl.bindAttribLocation(p, 1, "aNrm");
    gl.linkProgram(p);
    if (!gl.getProgramParameter(p, gl.LINK_STATUS)) throw new Error(gl.getProgramInfoLog(p));
    var u = {}, n = gl.getProgramParameter(p, gl.ACTIVE_UNIFORMS);
    for (var i = 0; i < n; i++) { var nm = gl.getActiveUniform(p, i).name; u[nm] = gl.getUniformLocation(p, nm); }
    return { p: p, u: u };
  }
  var P = null, PL = null, PG = null, uintExt = null;
  if (gl) {
    try {
      P = program(VS, FS); PL = program(LVS, LFS); PG = program(GVS, GFS);
      uintExt = (typeof WebGL2RenderingContext !== "undefined" && gl instanceof WebGL2RenderingContext) || gl.getExtension("OES_element_index_uint");
    } catch (e) { gl = null; msg.textContent = "WebGL shader error: " + e.message; }
  } else {
    msg.textContent = "WebGL is not available in this browser - use the 2D view in the sidebar.";
  }

  function buf(target, data) { var b = gl.createBuffer(); gl.bindBuffer(target, b); gl.bufferData(target, data, gl.STATIC_DRAW); return b; }

  // ------------------------------------------------------------------ GLB
  function parseGLB(ab) {
    var dv = new DataView(ab);
    if (dv.getUint32(0, true) !== 0x46546C67) throw new Error("not a GLB file");
    var jlen = dv.getUint32(12, true);
    var json = JSON.parse(new TextDecoder().decode(new Uint8Array(ab, 20, jlen)));
    var bin0 = 20 + jlen + 8;
    function acc(i) {
      var a = json.accessors[i], v = json.bufferViews[a.bufferView], off = bin0 + v.byteOffset + (a.byteOffset || 0);
      var n = a.count * (a.type === "VEC3" ? 3 : 1);
      return a.componentType === 5126 ? new Float32Array(ab, off, n) : new Uint32Array(ab, off, n);
    }
    var nodes = [], comps = {};
    json.nodes.forEach(function (nd) {
      if (nd.mesh == null) return;
      var ex = nd.extras || {}, o = { name: nd.name, ex: ex, kind: ex.kind, comp: ex.component, part: ex.part,
        sensor: ex.sensor_id || null, explode: ex.explode || [0, 0, 0], bbox: ex.bbox };
      json.meshes[nd.mesh].primitives.forEach(function (p) {
        if ((p.mode == null ? 4 : p.mode) === 4) {
          var pos = acc(p.attributes.POSITION), nrm = acc(p.attributes.NORMAL), idx = acc(p.indices), max = 0;
          for (var i = 0; i < idx.length; i++) if (idx[i] > max) max = idx[i];
          var small = max < 65535 || !uintExt;
          o.tri = { vb: buf(gl.ARRAY_BUFFER, pos), nb: buf(gl.ARRAY_BUFFER, nrm),
            ib: buf(gl.ELEMENT_ARRAY_BUFFER, small ? new Uint16Array(idx) : idx), n: idx.length,
            type: small ? gl.UNSIGNED_SHORT : gl.UNSIGNED_INT };
        } else if (p.mode === 1) {
          var lp = acc(p.attributes.POSITION);
          o.lines = { vb: buf(gl.ARRAY_BUFFER, lp), n: lp.length / 3 };
        }
      });
      o.base = hex(baseColour(o));
      o.see = o.kind === "part" && /housing|cover/.test(o.part);
      o.pick = nodes.length + 1;
      nodes.push(o);
      if (o.kind === "part") (comps[o.comp] = comps[o.comp] || []).push(o);
    });
    var asset = (json.asset && json.asset.extras) || {};
    return { nodes: nodes, comps: comps, asset: asset, byPart: nodes.reduce(function (m, n) { m[n.part] = n; return m; }, {}) };
  }

  function baseColour(o) {
    if (o.kind === "sensor") return PALETTE.sensor;
    var p = o.part || "";
    if (/pinion|gear_wheel/.test(p)) return PALETTE.gear;
    if (/ball|ring/.test(p)) return PALETTE.steel;
    if (/shaft/.test(p)) return PALETTE.shaft;
    if (/housing|cover/.test(p)) return PALETTE.housing;
    if (/coupling/.test(o.comp)) return PALETTE.coupling;
    return PALETTE[o.comp] || "#8b95a3";
  }

  function loadModel(url) {
    modelUrl = url;
    msg.style.display = "flex"; msg.textContent = "Loading CAD model…";
    fetch(url).then(function (r) { if (!r.ok) throw new Error("HTTP " + r.status); return r.arrayBuffer(); })
      .then(function (ab) {
        model = parseGLB(ab);
        makeGround();
        msg.style.display = "none";
        restoreCamera() || setView("iso", false);
        refresh();
      })
      .catch(function (e) { msg.style.display = "flex"; msg.textContent = "Could not load the CAD model (" + e.message + ")."; });
  }

  // ------------------------------------------------------------------ ground (contact shadow + grid)
  var ground = null;
  function makeGround() {
    var b = bounds(0), z = b.min[2] - 0.6, cx = (b.min[0] + b.max[0]) / 2, cy = (b.min[1] + b.max[1]) / 2;
    var hx = (b.max[0] - b.min[0]) * 0.62, hy = (b.max[1] - b.min[1]) * 0.9;
    var q = new Float32Array([cx - hx, cy - hy, z, cx + hx, cy - hy, z, cx + hx, cy + hy, z, cx - hx, cy - hy, z, cx + hx, cy + hy, z, cx - hx, cy + hy, z]);
    var lines = [], step = 50, X0 = Math.floor((cx - 1400) / step) * step, Y0 = Math.floor((cy - 900) / step) * step;
    for (var x = X0; x <= cx + 1400; x += step) lines.push(x, cy - 900, z - 0.2, x, cy + 900, z - 0.2);
    for (var y = Y0; y <= cy + 900; y += step) lines.push(cx - 1400, y, z - 0.2, cx + 1400, y, z - 0.2);
    ground = { q: buf(gl.ARRAY_BUFFER, q), rect: [cx, cy, hx, hy], g: buf(gl.ARRAY_BUFFER, new Float32Array(lines)), gn: lines.length / 3 };
  }

  // ------------------------------------------------------------------ geometry helpers
  function off(n, t) { return [n.explode[0] * t, n.explode[1] * t, n.explode[2] * t]; }
  function bounds(t, list) {
    var mn = [1e9, 1e9, 1e9], mx = [-1e9, -1e9, -1e9];
    (list || model.nodes).forEach(function (n) {
      var o = off(n, t);
      for (var k = 0; k < 3; k++) { mn[k] = Math.min(mn[k], n.bbox[k] + o[k]); mx[k] = Math.max(mx[k], n.bbox[k + 3] + o[k]); }
    });
    return { min: mn, max: mx };
  }
  function centre(b) { return [(b.min[0] + b.max[0]) / 2, (b.min[1] + b.max[1]) / 2, (b.min[2] + b.max[2]) / 2]; }
  function sensorNode(id) { return model && model.nodes.filter(function (n) { return n.sensor === id; })[0]; }
  function compOfSensor(id) { var s = sensorNode(id), m = s && model.byPart[s.ex.mount]; return m ? m.comp : null; }

  // ------------------------------------------------------------------ camera
  var VIEWS = { iso: [-1.13, 0.42], front: [-Math.PI / 2, 0.04], top: [-Math.PI / 2, 1.553], side: [0, 0.06] };
  // tight fit: project the 8 bbox corners for a view direction and solve for the camera distance
  function fitParams(list, az, el, margin) {
    var b = bounds(explodeT, list), c = centre(b);
    var ce = Math.cos(el), back = [ce * Math.cos(az), ce * Math.sin(az), Math.sin(el)];   // target -> eye
    var f = [-back[0], -back[1], -back[2]], r = norm(cross(f, [0, 0, 1])), u = cross(r, f);
    var w = canvas.clientWidth, h = canvas.clientHeight, asp = w > 0 && h > 0 ? w / h : 1.8;
    // keep the model clear of the inspector panel on the right: fit into the free width and shift left
    var panel = $("inspector").offsetWidth ? $("inspector").offsetWidth + 24 : 0;
    var free = w > 2 * panel ? (w - panel) / w : 1;
    var tv = Math.tan(cam.fov / 2), th = tv * asp, thf = th * free, d = 0;
    for (var i = 0; i < 8; i++) {
      var p = [i & 1 ? b.max[0] : b.min[0], i & 2 ? b.max[1] : b.min[1], i & 4 ? b.max[2] : b.min[2]];
      var q = sub(p, c), x = dot(q, r), y = dot(q, u), z = dot(q, back);
      d = Math.max(d, Math.abs(x) / thf + z, Math.abs(y) / tv + z);
    }
    d = Math.max(120, d * (margin || 1.04));
    var shift = (1 - free) * d * th;                       // world units: half the panel width at the target depth
    return { tx: c[0] + r[0] * shift, ty: c[1] + r[1] * shift, tz: c[2] + r[2] * shift, dist: d };
  }
  function fit(animate, list) { tween(fitParams(list, cam.az, cam.el), animate); }
  function setView(name, animate) {
    var v = VIEWS[name]; if (!v || !model) return;
    tween(Object.assign({ az: v[0], el: v[1] }, fitParams(null, v[0], v[1])), animate);
  }
  function tween(to, animate) {
    if (!animate) { Object.assign(cam, to); camAnim = null; requestRender(); return; }
    var targets = Object.assign({}, camAnim ? camAnim.to : {}, to), from = {};
    Object.keys(targets).forEach(function (k) { from[k] = cam[k]; });
    if (targets.az != null) {
      var d = targets.az - from.az;
      while (d > Math.PI) d -= 2 * Math.PI;
      while (d < -Math.PI) d += 2 * Math.PI;
      targets.az = from.az + d;
    }
    camAnim = { from: from, to: targets, t0: performance.now() };
    requestRender();
  }
  function saveCamera() {
    try { sessionStorage.setItem("ivhm_cam_v3", JSON.stringify({ c: cam, x: xray, e: edges, t: explodeTarget })); } catch (e) { /* storage unavailable */ }
  }
  function restoreCamera() {
    try {
      var s = JSON.parse(sessionStorage.getItem("ivhm_cam_v3") || "null");
      if (!s) return false;
      Object.assign(cam, s.c); xray = !!s.x; edges = s.e !== false; explodeT = explodeTarget = s.t || 0;
      $("explode").value = Math.round(explodeTarget * 100);
      $("b-xray").classList.toggle("on", xray); $("b-edges").classList.toggle("on", edges);
      return true;
    } catch (e) { return false; }
  }

  // ------------------------------------------------------------------ appearance from the args (replay output)
  function look(n) {
    var a = A || {}, c = n.base.slice(), em = [0, 0, 0], alpha = 1;
    if (n.kind === "sensor") {
      c = hex((a.sensor_fill || {})[n.sensor] || PALETTE.sensor);
      em = c.map(function (v) { return v * 0.28; });
    } else if ((a.part_fill || {})[n.comp]) {
      var s = hex(a.part_fill[n.comp]);
      c = mix(c, s, 0.62); em = s.map(function (v) { return v * 0.16; });
    }
    var selComp = selected && selected.type === "component" ? selected.id : null;
    var selSensor = selected && selected.type === "sensor" ? selected.id : null;
    var isSel = (selComp && n.kind === "part" && n.comp === selComp) || (selSensor && n.sensor === selSensor);
    if (isSel) em = [em[0] + ACCENT[0] * 0.14, em[1] + ACCENT[1] * 0.14, em[2] + ACCENT[2] * 0.14];
    var hv = hover && ((hover.kind === "sensor" && n.sensor === hover.sensor) || (hover.kind === "part" && n.kind === "part" && n.comp === hover.comp));
    if (hv) em = [em[0] + 0.07, em[1] + 0.07, em[2] + 0.07];
    if (xray && n.see) alpha = 0.2;
    return { c: c, em: em, a: alpha, sel: isSel };
  }

  // ------------------------------------------------------------------ rendering
  var raf = 0;
  function requestRender() { if (!raf) raf = requestAnimationFrame(frame); }
  function resize() {
    var dpr = Math.min(window.devicePixelRatio || 1, 2), w = Math.round(canvas.clientWidth * dpr), h = Math.round(canvas.clientHeight * dpr);
    if (canvas.width !== w || canvas.height !== h) { canvas.width = w; canvas.height = h; pickFbo = null; dirty = true; }
  }
  function frame(now) {
    raf = 0;
    if (!gl || !model) return;
    var animating = false;
    if (camAnim) {
      var t = Math.min(1, (now - camAnim.t0) / 450), e = t < 0.5 ? 2 * t * t : 1 - Math.pow(-2 * t + 2, 2) / 2;
      for (var k in camAnim.to) cam[k] = camAnim.from[k] + (camAnim.to[k] - camAnim.from[k]) * e;
      if (t >= 1) { camAnim = null; saveCamera(); } else animating = true;
    }
    if (Math.abs(explodeT - explodeTarget) > 1e-3) { explodeT += (explodeTarget - explodeT) * 0.16; animating = true; }
    else explodeT = explodeTarget;
    resize();
    draw();
    placeTags();
    if (animating) requestRender();
  }

  function matrices() {
    var b = camBasis(); eye = b.eye;
    var asp = canvas.width / Math.max(1, canvas.height);
    var near = Math.max(5, cam.dist * 0.03), far = cam.dist * 6 + 4000;
    VP = mul(persp(cam.fov, asp, near, far), lookAt(b.eye, [cam.tx, cam.ty, cam.tz], [0, 0, 1]));
  }

  function bindTri(n) {
    gl.bindBuffer(gl.ARRAY_BUFFER, n.tri.vb); gl.enableVertexAttribArray(0); gl.vertexAttribPointer(0, 3, gl.FLOAT, false, 0, 0);
    gl.bindBuffer(gl.ARRAY_BUFFER, n.tri.nb); gl.enableVertexAttribArray(1); gl.vertexAttribPointer(1, 3, gl.FLOAT, false, 0, 0);
    gl.bindBuffer(gl.ELEMENT_ARRAY_BUFFER, n.tri.ib);
  }

  function draw() {
    matrices();
    gl.viewport(0, 0, canvas.width, canvas.height);
    gl.clearColor(0, 0, 0, 0); gl.clear(gl.COLOR_BUFFER_BIT | gl.DEPTH_BUFFER_BIT);
    gl.enable(gl.DEPTH_TEST); gl.enable(gl.BLEND); gl.blendFunc(gl.SRC_ALPHA, gl.ONE_MINUS_SRC_ALPHA);
    // ground: soft contact shadow + faint grid
    gl.depthMask(false);
    gl.useProgram(PG.p); gl.uniformMatrix4fv(PG.u.uVP, false, VP); gl.uniform4fv(PG.u.uRect, ground.rect);
    gl.disableVertexAttribArray(1);
    gl.bindBuffer(gl.ARRAY_BUFFER, ground.q); gl.enableVertexAttribArray(0); gl.vertexAttribPointer(0, 3, gl.FLOAT, false, 0, 0);
    gl.drawArrays(gl.TRIANGLES, 0, 6);
    gl.useProgram(PL.p); gl.uniformMatrix4fv(PL.u.uVP, false, VP); gl.uniform3fv(PL.u.uOff, [0, 0, 0]);
    gl.uniform4fv(PL.u.uRGBA, [0.58, 0.65, 0.75, 0.07]);
    gl.bindBuffer(gl.ARRAY_BUFFER, ground.g); gl.vertexAttribPointer(0, 3, gl.FLOAT, false, 0, 0);
    gl.drawArrays(gl.LINES, 0, ground.gn);
    gl.depthMask(true);

    var looks = model.nodes.map(look), opaque = [], trans = [];
    model.nodes.forEach(function (n, i) { (looks[i].a < 1 ? trans : opaque).push(i); });
    gl.useProgram(P.p); gl.uniformMatrix4fv(P.u.uVP, false, VP); gl.uniform3fv(P.u.uEye, eye);
    gl.enable(gl.POLYGON_OFFSET_FILL); gl.polygonOffset(1, 1);
    opaque.forEach(function (i) { drawNode(model.nodes[i], looks[i]); });
    // see-through parts, back to front, without writing depth
    var e = eye;
    trans.sort(function (a, b) {
      var ca = model.nodes[a].bbox, cb = model.nodes[b].bbox;
      var da = Math.hypot((ca[0] + ca[3]) / 2 - e[0], (ca[1] + ca[4]) / 2 - e[1], (ca[2] + ca[5]) / 2 - e[2]);
      var db = Math.hypot((cb[0] + cb[3]) / 2 - e[0], (cb[1] + cb[4]) / 2 - e[1], (cb[2] + cb[5]) / 2 - e[2]);
      return db - da;
    });
    gl.depthMask(false);
    trans.forEach(function (i) { drawNode(model.nodes[i], looks[i]); });
    gl.depthMask(true);
    gl.disable(gl.POLYGON_OFFSET_FILL);
    // feature edges
    if (edges) {
      gl.useProgram(PL.p); gl.uniformMatrix4fv(PL.u.uVP, false, VP); gl.disableVertexAttribArray(1);
      model.nodes.forEach(function (n, i) {
        if (!n.lines) return;
        var L = looks[i];
        gl.uniform4fv(PL.u.uRGBA, L.sel ? [ACCENT[0], ACCENT[1], ACCENT[2], 0.95] : [0.03, 0.05, 0.08, L.a < 1 ? 0.3 : 0.55]);
        gl.uniform3fv(PL.u.uOff, off(n, explodeT));
        gl.bindBuffer(gl.ARRAY_BUFFER, n.lines.vb); gl.enableVertexAttribArray(0); gl.vertexAttribPointer(0, 3, gl.FLOAT, false, 0, 0);
        gl.drawArrays(gl.LINES, 0, n.lines.n);
      });
    }
  }
  function drawNode(n, L) {
    if (!n.tri) return;
    gl.uniform3fv(P.u.uOff, off(n, explodeT)); gl.uniform3fv(P.u.uColor, L.c); gl.uniform3fv(P.u.uEmis, L.em);
    gl.uniform1f(P.u.uAlpha, L.a);
    bindTri(n);
    gl.drawElements(gl.TRIANGLES, n.tri.n, n.tri.type, 0);
  }

  // ------------------------------------------------------------------ picking (id buffer)
  var pickFbo = null, pickTex = null, pickRb = null;
  function pickAt(px, py) {
    if (!gl || !model) return null;
    var w = canvas.width, h = canvas.height;
    if (!pickFbo) {
      pickFbo = gl.createFramebuffer(); pickTex = gl.createTexture(); pickRb = gl.createRenderbuffer();
      gl.bindTexture(gl.TEXTURE_2D, pickTex);
      gl.texImage2D(gl.TEXTURE_2D, 0, gl.RGBA, w, h, 0, gl.RGBA, gl.UNSIGNED_BYTE, null);
      gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MIN_FILTER, gl.NEAREST);
      gl.bindRenderbuffer(gl.RENDERBUFFER, pickRb); gl.renderbufferStorage(gl.RENDERBUFFER, gl.DEPTH_COMPONENT16, w, h);
      gl.bindFramebuffer(gl.FRAMEBUFFER, pickFbo);
      gl.framebufferTexture2D(gl.FRAMEBUFFER, gl.COLOR_ATTACHMENT0, gl.TEXTURE_2D, pickTex, 0);
      gl.framebufferRenderbuffer(gl.FRAMEBUFFER, gl.DEPTH_ATTACHMENT, gl.RENDERBUFFER, pickRb);
    }
    gl.bindFramebuffer(gl.FRAMEBUFFER, pickFbo);
    gl.viewport(0, 0, w, h); gl.disable(gl.BLEND); gl.enable(gl.DEPTH_TEST);
    gl.clearColor(0, 0, 0, 0); gl.clear(gl.COLOR_BUFFER_BIT | gl.DEPTH_BUFFER_BIT);
    matrices();
    gl.useProgram(PL.p); gl.uniformMatrix4fv(PL.u.uVP, false, VP); gl.disableVertexAttribArray(1);
    model.nodes.forEach(function (n) {
      if (!n.tri || (xray && n.see)) return;               // see-through housings let clicks reach the parts inside
      var id = n.pick;
      gl.uniform4fv(PL.u.uRGBA, [(id & 255) / 255, ((id >> 8) & 255) / 255, ((id >> 16) & 255) / 255, 1]);
      gl.uniform3fv(PL.u.uOff, off(n, explodeT));
      gl.bindBuffer(gl.ARRAY_BUFFER, n.tri.vb); gl.enableVertexAttribArray(0); gl.vertexAttribPointer(0, 3, gl.FLOAT, false, 0, 0);
      gl.bindBuffer(gl.ELEMENT_ARRAY_BUFFER, n.tri.ib);
      gl.drawElements(gl.TRIANGLES, n.tri.n, n.tri.type, 0);
    });
    var px8 = new Uint8Array(4), dpr = canvas.width / Math.max(1, canvas.clientWidth);
    gl.readPixels(Math.round(px * dpr), Math.round(h - py * dpr), 1, 1, gl.RGBA, gl.UNSIGNED_BYTE, px8);
    gl.bindFramebuffer(gl.FRAMEBUFFER, null);
    gl.enable(gl.BLEND);
    var id = px8[0] + (px8[1] << 8) + (px8[2] << 16);
    return id ? model.nodes[id - 1] : null;
  }

  // ------------------------------------------------------------------ tags (sensor markers, state chip)
  function project(p) {
    var x = VP[0] * p[0] + VP[4] * p[1] + VP[8] * p[2] + VP[12], y = VP[1] * p[0] + VP[5] * p[1] + VP[9] * p[2] + VP[13];
    var w = VP[3] * p[0] + VP[7] * p[1] + VP[11] * p[2] + VP[15];
    if (w <= 0) return null;
    return [(x / w * 0.5 + 0.5) * canvas.clientWidth, (1 - (y / w * 0.5 + 0.5)) * canvas.clientHeight];
  }
  var tagEls = {};
  function tagEl(key, cls) {
    var el = tagEls[key];
    if (!el) {
      el = document.createElement("div"); el.className = "tag " + cls; tagsEl.appendChild(el); tagEls[key] = el;
      el.addEventListener("click", function (ev) { ev.stopPropagation(); onTagClick(key); });
    }
    return el;
  }
  function onTagClick(key) {
    autoSel = false;
    if (key.indexOf("sensor:") === 0) selected = { type: "sensor", id: key.slice(7) };
    else selected = { type: "component", id: key.slice(5) };
    refresh();
  }
  function placeTags() {
    if (!model || !VP) return;
    var a = A || {}, sensors = a.sensors || {};
    model.nodes.forEach(function (n) {
      if (n.kind !== "sensor") return;
      var s = sensors[n.sensor] || {}, el = tagEl("sensor:" + n.sensor, "");
      var o = off(n, explodeT), p = project([(n.bbox[0] + n.bbox[3]) / 2 + o[0], (n.bbox[1] + n.bbox[4]) / 2 + o[1], n.bbox[5] + o[2] + 4]);
      if (!p) { el.style.display = "none"; return; }
      var col = (a.sensor_fill || {})[n.sensor] || "#94a3b8";
      var status = s.active ? (s.status ? s.status.toUpperCase() : "READY") : "other replay";
      el.innerHTML = '<span class="dot" style="background:' + col + '"></span>' + n.sensor +
        ' <span style="color:' + (s.active ? col : "#64748b") + ';font-weight:500">' + esc(status) + "</span>";
      el.classList.toggle("inactive", !s.active);
      el.classList.toggle("sel", !!(selected && selected.type === "sensor" && selected.id === n.sensor));
      el.style.display = ""; el.style.left = p[0] + "px"; el.style.top = (p[1] - 12) + "px";
    });
    // state chip above the monitored component of the selected subsystem
    var mon = (a.monitored || [])[0], el2 = tagEl("comp:" + (mon || "none"), "state");
    Object.keys(tagEls).forEach(function (k) { if (k.indexOf("comp:") === 0 && k !== "comp:" + mon) tagEls[k].style.display = "none"; });
    if (!mon || !model.comps[mon]) { el2.style.display = "none"; return; }
    var b = bounds(explodeT, model.comps[mon]), c = centre(b), p2 = project([c[0], c[1], b.max[2] + 95]);     // high enough to clear the sensor marker on top
    if (!p2) { el2.style.display = "none"; return; }
    var fr = a.frame, st = fr ? fr.state : null, col2 = st ? (a.state_colors || {})[st] : "#94a3b8";
    el2.innerHTML = esc(a.component_label || mon) + ' · <span style="color:' + col2 + '">' + esc(st ? pretty(st) : "ready") + "</span>";
    el2.style.borderColor = col2; el2.style.display = ""; el2.style.left = p2[0] + "px"; el2.style.top = (p2[1] - 12) + "px";
    el2.classList.toggle("sel", !!(selected && selected.type === "component" && selected.id === mon));
  }

  // ------------------------------------------------------------------ inspector + legend (text from the args only)
  function chip(text, col) { return '<span class="chip" style="color:' + col + '">' + esc(text) + "</span>"; }
  function bar(v, col) { return '<div class="bar"><i style="width:' + Math.max(0, Math.min(1, v || 0)) * 100 + "%;background:" + col + '"></i></div>'; }
  function sensorRows(ids) {
    var a = A || {}, out = "";
    ids.forEach(function (id) {
      var s = (a.sensors || {})[id]; if (!s) return;
      var col = (a.sensor_fill || {})[id] || "#94a3b8";
      out += "<tr><td><span class='dot' style='background:" + col + "'></span><b>" + id + "</b> " + esc(s.short || s.label) +
        "</td><td>" + (s.active ? (s.status ? esc(s.status) + (s.weight != null ? " · w " + fmt(s.weight) : "") : "ready") : "<span class='k'>other replay</span>") + "</td></tr>";
    });
    return out ? "<table>" + out + "</table>" : "";
  }
  function inspector() {
    var a = A || {}, el = $("inspector"), fr = a.frame, html = "";
    if (!model) { el.innerHTML = ""; return; }
    if (selected && selected.type === "sensor") {
      var s = (a.sensors || {})[selected.id] || {}, col = (a.sensor_fill || {})[selected.id] || "#94a3b8";
      html += "<h3>" + esc(selected.id + " · " + (s.label || "")) + "</h3><div class='sub'>" + esc(s.where || "") + "</div>";
      html += "<table><tr><td class='k'>Subsystem</td><td>" + esc(pretty(s.subsystem)) + "</td></tr>" +
        "<tr><td class='k'>Dataset</td><td>" + esc(s.dataset || "") + "</td></tr>" +
        "<tr><td class='k'>Channels</td><td>" + esc((s.channels || []).join(", ")) + "</td></tr>" +
        "<tr><td class='k'>Sample rate</td><td>" + (s.fs_hz ? (s.fs_hz / 1000) + " kHz" : "") + "</td></tr></table>";
      html += "<div class='sec'>";
      if (!s.active) html += "<div class='k'>Not part of the " + esc(pretty(a.subsystem)) + " replay - select " + esc(pretty(s.subsystem)) + " in the sidebar to replay its data.</div>";
      else if (!fr) html += "<div class='k'>No window replayed yet. Press Run or Step.</div>";
      else {
        html += "<table><tr><td class='k'>Quality (this window)</td><td>" + chip((s.status || "").toUpperCase(), col) + "</td></tr>" +
          "<tr><td class='k'>Reliability score</td><td>" + fmt(s.score) + "</td></tr></table>" + bar(s.score, col) +
          "<table><tr><td class='k'>Fusion weight</td><td>" + (s.weight == null ? "n/a (diagnosis suspended)" : fmt(s.weight)) + "</td></tr></table>" +
          (s.weight == null ? "" : bar(s.weight, "#38bdf8")) +
          "<div class='k' style='margin-top:4px'>" + esc(s.reasons && s.reasons.length ? s.reasons.join("; ") : "within learned clean range") + "</div>";
        if (fr.fault_label && fr.fault_label !== "clean") html += "<div class='k' style='margin-top:4px'>Injected (synthetic): " + esc(fr.fault_label) + "</div>";
      }
      html += "</div>";
    } else if (selected) {
      var comp = selected.id, label = (model.asset.component_labels || {})[comp] || pretty(comp);
      var parts = model.comps[comp] || [], part = selected.part ? model.byPart[selected.part] : null;
      var mon = a.monitored || [], other = a.other_monitored || [];
      html += "<h3>" + esc(label) + "</h3><div class='sub'>" + parts.length + " solid" + (parts.length === 1 ? "" : "s") +
        (part ? " · clicked: " + esc(pretty(part.part)) : "") + "</div>";
      if (part && part.ex.purpose) html += "<div class='k'>" + esc(part.ex.purpose) + "</div>";
      var mounted = Object.keys(a.sensors || {}).filter(function (id) { return compOfSensor(id) === comp; });
      html += "<div class='sec'>";
      if (mon.indexOf(comp) >= 0) {
        if (!fr) html += "<div>Monitored in this replay.</div><div class='k'>No window replayed yet. Press Run or Step.</div>";
        else {
          var sc = (a.state_colors || {})[fr.state] || "#94a3b8";
          html += "<table><tr><td class='k'>Health state</td><td>" + chip(pretty(fr.state), sc) + "</td></tr></table>" +
            "<div class='k' style='margin:3px 0 6px'>" + esc(fr.rule || "") + "</div>";
          if (fr.diagnosis_available && fr.probs) {
            Object.keys(fr.probs).forEach(function (k) {
              html += "<table><tr><td>" + esc(pretty(k)) + "</td><td>" + fmt(fr.probs[k]) + "</td></tr></table>" + bar(fr.probs[k], "#64748b");
            });
            html += "<table><tr><td>fault evidence</td><td>" + fmt(fr.p_fault) + "</td></tr></table>" + bar(fr.p_fault, "#f59e0b");
          } else html += "<div class='k'>Diagnosis suspended: no usable sensor in this window.</div>";
          html += "<table style='margin-top:4px'><tr><td class='k'>Window</td><td>" + fr.window + " (recording " + fr.recording_window + "/" + fr.windows_per_recording + ")</td></tr>" +
            "<tr><td class='k'>Recording</td><td>" + esc(fr.recording) + "</td></tr>" +
            "<tr><td class='k'>Ground truth</td><td>" + esc(pretty(fr.ground_truth)) + "</td></tr>" +
            "<tr><td class='k'>Injected fault</td><td>" + esc(fr.fault_label) + "</td></tr></table>";
        }
      } else if (other.indexOf(comp) >= 0) {
        html += "<div class='k'>Monitored in the " + esc(a.other_subsystem) + " replay - select it in the sidebar to replay its data.</div>";
      } else {
        html += mounted.length
          ? "<div class='k'>Its own condition is not diagnosed; the sensors mounted on it feed the replays listed below.</div>"
          : "<div class='k'>Not instrumented and not diagnosed; shown for context.</div>";
      }
      html += "</div>";
      if (mounted.length) html += "<div class='sec'><div class='k' style='margin-bottom:3px'>Sensors mounted here</div>" + sensorRows(mounted) + "</div>";
    }
    el.innerHTML = html;
  }
  function legend() {
    var a = A || {}, sc = a.state_colors || {}, rc = a.rel_colors || {};
    var h = "<div class='row'><span class='lbl'>Health</span>";
    Object.keys(sc).forEach(function (k) { h += "<span><span class='dot' style='background:" + sc[k] + "'></span>" + esc(pretty(k)) + "</span>"; });
    h += "<span class='lbl' style='margin-left:6px'>Sensor quality</span>";
    Object.keys(rc).forEach(function (k) { h += "<span><span class='dot' style='background:" + rc[k] + "'></span>" + esc(k) + "</span>"; });
    h += "<span><span class='dot' style='background:" + (a.inactive || "#475569") + "'></span>other replay</span></div>";
    h += "<div class='note'>" + esc(a.note || "") + "</div>";
    h += "<div class='hint'>Drag: rotate · Right-drag or Shift+drag: pan · Click, then wheel: zoom · Click a part or sensor: inspect · Double-click: focus</div>";
    $("legend").innerHTML = h;
  }

  function refresh() {
    inspector(); legend();
    if (model) { matrices(); placeTags(); }              // tags follow the data even before the next drawn frame
    var fr = (A || {}).frame;
    $("subtitle").textContent = (A && A.subtitle) || "FreeCAD model → STEP → GLB";
    dirty = true; requestRender();
  }

  // ------------------------------------------------------------------ args from Streamlit
  var lastSub = null;
  function onArgs(args) {
    A = args;
    var h = args.height || 620;
    document.body.style.height = h + "px";
    send("streamlit:setFrameHeight", { height: h });
    if (args.subsystem !== lastSub) { lastSub = args.subsystem; autoSel = true; }   // new subsystem: show its component
    if (autoSel) selected = (args.monitored && args.monitored[0]) ? { type: "component", id: args.monitored[0] } : null;
    if (gl && args.model_url && args.model_url !== modelUrl) loadModel(args.model_url);
    if (!args.model_url) { msg.style.display = "flex"; msg.textContent = args.model_error || "No CAD model available."; }
    refresh();
  }

  // ------------------------------------------------------------------ input
  var drag = null, lastPick = 0, wheelArmed = false;   // wheel zooms only after a click in the viewer
  function flashTip(text, px, py) {
    tip.textContent = text; tip.style.display = "block"; tip.style.left = (px + 14) + "px"; tip.style.top = (py + 12) + "px";
    clearTimeout(tip._t); tip._t = setTimeout(function () { tip.style.display = "none"; }, 1400);
  }
  canvas.addEventListener("contextmenu", function (e) { e.preventDefault(); });
  canvas.addEventListener("pointerdown", function (e) {
    canvas.setPointerCapture(e.pointerId);
    wheelArmed = true;
    drag = { x: e.clientX, y: e.clientY, x0: e.clientX, y0: e.clientY, pan: e.button === 2 || e.button === 1 || e.shiftKey, moved: false };
    camAnim = null;
  });
  canvas.addEventListener("pointermove", function (e) {
    var r = canvas.getBoundingClientRect(), px = e.clientX - r.left, py = e.clientY - r.top;
    if (drag) {
      var dx = e.clientX - drag.x, dy = e.clientY - drag.y; drag.x = e.clientX; drag.y = e.clientY;
      if (Math.abs(e.clientX - drag.x0) + Math.abs(e.clientY - drag.y0) > 4) { drag.moved = true; canvas.classList.add("dragging"); tip.style.display = "none"; }
      if (!drag.moved) return;
      if (drag.pan) {
        var b = camBasis(), k = 2 * cam.dist * Math.tan(cam.fov / 2) / Math.max(1, canvas.clientHeight);
        cam.tx += (-dx * b.r[0] + dy * b.u[0]) * k; cam.ty += (-dx * b.r[1] + dy * b.u[1]) * k; cam.tz += (-dx * b.r[2] + dy * b.u[2]) * k;
      } else {
        cam.az -= dx * 0.008; cam.el = Math.max(-0.2, Math.min(1.56, cam.el + dy * 0.006));
      }
      requestRender();
      return;
    }
    var now = performance.now();
    if (now - lastPick < 60 || !model) return;
    lastPick = now;
    var n = pickAt(px, py);
    var changed = (n ? n.name : null) !== (hover ? hover.name : null);
    hover = n;
    canvas.classList.toggle("hovering", !!n);
    if (n) {
      var lab = n.kind === "sensor" ? n.sensor + " · " + ((A && A.sensors && A.sensors[n.sensor]) || {}).label
        : ((model.asset.component_labels || {})[n.comp] || pretty(n.comp)) + " · " + pretty(n.part);
      tip.textContent = lab; tip.style.display = "block"; tip.style.left = (px + 14) + "px"; tip.style.top = (py + 12) + "px";
    } else tip.style.display = "none";
    if (changed) requestRender();
  });
  canvas.addEventListener("pointerleave", function () {
    wheelArmed = false; tip.style.display = "none";
    if (hover) { hover = null; requestRender(); }
  });
  canvas.addEventListener("pointerup", function (e) {
    var d = drag; drag = null; canvas.classList.remove("dragging");
    if (!d) return;
    if (d.moved) { saveCamera(); return; }
    var r = canvas.getBoundingClientRect(), n = pickAt(e.clientX - r.left, e.clientY - r.top);
    autoSel = false;
    if (!n) { selected = null; autoSel = true; onArgs(A || {}); return; }
    selected = n.kind === "sensor" ? { type: "sensor", id: n.sensor } : { type: "component", id: n.comp, part: n.part };
    refresh();
  });
  canvas.addEventListener("dblclick", function (e) {
    var r = canvas.getBoundingClientRect(), n = pickAt(e.clientX - r.left, e.clientY - r.top);
    if (!n) return;
    var list = n.kind === "sensor" ? [n] : model.comps[n.comp];
    var fp = fitParams(list, cam.az, cam.el, 2.2);
    fp.dist = Math.max(220, fp.dist);
    tween(fp, true);
  });
  canvas.addEventListener("wheel", function (e) {
    if (!wheelArmed && !e.ctrlKey) {                     // let the page scroll; zoom after a click (or Ctrl+wheel)
      var r = canvas.getBoundingClientRect();
      flashTip("Click the model first to zoom with the wheel", e.clientX - r.left, e.clientY - r.top);
      return;
    }
    e.preventDefault(); camAnim = null;
    cam.dist = Math.max(60, Math.min(9000, cam.dist * Math.exp(e.deltaY * 0.0011)));
    requestRender(); clearTimeout(canvas._st); canvas._st = setTimeout(saveCamera, 300);
  }, { passive: false });

  $("b-reset").onclick = function () { explodeTarget = 0; $("explode").value = 0; setView("iso", true); };
  $("b-fit").onclick = function () { fit(true); };
  Array.prototype.forEach.call(document.querySelectorAll("[data-view]"), function (b) { b.onclick = function () { setView(b.getAttribute("data-view"), true); }; });
  $("b-xray").onclick = function () { xray = !xray; this.classList.toggle("on", xray); saveCamera(); requestRender(); };
  $("b-edges").onclick = function () { edges = !edges; this.classList.toggle("on", edges); saveCamera(); requestRender(); };
  $("explode").oninput = function () { explodeTarget = this.value / 100; saveCamera(); requestRender(); };
  window.addEventListener("resize", function () { requestRender(); });
  if (window.ResizeObserver) new ResizeObserver(function () { requestRender(); }).observe(canvas);

  send("streamlit:componentReady", { apiVersion: 1 });
  send("streamlit:setFrameHeight", { height: 620 });
})();
