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

export function addCoin(eurioId, opts = {}) {
  state.collection.push({
    eurioId,
    addedAt: Date.now(),
    valueAtAddCents: opts.valueAtAddCents ?? null,
    condition: opts.condition ?? null,
    note: opts.note ?? null,
  });
  recomputeLevel();
  save();
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

// ───────── Demo seed (Phase 2 · Agent B5) ─────────
//
// Fills the collection with ~15 representative coins so the vault, profile
// level and achievements have something to show without going through 15
// scans. Spread addedAt dates over the last ~90 days and set a
// `valueAtAddCents` a bit lower than a mocked current p50, so a positive
// delta appears in profile stats.
//
// All helpers are local to this function — we do NOT extend the top-level
// module surface, and we do NOT mutate the existing `addCoin`/`reset` logic.

const DEMO_COIN_IDS = [
  // 5 pieces de circulation, pays varies (couvre copper / nordic / silver / bi-metal)
  'de-2002-1eur-standard',
  'es-2012-2eur-standard',
  'it-2008-50c-standard',
  'nl-2014-10c-standard',
  'pt-2010-5c-standard',
  // 6 commemoratives 2EUR "interessantes"
  'de-2007-2eur-treaty-of-rome',
  'fr-2015-2eur-70-years-of-peace-in-europe',
  'it-2012-2eur-10-years-of-euro-cash',
  'lu-2009-2eur-10th-anniversary-of-the-economic-and-monetary-union',
  'mc-2015-2eur-800-years-since-the-first-castle-in-the-rock',
  'sm-2016-2eur-550-years-since-the-death-of-donatello',
  // 4 pieces plus rares / micro-etats / emissions communes
  'va-2017-2eur-100-years-of-marian-apparitions-in-fatima',
  'ad-2014-2eur-20-years-in-the-council-of-europe',
  'mt-2015-2eur-republic-of-malta-1974',
  'ie-2009-2eur-10th-anniversary-of-the-economic-and-monetary-union',
];

// Fallback p50s by face value cents — matches the tone of the profile mockup
// without needing a real price oracle. Used both for the `current` (returned
// by hasCoin consumers) and to back-compute a plausible lower `valueAtAdd`.
function demoCurrentP50Cents(faceValueCents) {
  if (faceValueCents == null) return 220;
  if (faceValueCents <= 5)   return 60;    // ~0.60 €
  if (faceValueCents <= 20)  return 140;   // ~1.40 €
  if (faceValueCents <= 50)  return 220;   // ~2.20 €
  if (faceValueCents <= 100) return 380;   // ~3.80 €
  return 640;                               // ~6.40 € (commemos 2€)
}

export async function seedDemoCollection() {
  // Lazy-load data.js to avoid a hard import-time coupling with the mock
  // collection (state.js must stay standalone — data may not be loaded yet).
  const data = await import('./data.js');
  if (typeof data.init === 'function') {
    await data.init();
  }

  // Wipe the existing collection so re-running seed stays idempotent instead
  // of stacking duplicates. We do this in-place so we don't touch save/reset.
  state.collection.length = 0;

  const added = [];
  const now = Date.now();
  const DAY = 24 * 60 * 60 * 1000;

  DEMO_COIN_IDS.forEach((eurioId, i) => {
    // Not every id is guaranteed to exist in the dataset — if a commemorative
    // has been renamed, fall back to a same-country random coin so the demo
    // still lands 15 items.
    let coin = data.getCoin ? data.getCoin(eurioId) : null;
    if (!coin && typeof data.randomCoin === 'function') {
      coin = data.randomCoin();
    }
    if (!coin) return;

    const current = demoCurrentP50Cents(coin.faceValueCents);
    // Back-compute a value-at-add around 75% of current → positive delta.
    const valueAtAddCents = Math.max(coin.faceValueCents ?? 1,
                                     Math.round(current * 0.74));

    // Spread addedAt over the last ~90 days, deterministically.
    const addedAt = now - Math.round((90 - i * 5.5) * DAY);

    state.collection.push({
      eurioId: coin.eurioId,
      addedAt,
      valueAtAddCents,
      condition: i % 3 === 0 ? 'good' : null,
      note: null,
    });
    added.push(coin.eurioId);
  });

  // Mark onboarding as done so the router doesn't bounce us back to it.
  state.firstRun = false;

  recomputeLevel();
  save();

  return added;
}
