/* supabase.js — on-demand data layer for the prototype.
 *
 * The proto mimics the app: the offline CORE (titles/desc FR+EN, characteristics,
 * baseline prices, shared_reverse) is packaged in data/app_core.json (see data.js).
 * Anything heavier or fresher is fetched on-demand from Supabase:
 *   - obverse image (national side) → public Storage bucket `coin-images`
 *   - fresh prices, other-language i18n → PostgREST (read-only, anon key)
 *
 * Keys below are PUBLIC by design (anon / publishable) — safe in client code;
 * row access is governed by RLS (SELECT-only for anon).
 *
 * NOTE (coordination): this file is the contact point with the typed `api.js`
 * layer. It exposes URL builders + a thin fetch; the typed interface is built
 * on top of it elsewhere.
 */

export const SUPABASE_URL = 'https://ettxkixkxrzchbnohgfm.supabase.co';
export const SUPABASE_ANON_KEY = 'sb_publishable_qk_ZIshppa_JSxrC2BEGVQ_tPygF_YI';

const STORAGE_PUBLIC = `${SUPABASE_URL}/storage/v1/object/public`;
const REST = `${SUPABASE_URL}/rest/v1`;

/** Public URL of a coin's obverse (national side) webp in Storage. */
export function obverseUrl(eurioId) {
  return `${STORAGE_PUBLIC}/coin-images/${eurioId}/obverse.webp`;
}

/** Thin PostgREST GET (read-only). `path` e.g. `coin_price?eurio_id=eq.fr-...`. */
export async function rest(path) {
  const res = await fetch(`${REST}/${path}`, {
    headers: { apikey: SUPABASE_ANON_KEY, Authorization: `Bearer ${SUPABASE_ANON_KEY}` },
  });
  if (!res.ok) throw new Error(`supabase ${res.status}: ${path}`);
  return res.json();
}
