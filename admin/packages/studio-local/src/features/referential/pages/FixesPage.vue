<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import {
  AlertCircle, AlertTriangle, ArrowLeft, ArrowRight, CheckCircle2, ExternalLink,
  Loader2, RefreshCw, Wand2, Wifi, WifiOff, XCircle,
} from 'lucide-vue-next'
import { checkMlApi, ML_API } from '@/features/training/composables/useTrainingApi'
import {
  applyFixProposal,
  fetchFixProposalDetail,
  fetchFixProposals,
  refreshFixProposals,
  type FixApplyResponse,
  type FixApplyStep,
  type FixProposalDetail,
  type FixProposalsListResponse,
  type FixProposalSummary,
} from '../composables/useReferentialApi'

// ─── State ─────────────────────────────────────────────────────────────

const apiStatus = ref<'checking' | 'online' | 'offline'>('checking')
const list = ref<FixProposalsListResponse | null>(null)
const selected = ref<FixProposalSummary | null>(null)
const detail = ref<FixProposalDetail | null>(null)

const loading = ref(false)
const loadError = ref<string | null>(null)
const detailLoading = ref(false)
const detailError = ref<string | null>(null)

const refreshing = ref(false)
const refreshError = ref<string | null>(null)

const applying = ref(false)
const applyResult = ref<FixApplyResponse | null>(null)
const applyError = ref<string | null>(null)

const filter = ref<'all' | 'high' | 'medium' | 'low'>('all')

// ─── Loaders ───────────────────────────────────────────────────────────

async function refreshHealth() {
  apiStatus.value = 'checking'
  apiStatus.value = (await checkMlApi()) ? 'online' : 'offline'
}

async function loadList() {
  loading.value = true
  loadError.value = null
  try {
    const r = await fetchFixProposals()
    list.value = r
    if (!selected.value && r.proposals.length) {
      await selectCase(r.proposals[0])
    } else if (selected.value) {
      const still = r.proposals.find((p) => p.case_id === selected.value!.case_id)
      if (still) await selectCase(still)
      else selected.value = null
    }
  } catch (err) {
    loadError.value = err instanceof Error ? err.message : 'Erreur'
  } finally {
    loading.value = false
  }
}

async function selectCase(c: FixProposalSummary) {
  selected.value = c
  detail.value = null
  applyResult.value = null
  applyError.value = null
  detailLoading.value = true
  detailError.value = null
  try {
    detail.value = await fetchFixProposalDetail(c.case_id)
  } catch (err) {
    detailError.value = err instanceof Error ? err.message : 'Erreur détail'
  } finally {
    detailLoading.value = false
  }
}

async function triggerRefresh() {
  if (!confirm(
    'Re-run le script discover_referential_fixes (lecture seule, ne mute rien).\n'
    + 'Régénère ml/state/referential_fix_proposals.json depuis l\'audit actuel.\n'
    + 'Continuer ?',
  )) return
  refreshing.value = true
  refreshError.value = null
  try {
    await refreshFixProposals()
    await loadList()
  } catch (err) {
    refreshError.value = err instanceof Error ? err.message : 'Erreur refresh'
  } finally {
    refreshing.value = false
  }
}

async function triggerApply() {
  if (!selected.value) return
  const c = selected.value
  if (!confirm(
    `APPLIQUER le fix ${c.case_id} ?\n\n`
    + 'Cascade en 8 étapes : preflight → backup eurio.db → mutate DB → '
    + 'move BCE sidecars → fetch Numista images → push Supabase → audit.\n\n'
    + 'Un backup eurio.db.bak-fix-* sera créé avant toute mutation.\n'
    + 'En cas d\'échec push Supabase, l\'opération continue (relance manuelle via /push).',
  )) return
  applying.value = true
  applyError.value = null
  applyResult.value = null
  try {
    applyResult.value = await applyFixProposal(c.case_id)
    // Reload list (the case may now be obsolete, but discovery is read-only)
    await loadList()
  } catch (err) {
    applyError.value = err instanceof Error ? err.message : 'Erreur apply'
  } finally {
    applying.value = false
  }
}

onMounted(async () => {
  await refreshHealth()
  if (apiStatus.value === 'online') await loadList()
})

// ─── Derived ───────────────────────────────────────────────────────────

const filtered = computed<FixProposalSummary[]>(() => {
  if (!list.value) return []
  if (filter.value === 'all') return list.value.proposals
  return list.value.proposals.filter((p) => p.confidence === filter.value)
})

function imgUrl(eurioId: string, source: 'numista' | 'bce_comm'): string {
  return `${ML_API}/referential/canonical/${eurioId}/obverse?source=${source}`
}

function numistaUrl(id: number | null): string | null {
  if (!id) return null
  return `https://en.numista.com/catalogue/pieces${id}.html`
}

function targetBadgeStyle(t: 'existing' | 'new' | 'unknown') {
  if (t === 'new') return { bg: 'color-mix(in srgb, var(--success) 14%, var(--surface))', fg: 'var(--success)' }
  if (t === 'existing') return { bg: 'color-mix(in srgb, var(--ink-500) 14%, var(--surface))', fg: 'var(--ink-500)' }
  return { bg: 'color-mix(in srgb, var(--warning, #d97706) 14%, var(--surface))', fg: 'var(--warning, #d97706)' }
}

function stepIcon(status: FixApplyStep['status']) {
  if (status === 'ok') return CheckCircle2
  if (status === 'failed') return XCircle
  return AlertCircle
}

function stepColor(status: FixApplyStep['status']): string {
  if (status === 'ok') return 'var(--success)'
  if (status === 'failed') return 'var(--danger)'
  return 'var(--ink-500)'
}
</script>

<template>
  <div class="container mx-auto px-6 py-6" style="background: var(--surface-1); min-height: 100vh;">
    <!-- ═══ Header ═══ -->
    <header class="mb-6 flex items-baseline justify-between">
      <div>
        <router-link to="/referential"
                     class="inline-flex items-center gap-1.5 text-xs"
                     style="color: var(--ink-500);">
          <ArrowLeft class="h-3 w-3" /> Référentiel
        </router-link>
        <h1 class="mt-1 text-2xl font-bold" style="color: var(--ink);">
          Fixes référentiel (catalog_unlinked)
        </h1>
        <p class="mt-1 text-sm" style="color: var(--ink-500);">
          Propositions générées par <span class="font-mono">discover_referential_fixes</span>.
          Apply = cascade 8 étapes, backup auto avant mutation, push Supabase non-fatal.
        </p>
      </div>

      <div class="flex items-center gap-3">
        <div class="flex items-center gap-1.5 rounded-full border px-3 py-1 text-xs"
             :style="{
               borderColor: apiStatus === 'online' ? 'var(--success)' : 'var(--danger)',
               color: apiStatus === 'online' ? 'var(--success)' : 'var(--danger)',
             }">
          <Wifi v-if="apiStatus === 'online'" class="h-3 w-3" />
          <WifiOff v-else class="h-3 w-3" />
          {{ apiStatus === 'online' ? 'API en ligne' : 'API hors-ligne' }}
        </div>
        <button v-if="apiStatus === 'online'"
                class="inline-flex items-center gap-1.5 rounded-md border px-3 py-1.5 text-xs font-medium"
                style="border-color: var(--surface-3); color: var(--ink-500);"
                :disabled="loading || refreshing"
                @click="loadList">
          <RefreshCw class="h-3 w-3" :class="{ 'animate-spin': loading }" /> Reload
        </button>
        <button v-if="apiStatus === 'online'"
                class="inline-flex items-center gap-1.5 rounded-md border px-3 py-1.5 text-xs font-medium"
                style="border-color: var(--indigo-700); color: var(--indigo-700);"
                :disabled="refreshing"
                @click="triggerRefresh">
          <Wand2 class="h-3 w-3" :class="{ 'animate-spin': refreshing }" />
          {{ refreshing ? 'Discovery…' : 'Refresh discovery' }}
        </button>
      </div>
    </header>

    <div v-if="loadError"
         class="mb-6 rounded-lg border px-5 py-3 text-sm"
         style="border-color: var(--danger); background: color-mix(in srgb, var(--danger) 4%, var(--surface)); color: var(--danger);">
      <AlertCircle class="mr-1 inline-block h-4 w-4 -mt-0.5" />
      {{ loadError }}
    </div>
    <div v-if="refreshError"
         class="mb-6 rounded-lg border px-5 py-3 text-sm"
         style="border-color: var(--danger); background: color-mix(in srgb, var(--danger) 4%, var(--surface)); color: var(--danger);">
      <AlertCircle class="mr-1 inline-block h-4 w-4 -mt-0.5" />
      Refresh discovery : {{ refreshError }}
    </div>

    <template v-if="list">
      <!-- ═══ Summary ═══ -->
      <section class="mb-4 flex items-center justify-between gap-4">
        <div class="grid grid-cols-4 gap-3 flex-1">
          <div class="rounded-lg border px-4 py-2"
               style="border-color: var(--surface-3); background: var(--surface);">
            <div class="text-[10px] uppercase tracking-wider" style="color: var(--ink-500);">Total</div>
            <div class="font-mono text-lg font-bold" style="color: var(--ink);">{{ list.n_proposals }}</div>
          </div>
          <div class="rounded-lg border px-4 py-2"
               style="border-color: var(--surface-3); background: var(--surface);">
            <div class="text-[10px] uppercase tracking-wider" style="color: var(--ink-500);">High confidence</div>
            <div class="font-mono text-lg font-bold" style="color: var(--success);">{{ list.by_confidence.high ?? 0 }}</div>
          </div>
          <div class="rounded-lg border px-4 py-2"
               style="border-color: var(--surface-3); background: var(--surface);">
            <div class="text-[10px] uppercase tracking-wider" style="color: var(--ink-500);">Medium</div>
            <div class="font-mono text-lg font-bold" style="color: var(--warning, #d97706);">{{ list.by_confidence.medium ?? 0 }}</div>
          </div>
          <div class="rounded-lg border px-4 py-2"
               style="border-color: var(--surface-3); background: var(--surface);">
            <div class="text-[10px] uppercase tracking-wider" style="color: var(--ink-500);">Generated</div>
            <div class="font-mono text-xs" style="color: var(--ink);">
              {{ list.generated_at ? new Date(list.generated_at).toLocaleString() : '—' }}
            </div>
          </div>
        </div>
      </section>

      <section class="mb-3 flex gap-2">
        <button v-for="f in (['all','high','medium','low'] as const)" :key="f"
                class="rounded-full px-3 py-1 text-xs font-medium"
                :style="filter === f
                  ? { background: 'var(--ink)', color: 'var(--surface)' }
                  : { background: 'var(--surface)', color: 'var(--ink-500)', border: '1px solid var(--surface-3)' }"
                @click="filter = f">
          {{ f === 'all' ? `Tous (${list.n_proposals})` : `${f} (${list.by_confidence[f] ?? 0})` }}
        </button>
      </section>

      <!-- ═══ Two-pane layout ═══ -->
      <div class="grid gap-4 lg:grid-cols-[minmax(0,1fr)_minmax(0,1.5fr)]">
        <!-- ── List left ── -->
        <div class="rounded-lg border overflow-hidden"
             style="border-color: var(--surface-3); background: var(--surface);">
          <table class="w-full text-sm">
            <thead class="text-[10px] uppercase font-mono"
                   style="background: var(--surface-1); color: var(--ink-500);">
              <tr>
                <th class="px-3 py-2 text-left">Pays·An</th>
                <th class="px-3 py-2 text-left">Shape</th>
                <th class="px-3 py-2 text-left">Conf.</th>
                <th class="px-3 py-2 text-left">Case</th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="p in filtered" :key="p.case_id"
                  class="cursor-pointer border-t"
                  :style="selected?.case_id === p.case_id
                    ? { background: 'color-mix(in srgb, var(--indigo-700) 6%, var(--surface))', borderColor: 'var(--surface-2)' }
                    : { borderColor: 'var(--surface-2)' }"
                  @click="selectCase(p)">
                <td class="px-3 py-2 font-mono text-xs" style="color: var(--ink);">
                  {{ p.country }}·{{ p.year }}
                </td>
                <td class="px-3 py-2">
                  <span class="inline-block rounded-full px-2 py-0.5 font-mono text-[9px] uppercase"
                        style="background: color-mix(in srgb, var(--indigo-700) 12%, var(--surface)); color: var(--indigo-700);">
                    {{ p.shape }}
                  </span>
                </td>
                <td class="px-3 py-2">
                  <span class="inline-block rounded-full px-2 py-0.5 font-mono text-[9px] uppercase"
                        :style="p.confidence === 'high'
                          ? { background: 'color-mix(in srgb, var(--success) 12%, var(--surface))', color: 'var(--success)' }
                          : p.confidence === 'medium'
                          ? { background: 'color-mix(in srgb, var(--warning, #d97706) 12%, var(--surface))', color: 'var(--warning, #d97706)' }
                          : { background: 'color-mix(in srgb, var(--danger) 12%, var(--surface))', color: 'var(--danger)' }">
                    {{ p.confidence }}
                  </span>
                  <span v-if="p.n_warnings > 0"
                        class="ml-1.5 inline-flex items-center gap-0.5 font-mono text-[9px]"
                        style="color: var(--warning, #d97706);">
                    <AlertTriangle class="h-2.5 w-2.5" /> {{ p.n_warnings }}
                  </span>
                </td>
                <td class="px-3 py-2 text-xs font-mono" style="color: var(--ink);">
                  <div class="line-clamp-1">{{ p.case_id }}</div>
                  <div class="text-[10px]" style="color: var(--ink-500);">
                    swap {{ p.swap_current_numista_id }} → {{ p.swap_new_numista_id }}
                  </div>
                </td>
              </tr>
              <tr v-if="!filtered.length">
                <td colspan="4" class="px-3 py-8 text-center text-xs" style="color: var(--success);">
                  ✓ Aucun fix proposé pour ce filtre.
                </td>
              </tr>
            </tbody>
          </table>
        </div>

        <!-- ── Detail right ── -->
        <div class="rounded-lg border p-5"
             style="border-color: var(--surface-3); background: var(--surface);">
          <div v-if="detailLoading" class="flex items-center gap-2 text-xs" style="color: var(--ink-500);">
            <Loader2 class="h-3 w-3 animate-spin" /> Chargement détail…
          </div>
          <div v-else-if="detailError" class="text-sm" style="color: var(--danger);">
            <AlertCircle class="mr-1 inline-block h-4 w-4 -mt-0.5" /> {{ detailError }}
          </div>

          <template v-else-if="detail">
            <!-- Header -->
            <div class="mb-4 flex items-baseline justify-between gap-3">
              <div>
                <div class="font-mono text-xs" style="color: var(--ink-500);">{{ detail.case_id }}</div>
                <div class="mt-1 text-sm font-medium" style="color: var(--ink);">
                  {{ detail.country }} · {{ detail.year }} · shape {{ detail.shape }}
                </div>
              </div>
              <button class="inline-flex items-center gap-1.5 rounded-md px-4 py-2 text-xs font-medium"
                      style="background: var(--danger); color: white;"
                      :disabled="applying"
                      @click="triggerApply">
                <Loader2 v-if="applying" class="h-3 w-3 animate-spin" />
                <Wand2 v-else class="h-3 w-3" />
                {{ applying ? 'Apply en cours…' : 'Apply this fix' }}
              </button>
            </div>

            <!-- Apply result panel -->
            <div v-if="applyError"
                 class="mb-4 rounded-md border px-3 py-2 text-xs"
                 style="border-color: var(--danger); background: color-mix(in srgb, var(--danger) 4%, var(--surface)); color: var(--danger);">
              <AlertCircle class="mr-1 inline-block h-3 w-3 -mt-0.5" /> {{ applyError }}
            </div>
            <div v-if="applyResult"
                 class="mb-4 rounded-md border p-3"
                 :style="applyResult.success
                   ? { borderColor: 'var(--success)', background: 'color-mix(in srgb, var(--success) 4%, var(--surface))' }
                   : { borderColor: 'var(--danger)', background: 'color-mix(in srgb, var(--danger) 4%, var(--surface))' }">
              <div class="mb-2 flex items-center justify-between gap-2">
                <div class="font-mono text-xs font-semibold"
                     :style="{ color: applyResult.success ? 'var(--success)' : 'var(--danger)' }">
                  {{ applyResult.success ? '✓ Apply réussi' : '✗ Apply incomplet' }}
                  <span class="ml-2 opacity-70">{{ applyResult.duration_sec.toFixed(1) }}s</span>
                </div>
                <span v-if="applyResult.backup_path"
                      class="font-mono text-[10px]" style="color: var(--ink-500);">
                  backup: {{ applyResult.backup_path }}
                </span>
              </div>
              <ul class="space-y-1">
                <li v-for="step in applyResult.steps" :key="step.name"
                    class="flex items-start gap-2 font-mono text-[11px]">
                  <component :is="stepIcon(step.status)"
                             class="h-3.5 w-3.5 shrink-0 mt-0.5"
                             :style="{ color: stepColor(step.status) }" />
                  <div class="flex-1 min-w-0">
                    <div :style="{ color: stepColor(step.status) }">
                      {{ step.name }} · {{ step.status }}
                    </div>
                    <pre v-if="Object.keys(step.diagnostic).length"
                         class="mt-0.5 whitespace-pre-wrap text-[10px] opacity-70 overflow-x-auto"
                         style="color: var(--ink-500);">{{ JSON.stringify(step.diagnostic, null, 2) }}</pre>
                  </div>
                </li>
              </ul>
            </div>

            <!-- Reasoning -->
            <div class="mb-4 rounded-md border p-3 text-xs"
                 style="border-color: var(--surface-3); background: var(--surface-1); color: var(--ink);">
              {{ detail.reasoning }}
            </div>

            <!-- Warnings -->
            <div v-if="detail.warnings.length" class="mb-4 space-y-1">
              <div v-for="(w, i) in detail.warnings" :key="i"
                   class="rounded-md border px-3 py-2 text-xs flex items-start gap-2"
                   style="border-color: var(--warning, #d97706); background: color-mix(in srgb, var(--warning, #d97706) 4%, var(--surface)); color: var(--warning, #d97706);">
                <AlertTriangle class="h-3.5 w-3.5 shrink-0 mt-0.5" />
                <span>{{ w }}</span>
              </div>
            </div>

            <!-- Swap section -->
            <section v-if="detail.swap" class="mb-4">
              <h3 class="mb-2 font-mono text-[10px] uppercase tracking-wider" style="color: var(--ink-500);">
                Swap — l'eurio_id existant change de numista_id
              </h3>
              <div class="rounded-md border p-3"
                   style="border-color: var(--surface-3); background: var(--surface-1);">
                <div class="font-mono text-xs mb-2" style="color: var(--ink);">
                  {{ detail.swap.eurio_id }}
                </div>
                <div class="grid grid-cols-[1fr_auto_1fr] items-center gap-3 text-xs">
                  <div class="rounded border p-2"
                       style="border-color: var(--surface-3); background: var(--surface);">
                    <div class="font-mono text-[9px] uppercase mb-1" style="color: var(--ink-500);">Current (wrong)</div>
                    <div class="flex items-center justify-between gap-2">
                      <span class="font-mono" style="color: var(--ink);">#{{ detail.swap.current_numista_id }}</span>
                      <a :href="numistaUrl(detail.swap.current_numista_id)!" target="_blank" rel="noopener"
                         class="inline-flex items-center gap-0.5 text-[10px]"
                         style="color: var(--indigo-700);">
                        Numista <ExternalLink class="h-2.5 w-2.5" />
                      </a>
                    </div>
                    <div class="mt-1 text-[11px]" style="color: var(--ink);">{{ detail.swap.current_numista_title }}</div>
                    <div class="mt-1 font-mono text-[10px]" style="color: var(--danger);">
                      sim {{ detail.swap.current_similarity.toFixed(3) }}
                    </div>
                  </div>
                  <ArrowRight class="h-4 w-4" style="color: var(--indigo-700);" />
                  <div class="rounded border p-2"
                       style="border-color: var(--success); background: color-mix(in srgb, var(--success) 4%, var(--surface));">
                    <div class="font-mono text-[9px] uppercase mb-1" style="color: var(--success);">New (correct)</div>
                    <div class="flex items-center justify-between gap-2">
                      <span class="font-mono" style="color: var(--ink);">#{{ detail.swap.new_numista_id }}</span>
                      <a :href="numistaUrl(detail.swap.new_numista_id)!" target="_blank" rel="noopener"
                         class="inline-flex items-center gap-0.5 text-[10px]"
                         style="color: var(--indigo-700);">
                        Numista <ExternalLink class="h-2.5 w-2.5" />
                      </a>
                    </div>
                    <div class="mt-1 text-[11px]" style="color: var(--ink);">{{ detail.swap.new_numista_title }}</div>
                    <div class="mt-1 font-mono text-[10px]" style="color: var(--success);">
                      sim {{ detail.swap.new_similarity.toFixed(3) }}
                    </div>
                  </div>
                </div>
              </div>
            </section>

            <!-- New row section -->
            <section class="mb-4">
              <h3 class="mb-2 font-mono text-[10px] uppercase tracking-wider" style="color: var(--ink-500);">
                New row — à créer pour le numista_id déplacé
              </h3>
              <div class="rounded-md border p-3"
                   style="border-color: var(--surface-3); background: var(--surface-1);">
                <div class="flex items-baseline justify-between gap-2 mb-2">
                  <span class="font-mono text-xs" style="color: var(--ink);">{{ detail.new_row.eurio_id }}</span>
                  <a :href="numistaUrl(detail.new_row.numista_id)!" target="_blank" rel="noopener"
                     class="inline-flex items-center gap-0.5 text-[10px]"
                     style="color: var(--indigo-700);">
                    #{{ detail.new_row.numista_id }} <ExternalLink class="h-2.5 w-2.5" />
                  </a>
                </div>
                <div class="grid grid-cols-[auto_1fr] gap-x-3 gap-y-1 text-xs">
                  <span class="font-mono text-[10px] uppercase" style="color: var(--ink-500);">Theme</span>
                  <span style="color: var(--ink);">{{ detail.new_row.theme || '—' }}</span>
                  <span class="font-mono text-[10px] uppercase" style="color: var(--ink-500);">Design</span>
                  <span style="color: var(--ink);" class="line-clamp-3">{{ detail.new_row.design_description || '—' }}</span>
                </div>
              </div>
            </section>

            <!-- Images existant (avant apply) -->
            <section v-if="detail.swap" class="mb-4">
              <h3 class="mb-2 font-mono text-[10px] uppercase tracking-wider" style="color: var(--ink-500);">
                Images actuelles sur {{ detail.swap.eurio_id }}
              </h3>
              <div class="grid grid-cols-2 gap-3">
                <div>
                  <div class="font-mono text-[10px] uppercase mb-1" style="color: var(--ink-500);">Numista (current)</div>
                  <img :src="imgUrl(detail.swap.eurio_id, 'numista')"
                       class="aspect-square w-full rounded-md object-contain"
                       style="background: var(--surface-1);"
                       @error="(e) => ((e.target as HTMLImageElement).style.opacity = '0.2')" />
                </div>
                <div>
                  <div class="font-mono text-[10px] uppercase mb-1" style="color: var(--ink-500);">BCE comm</div>
                  <img :src="imgUrl(detail.swap.eurio_id, 'bce_comm')"
                       class="aspect-square w-full rounded-md object-contain"
                       style="background: var(--surface-1);"
                       @error="(e) => ((e.target as HTMLImageElement).style.opacity = '0.2')" />
                </div>
              </div>
              <p class="mt-2 text-[11px]" style="color: var(--ink-500);">
                Apply fetchera les images Numista pour les 2 nouveaux nids ({{ detail.swap.new_numista_id }} → existing,
                {{ detail.new_row.numista_id }} → new row).
              </p>
            </section>

            <!-- Source attributions -->
            <section v-if="detail.source_attributions.length" class="mb-2">
              <h3 class="mb-2 font-mono text-[10px] uppercase tracking-wider" style="color: var(--ink-500);">
                Source attributions
              </h3>
              <div class="space-y-2">
                <div v-for="(sa, i) in detail.source_attributions" :key="i"
                     class="rounded-md border p-3"
                     style="border-color: var(--surface-3); background: var(--surface-1);">
                  <div class="mb-1 flex items-center justify-between gap-2">
                    <span class="font-mono text-[10px] uppercase" style="color: var(--ink-500);">
                      {{ sa.source }}
                    </span>
                    <span class="inline-block rounded-full px-2 py-0.5 font-mono text-[9px] uppercase"
                          :style="{
                            background: targetBadgeStyle(sa.recommended_target).bg,
                            color: targetBadgeStyle(sa.recommended_target).fg,
                          }">
                      → {{ sa.recommended_target }}
                    </span>
                  </div>
                  <div class="text-[11px]" style="color: var(--ink);">
                    {{ sa.feature_text || '—' }}
                  </div>
                  <div class="mt-1 font-mono text-[10px]" style="color: var(--ink-500);">
                    sim existing={{ sa.sim_to_existing_slug.toFixed(3) }}
                    · new={{ sa.sim_to_new_slug.toFixed(3) }}
                  </div>
                </div>
              </div>
            </section>
          </template>

          <div v-else class="text-center text-sm py-12" style="color: var(--ink-500);">
            Sélectionne un cas à gauche.
          </div>
        </div>
      </div>
    </template>
  </div>
</template>
