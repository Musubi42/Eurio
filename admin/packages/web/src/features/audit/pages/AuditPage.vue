<script setup lang="ts">
import { supabase } from '@/shared/supabase/client'
import type { SetAudit } from '@/shared/supabase/types'
import { onMounted, ref } from 'vue'

const entries = ref<SetAudit[]>([])
const loading = ref(true)
const error = ref<string | null>(null)

const actionColor: Record<SetAudit['action'], string> = {
  create:     'var(--success)',
  publish:    'var(--success)',
  update:     'var(--warning)',
  activate:   'var(--success)',
  deactivate: 'var(--ink-400)',
  delete:     'var(--danger)',
}

async function fetchAudit() {
  loading.value = true
  const { data, error: err } = await supabase
    .from('sets_audit')
    .select('*')
    .order('at', { ascending: false })
    .limit(100)

  loading.value = false
  if (err) { error.value = err.message; return }
  entries.value = data ?? []
}

onMounted(fetchAudit)

function formatDate(iso: string) {
  return new Date(iso).toLocaleString('fr-FR', {
    day: '2-digit', month: '2-digit', year: 'numeric',
    hour: '2-digit', minute: '2-digit',
  })
}
</script>

<template>
  <div class="p-8">
    <div class="mb-6">
      <h1 class="font-display text-2xl italic font-semibold" style="color: var(--indigo-700);">
        Audit log
      </h1>
      <p class="mt-0.5 text-sm" style="color: var(--ink-500);">
        Historique des modifications des sets · lecture seule · 100 dernières entrées
      </p>
    </div>

    <div v-if="error" class="mb-4 rounded-md px-4 py-3 text-sm"
         style="background: var(--danger-soft); color: var(--danger);">{{ error }}</div>

    <div v-if="loading" class="space-y-2">
      <div v-for="i in 6" :key="i" class="h-12 animate-pulse rounded-md"
           style="background: var(--surface-1);" />
    </div>

    <div v-else-if="entries.length === 0"
         class="flex flex-col items-center justify-center rounded-lg border-2 border-dashed py-16"
         style="border-color: var(--surface-3);">
      <p class="font-display italic text-lg" style="color: var(--ink-400);">
        Aucune entrée d'audit
      </p>
    </div>

    <div v-else class="overflow-hidden rounded-lg border" style="border-color: var(--surface-3);">
      <table class="w-full text-sm">
        <thead>
          <tr style="background: var(--surface-1); border-bottom: 1px solid var(--surface-3);">
            <th class="px-4 py-3 text-left text-xs font-medium uppercase tracking-wider" style="color:var(--ink-500)">Date</th>
            <th class="px-4 py-3 text-left text-xs font-medium uppercase tracking-wider" style="color:var(--ink-500)">Set</th>
            <th class="px-4 py-3 text-left text-xs font-medium uppercase tracking-wider" style="color:var(--ink-500)">Action</th>
            <th class="px-4 py-3 text-left text-xs font-medium uppercase tracking-wider" style="color:var(--ink-500)">Acteur</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="(entry, i) in entries" :key="entry.id"
              :style="i < entries.length - 1 ? 'border-bottom: 1px solid var(--surface-2)' : ''">
            <td class="px-4 py-2.5 font-mono text-xs" style="color: var(--ink-400);">
              {{ formatDate(entry.at) }}
            </td>
            <td class="px-4 py-2.5 font-mono text-xs" style="color: var(--ink-500);">
              {{ entry.set_id }}
            </td>
            <td class="px-4 py-2.5">
              <span class="rounded-full px-2 py-0.5 text-xs font-medium capitalize"
                    :style="`color: ${actionColor[entry.action]}; background: ${actionColor[entry.action]}1a`">
                {{ entry.action }}
              </span>
            </td>
            <td class="px-4 py-2.5 text-xs" style="color: var(--ink-500);">
              {{ entry.actor }}
            </td>
          </tr>
        </tbody>
      </table>
    </div>
  </div>
</template>
