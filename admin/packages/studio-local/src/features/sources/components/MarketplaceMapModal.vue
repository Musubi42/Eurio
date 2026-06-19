<script setup lang="ts">
import { X } from 'lucide-vue-next'
import { computed } from 'vue'
import { mktShort, type MarketplaceMap } from '../composables/useMarketplaceMap'

/**
 * MarketplaceMapModal — détail du routage discovery eBay, ouvert depuis
 * le bandeau "Stratégie d'extraction" du pilote (front-ux.md §"Surface 1").
 * Lecture seule — la stratégie est figée côté code.
 *
 * Depuis le benchmark routing (2026-05-21), le routage est uniforme :
 * {EBAY_DE, EBAY_ES} pour toutes les origines (cf. marketplaces.py).
 */

const props = defineProps<{
  open: boolean
  map: MarketplaceMap | null
}>()

const emit = defineEmits<{ (e: 'close'): void }>()

const marketplaces = computed(() => props.map?.marketplaces ?? [])
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
          class="flex max-h-[80vh] w-full max-w-md flex-col rounded-lg border shadow-xl"
          style="background: var(--surface); border-color: var(--surface-3)"
        >
          <div class="flex items-start justify-between gap-4 px-6 py-4">
            <div>
              <h2 class="font-display text-lg italic" style="color: var(--indigo-700)">
                Routage discovery eBay
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
            <template v-else>
              <p class="mb-3 text-xs leading-relaxed" style="color: var(--ink)">
                Routage <strong>uniforme</strong> : chaque pièce est cherchée sur les
                {{ marketplaces.length }} marketplaces ci-dessous, quelle que soit son
                origine. Choix validé par le benchmark de recall (2026-05-20) —
                <span class="font-mono">{DE, ES}</span> couvre le top-2 sur ~22/24 origines.
                <span style="color: var(--ink-500)">EBAY_GB a été retiré (annonces en GBP,
                0 listing EUR exploitable).</span>
              </p>
              <table class="w-full text-xs">
                <thead>
                  <tr style="color: var(--ink-500)">
                    <th class="py-1.5 text-left font-medium">Marketplace</th>
                    <th class="py-1.5 text-left font-medium">Langue de query</th>
                  </tr>
                </thead>
                <tbody>
                  <tr
                    v-for="m in marketplaces"
                    :key="m.marketplace"
                    class="border-t"
                    style="border-color: var(--surface-2)"
                  >
                    <td class="py-1.5 font-mono" style="color: var(--ink)">
                      {{ mktShort(m.marketplace) }}
                    </td>
                    <td class="py-1.5 font-mono" style="color: var(--ink-500)">
                      {{ m.query_lang }}
                    </td>
                  </tr>
                </tbody>
              </table>
            </template>
          </div>
        </div>
      </div>
    </Transition>
  </Teleport>
</template>
