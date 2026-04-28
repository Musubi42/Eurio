'use client'

import { useEffect, useState } from 'react'
import Link from 'next/link'
import type { CatalogCoin } from '@/types/catalog'

const LS_KEY = 'eurio_loan_user'
type User = { id: string; name: string; emoji: string }

const ISSUE_LABELS: Record<string, string> = {
  'circulation': 'Circulation',
  'commemo-national': 'Commémo nationale',
  'commemo-common': 'Commémo commune',
  'starter-kit': 'Starter kit',
  'bu-set': 'BU set',
  'proof': 'Proof',
}

export default function CoinDetailClient({ coin }: { coin: CatalogCoin }) {
  const [user, setUser] = useState<User | null>(null)
  const [claimed, setClaimed] = useState(false)
  const [toggling, setToggling] = useState(false)
  const [imgIdx, setImgIdx] = useState(0)

  useEffect(() => {
    try {
      const stored = localStorage.getItem(LS_KEY)
      if (!stored) { window.location.href = '/'; return }
      const u: User = JSON.parse(stored)
      setUser(u)
      fetch('/api/me/claims', { headers: { 'x-user-id': u.id } })
        .then(r => r.json())
        .then(data => setClaimed((data.claims as string[]).includes(coin.eurio_id)))
    } catch {}
  }, [coin.eurio_id])

  async function toggleClaim() {
    if (!user || toggling) return
    setToggling(true)
    const next = !claimed
    setClaimed(next)
    try {
      await fetch('/api/claim', {
        method: next ? 'POST' : 'DELETE',
        headers: { 'Content-Type': 'application/json', 'x-user-id': user.id },
        body: JSON.stringify({ eurio_id: coin.eurio_id }),
      })
    } catch {
      setClaimed(claimed)
    } finally {
      setToggling(false)
    }
  }

  return (
    <main className="mx-auto max-w-md px-4 py-4">
      <Link href="/catalog" className="mb-4 inline-flex items-center gap-1 text-sm" style={{ color: 'var(--ink-500)' }}>
        ← Retour
      </Link>

      {/* Images */}
      {coin.images.length > 0 && (
        <div className="mb-4">
          <div className="aspect-square overflow-hidden rounded-2xl" style={{ background: 'var(--surface-2)' }}>
            <img
              src={coin.images[imgIdx] ?? coin.images[0]}
              alt={`${coin.country} ${coin.year}`}
              className="h-full w-full object-contain"
            />
          </div>
          {coin.images.length > 1 && (
            <div className="mt-2 flex justify-center gap-1.5">
              {coin.images.map((_, i) => (
                <button
                  key={i}
                  onClick={() => setImgIdx(i)}
                  className="h-2 w-2 rounded-full transition-colors"
                  style={{ background: i === imgIdx ? 'var(--indigo-700)' : 'var(--surface-3)' }}
                />
              ))}
            </div>
          )}
        </div>
      )}

      {/* Title */}
      <h1 className="mb-0.5 text-xl font-bold" style={{ color: 'var(--ink)' }}>
        {coin.country} · {coin.year} · 2 €
      </h1>
      <p className="mb-4 text-sm" style={{ color: 'var(--ink-500)' }}>
        {coin.issue_type ? ISSUE_LABELS[coin.issue_type] ?? coin.issue_type : ''}
      </p>

      {/* Claim toggle */}
      <button
        onClick={toggleClaim}
        disabled={toggling}
        className="mb-6 flex w-full items-center justify-between rounded-xl border px-4 py-3 text-sm font-medium transition-all"
        style={{
          borderColor: claimed ? 'var(--indigo-700)' : 'var(--surface-3)',
          background: claimed ? 'var(--indigo-50)' : 'white',
          color: claimed ? 'var(--indigo-700)' : 'var(--ink)',
          opacity: toggling ? 0.6 : 1,
        }}
      >
        <span>{claimed ? "✓ Tu l'as — merci !" : "☐ Tu l'as ?"}</span>
        <span className="text-lg">{claimed ? '✓' : '+'}</span>
      </button>

      {/* Details */}
      {coin.design_description && (
        <section className="mb-4">
          <h2 className="mb-1 text-sm font-semibold" style={{ color: 'var(--ink)' }}>À propos</h2>
          <p className="text-sm leading-relaxed" style={{ color: 'var(--ink-500)' }}>{coin.design_description}</p>
        </section>
      )}

      {coin.mintage && (
        <p className="mb-4 text-sm" style={{ color: 'var(--ink-500)' }}>
          Tirage : {coin.mintage.toLocaleString('fr-FR')}
        </p>
      )}

      {/* Market prices */}
      {coin.market_prices && (coin.market_prices.ebay_median ?? coin.market_prices.monnaie_de_paris) && (
        <section className="mb-4">
          <h2 className="mb-2 text-sm font-semibold" style={{ color: 'var(--ink)' }}>Cote</h2>
          <div className="flex flex-col gap-1">
            {coin.market_prices.ebay_median != null && (
              <p className="text-sm" style={{ color: 'var(--ink-500)' }}>
                · eBay (médiane) : {coin.market_prices.ebay_median.toFixed(2)} €
              </p>
            )}
            {coin.market_prices.monnaie_de_paris != null && (
              <p className="text-sm" style={{ color: 'var(--ink-500)' }}>
                · Monnaie de Paris : {coin.market_prices.monnaie_de_paris.toFixed(2)} €
              </p>
            )}
          </div>
        </section>
      )}

      {/* External links */}
      {(coin.cross_refs.numista_id || coin.cross_refs.wikipedia) && (
        <section>
          <h2 className="mb-2 text-sm font-semibold" style={{ color: 'var(--ink)' }}>En savoir plus</h2>
          <div className="flex flex-col gap-1">
            {coin.cross_refs.numista_id && (
              <a
                href={`https://en.numista.com/catalogue/pieces${coin.cross_refs.numista_id}.html`}
                target="_blank"
                rel="noopener noreferrer"
                className="text-sm underline"
                style={{ color: 'var(--indigo-600)' }}
              >
                → Numista
              </a>
            )}
            {coin.cross_refs.wikipedia && (
              <a
                href={coin.cross_refs.wikipedia}
                target="_blank"
                rel="noopener noreferrer"
                className="text-sm underline"
                style={{ color: 'var(--indigo-600)' }}
              >
                → Wikipédia
              </a>
            )}
          </div>
        </section>
      )}
    </main>
  )
}
