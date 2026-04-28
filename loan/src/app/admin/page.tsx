'use client'

import { useEffect, useState } from 'react'
import type { KVUser } from '@/lib/kv'

type Entry = {
  user: KVUser
  claims: string[]
  lent: string[]
}

// minimal coin label from eurio_id (e.g. FR-2024-EU-CIRC → FR 2024)
function labelFromId(id: string): string {
  const parts = id.split('-')
  return parts.slice(0, 2).join(' ')
}

export default function AdminPage() {
  const [entries, setEntries] = useState<Entry[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [expanded, setExpanded] = useState<Set<string>>(new Set())
  const [toggling, setToggling] = useState<string | null>(null)

  useEffect(() => {
    fetch('/api/admin/overview')
      .then(r => { if (!r.ok) throw new Error('Unauthorized'); return r.json() })
      .then(data => { setEntries(data); setLoading(false) })
      .catch(e => { setError(e.message); setLoading(false) })
  }, [])

  function toggleExpand(userId: string) {
    setExpanded(prev => {
      const s = new Set(prev)
      if (s.has(userId)) s.delete(userId) else s.add(userId)
      return s
    })
  }

  async function toggleLent(userId: string, eurioId: string, currentlyLent: boolean) {
    const key = `${userId}:${eurioId}`
    if (toggling === key) return
    setToggling(key)

    // Optimistic
    setEntries(prev => prev.map(e => {
      if (e.user.id !== userId) return e
      const lent = currentlyLent
        ? e.lent.filter(id => id !== eurioId)
        : [...e.lent, eurioId]
      return { ...e, lent }
    }))

    try {
      await fetch('/api/admin/lent', {
        method: currentlyLent ? 'DELETE' : 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ userId, eurio_id: eurioId }),
      })
    } catch {
      // revert
      setEntries(prev => prev.map(e => {
        if (e.user.id !== userId) return e
        const lent = currentlyLent
          ? [...e.lent, eurioId]
          : e.lent.filter(id => id !== eurioId)
        return { ...e, lent }
      }))
    } finally {
      setToggling(null)
    }
  }

  const totalClaims = entries.reduce((s, e) => s + e.claims.length, 0)
  const totalLent = entries.reduce((s, e) => s + e.lent.length, 0)

  if (loading) return <main className="p-8 text-sm" style={{ color: 'var(--ink-400)' }}>Chargement…</main>
  if (error) return <main className="p-8 text-sm" style={{ color: 'var(--danger)' }}>{error}</main>

  return (
    <main className="mx-auto max-w-2xl px-4 py-6">
      <h1 className="mb-1 text-lg font-bold" style={{ color: 'var(--indigo-700)' }}>
        Loan admin
      </h1>
      <p className="mb-6 text-sm" style={{ color: 'var(--ink-500)' }}>
        {entries.length} amis · {totalClaims} claims · {totalLent}/{totalClaims} prêtées
      </p>

      <div className="flex flex-col gap-2">
        {entries.map(({ user, claims, lent }) => {
          const isOpen = expanded.has(user.id)
          return (
            <div key={user.id} className="rounded-xl border overflow-hidden" style={{ borderColor: 'var(--surface-3)' }}>
              <button
                onClick={() => toggleExpand(user.id)}
                className="flex w-full items-center justify-between px-4 py-3"
                style={{ background: 'var(--surface-1)' }}
              >
                <span className="text-sm font-semibold" style={{ color: 'var(--ink)' }}>
                  {isOpen ? '▼' : '▶'} {user.emoji} {user.name}
                </span>
                <span className="text-xs" style={{ color: lent.length > 0 ? 'var(--success)' : 'var(--ink-400)' }}>
                  {lent.length} / {claims.length} prêtées
                </span>
              </button>

              {isOpen && (
                <div className="border-t" style={{ borderColor: 'var(--surface-3)' }}>
                  {claims.length === 0 && (
                    <p className="px-4 py-3 text-sm" style={{ color: 'var(--ink-400)' }}>Aucun claim.</p>
                  )}
                  {claims.map(eurioId => {
                    const isLent = lent.includes(eurioId)
                    const key = `${user.id}:${eurioId}`
                    return (
                      <label
                        key={eurioId}
                        className="flex cursor-pointer items-center gap-3 px-4 py-2.5 text-sm transition-colors"
                        style={{
                          background: isLent ? 'var(--success-soft)' : 'white',
                          borderBottom: '1px solid var(--surface-2)',
                        }}
                      >
                        <input
                          type="checkbox"
                          checked={isLent}
                          disabled={toggling === key}
                          onChange={() => toggleLent(user.id, eurioId, isLent)}
                          className="h-4 w-4 cursor-pointer accent-green-600"
                        />
                        <span style={{ color: 'var(--ink)', fontFamily: 'monospace', fontSize: '11px' }}>
                          {eurioId}
                        </span>
                        <span className="text-xs" style={{ color: 'var(--ink-400)' }}>
                          {labelFromId(eurioId)}
                        </span>
                        {isLent && <span className="ml-auto text-xs" style={{ color: 'var(--success)' }}>prêtée</span>}
                      </label>
                    )
                  })}
                </div>
              )}
            </div>
          )
        })}

        {entries.length === 0 && (
          <p className="py-8 text-center text-sm" style={{ color: 'var(--ink-400)' }}>
            Aucun ami n'a encore déclaré de pièces.
          </p>
        )}
      </div>
    </main>
  )
}
