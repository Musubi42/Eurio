/* api/util.ts — helpers déterministes partagés (hash, RNG seedé, fold accents). */

/** Hash FNV-1a 32-bit stable d'une chaîne. */
export function hashInt(str: string): number {
  let h = 2166136261 >>> 0
  for (let i = 0; i < str.length; i++) {
    h ^= str.charCodeAt(i)
    h = Math.imul(h, 16777619)
  }
  return h >>> 0
}

/** RNG déterministe (mulberry-ish) seedé par un entier. */
export function seeded(seed: number): () => number {
  let s = seed >>> 0
  return () => {
    s = (Math.imul(s ^ (s >>> 15), 2246822507) ^ Math.imul(s ^ (s >>> 13), 3266489909)) >>> 0
    return (s & 0xffffffff) / 0x100000000
  }
}

/** Normalise une chaîne pour recherche insensible aux accents/casse. */
export function fold(s: string): string {
  return (s || '').normalize('NFD').replace(/[\u0300-\u036f]/g, '').toLowerCase()
}
