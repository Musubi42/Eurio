<script setup lang="ts">
import { X } from 'lucide-vue-next'
import { computed } from 'vue'
import { mktShort, type MarketplaceMap } from '../composables/useMarketplaceMap'

/**
 * MarketplaceMapModal — table complète du routage pays → marketplaces eBay,
 * ouverte depuis le bandeau "Stratégie d'extraction" du pilote (front-ux.md
 * §"Surface 1"). Lecture seule — la stratégie est figée côté code.
 */

const props = defineProps<{
  open: boolean
  map: MarketplaceMap | null
}>()

const emit = defineEmits<{ (e: 'close'): void }>()

// Tri : pays avec marketplace natif d'abord, puis GB-only, puis 'eu'.
const sortedEntries = computed(() => {
  const entries = props.map?.entries ?? []
  return [...entries].sort((a, b) => {
    const rank = (e: typeof a) => (e.country === 'eu' ? 2 : e.primary ? 0 : 1)
    const ra = rank(a)
    const rb = rank(b)
    return ra !== rb ? ra - rb : a.country.localeCompare(b.country)
  })
})

function callsFor(primary: string | null, global_: string): number {
  return primary && primary !== global_ ? 2 : 1
}
</script>

<template>
  <Teleport to="body">
    <Transition name="fade">
      <div
        v-if="open"
        class="fixed inset-0 z-50 flex items-center justify-center"
        style="background: rgba(0, 0, 0, 0.5)"
        @click.self="emit('close')"
      >
        <div
          class="flex max-h-[80vh] w-full max-w-lg flex-col rounded-lg border shadow-xl"
          style="background: var(--surface); border-color: var(--surface-3)"
        >
          <div class="flex items-start justify-between gap-4 px-6 py-4">
            <div>
              <h2 class="font-display text-lg italic" style="color: var(--indigo-700)">
                Routage pays → marketplaces eBay
              </h2>
              <p class="mt-0.5 text-[11px]" style="color: var(--ink-500)">
                Stratégie figée — source : <span class="font-mono">ml/sources/ebay/marketplaces.py</span>
              </p>
            </div>
            <button
              type="button"
              class="rounded p-1 transition-colors hover:bg-[var(--surface-1)]"
              @click="emit('close')"
            >
              <X class="h-4 w-4" style="color: var(--ink-500)" />
            </button>
          </div>

          <div class="overflow-y-auto px-6 pb-5">
            <div v-if="!map" class="py-6 text-center text-xs" style="color: var(--ink-400)">
              Routage indisponible — l'API ML est hors ligne.
            </div>
            <table v-else class="w-full text-xs">
              <thead>
                <tr style="color: var(--ink-500)">
                  <th class="py-1.5 text-left font-medium">Pays</th>
                  <th class="py-1.5 text-left font-medium">Natif</th>
                  <th class="py-1.5 text-left font-medium">Global</th>
                  <th class="py-1.5 text-left font-medium">Query</th>
                  <th class="py-1.5 text-right font-medium">Calls</th>
                </tr>
              </thead>
              <tbody>
                <tr
                  v-for="e in sortedEntries"
                  :key="e.country"
                  class="border-t"
                  style="border-color: var(--surface-2)"
                >
                  <td class="py-1.5 font-mono" style="color: var(--ink)">{{ e.country }}</td>
                  <td class="py-1.5" style="color: var(--ink)">
                    <span v-if="e.primary" class="font-mono">{{ mktShort(e.primary) }}</span>
                    <span v-else style="color: var(--ink-400)">—</span>
                  </td>
                  <td class="py-1.5 font-mono" style="color: var(--ink-500)">
                    {{ mktShort(e.global_) }}
                  </td>
                  <td class="py-1.5 font-mono" style="color: var(--ink-500)">{{ e.query_lang }}</td>
                  <td class="py-1.5 text-right tabular-nums" style="color: var(--ink-500)">
                    {{ callsFor(e.primary, e.global_) }}
                  </td>
                </tr>
              </tbody>
            </table>
          </div>
        </div>
      </div>
    </Transition>
  </Teleport>
</template>
