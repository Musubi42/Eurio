// Scene : scan-coin-3d
// Three.js bimetal coin proto — render quality validation, no animation.
//
// Geometry  : bimetal mesh (silver outer ring + gold inner disc + cylindrical rim).
//             Top + bottom faces share the obverse/reverse photos via UVs that
//             reproduce the physical (x,y) → photo coordinate mapping. The ring
//             and disc therefore form a continuous picture across both materials.
// Textures  : obverse.png / reverse.png as albedo. Normal maps generated at load
//             time via Sobel on luminance (canvas 2D), gives relief under lighting.
//             Edge texture procedural (canvas, "2 ★ ★ ★ " pattern).
// Lighting  : RoomEnvironment via PMREMGenerator + 1 directional fill.
// Controls  : OrbitControls (drag/zoom). Chips = toggle normal, auto-rotate, reset.

import * as THREE from 'https://esm.sh/three@0.160.0';
import { OrbitControls } from 'https://esm.sh/three@0.160.0/examples/jsm/controls/OrbitControls.js';
import { RoomEnvironment } from 'https://esm.sh/three@0.160.0/examples/jsm/environments/RoomEnvironment.js';

// 2€ coin dimensions (mm). Thickness slightly inflated vs the 2.20mm spec for
// visual presence in the proto — at the camera distance we use, the real ratio
// reads "too thin" against Numista's flat scans.
const R_OUT = 12.875;          // outer radius (Ø 25.75)
const R_RING_INNER = 9.375;    // inner edge of silver ring (Ø 18.75)
const THICKNESS = 2.80;
// Hairline groove between disc and ring (disc press-fit into ring).
const RING_LIP = 0.06;
// Raised outer rim border on each face — the milled bezel of a struck coin.
// Width = how far the rim extends radially inward from R_OUT.
// Height = how much the rim protrudes above the ring face.
const RIM_WIDTH = 0.90;
const RIM_HEIGHT = 0.06;

// Photo geometry is now per-coin. ml/measure_photo_meta.py probes each Numista
// scan and writes (cx_uv, cy_uv, radius_uv) into coins.json — see the
// metadata-only approach in docs/coin-3d-viewer/decisions.md (D8).

// Defaults baked in from the visually-validated preset (relief 0.30, met 0.50,
// rough 0.50, exposure 0.80). The Numista scan already carries relief info, so
// the normal map is a very subtle lighting enhancer, not a relief replacement.
const DEFAULT_NORMAL_STRENGTH = 0.30;
const DEFAULT_METALNESS = 0.50;
const DEFAULT_ROUGHNESS = 0.50;
const DEFAULT_EXPOSURE = 0.80;
// Reverse face is naturally less dramatic (etched map vs deep-relief obverse)
// AND would receive only the back-key light — boost its normal map a bit so the
// engraved lines catch enough light to feel as "alive" as the obverse sculpt.
const REVERSE_RELIEF_BOOST = 1.33;

let activeContext = null;
let coinsManifest = null;     // cached fetch of coins.json

export async function mount({ state, query, navigate }) {
  if (activeContext) { activeContext.dispose(); activeContext = null; }

  const root = document.querySelector('[data-scene="scan-coin-3d"]');
  if (!root) return;
  const canvasWrap = root.querySelector('[data-slot="canvas-wrap"]');
  const statusEl = root.querySelector('[data-slot="status"]');
  const labelEl = root.querySelector('[data-slot="label"]');

  const ctx = createSceneContext(canvasWrap);
  ctx.root = root;
  ctx.statusEl = statusEl;
  ctx.labelEl = labelEl;
  // Edge texture is built once and reused across coin swaps — it doesn't depend
  // on the photo and rebuilding it would just churn GPU memory for no win.
  ctx.edgeTex = buildProceduralEdgeTexture();
  activeContext = ctx;

  root.querySelectorAll('[data-action]').forEach((el) => {
    el.addEventListener('click', () => onChipClick(el, ctx));
  });

  const tuneChip = root.querySelector('.coin3d-tune-toggle');
  const syncTuneVisibility = () => {
    if (tuneChip) tuneChip.classList.toggle('is-hidden', !state.state.debugMode);
  };
  syncTuneVisibility();
  window.addEventListener('debug:toggle', syncTuneVisibility);
  ctx.debugListener = syncTuneVisibility;

  try {
    setStatus(statusEl, 'Chargement du catalogue…');
    if (!coinsManifest) {
      const r = await fetch('data/coin-3d/coins.json');
      if (!r.ok) throw new Error(`coins.json: HTTP ${r.status}`);
      coinsManifest = await r.json();
    }
    const list = coinsManifest.coins;
    if (!list?.length) throw new Error('coins.json: empty list');

    // Resolve which coin to start with from ?id=, default to the first one.
    const requestedId = (query?.id || '').toString();
    let idx = list.findIndex((c) => c.numista_id === requestedId);
    if (idx < 0) idx = 0;
    ctx.coinIndex = idx;
    ctx.coinList = list;

    wireSliders(root, ctx);
    await loadAndBuildCoin(ctx, list[idx]);
  } catch (err) {
    console.error('[scan-coin-3d] init failed', err);
    setStatus(statusEl, `Erreur : ${err.message || err}`);
  }
}

// ───────── Coin swapping ─────────

async function loadAndBuildCoin(ctx, entry) {
  setStatus(ctx.statusEl, `Chargement ${entry.country} ${entry.year}…`);
  if (ctx.labelEl) {
    ctx.labelEl.textContent = `${entry.country} · ${entry.year} · ${entry.name}`;
  }

  // Drop the old coin's resources before we allocate the new ones — keeps
  // GPU memory bounded as the user navigates the carousel.
  if (ctx.coin) {
    ctx.scene.remove(ctx.coin.group);
    disposeCoin(ctx.coin);
    ctx.coin = null;
  }

  const [obverseTex, reverseTex] = await Promise.all([
    loadTexture(entry.obverse.path),
    loadTexture(entry.reverse.path),
  ]);

  await nextFrame();
  const reverseImgMirrored = mirrorImageHorizontal(reverseTex.image);
  const reverseTexMirrored = canvasToTexture(reverseImgMirrored, THREE.SRGBColorSpace);
  const obverseNormal = buildNormalMapFromImage(obverseTex.image, 1);
  const reverseNormal = buildNormalMapFromImage(reverseImgMirrored, 1);

  // The reverse texture was mirrored horizontally → its coin center's x flips.
  // cy and radius are invariant under horizontal mirror.
  const obverseMeta = entry.obverse;
  const reverseMeta = {
    cx_uv: 1 - entry.reverse.cx_uv,
    cy_uv: entry.reverse.cy_uv,
    radius_uv: entry.reverse.radius_uv,
  };

  const coin = buildCoin({
    obverseTex, obverseNormal, obverseMeta,
    reverseTex: reverseTexMirrored, reverseNormal, reverseMeta,
    edgeTex: ctx.edgeTex,
    tune: ctx.tune,
  });
  ctx.scene.add(coin.group);
  ctx.coin = coin;

  // Re-apply the current slider state to the freshly-built materials so the
  // user's tuning persists across coin swaps.
  if (ctx.tune) {
    Object.entries(ctx.tune).forEach(([k, v]) => applyTune(ctx, k, v));
  }

  // Reflect the current coin in the URL without firing the router (replaceState
  // doesn't trigger hashchange — we stay mounted, just swap the coin).
  history.replaceState({}, '', `#/scan/coin-3d?id=${entry.numista_id}`);

  setStatus(ctx.statusEl, '', { fadeOut: true });
}

function swapCoin(ctx, direction) {
  if (!ctx.coinList) return;
  const N = ctx.coinList.length;
  ctx.coinIndex = (ctx.coinIndex + direction + N) % N;
  loadAndBuildCoin(ctx, ctx.coinList[ctx.coinIndex]);
}

function disposeCoin(coin) {
  // Dispose every texture the coin owns. Some are shared between materials
  // (e.g. obverseTex on matSilver and matGold) — Texture.dispose() is idempotent.
  const textures = [
    coin.matSilver?.map, coin.matSilver?.normalMap,
    coin.matGold?.map,   coin.matGold?.normalMap,
    coin.matSilverBack?.map, coin.matSilverBack?.normalMap,
    coin.matGoldBack?.map,   coin.matGoldBack?.normalMap,
  ];
  for (const t of textures) t?.dispose?.();

  const materials = [
    coin.matSilver, coin.matGold, coin.matSilverBack, coin.matGoldBack,
    coin.matRim, coin.matEdge, coin.matGroove,
  ];
  for (const m of materials) m?.dispose?.();

  coin.group.traverse((obj) => obj.geometry?.dispose?.());
}

// ───────── Three.js scene plumbing ─────────

function createSceneContext(canvasWrap) {
  const renderer = new THREE.WebGLRenderer({ antialias: true, alpha: true });
  renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
  renderer.outputColorSpace = THREE.SRGBColorSpace;
  renderer.toneMapping = THREE.ACESFilmicToneMapping;
  renderer.toneMappingExposure = DEFAULT_EXPOSURE;
  canvasWrap.appendChild(renderer.domElement);

  const scene = new THREE.Scene();

  // IBL via Filament-style room env, baked through PMREM for PBR specular.
  const pmrem = new THREE.PMREMGenerator(renderer);
  scene.environment = pmrem.fromScene(new RoomEnvironment(renderer), 0.04).texture;

  // Two-key studio lighting : front key on +Z hemisphere illuminates the obverse,
  // back key (lower intensity) on -Z hemisphere keeps the reverse alive instead
  // of falling into shadow when the camera orbits to the back.
  const dirFront = new THREE.DirectionalLight(0xffffff, 1.4);
  dirFront.position.set(2.5, 3.5, 4.0);
  scene.add(dirFront);
  const dirBack = new THREE.DirectionalLight(0xffffff, 1.0);
  dirBack.position.set(-2.5, -3.5, -4.0);
  scene.add(dirBack);
  scene.add(new THREE.HemisphereLight(0xffffff, 0x202028, 0.25));

  const camera = new THREE.PerspectiveCamera(35, 1, 0.1, 200);
  camera.position.set(0, 6, 38);

  const controls = new OrbitControls(camera, renderer.domElement);
  controls.enableDamping = true;
  controls.dampingFactor = 0.08;
  controls.minDistance = 22;
  controls.maxDistance = 80;
  controls.target.set(0, 0, 0);
  controls.autoRotateSpeed = 1.2;

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
  function tick() {
    controls.update();
    renderer.render(scene, camera);
    raf = requestAnimationFrame(tick);
  }
  raf = requestAnimationFrame(tick);

  return {
    renderer, scene, camera, controls, pmrem, coin: null, debugListener: null,
    dispose() {
      cancelAnimationFrame(raf);
      ro.disconnect();
      if (this.debugListener) window.removeEventListener('debug:toggle', this.debugListener);
      controls.dispose();
      pmrem.dispose();
      renderer.dispose();
      if (renderer.domElement.parentNode) renderer.domElement.parentNode.removeChild(renderer.domElement);
    },
  };
}

// ───────── Coin construction ─────────

function buildCoin({
  obverseTex, obverseNormal, obverseMeta,
  reverseTex, reverseNormal, reverseMeta,
  edgeTex,
}) {
  const group = new THREE.Group();

  // ─── Z layout (top half, mirror for bottom) ──────────────────────────
  // Highest point of the coin = outer rim face (z = +T/2).
  // Ring face is recessed below the rim by RIM_HEIGHT.
  // Disc is recessed further by RING_LIP (the press-fit groove).
  const Z_RIM = THICKNESS / 2;
  const Z_RING = Z_RIM - RIM_HEIGHT;
  const Z_DISC = Z_RING - RING_LIP;

  // Face materials : photo as albedo, ring tinted silver, disc tinted gold.
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

  // Rim step walls (small vertical cliffs between ring face and rim) : plain
  // silver. A cylinder can't be UV-mapped from XY, and the wall is only 0.06mm
  // tall — barely visible except at grazing angles, plain silver reads fine.
  const matRim = new THREE.MeshStandardMaterial({
    color: 0xeaeaef,
    metalness: DEFAULT_METALNESS,
    roughness: DEFAULT_ROUGHNESS,
    side: THREE.DoubleSide,
  });

  // Disc-ring groove : near-black, non-metallic — reads as a hairline shadow
  // line, not as a visible metallic step.
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

  // ─── Top face (obverse) ───────────────────────────────────────────────
  const ringTop = makeAnnulus(R_RING_INNER, R_OUT - RIM_WIDTH, +1, obverseMeta);
  ringTop.position.z = Z_RING;
  ringTop.material = matSilver;

  // Rim shares matSilver so the obverse photo (and the 12 stars near its edge)
  // continues seamlessly from ring face onto the raised rim.
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

  // ─── Bottom face (reverse) ────────────────────────────────────────────
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

  // ─── Outer cylinder (tranche) ─────────────────────────────────────────
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

// Annulus (top or bottom face of the silver outer ring). UV maps each vertex
// to its real (x,y) position in the coin photo so the ring captures the photo's
// matching outer band. `meta` = { cx_uv, cy_uv, radius_uv } from coins.json.
function makeAnnulus(rInner, rOuter, normalSign, meta) {
  const segments = 192;
  const geo = new THREE.RingGeometry(rInner, rOuter, segments, 1);
  // RingGeometry's default normal is +Z. rotateX(π) is a proper rotation that
  // flips the normal to -Z without inverting winding (unlike scale(_, _, -1)).
  if (normalSign < 0) geo.rotateX(Math.PI);
  remapUVsFromXY(geo, meta);
  return new THREE.Mesh(geo);
}

function makeDisc(radius, normalSign, meta) {
  const segments = 128;
  const geo = new THREE.CircleGeometry(radius, segments);
  if (normalSign < 0) geo.rotateX(Math.PI);
  remapUVsFromXY(geo, meta);
  return new THREE.Mesh(geo);
}

// UV from world-aligned (x,y) coordinates of each vertex, calibrated by the
// per-photo metadata. Gives a continuous photo mapping across ring + disc + rim
// regardless of geometry boundaries, AND adapts to each Numista scan's specific
// centering / radius (originals are never modified — see decision D8).
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

// Sobel-derived normal map. Accepts an HTMLImageElement OR a canvas (both have
// width/height + drawable to a 2D context). Encodes as tangent-space RGB.
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
      const ml = lum[y * w + x0],                         mr = lum[y * w + x1];
      const bl = lum[y1 * w + x0], bc = lum[y1 * w + x], br = lum[y1 * w + x1];
      const gx = (tr + 2 * mr + br) - (tl + 2 * ml + bl);
      const gy = (bl + 2 * bc + br) - (tl + 2 * tc + tr);
      // Tangent-space normal : encode (-gx*s, -gy*s, 1) normalized.
      let nx = -gx * strength;
      let ny = -gy * strength;
      let nz = 1;
      const len = Math.hypot(nx, ny, nz) || 1;
      nx /= len; ny /= len; nz /= len;
      const o = (y * w + x) * 4;
      out[o]     = (nx * 0.5 + 0.5) * 255;
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

// Procedural edge texture (4096×256). High resolution, no public-domain unwrapped
// edge scan was good enough to use, so we generate one : reeded background
// (vertical knurling) + 6× "2 ★ ★ ★" lettering alternating upright/inverted, with
// incised look (dark fill + soft highlight).
function buildProceduralEdgeTexture() {
  const W = 4096;
  const H = 256;
  const cv = document.createElement('canvas');
  cv.width = W; cv.height = H;
  const ctx = cv.getContext('2d');

  // Base metal gradient — slight darkening at top/bottom to suggest cylindrical
  // shading even before lighting kicks in.
  const grad = ctx.createLinearGradient(0, 0, 0, H);
  grad.addColorStop(0.00, '#7a7a82');
  grad.addColorStop(0.50, '#c0c0c8');
  grad.addColorStop(1.00, '#7a7a82');
  ctx.fillStyle = grad;
  ctx.fillRect(0, 0, W, H);

  // Fine vertical reeding. ~280 stripes around the full circumference is close
  // to the real density of a milled 2€ edge.
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

  // Lettering : 6 repetitions of "2 ★ ★ ★", alternating orientation.
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

  // Edge-of-cylinder vignette to imply the rolled-off shape under lighting.
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

// Mirror an image horizontally into a fresh canvas. Used so the reverse face
// reads correctly to the user despite being viewed from -Z (which would
// otherwise flip the design left-right).
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

// ───────── UI handlers ─────────

function onChipClick(chip, ctx) {
  const action = chip.dataset.action;
  if (action === 'toggle-normal') {
    const on = chip.getAttribute('aria-pressed') !== 'true';
    chip.setAttribute('aria-pressed', String(on));
    // Restore the slider's relief value when re-enabled, zero it when disabled.
    const s = on ? (ctx.tune?.relief ?? DEFAULT_NORMAL_STRENGTH) : 0;
    setReliefStrength(ctx, s);
  } else if (action === 'toggle-rotate') {
    const on = chip.getAttribute('aria-pressed') !== 'true';
    chip.setAttribute('aria-pressed', String(on));
    ctx.controls.autoRotate = on;
  } else if (action === 'reset-view') {
    ctx.controls.reset();
    ctx.camera.position.set(0, 6, 38);
    ctx.controls.target.set(0, 0, 0);
  } else if (action === 'prev') {
    swapCoin(ctx, -1);
  } else if (action === 'next') {
    swapCoin(ctx, +1);
  } else if (action === 'toggle-tune') {
    // The chip and the panel's × close both fire this — read the panel's own
    // open state rather than the clicker's aria-pressed (the close button has none).
    const panel = document.querySelector('[data-slot="tune"]');
    if (!panel) return;
    const willOpen = panel.dataset.open !== 'true';
    panel.dataset.open = String(willOpen);
    const tuneChip = document.querySelector('.coin3d-tune-toggle');
    if (tuneChip) tuneChip.setAttribute('aria-pressed', String(willOpen));
  }
}

function wireSliders(root, ctx) {
  ctx.tune = {
    relief: DEFAULT_NORMAL_STRENGTH,
    metalness: DEFAULT_METALNESS,
    roughness: DEFAULT_ROUGHNESS,
    exposure: DEFAULT_EXPOSURE,
  };
  // Sync each slider's UI state to the canonical default — HTML is the wrong
  // place to keep these values once we treat the JS constants as the source.
  Object.entries(ctx.tune).forEach(([k, v]) => {
    const input = root.querySelector(`[data-tune="${k}"]`);
    const label = root.querySelector(`[data-val="${k}"]`);
    if (input) input.value = String(v);
    if (label) label.textContent = formatVal(v);
  });
  root.querySelectorAll('[data-tune]').forEach((input) => {
    const key = input.dataset.tune;
    const label = root.querySelector(`[data-val="${key}"]`);
    input.addEventListener('input', () => {
      const v = parseFloat(input.value);
      ctx.tune[key] = v;
      if (label) label.textContent = formatVal(v);
      applyTune(ctx, key, v);
    });
  });
}

function applyTune(ctx, key, v) {
  if (!ctx.coin) return;
  const faces = [ctx.coin.matSilver, ctx.coin.matGold, ctx.coin.matSilverBack, ctx.coin.matGoldBack];
  // Rim + edge surfaces also follow the same metal feel.
  const allMetal = [...faces, ctx.coin.matRim, ctx.coin.matEdge];
  if (key === 'relief') {
    setReliefStrength(ctx, v);
    const chip = document.querySelector('[data-action="toggle-normal"]');
    if (chip) chip.setAttribute('aria-pressed', String(v > 0));
  } else if (key === 'metalness') {
    allMetal.forEach((m) => { m.metalness = v; });
  } else if (key === 'roughness') {
    allMetal.forEach((m) => { m.roughness = v; });
  } else if (key === 'exposure') {
    ctx.renderer.toneMappingExposure = v;
  }
}

function setReliefStrength(ctx, v) {
  if (!ctx.coin) return;
  const back = v * REVERSE_RELIEF_BOOST;
  ctx.coin.matSilver.normalScale.set(v, v);
  ctx.coin.matGold.normalScale.set(v, v);
  ctx.coin.matSilverBack.normalScale.set(back, back);
  ctx.coin.matGoldBack.normalScale.set(back, back);
}

function formatVal(v) {
  return Math.abs(v) < 1 ? v.toFixed(2) : v.toFixed(1);
}

// ───────── small utils ─────────

function setStatus(el, text, opts = {}) {
  if (!el) return;
  el.textContent = text;
  el.classList.remove('is-hidden');
  if (opts.fadeOut) setTimeout(() => el.classList.add('is-hidden'), 1200);
}

function nextFrame() { return new Promise((r) => requestAnimationFrame(() => r())); }
