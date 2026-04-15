<script setup lang="ts">
import { supabase } from '@/shared/supabase/client'
import type { Set } from '@/shared/supabase/types'
import { Plus, RefreshCw } from 'lucide-vue-next'
import { onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'

const router = useRouter()
const sets = ref<Set[]>([])
const loading = ref(true)
const error = ref<string | null>(null)

const kindLabel: Record<Set['kind'], string> = {
  structural: 'Structurel',
  curated: 'Curé',
  parametric: 'Paramétré',
}

const categoryLabel: Record<Set['category'], string> = {
  country: 'Pays',
  theme: 'Thème',
  tier: 'Tier',
  personal: 'Personnel',
  hunt: 'Chasse',
}

async function fetchSets() {
  loading.value = true
  error.value = null

  const { data, error: err } = await supabase
    .from('sets')
    .select('*')
    .order('display_order', { ascending: true })

  loading.value = false

  if (err) {
    error.value = err.message
    return
  }

  sets.value = data ?? []
}

onMounted(fetchSets)
</script>

<template>
  <div class="p-8">
    <!-- Header -->
    <div class="mb-6 flex items-start justify-between">
      <div>
        <h1 class="font-display text-2xl italic font-semibold"
            style="color: var(--indigo-700);">
          Sets d'achievement
        </h1>
        <p class="mt-0.5 text-sm" style="color: var(--ink-500);">
          {{ sets.length }} set{{ sets.length !== 1 ? 's' : '' }} au total
        </p>
      </div>
      <div class="flex items-center gap-2">
        <button
          @click="fetchSets"
          :disabled="loading"
          class="flex items-center gap-2 rounded-md border px-3 py-2 text-sm transition-colors hover:bg-surface-1 disabled:opacity-50"
          style="border-color: var(--surface-3); color: var(--ink-500);"
        >
          <RefreshCw class="h-4 w-4" :class="loading && 'animate-spin'" />
        </button>
        <button
          class="flex items-center gap-2 rounded-md px-4 py-2 text-sm font-medium transition-opacity hover:opacity-90"
          style="background: var(--indigo-700); color: white;"
          @click="router.push('/sets/new')"
        >
          <Plus class="h-4 w-4" />
          Nouveau set
        </button>
      </div>
    </div>

    <!-- Error -->
    <div v-if="error"
         class="mb-4 rounded-md px-4 py-3 text-sm"
         style="background: var(--danger-soft); color: var(--danger);">
      {{ error }}
    </div>

    <!-- Loading skeleton -->
    <div v-if="loading" class="space-y-2">
      <div v-for="i in 5" :key="i"
           class="h-14 animate-pulse rounded-md"
           style="background: var(--surface-1);" />
    </div>

    <!-- Empty -->
    <div v-else-if="sets.length === 0"
         class="flex flex-col items-center justify-center rounded-lg border-2 border-dashed py-16"
         style="border-color: var(--surface-3);">
      <p class="font-display italic text-lg" style="color: var(--ink-400);">
        Aucun set pour l'instant
      </p>
      <p class="mt-1 text-sm" style="color: var(--ink-400);">
        Créez le premier set pour commencer.
      </p>
    </div>

    <!-- Table -->
    <div v-else class="overflow-hidden rounded-lg border" style="border-color: var(--surface-3);">
      <table class="w-full text-sm">
        <thead>
          <tr style="background: var(--surface-1); border-bottom: 1px solid var(--surface-3);">
            <th class="px-4 py-3 text-left font-medium text-xs uppercase tracking-wider"
                style="color: var(--ink-500);">Identifiant</th>
            <th class="px-4 py-3 text-left font-medium text-xs uppercase tracking-wider"
                style="color: var(--ink-500);">Nom</th>
            <th class="px-4 py-3 text-left font-medium text-xs uppercase tracking-wider"
                style="color: var(--ink-500);">Nature</th>
            <th class="px-4 py-3 text-left font-medium text-xs uppercase tracking-wider"
                style="color: var(--ink-500);">Catégorie</th>
            <th class="px-4 py-3 text-right font-medium text-xs uppercase tracking-wider"
                style="color: var(--ink-500);">Ordre</th>
            <th class="px-4 py-3 text-center font-medium text-xs uppercase tracking-wider"
                style="color: var(--ink-500);">Statut</th>
          </tr>
        </thead>
        <tbody>
          <tr
            v-for="(set, i) in sets"
            :key="set.id"
            class="cursor-pointer transition-colors hover:bg-surface-1"
            :style="i < sets.length - 1 ? 'border-bottom: 1px solid var(--surface-2)' : ''"
            @click="router.push(`/sets/${set.id}`)"
          >
            <td class="px-4 py-3 font-mono text-xs" style="color: var(--ink-500);">
              {{ set.id }}
            </td>
            <td class="px-4 py-3 font-medium" style="color: var(--ink);">
              {{ set.name_i18n.fr }}
            </td>
            <td class="px-4 py-3">
              <span class="rounded-full px-2 py-0.5 text-xs font-medium"
                    style="background: var(--surface-2); color: var(--ink-500);">
                {{ kindLabel[set.kind] }}
              </span>
            </td>
            <td class="px-4 py-3 text-sm" style="color: var(--ink-500);">
              {{ categoryLabel[set.category] }}
            </td>
            <td class="px-4 py-3 text-right font-mono text-xs" style="color: var(--ink-400);">
              {{ set.display_order }}
            </td>
            <td class="px-4 py-3 text-center">
              <span
                class="inline-block h-2 w-2 rounded-full"
                :style="set.active
                  ? 'background: var(--success)'
                  : 'background: var(--ink-200)'"
                :title="set.active ? 'Actif' : 'Inactif'"
              />
            </td>
          </tr>
        </tbody>
      </table>
    </div>
  </div>
</template>
