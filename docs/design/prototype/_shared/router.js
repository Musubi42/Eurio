/* router.js — hash-based router + shell bootstrap
 *
 * - Loads data (data.js) + state (state.js) once.
 * - Parses `location.hash` into { path, params, query }.
 * - Fetches scenes/<name>.html and injects into #view.
 * - Updates bottom nav active tab.
 * - Handles first-run redirect + debug routes.
 *
 * NOTE : routes that point to scenes not yet migrated from the old mockups
 *        render a stylised "Scene bientôt (Phase 2)" placeholder.
 */

import * as state from './state.js';
import * as data from './data.js';

// ───────── Route table ─────────
// Each entry : { pattern, scene, nav, chrome }
// - pattern : regex-style placeholder with :named segments
// - scene   : filename (without .html) OR null for a deferred scene
// - nav     : which bottom nav tab is active ('scan'|'vault'|'profile'|'marketplace'|null)
// - chrome  : 'none' | 'light' | 'dark' | 'modal'
//             'none'  → full-bleed : status bar + bottom nav + home indicator hidden
//             'light' → light status bar + light nav
//             'dark'  → dark status bar (light text) + dark nav
//             'modal' → reserved (sheets) — currently treated like 'light'

const ROUTES = [
  // Onboarding
  { path: '/onboarding/splash',      scene: 'onboarding-splash',    nav: null, chrome: 'none' },
  { path: '/onboarding/1',           scene: 'onboarding-1',         nav: null, chrome: 'none' },
  { path: '/onboarding/2',           scene: 'onboarding-2',         nav: null, chrome: 'none' },
  { path: '/onboarding/3',           scene: 'onboarding-3',         nav: null, chrome: 'none' },
  { path: '/onboarding/permission',  scene: 'onboarding-permission',nav: null, chrome: 'none' },
  { path: '/onboarding/replay',      scene: null,                   nav: null, chrome: 'none', action: 'replay-onboarding' },

  // Scan
  { path: '/scan',                   scene: 'scan-idle',            nav: 'scan', chrome: 'dark' },
  { path: '/scan/detecting',         scene: 'scan-detecting',       nav: 'scan', chrome: 'dark' },
  { path: '/scan/matched',           scene: 'scan-matched',         nav: 'scan', chrome: 'dark' },
  { path: '/scan/failure',           scene: 'scan-failure',         nav: 'scan', chrome: 'dark' },
  { path: '/scan/not-identified',    scene: 'scan-not-identified',  nav: 'scan', chrome: 'dark' },
  { path: '/scan/debug',             scene: 'scan-debug',           nav: 'scan', chrome: 'dark' },

  // Coin detail
  { path: '/coin/:eurioId',          scene: 'coin-detail',          nav: null, chrome: 'light' },

  // Vault — /vault routes directly to vault-home (no wrapper)
  { path: '/vault',                  scene: 'vault-home',           nav: 'vault', chrome: 'light' },
  { path: '/vault/filters',          scene: 'vault-filters',        nav: 'vault', chrome: 'light' },
  { path: '/vault/search',           scene: 'vault-search',         nav: 'vault', chrome: 'light' },

  // Profile
  { path: '/profile',                scene: 'profile',              nav: 'profile', chrome: 'light' },
  { path: '/profile/achievements',   scene: 'profile-achievements', nav: 'profile', chrome: 'light' },
  { path: '/profile/set/:setId',     scene: 'profile-set',          nav: 'profile', chrome: 'light' },
  { path: '/profile/unlock',         scene: 'profile-unlock',       nav: 'profile', chrome: 'none' },
  { path: '/profile/settings',       scene: 'profile-settings',     nav: 'profile', chrome: 'light' },

  // Marketplace (grisé, bientôt)
  { path: '/marketplace',            scene: 'marketplace-soon',     nav: 'marketplace', chrome: 'light' },

  // Debug
  { path: '/debug/reset',            scene: null, nav: null, chrome: 'light', action: 'reset' },
  { path: '/debug/seed-demo',        scene: null, nav: null, chrome: 'light', action: 'seed-demo' },
];

// ───────── Parsing ─────────

function parseHash(hash) {
  // #/foo/bar?x=1 -> { rawPath: '/foo/bar', query: { x: '1' } }
  const h = (hash || '').replace(/^#/, '') || '/';
  const [rawPath, queryString] = h.split('?');
  const query = {};
  if (queryString) {
    for (const kv of queryString.split('&')) {
      const [k, v] = kv.split('=');
      query[decodeURIComponent(k)] = decodeURIComponent(v ?? '');
    }
  }
  return { rawPath, query };
}

function match(route, rawPath) {
  const routeParts = route.path.split('/').filter(Boolean);
  const pathParts = rawPath.split('/').filter(Boolean);
  if (routeParts.length !== pathParts.length) return null;
  const params = {};
  for (let i = 0; i < routeParts.length; i++) {
    const rp = routeParts[i];
    const pp = pathParts[i];
    if (rp.startsWith(':')) {
      params[rp.slice(1)] = decodeURIComponent(pp);
    } else if (rp !== pp) {
      return null;
    }
  }
  return params;
}

function resolveRoute(rawPath) {
  for (const r of ROUTES) {
    const params = match(r, rawPath);
    if (params) return { route: r, params };
  }
  return null;
}

// ───────── Scene rendering ─────────

const view = () => document.getElementById('view');
const screenEl = () => document.querySelector('.screen');
const sceneCache = new Map();

async function fetchScene(sceneName) {
  if (sceneCache.has(sceneName)) return sceneCache.get(sceneName);
  try {
    const res = await fetch(`scenes/${sceneName}.html`);
    if (!res.ok) throw new Error(`${res.status}`);
    const html = await res.text();
    sceneCache.set(sceneName, html);
    return html;
  } catch (err) {
    return null;
  }
}

function renderPlaceholder(name, reason) {
  return `
    <div class="scene-placeholder">
      <div class="eyebrow eyebrow--gold">Phase 2 · à venir</div>
      <h2>Scène <code>${name || 'inconnue'}</code> bientôt disponible</h2>
      <p>${reason || 'Cette scène sera migrée par un agent Phase 2.'}</p>
      <p class="eyebrow">Retour <a href="#/scan" style="color:var(--indigo-700);text-decoration:underline">à l'écran Scan</a></p>
    </div>
  `;
}

async function renderScene(route, params, query) {
  const v = view();
  const sc = screenEl();
  if (!v || !sc) return;

  // Chrome (light/dark status bar + badge contrast)
  sc.dataset.chrome = route.chrome || 'light';

  // Special actions
  if (route.action === 'reset') {
    state.reset();
    location.hash = '#/onboarding/splash';
    return;
  }
  if (route.action === 'replay-onboarding') {
    state.replayOnboarding();
    location.hash = '#/onboarding/splash';
    return;
  }
  if (route.action === 'seed-demo') {
    // Agent B5 : seed ~15 demo coins then land on the vault.
    try {
      await state.seedDemoCollection();
    } catch (err) {
      console.warn('[router] seedDemoCollection failed', err);
    }
    location.hash = '#/vault';
    return;
  }

  if (!route.scene) {
    v.innerHTML = renderPlaceholder('', 'Route sans scène.');
    return;
  }

  const html = await fetchScene(route.scene);
  if (html == null) {
    v.innerHTML = renderPlaceholder(route.scene,
      'Le fichier correspondant n\'existe pas encore. Un agent de Phase 2 le créera dans <code>scenes/</code>.');
  } else {
    v.innerHTML = html;
  }

  // Optional co-located JS. Loaded once per scene, idempotent via ?t= cache.
  const sidecar = `scenes/${route.scene}.js`;
  try {
    const mod = await import(`../${sidecar}`).catch(() => null);
    if (mod && typeof mod.mount === 'function') {
      mod.mount({ params, query, state, data, navigate });
    }
  } catch (_) { /* no sidecar, fine */ }

  // Dispatch event for other listeners
  window.dispatchEvent(new CustomEvent('scene:mounted', {
    detail: { scene: route.scene, params, query },
  }));
}

// ───────── Nav update ─────────

function updateNav(route) {
  const nav = document.querySelector('.bottomnav');
  if (!nav) return;
  nav.querySelectorAll('.bottomnav__tab').forEach(tab => {
    const id = tab.dataset.nav;
    if (route && route.nav === id) {
      tab.setAttribute('aria-current', 'page');
    } else {
      tab.removeAttribute('aria-current');
    }
  });
}

// ───────── Public API ─────────

export function navigate(hash) {
  if (!hash.startsWith('#')) hash = '#' + (hash.startsWith('/') ? hash : '/' + hash);
  if (location.hash === hash) {
    resolve();
  } else {
    location.hash = hash;
  }
}

const listeners = new Set();
export function onRoute(fn) {
  listeners.add(fn);
  return () => listeners.delete(fn);
}

// ───────── Core resolve ─────────

async function resolve() {
  const { rawPath, query } = parseHash(location.hash);

  // Home redirect
  if (rawPath === '/' || rawPath === '') {
    const target = state.state.firstRun ? '#/onboarding/splash' : '#/scan';
    location.replace(target);
    return;
  }

  const resolved = resolveRoute(rawPath);
  if (!resolved) {
    view().innerHTML = renderPlaceholder(rawPath, 'Route inconnue.');
    updateNav(null);
    return;
  }
  const { route, params } = resolved;
  await renderScene(route, params, query);
  updateNav(route);
  listeners.forEach(fn => { try { fn({ route, params, query }); } catch (_) {} });
}

// ───────── Bootstrap ─────────

async function boot() {
  state.load();
  state.recomputeLevel();
  await data.init();
  installVersionBadge();
  window.addEventListener('hashchange', resolve);
  resolve();
}

// ───────── Version badge 7-tap debug ─────────

function installVersionBadge() {
  const badge = document.querySelector('.version-badge');
  if (!badge) return;
  badge.dataset.debug = state.state.debugMode ? 'on' : 'off';

  let taps = 0;
  let timer = null;
  badge.addEventListener('click', (ev) => {
    ev.preventDefault();
    taps += 1;
    clearTimeout(timer);
    timer = setTimeout(() => { taps = 0; }, 2000);
    if (taps >= 7) {
      taps = 0;
      const enabled = state.toggleDebug();
      badge.dataset.debug = enabled ? 'on' : 'off';
      console.info(`[debug] mode ${enabled ? 'enabled' : 'disabled'}`);
      window.dispatchEvent(new CustomEvent('debug:toggle', { detail: { enabled } }));
    }
  });
}

// Expose for debug / scene sidecars that want imperative nav.
window.eurio = Object.freeze({ navigate, state, data });

boot();
