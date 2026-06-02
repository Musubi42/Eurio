<script setup lang="ts">
/* CoinImage — avers RÉEL de la pièce (webp Supabase Storage) avec repli sur le
 * SVG procédural en cas d'absence/erreur. Remplace les usages directs de coinSvg
 * comme visuel principal d'une pièce (coffre, recherche, carte, fiche).
 *
 * L'avers est une photo carrée (coin centré, fond clair) → clip circulaire +
 * object-fit cover côté CSS (.coin-img). Le repli SVG garde la classe coin-svg
 * d'origine pour hériter du dimensionnement par conteneur. */
import { computed, ref, watch } from 'vue'
import { coinObverseUrl, coinSvg } from '@/api'
import type { Coin } from '@/api'

const props = withDefaults(defineProps<{ coin: Coin; size?: number; showLabel?: boolean }>(), {
  size: 120,
  showLabel: true,
})

// Repli si l'avers n'existe pas (404) ou échoue à charger.
const failed = ref(false)
watch(
  () => props.coin.eurioId,
  () => (failed.value = false),
)

const src = computed(() => coinObverseUrl(props.coin))
const svg = computed(() => coinSvg(props.coin, { size: props.size, showLabel: props.showLabel }))
const alt = computed(() => `${props.coin.countryName}${props.coin.year ? ' ' + props.coin.year : ''}`)
</script>

<template>
  <img
    v-if="src && !failed"
    class="coin-svg coin-img"
    :src="src"
    :alt="alt"
    loading="lazy"
    decoding="async"
    @error="failed = true"
  />
  <span v-else class="coin-img-fallback" v-html="svg"></span>
</template>
