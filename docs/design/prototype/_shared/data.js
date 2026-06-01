/* data.js — loads the offline core (C3) and exposes queries.
 *
 * Source: data/app_core.json — the offline core projected from Supabase by
 * `go-task ml:build-app-core`. The JSON is NOT tracked in git (regenerable).
 *
 * Shape: { schema_version, coins: [ { eurio_id, country, year,
 *   face_value_cents, is_commemorative, theme, design_description,
 *   variant_kind, names:{fr,en}, descriptions, prices, credits, topics,
 *   mint_releases, shared_reverse_id, ... } ], shared_reverse, mints, ... }
 *
 * On-demand data (obverse images, fresh prices, other languages) lives in
 * Supabase — see _shared/supabase.js (the contact point for the typed api.js).
 */

import { obverseUrl } from './supabase.js';

let _loaded = false;
let _byId = new Map();
let _all = [];
let _countries = [];
let _sharedReverse = new Map();   // shared_reverse_id → { asset_name, ... }

// ───────── Init / fetch ─────────

export async function init() {
  if (_loaded) return;
  try {
    const res = await fetch('data/app_core.json', { cache: 'force-cache' });
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    const raw = await res.json();
    const coins = Array.isArray(raw) ? raw : raw.coins ?? [];
    _all = coins.map(normalise);
    _byId = new Map(_all.map(c => [c.eurioId, c]));
    _countries = Array.from(new Set(_all.map(c => c.country).filter(Boolean))).sort();
    _sharedReverse = new Map((raw.shared_reverse ?? []).map(s => [s.id, s]));
    _loaded = true;
    console.info(`[data] loaded ${_all.length} coins (app_core v${raw.schema_version ?? '?'})`);
  } catch (err) {
    console.error('[data] load failed. Run `go-task ml:build-app-core` first.', err);
    _loaded = false;
  }
}

// Normalise an app_core coin into the friendly flat shape used by scenes.
// The full record (names, descriptions, prices, credits, topics, releases,
// shared_reverse_id) stays accessible via `.raw`.
function normalise(c) {
  const cents = c.face_value_cents ?? 0;
  return {
    eurioId: c.eurio_id,
    country: (c.country || '').toLowerCase(),
    countryName: c.country_name || c.country || '?',
    year: c.year ?? null,
    faceValue: cents / 100,                            // e.g. 2, 0.5
    faceValueCents: cents,
    isCommemorative: !!c.is_commemorative,
    theme: c.theme ?? null,
    designDescription: c.design_description ?? null,
    raw: c,
  };
}

export function isReady() { return _loaded; }

// ───────── Queries ─────────

export function getCoin(eurioId) {
  return _byId.get(eurioId) || null;
}

export function filterCoins({ country, year, faceValueCents, isCommemorative } = {}) {
  return _all.filter(c => {
    if (country && c.country !== country.toLowerCase()) return false;
    if (year && c.year !== year) return false;
    if (faceValueCents != null && c.faceValueCents !== faceValueCents) return false;
    if (isCommemorative != null && c.isCommemorative !== isCommemorative) return false;
    return true;
  });
}

export function searchCoins(query) {
  if (!query) return [];
  const q = fold(query);
  return _all.filter(c => {
    const hay = fold(`${c.countryName} ${c.theme || ''}`);
    return hay.includes(q);
  });
}

function fold(s) {
  return (s || '').normalize('NFD').replace(/[\u0300-\u036f]/g, '').toLowerCase();
}

export function randomCoin(filter = {}) {
  const pool = Object.keys(filter).length ? filterCoins(filter) : _all;
  if (!pool.length) return null;
  return pool[Math.floor(Math.random() * pool.length)];
}

export function allCountries() {
  return _countries.slice();
}

export function allCoins() {
  return _all.slice();
}

// ───────── 3D textures (avers Storage + carte packagée) ─────────

export function getSharedReverse(id) {
  return _sharedReverse.get(id) || null;
}

// Resolve the obverse (Supabase Storage) + reverse (packaged carte) texture URLs
// for a coin. Returns null if the shared_reverse mapping is missing.
export function coinTextures(coinOrId) {
  const c = typeof coinOrId === 'string' ? getCoin(coinOrId) : coinOrId;
  if (!c) return null;
  const srId = c.raw?.shared_reverse_id;
  const sr = srId ? _sharedReverse.get(srId) : null;
  if (!sr) return null;
  return {
    obverse: obverseUrl(c.eurioId),
    reverse: `data/shared_reverse/${sr.asset_name}`,
  };
}

// ───────── Coin SVG renderer ─────────
//
// Produces an inline SVG string for a stylised coin based on face value
// and a stable hash of the eurio_id. Used everywhere we need a placeholder.

const METALS = {
  copper: {
    outer: ['#E8B892', '#B8714A', '#6B3A1A'],
    inner: ['#D49A6A', '#8F5120'],
    text: '#3A1F08',
  },
  nordic: {
    outer: ['#F5D98A', '#C8A864', '#8F7637'],
    inner: ['#E0C078', '#9B7D3A'],
    text: '#5A4824',
  },
  bimetal_outer: {
    outer: ['#F5D98A', '#C8A864', '#8F7637'],
    inner: ['#E6E4C8', '#B7B59A', '#6B6A52'],
    text: '#2A2A1A',
  },
};

function metalFor(cents) {
  if (cents <= 5) return METALS.copper;
  if (cents <= 50) return METALS.nordic;
  return METALS.bimetal_outer;
}

function hashInt(str) {
  let h = 0;
  for (let i = 0; i < str.length; i++) {
    h = (h * 31 + str.charCodeAt(i)) >>> 0;
  }
  return h;
}

function formatFaceValue(cents) {
  if (cents >= 100) {
    const eur = cents / 100;
    return Number.isInteger(eur) ? `${eur} €` : `${eur.toFixed(2).replace('.', ',')} €`;
  }
  return `${cents} c`;
}

/**
 * Returns an inline SVG string for a coin.
 * @param {Object} coin - normalised coin (or plain eurioId string)
 * @param {Object} opts - { size?: number, showLabel?: boolean }
 */
export function coinSvg(coin, opts = {}) {
  const c = typeof coin === 'string' ? getCoin(coin) : coin;
  if (!c) return '';
  const size = opts.size ?? 200;
  const showLabel = opts.showLabel ?? true;
  const metal = metalFor(c.faceValueCents);
  const isBi = c.faceValueCents >= 100;
  const seed = hashInt(c.eurioId);
  const tilt = ((seed % 20) - 10) / 20; // -0.5..0.5
  const uid = `cg-${seed.toString(36)}`;

  const label = formatFaceValue(c.faceValueCents);
  const labelFont = size * 0.28;
  const subFont = size * 0.07;

  return `
<svg viewBox="0 0 ${size} ${size}" class="coin-svg" xmlns="http://www.w3.org/2000/svg" role="img" aria-label="${c.countryName} ${label}">
  <defs>
    <radialGradient id="${uid}-outer" cx="35%" cy="30%" r="80%">
      <stop offset="0%"  stop-color="${metal.outer[0]}"/>
      <stop offset="55%" stop-color="${metal.outer[1]}"/>
      <stop offset="100%" stop-color="${metal.outer[2]}"/>
    </radialGradient>
    <radialGradient id="${uid}-inner" cx="40%" cy="32%" r="75%">
      <stop offset="0%"  stop-color="${metal.inner[0]}"/>
      <stop offset="100%" stop-color="${metal.inner[metal.inner.length - 1]}"/>
    </radialGradient>
    <filter id="${uid}-rim" x="-10%" y="-10%" width="120%" height="120%">
      <feGaussianBlur stdDeviation="0.6"/>
    </filter>
  </defs>

  <g transform="rotate(${tilt} ${size/2} ${size/2})">
    <circle cx="${size/2}" cy="${size/2}" r="${size/2 - 2}" fill="url(#${uid}-outer)"/>
    <circle cx="${size/2}" cy="${size/2}" r="${size/2 - 2}"
            fill="none" stroke="rgba(0,0,0,0.35)" stroke-width="1"/>
    <circle cx="${size/2}" cy="${size/2}" r="${size * (isBi ? 0.32 : 0.40)}"
            fill="url(#${uid}-inner)" stroke="rgba(0,0,0,0.25)" stroke-width="0.8"/>

    ${showLabel ? `
      <text x="50%" y="52%"
            text-anchor="middle" dominant-baseline="middle"
            font-family="Fraunces, Georgia, serif"
            font-style="italic"
            font-size="${labelFont}"
            fill="${metal.text}"
            letter-spacing="-0.02em">${label}</text>
      <text x="50%" y="${size * 0.76}"
            text-anchor="middle"
            font-family="'JetBrains Mono', monospace"
            font-size="${subFont}"
            letter-spacing="0.18em"
            fill="${metal.text}"
            opacity="0.75">${(c.year ?? '').toString()}</text>
    ` : ''}
  </g>
</svg>`;
}
