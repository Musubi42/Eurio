<script setup lang="ts">
import { supabase } from '@/shared/supabase/client'
import type { Coin } from '@/shared/supabase/types'
import { Search } from 'lucide-vue-next'
import { onMounted, ref, watch } from 'vue'
import { useDebounceFn } from '@vueuse/core'

const coins = ref<Coin[]>([])
const loading = ref(true)
const error = ref<string | null>(null)
const query = ref('')
const total = ref(0)
const PAGE = 50

async function fetchCoins(search = '') {
  loading.value = true
  error.value = null

  let q = supabase
    .from('coins')
    .select('*', { count: 'exact' })
    .order('country')
    .order('year')
    .limit(PAGE)

  if (search.trim()) {
    q = q.or(`eurio_id.ilike.%${search}%,title.ilike.%${search}%,country.eq.${search.toLowerCase()}`)
  }

  const { data, error: err, count } = await q

  loading.value = false
  if (err) { error.value = err.message; return }

  coins.value = data ?? []
  total.value = count ?? 0
}

const debouncedFetch = useDebounceFn(() => fetchCoins(query.value), 300)
watch(query, debouncedFetch)
onMounted(() => fetchCoins())
</script>

<template>
  <div class="p-8">
    <div class="mb-6 flex items-start justify-between">
      <div>
        <h1 class="font-display text-2xl italic font-semibold"
            style="color: var(--indigo-700);">
          Référentiel pièces
        </h1>
        <p class="mt-0.5 text-sm" style="color: var(--ink-500);">
          {{ total }} pièces · lecture seule (géré via ml/bootstrap)
        </p>
      </div>
    </div>

    <!-- Search -->
    <div class="relative mb-4 max-w-sm">
      <Search class="absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2"
              style="color: var(--ink-400);" />
      <input
        v-model="query"
        type="search"
        placeholder="eurio_id, title, pays (ex: fr)…"
        class="w-full rounded-md border py-2 pl-9 pr-3 text-sm outline-none focus:ring-2"
        style="border-color: var(--surface-3); background: var(--surface); color: var(--ink); --tw-ring-color: var(--indigo-700);"
      />
    </div>

    <div v-if="error" class="mb-4 rounded-md px-4 py-3 text-sm"
         style="background: var(--danger-soft); color: var(--danger);">
      {{ error }}
    </div>

    <div v-if="loading" class="space-y-2">
      <div v-for="i in 8" :key="i" class="h-12 animate-pulse rounded-md"
           style="background: var(--surface-1);" />
    </div>

    <div v-else class="overflow-hidden rounded-lg border" style="border-color: var(--surface-3);">
      <table class="w-full text-sm">
        <thead>
          <tr style="background: var(--surface-1); border-bottom: 1px solid var(--surface-3);">
            <th class="px-4 py-3 text-left text-xs font-medium uppercase tracking-wider" style="color:var(--ink-500)">eurio_id</th>
            <th class="px-4 py-3 text-left text-xs font-medium uppercase tracking-wider" style="color:var(--ink-500)">Pays</th>
            <th class="px-4 py-3 text-left text-xs font-medium uppercase tracking-wider" style="color:var(--ink-500)">Année</th>
            <th class="px-4 py-3 text-left text-xs font-medium uppercase tracking-wider" style="color:var(--ink-500)">Val.</th>
            <th class="px-4 py-3 text-left text-xs font-medium uppercase tracking-wider" style="color:var(--ink-500)">Titre</th>
            <th class="px-4 py-3 text-left text-xs font-medium uppercase tracking-wider" style="color:var(--ink-500)">Type</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="(coin, i) in coins" :key="coin.eurio_id"
              :style="i < coins.length - 1 ? 'border-bottom: 1px solid var(--surface-2)' : ''">
            <td class="px-4 py-2.5 font-mono text-xs" style="color: var(--ink-500);">{{ coin.eurio_id }}</td>
            <td class="px-4 py-2.5 font-medium uppercase text-xs" style="color: var(--ink);">{{ coin.country }}</td>
            <td class="px-4 py-2.5 font-mono text-xs" style="color: var(--ink-400);">{{ coin.year }}</td>
            <td class="px-4 py-2.5 font-mono text-xs" style="color: var(--ink-400);">{{ coin.denomination }}€</td>
            <td class="px-4 py-2.5" style="color: var(--ink);">{{ coin.title ?? '—' }}</td>
            <td class="px-4 py-2.5">
              <span v-if="coin.issue_type"
                    class="rounded-full px-2 py-0.5 text-xs"
                    style="background: var(--surface-2); color: var(--ink-500);">
                {{ coin.issue_type }}
              </span>
              <span v-else style="color: var(--ink-300);">—</span>
            </td>
          </tr>
        </tbody>
      </table>
      <div v-if="total > PAGE"
           class="px-4 py-2.5 text-xs text-center"
           style="background: var(--surface-1); border-top: 1px solid var(--surface-3); color: var(--ink-400);">
        Affichage des {{ coins.length }} premiers résultats sur {{ total }}
      </div>
    </div>
  </div>
</template>
