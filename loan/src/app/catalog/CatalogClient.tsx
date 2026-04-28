'use client'

import { useEffect, useRef, useState } from 'react'
import Link from 'next/link'
import type { CatalogCoin } from '@/types/catalog'

const LS_KEY = 'eurio_loan_user'

type User = { id: string; name: string; emoji: string }

type Filters = {
  notOwned: boolean
  countries: Set<string>
  issueType: string | null
  query: string
}

const COUNTRIES = [
  'AD','AT','BE','BG','CY','DE','EE','ES','FI','FR',
  'GR','HR','IE','IT','LT','LU','LV','MC','MT','NL',
  'PT','SI','SK','SM','VA',
]

const ISSUE_LABELS: Record<string, string> = {
  'circulation': 'Circulation',
  'commemo-national': 'Commémo nationale',
  'commemo-common': 'Commémo commune',
  'starter-kit': 'Starter kit',
  'bu-set': 'BU set',
  'proof': 'Proof',
}

type Props = { coins: CatalogCoin[]; generatedAt: string }

export default function CatalogClient({ coins }: Props) {
  const [user, setUser] = useState<User | null>(null)
  const [claims, setClaims] = useState<Set<string>>(new Set())
  const [loadingClaims, setLoadingClaims] = useState(false)
  const [togglingId, setTogglingId] = useState<string | null>(null)
  const [showFilters, setShowFilters] = useState(false)
  const [filters, setFilters] = useState<Filters>({
    notOwned: true,
    countries: new Set(),
    issueType: null,
    query: '',
  })

  useEffect(() => {
    try {
      const stored = localStorage.getItem(LS_KEY)
      if (!stored) { window.location.href = '/'; return }
      const u: User = JSON.parse(stored)
      setUser(u)
      setLoadingClaims(true)
      fetch('/api/me/claims', { headers: { 'x-user-id': u.id } })
        .then(r => r.json())
        .then(data => setClaims(new Set(data.claims as string[])))
        .finally(() => setLoadingClaims(false))
    } catch {}
  }, [])

  async function toggleClaim(eurioId: string) {
    if (!user || togglingId) return
    const next = new Set(claims)
    const claimed = claims.has(eurioId)
    if (claimed) { next.delete(eurioId) } else { next.add(eurioId) }
    setClaims(next)
    setTogglingId(eurioId)
    try {
      await fetch('/api/claim', {
        method: claimed ? 'DELETE' : 'POST',
        headers: { 'Content-Type': 'application/json', 'x-user-id': user.id },
        body: JSON.stringify({ eurio_id: eurioId }),
      })
    } catch {
      // revert on error
      setClaims(claims)
    } finally {
      setTogglingId(null)
    }
  }

  const filtered = coins.filter(c => {
    if (filters.notOwned && c.personal_owned) return false
    if (filters.countries.size > 0 && !filters.countries.has(c.country)) return false
    if (filters.issueType && c.issue_type !== filters.issueType) return false
    if (filters.query) {
      const q = filters.query.toLowerCase()
      const match = c.country.toLowerCase().includes(q)
        || String(c.year).includes(q)
        || (c.theme?.toLowerCase().includes(q) ?? false)
        || (c.design_description?.toLowerCase().includes(q) ?? false)
      if (!match) return false
    }
    return true
  })

  function toggleCountry(c: string) {
    const s = new Set(filters.countries)
    if (s.has(c)) { s.delete(c) } else { s.add(c) }
    setFilters(f => ({ ...f, countries: s }))
  }

  const activeFilterCount = (filters.notOwned ? 1 : 0)
    + filters.countries.size
    + (filters.issueType ? 1 : 0)

  return (
    <main className="mx-auto max-w-md px-4 py-4">
      {/* Header */}
      <div className="mb-3 flex items-center justify-between">
        <span className="text-sm font-medium" style={{ color: 'var(--ink-500)' }}>
          {user ? `${user.emoji} ${user.name}` : '…'}
        </span>
        <span className="text-xs" style={{ color: 'var(--ink-300)' }}>
          {filtered.length} / {coins.length}
        </span>
      </div>

      {/* Search */}
      <div className="relative mb-3">
        <input
          type="search"
          value={filters.query}
          onChange={e => setFilters(f => ({ ...f, query: e.target.value }))}
          placeholder="Rechercher pays, thème, année…"
          className="w-full rounded-xl border px-3 py-2.5 text-sm outline-none"
          style={{ borderColor: 'var(--surface-3)', background: 'white', color: 'var(--ink)' }}
        />
      </div>

      {/* Active filter chips */}
      <div className="mb-3 flex flex-wrap gap-2">
        <button
          onClick={() => setFilters(f => ({ ...f, notOwned: !f.notOwned }))}
          className="flex items-center gap-1 rounded-full px-3 py-1 text-xs font-medium transition-colors"
          style={{
            background: filters.notOwned ? 'var(--indigo-700)' : 'var(--surface-1)',
            color: filters.notOwned ? 'white' : 'var(--ink-500)',
          }}
        >
          Pas chez Raph
          {filters.notOwned && <span className="ml-1 opacity-70">✓</span>}
        </button>

        <button
          onClick={() => setShowFilters(v => !v)}
          className="flex items-center gap-1 rounded-full border px-3 py-1 text-xs font-medium"
          style={{
            borderColor: 'var(--surface-3)',
            background: showFilters ? 'var(--surface-2)' : 'var(--surface-1)',
            color: 'var(--ink-500)',
          }}
        >
          + Filtres
          {activeFilterCount > 1 && (
            <span
              className="flex h-4 w-4 items-center justify-center rounded-full text-[10px]"
              style={{ background: 'var(--indigo-700)', color: 'white' }}
            >
              {activeFilterCount - (filters.notOwned ? 1 : 0)}
            </span>
          )}
        </button>
      </div>

      {/* Filter drawer */}
      {showFilters && (
        <div className="mb-4 rounded-xl border p-4" style={{ borderColor: 'var(--surface-3)', background: 'var(--surface-1)' }}>
          {/* Countries */}
          <p className="mb-2 text-xs font-semibold uppercase tracking-wide" style={{ color: 'var(--ink-400)' }}>Pays</p>
          <div className="mb-4 flex flex-wrap gap-1.5">
            {COUNTRIES.map(c => (
              <button
                key={c}
                onClick={() => toggleCountry(c)}
                className="rounded-full px-2.5 py-1 text-xs font-mono font-medium transition-colors"
                style={{
                  background: filters.countries.has(c) ? 'var(--indigo-700)' : 'var(--surface)',
                  color: filters.countries.has(c) ? 'white' : 'var(--ink-500)',
                }}
              >
                {c}
              </button>
            ))}
          </div>

          {/* Issue type */}
          <p className="mb-2 text-xs font-semibold uppercase tracking-wide" style={{ color: 'var(--ink-400)' }}>Type</p>
          <div className="flex flex-wrap gap-1.5">
            {Object.entries(ISSUE_LABELS).map(([key, label]) => (
              <button
                key={key}
                onClick={() => setFilters(f => ({ ...f, issueType: f.issueType === key ? null : key }))}
                className="rounded-full px-2.5 py-1 text-xs font-medium transition-colors"
                style={{
                  background: filters.issueType === key ? 'var(--indigo-700)' : 'var(--surface)',
                  color: filters.issueType === key ? 'white' : 'var(--ink-500)',
                }}
              >
                {label}
              </button>
            ))}
          </div>
        </div>
      )}

      {/* Coin list */}
      {loadingClaims && (
        <p className="mb-3 text-xs" style={{ color: 'var(--ink-400)' }}>Chargement de tes claims…</p>
      )}

      <div className="flex flex-col gap-2">
        {filtered.map(coin => {
          const claimed = claims.has(coin.eurio_id)
          return (
            <div
              key={coin.eurio_id}
              className="relative flex items-center gap-3 rounded-xl border p-3 transition-colors"
              style={{
                borderColor: claimed ? 'var(--indigo-300)' : 'var(--surface-3)',
                background: claimed ? 'var(--indigo-50)' : 'white',
              }}
            >
              {/* Image */}
              <Link href={`/coins/${coin.eurio_id}`} className="shrink-0">
                {coin.images[0] ? (
                  <img
                    src={coin.images[0]}
                    alt={`${coin.country} ${coin.year}`}
                    className="h-16 w-16 rounded-lg object-cover"
                    loading="lazy"
                  />
                ) : (
                  <div
                    className="flex h-16 w-16 items-center justify-center rounded-lg text-2xl"
                    style={{ background: 'var(--surface-2)' }}
                  >
                    🪙
                  </div>
                )}
              </Link>

              {/* Info */}
              <Link href={`/coins/${coin.eurio_id}`} className="min-w-0 flex-1">
                <p className="text-sm font-semibold" style={{ color: 'var(--ink)' }}>
                  {coin.country} · {coin.year}
                </p>
                <p className="text-xs" style={{ color: 'var(--ink-500)' }}>
                  {coin.issue_type ? ISSUE_LABELS[coin.issue_type] ?? coin.issue_type : ''}
                  {coin.theme ? ` · ${coin.theme}` : ''}
                </p>
                {coin.personal_owned && (
                  <p className="mt-0.5 text-xs font-medium" style={{ color: 'var(--success)' }}>
                    Raph l'a déjà ✅
                  </p>
                )}
              </Link>

              {/* Claim toggle */}
              <button
                onClick={() => toggleClaim(coin.eurio_id)}
                disabled={togglingId === coin.eurio_id}
                className="shrink-0 flex h-8 w-8 items-center justify-center rounded-full transition-all"
                style={{
                  background: claimed ? 'var(--indigo-700)' : 'var(--surface-2)',
                  opacity: togglingId === coin.eurio_id ? 0.5 : 1,
                }}
                title={claimed ? 'Retirer de tes claims' : "Je l'ai !"}
              >
                {claimed ? (
                  <span className="text-sm text-white">✓</span>
                ) : (
                  <span className="text-sm" style={{ color: 'var(--ink-400)' }}>+</span>
                )}
              </button>
            </div>
          )
        })}

        {filtered.length === 0 && (
          <p className="py-8 text-center text-sm" style={{ color: 'var(--ink-400)' }}>
            Aucune pièce ne correspond aux filtres.
          </p>
        )}
      </div>
    </main>
  )
}
