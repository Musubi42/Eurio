'use client'

import { useEffect, useState } from 'react'
import { useRouter } from 'next/navigation'
import { nanoid } from 'nanoid'

const EMOJIS = ['🦊', '🐢', '🦉', '🐙', '🐝', '🦋', '🌻', '🍒', '🍑', '🌶', '⚡', '🌙']
const LS_KEY = 'eurio_loan_user'

export default function HomePage() {
  const router = useRouter()
  const [name, setName] = useState('')
  const [emoji, setEmoji] = useState('')
  const [submitting, setSubmitting] = useState(false)
  const [error, setError] = useState('')
  const [checked, setChecked] = useState(false)

  useEffect(() => {
    try {
      const stored = localStorage.getItem(LS_KEY)
      if (stored) {
        router.replace('/catalog')
        return
      }
    } catch {}
    setChecked(true)
  }, [router])

  if (!checked) return null

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault()
    if (!name.trim() || !emoji) { setError('Choisis un prénom et un emoji'); return }
    setSubmitting(true)
    setError('')
    try {
      const res = await fetch('/api/users', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ name: name.trim(), emoji }),
      })
      if (!res.ok) throw new Error('Erreur serveur')
      const user = await res.json()
      localStorage.setItem(LS_KEY, JSON.stringify(user))
      router.push('/catalog')
    } catch {
      setError('Une erreur est survenue, réessaie.')
      setSubmitting(false)
    }
  }

  return (
    <main className="flex min-h-screen items-start justify-center px-4 pt-16">
      <div className="w-full max-w-sm">
        <div className="mb-8">
          <h1 className="text-xl font-bold mb-1" style={{ color: 'var(--indigo-700)' }}>
            Eurio · Prête-moi tes 2€
          </h1>
          <p className="text-sm leading-relaxed" style={{ color: 'var(--ink-500)' }}>
            Raphaël collectionne des pièces de 2€ pour entraîner son app de scan.
            Dis-lui lesquelles tu as — si tu veux bien lui en prêter quelques-unes ce serait top !
          </p>
        </div>

        <form onSubmit={handleSubmit} className="flex flex-col gap-5">
          <div>
            <label className="block text-sm font-medium mb-1.5" style={{ color: 'var(--ink)' }}>
              Comment tu t'appelles ?
            </label>
            <input
              type="text"
              value={name}
              onChange={e => setName(e.target.value)}
              placeholder="Thomas"
              maxLength={40}
              className="w-full rounded-lg border px-3 py-2.5 text-sm outline-none transition-colors"
              style={{
                borderColor: 'var(--surface-3)',
                background: 'white',
                color: 'var(--ink)',
              }}
              autoFocus
            />
          </div>

          <div>
            <p className="text-sm font-medium mb-2" style={{ color: 'var(--ink)' }}>
              Choisis un emoji :
            </p>
            <div className="grid grid-cols-6 gap-2">
              {EMOJIS.map(e => (
                <button
                  key={e}
                  type="button"
                  onClick={() => setEmoji(e)}
                  className="flex h-11 w-full items-center justify-center rounded-xl text-xl transition-all"
                  style={{
                    background: emoji === e ? 'var(--indigo-700)' : 'var(--surface-1)',
                    transform: emoji === e ? 'scale(1.1)' : 'scale(1)',
                    outline: emoji === e ? '2px solid var(--indigo-700)' : 'none',
                  }}
                >
                  {e}
                </button>
              ))}
            </div>
          </div>

          {error && (
            <p className="text-sm" style={{ color: 'var(--danger)' }}>{error}</p>
          )}

          <button
            type="submit"
            disabled={submitting}
            className="w-full rounded-xl py-3 text-sm font-semibold transition-opacity"
            style={{
              background: 'var(--indigo-700)',
              color: 'white',
              opacity: submitting ? 0.6 : 1,
            }}
          >
            {submitting ? 'Un instant…' : 'On y va →'}
          </button>
        </form>
      </div>
    </main>
  )
}
