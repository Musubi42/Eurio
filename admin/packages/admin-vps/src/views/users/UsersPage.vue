<script setup lang="ts">
/**
 * Page Users — liste des utilisateurs du miroir local (peuplé par les
 * logins OIDC) + édition des rôles applicatifs.
 *
 * Scopes :
 * - Lecture : `users:read` (owner + admin)
 * - Édition : `users:manage` (owner uniquement) — le bouton "Modifier"
 *   est caché aux non-owner.
 *
 * Anti-lockout : l'API refuse de retirer le dernier owner. On affiche
 * un message clair côté UI si on tombe sur cette erreur.
 */
import { computed, onMounted, ref } from 'vue'

import { ApiError } from '@/api/client'
import { ALL_ROLES, usersApi, type Role, type UserRow } from '@/api/users'
import { useAuthStore } from '@/stores/auth'

const auth = useAuthStore()

const users = ref<UserRow[]>([])
const loading = ref(false)
const errorMsg = ref('')

const editingId = ref<string | null>(null)
const editingRoles = ref<Set<Role>>(new Set())
const saving = ref(false)
const editError = ref('')

const canManage = computed(() => auth.hasScope('users:manage'))

async function load() {
  loading.value = true
  errorMsg.value = ''
  try {
    users.value = await usersApi.list()
  } catch (e) {
    errorMsg.value = e instanceof Error ? e.message : String(e)
  } finally {
    loading.value = false
  }
}

function startEdit(u: UserRow) {
  editingId.value = u.id
  editingRoles.value = new Set(u.roles)
  editError.value = ''
}

function cancelEdit() {
  editingId.value = null
  editingRoles.value = new Set()
  editError.value = ''
}

function toggleRole(r: Role) {
  const next = new Set(editingRoles.value)
  if (next.has(r)) next.delete(r)
  else next.add(r)
  editingRoles.value = next
}

async function saveRoles(u: UserRow) {
  saving.value = true
  editError.value = ''
  try {
    await usersApi.setRoles(u.id, [...editingRoles.value])
    await load()
    cancelEdit()
  } catch (e) {
    editError.value =
      e instanceof ApiError && typeof e.body === 'object' && e.body && 'detail' in e.body
        ? String((e.body as { detail: unknown }).detail)
        : e instanceof Error
          ? e.message
          : String(e)
  } finally {
    saving.value = false
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

function relTime(ms: number | null): string {
  if (!ms) return 'jamais'
  const diff = Date.now() - ms
  if (diff < 60_000) return "à l'instant"
  const min = Math.floor(diff / 60_000)
  if (min < 60) return `il y a ${min} min`
  const h = Math.floor(min / 60)
  if (h < 24) return `il y a ${h} h`
  const d = Math.floor(h / 24)
  return `il y a ${d} j`
}

function isMe(u: UserRow): boolean {
  return u.id === auth.principal?.user_id
}

onMounted(load)
</script>

<template>
  <section class="page">
    <header class="page-head">
      <div>
        <h2>Users</h2>
        <p class="muted small">
          Miroir local des utilisateurs Authentik (peuplé au premier login OIDC).
          Création / suppression = côté Authentik. Ici on gère uniquement les
          <strong>rôles applicatifs</strong> Eurio.
        </p>
      </div>
      <button :disabled="loading" @click="load">Rafraîchir</button>
    </header>

    <p v-if="errorMsg" class="err">{{ errorMsg }}</p>

    <div v-if="loading && !users.length" class="card center muted">Chargement…</div>

    <ul v-else-if="users.length" class="rows">
      <li v-for="u in users" :key="u.id" class="row" :class="{ inactive: !u.active }">
        <div class="row-main">
          <div class="row-head">
            <span class="email">{{ u.email }}</span>
            <span v-if="isMe(u)" class="pill me">toi</span>
            <span v-if="!u.active" class="pill inactive">inactif</span>
          </div>
          <div v-if="u.name" class="row-name">{{ u.name }}</div>
          <div class="row-meta">
            créé {{ fmtDate(u.created_at) }} · dernier login {{ relTime(u.last_login_at) }}
          </div>

          <!-- Affichage normal -->
          <div v-if="editingId !== u.id" class="row-roles">
            <code v-for="r in u.roles" :key="r">{{ r }}</code>
            <span v-if="!u.roles.length" class="muted small">aucun rôle</span>
          </div>

          <!-- Mode édition -->
          <div v-else class="edit-roles">
            <label v-for="r in ALL_ROLES" :key="r">
              <input
                type="checkbox"
                :checked="editingRoles.has(r)"
                @change="toggleRole(r)"
              />
              <code>{{ r }}</code>
            </label>
            <p v-if="editError" class="err small">{{ editError }}</p>
            <div class="edit-actions">
              <button :disabled="saving" @click="cancelEdit">Annuler</button>
              <button class="primary" :disabled="saving" @click="saveRoles(u)">
                {{ saving ? 'Sauvegarde…' : 'Sauvegarder' }}
              </button>
            </div>
          </div>
        </div>
        <div v-if="canManage && editingId !== u.id" class="row-actions">
          <button @click="startEdit(u)">Modifier rôles</button>
        </div>
      </li>
    </ul>

    <div v-else class="card center">
      <p class="muted">Aucun user dans le miroir local.</p>
    </div>
  </section>
</template>

<style scoped>
.page {
  padding: var(--space-5) var(--space-6);
  max-width: 960px;
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
.page-head h2 { margin: 0; font-size: var(--text-xl); }
.muted { color: var(--text-secondary); }
.small {
  font-size: var(--text-sm);
  margin: var(--space-1) 0 0;
}
.err {
  color: var(--danger);
  margin-bottom: var(--space-3);
}
.err.small { font-size: var(--text-xs); margin: 0; }
.card {
  background: white;
  border: 1px solid var(--border);
  border-radius: var(--radius-md);
  padding: var(--space-5);
}
.center { text-align: center; }

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
  gap: var(--space-3);
  align-items: start;
}
.row.inactive { opacity: 0.55; }
.row-main { grid-column: 1; display: flex; flex-direction: column; gap: 4px; }
.row-head {
  display: flex;
  align-items: center;
  gap: var(--space-2);
}
.email { font-weight: 600; font-size: var(--text-md); }
.row-name { font-size: var(--text-sm); color: var(--text-secondary); }
.row-meta { font-size: var(--text-xs); color: var(--text-secondary); }
.row-roles {
  display: flex;
  flex-wrap: wrap;
  gap: 4px;
  margin-top: var(--space-2);
}
.row-roles code {
  font-size: 11px;
  background: var(--surface-2);
  padding: 2px 8px;
  border-radius: 999px;
}
.row-actions { grid-column: 2; }
.pill {
  font-size: var(--text-xs);
  padding: 2px 8px;
  border-radius: 999px;
  font-weight: 500;
}
.pill.me { background: var(--brand); color: white; }
.pill.inactive { background: #fbe1e1; color: #962020; }

.edit-roles {
  display: flex;
  flex-direction: column;
  gap: var(--space-2);
  margin-top: var(--space-2);
  padding: var(--space-3);
  background: var(--surface-2);
  border-radius: var(--radius-sm);
}
.edit-roles label {
  display: flex;
  align-items: center;
  gap: var(--space-2);
  font-size: var(--text-sm);
  cursor: pointer;
}
.edit-roles code {
  font-size: 11px;
}
.edit-actions {
  display: flex;
  justify-content: flex-end;
  gap: var(--space-2);
}

button.primary {
  background: var(--brand);
  color: white;
  border: 1px solid var(--brand);
}
button.primary:hover { background: var(--brand-hover); }
button.primary:disabled { opacity: 0.6; cursor: default; }

@media (max-width: 640px) {
  .page-head { flex-direction: column; align-items: stretch; }
  .row { grid-template-columns: 1fr; }
  .row-actions { grid-column: 1; }
  .row-actions button { width: 100%; }
}
</style>
