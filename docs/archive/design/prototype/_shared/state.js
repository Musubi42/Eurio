/* state.js — mock state + localStorage persistence
 * Namespace key : "eurio.proto.v1"
 */

const LS_KEY = 'eurio.proto.v1';

const DEFAULT_STATE = {
  firstRun: true,
  collection: [],          // [{ eurioId, addedAt, valueAtAddCents, condition, note }]
  level: {
    tier: 'Découvreur',    // Découvreur | Passionné | Expert | Maître
    progressPct: 0,
    nextThresholdHint: 'Scanne ta première pièce',
    pendingUnlock: null,   // setId waiting for profile.js to celebrate
    unlockedSets: [],      // setIds already celebrated (deduped)
  },
  prefs: {
    notifications: false,
    catalogUpdate: 'wifi', // wifi | cell | manual
    telemetry: false,
    locale: 'fr',
  },
  debugMode: false,
};

function deepClone(obj) {
  return JSON.parse(JSON.stringify(obj));
}

export const state = deepClone(DEFAULT_STATE);

// ───────── Persistence ─────────

export function load() {
  try {
    const raw = localStorage.getItem(LS_KEY);
    if (!raw) {
      // First ever load : write the default so we know we're initialised.
      save();
      return state;
    }
    const parsed = JSON.parse(raw);
    Object.assign(state, deepClone(DEFAULT_STATE), parsed);
    return state;
  } catch (err) {
    console.warn('[state] load failed, resetting', err);
    reset();
    return state;
  }
}

export function save() {
  try {
    localStorage.setItem(LS_KEY, JSON.stringify(state));
  } catch (err) {
    console.warn('[state] save failed', err);
  }
}

export function reset() {
  Object.keys(state).forEach(k => delete state[k]);
  Object.assign(state, deepClone(DEFAULT_STATE));
  save();
}

// ───────── Collection ─────────

// Set definitions for auto-unlock celebration. Kept in sync with the
// achievements list inside scenes/profile.js — when this list grows, mirror
// the change there too. Only sets where completing them should trigger the
// celebration screen belong here.
const SET_DEFINITIONS = {
  'circulation-fr': [
    'fr-2020-1c-standard',  'fr-2020-2c-standard',
    'fr-2020-5c-standard',  'fr-2020-10c-standard',
    'fr-2020-20c-standard', 'fr-2020-50c-standard',
    'fr-2020-1eur-standard','fr-2020-2eur-standard',
  ],
};

function checkSetCompletions() {
  const ids = new Set(state.collection.map(c => c.eurioId));
  const already = new Set(state.level.unlockedSets || []);
  for (const [setId, members] of Object.entries(SET_DEFINITIONS)) {
    if (already.has(setId)) continue;
    const complete = members.every(m => ids.has(m));
    if (complete) {
      state.level.pendingUnlock = setId;
      state.level.unlockedSets = [...already, setId];
      // Stop at the first newly-completed set — celebrate one at a time.
      return;
    }
  }
}

export function addCoin(eurioId, opts = {}) {
  state.collection.push({
    eurioId,
    addedAt: Date.now(),
    valueAtAddCents: opts.valueAtAddCents ?? null,
    condition: opts.condition ?? null,
    note: opts.note ?? null,
  });
  recomputeLevel();
  checkSetCompletions();
  save();
}

export function consumePendingUnlock() {
  const id = state.level.pendingUnlock;
  state.level.pendingUnlock = null;
  save();
  return id;
}

export function removeCoin(eurioId) {
  const idx = state.collection.findIndex(c => c.eurioId === eurioId);
  if (idx >= 0) {
    state.collection.splice(idx, 1);
    recomputeLevel();
    save();
  }
}

export function hasCoin(eurioId) {
  return state.collection.some(c => c.eurioId === eurioId);
}

// ───────── Level (dumb heuristic for prototype) ─────────

const TIER_THRESHOLDS = [
  { tier: 'Découvreur', min: 0,   next: 'Passionné', nextAt: 5 },
  { tier: 'Passionné',  min: 5,   next: 'Expert',    nextAt: 30 },
  { tier: 'Expert',     min: 30,  next: 'Maître',    nextAt: 100 },
  { tier: 'Maître',     min: 100, next: null,        nextAt: null },
];

export function recomputeLevel() {
  const count = state.collection.length;
  let current = TIER_THRESHOLDS[0];
  for (const t of TIER_THRESHOLDS) {
    if (count >= t.min) current = t;
  }
  state.level.tier = current.tier;
  if (current.next) {
    const span = current.nextAt - current.min;
    const done = count - current.min;
    state.level.progressPct = Math.min(100, Math.round((done / span) * 100));
    state.level.nextThresholdHint = `Encore ${current.nextAt - count} pièces pour devenir ${current.next}`;
  } else {
    state.level.progressPct = 100;
    state.level.nextThresholdHint = 'Tu as atteint le rang le plus élevé.';
  }
}

// ───────── Debug flag ─────────

export function toggleDebug() {
  state.debugMode = !state.debugMode;
  save();
  return state.debugMode;
}

// ───────── Onboarding flag ─────────

export function completeOnboarding() {
  state.firstRun = false;
  save();
}

export function replayOnboarding() {
  state.firstRun = true;
  save();
}

// ───────── State presets (parity viewer + demo seed) ─────────
//
// Presets are loaded from shared JSON fixtures in _shared/fixtures/.
// They override state in memory WITHOUT writing to localStorage.
// This lets the parity viewer show different states per scene
// (populated vault, empty vault, advanced profile) without side effects.
// The same JSON files are consumed by Android (debug seed) and Maestro.

const KNOWN_PRESETS = ['empty', 'populated', 'profile-demo'];
const _presetCache = new Map();

async function fetchPreset(name) {
  if (_presetCache.has(name)) return _presetCache.get(name);
  const res = await fetch(`_shared/fixtures/preset-${name}.json`);
  if (!res.ok) throw new Error(`Preset "${name}" not found (${res.status})`);
  const data = await res.json();
  _presetCache.set(name, data);
  return data;
}

export async function applyPreset(name) {
  if (!name || !KNOWN_PRESETS.includes(name)) return false;

  const preset = await fetchPreset(name);

  // Reset state to defaults, then apply fixture collection
  Object.assign(state, deepClone(DEFAULT_STATE));
  state.firstRun = preset.firstRun ?? false;
  state.collection = deepClone(preset.collection ?? []);

  // Apply level override if present (e.g. profile-demo), otherwise recompute
  if (preset.levelOverride) {
    Object.assign(state.level, deepClone(preset.levelOverride));
  } else {
    recomputeLevel();
  }

  save();
  return true;
}

// Backward-compatible alias — used by #/debug/seed-demo route
export async function seedDemoCollection() {
  await applyPreset('populated');
  return state.collection.map(c => c.eurioId);
}
