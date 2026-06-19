<script setup lang="ts">
import { computed } from 'vue'
import { mktFlagUrl, mktShort } from '../composables/useMarketplaceMap'

/**
 * MarketplaceBadge — badge marketplace eBay : drapeau du pays en fond,
 * code ISO2 en surimpression. Un scrim sombre semi-transparent garantit
 * la lisibilité du texte blanc sur n'importe quel drapeau (y compris les
 * bandes claires, ex. blanc du drapeau néerlandais).
 *
 * Réutilisé par le run breakdown (colonne Mkts, F2) et la coin-detail
 * (badge par thumb, F4). Cf. front-ux.md §"Récap palette marketplaces".
 */

const props = withDefaults(
  defineProps<{
    marketplace: string
    /** 'md' = tableau (défaut) · 'sm' = coin d'un thumb */
    size?: 'sm' | 'md'
  }>(),
  { size: 'md' },
)

const flagUrl = computed(() => mktFlagUrl(props.marketplace))
const code = computed(() => mktShort(props.marketplace))

// Vite inline les petits SVG en data-URI (non-quotés, à `'` internes) :
// il FAUT envelopper l'URL dans des guillemets sinon le `url()` CSS casse.
const flagStyle = computed(() =>
  flagUrl.value ? { backgroundImage: `url("${flagUrl.value}")` } : {},
)
</script>

<template>
  <span
    class="mkt-badge"
    :class="size === 'sm' ? 'mkt-badge--sm' : 'mkt-badge--md'"
    :title="marketplace"
  >
    <span v-if="flagUrl" class="mkt-flag" :style="flagStyle" />
    <span class="mkt-scrim" :class="{ 'mkt-scrim--plain': !flagUrl }" />
    <span class="mkt-code">{{ code }}</span>
  </span>
</template>

<style scoped>
.mkt-badge {
  position: relative;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  overflow: hidden;
  border-radius: 3px;
  font-family: ui-monospace, 'SF Mono', Menlo, monospace;
  line-height: 1;
  vertical-align: middle;
}
.mkt-badge--md {
  min-width: 26px;
  height: 16px;
  padding: 0 3px;
}
.mkt-badge--sm {
  min-width: 22px;
  height: 14px;
  padding: 0 2px;
}
.mkt-flag {
  position: absolute;
  inset: 0;
  background-position: center;
  background-size: cover;
  background-repeat: no-repeat;
}
.mkt-scrim {
  position: absolute;
  inset: 0;
  background: rgba(0, 0, 0, 0.4);
}
/* Marketplace non mappé à un drapeau → fond neutre opaque. */
.mkt-scrim--plain {
  background: var(--ink-500, #6b7280);
}
.mkt-code {
  position: relative;
  color: #fff;
  font-weight: 700;
  letter-spacing: 0.02em;
  text-shadow: 0 1px 2px rgba(0, 0, 0, 0.75);
}
.mkt-badge--md .mkt-code {
  font-size: 9px;
}
.mkt-badge--sm .mkt-code {
  font-size: 8px;
}
</style>
