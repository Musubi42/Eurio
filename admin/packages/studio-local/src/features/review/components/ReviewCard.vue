<script setup lang="ts">
// Card partagée crop ↔ canonical + métadonnées listing, utilisée par les vues
// en grille : auto-accept déterministe (voie locale) et arbitrage des décisions
// d'amis (lot 8, voie VPS).
//
// ⚠️ Elle attend des URLs SERVABLES telles quelles — la résolution appartient à
// l'appelant, qui seul sait quelle API a produit le chemin.
//
// Le slot `metrics` permet à chaque page d'injecter les métriques
// spécifiques de sa voie (sim/spread/face pour AutoAccept, verdict/
// confidence/model pour CCProxy) sans dupliquer la coquille.
//
// Style aligné sur tokens.css : surface papier, indigo brand, mono pour
// les chiffres et codes, lucide icons.

import { ExternalLink, CheckSquare, Square } from 'lucide-vue-next'

defineProps<{
  cropUrl: string
  canonicalUrl: string | null
  eurioId: string
  targetLabel: string
  listingTitle: string
  listingUrl: string | null
  source: string
  selected: boolean
  /**
   * Couleur d'accent quand sélectionné (border + checkbox).
   * Default = var(--success). CCProxy passe la couleur du verdict.
   */
  accentColor?: string
}>()

defineEmits<{
  (e: 'toggle'): void
}>()

// La card ne RÉSOUT plus les URLs : chaque page lui passe des URLs déjà
// servables. Elle les préfixait par `ML_API` (`127.0.0.1:8042`), ce qui est juste
// pour l'auto-accept (servi par l'app full) et FAUX pour l'arbitrage (servi par
// le VPS) — une seule composante ne peut pas trancher pour ses deux appelants.
function img(url: string | null | undefined): string | null {
  return url || null
}
</script>

<template>
  <article
    class="card flex flex-col gap-3 rounded-lg border p-3 transition-colors"
    :class="{ 'card-selected': selected }"
    :style="{
      'border-color': selected ? (accentColor ?? 'var(--success)') : 'var(--surface-3)',
      background: 'var(--surface)',
    }"
    @click="$emit('toggle')"
  >
    <!-- Top row : crop ↔ canonical -->
    <div class="grid grid-cols-2 gap-2">
      <div class="relative aspect-square overflow-hidden rounded-md" style="background: var(--surface-1);">
        <img
          v-if="img(cropUrl)"
          :src="img(cropUrl)!"
          :alt="`crop ${eurioId}`"
          class="absolute inset-0 h-full w-full object-cover"
          loading="lazy"
        />
        <span
          class="absolute left-1 top-1 rounded px-1.5 py-0.5 font-mono text-[9px] uppercase tracking-wider"
          style="background: var(--ink); color: var(--surface); opacity: 0.85;"
        >crop</span>
      </div>
      <div class="relative aspect-square overflow-hidden rounded-md" style="background: var(--surface-1);">
        <img
          v-if="img(canonicalUrl)"
          :src="img(canonicalUrl)!"
          :alt="`canonical ${eurioId}`"
          class="absolute inset-0 h-full w-full object-cover"
          loading="lazy"
        />
        <span
          class="absolute right-1 top-1 rounded px-1.5 py-0.5 font-mono text-[9px] uppercase tracking-wider"
          style="background: var(--indigo-700); color: var(--surface); opacity: 0.85;"
        >cible</span>
      </div>
    </div>

    <!-- Métadonnées -->
    <div class="flex flex-col gap-1.5">
      <div class="flex items-start justify-between gap-2">
        <div class="min-w-0 flex-1">
          <p
            class="truncate font-mono text-[11px] font-semibold"
            style="color: var(--indigo-700);"
            :title="eurioId"
          >
            {{ eurioId }}
          </p>
          <p class="truncate text-[12px]" style="color: var(--ink-700);" :title="targetLabel">
            {{ targetLabel }}
          </p>
        </div>
        <component
          :is="selected ? CheckSquare : Square"
          class="h-5 w-5 flex-shrink-0"
          :style="{
            color: selected ? (accentColor ?? 'var(--success)') : 'var(--ink-400)',
          }"
        />
      </div>

      <!-- Slot métriques spécifiques à chaque voie. -->
      <slot name="metrics" />

      <p class="line-clamp-2 text-[11px] italic" style="color: var(--ink-500);" :title="listingTitle">
        « {{ listingTitle || '—' }} »
      </p>

      <div class="flex items-center justify-between gap-2">
        <span
          class="rounded-sm px-1.5 py-0.5 font-mono text-[9px] uppercase tracking-wider"
          style="background: var(--surface-1); color: var(--ink-500); border: 1px solid var(--surface-3);"
        >
          {{ source }}
        </span>
        <a
          v-if="listingUrl"
          :href="listingUrl"
          target="_blank"
          rel="noopener"
          class="inline-flex items-center gap-1 text-[10px] underline-offset-2 hover:underline"
          style="color: var(--ink-500);"
          @click.stop
        >
          <ExternalLink class="h-3 w-3" />
          listing
        </a>
      </div>
    </div>
  </article>
</template>

<style scoped>
.card { cursor: pointer; }
.card:hover { background: var(--surface-1) !important; }
.card-selected { box-shadow: 0 0 0 1px var(--card-accent, var(--success)); }
</style>
