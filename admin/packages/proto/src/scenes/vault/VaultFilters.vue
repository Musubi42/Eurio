<script setup lang="ts">
/* Scène vault-filters — feuille de filtres (pays/année/faciale/type/rareté/
 * condition), persistée dans le store. Port de vault-filters.html/.js. */
import { computed, reactive } from 'vue'
import { useRouter } from 'vue-router'
import { allCountries, getCoin } from '@/api'
import { defaultVaultFilters, useCollectionStore } from '@/stores/collection'
import type { VaultFilters } from '@/stores/collection'

const router = useRouter()
const store = useCollectionStore()

// Copie locale réactive, commitée dans le store à chaque changement.
const filters = reactive<VaultFilters>(structuredClone({ ...defaultVaultFilters(), ...store.prefs.vaultFilters }))

const countries = allCountries()

const FACE_VALUES = [
  { v: 1, label: '1 c' }, { v: 2, label: '2 c' }, { v: 5, label: '5 c' }, { v: 10, label: '10 c' },
  { v: 20, label: '20 c' }, { v: 50, label: '50 c' }, { v: 100, label: '1 €' }, { v: 200, label: '2 €' },
]
const TYPES = [
  { v: 'circulation', label: 'Circulation' },
  { v: 'commemorative', label: 'Commémorative' },
  { v: 'common', label: 'Émission commune' },
]
const RARITIES = [
  { v: 'common', label: 'Commune' }, { v: 'uncommon', label: 'Peu courante' },
  { v: 'rare', label: 'Rare' }, { v: 'ultra', label: 'Très rare' },
]
const CONDITIONS = [
  { v: 'UNC', label: 'UNC' }, { v: 'SUP', label: 'SUP' }, { v: 'TTB', label: 'TTB' },
  { v: 'TB', label: 'TB' }, { v: 'B', label: 'B' }, { v: 'unknown', label: 'Non renseignée' },
]

function commit() {
  store.setVaultFilters(structuredClone({ ...filters }))
}
function toggleStr(arr: string[], v: string) {
  const i = arr.indexOf(v)
  if (i >= 0) arr.splice(i, 1)
  else arr.push(v)
  commit()
}
function toggleNum(arr: number[], v: number) {
  const i = arr.indexOf(v)
  if (i >= 0) arr.splice(i, 1)
  else arr.push(v)
  commit()
}
function clampYear(y: number): number {
  if (Number.isNaN(y)) return 1999
  return Math.max(1999, Math.min(2026, Math.round(y)))
}
function onYearMin(e: Event) {
  filters.yearMin = clampYear(Number((e.target as HTMLInputElement).value))
  commit()
}
function onYearMax(e: Event) {
  filters.yearMax = clampYear(Number((e.target as HTMLInputElement).value))
  commit()
}
function reset() {
  Object.assign(filters, defaultVaultFilters())
  commit()
}

// Nombre de pièces du coffre qui matchent.
const count = computed(() => {
  return store.collection.filter((entry) => {
    const coin = getCoin(entry.eurioId)
    if (!coin) return false
    if (filters.countries.length && !filters.countries.includes(coin.country)) return false
    if (filters.faceValueCents.length && !filters.faceValueCents.includes(coin.faceValueCents)) return false
    if (filters.yearMin && coin.year && coin.year < filters.yearMin) return false
    if (filters.yearMax && coin.year && coin.year > filters.yearMax) return false
    if (filters.types.length) {
      const t = coin.isCommemorative ? 'commemorative' : 'circulation'
      if (!filters.types.includes(t)) return false
    }
    return true
  }).length
})
</script>

<template>
  <section class="vault-filters-root" data-scene="vault-filters">
    <header class="vault-filters-head">
      <h2 class="vault-filters-head__title">Filtres</h2>
      <button type="button" class="vault-filters-close" aria-label="Fermer" data-testid="filters-close" @click="router.push('/vault')">
        <svg viewBox="0 0 24 24" aria-hidden="true"><path d="M6 6l12 12M18 6L6 18" /></svg>
      </button>
    </header>

    <div class="vault-filters-body">
      <section class="vault-filters-section">
        <div class="vault-filters-section__title">Pays</div>
        <div class="vault-filters-chips">
          <button v-for="c in countries" :key="c" type="button" class="vault-filters-chip" :aria-pressed="filters.countries.includes(c)" @click="toggleStr(filters.countries, c)">{{ c.toUpperCase() }}</button>
        </div>
      </section>

      <section class="vault-filters-section">
        <div class="vault-filters-section__title">Année</div>
        <div class="vault-filters-year">
          <label class="vault-filters-year__chip">
            <span class="vault-filters-year__label">De</span>
            <input type="number" class="vault-filters-year__value tabular" min="1999" max="2026" :value="filters.yearMin" @change="onYearMin" />
          </label>
          <span class="vault-filters-year__dash" aria-hidden="true"></span>
          <label class="vault-filters-year__chip">
            <span class="vault-filters-year__label">À</span>
            <input type="number" class="vault-filters-year__value tabular" min="1999" max="2026" :value="filters.yearMax" @change="onYearMax" />
          </label>
        </div>
      </section>

      <section class="vault-filters-section">
        <div class="vault-filters-section__title">Valeur faciale</div>
        <div class="vault-filters-chips">
          <button v-for="f in FACE_VALUES" :key="f.v" type="button" class="vault-filters-chip" :aria-pressed="filters.faceValueCents.includes(f.v)" @click="toggleNum(filters.faceValueCents, f.v)">{{ f.label }}</button>
        </div>
      </section>

      <section class="vault-filters-section">
        <div class="vault-filters-section__title">Type</div>
        <div class="vault-filters-chips">
          <button v-for="t in TYPES" :key="t.v" type="button" class="vault-filters-chip" :aria-pressed="filters.types.includes(t.v)" @click="toggleStr(filters.types, t.v)">{{ t.label }}</button>
        </div>
      </section>

      <section class="vault-filters-section">
        <div class="vault-filters-section__title">Rareté</div>
        <div class="vault-filters-chips">
          <button v-for="r in RARITIES" :key="r.v" type="button" class="vault-filters-chip" :aria-pressed="filters.rarities.includes(r.v)" @click="toggleStr(filters.rarities, r.v)">{{ r.label }}</button>
        </div>
      </section>

      <section class="vault-filters-section">
        <div class="vault-filters-section__title">Condition</div>
        <div class="vault-filters-chips">
          <button v-for="c in CONDITIONS" :key="c.v" type="button" class="vault-filters-chip" :aria-pressed="filters.conditions.includes(c.v)" @click="toggleStr(filters.conditions, c.v)">{{ c.label }}</button>
        </div>
      </section>
    </div>

    <footer class="vault-filters-foot">
      <button type="button" class="btn btn-ghost vault-filters-reset" data-testid="filters-reset" @click="reset">Réinitialiser</button>
      <button type="button" class="btn btn-primary" data-testid="filters-apply" @click="router.push('/vault')"><span>Voir <span>{{ count }}</span> pièces</span></button>
    </footer>
  </section>
</template>

<style src="../../styles/vault-filters.css"></style>
