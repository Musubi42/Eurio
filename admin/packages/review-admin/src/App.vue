<script setup lang="ts">
import { onMounted, ref } from 'vue'
import {
  api,
  AuthError,
  clearToken,
  getToken,
  setToken,
  type Flow,
  type Reviewer,
} from './api'

// ─── État ────────────────────────────────────────────────────────────────────
const authed = ref(false)
const tokenInput = ref('')
const loginError = ref('')
const busy = ref(false)

const flow = ref<Flow | null>(null)
const reviewers = ref<Reviewer[]>([])
const loadError = ref('')

const newName = ref('')
const newCode = ref('')
const createError = ref('')
const created = ref<{ name: string; invite_url: string } | null>(null)

const revealed = ref<Set<string>>(new Set())
const copiedKey = ref('')

// ─── Helpers ─────────────────────────────────────────────────────────────────
function slugify(s: string): string {
  return s
    .normalize('NFD')
    .replace(/[̀-ͯ]/g, '')
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, '')
    .slice(0, 12)
}
function genCode(name: string): string {
  const base = slugify(name) || 'ami'
  const suffix = Math.floor(10 + Math.random() * 90)
  return `${base}${suffix}`
}
function maskCode(token: string): string {
  if (token.length <= 5) return token
  return `${token.slice(0, 3)}•••${token.slice(-2)}`
}
function toggleReveal(token: string): void {
  const s = new Set(revealed.value)
  if (s.has(token)) s.delete(token)
  else s.add(token)
  revealed.value = s
}
async function copy(text: string, key: string): Promise<void> {
  await navigator.clipboard.writeText(text)
  copiedKey.value = key
  setTimeout(() => {
    if (copiedKey.value === key) copiedKey.value = ''
  }, 1500)
}
function whatsappLink(url: string): string {
  const msg = `Salut ! Voici ton lien pour reviewer des pièces Eurio : ${url}`
  return `https://wa.me/?text=${encodeURIComponent(msg)}`
}
function relTime(iso: string | null): string {
  if (!iso) return 'jamais'
  const diff = Date.now() - new Date(iso).getTime()
  if (Number.isNaN(diff)) return iso
  const min = Math.floor(diff / 60000)
  if (min < 1) return "à l'instant"
  if (min < 60) return `il y a ${min} min`
  const h = Math.floor(min / 60)
  if (h < 24) return `il y a ${h} h`
  const d = Math.floor(h / 24)
  return `il y a ${d} j`
}

// ─── Auth ────────────────────────────────────────────────────────────────────
async function tryLogin(): Promise<void> {
  const t = tokenInput.value.trim()
  if (!t) return
  setToken(t)
  loginError.value = ''
  busy.value = true
  try {
    await api.flow()
    authed.value = true
    await refresh()
  } catch (e) {
    clearToken()
    loginError.value = e instanceof AuthError ? 'Token refusé.' : (e as Error).message
  } finally {
    busy.value = false
  }
}
function logout(): void {
  clearToken()
  authed.value = false
  tokenInput.value = ''
  flow.value = null
  reviewers.value = []
}

// ─── Données ─────────────────────────────────────────────────────────────────
async function refresh(): Promise<void> {
  loadError.value = ''
  try {
    const [f, r] = await Promise.all([api.flow(), api.listReviewers()])
    flow.value = f
    reviewers.value = r.reviewers
  } catch (e) {
    if (e instanceof AuthError) {
      authed.value = false
      return
    }
    loadError.value = (e as Error).message
  }
}

async function create(): Promise<void> {
  createError.value = ''
  created.value = null
  const name = newName.value.trim()
  if (!name) {
    createError.value = 'Nom requis.'
    return
  }
  const code = newCode.value.trim() || genCode(name)
  busy.value = true
  try {
    const res = await api.createReviewer(code, name)
    created.value = { name: res.name, invite_url: res.invite_url }
    newName.value = ''
    newCode.value = ''
    await refresh()
  } catch (e) {
    createError.value = (e as Error).message
  } finally {
    busy.value = false
  }
}

async function revoke(r: Reviewer): Promise<void> {
  if (!confirm(`Révoquer ${r.display_name} ? Il ne pourra plus se connecter.`)) return
  await api.revokeReviewer(r.token)
  await refresh()
}
async function reactivate(r: Reviewer): Promise<void> {
  await api.reactivateReviewer(r.token)
  await refresh()
}
function openAs(r: Reviewer): void {
  window.open(r.invite_url, '_blank', 'noopener')
}

onMounted(async () => {
  if (getToken()) {
    authed.value = true
    await refresh()
  }
})
</script>

<template>
  <!-- ─── Login ───────────────────────────────────────────────────────── -->
  <main v-if="!authed" class="login">
    <form class="login-card" @submit.prevent="tryLogin">
      <h1>Eurio · Régie review</h1>
      <p class="muted">Colle le token admin pour entrer.</p>
      <input
        v-model="tokenInput"
        type="password"
        placeholder="REVIEW_ADMIN_TOKEN"
        autocomplete="off"
        autofocus
      />
      <button type="submit" :disabled="busy || !tokenInput.trim()">
        {{ busy ? '…' : 'Entrer' }}
      </button>
      <p v-if="loginError" class="error">{{ loginError }}</p>
    </form>
  </main>

  <!-- ─── Dashboard ───────────────────────────────────────────────────── -->
  <main v-else class="dash">
    <header class="topbar">
      <h1>Eurio · Régie review</h1>
      <div class="topbar-actions">
        <button class="ghost" :disabled="busy" @click="refresh">Rafraîchir</button>
        <button class="ghost" @click="logout">Déconnexion</button>
      </div>
    </header>

    <p v-if="loadError" class="error block">{{ loadError }}</p>

    <!-- Flux -->
    <section v-if="flow" class="flow">
      <div class="stat">
        <span class="stat-num">{{ flow.pending }}</span>
        <span class="stat-lbl">en attente de review</span>
      </div>
      <div class="stat">
        <span class="stat-num">{{ flow.awaiting_reconcile }}</span>
        <span class="stat-lbl">à réconcilier (Mac)</span>
      </div>
      <div class="stat">
        <span class="stat-num small">{{ relTime(flow.last_publish_at) }}</span>
        <span class="stat-lbl">dernier publish</span>
      </div>
      <div class="stat">
        <span class="stat-num small">{{ relTime(flow.last_reconcile_at) }}</span>
        <span class="stat-lbl">dernier reconcile</span>
      </div>
    </section>

    <!-- Créer un code -->
    <section class="card">
      <h2>Inviter un reviewer</h2>
      <form class="create" @submit.prevent="create">
        <label>
          Nom
          <input v-model="newName" placeholder="Paolo" />
        </label>
        <label>
          Code
          <div class="code-row">
            <input v-model="newCode" :placeholder="genCode(newName) || 'auto'" />
            <button type="button" class="ghost" @click="newCode = genCode(newName)">
              ↻ auto
            </button>
          </div>
        </label>
        <button type="submit" class="primary" :disabled="busy || !newName.trim()">Créer</button>
      </form>
      <p v-if="createError" class="error">{{ createError }}</p>

      <div v-if="created" class="invite">
        <p>
          Lien prêt à partager pour <strong>{{ created.name }}</strong> :
        </p>
        <div class="invite-url">
          <code>{{ created.invite_url }}</code>
        </div>
        <div class="invite-actions">
          <button class="primary" @click="copy(created.invite_url, 'created')">
            {{ copiedKey === 'created' ? '✓ Copié' : 'Copier le lien' }}
          </button>
          <a class="btn whatsapp" :href="whatsappLink(created.invite_url)" target="_blank" rel="noopener">
            Partager via WhatsApp
          </a>
        </div>
      </div>
    </section>

    <!-- Tableau reviewers -->
    <section class="card">
      <h2>Reviewers <span class="muted">({{ reviewers.length }})</span></h2>
      <table v-if="reviewers.length" class="reviewers">
        <thead>
          <tr>
            <th>Nom</th>
            <th>Code</th>
            <th class="num">Total</th>
            <th class="num">7 j</th>
            <th class="num">Lease</th>
            <th>Activité</th>
            <th class="actions">Actions</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="r in reviewers" :key="r.token" :class="{ inactive: !r.is_active }">
            <td>{{ r.display_name }}</td>
            <td>
              <button class="code" :title="revealed.has(r.token) ? 'Masquer' : 'Révéler'" @click="toggleReveal(r.token)">
                {{ revealed.has(r.token) ? r.token : maskCode(r.token) }}
              </button>
              <button class="link" @click="copy(r.invite_url, r.token)">
                {{ copiedKey === r.token ? '✓' : 'copier lien' }}
              </button>
            </td>
            <td class="num">{{ r.total }}</td>
            <td class="num">{{ r.last7 }}</td>
            <td class="num">{{ r.in_flight || '' }}</td>
            <td>{{ relTime(r.last_seen_at) }}</td>
            <td class="actions">
              <button class="link" @click="openAs(r)">ouvrir ↗</button>
              <button v-if="r.is_active" class="link danger" @click="revoke(r)">révoquer</button>
              <button v-else class="link" @click="reactivate(r)">réactiver</button>
            </td>
          </tr>
        </tbody>
      </table>
      <p v-else class="muted">Aucun reviewer pour l'instant.</p>
    </section>
  </main>
</template>

<style scoped>
h1 {
  font-size: 1.15rem;
  margin: 0;
}
h2 {
  font-size: 1rem;
  margin: 0 0 0.75rem;
}
.muted {
  color: var(--ink-400);
  font-weight: 400;
}
.error {
  color: var(--danger);
  font-size: 0.875rem;
}
.error.block {
  margin: 1rem auto;
  max-width: 880px;
}

/* Login */
.login {
  min-height: 100vh;
  display: grid;
  place-items: center;
  padding: 1rem;
}
.login-card {
  background: var(--paper, #fff);
  border-radius: var(--radius-xl);
  box-shadow: var(--shadow-card);
  padding: 2rem;
  width: 100%;
  max-width: 360px;
  display: flex;
  flex-direction: column;
  gap: 0.75rem;
}

/* Dashboard */
.dash {
  max-width: 880px;
  margin: 0 auto;
  padding: 1.25rem 1rem 4rem;
}
.topbar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 1.25rem;
}
.topbar-actions {
  display: flex;
  gap: 0.5rem;
}

/* Flux */
.flow {
  display: grid;
  grid-template-columns: repeat(4, 1fr);
  gap: 0.75rem;
  margin-bottom: 1.25rem;
}
.stat {
  background: var(--paper, #fff);
  border-radius: var(--radius-lg);
  box-shadow: var(--shadow-sm);
  padding: 0.9rem 1rem;
  display: flex;
  flex-direction: column;
  gap: 0.2rem;
}
.stat-num {
  font-size: 1.6rem;
  font-weight: 700;
  color: var(--indigo-600);
}
.stat-num.small {
  font-size: 1rem;
}
.stat-lbl {
  font-size: 0.75rem;
  color: var(--ink-400);
}

/* Cards */
.card {
  background: var(--paper, #fff);
  border-radius: var(--radius-xl);
  box-shadow: var(--shadow-sm);
  padding: 1.25rem;
  margin-bottom: 1.25rem;
}
.create {
  display: flex;
  gap: 1rem;
  align-items: flex-end;
  flex-wrap: wrap;
}
.create label {
  display: flex;
  flex-direction: column;
  gap: 0.3rem;
  font-size: 0.8rem;
  color: var(--ink-400);
}
.code-row {
  display: flex;
  gap: 0.4rem;
}

/* Invite result */
.invite {
  margin-top: 1rem;
  padding-top: 1rem;
  border-top: 1px solid var(--gray-200);
}
.invite-url {
  background: var(--indigo-50);
  border-radius: var(--radius-md);
  padding: 0.6rem 0.8rem;
  overflow-x: auto;
}
.invite-url code {
  font-family: var(--font-mono, monospace);
  font-size: 0.9rem;
  color: var(--indigo-700);
}
.invite-actions {
  display: flex;
  gap: 0.5rem;
  margin-top: 0.75rem;
}

/* Table */
.reviewers {
  width: 100%;
  border-collapse: collapse;
  font-size: 0.9rem;
}
.reviewers th,
.reviewers td {
  text-align: left;
  padding: 0.55rem 0.5rem;
  border-bottom: 1px solid var(--gray-100);
}
.reviewers th {
  font-size: 0.72rem;
  text-transform: uppercase;
  letter-spacing: 0.04em;
  color: var(--ink-400);
}
.reviewers .num {
  text-align: right;
  font-variant-numeric: tabular-nums;
}
.reviewers .actions {
  text-align: right;
  white-space: nowrap;
}
tr.inactive td {
  opacity: 0.45;
}

/* Controls */
input {
  font: inherit;
  padding: 0.5rem 0.65rem;
  border: 1px solid var(--gray-300);
  border-radius: var(--radius-md);
  background: var(--paper, #fff);
  color: var(--ink);
}
input:focus {
  outline: 2px solid var(--indigo-400);
  outline-offset: 0;
}
button,
.btn {
  font: inherit;
  cursor: pointer;
  border: none;
  border-radius: var(--radius-md);
  padding: 0.5rem 0.85rem;
  background: var(--gray-200);
  color: var(--ink);
  text-decoration: none;
  display: inline-block;
}
button:disabled {
  opacity: 0.5;
  cursor: default;
}
button.primary,
.btn.primary {
  background: var(--indigo-600);
  color: #fff;
}
.btn.whatsapp {
  background: #25d366;
  color: #08431f;
}
button.ghost {
  background: transparent;
  border: 1px solid var(--gray-300);
}
button.code {
  background: var(--gray-100);
  font-family: var(--font-mono, monospace);
  padding: 0.2rem 0.45rem;
  font-size: 0.85rem;
}
button.link {
  background: transparent;
  color: var(--indigo-600);
  padding: 0.2rem 0.4rem;
  font-size: 0.82rem;
}
button.link.danger {
  color: var(--danger);
}

@media (max-width: 640px) {
  .flow {
    grid-template-columns: repeat(2, 1fr);
  }
}
</style>
