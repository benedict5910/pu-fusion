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

  // Surface finishes (display only): sRGB albedo, metalness, roughness. The finish of every solid comes from the CAD
  // model (node.extras.finish); older GLB files without it fall back to a name-based guess (finishOf).
  var FINISH = {
    painted:       { c: "#4f5968", m: 0.05, r: 0.42 },   // motor frame, cowl, terminal box: painted steel
    painted_dark:  { c: "#30363f", m: 0.10, r: 0.52 },   // riser, plinth, pedestal
    plate:         { c: "#7a818b", m: 0.70, r: 0.38 },   // base plate: ground steel
    painted_load:  { c: "#46524c", m: 0.05, r: 0.45 },   // load unit
    cast:          { c: "#8b929c", m: 0.45, r: 0.48 },   // bearing housings, gearbox housing and cover
    machined:      { c: "#c9cdd3", m: 1.00, r: 0.24 },   // shafts, collars (turned steel)
    black_oxide:   { c: "#34373c", m: 0.85, r: 0.36 },   // coupling hubs
    elastomer:     { c: "#1f2227", m: 0.00, r: 0.80 },   // coupling spiders
    bearing_steel: { c: "#d7dade", m: 1.00, r: 0.16 },   // rings and balls
    gear:          { c: "#b3b6bb", m: 1.00, r: 0.30 },
    cable:         { c: "#15171b", m: 0.00, r: 0.60 },
    sensor:        { c: "#94a3b8", m: 0.30, r: 0.35 }
  };
  var ACCENT = [0.13, 0.83, 0.93];                        // cyan: selection

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

  // ------------------------------------------------------------------ shaders (GLSL ES 1.0: WebGL 1 and 2)
  // Physically based shading: GGX specular + Lambert diffuse for a key light (with a soft shadow map), a fill and a
  // rim light, plus an analytic studio environment (gradient sky + two soft boxes) for reflections on metal; ACES
  // tone mapping and sRGB output. Everything is computed from the CAD geometry; no textures are loaded.
  var VS = "attribute vec3 aPos; attribute vec3 aNrm; uniform mat4 uVP; uniform mat4 uLVP; uniform vec3 uOff;" +
    "varying vec3 vW; varying vec3 vN; varying vec4 vL;" +
    "void main(){ vec3 w=aPos+uOff; vW=w; vN=aNrm; vL=uLVP*vec4(w,1.0); gl_Position=uVP*vec4(w,1.0); }";
  var COMMON = "precision highp float;" +
    "float unpack(vec4 c){ return dot(c, vec4(1.0, 1.0/255.0, 1.0/65025.0, 1.0/16581375.0)); }" +
    "uniform sampler2D uShadow; uniform float uShadowOn; uniform vec2 uShadowTexel;" +
    "float shadowAt(vec4 lp, float bias){ if(uShadowOn<0.5) return 1.0; vec3 p=lp.xyz/lp.w*0.5+0.5;" +
    " if(p.x<0.0||p.x>1.0||p.y<0.0||p.y>1.0||p.z>1.0) return 1.0; float s=0.0;" +
    " for(int i=-2;i<=2;i++) for(int j=-2;j<=2;j++){ vec2 o=vec2(float(i),float(j))*uShadowTexel*1.25;" +
    "  s+= (p.z-bias > unpack(texture2D(uShadow,p.xy+o))) ? 0.0 : 1.0; }" +
    " return s/25.0; }";
  var FS = COMMON +
    "varying vec3 vW; varying vec3 vN; varying vec4 vL; uniform vec3 uEye; uniform vec3 uColor; uniform vec3 uEmis;" +
    "uniform float uAlpha; uniform float uMetal; uniform float uRough; uniform vec3 uLight; uniform float uBrushed;" +
    "uniform vec3 uRim; uniform float uFloor;" +
    "const float PI=3.14159265;" +
    "float D_GGX(float nh,float a){ float a2=a*a; float d=nh*nh*(a2-1.0)+1.0; return a2/(PI*d*d); }" +
    "float V_SmithGGX(float nl,float nv,float a){ float k=a*0.5; return 0.25/((nl*(1.0-k)+k)*(nv*(1.0-k)+k)); }" +
    "vec3 F_Schlick(vec3 f0,float vh){ return f0+(1.0-f0)*pow(1.0-vh,5.0); }" +
    "vec3 env(vec3 r,float rough){" +              // studio environment, blurred by roughness
    " float hz=r.z; vec3 col=mix(vec3(0.018,0.021,0.026),vec3(0.13,0.15,0.18),smoothstep(-0.35,0.05,hz));" +
    " col=mix(col,vec3(0.30,0.34,0.40),smoothstep(0.0,0.9,hz));" +
    " float sh=mix(260.0,6.0,rough); float k=mix(1.0,0.10,rough);" +
    " col+=vec3(2.6,2.55,2.45)*k*pow(max(dot(r,normalize(vec3(-0.35,-0.55,0.76))),0.0),sh);" +
    " col+=vec3(0.9,1.05,1.25)*k*pow(max(dot(r,normalize(vec3(0.75,0.35,0.35))),0.0),sh*0.7);" +
    " col+=vec3(0.35,0.42,0.5)*k*pow(max(dot(r,normalize(vec3(-0.6,0.7,0.25))),0.0),sh*0.5);" +
    " return col; }" +
    "vec2 envBRDF(float nv,float rough){ vec4 c0=vec4(-1.0,-0.0275,-0.572,0.022); vec4 c1=vec4(1.0,0.0425,1.04,-0.04);" +
    " vec4 r=rough*c0+c1; float a004=min(r.x*r.x,exp2(-9.28*nv))*r.x+r.y; return vec2(-1.04,1.04)*a004+r.zw; }" +
    "float hash(float n){ return fract(sin(n)*43758.5453); }" +
    "vec3 light(vec3 n,vec3 v,vec3 l,vec3 c,vec3 albedo,vec3 f0,float a){ float nl=max(dot(n,l),0.0); if(nl<=0.0) return vec3(0.0);" +
    " vec3 h=normalize(l+v); float nv=max(dot(n,v),1e-4); vec3 F=F_Schlick(f0,max(dot(v,h),0.0));" +
    " vec3 spec=D_GGX(max(dot(n,h),0.0),a)*V_SmithGGX(nl,nv,a)*F; vec3 kd=(1.0-F)*(1.0-uMetal);" +
    " return (kd*albedo/PI+spec)*c*nl; }" +
    "vec3 aces(vec3 x){ return clamp((x*(2.51*x+0.03))/(x*(2.43*x+0.59)+0.14),0.0,1.0); }" +
    "void main(){ vec3 n=normalize(vN); vec3 v=normalize(uEye-vW); if(dot(n,v)<0.0) n=-n;" +
    " float rough=uRough; if(uBrushed>0.5){ float st=hash(floor(vW.x*2.3))*0.6+hash(floor(vW.x*0.7))*0.4; rough=clamp(rough*(0.75+0.55*st),0.08,1.0); }" +
    " float a=max(rough*rough,0.002); vec3 f0=mix(vec3(0.04),uColor,uMetal); vec3 albedo=uColor;" +
    " float sh=shadowAt(vL, 0.0015+0.002*(1.0-max(dot(n,uLight),0.0)));" +
    " vec3 c=light(n,v,uLight,vec3(3.1,3.0,2.85),albedo,f0,a)*sh;" +
    " c+=light(n,v,normalize(vec3(0.7,0.55,0.35)),vec3(0.55,0.65,0.85),albedo,f0,a);" +
    " c+=light(n,v,normalize(vec3(0.15,0.9,-0.05)),vec3(0.45,0.5,0.6),albedo,f0,a);" +
    " float nv=max(dot(n,v),1e-4); vec2 eb=envBRDF(nv,rough); vec3 r=reflect(-v,n);" +
    " float ao=mix(0.55,1.0,smoothstep(uFloor,uFloor+70.0,vW.z));" +          // ground occlusion
    " vec3 irr=mix(vec3(0.035,0.04,0.05),vec3(0.20,0.23,0.28),0.5+0.5*n.z);" +
    " c+=(albedo*(1.0-uMetal)*irr + env(r,rough)*(f0*eb.x+eb.y))*ao*mix(0.65,1.0,sh);" +
    " float fr=pow(1.0-nv,3.0); c+=uRim*fr*1.6+uEmis;" +
    " c=aces(c*1.35); c=pow(c,vec3(1.0/2.2)); gl_FragColor=vec4(c,uAlpha); }";
  // depth pass for the key-light shadow map (depth packed into RGBA8: works without depth textures)
  var SVS = "attribute vec3 aPos; uniform mat4 uLVP; uniform vec3 uOff; varying float vD;" +
    "void main(){ vec4 p=uLVP*vec4(aPos+uOff,1.0); vD=p.z/p.w*0.5+0.5; gl_Position=p; }";
  var SFS = "precision highp float; varying float vD;" +
    "vec4 pack(float d){ vec4 e=fract(vec4(1.0,255.0,65025.0,16581375.0)*d); e-=e.yzww*vec4(1.0/255.0,1.0/255.0,1.0/255.0,0.0); return e; }" +
    "void main(){ gl_FragColor=pack(vD); }";
  var LVS = "attribute vec3 aPos; uniform mat4 uVP; uniform vec3 uOff; void main(){ gl_Position=uVP*vec4(aPos+uOff,1.0); }";
  var LFS = "precision mediump float; uniform vec4 uRGBA; void main(){ gl_FragColor=uRGBA; }";
  // floor: receives the soft shadow, fades out radially, faint engineering grid
  var GVS = "attribute vec3 aPos; uniform mat4 uVP; uniform mat4 uLVP; varying vec3 vW; varying vec4 vL;" +
    "void main(){ vW=aPos; vL=uLVP*vec4(aPos,1.0); gl_Position=uVP*vec4(aPos,1.0); }";
  var GFS = COMMON + "varying vec3 vW; varying vec4 vL; uniform vec4 uRect;" +
    "void main(){ vec2 q=(vW.xy-uRect.xy)/uRect.zw; float fade=1.0-smoothstep(0.35,1.0,length(q));" +
    " float s=shadowAt(vL,0.002); vec2 g=abs(fract(vW.xy/50.0-0.5)-0.5);" +
    " float line=1.0-smoothstep(0.0,0.018,min(g.x,g.y));" +
    " float contact=1.0-smoothstep(0.0,1.0,length(q*vec2(0.95,0.75)));" +
    " float a=((1.0-s)*0.62+contact*0.18)*fade; vec3 col=vec3(0.0);" +
    " col=mix(col,vec3(0.55,0.65,0.78),line*0.10*fade); a=max(a,line*0.10*fade);" +
    " gl_FragColor=vec4(col,a); }";
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
  var P = null, PL = null, PG = null, PS = null, uintExt = null;
  if (gl) {
    try {
      P = program(VS, FS); PL = program(LVS, LFS); PG = program(GVS, GFS); PS = program(SVS, SFS);
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
      o.fin = FINISH[ex.finish] || FINISH[finishOf(o)];
      o.base = lin(hex(o.fin.c));
      o.see = o.kind === "part" && /housing|cover/.test(o.part);
      o.pick = nodes.length + 1;
      nodes.push(o);
      if (o.kind === "part") (comps[o.comp] = comps[o.comp] || []).push(o);
    });
    var asset = (json.asset && json.asset.extras) || {};
    return { nodes: nodes, comps: comps, asset: asset, byPart: nodes.reduce(function (m, n) { m[n.part] = n; return m; }, {}) };
  }

  function finishOf(o) {
    if (o.kind === "sensor") return "sensor";
    var p = o.part || "";
    if (/pinion|gear_wheel/.test(p)) return "gear";
    if (/ball|ring/.test(p)) return "bearing_steel";
    if (/shaft/.test(p)) return "machined";
    if (/housing|cover/.test(p)) return "cast";
    if (/spider/.test(p)) return "elastomer";
    if (/coupling/.test(o.comp)) return "black_oxide";
    if (/cable/.test(p)) return "cable";
    if (/base|riser|plinth|pedestal/.test(p)) return "painted_dark";
    return o.comp === "load" ? "painted_load" : "painted";
  }
  function lin(c) { return c.map(function (v) { return Math.pow(v, 2.2); }); }

  function loadModel(url) {
    modelUrl = url;
    msg.style.display = "flex"; msg.textContent = "Loading CAD model…";
    fetch(url).then(function (r) { if (!r.ok) throw new Error("HTTP " + r.status); return r.arrayBuffer(); })
      .then(function (ab) {
        model = parseGLB(ab);
        makeGround();
        msg.style.display = "none";
        if (!restoreCamera()) { setView("iso", false); autoView = "iso"; }
        refresh();
      })
      .catch(function (e) { msg.style.display = "flex"; msg.textContent = "Could not load the CAD model (" + e.message + ")."; });
  }

  // ------------------------------------------------------------------ floor + key-light shadow map
  var ground = null, LIGHT = norm([-0.42, -0.62, 0.66]), SHADOW_N = 2048;
  var shadow = { fbo: null, tex: null, rb: null, vp: null, dirty: true, t: -1 };
  function makeGround() {
    var b = bounds(0), z = b.min[2] - 0.5, cx = (b.min[0] + b.max[0]) / 2, cy = (b.min[1] + b.max[1]) / 2;
    var hx = (b.max[0] - b.min[0]) * 1.05, hy = (b.max[1] - b.min[1]) * 2.2;
    var q = new Float32Array([cx - hx, cy - hy, z, cx + hx, cy - hy, z, cx + hx, cy + hy, z, cx - hx, cy - hy, z, cx + hx, cy + hy, z, cx - hx, cy + hy, z]);
    ground = { q: buf(gl.ARRAY_BUFFER, q), rect: [cx, cy, hx, hy], z: z };
    shadow.dirty = true;
  }
  function ortho(l, r, b, t, n, f) {
    return [2 / (r - l), 0, 0, 0, 0, 2 / (t - b), 0, 0, 0, 0, -2 / (f - n), 0, -(r + l) / (r - l), -(t + b) / (t - b), -(f + n) / (f - n), 1];
  }
  function renderShadow() {
    if (!shadow.fbo) {
      shadow.fbo = gl.createFramebuffer(); shadow.tex = gl.createTexture(); shadow.rb = gl.createRenderbuffer();
      gl.bindTexture(gl.TEXTURE_2D, shadow.tex);
      gl.texImage2D(gl.TEXTURE_2D, 0, gl.RGBA, SHADOW_N, SHADOW_N, 0, gl.RGBA, gl.UNSIGNED_BYTE, null);
      gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MIN_FILTER, gl.NEAREST); gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MAG_FILTER, gl.NEAREST);
      gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_WRAP_S, gl.CLAMP_TO_EDGE); gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_WRAP_T, gl.CLAMP_TO_EDGE);
      gl.bindRenderbuffer(gl.RENDERBUFFER, shadow.rb); gl.renderbufferStorage(gl.RENDERBUFFER, gl.DEPTH_COMPONENT16, SHADOW_N, SHADOW_N);
      gl.bindFramebuffer(gl.FRAMEBUFFER, shadow.fbo);
      gl.framebufferTexture2D(gl.FRAMEBUFFER, gl.COLOR_ATTACHMENT0, gl.TEXTURE_2D, shadow.tex, 0);
      gl.framebufferRenderbuffer(gl.FRAMEBUFFER, gl.DEPTH_ATTACHMENT, gl.RENDERBUFFER, shadow.rb);
    }
    // light-space box around the (possibly exploded) assembly
    var b = bounds(explodeT), c = centre(b), rad = Math.hypot(b.max[0] - b.min[0], b.max[1] - b.min[1], b.max[2] - b.min[2]) / 2 + 20;
    var eyeL = [c[0] + LIGHT[0] * rad * 2, c[1] + LIGHT[1] * rad * 2, c[2] + LIGHT[2] * rad * 2];
    shadow.vp = mul(ortho(-rad, rad, -rad, rad, rad * 0.5, rad * 3.6), lookAt(eyeL, c, [0, 0, 1]));
    gl.bindFramebuffer(gl.FRAMEBUFFER, shadow.fbo);
    gl.viewport(0, 0, SHADOW_N, SHADOW_N); gl.disable(gl.BLEND); gl.enable(gl.DEPTH_TEST);
    gl.clearColor(1, 1, 1, 1); gl.clear(gl.COLOR_BUFFER_BIT | gl.DEPTH_BUFFER_BIT);
    gl.useProgram(PS.p); gl.uniformMatrix4fv(PS.u.uLVP, false, shadow.vp); gl.disableVertexAttribArray(1);
    model.nodes.forEach(function (n) {
      if (!n.tri) return;
      gl.uniform3fv(PS.u.uOff, off(n, explodeT));
      gl.bindBuffer(gl.ARRAY_BUFFER, n.tri.vb); gl.enableVertexAttribArray(0); gl.vertexAttribPointer(0, 3, gl.FLOAT, false, 0, 0);
      gl.bindBuffer(gl.ELEMENT_ARRAY_BUFFER, n.tri.ib);
      gl.drawElements(gl.TRIANGLES, n.tri.n, n.tri.type, 0);
    });
    gl.bindFramebuffer(gl.FRAMEBUFFER, null);
    gl.enable(gl.BLEND);
    shadow.dirty = false; shadow.t = explodeT;
  }
  function bindShadow(prog) {
    gl.activeTexture(gl.TEXTURE0); gl.bindTexture(gl.TEXTURE_2D, shadow.tex);
    gl.uniform1i(prog.u.uShadow, 0); gl.uniform1f(prog.u.uShadowOn, shadow.vp ? 1 : 0);
    gl.uniform2fv(prog.u.uShadowTexel, [1 / SHADOW_N, 1 / SHADOW_N]);
    gl.uniformMatrix4fv(prog.u.uLVP, false, shadow.vp);
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
  var VIEWS = { iso: [-1.02, 0.48], front: [-Math.PI / 2, 0.04], top: [-Math.PI / 2, 1.553], side: [0, 0.06] };
  // tight fit: project the 8 bbox corners for a view direction and solve for the camera distance
  function freeRect() {                                   // canvas area not covered by the inspector and the legend
    var w = canvas.clientWidth, h = canvas.clientHeight;
    var ins = $("inspector"), leg = $("legend");
    var right = ins.offsetWidth && w > 2 * ins.offsetWidth ? w - ins.offsetWidth - 24 : w;
    var bottom = leg.offsetHeight && h > 3 * leg.offsetHeight ? h - leg.offsetHeight - 18 : h;
    return { l: 0, r: right, t: 10, b: bottom, w: w, h: h };
  }
  function fitParams(list, az, el, margin) {
    var b = bounds(explodeT, list), c = centre(b), pts = [];
    (list || model.nodes).forEach(function (n) {                 // corners of every solid: a tighter fit than the
      var o = off(n, explodeT);                                  // corners of the overall box
      for (var i = 0; i < 8; i++) pts.push([(i & 1 ? n.bbox[3] : n.bbox[0]) + o[0], (i & 2 ? n.bbox[4] : n.bbox[1]) + o[1], (i & 4 ? n.bbox[5] : n.bbox[2]) + o[2]]);
    });
    var ce = Math.cos(el), back = [ce * Math.cos(az), ce * Math.sin(az), Math.sin(el)];   // target -> eye
    var f = [-back[0], -back[1], -back[2]], r = norm(cross(f, [0, 0, 1])), u = cross(r, f);
    var R = freeRect(), w = R.w || 1, h = R.h || 1, asp = w / h;
    var fx = (R.r - R.l) / w, fy = (R.b - R.t) / h;
    var tv = Math.tan(cam.fov / 2), th = tv * asp, d = 0;
    var cxN = (R.l + R.r) / w - 1, cyN = 1 - (R.t + R.b) / h;       // centre of the free area in NDC
    // exact perspective fit of every corner into [centre +- half free size] with the target shifted so that the
    // assembly centre lands in the middle of the free area (points nearer the camera are magnified more)
    for (var i = 0; i < pts.length; i++) {
      var q = sub(pts[i], c), x = dot(q, r), y = dot(q, u), z = dot(q, back);
      d = Math.max(d, (x / th + (cxN + fx) * z) / fx, (-x / th - (cxN - fx) * z) / fx,
                      (y / tv + (cyN + fy) * z) / fy, (-y / tv - (cyN - fy) * z) / fy);
    }
    d = Math.max(120, d * (margin || 1.03));
    var sx = -cxN * d * th, sy = -cyN * d * tv;
    return { tx: c[0] + r[0] * sx + u[0] * sy, ty: c[1] + r[1] * sx + u[1] * sy, tz: c[2] + r[2] * sx + u[2] * sy, dist: d };
  }
  function fit(animate, list) { tween(fitParams(list, cam.az, cam.el), animate); }
  var autoView = null;           // camera still at a fitted standard view: re-fit it when the frame size changes
  function setView(name, animate) {
    autoView = name;
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
    try { sessionStorage.setItem("ivhm_cam_v4", JSON.stringify({ c: cam, x: xray, e: edges, t: explodeTarget })); } catch (e) { /* storage unavailable */ }
  }
  function restoreCamera() {
    try {
      var s = JSON.parse(sessionStorage.getItem("ivhm_cam_v4") || "null");
      if (!s) return false;
      Object.assign(cam, s.c); xray = !!s.x; edges = s.e !== false; explodeT = explodeTarget = s.t || 0;
      $("explode").value = Math.round(explodeTarget * 100);
      $("b-xray").classList.toggle("on", xray); $("b-edges").classList.toggle("on", edges);
      return true;
    } catch (e) { return false; }
  }

  // ------------------------------------------------------------------ appearance from the args (replay output)
  function look(n) {
    var a = A || {}, f = n.fin || FINISH.painted, c = n.base.slice(), em = [0, 0, 0], rim = [0, 0, 0], alpha = 1, stateEdge = null;
    var metal = f.m, rough = f.r;
    if (n.kind === "sensor") {
      var sc = lin(hex((a.sensor_fill || {})[n.sensor] || FINISH.sensor.c));
      c = sc; em = sc.map(function (v) { return v * 0.30; }); metal = 0.25; rough = 0.32;
    } else if ((a.part_fill || {})[n.comp]) {               // health state of the monitored component (from the replay)
      var s = lin(hex(a.part_fill[n.comp]));
      c = mix(c.map(function (v) { return v * 0.55; }), s, 0.36); em = s.map(function (v) { return v * 0.035; }); rim = s.map(function (v) { return v * 0.9; });
      metal = Math.min(metal, 0.3); stateEdge = hex(a.part_fill[n.comp]);
    }
    var selComp = selected && selected.type === "component" ? selected.id : null;
    var selSensor = selected && selected.type === "sensor" ? selected.id : null;
    var isSel = (selComp && n.kind === "part" && n.comp === selComp) || (selSensor && n.sensor === selSensor);
    if (isSel && autoSel && stateEdge) isSel = false;     // auto-selected monitored part: show its health colour, not cyan
    if (isSel) { rim = [rim[0] + ACCENT[0] * 0.4, rim[1] + ACCENT[1] * 0.4, rim[2] + ACCENT[2] * 0.4]; em = [em[0] + 0.003, em[1] + 0.02, em[2] + 0.024]; }
    var hv = hover && ((hover.kind === "sensor" && n.sensor === hover.sensor) || (hover.kind === "part" && n.kind === "part" && n.comp === hover.comp));
    if (hv) { em = [em[0] + 0.025, em[1] + 0.03, em[2] + 0.035]; rim = [rim[0] + 0.12, rim[1] + 0.16, rim[2] + 0.2]; }
    if (xray && n.see) alpha = 0.16;
    return { c: c, em: em, rim: rim, a: alpha, sel: isSel, m: metal, r: rough, brushed: f === FINISH.machined ? 1 : 0, edge: stateEdge };
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
    if (shadow.dirty || Math.abs(shadow.t - explodeT) > 1e-4) renderShadow();
    matrices();
    gl.viewport(0, 0, canvas.width, canvas.height);
    gl.clearColor(0, 0, 0, 0); gl.clear(gl.COLOR_BUFFER_BIT | gl.DEPTH_BUFFER_BIT);
    gl.enable(gl.DEPTH_TEST); gl.enable(gl.BLEND); gl.blendFunc(gl.SRC_ALPHA, gl.ONE_MINUS_SRC_ALPHA);
    // floor: soft shadow of the key light + faint grid, no depth write
    gl.depthMask(false);
    gl.useProgram(PG.p); gl.uniformMatrix4fv(PG.u.uVP, false, VP); gl.uniform4fv(PG.u.uRect, ground.rect); bindShadow(PG);
    gl.disableVertexAttribArray(1);
    gl.bindBuffer(gl.ARRAY_BUFFER, ground.q); gl.enableVertexAttribArray(0); gl.vertexAttribPointer(0, 3, gl.FLOAT, false, 0, 0);
    gl.drawArrays(gl.TRIANGLES, 0, 6);
    gl.depthMask(true);

    var looks = model.nodes.map(look), opaque = [], trans = [];
    model.nodes.forEach(function (n, i) { (looks[i].a < 1 ? trans : opaque).push(i); });
    gl.useProgram(P.p); gl.uniformMatrix4fv(P.u.uVP, false, VP); gl.uniform3fv(P.u.uEye, eye);
    gl.uniform3fv(P.u.uLight, LIGHT); gl.uniform1f(P.u.uFloor, ground.z); bindShadow(P);
    gl.enable(gl.POLYGON_OFFSET_FILL); gl.polygonOffset(1, 1);
    opaque.forEach(function (i) { drawNode(model.nodes[i], looks[i]); });
    var e = eye;                                          // see-through parts, back to front, without writing depth
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
    // B-rep feature edges: thin and dark (cyan on the selection) - they sharpen silhouettes like a CAD viewport
    if (edges) {
      gl.useProgram(PL.p); gl.uniformMatrix4fv(PL.u.uVP, false, VP); gl.disableVertexAttribArray(1);
      model.nodes.forEach(function (n, i) {
        if (!n.lines) return;
        var L = looks[i];
        gl.uniform4fv(PL.u.uRGBA, L.sel ? [ACCENT[0], ACCENT[1], ACCENT[2], 0.85] : L.edge ? [L.edge[0], L.edge[1], L.edge[2], 0.7]
          : [0.02, 0.03, 0.05, L.a < 1 ? 0.22 : 0.42]);
        gl.uniform3fv(PL.u.uOff, off(n, explodeT));
        gl.bindBuffer(gl.ARRAY_BUFFER, n.lines.vb); gl.enableVertexAttribArray(0); gl.vertexAttribPointer(0, 3, gl.FLOAT, false, 0, 0);
        gl.drawArrays(gl.LINES, 0, n.lines.n);
      });
    }
  }
  function drawNode(n, L) {
    if (!n.tri) return;
    gl.uniform3fv(P.u.uOff, off(n, explodeT)); gl.uniform3fv(P.u.uColor, L.c); gl.uniform3fv(P.u.uEmis, L.em);
    gl.uniform3fv(P.u.uRim, L.rim); gl.uniform1f(P.u.uAlpha, L.a); gl.uniform1f(P.u.uMetal, L.m);
    gl.uniform1f(P.u.uRough, L.r); gl.uniform1f(P.u.uBrushed, L.brushed);
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
  // Callouts: each label sits above its anchor on a leader line; labels are pushed apart (never over each other)
  // and kept clear of the toolbar and the inspector so they do not hide the machine's controls or readouts.
  function rectOf(el) { return { l: el.offsetLeft, t: el.offsetTop, r: el.offsetLeft + el.offsetWidth, b: el.offsetTop + el.offsetHeight }; }
  function hit(a, b, pad) { return a.l < b.r + pad && a.r > b.l - pad && a.t < b.b + pad && a.b > b.t - pad; }
  function placeTags() {
    if (!model || !VP) return;
    var a = A || {}, sensors = a.sensors || {}, items = [];
    model.nodes.forEach(function (n) {
      if (n.kind !== "sensor") return;
      var s = sensors[n.sensor] || {}, el = tagEl("sensor:" + n.sensor, "");
      var o = off(n, explodeT), p = project([(n.bbox[0] + n.bbox[3]) / 2 + o[0], (n.bbox[1] + n.bbox[4]) / 2 + o[1], n.bbox[5] + o[2]]);
      if (!p) { el.style.display = "none"; return; }
      var col = (a.sensor_fill || {})[n.sensor] || "#94a3b8";
      var status = s.active ? (s.status ? s.status.toUpperCase() : "READY") : "other replay";
      el.innerHTML = '<span class="dot" style="background:' + col + '"></span>' + n.sensor +
        ' <span style="color:' + (s.active ? col : "#64748b") + ';font-weight:500">' + esc(status) + "</span>";
      el.classList.toggle("inactive", !s.active);
      el.classList.toggle("sel", !!(selected && selected.type === "sensor" && selected.id === n.sensor));
      el.style.display = "";
      items.push({ el: el, p: p, rise: s.active ? 44 : 30, col: s.active ? col : "#475569", prio: s.active ? 1 : 2 });
    });
    // state chip above the monitored component of the selected subsystem
    var mon = (a.monitored || [])[0], el2 = tagEl("comp:" + (mon || "none"), "state");
    Object.keys(tagEls).forEach(function (k) { if (k.indexOf("comp:") === 0 && k !== "comp:" + mon) tagEls[k].style.display = "none"; });
    if (mon && model.comps[mon]) {
      var b = bounds(explodeT, model.comps[mon]), c = centre(b), p2 = project([c[0], c[1] - (b.max[1] - b.min[1]) * 0.25, b.max[2]]);
      if (p2) {
        var fr = a.frame, st = fr ? fr.state : null, col2 = st ? (a.state_colors || {})[st] : "#94a3b8";
        el2.innerHTML = esc(a.component_label || mon) + ' · <span style="color:' + col2 + '">' + esc(st ? pretty(st) : "ready") + "</span>";
        el2.style.borderColor = col2; el2.style.display = "";
        el2.classList.toggle("sel", !!(selected && selected.type === "component" && selected.id === mon));
        items.unshift({ el: el2, p: p2, rise: 96, col: col2, prio: 0 });
      } else el2.style.display = "none";
    } else el2.style.display = "none";
    // layout: highest priority first; push each label up until it clears the ones already placed
    var R = freeRect(), placed = [], avoid = [rectOf($("toolbar")), rectOf($("title"))], lines = "";
    if ($("inspector").offsetWidth) avoid.push(rectOf($("inspector")));
    items.sort(function (x, y) { return x.prio - y.prio || x.p[0] - y.p[0]; });
    items.forEach(function (it) {
      var w = it.el.offsetWidth, h = it.el.offsetHeight;
      var lean = it.prio === 2 ? 38 : 0;                      // inactive sensors lean aside so leaders do not cross
      var x = Math.max(w / 2 + 6, Math.min(R.r - w / 2 - 6, it.p[0] + lean)), y = it.p[1] - it.rise;
      for (var k = 0; k < 24; k++) {
        var rc = { l: x - w / 2, r: x + w / 2, t: y - h, b: y }, clash = null;
        placed.concat(avoid).forEach(function (q) { if (!clash && hit(rc, q, 5)) clash = q; });
        if (!clash) break;
        if (avoid.indexOf(clash) >= 0 && clash.l > R.r - 1) x = clash.l - w / 2 - 8;            // inspector: move left
        else if (avoid.indexOf(clash) >= 0 && clash.l < 40) x = clash.r + w / 2 + 8;           // toolbar/title: move right
        else y = clash.t - 6;                                                                  // another label: move up
      }
      y = Math.max(h + 4, y);
      it.el.style.left = x + "px"; it.el.style.top = y + "px";
      placed.push({ l: x - w / 2, r: x + w / 2, t: y - h, b: y });
      lines += '<line x1="' + it.p[0].toFixed(1) + '" y1="' + it.p[1].toFixed(1) + '" x2="' + x.toFixed(1) + '" y2="' + y.toFixed(1) +
        '" stroke="' + it.col + '" stroke-opacity="' + (it.prio === 2 ? 0.35 : 0.8) + '" stroke-width="1"/>' +
        '<circle cx="' + it.p[0].toFixed(1) + '" cy="' + it.p[1].toFixed(1) + '" r="2.6" fill="' + it.col + '" fill-opacity="' + (it.prio === 2 ? 0.4 : 1) + '"/>';
    });
    $("leaders").innerHTML = lines;
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
        "<div class='k' style='font-size:10.5px;margin-left:13px'>" + esc((s.channels || []).join(", ")) + "</div></td><td>" + (s.active ? (s.status ? esc(s.status) + (s.weight != null ? " · w " + fmt(s.weight) : "") : "ready") : "<span class='k'>other replay</span>") + "</td></tr>";
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
        if (!fr) html += "<div>Monitored in this replay (" + esc(pretty(a.subsystem)) + ").</div><div class='k'>No window replayed yet. Press Run or Step.</div>";
        else {
          var sc = (a.state_colors || {})[fr.state] || "#94a3b8";
          var ds = mounted.map(function (id) { return ((a.sensors || {})[id] || {}).dataset; }).filter(Boolean)[0];
          html += "<table><tr><td class='k'>Subsystem</td><td>" + esc(pretty(a.subsystem)) + (ds ? " · " + esc(ds) : "") + "</td></tr>" +
            "<tr><td class='k'>Health state</td><td>" + chip(pretty(fr.state), sc) + "</td></tr></table>" +
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
      autoView = null;
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
    var bb = bounds(explodeT, list), diag = Math.hypot(bb.max[0] - bb.min[0], bb.max[1] - bb.min[1], bb.max[2] - bb.min[2]);
    var fp = fitParams(list, cam.az, cam.el, diag > 600 ? 1.08 : diag > 150 ? 1.5 : 2.2);   // small parts get context
    fp.dist = Math.max(220, fp.dist);
    autoView = null; tween(fp, true);
  });
  canvas.addEventListener("wheel", function (e) {
    if (!wheelArmed && !e.ctrlKey) {                     // let the page scroll; zoom after a click (or Ctrl+wheel)
      var r = canvas.getBoundingClientRect();
      flashTip("Click the model first to zoom with the wheel", e.clientX - r.left, e.clientY - r.top);
      return;
    }
    e.preventDefault(); camAnim = null; autoView = null;
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
  var lastSize = "";
  if (window.ResizeObserver) new ResizeObserver(function () {
    var sz = canvas.clientWidth + "x" + canvas.clientHeight;
    if (sz !== lastSize && model && autoView) { var v = autoView; setView(v, false); }
    lastSize = sz; requestRender();
  }).observe(canvas);

  send("streamlit:componentReady", { apiVersion: 1 });
  send("streamlit:setFrameHeight", { height: 620 });
})();
