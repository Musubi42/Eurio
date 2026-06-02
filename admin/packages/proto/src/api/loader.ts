/* api/loader.ts — LE SEUL POINT BAS-NIVEAU de chargement des données.
 *
 * ⚠️ Point de contact unique avec le chantier « eurio.db source unique ».
 * L'autre session repointe ICI (et seulement ici) la provenance du snapshot.
 * Aucune scène ni aucun store ne charge de données ailleurs.
 *
 * Deux modes via VITE_DATA_MODE :
 *   - 'fixtures' (défaut) → fetch data/app_core.json packagé (public/).
 *   - 'live'              → fetch la projection app-facing Supabase (PostgREST,
 *                           clé anon read-only) et reconstruit le même Snapshot.
 */

import type { RawCoin, Snapshot } from './types'
import { isParity } from './parity'

const MODE: 'fixtures' | 'live' = import.meta.env.VITE_DATA_MODE ?? 'fixtures'

// Storage public Supabase (avers). Public par design — pas de clé requise.
const SUPABASE_URL = 'https://ettxkixkxrzchbnohgfm.supabase.co'
const STORAGE_PUBLIC = `${SUPABASE_URL}/storage/v1/object/public`

// Clé anon PUBLIQUE (RLS read-only) — embarquable, protégée par les policies.
// Surchargée par VITE_SUPABASE_ANON_KEY si fournie.
const SUPABASE_ANON_KEY =
  import.meta.env.VITE_SUPABASE_ANON_KEY ??
  '***REDACTED-SECRET***'

/** URL publique de l'avers (face nationale) webp d'une pièce dans Storage. */
export function obverseUrl(eurioId: string): string {
  return `${STORAGE_PUBLIC}/coin-images/${eurioId}/obverse.webp`
}

let _cache: Promise<Snapshot> | null = null

/** Charge le snapshot brut (une fois, mémoïsé). */
export function loadSnapshot(): Promise<Snapshot> {
  if (_cache) return _cache
  _cache = MODE === 'live' ? loadLive() : loadFixtures()
  return _cache
}

async function loadFixtures(): Promise<Snapshot> {
  // En parité, on sert le bundle figé hermétique (cf. build_app_core_qa).
  const file = isParity() ? 'app_core_qa.json' : 'app_core.json'
  const url = `${import.meta.env.BASE_URL}data/${file}`
  const res = await fetch(url, { cache: 'force-cache' })
  if (!res.ok) {
    throw new Error(
      `[loader] ${file} introuvable (${res.status}). ` +
        'Régénère-le via `go-task ml:build-app-core` (ou parity:capture-proto pour le QA).',
    )
  }
  return (await res.json()) as Snapshot
}

// ───────── Mode live (PostgREST) ─────────
//
// ⚠️ DOIT REFLÉTER ml/export/build_app_core.py (fetch_core + build_json) : même
// sélection de tables/colonnes, mêmes filtres (i18n FR+EN, prix kind=market),
// même imbrication par pièce. Si le build évolue, mettre à jour les deux.

const REST = `${SUPABASE_URL}/rest/v1`
const PAGE = 1000
const OFFLINE_LANGS = ['fr', 'en']

const COIN_COLS =
  'eurio_id,country,country_name,year,face_value_cents,is_commemorative,collector_only,' +
  'theme,design_description,mintage,diameter_mm,weight_g,thickness_mm,composition,shape,' +
  'orientation,edge_description,edge_lettering,obverse_lettering,reverse_lettering,demonetized,' +
  'demonetized_on,design_group_id,variant_kind,canonical_eurio_id,series_id,shared_reverse_id'

/** GET PostgREST paginé (Range header) → toutes les lignes. */
async function pgFetchAll<T = Record<string, unknown>>(
  table: string,
  select: string,
  extraParams: Record<string, string> = {},
): Promise<T[]> {
  const out: T[] = []
  const qs = new URLSearchParams({ select, ...extraParams }).toString()
  for (let offset = 0; ; offset += PAGE) {
    const res = await fetch(`${REST}/${table}?${qs}`, {
      headers: {
        apikey: SUPABASE_ANON_KEY,
        Authorization: `Bearer ${SUPABASE_ANON_KEY}`,
        'Range-Unit': 'items',
        Range: `${offset}-${offset + PAGE - 1}`,
      },
    })
    if (!res.ok) throw new Error(`[loader] live ${table} ${res.status}`)
    const page = (await res.json()) as T[]
    out.push(...page)
    if (page.length < PAGE) return out
  }
}

function groupBy<T extends Record<string, unknown>>(rows: T[], key: string): Map<string, T[]> {
  const m = new Map<string, T[]>()
  for (const r of rows) {
    const k = String(r[key])
    const arr = m.get(k)
    if (arr) arr.push(r)
    else m.set(k, [r])
  }
  return m
}

type Row = Record<string, unknown>

async function loadLive(): Promise<Snapshot> {
  const langFilter = `in.(${OFFLINE_LANGS.join(',')})`
  const [coins, sharedReverse, designGroup, mints, releases, credits, topics, names, descs, prices] =
    await Promise.all([
      pgFetchAll<Row>('coin', COIN_COLS),
      pgFetchAll<Row>('shared_reverse', 'id,label,asset_name,map_version,applies_to'),
      pgFetchAll<Row>('design_group', 'id,designation'),
      pgFetchAll<Row>('mint', 'id,country,mark,city,display_name'),
      pgFetchAll<Row>('coin_mint_release', 'id,parent_type_id,mint_year,mint_id,issue_type,mintage'),
      pgFetchAll<Row>('coin_credit', 'eurio_id,role,name,position'),
      pgFetchAll<Row>('coin_topic', 'eurio_id,lang,topic', { lang: langFilter }),
      pgFetchAll<Row>('coin_name_i18n', 'eurio_id,lang,title', { lang: langFilter }),
      pgFetchAll<Row>('coin_description_i18n', 'eurio_id,lang,title,description', { lang: langFilter }),
      pgFetchAll<Row>('coin_price', 'eurio_id,grade,p_low,p_mid,p_high,currency,source,sampled_at', {
        kind: 'eq.market',
      }),
    ])

  const byName = groupBy(names, 'eurio_id')
  const byDesc = groupBy(descs, 'eurio_id')
  const byPrice = groupBy(prices, 'eurio_id')
  const byCredit = groupBy(credits, 'eurio_id')
  const byTopic = groupBy(topics, 'eurio_id')
  const byRelease = groupBy(releases, 'parent_type_id') // parent_type_id == eurio_id du type

  const nested = coins.map((c) => {
    const eid = String(c.eurio_id)
    return {
      ...c,
      names: Object.fromEntries((byName.get(eid) ?? []).map((r) => [r.lang as string, r.title])),
      descriptions: Object.fromEntries(
        (byDesc.get(eid) ?? []).map((r) => [r.lang as string, { title: r.title, description: r.description }]),
      ),
      prices: (byPrice.get(eid) ?? []).map((r) => ({
        grade: r.grade, p_low: r.p_low, p_mid: r.p_mid, p_high: r.p_high,
        currency: r.currency, source: r.source, sampled_at: r.sampled_at,
      })),
      credits: (byCredit.get(eid) ?? []).map((r) => ({ role: r.role, name: r.name, position: r.position })),
      topics: (byTopic.get(eid) ?? []).map((r) => ({ lang: r.lang, topic: r.topic })),
      mint_releases: (byRelease.get(eid) ?? []).map((r) => ({
        id: r.id, mint_year: r.mint_year, mint_id: r.mint_id, issue_type: r.issue_type, mintage: r.mintage,
      })),
    } as unknown as RawCoin
  })

  return {
    schema_version: 2,
    generated_at: new Date().toISOString(),
    offline_langs: OFFLINE_LANGS,
    shared_reverse: sharedReverse as Snapshot['shared_reverse'],
    design_groups: designGroup.map((d) => ({ id: d.id, designation: d.designation })),
    mints,
    coin_count: nested.length,
    coins: nested,
  }
}
