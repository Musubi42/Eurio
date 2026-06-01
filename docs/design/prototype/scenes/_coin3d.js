// scenes/_coin3d.js — shared Three.js coin engine
// =================================================
// Extracted from scan-coin-3d.js so several scenes can reuse the SAME bimetal
// coin renderer instead of duplicating ~400 lines (R0 — pas de dette).
//
// Consumers :
//   - scan-coin-3d.js        — render-quality lab (OrbitControls + tune sliders)
//   - scan-transition-3d.js  — diégetic scan→3D transition (custom flick physics)
//
// What lives here :
//   - createStage()          — renderer + studio lighting + camera + RAF loop
//                              with onFrame() hooks. NO controls (each scene owns
//                              its own interaction model).
//   - buildCoinFromUrls()    — loads avers (Supabase Storage) + revers (packaged
//                              carte) textures and builds the full bimetal mesh.
//   - buildProceduralEdgeTexture(), disposeCoin() — helpers shared across scenes.
//
// Geometry / lighting constants are the visually-validated values from the
// original lab (see docs/coin-3d-viewer/decisions.md).

import * as THREE from 'https://esm.sh/three@0.160.0';
import { RoomEnvironment } from 'https://esm.sh/three@0.160.0/examples/jsm/environments/RoomEnvironment.js';

// ───────── 2€ coin dimensions (mm) ─────────
// Thickness slightly inflated vs the 2.20mm spec for visual presence at our
// camera distance — the real ratio reads "too thin" against flat Numista scans.
export const R_OUT = 12.875;        // outer radius (Ø 25.75)
const R_RING_INNER = 9.375;         // inner edge of silver ring (Ø 18.75)
const THICKNESS = 2.80;
const RING_LIP = 0.06;              // hairline groove between disc and ring
const RIM_WIDTH = 0.90;             // raised outer rim border, radial width
const RIM_HEIGHT = 0.06;            // rim protrusion above the ring face

// ───────── Material defaults (visually-validated preset) ─────────
export const DEFAULT_NORMAL_STRENGTH = 0.30;
export const DEFAULT_METALNESS = 0.50;
export const DEFAULT_ROUGHNESS = 0.50;
export const DEFAULT_EXPOSURE = 0.80;
// Reverse face is naturally less dramatic (etched map vs deep-relief obverse) AND
// receives only the back-key light — boost its normal map so engraved lines stay
// as "alive" as the obverse sculpt.
export const REVERSE_RELIEF_BOOST = 1.33;

// ───────── Stage : renderer + lighting + camera + RAF loop ─────────
// Returns a handle each scene drives with its own interaction model. The loop
// calls every registered onFrame(cb) then renders — a scene adds controls.update
// or its own physics step there.

export function createStage(canvasWrap, opts = {}) {
  const exposure = opts.exposure ?? DEFAULT_EXPOSURE;

  const renderer = new THREE.WebGLRenderer({ antialias: true, alpha: true });
  renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
  renderer.outputColorSpace = THREE.SRGBColorSpace;
  renderer.toneMapping = THREE.ACESFilmicToneMapping;
  renderer.toneMappingExposure = exposure;
  canvasWrap.appendChild(renderer.domElement);

  const scene = new THREE.Scene();

  // IBL via Filament-style room env, baked through PMREM for PBR specular.
  const pmrem = new THREE.PMREMGenerator(renderer);
  scene.environment = pmrem.fromScene(new RoomEnvironment(renderer), 0.04).texture;

  // Two-key studio lighting : front key on +Z lights the obverse, back key
  // (lower) on -Z keeps the reverse alive when the camera orbits behind.
  const dirFront = new THREE.DirectionalLight(0xffffff, 1.4);
  dirFront.position.set(2.5, 3.5, 4.0);
  scene.add(dirFront);
  const dirBack = new THREE.DirectionalLight(0xffffff, 1.0);
  dirBack.position.set(-2.5, -3.5, -4.0);
  scene.add(dirBack);
  scene.add(new THREE.HemisphereLight(0xffffff, 0x202028, 0.25));

  const camera = new THREE.PerspectiveCamera(35, 1, 0.1, 200);
  camera.position.set(0, 6, 38);
  camera.lookAt(0, 0, 0);

  const frameCbs = new Set();

  function resize() {
    const w = canvasWrap.clientWidth || 1;
    const h = canvasWrap.clientHeight || 1;
    renderer.setSize(w, h, false);
    camera.aspect = w / h;
    camera.updateProjectionMatrix();
  }
  resize();
  const ro = new ResizeObserver(resize);
  ro.observe(canvasWrap);

  let raf = 0;
  let running = false;
  let last = 0;
  function tick(now) {
    const dt = last ? Math.min((now - last) / 1000, 1 / 20) : 1 / 60;
    last = now;
    frameCbs.forEach((cb) => cb(dt, now));
    renderer.render(scene, camera);
    raf = requestAnimationFrame(tick);
  }

  return {
    renderer, scene, camera, pmrem,
    onFrame(cb) { frameCbs.add(cb); return () => frameCbs.delete(cb); },
    start() { if (!running) { running = true; last = 0; raf = requestAnimationFrame(tick); } },
    stop() { running = false; cancelAnimationFrame(raf); },
    resize,
    setExposure(v) { renderer.toneMappingExposure = v; },
    dispose() {
      running = false;
      cancelAnimationFrame(raf);
      ro.disconnect();
      pmrem.dispose();
      renderer.dispose();
      if (renderer.domElement.parentNode) {
        renderer.domElement.parentNode.removeChild(renderer.domElement);
      }
    },
  };
}

// ───────── Coin construction from a manifest entry ─────────
// Loads obverse/reverse textures, derives normal maps + mirrored reverse, and
// builds the bimetal mesh. Returns { group, matSilver, matGold, ... } so the
// caller can add group to the scene and tune materials.

// Build a coin from texture URLs (avers = Supabase Storage, revers = packaged
// carte asset). The canonical avers crops are tight + centred (cx/cy≈0.5,
// r≈0.5, σ≈0.001 measured over the catalogue), so UV mapping is FIXED — no
// per-image measurement needed. This replaces the legacy coins.json manifest
// (numista_id keyed, measured UV) now that images live in the app data layer.
const FIXED_UV = { cx_uv: 0.5, cy_uv: 0.5, radius_uv: 0.5 };

export async function buildCoinFromUrls({ obverse, reverse }, { edgeTex } = {}) {
  const [obverseTex, reverseTex] = await Promise.all([
    loadTexture(obverse),
    loadTexture(reverse),
  ]);

  await nextFrame();
  const reverseImgMirrored = mirrorImageHorizontal(reverseTex.image);
  const reverseTexMirrored = canvasToTexture(reverseImgMirrored, THREE.SRGBColorSpace);
  const obverseNormal = buildNormalMapFromImage(obverseTex.image, 1);
  const reverseNormal = buildNormalMapFromImage(reverseImgMirrored, 1);

  // Reverse mirrored horizontally → cx flips; with cx=0.5 it is unchanged.
  const reverseMeta = { cx_uv: 1 - FIXED_UV.cx_uv, cy_uv: FIXED_UV.cy_uv, radius_uv: FIXED_UV.radius_uv };

  return buildCoin({
    obverseTex, obverseNormal, obverseMeta: FIXED_UV,
    reverseTex: reverseTexMirrored, reverseNormal, reverseMeta,
    edgeTex,
  });
}

export function disposeCoin(coin) {
  // Some textures are shared between materials — Texture.dispose() is idempotent.
  const textures = [
    coin.matSilver?.map, coin.matSilver?.normalMap,
    coin.matGold?.map, coin.matGold?.normalMap,
    coin.matSilverBack?.map, coin.matSilverBack?.normalMap,
    coin.matGoldBack?.map, coin.matGoldBack?.normalMap,
  ];
  for (const t of textures) t?.dispose?.();

  const materials = [
    coin.matSilver, coin.matGold, coin.matSilverBack, coin.matGoldBack,
    coin.matRim, coin.matEdge, coin.matGroove,
  ];
  for (const m of materials) m?.dispose?.();

  coin.group.traverse((obj) => obj.geometry?.dispose?.());
}

function buildCoin({
  obverseTex, obverseNormal, obverseMeta,
  reverseTex, reverseNormal, reverseMeta,
  edgeTex,
}) {
  const group = new THREE.Group();

  // Z layout (top half, mirror for bottom). Rim is the highest point; ring face
  // recessed by RIM_HEIGHT; disc recessed further by RING_LIP (press-fit groove).
  const Z_RIM = THICKNESS / 2;
  const Z_RING = Z_RIM - RIM_HEIGHT;
  const Z_DISC = Z_RING - RING_LIP;

  const matSilver = new THREE.MeshStandardMaterial({
    color: 0xeaeaef,
    metalness: DEFAULT_METALNESS,
    roughness: DEFAULT_ROUGHNESS,
    map: obverseTex,
    normalMap: obverseNormal,
    normalScale: new THREE.Vector2(DEFAULT_NORMAL_STRENGTH, DEFAULT_NORMAL_STRENGTH),
  });
  const matGold = new THREE.MeshStandardMaterial({
    color: 0xf3d68a,
    metalness: DEFAULT_METALNESS,
    roughness: DEFAULT_ROUGHNESS,
    map: obverseTex,
    normalMap: obverseNormal,
    normalScale: new THREE.Vector2(DEFAULT_NORMAL_STRENGTH, DEFAULT_NORMAL_STRENGTH),
  });
  const matSilverBack = matSilver.clone();
  matSilverBack.map = reverseTex;
  matSilverBack.normalMap = reverseNormal;
  matSilverBack.normalScale = new THREE.Vector2(
    DEFAULT_NORMAL_STRENGTH * REVERSE_RELIEF_BOOST,
    DEFAULT_NORMAL_STRENGTH * REVERSE_RELIEF_BOOST,
  );
  const matGoldBack = matGold.clone();
  matGoldBack.map = reverseTex;
  matGoldBack.normalMap = reverseNormal;
  matGoldBack.normalScale = new THREE.Vector2(
    DEFAULT_NORMAL_STRENGTH * REVERSE_RELIEF_BOOST,
    DEFAULT_NORMAL_STRENGTH * REVERSE_RELIEF_BOOST,
  );

  // Rim step walls : plain silver (a 0.06mm cylinder can't be XY-UV-mapped and
  // is barely visible except at grazing angles).
  const matRim = new THREE.MeshStandardMaterial({
    color: 0xeaeaef,
    metalness: DEFAULT_METALNESS,
    roughness: DEFAULT_ROUGHNESS,
    side: THREE.DoubleSide,
  });
  // Disc-ring groove : near-black, non-metallic → reads as a hairline shadow.
  const matGroove = new THREE.MeshStandardMaterial({
    color: 0x07070a,
    metalness: 0.0,
    roughness: 1.0,
    side: THREE.DoubleSide,
  });
  // Cylinder side (tranche).
  const matEdge = new THREE.MeshStandardMaterial({
    color: 0xeaeaef,
    metalness: DEFAULT_METALNESS,
    roughness: DEFAULT_ROUGHNESS,
    map: edgeTex,
  });

  // Top face (obverse).
  const ringTop = makeAnnulus(R_RING_INNER, R_OUT - RIM_WIDTH, +1, obverseMeta);
  ringTop.position.z = Z_RING;
  ringTop.material = matSilver;
  const rimTop = makeAnnulus(R_OUT - RIM_WIDTH, R_OUT, +1, obverseMeta);
  rimTop.position.z = Z_RIM;
  rimTop.material = matSilver;
  const discTop = makeDisc(R_RING_INNER, +1, obverseMeta);
  discTop.position.z = Z_DISC;
  discTop.material = matGold;
  const grooveTop = new THREE.Mesh(cylinderRing(R_RING_INNER, RING_LIP), matGroove);
  grooveTop.position.z = Z_RING - RING_LIP / 2;
  const rimStepTop = new THREE.Mesh(cylinderRing(R_OUT - RIM_WIDTH, RIM_HEIGHT), matRim);
  rimStepTop.position.z = Z_RING + RIM_HEIGHT / 2;
  group.add(ringTop, rimTop, discTop, grooveTop, rimStepTop);

  // Bottom face (reverse).
  const ringBot = makeAnnulus(R_RING_INNER, R_OUT - RIM_WIDTH, -1, reverseMeta);
  ringBot.position.z = -Z_RING;
  ringBot.material = matSilverBack;
  const rimBot = makeAnnulus(R_OUT - RIM_WIDTH, R_OUT, -1, reverseMeta);
  rimBot.position.z = -Z_RIM;
  rimBot.material = matSilverBack;
  const discBot = makeDisc(R_RING_INNER, -1, reverseMeta);
  discBot.position.z = -Z_DISC;
  discBot.material = matGoldBack;
  const grooveBot = new THREE.Mesh(cylinderRing(R_RING_INNER, RING_LIP), matGroove);
  grooveBot.position.z = -Z_RING + RING_LIP / 2;
  const rimStepBot = new THREE.Mesh(cylinderRing(R_OUT - RIM_WIDTH, RIM_HEIGHT), matRim);
  rimStepBot.position.z = -Z_RING - RIM_HEIGHT / 2;
  group.add(ringBot, rimBot, discBot, grooveBot, rimStepBot);

  // Outer cylinder (tranche).
  const cylGeo = new THREE.CylinderGeometry(R_OUT, R_OUT, THICKNESS, 128, 1, true);
  cylGeo.rotateX(Math.PI / 2);
  const cyl = new THREE.Mesh(cylGeo, matEdge);
  group.add(cyl);

  return {
    group,
    matSilver, matGold, matSilverBack, matGoldBack,
    matRim, matEdge, matGroove,
  };
}

function cylinderRing(radius, height) {
  const g = new THREE.CylinderGeometry(radius, radius, height, 96, 1, true);
  g.rotateX(Math.PI / 2);
  return g;
}

// Annulus (silver outer ring face). UVs map each vertex to its real (x,y) photo
// position so the picture is continuous across ring + disc + rim regardless of
// geometry boundaries. `meta` = { cx_uv, cy_uv, radius_uv } from coins.json.
function makeAnnulus(rInner, rOuter, normalSign, meta) {
  const geo = new THREE.RingGeometry(rInner, rOuter, 192, 1);
  // rotateX(π) flips the normal to -Z without inverting winding.
  if (normalSign < 0) geo.rotateX(Math.PI);
  remapUVsFromXY(geo, meta);
  return new THREE.Mesh(geo);
}

function makeDisc(radius, normalSign, meta) {
  const geo = new THREE.CircleGeometry(radius, 128);
  if (normalSign < 0) geo.rotateX(Math.PI);
  remapUVsFromXY(geo, meta);
  return new THREE.Mesh(geo);
}

function remapUVsFromXY(geo, meta) {
  const cx = meta.cx_uv;
  const cy = meta.cy_uv;
  const r = meta.radius_uv;
  const pos = geo.attributes.position;
  const uv = geo.attributes.uv;
  for (let i = 0; i < pos.count; i++) {
    const x = pos.getX(i);
    const y = pos.getY(i);
    uv.setXY(i, cx + (x / R_OUT) * r, cy + (y / R_OUT) * r);
  }
  uv.needsUpdate = true;
}

// ───────── Texture helpers ─────────

function loadTexture(url) {
  return new Promise((resolve, reject) => {
    new THREE.TextureLoader().load(
      url,
      (tex) => {
        tex.colorSpace = THREE.SRGBColorSpace;
        tex.anisotropy = 8;
        tex.needsUpdate = true;
        resolve(tex);
      },
      undefined,
      (err) => reject(err),
    );
  });
}

// Sobel-derived normal map. Accepts an HTMLImageElement OR a canvas. Encodes a
// tangent-space RGB normal from the luminance gradient.
function buildNormalMapFromImage(src, strength) {
  const w = src.width;
  const h = src.height;
  const cv = document.createElement('canvas');
  cv.width = w; cv.height = h;
  const ctx = cv.getContext('2d');
  ctx.drawImage(src, 0, 0);
  const srcPx = ctx.getImageData(0, 0, w, h).data;

  const lum = new Float32Array(w * h);
  for (let i = 0, p = 0; i < srcPx.length; i += 4, p++) {
    lum[p] = (0.299 * srcPx[i] + 0.587 * srcPx[i + 1] + 0.114 * srcPx[i + 2]) / 255;
  }

  const dst = ctx.createImageData(w, h);
  const out = dst.data;
  for (let y = 0; y < h; y++) {
    for (let x = 0; x < w; x++) {
      const x0 = Math.max(0, x - 1), x1 = Math.min(w - 1, x + 1);
      const y0 = Math.max(0, y - 1), y1 = Math.min(h - 1, y + 1);
      const tl = lum[y0 * w + x0], tc = lum[y0 * w + x], tr = lum[y0 * w + x1];
      const ml = lum[y * w + x0], mr = lum[y * w + x1];
      const bl = lum[y1 * w + x0], bc = lum[y1 * w + x], br = lum[y1 * w + x1];
      const gx = (tr + 2 * mr + br) - (tl + 2 * ml + bl);
      const gy = (bl + 2 * bc + br) - (tl + 2 * tc + tr);
      let nx = -gx * strength;
      let ny = -gy * strength;
      let nz = 1;
      const len = Math.hypot(nx, ny, nz) || 1;
      nx /= len; ny /= len; nz /= len;
      const o = (y * w + x) * 4;
      out[o] = (nx * 0.5 + 0.5) * 255;
      out[o + 1] = (ny * 0.5 + 0.5) * 255;
      out[o + 2] = (nz * 0.5 + 0.5) * 255;
      out[o + 3] = 255;
    }
  }
  ctx.putImageData(dst, 0, 0);

  const tex = new THREE.CanvasTexture(cv);
  tex.colorSpace = THREE.NoColorSpace;
  tex.anisotropy = 8;
  tex.needsUpdate = true;
  return tex;
}

// Procedural edge texture (4096×256) : reeded background + 6× "2 ★ ★ ★" lettering
// alternating upright/inverted, incised look. Built once and reused across coins.
export function buildProceduralEdgeTexture() {
  const W = 4096;
  const H = 256;
  const cv = document.createElement('canvas');
  cv.width = W; cv.height = H;
  const ctx = cv.getContext('2d');

  const grad = ctx.createLinearGradient(0, 0, 0, H);
  grad.addColorStop(0.00, '#7a7a82');
  grad.addColorStop(0.50, '#c0c0c8');
  grad.addColorStop(1.00, '#7a7a82');
  ctx.fillStyle = grad;
  ctx.fillRect(0, 0, W, H);

  const stripes = 280;
  const stripeW = W / stripes;
  for (let i = 0; i < stripes; i++) {
    const x = i * stripeW + Math.sin(i * 12.43) * 0.6;
    const dark = 0.30 + 0.10 * Math.sin(i * 1.7);
    ctx.fillStyle = `rgba(35,35,42,${dark.toFixed(3)})`;
    ctx.fillRect(x, 0, stripeW * 0.55, H);
    ctx.fillStyle = 'rgba(225,225,232,0.10)';
    ctx.fillRect(x + stripeW * 0.6, 0, 1, H);
  }

  const reps = 6;
  ctx.font = 'bold 110px "Times New Roman", "Georgia", serif';
  ctx.textAlign = 'center';
  ctx.textBaseline = 'middle';
  for (let i = 0; i < reps; i++) {
    const cx = (i + 0.5) * W / reps;
    const inverted = i % 2 === 1;
    ctx.save();
    ctx.translate(cx, H / 2);
    if (inverted) ctx.rotate(Math.PI);
    ctx.fillStyle = 'rgba(20,20,25,0.85)';
    ctx.fillText('2 ★ ★ ★', 0, 4);
    ctx.fillStyle = 'rgba(245,245,250,0.28)';
    ctx.fillText('2 ★ ★ ★', 0, -2);
    ctx.restore();
  }

  const shade = ctx.createLinearGradient(0, 0, 0, H);
  shade.addColorStop(0.00, 'rgba(0,0,0,0.22)');
  shade.addColorStop(0.50, 'rgba(0,0,0,0)');
  shade.addColorStop(1.00, 'rgba(0,0,0,0.22)');
  ctx.fillStyle = shade;
  ctx.fillRect(0, 0, W, H);

  const tex = new THREE.CanvasTexture(cv);
  tex.wrapS = THREE.RepeatWrapping;
  tex.wrapT = THREE.ClampToEdgeWrapping;
  tex.colorSpace = THREE.SRGBColorSpace;
  tex.anisotropy = 16;
  tex.needsUpdate = true;
  return tex;
}

function mirrorImageHorizontal(img) {
  const cv = document.createElement('canvas');
  cv.width = img.width;
  cv.height = img.height;
  const ctx = cv.getContext('2d');
  ctx.translate(img.width, 0);
  ctx.scale(-1, 1);
  ctx.drawImage(img, 0, 0);
  return cv;
}

function canvasToTexture(canvas, colorSpace) {
  const tex = new THREE.CanvasTexture(canvas);
  tex.colorSpace = colorSpace || THREE.NoColorSpace;
  tex.anisotropy = 8;
  tex.needsUpdate = true;
  return tex;
}

function nextFrame() { return new Promise((r) => requestAnimationFrame(() => r())); }
