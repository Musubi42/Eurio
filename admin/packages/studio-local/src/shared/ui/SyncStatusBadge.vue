<script setup lang="ts">
// Badge de sync (local-sync) — bas de sidebar, au-dessus de la zone identité.
// Pastille verte (à jour) / orange (sync en cours) / rouge (échec), « il y a
// X min », bouton sync manuel ; hover → popover détaillé. Local-only : le
// parent le gate sur caps.hasLocalMlApi.

import { useSyncStatusQuery, useTriggerSyncMutation } from '@/features/sync/composables/useSyncQueries'
import { Loader2, RefreshCw } from 'lucide-vue-next'
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'

withDefaults(defineProps<{ collapsed?: boolean }>(), { collapsed: false })

const query = useSyncStatusQuery()
const trigger = useTriggerSyncMutation()
const status = computed(() => query.data.value ?? null)

// Horloge locale pour le « il y a X min » (re-render sans re-fetch).
const nowTick = ref(Date.now())
let timer: ReturnType<typeof setInterval> | undefined
onMounted(() => { timer = setInterval(() => { nowTick.value = Date.now() }, 30_000) })
onBeforeUnmount(() => { if (timer) clearInterval(timer) })

const tint = computed(() => {
  const s = status.value?.state
  if (s === 'syncing') return 'var(--warning)'
  if (s === 'error') return 'var(--danger)'
  if (s === 'ok' || s === 'pending') return 'var(--success)'
  return 'rgba(255,255,255,0.35)' // disabled / API locale muette
})

// datetime('now') SQLite = UTC sans suffixe → on force le Z au parse.
function parseUtc(ts: string): number {
  return new Date(ts.includes('T') ? ts : `${ts.replace(' ', 'T')}Z`).getTime()
}

const lastSyncLabel = computed(() => {
  const at = status.value?.last_sync_at
  if (!at) return 'jamais synchronisé'
  const mins = Math.max(0, Math.round((nowTick.value - parseUtc(at)) / 60_000))
  if (mins < 1) return "à l'instant"
  if (mins < 60) return `il y a ${mins} min`
  const h = Math.floor(mins / 60)
  return `il y a ${h} h${mins % 60 ? ` ${mins % 60} min` : ''}`
})

const line = computed(() => {
  const s = status.value
  if (!s) return 'Sync — statut inconnu'
  switch (s.state) {
    case 'syncing': return 'Synchronisation…'
    case 'error': return 'Sync en échec'
    case 'pending': return `${s.pending_events} en attente`
    case 'disabled': return 'Sync désactivée'
    default: return `Sync ${lastSyncLabel.value}`
  }
})

const canTrigger = computed(() => {
  const s = status.value?.state
  return s === 'ok' || s === 'pending' || s === 'error'
})

function onTrigger() {
  if (canTrigger.value && !trigger.isPending.value) trigger.mutate()
}
</script>

<template>
  <div
    class="group relative border-t"
    style="border-color: rgba(255,255,255,0.08);"
  >
    <!-- Ligne badge -->
    <div
      class="flex items-center py-2 text-xs"
      :class="collapsed ? 'justify-center px-0' : 'gap-2 px-3'"
      style="color: rgba(255,255,255,0.65);"
    >
      <span
        class="h-2.5 w-2.5 flex-shrink-0 rounded-full"
        :style="{
          background: tint,
          boxShadow: status?.state === 'syncing' ? `0 0 6px ${'var(--warning)'}` : 'none',
        }"
      ></span>
      <template v-if="!collapsed">
        <span class="truncate">{{ line }}</span>
        <button
          type="button"
          class="ml-auto flex h-6 w-6 flex-shrink-0 items-center justify-center rounded-md transition-colors hover:bg-white/10 disabled:cursor-not-allowed disabled:opacity-40"
          style="color: rgba(255,255,255,0.6);"
          title="Synchroniser maintenant"
          :disabled="!canTrigger || trigger.isPending.value || status?.state === 'syncing'"
          @click="onTrigger"
        >
          <Loader2
            v-if="status?.state === 'syncing' || trigger.isPending.value"
            class="h-3.5 w-3.5 animate-spin"
          />
          <RefreshCw v-else class="h-3.5 w-3.5" />
        </button>
      </template>
    </div>

    <!-- Popover détail (hover, pattern maison group-hover + absolute) -->
    <div
      class="pointer-events-none absolute bottom-full left-2 z-50 mb-1 w-64 rounded-lg border p-3 opacity-0 shadow-lg transition-opacity duration-150 group-hover:pointer-events-auto group-hover:opacity-100"
      style="background: var(--surface); border-color: var(--ink-200, rgba(0,0,0,0.12)); color: var(--ink);"
    >
      <div class="mb-2 flex items-center gap-2">
        <span class="h-2 w-2 rounded-full" :style="{ background: tint }"></span>
        <p class="text-[10px] font-semibold uppercase tracking-widest" style="color: var(--ink-500);">
          Sync événements
        </p>
      </div>
      <dl class="space-y-1 text-xs">
        <div class="flex justify-between gap-2">
          <dt style="color: var(--ink-500);">Machine</dt>
          <dd class="font-mono">{{ status?.machine_id ?? '—' }}</dd>
        </div>
        <div class="flex justify-between gap-2">
          <dt style="color: var(--ink-500);">Dernier sync</dt>
          <dd>{{ lastSyncLabel }}</dd>
        </div>
        <div class="flex justify-between gap-2">
          <dt style="color: var(--ink-500);">En attente</dt>
          <dd class="font-mono">{{ status?.pending_events ?? 0 }}</dd>
        </div>
        <div class="flex justify-between gap-2">
          <dt style="color: var(--ink-500);">Dernier push / pull</dt>
          <dd class="font-mono">{{ status?.last_push_count ?? 0 }} / {{ status?.last_pull_count ?? 0 }}</dd>
        </div>
        <div v-if="status?.state === 'error' && status?.last_error" class="pt-1">
          <dt class="mb-0.5" style="color: var(--danger);">Erreur</dt>
          <dd class="break-words font-mono text-[10px]" style="color: var(--danger);">
            {{ status.last_error }}
          </dd>
        </div>
        <div v-if="status?.state === 'disabled'" class="pt-1 italic" style="color: var(--ink-500);">
          {{ status?.reason ?? 'EURIO_API_URL absent côté API locale.' }}
        </div>
      </dl>
      <button
        type="button"
        class="mt-2 w-full rounded-md border py-1 text-xs font-medium transition-colors hover:bg-black/5 disabled:cursor-not-allowed disabled:opacity-40"
        style="border-color: var(--ink-200, rgba(0,0,0,0.15));"
        :disabled="!canTrigger || trigger.isPending.value || status?.state === 'syncing'"
        @click="onTrigger"
      >
        {{ status?.state === 'syncing' ? 'Synchronisation…' : 'Synchroniser maintenant' }}
      </button>
    </div>
  </div>
</template>
