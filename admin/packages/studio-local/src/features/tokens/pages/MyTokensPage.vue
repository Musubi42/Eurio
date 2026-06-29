<script setup lang="ts">
/**
 * Mes tokens — gestion des Personal Access Tokens du user courant.
 * Scope requis : `tokens:manage_own` (toujours présent puisque tous les
 * rôles owner/admin/reviewer l'ont).
 *
 * UX clés :
 * - Affichage du clair via modale dédiée, **une seule fois**, copy-to-clipboard.
 * - Pas de persistance du clair (jamais localStorage). À la fermeture, c'est perdu.
 * - Mobile-friendly : table → cards en <640px (cf. ResponsiveTable plus tard).
 */
import { computed, onMounted, reactive, ref } from 'vue'

import { EurioApiError } from '@/shared/api/eurio-api'
import { tokensApi, type CreateTokenResponse, type TokenRow } from '../api/tokens'
import { useEurioSession } from '@/stores/eurio-session'

const session = useEurioSession()

const tokens = ref<TokenRow[]>([])
const loading = ref(false)
const errorMsg = ref('')

const showCreateModal = ref(false)
const creating = ref(false)
const createError = ref('')
const newToken = ref<CreateTokenResponse | null>(null)
const copied = ref(false)

const form = reactive({
  name: '',
  scopes: new Set<string>(),
  expiresInDays: '' as string,
})

// Scopes disponibles = scopes effectifs du user (impossible d'aller au-delà côté API).
// On retire `audit:write` qui est de toute façon refusé.
const availableScopes = computed(() =>
  (session.principal?.scopes ?? []).filter((s) => s !== 'audit:write'),
)

async function load() {
  loading.value = true
  errorMsg.value = ''
  try {
    tokens.value = await tokensApi.list()
  } catch (e) {
    errorMsg.value = e instanceof Error ? e.message : String(e)
  } finally {
    loading.value = false
  }
}

function openCreate() {
  form.name = ''
  form.scopes = new Set(availableScopes.value) // par défaut : tous les scopes effectifs
  form.expiresInDays = ''
  newToken.value = null
  createError.value = ''
  copied.value = false
  showCreateModal.value = true
}

function toggleScope(s: string) {
  const next = new Set(form.scopes)
  if (next.has(s)) next.delete(s)
  else next.add(s)
  form.scopes = next
}

function selectAllScopes() {
  form.scopes = new Set(availableScopes.value)
}
function selectNoScopes() {
  form.scopes = new Set()
}

async function submitCreate() {
  if (!form.name.trim()) {
    createError.value = 'Le nom est requis.'
    return
  }
  if (form.scopes.size === 0) {
    createError.value = 'Sélectionne au moins un scope.'
    return
  }
  creating.value = true
  createError.value = ''
  try {
    const expiresMs = form.expiresInDays
      ? Date.now() + Number(form.expiresInDays) * 86400 * 1000
      : null
    newToken.value = await tokensApi.create({
      name: form.name.trim(),
      scopes: [...form.scopes],
      expires_at: expiresMs,
    })
    await load()
  } catch (e) {
    createError.value =
      e instanceof EurioApiError && typeof e.body === 'object' && e.body && 'detail' in e.body
        ? String((e.body as { detail: unknown }).detail)
        : e instanceof Error
          ? e.message
          : String(e)
  } finally {
    creating.value = false
  }
}

async function copyClear() {
  if (!newToken.value) return
  try {
    await navigator.clipboard.writeText(newToken.value.token)
    copied.value = true
    setTimeout(() => (copied.value = false), 2000)
  } catch {
    /* ignore */
  }
}

function closeModal() {
  showCreateModal.value = false
  newToken.value = null
  copied.value = false
}

async function revoke(t: TokenRow) {
  if (!confirm(`Révoquer le token « ${t.name} » ? Le client qui l'utilise tombera en 401.`)) {
    return
  }
  try {
    await tokensApi.revoke(t.id)
    await load()
  } catch (e) {
    errorMsg.value = e instanceof Error ? e.message : String(e)
  }
}

function fmtDate(ms: number | null): string {
  if (!ms) return '—'
  return new Date(ms).toLocaleString('fr-FR', {
    year: 'numeric',
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
  })
}

function expired(t: TokenRow): boolean {
  return Boolean(t.expires_at && t.expires_at < Date.now())
}

onMounted(load)
</script>

<template>
  <section class="page">
    <header class="page-head">
      <div>
        <h2>Mes tokens</h2>
        <p class="muted small">
          Personal Access Tokens pour l'usage local (studio-local, scripts CLI, curl).
          Le clair n'est affiché qu'à la création — copie-le et garde-le en sûreté.
        </p>
      </div>
      <button class="primary" @click="openCreate">+ Nouveau token</button>
    </header>

    <p v-if="errorMsg" class="err">{{ errorMsg }}</p>

    <div v-if="loading && !tokens.length" class="card center muted">Chargement…</div>

    <div v-else-if="!tokens.length" class="card center">
      <p class="muted">Aucun token. Crée-en un pour activer un client local.</p>
    </div>

    <ul v-else class="rows">
      <li
        v-for="t in tokens"
        :key="t.id"
        class="row"
        :class="{ inactive: !t.active || expired(t) }"
      >
        <div class="row-head">
          <span class="name">{{ t.name }}</span>
          <span v-if="!t.active" class="pill revoked">révoqué</span>
          <span v-else-if="expired(t)" class="pill expired">expiré</span>
          <span v-else class="pill active">actif</span>
        </div>
        <div class="row-meta">
          <span>créé {{ fmtDate(t.created_at) }}</span>
          <span v-if="t.last_used_at"> · vu {{ fmtDate(t.last_used_at) }}</span>
          <span v-if="t.expires_at"> · expire {{ fmtDate(t.expires_at) }}</span>
        </div>
        <div class="row-scopes">
          <code v-for="s in t.scopes" :key="s">{{ s }}</code>
        </div>
        <div class="row-actions">
          <button v-if="t.active && !expired(t)" class="danger" @click="revoke(t)">
            Révoquer
          </button>
        </div>
      </li>
    </ul>

    <!-- Modale création -->
    <div v-if="showCreateModal" class="modal-overlay" @click.self="closeModal">
      <div class="modal" role="dialog" aria-modal="true">
        <header class="modal-head">
          <h3>{{ newToken ? 'Token créé' : 'Nouveau token' }}</h3>
          <button class="close" aria-label="Fermer" @click="closeModal">×</button>
        </header>

        <!-- Étape 1 : formulaire -->
        <div v-if="!newToken" class="modal-body">
          <label>
            Nom (pour repérage)
            <input
              v-model="form.name"
              type="text"
              placeholder="mac-raph, pc-training, curl-debug…"
              maxlength="80"
              autocomplete="off"
            />
          </label>

          <div class="scopes">
            <div class="scopes-head">
              <span class="label">Scopes ({{ form.scopes.size }} sélectionné{{ form.scopes.size > 1 ? 's' : '' }})</span>
              <div class="scopes-actions">
                <button class="link" type="button" @click="selectAllScopes">Tout</button>
                <button class="link" type="button" @click="selectNoScopes">Aucun</button>
              </div>
            </div>
            <ul class="scopes-list">
              <li v-for="s in availableScopes" :key="s">
                <label>
                  <input
                    type="checkbox"
                    :checked="form.scopes.has(s)"
                    @change="toggleScope(s)"
                  />
                  <code>{{ s }}</code>
                </label>
              </li>
            </ul>
          </div>

          <label>
            Expiration (jours, optionnel)
            <input
              v-model="form.expiresInDays"
              type="number"
              min="1"
              max="3650"
              placeholder="ex: 90 — vide = jamais"
            />
          </label>

          <p v-if="createError" class="err">{{ createError }}</p>

          <div class="modal-actions">
            <button @click="closeModal">Annuler</button>
            <button class="primary" :disabled="creating" @click="submitCreate">
              {{ creating ? 'Création…' : 'Créer le token' }}
            </button>
          </div>
        </div>

        <!-- Étape 2 : affichage du clair -->
        <div v-else class="modal-body">
          <p class="warning">
            ⚠ Copie ce token <strong>maintenant</strong>. Il ne sera plus jamais affiché.
            Si tu le perds, révoque-le et crée-en un nouveau.
          </p>
          <div class="token-clear">
            <code>{{ newToken.token }}</code>
            <button class="primary" @click="copyClear">
              {{ copied ? '✓ Copié' : 'Copier' }}
            </button>
          </div>
          <p class="muted small">
            Scopes : {{ newToken.scopes.join(', ') }}<br />
            Expiration : {{ newToken.expires_at ? fmtDate(newToken.expires_at) : 'aucune' }}
          </p>
          <div class="modal-actions">
            <button class="primary" @click="closeModal">J'ai copié — fermer</button>
          </div>
        </div>
      </div>
    </div>
  </section>
</template>

<style scoped>
.page {
  padding: var(--space-5) var(--space-6);
  max-width: 880px;
  margin: 0 auto;
}
.page-head {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: var(--space-4);
  margin-bottom: var(--space-5);
  flex-wrap: wrap;
}
.page-head h2 {
  margin: 0;
  font-size: var(--text-xl);
}
.muted {
  color: var(--text-secondary);
}
.small {
  font-size: var(--text-sm);
  margin: var(--space-1) 0 0;
}
.err {
  color: var(--danger);
  margin-bottom: var(--space-3);
}
.card {
  background: white;
  border: 1px solid var(--border);
  border-radius: var(--radius-md);
  padding: var(--space-5);
}
.center {
  text-align: center;
}

/* Liste tokens */
.rows {
  list-style: none;
  padding: 0;
  margin: 0;
  display: flex;
  flex-direction: column;
  gap: var(--space-3);
}
.row {
  background: white;
  border: 1px solid var(--border);
  border-radius: var(--radius-md);
  padding: var(--space-4);
  display: grid;
  grid-template-columns: 1fr auto;
  gap: var(--space-2);
  align-items: start;
}
.row.inactive {
  opacity: 0.55;
}
.row-head {
  grid-column: 1;
  display: flex;
  align-items: center;
  gap: var(--space-2);
  font-weight: 600;
}
.name {
  font-size: var(--text-md);
}
.pill {
  font-size: var(--text-xs);
  padding: 2px 8px;
  border-radius: 999px;
  font-weight: 500;
}
.pill.active { background: #d6f5dc; color: #1b6f31; }
.pill.revoked { background: #fbe1e1; color: #962020; }
.pill.expired { background: #fff0d6; color: #6f4d1b; }
.row-meta {
  grid-column: 1;
  font-size: var(--text-xs);
  color: var(--text-secondary);
}
.row-scopes {
  grid-column: 1;
  display: flex;
  flex-wrap: wrap;
  gap: 4px;
  margin-top: 4px;
}
.row-scopes code {
  font-size: 11px;
  background: var(--surface-2);
  padding: 2px 6px;
  border-radius: var(--radius-sm);
}
.row-actions {
  grid-column: 2;
  grid-row: 1 / span 3;
  align-self: center;
}

button.primary {
  background: var(--brand);
  color: white;
  border: 1px solid var(--brand);
}
button.primary:hover { background: var(--brand-hover); }
button.danger {
  background: white;
  color: var(--danger);
  border: 1px solid var(--danger);
}
button.danger:hover { background: var(--danger); color: white; }

/* Modale */
.modal-overlay {
  position: fixed;
  inset: 0;
  background: rgba(0, 0, 0, 0.45);
  display: flex;
  align-items: center;
  justify-content: center;
  padding: var(--space-3);
  z-index: 50;
}
.modal {
  background: white;
  border-radius: var(--radius-lg);
  max-width: 560px;
  width: 100%;
  max-height: 90vh;
  overflow-y: auto;
  box-shadow: 0 20px 50px rgba(0, 0, 0, 0.25);
}
.modal-head {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: var(--space-4) var(--space-5);
  border-bottom: 1px solid var(--border);
}
.modal-head h3 { margin: 0; font-size: var(--text-lg); }
.close {
  background: transparent;
  border: none;
  font-size: 22px;
  cursor: pointer;
  color: var(--text-secondary);
  padding: 0 var(--space-2);
}
.modal-body {
  padding: var(--space-4) var(--space-5);
  display: flex;
  flex-direction: column;
  gap: var(--space-4);
}
.modal-body label {
  display: flex;
  flex-direction: column;
  gap: var(--space-2);
  font-size: var(--text-sm);
  color: var(--text-secondary);
}
.modal-body input[type="text"],
.modal-body input[type="number"] {
  padding: var(--space-2) var(--space-3);
  border: 1px solid var(--border);
  border-radius: var(--radius-sm);
  font-size: var(--text-md);
}
.scopes-head {
  display: flex;
  justify-content: space-between;
  align-items: baseline;
  margin-bottom: var(--space-2);
}
.scopes-head .label {
  font-size: var(--text-sm);
  color: var(--text-secondary);
}
.scopes-actions { display: flex; gap: var(--space-2); }
.scopes-actions .link {
  background: transparent;
  border: none;
  color: var(--brand);
  font-size: var(--text-xs);
  cursor: pointer;
  padding: 0;
}
.scopes-list {
  list-style: none;
  padding: 0;
  margin: 0;
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(180px, 1fr));
  gap: 4px;
  max-height: 220px;
  overflow-y: auto;
  border: 1px solid var(--border);
  border-radius: var(--radius-sm);
  padding: var(--space-2);
}
.scopes-list label {
  flex-direction: row;
  gap: var(--space-2);
  align-items: center;
  cursor: pointer;
  font-size: var(--text-xs);
}
.scopes-list code {
  font-size: 11px;
}
.modal-actions {
  display: flex;
  justify-content: flex-end;
  gap: var(--space-2);
  padding-top: var(--space-2);
  border-top: 1px solid var(--border);
}

/* Step 2 : clair */
.warning {
  background: #fff4d6;
  border: 1px solid #f0d77a;
  color: #5d4a0c;
  padding: var(--space-3);
  border-radius: var(--radius-sm);
  margin: 0;
  font-size: var(--text-sm);
}
.token-clear {
  display: flex;
  align-items: center;
  gap: var(--space-2);
  background: var(--surface-2);
  padding: var(--space-3);
  border-radius: var(--radius-sm);
  overflow-x: auto;
}
.token-clear code {
  font-family: ui-monospace, 'SF Mono', Menlo, monospace;
  font-size: var(--text-sm);
  flex: 1;
  word-break: break-all;
}

/* Mobile */
@media (max-width: 640px) {
  .page-head { flex-direction: column; align-items: stretch; }
  .row {
    grid-template-columns: 1fr;
  }
  .row-actions {
    grid-column: 1;
    grid-row: auto;
  }
  .row-actions button { width: 100%; }
}
</style>
