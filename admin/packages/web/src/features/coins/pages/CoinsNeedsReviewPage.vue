<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref, watch } from 'vue'
import {
  AlertTriangle, ArrowRightLeft, Check, ChevronRight, FilePen, Inbox,
  Loader2, Search, ShieldCheck, Trash2, WifiOff, X,
} from 'lucide-vue-next'

import {
  HINT_LABEL, HINT_TAGLINE, countryFlag, useCoinsReview,
  type CatalogHit, type ReviewHint, type ReviewItem,
  type RebindPayload, type VerifyParentPayload, type UncertainPayload,
} from '../composables/useCoinsReview'

const {
  loading, saving, error, stats, grouped, selected,
  fetchQueue, searchNumista, rebind, noCoverage, deleteRedirect,
  select, selectRelative,
} = useCoinsReview()

// ─── Local UI state ─────────────────────────────────────────────────────────

const searchQuery = ref('')
const searchHits = ref<CatalogHit[]>([])
const searchLoading = ref(false)
const includeLive = ref(false)
const searchInputRef = ref<HTMLInputElement | null>(null)
const errorBanner = ref<string | null>(null)

const showDeleteModal = ref(false)
const deleteTargetEid = ref('')

const showNoCoverageModal = ref(false)
const noCoverageNote = ref('')

// ─── Numista catalog URLs ───────────────────────────────────────────────────

function numistaUrl(nid: string | number | null | undefined): string | null {
  if (nid === null || nid === undefined || nid === '') return null
  return `https://en.numista.com/catalogue/pieces${nid}.html`
}

// ─── Auto-fill search on selection change ───────────────────────────────────

watch(selected, (cur, prev) => {
  if (!cur) return
  if (cur.eurio_id === prev?.eurio_id) return
  // Clear search state
  searchHits.value = []
  errorBanner.value = null
  // Auto-prefill search for rebind cases with the lost catalog name (helps the
  // admin immediately see candidates rather than having to retype the theme).
  if (cur.review_action_hint === 'rebind') {
    const payload = cur.review_payload as RebindPayload
    const auditName = payload?.audit_old_catalog_name ?? ''
    searchQuery.value = extractThemeWords(auditName)
    void runSearch()
  } else {
    searchQuery.value = ''
  }
}, { immediate: false })

function extractThemeWords(catalogName: string): string {
  // Numista names look like "2 Euros (Theme words here)". Extract parenthesized
  // theme. If absent, fall back to the full name.
  const m = /\(([^)]+)\)/.exec(catalogName)
  return (m ? m[1] : catalogName).trim()
}

async function runSearch() {
  if (!selected.value) return
  searchLoading.value = true
  try {
    searchHits.value = await searchNumista({
      q: searchQuery.value.trim() || undefined,
      country: selected.value.country,
      year: selected.value.year,
      includeLive: includeLive.value,
      limit: 12,
    })
  } catch (e) {
    errorBanner.value = e instanceof Error ? e.message : String(e)
  } finally {
    searchLoading.value = false
  }
}

// ─── Actions ────────────────────────────────────────────────────────────────

async function doRebind(nid: string, nativeUrl?: string | null) {
  if (!selected.value || saving.value) return
  try {
    await rebind(selected.value.eurio_id, nid, nativeUrl ?? null)
    searchHits.value = []
    searchQuery.value = ''
    errorBanner.value = null
  } catch (e) {
    errorBanner.value = e instanceof Error ? e.message : String(e)
  }
}

async function doConfirmCurrent() {
  if (!selected.value || saving.value) return
  const nid = currentNumistaId(selected.value)
  if (!nid) {
    errorBanner.value = 'pas de current_numista_id — utiliser Rebind à la place'
    return
  }
  await doRebind(String(nid))
}

async function doNoCoverage() {
  if (!selected.value || saving.value) return
  showNoCoverageModal.value = false
  try {
    await noCoverage(selected.value.eurio_id, noCoverageNote.value || undefined)
    noCoverageNote.value = ''
    errorBanner.value = null
  } catch (e) {
    errorBanner.value = e instanceof Error ? e.message : String(e)
  }
}

async function doDeleteRedirect() {
  if (!selected.value || saving.value) return
  if (!deleteTargetEid.value.trim()) return
  try {
    await deleteRedirect(selected.value.eurio_id, deleteTargetEid.value.trim())
    showDeleteModal.value = false
    deleteTargetEid.value = ''
    errorBanner.value = null
  } catch (e) {
    errorBanner.value = e instanceof Error ? e.message : String(e)
  }
}

function currentNumistaId(item: ReviewItem): string | number | null {
  const x = item.cross_refs?.numista_id as string | number | null | undefined
  return x ?? null
}

// ─── Keyboard ───────────────────────────────────────────────────────────────

function onKeydown(e: KeyboardEvent) {
  const tag = (e.target as HTMLElement | null)?.tagName
  if (tag === 'INPUT' || tag === 'TEXTAREA') return
  if (showDeleteModal.value || showNoCoverageModal.value) {
    if (e.key === 'Escape') {
      showDeleteModal.value = false
      showNoCoverageModal.value = false
    }
    return
  }
  const k = e.key.toLowerCase()

  if (k === 'j' || e.key === 'ArrowDown') { selectRelative(1); e.preventDefault(); return }
  if (k === 'k' || e.key === 'ArrowUp')   { selectRelative(-1); e.preventDefault(); return }

  // Digit picks the nth candidate (rebind / uncertain)
  if (/^[1-9]$/.test(e.key)) {
    const idx = parseInt(e.key, 10) - 1
    const hit = searchHits.value[idx]
    if (hit) { void doRebind(hit.numista_id); e.preventDefault(); return }
  }

  if (k === 'c') {
    // primary action depends on hint
    const item = selected.value
    if (!item) return
    if (item.review_action_hint === 'rebind') {
      searchInputRef.value?.focus()
    } else {
      void doConfirmCurrent()
    }
    e.preventDefault()
    return
  }
  if (k === 'r') { searchInputRef.value?.focus(); e.preventDefault(); return }
  if (k === 'n') { showNoCoverageModal.value = true; e.preventDefault(); return }
  if (k === 'd') { showDeleteModal.value = true; e.preventDefault(); return }
}

onMounted(() => {
  window.addEventListener('keydown', onKeydown)
  void fetchQueue()
})
onUnmounted(() => window.removeEventListener('keydown', onKeydown))

// ─── Hint chip styling ──────────────────────────────────────────────────────

const HINT_STYLES: Record<ReviewHint, { chip: string; primary: string; tagBg: string }> = {
  rebind: {
    chip: 'background: color-mix(in srgb, var(--indigo-700) 10%, white); color: var(--indigo-700);',
    primary: 'background: var(--indigo-700); color: white;',
    tagBg: 'background: color-mix(in srgb, var(--indigo-700) 10%, white);',
  },
  verify_parent: {
    chip: 'background: color-mix(in srgb, var(--gold) 16%, white); color: var(--gold-deep);',
    primary: 'background: var(--gold-deep); color: white;',
    tagBg: 'background: color-mix(in srgb, var(--gold) 18%, white);',
  },
  confirm_or_rematch_uncertain: {
    chip: 'background: color-mix(in srgb, var(--warning) 14%, white); color: var(--warning);',
    primary: 'background: var(--warning); color: white;',
    tagBg: 'background: color-mix(in srgb, var(--warning) 14%, white);',
  },
}

function primaryStyle(h: ReviewHint) { return HINT_STYLES[h].primary }

// Sample images helper
function obverseImage(item: ReviewItem): string | null {
  const imgs = item.images
  if (!imgs) return null
  if (Array.isArray(imgs)) {
    const obv = imgs.find((i: any) => i?.role === 'obverse')
    return obv?.url ?? (imgs[0] as any)?.url ?? null
  }
  if (typeof imgs === 'object') return (imgs as any).obverse ?? null
  return null
}

const primaryHint = computed(() => selected.value?.review_action_hint ?? 'rebind')
const primaryLabel = computed(() => {
  if (!selected.value) return ''
  const h = selected.value.review_action_hint
  if (h === 'rebind') return 'Focus search'
  if (h === 'verify_parent') return 'Confirmer as-is'
  return 'Confirmer current'
})
</script>

<template>
  <div class="flex h-full flex-col" style="background: var(--surface);">

    <!-- ── Header ─────────────────────────────────────────────────────── -->
    <header class="flex items-center justify-between border-b px-8 py-5"
            style="border-color: var(--border); background: var(--paper);">
      <div class="flex items-baseline gap-3">
        <h1 class="font-display text-2xl" style="color: var(--ink); font-weight: 600;">
          Revue référentiel
        </h1>
        <span class="font-mono text-xs uppercase tracking-wider" style="color: var(--ink-500);">
          / chunk 3e
        </span>
      </div>

      <div class="flex items-center gap-2 text-xs">
        <span class="rounded-full px-3 py-1 font-mono"
              :style="HINT_STYLES.rebind.chip">{{ stats.rebind }} rebind</span>
        <span class="rounded-full px-3 py-1 font-mono"
              :style="HINT_STYLES.verify_parent.chip">{{ stats.verify_parent }} verify</span>
        <span class="rounded-full px-3 py-1 font-mono"
              :style="HINT_STYLES.confirm_or_rematch_uncertain.chip">{{ stats.confirm_or_rematch_uncertain }} uncertain</span>
        <span class="ml-2 text-[11px] uppercase tracking-wider" style="color: var(--ink-500);">
          {{ stats.total }} en queue
        </span>
      </div>
    </header>

    <!-- ── Error banner ─────────────────────────────────────────────────── -->
    <div v-if="errorBanner"
         class="flex items-center gap-2 border-b px-8 py-2 text-sm"
         style="border-color: var(--danger); background: color-mix(in srgb, var(--danger) 6%, white); color: var(--danger);">
      <AlertTriangle class="h-4 w-4" />
      <span class="font-mono text-xs">{{ errorBanner }}</span>
      <button class="ml-auto text-xs underline" @click="errorBanner = null">dismiss</button>
    </div>

    <!-- ── API offline ──────────────────────────────────────────────────── -->
    <div v-if="error" class="flex flex-1 flex-col items-center justify-center gap-3 text-sm"
         style="color: var(--ink-500);">
      <WifiOff class="h-8 w-8 opacity-40" />
      <p class="font-mono">{{ error }}</p>
      <p class="text-xs opacity-60">Lancer <code>go-task ml:api</code> sur le port 8042.</p>
      <button @click="fetchQueue"
              class="mt-2 rounded-md px-3 py-1.5 text-xs font-medium"
              style="background: var(--indigo-700); color: white;">
        Réessayer
      </button>
    </div>

    <!-- ── Loading ──────────────────────────────────────────────────────── -->
    <div v-else-if="loading" class="flex flex-1 items-center justify-center text-sm"
         style="color: var(--ink-500);">
      <Loader2 class="mr-2 h-4 w-4 animate-spin" /> Chargement…
    </div>

    <!-- ── Done ─────────────────────────────────────────────────────────── -->
    <div v-else-if="stats.total === 0"
         class="flex flex-1 flex-col items-center justify-center gap-3 px-8 py-16 text-center">
      <ShieldCheck class="h-12 w-12" style="color: var(--success);" />
      <h2 class="font-display text-3xl" style="color: var(--ink);">Queue vide</h2>
      <p class="max-w-md text-sm" style="color: var(--ink-500);">
        Tous les coins en review ont été résolus. Le référentiel V2 est propre.
      </p>
    </div>

    <!-- ── Main 2-pane layout ───────────────────────────────────────────── -->
    <div v-else class="flex flex-1 overflow-hidden">

      <!-- ── LEFT: grouped list ─────────────────────────────────────── -->
      <aside class="flex w-[340px] flex-shrink-0 flex-col overflow-hidden border-r"
             style="border-color: var(--border); background: var(--surface-1);">

        <div v-for="group in grouped" :key="group.hint" class="flex flex-col">
          <h2 v-if="group.items.length > 0"
              class="px-5 pt-5 pb-2 font-display text-xs uppercase tracking-[0.18em]"
              :style="{ color: 'var(--ink-500)' }">
            <span class="inline-block rounded-sm px-1.5 py-0.5 mr-2 align-middle"
                  :style="HINT_STYLES[group.hint].chip" style="font-family: var(--font-mono); font-size: 10px;">
              {{ group.items.length }}
            </span>
            {{ HINT_LABEL[group.hint] }}
          </h2>

          <ul class="mb-1">
            <li v-for="it in group.items" :key="it.eurio_id">
              <button
                class="group flex w-full items-start gap-3 px-5 py-2.5 text-left transition-colors"
                :style="selected?.eurio_id === it.eurio_id
                  ? 'background: var(--paper); box-shadow: inset 3px 0 0 var(--indigo-700);'
                  : 'background: transparent;'"
                @click="select(it.eurio_id)"
              >
                <span class="text-base leading-none mt-0.5">{{ countryFlag(it.country) }}</span>
                <span class="flex-1 min-w-0">
                  <span class="block truncate font-mono text-[12px]"
                        :style="selected?.eurio_id === it.eurio_id ? 'color: var(--ink);' : 'color: var(--ink-500);'">
                    {{ it.eurio_id }}
                  </span>
                  <span class="block truncate text-[11px]" style="color: var(--ink-500);">
                    {{ it.theme || it.design_description || '—' }}
                  </span>
                </span>
                <ChevronRight v-if="selected?.eurio_id === it.eurio_id"
                              class="h-4 w-4 mt-1 flex-shrink-0"
                              :style="{ color: 'var(--indigo-700)' }" />
              </button>
            </li>
          </ul>
        </div>
      </aside>

      <!-- ── RIGHT: detail panel ─────────────────────────────────────── -->
      <section class="flex flex-1 flex-col overflow-y-auto">

        <div v-if="!selected" class="flex flex-1 items-center justify-center text-sm" style="color: var(--ink-500);">
          Sélectionner un cas dans la liste.
        </div>

        <div v-else class="flex flex-1 flex-col">

          <!-- Hint banner -->
          <div class="border-b px-8 py-3 flex items-center gap-3"
               style="border-color: var(--border);"
               :style="`border-color: var(--border); ${HINT_STYLES[selected.review_action_hint].tagBg}`">
            <span class="font-mono text-[10px] uppercase tracking-widest px-2 py-1 rounded"
                  :style="HINT_STYLES[selected.review_action_hint].chip">
              {{ HINT_LABEL[selected.review_action_hint] }}
            </span>
            <span class="text-xs" style="color: var(--ink-700);">
              {{ HINT_TAGLINE[selected.review_action_hint] }}
            </span>
          </div>

          <!-- Coin source card -->
          <div class="px-8 pt-8">
            <div class="flex items-start gap-6 border rounded-lg p-6"
                 style="border-color: var(--border); background: var(--paper);">
              <div class="w-32 h-32 shrink-0 rounded-md overflow-hidden flex items-center justify-center"
                   style="background: var(--surface-2); border: 1px solid var(--border);">
                <img v-if="obverseImage(selected)" :src="obverseImage(selected)!" class="w-full h-full object-cover" />
                <Inbox v-else class="h-8 w-8 opacity-30" />
              </div>
              <div class="flex-1 min-w-0">
                <div class="flex items-baseline gap-3">
                  <h2 class="font-display text-xl" style="color: var(--ink); font-weight: 600;">
                    {{ selected.theme || selected.design_description || selected.eurio_id }}
                  </h2>
                  <span class="text-base">{{ countryFlag(selected.country) }}</span>
                </div>
                <div class="mt-1 font-mono text-xs" style="color: var(--ink-500);">
                  {{ selected.eurio_id }}
                </div>
                <div class="mt-3 flex flex-wrap gap-2 text-xs" style="color: var(--ink-500);">
                  <span class="rounded-full px-2.5 py-0.5" style="background: var(--surface-2);">
                    {{ selected.country }} · {{ selected.year }}
                  </span>
                  <span v-if="selected.is_commemorative" class="rounded-full px-2.5 py-0.5"
                        style="background: color-mix(in srgb, var(--gold) 16%, white); color: var(--gold-deep);">
                    commémorative
                  </span>
                  <span v-if="selected.design_group_id" class="rounded-full px-2.5 py-0.5 font-mono"
                        style="background: var(--surface-2);">
                    dg · {{ selected.design_group_id }}
                  </span>
                  <span v-if="currentNumistaId(selected) !== null"
                        class="rounded-full px-2.5 py-0.5 font-mono"
                        style="background: var(--surface-2);">
                    numista · {{ currentNumistaId(selected) }}
                  </span>
                  <span v-else class="rounded-full px-2.5 py-0.5 font-mono"
                        style="background: color-mix(in srgb, var(--danger) 10%, white); color: var(--danger);">
                    no numista_id
                  </span>
                </div>
                <p v-if="selected.review_reason"
                   class="mt-4 text-xs italic"
                   style="color: var(--ink-700); font-family: var(--font-display);">
                  « {{ selected.review_reason }} »
                </p>
              </div>
            </div>
          </div>

          <!-- ── Hint-specific case file ───────────────────────────── -->

          <!-- REBIND -->
          <div v-if="selected.review_action_hint === 'rebind'" class="px-8 pt-6 pb-32 flex flex-col gap-6">
            <div>
              <h3 class="font-display text-base mb-2" style="color: var(--ink);">Audit context</h3>
              <div class="border rounded-md p-4 text-sm" style="border-color: var(--border); background: var(--surface-1);">
                <div class="flex items-center gap-2 mb-2">
                  <X class="h-3.5 w-3.5" style="color: var(--danger);" />
                  <span style="color: var(--ink-500);">Ex-binding perdu en chunk 3b :</span>
                </div>
                <div class="font-mono text-xs flex flex-wrap gap-3" style="color: var(--ink);">
                  <span class="rounded px-2 py-0.5" style="background: var(--surface-2);">
                    nid {{ (selected.review_payload as RebindPayload)?.audit_old_nid ?? '?' }}
                  </span>
                  <span style="color: var(--ink-500);">
                    {{ (selected.review_payload as RebindPayload)?.audit_old_catalog_name ?? '?' }}
                  </span>
                </div>
              </div>
            </div>

            <!-- Search bar -->
            <div>
              <h3 class="font-display text-base mb-2 flex items-center gap-2" style="color: var(--ink);">
                <Search class="h-4 w-4" /> Rechercher un nouveau nid
              </h3>
              <div class="border rounded-md p-3 flex items-center gap-2"
                   style="border-color: var(--border); background: white;">
                <input
                  ref="searchInputRef"
                  v-model="searchQuery"
                  @keyup.enter="runSearch"
                  type="text"
                  placeholder="Mots-clés du thème…"
                  class="flex-1 bg-transparent outline-none text-sm font-mono"
                  style="color: var(--ink);"
                />
                <label class="flex items-center gap-1.5 text-[11px] cursor-pointer" style="color: var(--ink-500);">
                  <input type="checkbox" v-model="includeLive" class="accent-current" />
                  live API
                </label>
                <button
                  @click="runSearch"
                  :disabled="searchLoading"
                  class="rounded px-3 py-1.5 text-xs font-medium transition-opacity disabled:opacity-50"
                  style="background: var(--indigo-700); color: white;"
                >
                  {{ searchLoading ? '…' : 'Search' }}
                </button>
              </div>
            </div>

            <!-- Candidates -->
            <div v-if="searchHits.length > 0">
              <h3 class="font-display text-base mb-2" style="color: var(--ink);">
                Candidats <span style="color: var(--ink-500);" class="font-ui text-xs">({{ searchHits.length }})</span>
              </h3>
              <ul class="flex flex-col gap-2">
                <li v-for="(hit, i) in searchHits" :key="hit.numista_id">
                  <button
                    @click="doRebind(hit.numista_id)"
                    :disabled="saving"
                    class="group w-full flex items-center gap-3 border rounded-md px-4 py-3 text-left transition-all"
                    style="border-color: var(--border); background: white;"
                    onmouseover="this.style.borderColor='var(--indigo-700)'; this.style.background='var(--surface-1)';"
                    onmouseout="this.style.borderColor='var(--border)'; this.style.background='white';"
                  >
                    <kbd class="font-mono text-[10px] w-5 h-5 rounded flex items-center justify-center"
                         style="background: var(--surface-2); color: var(--ink-500);">{{ i + 1 }}</kbd>
                    <div class="flex-1 min-w-0">
                      <div class="flex items-baseline gap-2">
                        <span class="font-mono text-xs" style="color: var(--ink-500);">nid {{ hit.numista_id }}</span>
                        <span v-if="hit.source === 'numista_live'"
                              class="font-mono text-[10px] px-1.5 py-0.5 rounded"
                              style="background: var(--gold-100); color: var(--gold-deep);">live</span>
                      </div>
                      <div class="text-sm truncate" style="color: var(--ink);">{{ hit.name }}</div>
                    </div>
                    <div class="flex items-center gap-2">
                      <div class="w-16 h-1 rounded-full overflow-hidden" style="background: var(--surface-2);">
                        <div class="h-full" :style="`width: ${(hit.score * 100).toFixed(0)}%; background: var(--indigo-700);`"></div>
                      </div>
                      <a v-if="numistaUrl(hit.numista_id)"
                         :href="numistaUrl(hit.numista_id)!" target="_blank" rel="noopener"
                         class="text-[11px] underline"
                         style="color: var(--ink-500);"
                         @click.stop>↗</a>
                    </div>
                  </button>
                </li>
              </ul>
            </div>
            <div v-else-if="!searchLoading && searchQuery"
                 class="text-sm border border-dashed rounded-md px-4 py-6 text-center"
                 style="border-color: var(--border); color: var(--ink-500);">
              Aucun candidat. Essayer d'autres mots-clés, ou activer <span class="font-mono">live API</span>.
            </div>
          </div>

          <!-- VERIFY PARENT -->
          <div v-else-if="selected.review_action_hint === 'verify_parent'"
               class="px-8 pt-6 pb-32 flex flex-col gap-6">
            <div>
              <h3 class="font-display text-base mb-2" style="color: var(--ink);">Parent créé par chunk 3d</h3>
              <div class="border rounded-md p-4 text-sm" style="border-color: var(--border); background: var(--surface-1);">
                <div class="flex flex-wrap gap-3 mb-3">
                  <span class="rounded-full px-2.5 py-0.5 font-mono text-xs"
                        style="background: color-mix(in srgb, var(--gold) 18%, white); color: var(--gold-deep);">
                    bucket {{ (selected.review_payload as VerifyParentPayload)?.bucket }}
                  </span>
                  <span class="rounded-full px-2.5 py-0.5 font-mono text-xs" style="background: var(--surface-2);">
                    primary nid {{ (selected.review_payload as VerifyParentPayload)?.primary_numista_id }}
                  </span>
                </div>
                <p class="text-xs italic" style="color: var(--ink-500); font-family: var(--font-display);">
                  {{ (selected.review_payload as VerifyParentPayload)?.review_reason_seed }}
                </p>
              </div>
            </div>

            <div>
              <h3 class="font-display text-base mb-2" style="color: var(--ink);">
                Member variants <span class="font-ui text-xs" style="color: var(--ink-500);">
                  ({{ ((selected.review_payload as VerifyParentPayload)?.member_variants?.length) ?? 0 }})
                </span>
              </h3>
              <ul class="flex flex-col gap-2">
                <li v-for="v in ((selected.review_payload as VerifyParentPayload)?.member_variants ?? [])"
                    :key="v.variant_id"
                    class="border rounded-md px-4 py-3 flex items-center gap-3"
                    style="border-color: var(--border); background: white;">
                  <span class="rounded px-2 py-0.5 font-mono text-[10px] uppercase"
                        style="background: var(--surface-2); color: var(--ink-700);">
                    {{ v.finish }}
                  </span>
                  <span class="font-mono text-xs" style="color: var(--ink-500);">nid {{ v.numista_id }}</span>
                  <span class="text-sm flex-1 min-w-0 truncate" style="color: var(--ink);">{{ v.catalog_name }}</span>
                  <a :href="numistaUrl(v.numista_id)!" target="_blank" rel="noopener"
                     class="text-[11px] underline" style="color: var(--ink-500);">↗</a>
                </li>
              </ul>
            </div>
          </div>

          <!-- UNCERTAIN -->
          <div v-else-if="selected.review_action_hint === 'confirm_or_rematch_uncertain'"
               class="px-8 pt-6 pb-32 flex flex-col gap-6">
            <div>
              <h3 class="font-display text-base mb-2" style="color: var(--ink);">Audit overlap detecté</h3>
              <div class="grid grid-cols-2 gap-4">
                <!-- Current -->
                <div class="border rounded-md p-4" style="border-color: var(--border); background: var(--surface-1);">
                  <div class="text-[10px] uppercase tracking-widest mb-2" style="color: var(--ink-500);">
                    binding actuel
                  </div>
                  <div class="font-mono text-xs mb-1" style="color: var(--ink-500);">
                    nid {{ (selected.review_payload as UncertainPayload)?.current_numista_id ?? '?' }}
                  </div>
                  <div class="text-sm" style="color: var(--ink);">
                    {{ selected.theme || '—' }}
                  </div>
                  <a v-if="numistaUrl((selected.review_payload as UncertainPayload)?.current_numista_id)"
                     :href="numistaUrl((selected.review_payload as UncertainPayload)?.current_numista_id)!"
                     target="_blank" rel="noopener"
                     class="mt-2 inline-block text-[11px] underline" style="color: var(--indigo-700);">
                    Voir sur Numista ↗
                  </a>
                </div>
                <!-- Suspect -->
                <div class="border rounded-md p-4"
                     :style="`border-color: var(--warning); ${HINT_STYLES.confirm_or_rematch_uncertain.tagBg}`">
                  <div class="text-[10px] uppercase tracking-widest mb-2"
                       style="color: var(--warning);">audit suspect</div>
                  <div class="font-mono text-xs mb-1" style="color: var(--ink-500);">
                    nid {{ (selected.review_payload as UncertainPayload)?.suspect_numista_id }}
                  </div>
                  <div class="text-sm" style="color: var(--ink);">
                    {{ (selected.review_payload as UncertainPayload)?.suspect_catalog_name ?? '—' }}
                  </div>
                  <a v-if="numistaUrl((selected.review_payload as UncertainPayload)?.suspect_numista_id)"
                     :href="numistaUrl((selected.review_payload as UncertainPayload)?.suspect_numista_id)!"
                     target="_blank" rel="noopener"
                     class="mt-2 inline-block text-[11px] underline" style="color: var(--warning);">
                    Voir sur Numista ↗
                  </a>
                </div>
              </div>
              <p class="mt-3 text-xs" style="color: var(--ink-500);">
                <template v-if="(selected.review_payload as UncertainPayload)?.current_numista_id === Number((selected.review_payload as UncertainPayload)?.suspect_numista_id) || String((selected.review_payload as UncertainPayload)?.current_numista_id) === String((selected.review_payload as UncertainPayload)?.suspect_numista_id)">
                  Le current et le suspect pointent vers le <strong>même nid</strong>. Confirmer le binding actuel pour
                  clore, ou rebind/no-coverage si on pense que la pièce V1 doit être détachée.
                </template>
                <template v-else>
                  Deux nids distincts en jeu. Choisir : garder current, rebind au suspect, ou no-coverage.
                </template>
              </p>
            </div>

            <!-- Alternative candidates -->
            <div v-if="searchHits.length > 0">
              <h3 class="font-display text-base mb-2" style="color: var(--ink);">
                Autres candidats <span class="font-ui text-xs" style="color: var(--ink-500);">({{ searchHits.length }})</span>
              </h3>
              <ul class="flex flex-col gap-2">
                <li v-for="(hit, i) in searchHits" :key="hit.numista_id">
                  <button
                    @click="doRebind(hit.numista_id)"
                    :disabled="saving"
                    class="w-full flex items-center gap-3 border rounded-md px-4 py-3 text-left"
                    style="border-color: var(--border); background: white;"
                  >
                    <kbd class="font-mono text-[10px] w-5 h-5 rounded flex items-center justify-center"
                         style="background: var(--surface-2); color: var(--ink-500);">{{ i + 1 }}</kbd>
                    <div class="flex-1 min-w-0">
                      <div class="font-mono text-xs" style="color: var(--ink-500);">nid {{ hit.numista_id }}</div>
                      <div class="text-sm truncate" style="color: var(--ink);">{{ hit.name }}</div>
                    </div>
                  </button>
                </li>
              </ul>
            </div>

            <button
              v-if="searchHits.length === 0"
              @click="runSearch"
              class="self-start text-xs underline"
              style="color: var(--ink-500);">
              Charger les autres candidats {{ selected.country }}/{{ selected.year }}
            </button>
          </div>

          <!-- ── Sticky action bar ────────────────────────────────── -->
          <div class="sticky bottom-0 border-t px-8 py-4 flex items-center gap-3"
               style="border-color: var(--border); background: var(--paper);">
            <button
              @click="primaryHint === 'rebind' ? searchInputRef?.focus() : doConfirmCurrent()"
              :disabled="saving"
              class="rounded-md px-4 py-2 text-sm font-medium transition-opacity disabled:opacity-50"
              :style="primaryStyle(primaryHint)"
            >
              <Check v-if="primaryHint !== 'rebind'" class="h-3.5 w-3.5 inline mr-1 -mt-0.5" />
              <Search v-else class="h-3.5 w-3.5 inline mr-1 -mt-0.5" />
              {{ primaryLabel }} <span class="opacity-60 text-[10px] font-mono ml-1">C</span>
            </button>

            <button
              @click="showNoCoverageModal = true"
              :disabled="saving"
              class="rounded-md px-4 py-2 text-sm border transition-colors disabled:opacity-50"
              style="border-color: var(--border); background: white; color: var(--ink);"
            >
              <FilePen class="h-3.5 w-3.5 inline mr-1 -mt-0.5" />
              No-coverage <span class="opacity-60 text-[10px] font-mono ml-1">N</span>
            </button>

            <button
              @click="showDeleteModal = true"
              :disabled="saving"
              class="rounded-md px-4 py-2 text-sm border transition-colors disabled:opacity-50"
              style="border-color: var(--danger); color: var(--danger); background: white;"
            >
              <Trash2 class="h-3.5 w-3.5 inline mr-1 -mt-0.5" />
              Delete & redirect <span class="opacity-60 text-[10px] font-mono ml-1">D</span>
            </button>

            <div class="ml-auto text-[11px] font-mono" style="color: var(--ink-500);">
              <span v-if="saving"><Loader2 class="inline h-3 w-3 animate-spin -mt-0.5" /> saving…</span>
              <span v-else>j/k navigate · 1-9 pick · c/n/d action</span>
            </div>
          </div>

        </div>
      </section>
    </div>

    <!-- ── Modal: no-coverage note ───────────────────────────────────── -->
    <div v-if="showNoCoverageModal"
         class="fixed inset-0 z-50 flex items-center justify-center"
         style="background: rgba(11, 12, 34, 0.4);"
         @click.self="showNoCoverageModal = false">
      <div class="border rounded-lg p-6 w-full max-w-md"
           style="background: white; border-color: var(--border); box-shadow: var(--shadow-card);">
        <h3 class="font-display text-lg mb-1" style="color: var(--ink);">Marquer no-coverage</h3>
        <p class="text-xs mb-4" style="color: var(--ink-500);">
          Cette pièce reste en DB sans numista_id. Note optionnelle pour traçabilité.
        </p>
        <textarea v-model="noCoverageNote"
                  rows="3"
                  placeholder="Ex: 'Numista n'a pas cette commémo, vérifié par X.'"
                  class="w-full border rounded-md p-2 text-sm font-mono"
                  style="border-color: var(--border); color: var(--ink);"></textarea>
        <div class="mt-4 flex justify-end gap-2">
          <button @click="showNoCoverageModal = false"
                  class="rounded px-3 py-1.5 text-xs"
                  style="background: var(--surface-2); color: var(--ink);">Annuler</button>
          <button @click="doNoCoverage"
                  :disabled="saving"
                  class="rounded px-3 py-1.5 text-xs font-medium"
                  style="background: var(--indigo-700); color: white;">
            Confirmer no-coverage
          </button>
        </div>
      </div>
    </div>

    <!-- ── Modal: delete-redirect ────────────────────────────────────── -->
    <div v-if="showDeleteModal"
         class="fixed inset-0 z-50 flex items-center justify-center"
         style="background: rgba(11, 12, 34, 0.4);"
         @click.self="showDeleteModal = false">
      <div class="border rounded-lg p-6 w-full max-w-md"
           style="background: white; border-color: var(--danger); box-shadow: var(--shadow-card);">
        <h3 class="font-display text-lg mb-1 flex items-center gap-2" style="color: var(--danger);">
          <Trash2 class="h-4 w-4" /> Supprimer et rediriger
        </h3>
        <p class="text-xs mb-4" style="color: var(--ink-500);">
          Migre <span class="font-mono">{{ selected?.eurio_id }}</span> et ses dépendants
          (coin_source_refs, coin_market_prices, set_members…) vers une autre pièce, puis DELETE.
          <strong>Irréversible.</strong>
        </p>
        <label class="block text-[11px] font-mono uppercase tracking-wider mb-1"
               style="color: var(--ink-500);">target eurio_id</label>
        <input v-model="deleteTargetEid"
               type="text"
               placeholder="ex: fr-2010-2eur-other-slug"
               class="w-full border rounded-md p-2 text-sm font-mono"
               style="border-color: var(--border); color: var(--ink);" />
        <div class="mt-4 flex justify-end gap-2">
          <button @click="showDeleteModal = false"
                  class="rounded px-3 py-1.5 text-xs"
                  style="background: var(--surface-2); color: var(--ink);">Annuler</button>
          <button @click="doDeleteRedirect"
                  :disabled="saving || !deleteTargetEid.trim()"
                  class="rounded px-3 py-1.5 text-xs font-medium transition-opacity disabled:opacity-50"
                  style="background: var(--danger); color: white;">
            <ArrowRightLeft class="inline h-3 w-3 mr-1 -mt-0.5" />
            Migrer & supprimer
          </button>
        </div>
      </div>
    </div>

  </div>
</template>
