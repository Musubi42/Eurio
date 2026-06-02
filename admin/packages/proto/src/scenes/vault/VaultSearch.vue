<script setup lang="ts">
/* Scène vault-search — recherche live, résultats scindés coffre / à chasser.
 * Port de vault-search.html/.js. */
import { computed, onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import { searchCoins } from '@/api'
import type { Coin } from '@/api'
import { useCollectionStore } from '@/stores/collection'
import CoinImage from '@/components/CoinImage.vue'

const router = useRouter()
const store = useCollectionStore()
const MAX_PER_SECTION = 20

const query = ref('')
const inputEl = ref<HTMLInputElement | null>(null)

const results = computed(() => {
  const q = query.value.trim()
  if (!q) return null
  const owned: Coin[] = []
  const hunt: Coin[] = []
  for (const c of searchCoins(q)) {
    if (store.hasCoin(c.eurioId)) owned.push(c)
    else hunt.push(c)
    if (owned.length + hunt.length > MAX_PER_SECTION * 2) break
  }
  return { owned: owned.slice(0, MAX_PER_SECTION), hunt: hunt.slice(0, MAX_PER_SECTION) }
})

function escapeHtml(s: string): string {
  return s.replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' })[c]!)
}
function highlight(text: string): string {
  const t = text ?? ''
  const q = query.value.trim()
  const esc = escapeHtml(t)
  if (!q) return esc
  const safe = q.replace(/[-/\\^$*+?.()|[\]{}]/g, '\\$&')
  try {
    return esc.replace(new RegExp(`(${safe})`, 'ig'), '<mark>$1</mark>')
  } catch {
    return esc
  }
}
function formatFaceValue(cents: number): string {
  if (cents >= 100) {
    const eur = cents / 100
    return Number.isInteger(eur) ? `${eur} €` : `${eur.toFixed(2).replace('.', ',')} €`
  }
  return `${cents} c`
}
function open(c: Coin, ctx: 'owned' | 'reference') {
  router.push(`/coin/${encodeURIComponent(c.eurioId)}?ctx=${ctx}`)
}

onMounted(() => inputEl.value?.focus())
</script>

<template>
  <section class="vault-search-root" data-scene="vault-search">
    <header class="vault-search-head">
      <div class="vault-search-field">
        <svg viewBox="0 0 24 24" aria-hidden="true"><circle cx="11" cy="11" r="7" /><path d="M20 20l-3.5-3.5" /></svg>
        <input ref="inputEl" v-model="query" type="search" placeholder="France 2012, Erasmus…" autocomplete="off" spellcheck="false" aria-label="Rechercher une pièce" data-testid="search-input" />
      </div>
      <button type="button" class="vault-search-cancel" data-testid="search-close" @click="router.push('/vault')">Annuler</button>
    </header>

    <div class="vault-search-body">
      <div v-if="!results" class="vault-search-empty">
        <h3>Cherche une pièce</h3>
        <p>Essaye <em>France 2012</em> ou <em>Erasmus</em> — on cherchera dans ton coffre et dans le catalogue.</p>
        <div class="vault-search-suggest">
          <button v-for="s in ['France', 'Erasmus', '2 euros']" :key="s" type="button" @click="query = s">{{ s }}</button>
        </div>
      </div>

      <div v-else class="vault-search-results-wrap">
        <section v-show="results.owned.length" class="vault-search-section">
          <div class="vault-search-section__title"><span>Dans ton coffre</span><span class="vault-search-section__count">{{ results.owned.length }}</span></div>
          <div class="vault-search-results">
            <button v-for="c in results.owned" :key="c.eurioId" type="button" class="vault-search-row" @click="open(c, 'owned')">
              <div class="vault-search-row__coin"><CoinImage :coin="c" :size="44" :show-label="false" /></div>
              <div class="vault-search-row__meta">
                <span class="vault-search-row__title" v-html="highlight(c.countryName)" />
                <span class="vault-search-row__sub">{{ formatFaceValue(c.faceValueCents) }} · {{ c.year ?? '—' }}<template v-if="c.theme"> · <span v-html="highlight(c.theme)" /></template></span>
              </div>
            </button>
          </div>
        </section>

        <section v-show="results.hunt.length" class="vault-search-section">
          <div class="vault-search-section__title"><span>Dans le catalogue · à chasser</span><span class="vault-search-section__count">{{ results.hunt.length }}</span></div>
          <div class="vault-search-results">
            <button v-for="c in results.hunt" :key="c.eurioId" type="button" class="vault-search-row" @click="open(c, 'reference')">
              <div class="vault-search-row__coin"><CoinImage :coin="c" :size="44" :show-label="false" /></div>
              <div class="vault-search-row__meta">
                <span class="vault-search-row__title" v-html="highlight(c.countryName)" />
                <span class="vault-search-row__sub">{{ formatFaceValue(c.faceValueCents) }} · {{ c.year ?? '—' }}<template v-if="c.theme"> · <span v-html="highlight(c.theme)" /></template></span>
              </div>
              <span class="vault-search-row__cta">à chasser</span>
            </button>
          </div>
        </section>
      </div>
    </div>
  </section>
</template>

<style src="../../styles/vault-search.css"></style>
