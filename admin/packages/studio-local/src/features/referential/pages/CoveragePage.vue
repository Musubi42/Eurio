<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import {
  fetchCoverageMatrix,
  discoverCoin,
  discoverAll,
  fetchDiscoveryQueue,
  acceptDiscovery,
  rejectDiscovery,
  type CoverageMatrixResponse,
  type CoverageCell,
  type CoinMarker,
  type DiscoveryQueueItem,
} from '../composables/useReferentialApi'
import {
  fetchCoinCard,
  postCoinRefresh,
  type CoinCard,
} from '@/features/coins/composables/useCoinsApi'

const ML_API = 'http://127.0.0.1:8042'

const data = ref<CoverageMatrixResponse | null>(null)
const loading = ref(true)
const error = ref<string | null>(null)
const router = useRouter()

// Nom FR par ISO2 (lignes plus lisibles que le code seul).
const COUNTRY_FR: Record<string, string> = {
  AD: 'Andorre', AT: 'Autriche', BE: 'Belgique', BG: 'Bulgarie', CY: 'Chypre',
  DE: 'Allemagne', EE: 'Estonie', ES: 'Espagne', FI: 'Finlande', FR: 'France',
  GR: 'Grèce', HR: 'Croatie', IE: 'Irlande', IT: 'Italie', LT: 'Lituanie',
  LU: 'Luxembourg', LV: 'Lettonie', MC: 'Monaco', MT: 'Malte', NL: 'Pays-Bas',
  PT: 'Portugal', SI: 'Slovénie', SK: 'Slovaquie', SM: 'Saint-Marin', VA: 'Vatican',
}

const queue = ref<DiscoveryQueueItem[]>([])
async function loadQueue() {
  try { queue.value = await fetchDiscoveryQueue() } catch { /* file optionnelle */ }
}
async function reloadMatrix() {
  data.value = await fetchCoverageMatrix()
}

onMounted(async () => {
  try {
    await Promise.all([reloadMatrix(), loadQueue()])
  } catch (e) {
    error.value = e instanceof Error ? e.message : String(e)
  } finally {
    loading.value = false
  }
})

function cell(country: string, year: number): CoverageCell | null {
  return data.value?.cells[country]?.[String(year)] ?? null
}

// Total des pièces attendues par pays (colonne « Tot. »).
const totalByCountry = computed<Record<string, number>>(() => {
  const out: Record<string, number> = {}
  if (!data.value) return out
  for (const country of data.value.countries) {
    let n = 0
    for (const year of data.value.years) n += cell(country, year)?.markers.length ?? 0
    out[country] = n
  }
  return out
})

function markerClasses(m: CoinMarker): string[] {
  return [`m-${m.state}`, m.jo ? 'm-jo' : '', m.joint ? 'm-joint' : ''].filter(Boolean)
}

// ── Hover-card ────────────────────────────────────────────────────────────
interface HoverInfo {
  marker: CoinMarker
  country: string
  year: number
  x: number
  y: number
}
const hover = ref<HoverInfo | null>(null)
const cardCache = new Map<string, CoinCard | 'loading' | 'error'>()
const cardTick = ref(0) // force recompute du getter quand le cache se remplit

function onEnter(m: CoinMarker, country: string, year: number, ev: MouseEvent) {
  hover.value = { marker: m, country, year, x: ev.clientX, y: ev.clientY }
  if (m.eurio_id && !cardCache.has(m.eurio_id)) {
    const eid = m.eurio_id
    cardCache.set(eid, 'loading')
    cardTick.value++
    fetchCoinCard(eid)
      .then((c) => cardCache.set(eid, c))
      .catch(() => cardCache.set(eid, 'error'))
      .finally(() => cardTick.value++)
  }
}
function onLeave() {
  hover.value = null
}
const hoverCard = computed<CoinCard | 'loading' | 'error' | null>(() => {
  void cardTick.value
  const eid = hover.value?.marker.eurio_id
  return eid ? (cardCache.get(eid) ?? null) : null
})
function imgSrc(url: string | null): string | undefined {
  if (!url) return undefined
  return url.startsWith('http') ? url : `${ML_API}${url}`
}

// ── Popover épinglé (actions) ───────────────────────────────────────────
const pinned = ref<HoverInfo | null>(null)
const busy = ref<string | null>(null) // message d'action en cours
const flash = ref<string | null>(null)

function onClick(m: CoinMarker, country: string, year: number, ev: MouseEvent) {
  pinned.value = { marker: m, country, year, x: ev.clientX, y: ev.clientY }
  hover.value = null
  if (m.eurio_id && !cardCache.has(m.eurio_id)) onEnter(m, country, year, ev)
}
function unpin() { pinned.value = null }

async function doDiscover(country: string, year: number) {
  busy.value = `Recherche Numista ${country} ${year}…`
  try {
    const res = await discoverCoin(country, year)
    flash.value = res.error
      ? `Erreur : ${res.error}`
      : res.queued > 0
        ? `${res.queued} candidat(s) ajouté(s) à la review.`
        : 'Rien trouvé sur Numista pour cette cellule.'
    await loadQueue()
  } catch (e) {
    flash.value = e instanceof Error ? e.message : String(e)
  } finally {
    busy.value = null
    unpin()
  }
}

async function doDiscoverAll() {
  busy.value = 'Découverte de toutes les cellules manquantes…'
  try {
    const res = await discoverAll()
    flash.value = `${res.queued} candidat(s) en review · ${res.not_found.length} cellule(s) sans candidat Numista.`
    await loadQueue()
  } catch (e) {
    flash.value = e instanceof Error ? e.message : String(e)
  } finally {
    busy.value = null
  }
}

async function doRefresh(eurioId: string) {
  busy.value = 'Complétion (Numista)…'
  try {
    await postCoinRefresh(eurioId, 'numista')
    flash.value = 'Refetch lancé — recharge la page dans un instant.'
  } catch (e) {
    flash.value = e instanceof Error ? e.message : String(e)
  } finally {
    busy.value = null
    unpin()
  }
}

async function doAccept(item: DiscoveryQueueItem) {
  busy.value = `Ingest ${item.proposed_eurio_id}…`
  try {
    const res = await acceptDiscovery(item.id)
    flash.value = res.ok ? 'Pièce ingérée et liée ✓' : 'Échec de l\'ingest.'
    await Promise.all([reloadMatrix(), loadQueue()])
  } catch (e) {
    flash.value = e instanceof Error ? e.message : String(e)
  } finally {
    busy.value = null
  }
}

async function doReject(item: DiscoveryQueueItem) {
  await rejectDiscovery(item.id)
  await loadQueue()
}

function goToCoin(eurioId: string) {
  router.push(`/coins/${encodeURIComponent(eurioId)}`)
}
function discoverImgSrc(url: string | null): string | undefined {
  if (!url) return undefined
  return url.startsWith('http') ? url : `${ML_API}${url}`
}
</script>

<template>
  <div class="space-y-6 p-6">
    <header class="space-y-1">
      <RouterLink to="/referential" class="text-[10px] uppercase tracking-wider" style="color: var(--ink-500);">← Référentiel</RouterLink>
      <h1 class="font-display text-2xl italic font-semibold" style="color: var(--indigo-700);">
        Couverture 2 € commémoratives
      </h1>
      <p class="text-sm" style="color: var(--ink-500);">
        Une pièce = un point. Couleur = son état dans <code>eurio.db</code>.
        L'attendu vient de <code>nl.wikipedia</code> (énumération par pièce) ; le
        liseré indigo = avis officiel JO. Le rouge, c'est la liste de travail.
      </p>
    </header>

    <p v-if="loading" class="text-sm" style="color: var(--ink-500);">Chargement…</p>
    <p v-else-if="error" class="text-sm" style="color: var(--danger);">{{ error }}</p>

    <template v-else-if="data">
      <div class="flex flex-wrap gap-4">
        <div class="rounded-lg border p-4" style="border-color: var(--surface-3); background: var(--surface);">
          <div class="text-[10px] uppercase tracking-wider" style="color: var(--ink-500);">Attendu (Wikipédia)</div>
          <div class="font-mono text-xl" style="color: var(--ink-900);">{{ data.summary.expected }}</div>
        </div>
        <div class="rounded-lg border p-4" style="border-color: var(--surface-3); background: var(--surface);">
          <div class="text-[10px] uppercase tracking-wider" style="color: var(--ink-500);">Possédées</div>
          <div class="font-mono text-xl" style="color: var(--success);">{{ data.summary.owned }}</div>
        </div>
        <div v-if="data.summary.partial" class="rounded-lg border p-4" style="border-color: var(--surface-3); background: var(--surface);">
          <div class="text-[10px] uppercase tracking-wider" style="color: var(--ink-500);">Partielles</div>
          <div class="font-mono text-xl" style="color: var(--warning);">{{ data.summary.partial }}</div>
        </div>
        <div class="rounded-lg border p-4" style="border-color: var(--surface-3); background: var(--surface);">
          <div class="text-[10px] uppercase tracking-wider" style="color: var(--ink-500);">Manquantes</div>
          <div class="font-mono text-xl" style="color: var(--danger);">{{ data.summary.missing }}</div>
        </div>
        <div class="rounded-lg border p-4" style="border-color: var(--surface-3); background: var(--surface);">
          <div class="text-[10px] uppercase tracking-wider" style="color: var(--ink-500);">Avis JO officiels</div>
          <div class="font-mono text-xl" style="color: var(--indigo-700);">{{ data.summary.jo_official }}</div>
        </div>
        <div class="rounded-lg border p-4" style="border-color: var(--surface-3); background: var(--surface);">
          <div class="text-[10px] uppercase tracking-wider" style="color: var(--ink-500);">Couverture</div>
          <div class="font-mono text-xl" style="color: var(--ink-900);">{{ data.summary.coverage_pct }} %</div>
        </div>
      </div>

      <div class="flex flex-wrap items-center gap-4 text-xs" style="color: var(--ink-500);">
        <span class="flex items-center gap-1.5"><span class="dot m-have" /> possédée</span>
        <span class="flex items-center gap-1.5"><span class="dot m-partial" /> partielle</span>
        <span class="flex items-center gap-1.5"><span class="dot m-missing" /> manquante</span>
        <span class="flex items-center gap-1.5"><span class="dot m-planned" /> planifiée</span>
        <span class="flex items-center gap-1.5"><span class="dot m-have m-jo" /> avis JO officiel</span>
        <span class="flex items-center gap-1.5"><span class="dot m-have m-joint" /> émission commune</span>
        <span class="flex items-center gap-1.5"><span class="dot dot-oz" /> hors zone euro</span>
        <span>– = aucune émission</span>
      </div>

      <div class="rounded-lg border overflow-auto" style="border-color: var(--surface-3); background: var(--surface); max-height: 78vh;">
        <table class="text-xs" style="border-collapse: separate; border-spacing: 0;">
          <thead>
            <tr>
              <th class="sticky left-0 top-0 z-20 px-3 py-2 text-left font-semibold" style="background: var(--surface-2); color: var(--ink-700);">Pays</th>
              <th class="sticky top-0 z-10 px-2 py-2 text-right font-mono" style="background: var(--surface-2); color: var(--ink-500);">Tot.</th>
              <th v-for="y in data.years" :key="y" class="sticky top-0 z-10 px-2 py-2 text-center font-mono" style="background: var(--surface-2); color: var(--ink-700); min-width: 3.2rem;">{{ y }}</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="country in data.countries" :key="country">
              <th class="sticky left-0 z-10 px-3 py-1 text-left font-semibold whitespace-nowrap" style="background: var(--surface-2); color: var(--ink-900);">
                <span class="font-mono">{{ country }}</span>
                <span class="ml-1.5 font-normal" style="color: var(--ink-500);">{{ COUNTRY_FR[country] ?? '' }}</span>
              </th>
              <td class="px-2 py-1 text-right font-mono" style="color: var(--ink-400);">{{ totalByCountry[country] }}</td>
              <td
                v-for="y in data.years"
                :key="y"
                class="px-1.5 py-1 align-middle"
                :class="{ oz: cell(country, y)?.out_of_zone && !cell(country, y)?.markers.length }"
              >
                <div v-if="cell(country, y)?.markers.length" class="cell">
                  <span
                    v-for="(m, i) in cell(country, y)!.markers"
                    :key="i"
                    class="dot clickable"
                    :class="markerClasses(m)"
                    @mouseenter="onEnter(m, country, y, $event)"
                    @mouseleave="onLeave"
                    @click="onClick(m, country, y, $event)"
                  />
                </div>
                <span v-else-if="!cell(country, y)?.out_of_zone" class="none">–</span>
              </td>
            </tr>
          </tbody>
        </table>
      </div>

      <!-- Bandeau d'action en cours / résultat -->
      <p v-if="busy" class="text-xs" style="color: var(--indigo-700);">⏳ {{ busy }}</p>
      <p v-else-if="flash" class="text-xs" style="color: var(--ink-700);">{{ flash }}</p>

      <!-- Section review des découvertes Numista -->
      <section class="space-y-3">
        <div class="flex items-center gap-3">
          <h2 class="font-display text-lg italic font-semibold" style="color: var(--indigo-700);">
            Review des découvertes
          </h2>
          <span class="font-mono text-xs" style="color: var(--ink-500);">{{ queue.length }} en attente</span>
          <button
            class="rounded-full border px-3 py-1 font-mono text-[10px]"
            style="border-color: var(--surface-3); color: var(--indigo-700);"
            :disabled="!!busy"
            @click="doDiscoverAll"
          >
            Découvrir tout (Numista) →
          </button>
        </div>
        <p class="text-xs" style="color: var(--ink-500);">
          Candidats Numista pour les cellules rouges. Vérifie image + titre, puis
          accepte (ingest complet) ou rejette. Clique aussi un point rouge de la
          matrice pour lancer une recherche ciblée sur sa cellule.
        </p>

        <p v-if="!queue.length" class="text-sm" style="color: var(--ink-400);">
          Aucun candidat en review. Lance « Découvrir tout » ou clique une cellule manquante.
        </p>
        <div v-else class="grid gap-3" style="grid-template-columns: repeat(auto-fill, minmax(280px, 1fr));">
          <div
            v-for="item in queue"
            :key="item.id"
            class="flex gap-3 rounded-lg border p-3"
            style="border-color: var(--surface-3); background: var(--surface);"
          >
            <div class="rc-img">
              <img v-if="discoverImgSrc(item.image_url)" :src="discoverImgSrc(item.image_url)" alt="" />
              <div v-else class="hc-img-ph">∅</div>
            </div>
            <div class="min-w-0 flex-1">
              <div class="text-[13px] font-semibold" style="color: var(--ink-900);">{{ item.numista_title }}</div>
              <div class="mt-0.5 font-mono text-[10px]" style="color: var(--ink-400);">
                {{ item.country }} · {{ item.year }} · n°{{ item.numista_id }}
                <span v-if="item.is_variant" style="color: var(--warning);"> · variante</span>
              </div>
              <div class="mt-1 text-[11px]" style="color: var(--ink-500);">
                → <code>{{ item.proposed_eurio_id }}</code>
              </div>
              <div v-if="item.theme_wiki" class="mt-0.5 text-[11px]" style="color: var(--ink-400);">
                comble : {{ item.theme_wiki }}
              </div>
              <div class="mt-2 flex gap-2">
                <button
                  class="rounded border px-2 py-1 text-[11px]"
                  style="border-color: var(--success); color: var(--success);"
                  :disabled="!!busy"
                  @click="doAccept(item)"
                >✓ Accepter</button>
                <button
                  class="rounded border px-2 py-1 text-[11px]"
                  style="border-color: var(--danger); color: var(--danger);"
                  :disabled="!!busy"
                  @click="doReject(item)"
                >✕ Rejeter</button>
              </div>
            </div>
          </div>
        </div>
      </section>
    </template>

    <!-- Hover-card (aperçu, suit le curseur) -->
    <div
      v-if="hover && !pinned"
      class="hovercard"
      :style="{ left: Math.min(hover.x + 16, 1100) + 'px', top: hover.y + 16 + 'px' }"
    >
      <template v-if="hover.marker.eurio_id">
        <div class="hc-img">
          <img
            v-if="hoverCard && hoverCard !== 'loading' && hoverCard !== 'error' && imgSrc(hoverCard.image_url)"
            :src="imgSrc((hoverCard as CoinCard).image_url)"
            alt=""
          />
          <div v-else class="hc-img-ph">{{ hoverCard === 'loading' ? '…' : '∅' }}</div>
        </div>
        <div class="hc-body">
          <div class="hc-title">
            {{ hoverCard && hoverCard !== 'loading' && hoverCard !== 'error'
              ? ((hoverCard as CoinCard).title_fr || hover.marker.theme)
              : hover.marker.theme }}
          </div>
          <div class="hc-meta">
            {{ hover.country }} · {{ hover.year }}
            <span v-if="hover.marker.jo" class="hc-jo">· avis JO</span>
            <span v-if="hover.marker.joint">· commune</span>
          </div>
        </div>
      </template>
      <template v-else>
        <div class="hc-body">
          <div class="hc-title">{{ hover.marker.theme }}</div>
          <div class="hc-meta hc-missing">{{ hover.country }} · {{ hover.year }} · manquante — à découvrir</div>
        </div>
      </template>
    </div>

    <!-- Popover épinglé (au clic) avec actions -->
    <template v-if="pinned">
      <div class="pin-backdrop" @click="unpin" />
      <div
        class="hovercard pinned"
        :style="{ left: Math.min(pinned.x + 16, 1100) + 'px', top: pinned.y + 16 + 'px' }"
      >
        <div v-if="pinned.marker.eurio_id" class="hc-img">
          <img
            v-if="hoverCard && hoverCard !== 'loading' && hoverCard !== 'error' && imgSrc((hoverCard as CoinCard).image_url)"
            :src="imgSrc((hoverCard as CoinCard).image_url)"
            alt=""
          />
          <div v-else class="hc-img-ph">{{ hoverCard === 'loading' ? '…' : '∅' }}</div>
        </div>
        <div class="hc-body">
          <div class="hc-title">
            {{ pinned.marker.eurio_id && hoverCard && hoverCard !== 'loading' && hoverCard !== 'error'
              ? ((hoverCard as CoinCard).title_fr || pinned.marker.theme)
              : pinned.marker.theme }}
          </div>
          <div class="hc-meta">{{ pinned.country }} · {{ pinned.year }}</div>
          <div class="mt-2 flex flex-col gap-1.5">
            <button v-if="pinned.marker.eurio_id" class="pin-btn" @click="goToCoin(pinned.marker.eurio_id!)">
              Ouvrir la fiche →
            </button>
            <button
              v-if="pinned.marker.eurio_id && pinned.marker.state === 'partial'"
              class="pin-btn"
              :disabled="!!busy"
              @click="doRefresh(pinned.marker.eurio_id!)"
            >Compléter (Numista)</button>
            <button
              v-if="!pinned.marker.eurio_id"
              class="pin-btn pin-btn-primary"
              :disabled="!!busy"
              @click="doDiscover(pinned.country, pinned.year)"
            >Découvrir sur Numista</button>
          </div>
        </div>
      </div>
    </template>
  </div>
</template>

<style scoped>
.cell {
  display: flex;
  flex-wrap: wrap;
  gap: 4px;
  justify-content: center;
  align-items: center;
  max-width: 4.4rem;
  margin: 0 auto;
}
.none {
  display: block;
  text-align: center;
  color: var(--ink-300);
}
td.oz {
  background: repeating-linear-gradient(
    45deg, var(--surface-2), var(--surface-2) 3px, var(--surface) 3px, var(--surface) 6px
  );
}

/* Marqueur = un carré arrondi par pièce, coloré par état. */
.dot {
  display: inline-block;
  width: 13px;
  height: 13px;
  border-radius: 4px;
  position: relative;
}
.dot.clickable { cursor: pointer; }
.dot.clickable:hover { transform: scale(1.25); z-index: 2; }
.m-have { background: var(--success); }
.m-partial { background: var(--warning); }
.m-missing { background: var(--danger); }
.m-planned { background: transparent; border: 1.6px dashed var(--danger); }
.dot-oz {
  background: repeating-linear-gradient(
    45deg, var(--surface-2), var(--surface-2) 2px, var(--surface) 2px, var(--surface) 4px
  );
  border: 1px solid var(--surface-3);
}
/* Avis JO officiel : liseré indigo. */
.m-jo { box-shadow: 0 0 0 1.6px var(--surface), 0 0 0 3px var(--indigo-700); }
/* Émission commune : losange. */
.m-joint { border-radius: 3px; transform: rotate(45deg); }
.m-joint.clickable:hover { transform: rotate(45deg) scale(1.25); }

.hovercard {
  position: fixed;
  z-index: 50;
  display: flex;
  gap: 10px;
  align-items: center;
  max-width: 320px;
  padding: 10px 12px;
  border-radius: 10px;
  border: 1px solid var(--surface-3);
  background: var(--surface);
  box-shadow: 0 8px 24px rgba(14, 14, 31, 0.18);
  pointer-events: none;
}
.hc-img {
  width: 56px;
  height: 56px;
  flex-shrink: 0;
  border-radius: 8px;
  background: var(--paper);
  display: flex;
  align-items: center;
  justify-content: center;
  overflow: hidden;
}
.hc-img img { width: 100%; height: 100%; object-fit: contain; }
.hc-img-ph { color: var(--ink-300); font-size: 18px; }
.hc-body { min-width: 0; }
.hc-title {
  font-size: 12.5px;
  font-weight: 600;
  color: var(--ink-900);
  line-height: 1.3;
}
.hc-meta { font-size: 11px; color: var(--ink-500); margin-top: 2px; }
.hc-jo { color: var(--indigo-700); }
.hc-missing { color: var(--danger); }

/* Popover épinglé : cliquable (boutons), au-dessus du backdrop. */
.hovercard.pinned {
  pointer-events: auto;
  align-items: flex-start;
  z-index: 60;
}
.pin-backdrop { position: fixed; inset: 0; z-index: 55; }
.pin-btn {
  border: 1px solid var(--surface-3);
  border-radius: 6px;
  padding: 4px 10px;
  font-size: 11px;
  color: var(--ink-700);
  background: var(--surface);
  cursor: pointer;
  text-align: left;
}
.pin-btn:hover { background: var(--surface-2); }
.pin-btn:disabled { opacity: 0.5; cursor: default; }
.pin-btn-primary { border-color: var(--indigo-700); color: var(--indigo-700); }

/* Vignette des cartes de review. */
.rc-img {
  width: 64px;
  height: 64px;
  flex-shrink: 0;
  border-radius: 8px;
  background: var(--paper);
  display: flex;
  align-items: center;
  justify-content: center;
  overflow: hidden;
}
.rc-img img { width: 100%; height: 100%; object-fit: contain; }
</style>
