// The snakes in a Three.js studio: meshes from geometry.js, a procedural softbox
// environment, baked ambient occlusion, eyes, and a painted contact shadow on a white
// ground. The camera frames the reference image exactly: one world unit is one
// reference pixel, so a still at 1448 x 1086 lines up with the reference pixel for pixel.
import * as THREE from "three";
import { centrelines, strandSurface, headSurface, headSurface2, balls, occlusion, headKey, sub, add, mul, dot, unit, norm, clamp, smoothstep } from "./geometry.js";

export const FRAME = { width: 1448, height: 1086 };

export const LOOK = {
  yellow: "#ffc22e",
  blue: "#0d4fd6",
  eye: "#0a0f24",
  background: "#ffffff",
  head: { snoutLen: 1.0, snoutQ: 2.2, q: 2.4, wide: 1.06, flat: 0.96 }, // snoutLen and snoutQ as the fit (params "snout")
  eyeR: 15,
  headBlend: 24, // smooth-union radius between head and neck
  eyes: [[369, 336], [1103, 324]], // reference pixels: yellow's eye, blue's eye
  ao: { k: 0.085, groundK: 0.35, groundFall: 70 },
  material: { roughness: 0.32, clearcoat: 1, clearcoatRoughness: 0.06 },
  envLevel: 1.0,
  env: { room: 0.18, key: 16, keySize: 1.8, keyPos: [-4.2, 4.6, 5.0], over: 4, front: 0.9, fill: 1.0, rim: 2.0, floor: 0.9 },
  toneMapping: "none",
  exposure: 1.0,
  shadow: { colour: [0.3, 0.2, 0.16], broad: 0.006, contact: 0.06 },
};

// A softbox studio: a dim room, a broad box overhead for the tops, a small key box at
// upper left for each coil's white spot, a front fill, a back rim, and a white floor that
// lifts the undersides as the reference's floor does.
function studio(renderer, env) {
  const room = new THREE.Scene();
  // env.tint warms (or cools) the whole studio: room and every light
  const tint = env.tint || [1, 1, 1];
  const k = (x) => new THREE.Color(x * tint[0], x * tint[1], x * tint[2]);
  room.add(new THREE.Mesh(new THREE.BoxGeometry(20, 12, 20), new THREE.MeshBasicMaterial({ color: k(env.room), side: THREE.BackSide })));
  // each light is a panel with feathered edges (env.feather, a fraction of its size), so
  // its reflection fades out instead of ending in a hard-edged rectangle
  const feather = env.feather ?? 0;
  const panel = (round) => {
    if (!feather) return null;
    const N = 128, cv = document.createElement("canvas"); cv.width = cv.height = N;
    const g = cv.getContext("2d"), img = g.createImageData(N, N);
    const ss = (e0, e1, x) => { const t = clamp((x - e0) / (e1 - e0), 0, 1); return t * t * (3 - 2 * t); };
    for (let y = 0; y < N; y++)
      for (let x = 0; x < N; x++) {
        const u = (x + 0.5) / N, v = (y + 0.5) / N;
        const a = round ? ss(0.5, 0.5 * (1 - feather), Math.hypot(u - 0.5, v - 0.5)) : ss(0, feather, Math.min(u, 1 - u)) * ss(0, feather, Math.min(v, 1 - v));
        img.data.set([255 * a, 255 * a, 255 * a, 255], 4 * (y * N + x));
      }
    g.putImageData(img, 0, 0);
    const t = new THREE.CanvasTexture(cv); t.colorSpace = THREE.NoColorSpace;
    return t;
  };
  const box = (w, h, pos, level, round = false) => {
    if (!level) return;
    const g = round ? new THREE.CircleGeometry(w / 2, 32) : new THREE.PlaneGeometry(w, h);
    const m = new THREE.Mesh(g, new THREE.MeshBasicMaterial({ color: k(level), map: panel(round), side: THREE.DoubleSide }));
    m.position.set(...pos); m.lookAt(0, 0, 0); room.add(m);
  };
  box(env.keySize, env.keySize, env.keyPos, env.key, true);
  box(env.overSize?.[0] ?? 10, env.overSize?.[1] ?? 5, [0, 5.8, 0.8], env.over);
  box(6, 4, [0.5, 0.5, 6.5], env.front);
  box(3, 5, [5.5, 1.5, 4.5], env.fill);
  box(1.2, 6, [6.5, 1.0, -3.0], env.rim);
  box(16, 16, [0, -5.9, 0], env.floor);
  const pmrem = new THREE.PMREMGenerator(renderer);
  const tex = pmrem.fromScene(room, env.blur ?? 0.02).texture;
  room.traverse((o) => { if (o.isMesh) { o.geometry.dispose(); o.material.dispose(); } });
  pmrem.dispose();
  return tex;
}

// Ambient occlusion from a per-vertex attribute, applied where three's aoMap would be:
// indirect diffuse, clear coat and specular.
function withVertexAO(material) {
  material.onBeforeCompile = (shader) => {
    shader.vertexShader = shader.vertexShader
      .replace("#include <common>", "#include <common>\nattribute float ao;\nvarying float vAo;")
      .replace("#include <begin_vertex>", "#include <begin_vertex>\nvAo = ao;");
    shader.fragmentShader = shader.fragmentShader
      .replace("#include <common>", "#include <common>\nvarying float vAo;")
      .replace("#include <aomap_fragment>", `
        float ambientOcclusion = vAo;
        reflectedLight.indirectDiffuse *= ambientOcclusion;
        #if defined( USE_CLEARCOAT )
          clearcoatSpecularIndirect *= ambientOcclusion;
        #endif
        #if defined( USE_ENVMAP ) && defined( STANDARD )
          float dotNV = saturate( dot( geometryNormal, geometryViewDir ) );
          reflectedLight.indirectSpecular *= computeSpecularOcclusion( dotNV, ambientOcclusion, material.roughness );
        #endif`);
  };
  return material;
}

// The mesh of one strand: tip, rings, tip; normals from the faces.
function strandGeometry(surface) {
  const { rings, tips, radial } = surface;
  const nv = 2 + rings.length * radial;
  const pos = new Float32Array(nv * 3);
  pos.set(tips[0], 0);
  rings.forEach((ring, i) => ring.forEach((p, j) => pos.set(p, 3 * (1 + i * radial + j))));
  pos.set(tips[1], 3 * (nv - 1));
  const idx = [];
  const at = (i, j) => 1 + i * radial + ((j + radial) % radial);
  for (let j = 0; j < radial; j++) idx.push(0, at(0, j + 1), at(0, j));
  for (let i = 0; i < rings.length - 1; i++)
    for (let j = 0; j < radial; j++) {
      idx.push(at(i, j), at(i, j + 1), at(i + 1, j));
      idx.push(at(i, j + 1), at(i + 1, j + 1), at(i + 1, j));
    }
  const last = rings.length - 1;
  for (let j = 0; j < radial; j++) idx.push(nv - 1, at(last, j), at(last, j + 1));
  const g = new THREE.BufferGeometry();
  g.setAttribute("position", new THREE.BufferAttribute(pos, 3));
  g.setIndex(idx);
  g.computeVertexNormals();
  // the face winding gives outward normals only if the rings run the right way round;
  // check against each ring's centre and flip if not
  const n = g.attributes.normal.array;
  let out = 0;
  surface.centres.forEach((c, i) => {
    const v = 1 + i * radial;
    out += Math.sign(dot([n[3 * v], n[3 * v + 1], n[3 * v + 2]], sub([pos[3 * v], pos[3 * v + 1], pos[3 * v + 2]], c)));
  });
  if (out < 0) {
    for (let k = 0; k < idx.length; k += 3) [idx[k + 1], idx[k + 2]] = [idx[k + 2], idx[k + 1]];
    g.setIndex(idx); g.computeVertexNormals();
  }
  return g;
}

// screen position (reference pixels) of a world point, for the given elevation
export const toImage = (p, elev) => [p[0], -(p[1] * Math.cos(elev) - p[2] * Math.sin(elev))];

// A painted shadow: soft blobs under every ball, darker and tighter near the ground.
function shadowTexture(ballList, ground, rect, look) {
  const W = 1024, H = Math.round((W * rect.depth) / rect.width);
  const cv = document.createElement("canvas"); cv.width = W; cv.height = H;
  const g = cv.getContext("2d");
  // the alpha map reads the green channel: white blobs, added up, on black
  g.fillStyle = "#000"; g.fillRect(0, 0, W, H);
  g.globalCompositeOperation = "source-over";
  const toPx = (x, z) => [((x - rect.x0) / rect.width) * W, ((rect.z1 - z) / rect.depth) * H];
  const blob = (x, z, r, a) => {
    const [px, py] = toPx(x, z), pr = (r / rect.width) * W;
    const grd = g.createRadialGradient(px, py, 0, px, py, pr);
    grd.addColorStop(0, `rgba(255,255,255,${a})`); grd.addColorStop(1, "rgba(255,255,255,0)");
    g.fillStyle = grd; g.beginPath(); g.arc(px, py, pr, 0, 2 * Math.PI); g.fill();
  };
  for (const [x, y, z, r] of ballList) {
    const h = Math.max(0, y - r - ground);
    blob(x, z, 2.2 * r + 0.9 * h, look.shadow.broad * Math.exp(-h / 260));     // broad, faint
    blob(x, z, 1.05 * r + 0.25 * h, look.shadow.contact * Math.exp(-h / 22)); // contact
  }
  const tex = new THREE.CanvasTexture(cv);
  tex.colorSpace = THREE.NoColorSpace;
  return tex;
}

// A baked head mesh (tools/bake_heads.mjs), decoded; null if it was made from other params.
function unbake(baked, params, lines) {
  if (!baked) return null;
  if (baked.params_hash !== headKey(params, lines)) {
    console.warn("baked heads were made from different params; meshing the heads instead");
    return null;
  }
  const dec = (s, T) => new T(Uint8Array.from(atob(s), (ch) => ch.charCodeAt(0)).buffer);
  return Object.fromEntries(Object.entries(baked.heads).map(([k, h]) => [k, {
    positions: dec(h.positions, Float32Array), normals: dec(h.normals, Float32Array), indices: dec(h.indices, Uint32Array), balls: h.balls }]));
}

// `body` (optional): { yellow, blue } strands in the shape centrelines() returns them (pts, r,
// head, s, and mate/mateS/mateW for the press), used instead of the centreline model, so
// another body representation can be rendered through this scene unchanged
// `extra` (optional): { cut: { yellow: [s0, s1], blue: [s0, s1] }, meshes: { yellow: [...], blue: [...] } }:
// the strand's tube is left out between its own stations s0..s1 (two tube segments remain) and the
// given meshes ({ positions, normals, indices }) are added with that strand's material and occlusion
// (tools/beads.py: a lobe-primitive body for one region)
export function createScene(canvas, params, look = LOOK, { still = false, bakedHeads = null, body = null, extra = null } = {}) {
  const renderer = new THREE.WebGLRenderer({ canvas, antialias: true, preserveDrawingBuffer: still, alpha: false });
  renderer.toneMapping = { none: THREE.NoToneMapping, neutral: THREE.NeutralToneMapping, agx: THREE.AgXToneMapping, aces: THREE.ACESFilmicToneMapping }[look.toneMapping];
  renderer.toneMappingExposure = look.exposure;
  renderer.setClearColor(look.background);
  const scene = new THREE.Scene();
  scene.environment = studio(renderer, look.env);
  scene.environmentIntensity = look.envLevel;

  const elev = (params.cam.elev * Math.PI) / 180;
  const camera = new THREE.OrthographicCamera(-FRAME.width / 2, FRAME.width / 2, FRAME.height / 2, -FRAME.height / 2, 1, 20000);
  const target = new THREE.Vector3(FRAME.width / 2, -FRAME.height / 2 / Math.cos(elev), 0);
  camera.position.copy(target).add(new THREE.Vector3(0, Math.sin(elev), Math.cos(elev)).multiplyScalar(6000));
  camera.up.set(0, 1, 0);
  camera.lookAt(target);

  const lines = body ? { ...centrelines(params), ...body } : centrelines(params);
  const baked = unbake(bakedHeads, params, lines);
  // with head cones, each head and its neck are a separate smooth surface (head.js), and
  // the tube takes over from the neck at `join`, starting with a round cap inside it
  const heads = {};
  const strands = { yellow: lines.yellow, blue: lines.blue };

  if (params.head_profiles) {
    // heads v2: swept-profile heads, constructed necks joining the strand behind the wrap
    ["yellow", "blue"].forEach((name, i) => {
      const nk = params.necks[i];
      heads[name] = (baked && !look.headParts && baked[name]) ||
        headSurface2(lines[name], params.head_profiles[i], nk, elev, { k: params.neck_blend ?? 12, parts: look.headParts || "both" });
      const st = lines[name], i0 = st.s.findIndex((x) => x >= nk.join_s - 2);
      strands[name] = Object.fromEntries(Object.entries(st).map(([k, v]) => [k, Array.isArray(v) ? v.slice(i0) : v]));
    });
  } else if (params.head_cones) {
    ["yellow", "blue"].forEach((name, i) => {
      const cone = params.head_cones[i], join = cone.cut + (params.neck_join || 150);
      heads[name] = headSurface(lines[name], cone, elev, { join, k: look.headBlend });
      const st = lines[name], i0 = st.s.findIndex((x) => x >= join - 2);
      strands[name] = Object.fromEntries(Object.entries(st).map(([k, v]) => [k, Array.isArray(v) ? v.slice(i0) : v]));
    });
  }
  const capHead = params.head_cones || params.head_profiles ? { ...look.head, snoutLen: 1, snoutQ: 2 } : look.head;
  const tube = { head: capHead, ...(params.tube || {}), view: [0, Math.sin(elev), Math.cos(elev)] };
  if (tube.press && params.head_profiles) {
    // press only where the partner is a tube: not past its tail, and not above its join,
    // where its neck is part of the head surface
    ["yellow", "blue"].forEach((name, i) => {
      const st = strands[name], mateJoin = params.necks[1 - i].join_s;
      st.press = st.mateW.map((w, j) => w * smoothstep(mateJoin, mateJoin + 30, st.mateS[j]));
    });
  }
  const surfaces = { yellow: strandSurface(strands.yellow, tube), blue: strandSurface(strands.blue, tube) };
  if (extra?.cut) {
    for (const name of ["yellow", "blue"]) {
      const c = extra.cut[name];
      if (!c) continue;
      const st = strands[name];
      const part = (keep) => Object.fromEntries(Object.entries(st).map(([k, v]) => [k, Array.isArray(v) ? v.filter((_, i) => keep(st.s[i])) : v]));
      surfaces[name] = strandSurface(part((x) => x < c[0]), tube);
      surfaces[name + "_2"] = strandSurface(part((x) => x > c[1]), tube);
    }
  }
  const spacing = params.a / 2;
  const ballList = balls(params.head_profiles ? [strands.yellow, strands.blue] : [lines.yellow, lines.blue], spacing);
  if (params.head_profiles) {
    // the other snake's tail near each neck still comes from the full strands
    ballList.push(...balls([lines.yellow, lines.blue], spacing).filter((b) => !ballList.some((c) => c[0] === b[0] && c[1] === b[1])).filter((b) => {
      const id = b[4], st = id === 0 ? lines.yellow : lines.blue, idx = st.pts.findIndex((q) => q[0] === b[0] && q[1] === b[1] && q[2] === b[2]);
      return idx >= 0 && st.s[idx] > params.necks[id].join_s;
    }));
  }
  for (const [name, h] of Object.entries(heads)) ballList.push(...h.balls.map((b) => [...b, name === "yellow" ? 0 : 1]));
  let ground = Infinity;
  for (const s of Object.values(surfaces)) for (const ring of s.rings) for (const p of ring) ground = Math.min(ground, p[1]);

  const group = new THREE.Group();
  const meshes = {}, headMeshes = {};
  const withAO = (geo, own) => {
    const ao = occlusion(geo.attributes.position.array, geo.attributes.normal.array, ballList, ground, { ...look.ao, spacing }, own);
    geo.setAttribute("ao", new THREE.BufferAttribute(ao, 1));
    return geo;
  };
  for (const [key, surf] of Object.entries(surfaces)) {
    const name = key.split("_")[0];
    const { specularColor, ...opts } = { ...look.material, ...(look.materials?.[name] || {}) };
    const mat = withVertexAO(new THREE.MeshPhysicalMaterial({ color: look[name], ...opts, ...(specularColor ? { specularColor: new THREE.Color(specularColor) } : {}) }));
    const own = name === "yellow" ? 0 : 1;
    meshes[key] = new THREE.Mesh(withAO(strandGeometry(surf), own), mat);
    group.add(meshes[key]);
    if (key !== name) continue;
    for (const m of extra?.meshes?.[name] || []) {
      const g = new THREE.BufferGeometry();
      g.setAttribute("position", new THREE.BufferAttribute(new Float32Array(m.positions), 3));
      g.setAttribute("normal", new THREE.BufferAttribute(new Float32Array(m.normals), 3));
      g.setIndex(new THREE.BufferAttribute(new Uint32Array(m.indices), 1));
      group.add(new THREE.Mesh(withAO(g, own), mat));
    }
    if (heads[name]) {
      const g = new THREE.BufferGeometry();
      g.setAttribute("position", new THREE.BufferAttribute(heads[name].positions, 3));
      g.setAttribute("normal", new THREE.BufferAttribute(heads[name].normals, 3));
      const ix = heads[name].indices;
      g.setIndex(ArrayBuffer.isView(ix) ? new THREE.BufferAttribute(ix, 1) : ix);
      headMeshes[name] = new THREE.Mesh(withAO(g, own), mat);
      group.add(headMeshes[name]);
    }
  }

  // eyes: on each head, at the surface point that lands nearest the reference's eye
  const em = look.eyeMaterial || { roughness: 0.12, clearcoat: 1, clearcoatRoughness: 0.02 };
  const eyeMat = new THREE.MeshPhysicalMaterial({ color: look.eye, ...em });
  // the catchlight is painted on, as in the reference: one clean white spot, not a
  // reflection of the whole studio
  const glint = look.catchlight && new THREE.MeshBasicMaterial({ color: 0xffffff, toneMapped: false });
  const eyes = [];
  [["yellow", look.eyes[0]], ["blue", look.eyes[1]]].forEach(([name, want]) => {
    const mesh = headMeshes[name] || meshes[name];
    const geo = mesh.geometry, P = geo.attributes.position.array, Nn = geo.attributes.normal.array;
    // without a separate head, the head end of the tube comes first
    const count = headMeshes[name] ? P.length / 3 : surfaces[name].rings.length * 0.25 * surfaces[name].radial;
    let best = null, bd = Infinity;
    for (let v = 1; v < count; v++) {
      const p = [P[3 * v], P[3 * v + 1], P[3 * v + 2]], n = [Nn[3 * v], Nn[3 * v + 1], Nn[3 * v + 2]];
      const facing = n[2] * Math.cos(elev) + n[1] * Math.sin(elev);
      if (facing < 0.3) continue;
      const [ix, iy] = toImage(p, elev);
      const d = Math.hypot(ix - want[0], iy - want[1]);
      if (d < bd) { bd = d; best = { p, n }; }
    }
    if (!best) return;
    const c = sub(best.p, mul(best.n, 0.35 * look.eyeR));
    const eye = new THREE.Mesh(new THREE.SphereGeometry(look.eyeR, 48, 32), eyeMat);
    eye.position.set(...c);
    group.add(eye); eyes.push(eye);
    if (look.eyeSocket && headMeshes[name]) {
      // the socket: the head's own occlusion darkened in a soft band just outside the eye,
      // as the reference's recess is shaded (not a separate ring)
      const { k = 0.4, w = 3.5, at = 0.95 } = look.eyeSocket;
      const ao = geo.attributes.ao, Rr = at * Math.sqrt(1 - 0.35 ** 2) * look.eyeR;
      for (let v = 0; v < ao.count; v++) {
        const d = norm(sub([P[3 * v], P[3 * v + 1], P[3 * v + 2]], add(c, mul(best.n, 0.35 * look.eyeR))));
        if (d < Rr + 4 * w) ao.array[v] *= 1 - k * Math.exp(-0.5 * (Math.max(d - Rr, 0) / w) ** 2);
      }
      ao.needsUpdate = true;
    }
    if (glint) {
      const { dir, size } = look.catchlight, dn = unit(dir);
      const spot = new THREE.Mesh(new THREE.CircleGeometry(size * look.eyeR, 32), glint);
      spot.position.set(...add(c, mul(dn, look.eyeR * 1.01)));
      spot.lookAt(...add(c, mul(dn, look.eyeR * 3)));
      group.add(spot);
    }
  });
  if (look.isolate === "heads") {
    // diagnostics: the heads and necks alone, as complete solids
    for (const mesh of Object.values(meshes)) mesh.visible = false;
  }
  if (look.debugNormals) {
    // surface normals as colours, for checking continuity
    const nm = new THREE.MeshNormalMaterial();
    group.traverse((o) => { if (o.isMesh) o.material = nm; });
  }
  scene.add(group);

  // ground: a white plane carrying the painted shadow
  let x0 = Infinity, x1 = -Infinity, z0 = Infinity, z1 = -Infinity;
  for (const [x, , z, r] of ballList) { x0 = Math.min(x0, x - 4 * r); x1 = Math.max(x1, x + 4 * r); z0 = Math.min(z0, z - 4 * r); z1 = Math.max(z1, z + 4 * r); }
  const rect = { x0: x0 - 200, width: x1 - x0 + 400, z1: z1 + 200, depth: z1 - z0 + 400 };
  const shadow = new THREE.Mesh(
    new THREE.PlaneGeometry(rect.width, rect.depth),
    new THREE.MeshBasicMaterial({ color: new THREE.Color(...look.shadow.colour), transparent: true, alphaMap: shadowTexture(ballList, ground, rect, look), depthWrite: false, toneMapped: false }),
  );
  shadow.rotation.x = -Math.PI / 2;
  shadow.position.set(rect.x0 + rect.width / 2, ground - 0.5, rect.z1 - rect.depth / 2);
  scene.add(shadow);
  if (look.shadowCard) {
    // The reference's floor shadow, painted on a card behind the base that faces the camera:
    // at this camera (a few degrees above the floor) a shadow lying on the floor would be
    // squashed to a line. A soft warm band under the base that fades beyond it, and a short
    // darker contact shadow under each foot, both placed from the model's own feet.
    shadow.visible = false;
    // three frames wide, so a wider window never shows its ends (the band fades out by then)
    const sc = look.shadowCard, x0 = -FRAME.width, y0 = sc.top ?? 640, Wc = 3 * FRAME.width, Hc = FRAME.height - y0;
    // the bottom of the model in each image column, from the balls
    const bottom = new Float32Array(Wc).fill(-Infinity);
    for (const [bx, by, bz, br] of ballList) {
      const [ix, iy] = toImage([bx, by, bz], elev);
      for (let x = Math.max(0, Math.floor(ix - br - x0)); x <= Math.min(Wc - 1, Math.ceil(ix + br - x0)); x++) {
        const h = br * br - (x + x0 - ix) ** 2;
        if (h > 0) bottom[x] = Math.max(bottom[x], iy + Math.sqrt(h));
      }
    }
    // look.shadowCard.fromMesh: the bottom from the strands' mesh itself (every ring vertex), so the
    // contact shadow hugs a lobe whose section or displacement handles moved its bottom off the
    // balls' round profile (the balls' bottom left a pale crescent under such a lobe: r10-L13)
    if (sc.fromMesh) {
      bottom.fill(-Infinity);
      for (const s of Object.values(surfaces)) for (const ring of s.rings) for (const p of ring) {
        const [ix, iy] = toImage(p, elev), xc = Math.round(ix - x0);
        for (let x = Math.max(0, xc - 1); x <= Math.min(Wc - 1, xc + 1); x++) bottom[x] = Math.max(bottom[x], iy);
      }
    }
    let foot = -Infinity;
    for (let x = 0; x < Wc; x++) if (bottom[x] > -Infinity) foot = Math.max(foot, bottom[x]);
    // the band is strongest around the feet: their nearness to the floor, blurred widely
    const near = Float32Array.from(bottom, (b) => (b > -Infinity ? Math.exp(-(foot - b) / sc.contactRange) : 0));
    const env = new Float32Array(Wc);
    for (let x = 0; x < Wc; x++) {
      let acc = 0;
      for (let k = 0; k < Wc; k += 2) if (near[k] > 1e-3) acc += near[k] * Math.exp(-0.5 * ((x - k) / sc.fade) ** 2);
      env[x] = acc;
    }
    const emax = Math.max(...env);
    for (let x = 0; x < Wc; x++) env[x] /= emax || 1;
    const cv = document.createElement("canvas"); cv.width = Wc; cv.height = Hc;
    const g = cv.getContext("2d"), img = g.createImageData(Wc, Hc);
    const [cr, cg, cb] = sc.colour;
    // across the floor (up the image) the shadow fades slowly; at its near edge, the line of
    // the feet, it ends quickly, as the reference's does
    const edge = foot + sc.bandOffset;
    for (let x = 0; x < Wc; x++) {
      for (let y = 0; y < Hc; y++) {
        const iy = y0 + y;
        let a = sc.band * env[x] * (iy < edge ? Math.exp(-(edge - iy) / sc.fadeUp) : Math.exp(-(((iy - edge) / sc.fadeDown) ** 2)));
        if (near[x] > 1e-3 && iy > bottom[x] - 2) a += sc.contact * near[x] * Math.exp(-(iy - bottom[x] + 2) / sc.contactFall);
        a = Math.min(a, 0.9);
        img.data.set([cr * 255, cg * 255, cb * 255, a * 255], 4 * (y * Wc + x));
      }
    }
    g.putImageData(img, 0, 0);
    const tex = new THREE.CanvasTexture(cv); tex.colorSpace = THREE.SRGBColorSpace;
    const card = new THREE.Mesh(new THREE.PlaneGeometry(Wc, Hc), new THREE.MeshBasicMaterial({ map: tex, transparent: true, depthWrite: false, toneMapped: false }));
    // image point (x, y) at distance D behind the model: (x, -y cos e, y sin e) - D (0, sin e, cos e)
    const cx = x0 + Wc / 2, cy = y0 + Hc / 2, D = 400;
    card.position.set(cx, -cy * Math.cos(elev) - D * Math.sin(elev), cy * Math.sin(elev) - D * Math.cos(elev));
    card.rotation.x = -elev;
    card.renderOrder = -1;
    scene.add(card);
  }

  function resize(w, h) {
    renderer.setSize(w, h, false);
    // keep the reference framing; letterbox to the canvas aspect
    const aspect = w / h, fa = FRAME.width / FRAME.height;
    const hw = aspect > fa ? (FRAME.height / 2) * aspect : FRAME.width / 2;
    const hh = aspect > fa ? FRAME.height / 2 : FRAME.width / 2 / aspect;
    Object.assign(camera, { left: -hw, right: hw, top: hh, bottom: -hh });
    camera.updateProjectionMatrix();
  }
  return { renderer, scene, camera, group, meshes, eyes, lines, surfaces, resize, render: () => renderer.render(scene, camera) };
}
