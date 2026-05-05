<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import {
  AlertTriangle,
  ArrowLeft,
  CheckCircle2,
  ExternalLink,
  Loader2,
  Package,
  Search,
  Target,
  XCircle,
} from 'lucide-vue-next'
import {
  fetchRunBreakdown,
  RunBreakdownError,
  type RunBreakdown,
  type RunBreakdownEntry,
} from '../composables/useRunBreakdown'
import type { SourceId } from '../composables/useSourcesApi'

const route = useRoute()
const router = useRouter()

const sourceId = computed(() => route.params.id as SourceId)
const runId = computed(() => route.params.run_id as string)

const data = ref<RunBreakdown | null>(null)
const loading = ref(true)
const error = ref<string | null>(null)

async function load() {
  loading.value = true
  error.value = null
  try {
    data.value = await fetchRunBreakdown(sourceId.value, runId.value)
  } catch (err) {
    if (err instanceof RunBreakdownError && err.status === 404) {
      error.value = `Run introuvable : ${runId.value}`
    } else {
      error.value = err instanceof Error ? err.message : String(err)
    }
    data.value = null
  } finally {
    loading.value = false
  }
}

onMounted(load)
watch([sourceId, runId], load)

// ─── Derived ────────────────────────────────────────────────────────────

const targeted = computed(() =>
  (data.value?.per_eurio ?? []).filter((e) => e.was_targeted),
)
const discovered = computed(() =>
  (data.value?.per_eurio ?? []).filter((e) => !e.was_targeted),
)

const targetIds = computed(
  () => (data.value?.filters?.target_eurio_ids as string[] | undefined) ?? [],
)

const totalsTargeted = computed(() => sumRows(targeted.value))
const totalsDiscovered = computed(() => sumRows(discovered.value))

function sumRows(rows: RunBreakdownEntry[]) {
  const acc = {
    n_listings: 0, n_crops_searched: 0, n_searched_auto: 0,
    n_searched_review_single: 0, n_searched_review_lot: 0,
    n_searched_pending: 0, n_searched_rejected: 0,
    n_attributed_from_other: 0, n_quotes: 0,
  }
  for (const r of rows) {
    acc.n_listings += r.n_listings
    acc.n_crops_searched += r.n_crops_searched
    acc.n_searched_auto += r.n_searched_auto
    acc.n_searched_review_single += r.n_searched_review_single
    acc.n_searched_review_lot += r.n_searched_review_lot
    acc.n_searched_pending += r.n_searched_pending
    acc.n_searched_rejected += r.n_searched_rejected
    acc.n_attributed_from_other += r.n_attributed_from_other
    acc.n_quotes += r.n_quotes
  }
  return acc
}

const STATUS_TONE: Record<RunBreakdown['status'], string> = {
  success: 'var(--success)',
  partial: 'var(--warning)',
  failed: 'var(--danger)',
  running: 'var(--indigo-500)',
}

function formatAbsolute(iso: string): string {
  const d = new Date(iso.replace(' ', 'T'))
  if (Number.isNaN(d.getTime())) return iso
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')} ${String(d.getHours()).padStart(2, '0')}:${String(d.getMinutes()).padStart(2, '0')}`
}

function gotoReview(entry: RunBreakdownEntry) {
  // Toggle deep-link : si la row a uniquement du review_lot → mode=lot,
  // si uniquement du review_single → default (single), sinon default
  // (single visible mais l'utilisateur peut pivoter via le toggle).
  const hasLot = entry.n_searched_review_lot > 0
  const hasSingle = entry.n_searched_review_single > 0
  const mode: 'single' | 'lot' = hasLot && !hasSingle ? 'lot' : 'single'
  const query: Record<string, string> = {
    run_id: runId.value,
    eurio_id: entry.eurio_id,
  }
  if (mode === 'lot') query.mode = 'lot'
  router.push({ path: '/review', query })
}

function gotoListings(eurio_id: string) {
  router.push({
    path: `/sources/${sourceId.value}/runs/${runId.value}/listings`,
    query: { eurio_id },
  })
}

function onRowClick(ev: MouseEvent, eurio_id: string) {
  // Exclude clicks on interactive children (buttons, links).
  if ((ev.target as HTMLElement).closest('button, a')) return
  gotoListings(eurio_id)
}
</script>

<template>
  <div class="p-8">
    <button
      class="mb-4 inline-flex items-center gap-1.5 text-xs transition-colors"
      style="color: var(--ink-400);"
      @mouseenter="(e) => ((e.currentTarget as HTMLElement).style.color = 'var(--indigo-700)')"
      @mouseleave="(e) => ((e.currentTarget as HTMLElement).style.color = 'var(--ink-400)')"
      @click="router.push(`/sources/${sourceId}`)"
    >
      <ArrowLeft class="h-3 w-3" />
      Retour à {{ sourceId }}
    </button>

    <div
      v-if="loading"
      class="flex items-center gap-2 py-16 text-sm"
      style="color: var(--ink-400);"
    >
      <Loader2 class="h-4 w-4 animate-spin" /> Chargement du breakdown…
    </div>

    <div
      v-else-if="error"
      class="rounded-lg border px-5 py-3 text-sm"
      style="border-color: var(--danger); background: color-mix(in srgb, var(--danger) 4%, var(--surface)); color: var(--danger);"
    >
      {{ error }}
    </div>

    <template v-else-if="data">
      <header
        class="mb-6 rounded-lg border px-6 py-5"
        style="border-color: var(--surface-3); background: var(--surface);"
      >
        <div class="flex flex-wrap items-start justify-between gap-6">
          <div class="min-w-0 flex-1">
            <p
              class="font-mono text-[10px] uppercase tracking-wider"
              style="color: var(--ink-500);"
            >
              Run
              · <span style="color: var(--gold-600);">{{ data.source_id }}</span>
              · {{ formatAbsolute(data.started_at) }}
            </p>
            <h1
              class="mt-1 font-mono text-base font-semibold leading-tight"
              style="color: var(--ink);"
            >
              {{ data.run_id }}
            </h1>
            <p class="mt-2 font-mono text-[11px]" style="color: var(--ink-500);">
              <span style="color: var(--ink-400);">Ciblés&nbsp;:</span>
              {{ targetIds.length }}
              <span class="mx-2 opacity-40">|</span>
              <span style="color: var(--ink-400);">Découverts&nbsp;:</span>
              {{ discovered.length }}
            </p>
          </div>
          <div
            class="inline-flex items-center gap-1.5 rounded-full border px-3 py-1 text-xs font-medium"
            :style="{
              borderColor: STATUS_TONE[data.status],
              color: STATUS_TONE[data.status],
              background: `color-mix(in srgb, ${STATUS_TONE[data.status]} 6%, var(--surface))`,
            }"
          >
            <CheckCircle2 v-if="data.status === 'success'" class="h-3 w-3" />
            <AlertTriangle v-else-if="data.status === 'partial'" class="h-3 w-3" />
            <Loader2 v-else-if="data.status === 'running'" class="h-3 w-3 animate-spin" />
            <XCircle v-else class="h-3 w-3" />
            {{ data.status }}
          </div>
        </div>
      </header>

      <!-- Section : ciblés -->
      <section class="mb-8">
        <h2
          class="mb-3 inline-flex items-center gap-2 font-mono text-[11px] uppercase tracking-wider"
          style="color: var(--indigo-700);"
        >
          <Target class="h-3 w-3" />
          Ciblés <span style="color: var(--ink-400);">·</span>
          <span style="color: var(--ink-500);">{{ targeted.length }}</span>
        </h2>
        <div
          v-if="!targeted.length"
          class="rounded-lg border-2 border-dashed px-6 py-8 text-center text-sm"
          style="border-color: var(--surface-3); color: var(--ink-400);"
        >
          Aucun eurio_id ciblé pour ce run.
        </div>
        <div
          v-else
          class="overflow-hidden rounded-lg border"
          style="border-color: var(--surface-3); background: var(--surface);"
        >
          <table class="w-full text-left text-sm">
            <thead>
              <tr
                class="font-mono text-[10px] uppercase tracking-wider"
                style="background: var(--surface-1); color: var(--ink-500);"
              >
                <th class="px-3 py-2.5 font-medium" title="Identifiant canonique de la pièce — clic ligne ouvre la fiche">eurio_id</th>
                <th class="px-2 py-2.5 text-right font-medium" title="source_images cherchés pour cet eurio (axe search)">List.</th>
                <th class="px-2 py-2.5 text-right font-medium" title="Crops dans ces listings — somme exacte de Auto + Rev.S + Rev.L + Pend. + Rej.">Crops</th>
                <th class="px-2 py-2.5 text-right font-medium" title="Crops résolus automatiquement (auto_phash | auto_name | manual)">Auto</th>
                <th class="px-2 py-2.5 text-right font-medium" title="Crops en review_queue avec kind='single' (statut open)">Rev.S</th>
                <th class="px-2 py-2.5 text-right font-medium" title="Crops en review_queue avec kind='lot' (statut open)">Rev.L</th>
                <th class="px-2 py-2.5 text-right font-medium" title="Crops needs_review/pending sans entrée review_queue (le résolveur n'a pas encore tranché)">Pend.</th>
                <th class="px-2 py-2.5 text-right font-medium" title="Crops avec resolution_status='rejected'">Rej.</th>
                <th class="px-2 py-2.5 text-right font-medium" title="Crops résolus à cet eurio depuis un listing cherché pour autre chose (cas lot, axe attribution)">Attr.</th>
                <th class="px-2 py-2.5 text-right font-medium" title="coin_market_quotes générés pour cet eurio depuis ce run">Quotes</th>
                <th class="px-2 py-2.5 font-medium" title="Au moins un listing associé est is_lot_suspected ou multi-crop">Lot ?</th>
                <th class="px-3 py-2.5 font-medium" title="Lien vers la file de review filtrée run+eurio (si items review)">
                  <span class="inline-flex items-center gap-1">
                    <Search class="h-2.5 w-2.5" /> Review
                  </span>
                </th>
              </tr>
            </thead>
            <tbody>
              <tr
                v-for="row in targeted"
                :key="row.eurio_id"
                class="cursor-pointer border-t transition-colors"
                style="border-color: var(--surface-2);"
                :title="`Voir les listings pour ${row.eurio_id}`"
                @mouseenter="(e) => ((e.currentTarget as HTMLElement).style.background = 'var(--surface-1)')"
                @mouseleave="(e) => ((e.currentTarget as HTMLElement).style.background = 'transparent')"
                @click="(ev) => onRowClick(ev, row.eurio_id)"
              >
                <td class="px-3 py-2 font-mono text-[11px]" style="color: var(--ink);">
                  {{ row.eurio_id }}
                </td>
                <td class="px-2 py-2 text-right font-mono text-[12px] tabular-nums" style="color: var(--ink-700);">
                  {{ row.n_listings || '·' }}
                </td>
                <td class="px-2 py-2 text-right font-mono text-[12px] tabular-nums" style="color: var(--ink);">
                  {{ row.n_crops_searched || '·' }}
                </td>
                <td class="px-2 py-2 text-right font-mono text-[12px] tabular-nums"
                    :style="{ color: row.n_searched_auto > 0 ? 'var(--success)' : 'var(--ink-400)' }">
                  {{ row.n_searched_auto || '·' }}
                </td>
                <td class="px-2 py-2 text-right font-mono text-[12px] tabular-nums"
                    :style="{ color: row.n_searched_review_single > 0 ? 'var(--gold-600)' : 'var(--ink-400)' }">
                  {{ row.n_searched_review_single || '·' }}
                </td>
                <td class="px-2 py-2 text-right font-mono text-[12px] tabular-nums"
                    :style="{ color: row.n_searched_review_lot > 0 ? 'var(--gold-600)' : 'var(--ink-400)' }">
                  {{ row.n_searched_review_lot || '·' }}
                </td>
                <td class="px-2 py-2 text-right font-mono text-[12px] tabular-nums" style="color: var(--ink-400);">
                  {{ row.n_searched_pending || '·' }}
                </td>
                <td class="px-2 py-2 text-right font-mono text-[12px] tabular-nums"
                    :style="{ color: row.n_searched_rejected > 0 ? 'var(--danger)' : 'var(--ink-400)' }">
                  {{ row.n_searched_rejected || '·' }}
                </td>
                <td class="px-2 py-2 text-right font-mono text-[12px] tabular-nums"
                    :style="{ color: row.n_attributed_from_other > 0 ? 'var(--indigo-700)' : 'var(--ink-400)' }">
                  {{ row.n_attributed_from_other || '·' }}
                </td>
                <td class="px-2 py-2 text-right font-mono text-[12px] tabular-nums"
                    :style="{ color: row.n_quotes > 0 ? 'var(--success)' : 'var(--ink-400)' }">
                  {{ row.n_quotes || '·' }}
                </td>
                <td class="px-2 py-2">
                  <span
                    v-if="row.via_lot"
                    class="inline-flex items-center gap-1 rounded-full px-1.5 py-0.5 font-mono text-[10px]"
                    style="background: color-mix(in srgb, var(--gold-600) 12%, var(--surface)); color: var(--gold-600);"
                  >
                    <Package class="h-2.5 w-2.5" /> lot
                  </span>
                  <span v-else style="color: var(--ink-400);">·</span>
                </td>
                <td class="px-3 py-2 text-right">
                  <button
                    v-if="row.n_searched_review_single + row.n_searched_review_lot > 0"
                    class="inline-flex items-center gap-1 rounded-md border px-2 py-0.5 font-mono text-[10px] transition-colors"
                    style="border-color: var(--surface-3); color: var(--gold-600); background: var(--surface);"
                    @mouseenter="(e) => { const el = e.currentTarget as HTMLElement; el.style.borderColor = 'var(--gold-600)'; el.style.background = 'color-mix(in srgb, var(--gold-600) 8%, var(--surface))'; }"
                    @mouseleave="(e) => { const el = e.currentTarget as HTMLElement; el.style.borderColor = 'var(--surface-3)'; el.style.background = 'var(--surface)'; }"
                    @click.stop="gotoReview(row)"
                    title="Reviewer ce run (atterrit sur la file Single ou Lot selon les compteurs)"
                  >
                    <Search class="h-2.5 w-2.5" /> review
                    <ExternalLink class="h-2.5 w-2.5" />
                  </button>
                  <span v-else style="color: var(--ink-400);">·</span>
                </td>
              </tr>
              <tr
                class="border-t font-semibold"
                style="border-color: var(--surface-3); background: var(--surface-1);"
              >
                <td class="px-3 py-2 font-mono text-[10px] uppercase tracking-wider" style="color: var(--ink-500);">
                  Total
                </td>
                <td class="px-2 py-2 text-right font-mono text-[12px] tabular-nums" style="color: var(--ink);">{{ totalsTargeted.n_listings }}</td>
                <td class="px-2 py-2 text-right font-mono text-[12px] tabular-nums" style="color: var(--ink);">{{ totalsTargeted.n_crops_searched }}</td>
                <td class="px-2 py-2 text-right font-mono text-[12px] tabular-nums" style="color: var(--ink);">{{ totalsTargeted.n_searched_auto }}</td>
                <td class="px-2 py-2 text-right font-mono text-[12px] tabular-nums" style="color: var(--ink);">{{ totalsTargeted.n_searched_review_single }}</td>
                <td class="px-2 py-2 text-right font-mono text-[12px] tabular-nums" style="color: var(--ink);">{{ totalsTargeted.n_searched_review_lot }}</td>
                <td class="px-2 py-2 text-right font-mono text-[12px] tabular-nums" style="color: var(--ink);">{{ totalsTargeted.n_searched_pending }}</td>
                <td class="px-2 py-2 text-right font-mono text-[12px] tabular-nums" style="color: var(--ink);">{{ totalsTargeted.n_searched_rejected }}</td>
                <td class="px-2 py-2 text-right font-mono text-[12px] tabular-nums" style="color: var(--ink);">{{ totalsTargeted.n_attributed_from_other }}</td>
                <td class="px-2 py-2 text-right font-mono text-[12px] tabular-nums" style="color: var(--ink);">{{ totalsTargeted.n_quotes }}</td>
                <td class="px-2 py-2"></td>
                <td class="px-3 py-2"></td>
              </tr>
            </tbody>
          </table>
        </div>
      </section>

      <!-- Section : découverts -->
      <section v-if="discovered.length">
        <h2
          class="mb-3 inline-flex items-center gap-2 font-mono text-[11px] uppercase tracking-wider"
          style="color: var(--gold-600);"
        >
          <Package class="h-3 w-3" />
          Découverts hors cible <span style="color: var(--ink-400);">·</span>
          <span style="color: var(--ink-500);">{{ discovered.length }}</span>
        </h2>
        <div
          class="overflow-hidden rounded-lg border"
          style="border-color: var(--surface-3); background: var(--surface);"
        >
          <table class="w-full text-left text-sm">
            <thead>
              <tr
                class="font-mono text-[10px] uppercase tracking-wider"
                style="background: var(--surface-1); color: var(--ink-500);"
              >
                <th class="px-3 py-2.5 font-medium" title="Identifiant canonique de la pièce — clic ligne ouvre la fiche">eurio_id</th>
                <th class="px-2 py-2.5 text-right font-medium" title="Crops résolus à cet eurio depuis un listing cherché pour autre chose (axe attribution)">Attr.</th>
                <th class="px-2 py-2.5 font-medium" title="Au moins un listing associé est is_lot_suspected ou multi-crop">Lot ?</th>
                <th class="px-2 py-2.5 text-right font-medium" title="coin_market_quotes générés pour cet eurio depuis ce run">Quotes</th>
                <th class="px-3 py-2.5 font-medium" title="Lien vers la file de review filtrée run+eurio">
                  <span class="inline-flex items-center gap-1">
                    <Search class="h-2.5 w-2.5" /> Review
                  </span>
                </th>
              </tr>
            </thead>
            <tbody>
              <tr
                v-for="row in discovered"
                :key="row.eurio_id"
                class="cursor-pointer border-t transition-colors"
                style="border-color: var(--surface-2);"
                :title="`Voir les listings pour ${row.eurio_id}`"
                @mouseenter="(e) => ((e.currentTarget as HTMLElement).style.background = 'var(--surface-1)')"
                @mouseleave="(e) => ((e.currentTarget as HTMLElement).style.background = 'transparent')"
                @click="(ev) => onRowClick(ev, row.eurio_id)"
              >
                <td class="px-3 py-2 font-mono text-[11px]" style="color: var(--ink);">
                  {{ row.eurio_id }}
                </td>
                <td class="px-2 py-2 text-right font-mono text-[12px] tabular-nums"
                    :style="{ color: 'var(--indigo-700)' }">
                  {{ row.n_attributed_from_other }}
                </td>
                <td class="px-2 py-2">
                  <span
                    v-if="row.via_lot"
                    class="inline-flex items-center gap-1 rounded-full px-1.5 py-0.5 font-mono text-[10px]"
                    style="background: color-mix(in srgb, var(--gold-600) 12%, var(--surface)); color: var(--gold-600);"
                  >
                    <Package class="h-2.5 w-2.5" /> lot
                  </span>
                  <span v-else style="color: var(--ink-400);">·</span>
                </td>
                <td class="px-2 py-2 text-right font-mono text-[12px] tabular-nums"
                    :style="{ color: row.n_quotes > 0 ? 'var(--success)' : 'var(--ink-400)' }">
                  {{ row.n_quotes || '·' }}
                </td>
                <td class="px-3 py-2 text-right">
                  <button
                    class="inline-flex items-center gap-1 rounded-md border px-2 py-0.5 font-mono text-[10px] transition-colors"
                    style="border-color: var(--surface-3); color: var(--gold-600); background: var(--surface);"
                    @mouseenter="(e) => { const el = e.currentTarget as HTMLElement; el.style.borderColor = 'var(--gold-600)'; el.style.background = 'color-mix(in srgb, var(--gold-600) 8%, var(--surface))'; }"
                    @mouseleave="(e) => { const el = e.currentTarget as HTMLElement; el.style.borderColor = 'var(--surface-3)'; el.style.background = 'var(--surface)'; }"
                    @click.stop="gotoReview(row)"
                    title="Reviewer ce run (atterrit sur la file Single ou Lot selon les compteurs)"
                  >
                    <Search class="h-2.5 w-2.5" /> review
                    <ExternalLink class="h-2.5 w-2.5" />
                  </button>
                </td>
              </tr>
              <tr
                class="border-t font-semibold"
                style="border-color: var(--surface-3); background: var(--surface-1);"
              >
                <td class="px-3 py-2 font-mono text-[10px] uppercase tracking-wider" style="color: var(--ink-500);">
                  Total
                </td>
                <td class="px-2 py-2 text-right font-mono text-[12px] tabular-nums" style="color: var(--ink);">{{ totalsDiscovered.n_attributed_from_other }}</td>
                <td class="px-2 py-2"></td>
                <td class="px-2 py-2 text-right font-mono text-[12px] tabular-nums" style="color: var(--ink);">{{ totalsDiscovered.n_quotes }}</td>
                <td class="px-3 py-2"></td>
              </tr>
            </tbody>
          </table>
        </div>
      </section>

      <!-- Légende -->
      <p class="mt-6 max-w-3xl font-mono text-[10px] leading-relaxed" style="color: var(--ink-400);">
        <strong style="color: var(--ink-500);">Légende&nbsp;</strong> ·
        <em>List.</em>&nbsp;= source_images cherchés pour cet eurio
        · <em>Crops</em>&nbsp;= crops dans ces listings (somme exacte de Auto + Rev.S + Rev.L + Pend. + Rej.)
        · <em>Attr.</em>&nbsp;= crops résolus à cet eurio depuis un listing cherché pour <em>autre chose</em>
        (typiquement un coffret) · <em>Lot ?</em>&nbsp;= au moins un listing associé est suspect lot
        ou multi-crop.
      </p>
    </template>
  </div>
</template>
