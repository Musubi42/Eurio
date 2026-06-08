<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { AuthError, api, type ReviewItem } from './api'

type Phase = 'boot' | 'auth' | 'loading' | 'review' | 'celebrate' | 'error'

const phase = ref<Phase>('boot')
const name = ref('')
const queue = ref<ReviewItem[]>([])
const sessionCount = ref(0)
const total = ref(0)
const errorMsg = ref('')
const codeInput = ref('')
const authError = ref('')
const acting = ref(false)

const current = computed<ReviewItem | null>(() => queue.value[0] ?? null)

// ─── Auth ──────────────────────────────────────────────────────────────────

async function authenticate(token: string) {
  authError.value = ''
  try {
    const res = await api.auth(token)
    name.value = res.name
    cleanUrl()
    await startBatch()
  } catch {
    authError.value = 'Code inconnu. Réessaie ou demande ton lien.'
    phase.value = 'auth'
  }
}

function cleanUrl() {
  if (window.location.search) {
    window.history.replaceState({}, '', window.location.pathname)
  }
}

function submitCode() {
  const t = codeInput.value.trim()
  if (t) void authenticate(t)
}

// ─── Batch ─────────────────────────────────────────────────────────────────

async function startBatch() {
  phase.value = 'loading'
  try {
    const res = await api.claim()
    queue.value = res.items
    if (queue.value.length === 0) {
      await refreshStats()
      phase.value = 'celebrate'
    } else {
      phase.value = 'review'
    }
  } catch (e) {
    handleError(e)
  }
}

async function refreshStats() {
  try {
    total.value = (await api.stats()).total
  } catch {
    /* non bloquant */
  }
}

// ─── Décisions ───────────────────────────────────────────────────────────────

function advance() {
  queue.value = queue.value.slice(1)
  if (queue.value.length === 0) {
    void refreshStats().then(() => (phase.value = 'celebrate'))
  }
}

async function accept(eurioId: string) {
  const item = current.value
  if (!item || acting.value) return
  acting.value = true
  try {
    await api.decide(item.id, { action: 'accept', eurio_id: eurioId, face: 'obverse' })
    sessionCount.value++
    advance()
  } catch (e) {
    // 409 = item repris/expiré : on passe simplement au suivant.
    if (e instanceof AuthError) return handleError(e)
    advance()
  } finally {
    acting.value = false
  }
}

async function reject() {
  const item = current.value
  if (!item || acting.value) return
  acting.value = true
  try {
    await api.decide(item.id, { action: 'reject', quality_reason: 'not_a_coin' })
    sessionCount.value++
    advance()
  } catch (e) {
    if (e instanceof AuthError) return handleError(e)
    advance()
  } finally {
    acting.value = false
  }
}

async function skip() {
  const item = current.value
  if (!item || acting.value) return
  acting.value = true
  try {
    await api.skip(item.id)
  } catch (e) {
    if (e instanceof AuthError) return handleError(e)
  } finally {
    advance()
    acting.value = false
  }
}

function handleError(e: unknown) {
  if (e instanceof AuthError) {
    phase.value = 'auth'
    return
  }
  errorMsg.value = e instanceof Error ? e.message : String(e)
  phase.value = 'error'
}

// ─── Boot ────────────────────────────────────────────────────────────────────

onMounted(async () => {
  const token = new URLSearchParams(window.location.search).get('u')
  if (token) return authenticate(token)
  try {
    name.value = (await api.me()).name
    await startBatch()
  } catch {
    phase.value = 'auth'
  }
})
</script>

<template>
  <main class="wrap">
    <!-- Auth -->
    <div v-if="phase === 'auth'" class="card-center">
      <h1 class="brand">Eurio · Review</h1>
      <p class="muted">Entre ton code pour commencer.</p>
      <input
        v-model="codeInput"
        class="code-input"
        placeholder="Ton code"
        @keyup.enter="submitCode"
      />
      <button class="btn-primary" @click="submitCode">Commencer</button>
      <p v-if="authError" class="err">{{ authError }}</p>
    </div>

    <!-- Loading -->
    <div v-else-if="phase === 'loading' || phase === 'boot'" class="card-center">
      <p class="muted">Chargement…</p>
    </div>

    <!-- Error -->
    <div v-else-if="phase === 'error'" class="card-center">
      <p class="err">{{ errorMsg }}</p>
      <button class="btn-primary" @click="startBatch">Réessayer</button>
    </div>

    <!-- Celebrate -->
    <div v-else-if="phase === 'celebrate'" class="card-center">
      <div class="party">🎉</div>
      <h2 class="brand">Bien joué {{ name }} !</h2>
      <p class="muted">
        {{ sessionCount }} pièce{{ sessionCount > 1 ? 's' : '' }} reviewée{{ sessionCount > 1 ? 's' : '' }}
        cette session.
        <template v-if="total"> ({{ total }} au total)</template>
      </p>
      <button class="btn-primary" @click="sessionCount = 0; startBatch()">Encore 10</button>
    </div>

    <!-- Review -->
    <div v-else-if="phase === 'review' && current" class="review">
      <header class="topbar">
        <span class="who">{{ name }}</span>
        <span class="counter">{{ sessionCount }} faites · {{ queue.length }} restantes</span>
      </header>

      <div class="crop">
        <img v-if="current.crop_url" :src="current.crop_url" alt="pièce" />
        <span v-else class="muted">image indisponible</span>
      </div>

      <p v-if="current.listing_title" class="listing">{{ current.listing_title }}</p>

      <p class="prompt">Quelle pièce est-ce ?</p>
      <div class="candidates">
        <button
          v-for="c in current.candidates"
          :key="c.eurio_id"
          class="candidate"
          :disabled="acting"
          @click="accept(c.eurio_id)"
        >
          <img v-if="c.thumb_url" :src="c.thumb_url" alt="" />
          <span class="cand-label">
            <strong>{{ c.label }}</strong>
            <small v-if="c.denomination">{{ c.denomination }}</small>
          </span>
        </button>
        <p v-if="!current.candidates.length" class="muted">
          Aucune suggestion — passe si tu n'es pas sûr·e.
        </p>
      </div>

      <footer class="actions">
        <button class="btn-ghost" :disabled="acting" @click="reject">❌ Pas une pièce</button>
        <button class="btn-ghost" :disabled="acting" @click="skip">⏭ Passer</button>
      </footer>
    </div>
  </main>
</template>

<style scoped>
.wrap {
  min-height: 100%;
  display: flex;
  flex-direction: column;
  align-items: center;
  padding: 16px;
}

.card-center {
  margin: auto;
  background: var(--surface);
  border-radius: 20px;
  padding: 32px 24px;
  max-width: 420px;
  width: 100%;
  text-align: center;
  box-shadow: 0 12px 40px rgba(0, 0, 0, 0.25);
}

.brand {
  color: var(--indigo-700);
  margin: 0 0 8px;
  font-weight: 700;
}
.muted {
  color: var(--ink-500);
  margin: 4px 0 16px;
}
.err {
  color: var(--danger);
  margin-top: 12px;
}
.party {
  font-size: 56px;
}

.code-input {
  width: 100%;
  padding: 14px;
  font-size: 18px;
  border: 1px solid var(--surface-3);
  border-radius: 12px;
  margin-bottom: 12px;
  text-align: center;
}

.btn-primary {
  background: var(--indigo-700);
  color: #fff;
  border: 0;
  border-radius: 12px;
  padding: 14px 20px;
  font-size: 16px;
  font-weight: 600;
  cursor: pointer;
  width: 100%;
}
.btn-primary:active {
  transform: scale(0.98);
}

/* Review */
.review {
  background: var(--surface);
  border-radius: 20px;
  width: 100%;
  max-width: 480px;
  margin: auto;
  padding: 16px;
  box-shadow: 0 12px 40px rgba(0, 0, 0, 0.25);
}
.topbar {
  display: flex;
  justify-content: space-between;
  align-items: center;
  font-size: 13px;
  color: var(--ink-500);
  margin-bottom: 12px;
}
.who {
  font-weight: 600;
  color: var(--indigo-700);
}
.counter {
  font-variant-numeric: tabular-nums;
}

.crop {
  aspect-ratio: 1;
  background: var(--surface-2);
  border-radius: 14px;
  display: flex;
  align-items: center;
  justify-content: center;
  overflow: hidden;
}
.crop img {
  max-width: 100%;
  max-height: 100%;
  object-fit: contain;
}
.listing {
  font-size: 13px;
  color: var(--ink-500);
  margin: 10px 2px;
  text-align: center;
}
.prompt {
  font-weight: 600;
  margin: 12px 2px 8px;
}

.candidates {
  display: flex;
  flex-direction: column;
  gap: 8px;
}
.candidate {
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 8px 10px;
  border: 1px solid var(--surface-3);
  border-radius: 12px;
  background: var(--surface-1);
  cursor: pointer;
  text-align: left;
  width: 100%;
}
.candidate:active {
  transform: scale(0.99);
}
.candidate img {
  width: 44px;
  height: 44px;
  object-fit: contain;
  border-radius: 8px;
  background: #fff;
}
.cand-label {
  display: flex;
  flex-direction: column;
}
.cand-label small {
  color: var(--ink-500);
}

.actions {
  display: flex;
  gap: 8px;
  margin-top: 16px;
}
.btn-ghost {
  flex: 1;
  padding: 12px;
  border: 1px solid var(--surface-3);
  border-radius: 12px;
  background: transparent;
  font-size: 14px;
  cursor: pointer;
}
.btn-ghost:active {
  transform: scale(0.98);
}
button:disabled {
  opacity: 0.5;
  cursor: default;
}
</style>
