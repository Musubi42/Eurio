<script setup lang="ts">
// Galerie des images d'enrichment (eBay, etc.) attachées à un eurio_id.
//
// Affichée sous les thumbnails référentiels Numista, dans la colonne
// gauche de CoinDetailPage. Réutilise le style des thumbs canoniques
// (h-16 w-16, border-2). Click sur un thumb → emit `select` avec un
// payload CoinImage-compatible que le parent affichera dans le grand
// viewer (pas de lightbox locale).
//
// V1 cible les besoins immédiats : voir ce qui a été ramené par les
// scrapes, pinpointer les assignations douteuses, les renvoyer en
// review queue en bulk. Le rollback est anticipé ici (chunk D de la
// vision auto-validation §P3) parce qu'il découle naturellement de la
// galerie — sélection multiple → footer → "Re-flagger".

import { computed, onMounted, ref, watch } from 'vue'
import { useRouter } from 'vue-router'
import { Crop, ImageOff, Loader2, RotateCcw, X } from 'lucide-vue-next'
import type { CoinImage } from '@/shared/types/domain'
import CircleCropEditor from '@/features/review/components/CircleCropEditor.vue'
import {
  fetchCoinAssets,
  reflagAssetsNeedsReview,
  statusVisual,
  type CoinAsset,
  type CoinAssetsPage,
} from '../composables/useCoinAssets'

const props = defineProps<{
  eurioId: string
  /** url courante du grand viewer — sert à highlighter le thumb actif. */
  selectedUrl?: string | null
}>()

const emit = defineEmits<{
  /** Click sur une image enrichment — le parent met à jour selectedImage. */
  (e: 'select', img: CoinImage): void
}>()

const router = useRouter()

const assets = ref<CoinAsset[]>([])
const total = ref(0)
const nextOffset = ref<number | null>(null)
const loading = ref(false)
const loadingMore = ref(false)
const error = ref<string | null>(null)
const includeUnresolved = ref(false)
const selectedIds = ref<Set<string>>(new Set())
const reflagging = ref(false)
const reflagToast = ref<string | null>(null)

// Recadrage EN PLACE : l'asset en cours d'édition (overlay éditeur de cercle)
// + un jeton de cache-bust par asset. Le crop est écrasé au même chemin côté
// backend → on force le <img> à re-fetcher en changeant son `?v=` (le header
// Cache-Control: no-cache garantit alors des bytes frais). Recadrer ne change
// NI le statut NI l'eurio_id — pas de retour en review.
const recropAsset = ref<CoinAsset | null>(null)
const bust = ref<Record<string, number>>({})

function thumbSrc(a: CoinAsset): string {
  const v = bust.value[a.id]
  return v ? `${a.file_url}?v=${v}` : a.file_url
}

function onRecropSaved() {
  const a = recropAsset.value
  if (a) bust.value = { ...bust.value, [a.id]: Date.now() }
}

const PAGE_SIZE = 60

async function load() {
  loading.value = true
  error.value = null
  selectedIds.value = new Set()
  try {
    const page = await fetchCoinAssets(props.eurioId, {
      includeUnresolved: includeUnresolved.value,
      limit: PAGE_SIZE,
      offset: 0,
    })
    applyPage(page, /* append */ false)
  } catch (e) {
    error.value = (e as Error).message
  } finally {
    loading.value = false
  }
}

async function loadMore() {
  if (nextOffset.value === null || loadingMore.value) return
  loadingMore.value = true
  try {
    const page = await fetchCoinAssets(props.eurioId, {
      includeUnresolved: includeUnresolved.value,
      limit: PAGE_SIZE,
      offset: nextOffset.value,
    })
    applyPage(page, /* append */ true)
  } catch (e) {
    error.value = (e as Error).message
  } finally {
    loadingMore.value = false
  }
}

function applyPage(page: CoinAssetsPage, append: boolean) {
  assets.value = append ? [...assets.value, ...page.assets] : page.assets
  total.value = page.total
  nextOffset.value = page.next_offset
}

function toggleSelected(id: string) {
  const next = new Set(selectedIds.value)
  if (next.has(id)) next.delete(id)
  else next.add(id)
  selectedIds.value = next
}

function clearSelection() {
  selectedIds.value = new Set()
}

function onThumbClick(a: CoinAsset) {
  // Maps un CoinAsset → CoinImage (la shape attendue par le grand viewer).
  // `thumbSrc` propage le cache-bust post-recrop au viewer parent.
  emit('select', {
    url: thumbSrc(a),
    role: a.face ?? 'unknown',
    source: a.source,
  })
}

async function bulkReflag() {
  if (selectedIds.value.size === 0) return
  if (
    !window.confirm(
      `Renvoyer ${selectedIds.value.size} image(s) en review ?\n` +
        `Elles repassent en needs_review et la review s'ouvre sur ces crops ` +
        `(recadrer / re-choisir la pièce, puis valider).`,
    )
  ) {
    return
  }
  reflagging.value = true
  try {
    const ids = Array.from(selectedIds.value)
    const res = await reflagAssetsNeedsReview(ids)
    // Ouvre la review directement sur ces rows exactes (robuste aux rescués).
    if (res.review_ids && res.review_ids.length) {
      void router.push({ path: '/review/manual', query: { ids: res.review_ids.join(',') } })
      return
    }
    // Aucun item ouvrable (p.ex. tous introuvables) — feedback en place.
    reflagToast.value = `${res.n_reflagged} re-flaggée(s)` +
      (res.n_skipped ? ` · ${res.n_skipped} ignorée(s)` : '')
    setTimeout(() => (reflagToast.value = null), 3000)
    await load()
  } catch (e) {
    error.value = (e as Error).message
  } finally {
    reflagging.value = false
  }
}

const selectedCount = computed(() => selectedIds.value.size)

watch(includeUnresolved, () => void load())
watch(() => props.eurioId, () => void load())
onMounted(() => void load())
</script>

<template>
  <section class="mt-5">
    <header class="mb-2 flex items-center justify-between gap-3">
      <h3
        class="font-display text-base font-semibold tracking-tight"
        style="color: var(--ink);"
      >
        Enrichment
        <span
          v-if="!loading"
          class="ml-1.5 font-mono text-[11px] font-normal"
          style="color: var(--ink-500);"
        >
          {{ total }}
        </span>
      </h3>
      <button
        type="button"
        class="inline-flex items-center gap-1.5 rounded-md border px-2 py-1 font-mono text-[10px] uppercase tracking-wider transition-colors"
        :style="{
          borderColor: includeUnresolved ? 'var(--gold-600)' : 'var(--surface-3)',
          background: includeUnresolved
            ? 'color-mix(in srgb, var(--gold-600) 8%, var(--surface))'
            : 'var(--surface)',
          color: includeUnresolved ? 'var(--gold-600)' : 'var(--ink-500)',
        }"
        :title="includeUnresolved
          ? 'Masquer needs_review + rejected'
          : 'Afficher aussi needs_review + rejected'"
        @click="includeUnresolved = !includeUnresolved"
      >
        <span
          class="inline-block h-1.5 w-1.5 rounded-full"
          :style="{ background: includeUnresolved ? 'var(--gold-600)' : 'var(--surface-3)' }"
        />
        needs_review
      </button>
    </header>

    <!-- Loading -->
    <p
      v-if="loading"
      class="font-mono text-[11px]"
      style="color: var(--ink-400);"
    >
      …chargement.
    </p>

    <!-- Error -->
    <p
      v-else-if="error"
      class="rounded-md border px-3 py-2 text-[11px]"
      style="border-color: var(--danger); background: color-mix(in srgb, var(--danger) 4%, var(--surface)); color: var(--danger);"
    >
      {{ error }}
    </p>

    <!-- Empty -->
    <p
      v-else-if="!assets.length"
      class="flex items-center gap-1.5 text-[11px]"
      style="color: var(--ink-400);"
    >
      <ImageOff class="h-3.5 w-3.5" />
      Pas d'enrichment{{ includeUnresolved ? '' : ' validé' }} pour cette pièce.
    </p>

    <!-- Thumbs (style aligné sur les thumbs référentiels au-dessus) -->
    <div
      v-else
      class="overflow-y-auto rounded-md"
      style="max-height: calc(5 * 4rem + 4 * 0.5rem + 0.25rem);"
    >
      <div class="flex flex-wrap gap-2">
        <button
          v-for="a in assets"
          :key="a.id"
          type="button"
          class="group relative h-16 w-16 flex-shrink-0 overflow-hidden rounded-md border-2 transition-all"
          :style="{
            borderColor:
              selectedUrl === a.file_url
                ? 'var(--gold)'
                : statusVisual(a.resolution_status).ringColor,
            background:
              selectedUrl === a.file_url ? 'var(--surface-1)' : 'var(--surface)',
          }"
          :title="`${a.source} · ${a.resolution_status}` + (a.decided_by ? ` · ${a.decided_by}` : '')"
          @click="onThumbClick(a)"
        >
          <img
            :src="thumbSrc(a)"
            :alt="a.id"
            class="h-full w-full object-cover transition-transform group-hover:scale-105"
            loading="lazy"
          />

          <!-- Recadrer EN PLACE (hover, top-left) — n'altère NI statut NI
               eurio_id. Pour « mauvaise pièce », passer par Re-flagger. -->
          <span
            class="absolute left-1 top-1 flex h-5 w-5 items-center justify-center rounded opacity-0 transition-opacity group-hover:opacity-100"
            style="background: rgba(14,14,31,0.62); backdrop-filter: blur(2px);"
            title="Recadrer ce crop (en place)"
            @click.stop="recropAsset = a"
          >
            <Crop class="h-3 w-3" style="color: #fff;" />
          </span>

          <!-- Status label (bottom) — needs_review / rejected uniquement -->
          <span
            v-if="statusVisual(a.resolution_status).label"
            class="pointer-events-none absolute bottom-0 left-0 right-0 px-1 py-0.5 text-center font-mono text-[8px] uppercase tracking-wider"
            :style="{
              color: statusVisual(a.resolution_status).labelColor,
              background: 'color-mix(in srgb, var(--surface) 92%, transparent)',
            }"
          >
            {{ statusVisual(a.resolution_status).label }}
          </span>

          <!-- Selection checkbox (top-right) -->
          <span
            class="absolute right-1 top-1 flex h-4 w-4 items-center justify-center rounded border-2 transition-colors"
            :style="{
              borderColor: selectedIds.has(a.id)
                ? 'var(--indigo-700)'
                : 'rgba(255,255,255,0.7)',
              background: selectedIds.has(a.id)
                ? 'var(--indigo-700)'
                : 'rgba(14,14,31,0.4)',
              backdropFilter: 'blur(2px)',
            }"
            @click.stop="toggleSelected(a.id)"
          >
            <svg
              v-if="selectedIds.has(a.id)"
              class="h-2.5 w-2.5"
              fill="none"
              viewBox="0 0 24 24"
              stroke="white"
              stroke-width="3"
            >
              <path stroke-linecap="round" stroke-linejoin="round" d="M5 13l4 4L19 7" />
            </svg>
          </span>
        </button>

        <!-- Load more chip (inline, en fin de grid) -->
        <button
          v-if="nextOffset !== null"
          type="button"
          class="flex h-16 flex-shrink-0 items-center justify-center rounded-md border-2 border-dashed px-3 font-mono text-[10px] uppercase tracking-wider"
          style="border-color: var(--surface-3); color: var(--ink-500); background: var(--surface);"
          :disabled="loadingMore"
          @click="loadMore"
        >
          <Loader2 v-if="loadingMore" class="mr-1 h-3 w-3 animate-spin" />
          + {{ total - assets.length }}
        </button>
      </div>
    </div>

    <!-- ── Sticky footer : bulk actions ── -->
    <Teleport to="body">
      <Transition name="footer-slide">
        <div
          v-if="selectedCount > 0"
          class="fixed bottom-4 left-1/2 z-40 flex -translate-x-1/2 items-center gap-3 rounded-full border px-4 py-2 shadow-lg"
          style="background: var(--surface); border-color: var(--surface-3); box-shadow: var(--shadow-lg);"
        >
          <span class="font-mono text-[12px]" style="color: var(--ink);">
            <strong>{{ selectedCount }}</strong> sélectionnée{{ selectedCount > 1 ? 's' : '' }}
          </span>
          <span class="h-4 w-px" style="background: var(--surface-3);" />
          <button
            type="button"
            class="inline-flex items-center gap-1.5 rounded-md border px-2.5 py-1 font-mono text-[11px] uppercase tracking-wider transition-colors"
            :disabled="reflagging"
            :style="{
              borderColor: 'var(--gold-600)',
              color: 'var(--gold-600)',
              background: 'color-mix(in srgb, var(--gold-600) 6%, var(--surface))',
            }"
            @click="bulkReflag"
          >
            <RotateCcw class="h-3 w-3" />
            Renvoyer en review
          </button>
          <button
            type="button"
            class="inline-flex h-6 w-6 items-center justify-center rounded-md border transition-colors"
            style="border-color: var(--surface-3); color: var(--ink-500);"
            title="Tout déselectionner"
            @click="clearSelection"
          >
            <X class="h-3 w-3" />
          </button>
        </div>
      </Transition>
    </Teleport>

    <!-- ── Toast ── -->
    <Teleport to="body">
      <Transition name="copy-toast">
        <div
          v-if="reflagToast"
          class="fixed bottom-20 left-1/2 z-50 -translate-x-1/2 rounded-md border px-3 py-2 text-xs"
          style="background: var(--surface); border-color: var(--success); color: var(--success); box-shadow: var(--shadow-md);"
        >
          {{ reflagToast }}
        </div>
      </Transition>
    </Teleport>

    <!-- ── Éditeur de recadrage EN PLACE (overlay plein écran) ── -->
    <CircleCropEditor
      v-if="recropAsset"
      :asset-id="recropAsset.id"
      @saved="onRecropSaved"
      @close="recropAsset = null"
    />
  </section>
</template>

<style scoped>
.footer-slide-enter-active,
.footer-slide-leave-active {
  transition: transform 200ms ease-out, opacity 200ms ease-out;
}
.footer-slide-enter-from,
.footer-slide-leave-to {
  transform: translate(-50%, 100%);
  opacity: 0;
}
.copy-toast-enter-active,
.copy-toast-leave-active {
  transition: opacity 150ms ease-out;
}
.copy-toast-enter-from,
.copy-toast-leave-to {
  opacity: 0;
}
</style>
