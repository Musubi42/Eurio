<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { AlertCircle, CloudUpload, Compass, Database, Globe, RefreshCw, Sparkles, Wifi, WifiOff } from 'lucide-vue-next'
import { checkMlApi } from '@/features/training/composables/useTrainingApi'
import {
  fetchCoverage,
  fetchJointIssues,
  fetchZeroCanon,
  runDiscover,
  runHeal,
  runPush,
  type CoverageResponse,
  type DiscoverResponse,
  type HealResponse,
  type JointIssuesResponse,
  type PushResponse,
  type ZeroCanonResponse,
} from '../composables/useReferentialApi'

// ─── State ─────────────────────────────────────────────────────────────

const apiStatus = ref<'checking' | 'online' | 'offline'>('checking')
const coverage = ref<CoverageResponse | null>(null)
const joints = ref<JointIssuesResponse | null>(null)
const zeroCanon = ref<ZeroCanonResponse | null>(null)
const loading = ref(false)
const loadError = ref<string | null>(null)
const healing = ref(false)
const healResult = ref<HealResponse | null>(null)
const healError = ref<string | null>(null)
const discovering = ref(false)
const discoverResult = ref<DiscoverResponse | null>(null)
const discoverError = ref<string | null>(null)
const pushing = ref(false)
const pushResult = ref<PushResponse | null>(null)
const pushError = ref<string | null>(null)

const activeTab = ref<'canonical' | 'local_image' | 'payload' | 'bce_only'>('canonical')

// ─── Loaders ───────────────────────────────────────────────────────────

async function refreshHealth() {
  apiStatus.value = 'checking'
  apiStatus.value = (await checkMlApi()) ? 'online' : 'offline'
}

async function refreshCoverage() {
  loading.value = true
  loadError.value = null
  try {
    const [cov, jts, zc] = await Promise.all([
      fetchCoverage(), fetchJointIssues(), fetchZeroCanon(),
    ])
    coverage.value = cov
    joints.value = jts
    zeroCanon.value = zc
  } catch (err) {
    loadError.value = err instanceof Error ? err.message : 'Erreur de chargement'
  } finally {
    loading.value = false
  }
}

async function triggerDiscover() {
  if (!confirm('Lance Discover : sweep Numista pour 21 pays eurozone × année courante + suivante (~50 calls API). Insère les nouvelles pièces + télécharge leurs images locales.\nContinuer ?')) return
  discovering.value = true
  discoverError.value = null
  discoverResult.value = null
  try {
    discoverResult.value = await runDiscover()
    await refreshCoverage()
  } catch (err) {
    discoverError.value = err instanceof Error ? err.message : 'Erreur Discover'
  } finally {
    discovering.value = false
  }
}

async function triggerPush() {
  if (!confirm('Push eurio.db → Supabase. 4 étapes : rewrite URLs, upload images Storage, sync tables PostgREST, DELETE zombies.\nUtilise SUPABASE_SERVICE_ROLE_KEY. Continuer ?')) return
  pushing.value = true
  pushError.value = null
  pushResult.value = null
  try {
    pushResult.value = await runPush()
    await refreshCoverage()
  } catch (err) {
    pushError.value = err instanceof Error ? err.message : 'Erreur Push'
  } finally {
    pushing.value = false
  }
}

async function triggerHeal() {
  if (!confirm('Lance Heal : enrich payloads + migrate canonical schema + sync images locales. ~2-5 min sur 0 gaps, plus si nouveaux.\nContinuer ?')) return
  healing.value = true
  healError.value = null
  healResult.value = null
  try {
    healResult.value = await runHeal()
    await refreshCoverage()
  } catch (err) {
    healError.value = err instanceof Error ? err.message : 'Erreur Heal'
  } finally {
    healing.value = false
  }
}

onMounted(async () => {
  await refreshHealth()
  if (apiStatus.value === 'online') await refreshCoverage()
})

// ─── Derived ───────────────────────────────────────────────────────────

const activeYears = computed(() => {
  if (!coverage.value) return []
  return coverage.value.by_year.filter(y => y.n_bce_listed > 0 || y.n_eurio_db > 0)
})

const maxBarValue = computed(() =>
  Math.max(1, ...activeYears.value.flatMap(y => [y.n_bce_listed, y.n_eurio_db])),
)

const totalGaps = computed(() => {
  if (!coverage.value) return 0
  const s = coverage.value.summary
  return s.n_missing_canonical + s.n_missing_payload + s.n_missing_local_image + s.n_bce_only
})

function tabCount(tab: typeof activeTab.value): number {
  if (!coverage.value) return 0
  const s = coverage.value.summary
  if (tab === 'canonical') return s.n_missing_canonical
  if (tab === 'local_image') return s.n_missing_local_image
  if (tab === 'payload') return s.n_missing_payload
  return s.n_bce_only
}
</script>

<template>
  <div class="p-8">
    <!-- ═══ Header ═══ -->
    <header class="mb-6 flex items-start justify-between">
      <div>
        <h1
          class="font-display text-2xl italic font-semibold"
          style="color: var(--indigo-700);"
        >
          Référentiel
        </h1>
        <p class="mt-0.5 text-sm" style="color: var(--ink-500);">
          Complétude du catalogue commémo 2 € — eurio.db (vérité) vs BCE (oracle)
          <span
            class="ml-2 rounded-sm px-1.5 py-0.5 font-mono text-[10px] uppercase tracking-wider"
            style="background: var(--surface-1); color: var(--ink-500); border: 1px solid var(--surface-3);"
          >
            Chunk B · Heal
          </span>
        </p>
      </div>

      <div class="flex items-center gap-3">
        <div
          class="flex items-center gap-2 rounded-full border px-3 py-1 text-xs"
          :style="{
            borderColor: apiStatus === 'online' ? 'var(--success)' : 'var(--danger)',
            color: apiStatus === 'online' ? 'var(--success)' : 'var(--danger)',
            background: apiStatus === 'online'
              ? 'color-mix(in srgb, var(--success) 6%, var(--surface))'
              : 'color-mix(in srgb, var(--danger) 6%, var(--surface))',
          }"
        >
          <Wifi v-if="apiStatus === 'online'" class="h-3 w-3" />
          <WifiOff v-else class="h-3 w-3" />
          {{ apiStatus === 'online' ? 'ML API connectée' : 'ML API hors-ligne' }}
        </div>
        <button
          v-if="apiStatus === 'online'"
          class="inline-flex items-center gap-1.5 rounded-md border px-3 py-1.5 text-xs font-medium"
          style="border-color: var(--surface-3); color: var(--ink-500);"
          :disabled="loading"
          @click="refreshCoverage"
        >
          <RefreshCw class="h-3 w-3" :class="{ 'animate-spin': loading }" /> Refresh
        </button>
      </div>
    </header>

    <!-- ═══ Offline banner ═══ -->
    <div
      v-if="apiStatus === 'offline'"
      class="mb-6 rounded-lg border-2 border-dashed px-5 py-6 text-center"
      style="border-color: var(--danger); background: color-mix(in srgb, var(--danger) 4%, var(--surface));"
    >
      <WifiOff class="mx-auto mb-2 h-6 w-6" style="color: var(--danger);" />
      <p class="text-sm font-medium" style="color: var(--danger);">
        ML API non jointe (http://127.0.0.1:8042)
      </p>
      <p class="mt-1 text-xs" style="color: var(--ink-500);">
        Lance
        <code style="background: var(--surface-1); padding: 1px 4px; border-radius: 3px;">go-task ml:api</code>
        puis clique sur réessayer.
      </p>
      <button
        class="mt-3 inline-flex items-center gap-1.5 rounded-md px-3 py-1.5 text-xs font-medium"
        style="background: var(--ink); color: var(--surface);"
        @click="refreshHealth"
      >
        <RefreshCw class="h-3 w-3" /> Réessayer
      </button>
    </div>

    <div
      v-if="loadError"
      class="mb-6 rounded-lg border px-5 py-3 text-sm"
      style="border-color: var(--danger); background: color-mix(in srgb, var(--danger) 4%, var(--surface)); color: var(--danger);"
    >
      <AlertCircle class="mr-1 inline-block h-4 w-4 -mt-0.5" />
      {{ loadError }}
    </div>

    <template v-if="apiStatus === 'online' && coverage">
      <!-- ═══ Summary cards ═══ -->
      <section class="mb-6 grid grid-cols-2 gap-3 lg:grid-cols-5">
        <div class="rounded-lg border px-4 py-3" style="border-color: var(--surface-3); background: var(--surface);">
          <div class="text-[11px] uppercase tracking-wider" style="color: var(--ink-500);">BCE listed</div>
          <div class="mt-0.5 font-mono text-xl font-bold" style="color: var(--ink);">
            {{ coverage.summary.n_bce_listed_total }}
          </div>
          <div class="mt-0.5 text-[10px]" style="color: var(--ink-500);">oracle officiel</div>
        </div>
        <div class="rounded-lg border px-4 py-3" style="border-color: var(--surface-3); background: var(--surface);">
          <div class="text-[11px] uppercase tracking-wider" style="color: var(--ink-500);">eurio.db</div>
          <div class="mt-0.5 font-mono text-xl font-bold" style="color: var(--indigo-700);">
            {{ coverage.summary.n_eurio_db_total }}
          </div>
          <div class="mt-0.5 text-[10px]" style="color: var(--ink-500);">notre vérité</div>
        </div>
        <div class="rounded-lg border px-4 py-3" style="border-color: var(--surface-3); background: var(--surface);">
          <div class="text-[11px] uppercase tracking-wider" style="color: var(--ink-500);">Avec canonical</div>
          <div class="mt-0.5 font-mono text-xl font-bold"
               :style="{ color: coverage.summary.n_missing_canonical ? 'var(--warning, #d97706)' : 'var(--success)' }">
            {{ coverage.summary.n_with_canonical_total }}
          </div>
          <div class="mt-0.5 text-[10px]" style="color: var(--ink-500);">
            {{ coverage.summary.n_missing_canonical }} manquantes
          </div>
        </div>
        <div class="rounded-lg border px-4 py-3" style="border-color: var(--surface-3); background: var(--surface);">
          <div class="text-[11px] uppercase tracking-wider" style="color: var(--ink-500);">Image locale</div>
          <div class="mt-0.5 font-mono text-xl font-bold"
               :style="{ color: coverage.summary.n_missing_local_image ? 'var(--warning, #d97706)' : 'var(--success)' }">
            {{ coverage.summary.n_with_local_image_total }}
          </div>
          <div class="mt-0.5 text-[10px]" style="color: var(--ink-500);">
            {{ coverage.summary.n_missing_local_image }} sans local_path
          </div>
        </div>
        <div class="rounded-lg border px-4 py-3"
             :style="{
               borderColor: coverage.summary.n_bce_only > 0 ? 'var(--warning, #d97706)' : 'var(--surface-3)',
               background: coverage.summary.n_bce_only > 0
                 ? 'color-mix(in srgb, var(--warning, #d97706) 6%, var(--surface))'
                 : 'var(--surface)',
             }">
          <div class="text-[11px] uppercase tracking-wider" style="color: var(--ink-500);">BCE-only</div>
          <div class="mt-0.5 font-mono text-xl font-bold"
               :style="{ color: coverage.summary.n_bce_only ? 'var(--warning, #d97706)' : 'var(--success)' }">
            {{ coverage.summary.n_bce_only }}
          </div>
          <div class="mt-0.5 text-[10px]" style="color: var(--ink-500);">
            à découvrir via Numista
          </div>
        </div>
      </section>

      <!-- ═══ Discover action (Numista oracle) ═══ -->
      <section class="mb-6 rounded-lg border p-5"
               style="border-color: var(--surface-3); background: var(--surface);">
        <div class="flex items-start justify-between gap-4">
          <div class="flex-1">
            <h2 class="flex items-center gap-2 font-mono text-xs uppercase tracking-wider" style="color: var(--ink-500);">
              <Compass class="h-3.5 w-3.5" style="color: var(--indigo-700);" />
              <span style="color: var(--indigo-700);">Discover</span>
              <span class="opacity-60">· Numista oracle pour 2026+</span>
            </h2>
            <p class="mt-2 text-sm" style="color: var(--ink-500);">
              Sweep <strong>/v3/types?issuer={pays}</strong> sur les 21 pays eurozone × année courante + suivante.
              Pour chaque nouveau <code>numista_id</code> détecté : INSERT en <code>coins</code> + <code>coin_canonical_images</code> +
              cascade download local. Idempotent (skip si déjà connu).
              BCE = oracle d'autorité ancienne ; Numista = oracle réactif pour l'année courante.
            </p>
          </div>
          <button
            class="rounded-md px-4 py-2 text-sm font-medium"
            :style="{
              background: discovering ? 'var(--surface-2)' : 'var(--indigo-700)',
              color: 'var(--surface)',
              opacity: discovering ? 0.6 : 1,
              cursor: discovering ? 'wait' : 'pointer',
            }"
            :disabled="discovering"
            @click="triggerDiscover"
          >
            <span class="inline-flex items-center gap-1.5">
              <Compass class="h-3.5 w-3.5" :class="{ 'animate-spin': discovering }" />
              {{ discovering ? 'Discover en cours…' : 'Lancer Discover' }}
            </span>
          </button>
        </div>

        <div
          v-if="discoverError"
          class="mt-4 rounded-md border px-3 py-2 text-xs"
          style="border-color: var(--danger); background: color-mix(in srgb, var(--danger) 4%, var(--surface)); color: var(--danger);"
        >
          <AlertCircle class="mr-1 inline-block h-3.5 w-3.5 -mt-0.5" /> {{ discoverError }}
        </div>

        <div
          v-if="discoverResult"
          class="mt-4 rounded-md border px-4 py-3 text-xs"
          style="border-color: var(--success); background: color-mix(in srgb, var(--success) 4%, var(--surface));"
        >
          <div class="font-medium" style="color: var(--success);">
            Discover terminé en {{ discoverResult.duration_sec.toFixed(1) }} s
            (range {{ discoverResult.year_from }}-{{ discoverResult.year_to }})
          </div>
          <div class="mt-2 space-y-2" style="color: var(--ink-500);">
            <div>
              <div class="font-mono text-[10px] uppercase" style="color: var(--indigo-700);">discover_numista</div>
              <pre class="mt-1 overflow-auto text-[10px]">{{ JSON.stringify(discoverResult.discover_numista, null, 2) }}</pre>
            </div>
            <div v-if="discoverResult.cascade_images">
              <div class="font-mono text-[10px] uppercase" style="color: var(--indigo-700);">cascade_images</div>
              <pre class="mt-1 overflow-auto text-[10px]">{{ JSON.stringify(discoverResult.cascade_images, null, 2) }}</pre>
            </div>
          </div>
        </div>
      </section>

      <!-- ═══ Heal action ═══ -->
      <section class="mb-6 rounded-lg border p-5"
               style="border-color: var(--surface-3); background: var(--surface);">
        <div class="flex items-start justify-between gap-4">
          <div class="flex-1">
            <h2 class="flex items-center gap-2 font-mono text-xs uppercase tracking-wider" style="color: var(--ink-500);">
              <Sparkles class="h-3.5 w-3.5" style="color: var(--indigo-700);" />
              <span style="color: var(--indigo-700);">Heal</span>
              <span class="opacity-60">· combler les gaps existants</span>
            </h2>
            <p class="mt-2 text-sm" style="color: var(--ink-500);">
              Enchaîne <strong>enrich_missing_payloads</strong> (Numista per-coin pour les payloads vides),
              <strong>migrate_canonical_schema</strong> (re-propage <code>images</code> → <code>coin_canonical_images</code>),
              et <strong>migrate_canonical_images_local</strong> (download + WebP + local_path).
              Idempotent — si rien n'est cassé, le run ne consomme rien.
            </p>
            <div v-if="totalGaps" class="mt-2 text-sm font-medium" style="color: var(--warning, #d97706);">
              {{ totalGaps }} gap{{ totalGaps > 1 ? 's' : '' }} détecté{{ totalGaps > 1 ? 's' : '' }}.
            </div>
            <div v-else class="mt-2 text-sm font-medium" style="color: var(--success);">
              Tout est propre. Heal ne fera rien d'utile.
            </div>
          </div>

          <button
            class="rounded-md px-4 py-2 text-sm font-medium"
            :style="{
              background: healing ? 'var(--surface-2)' : 'var(--indigo-700)',
              color: 'var(--surface)',
              opacity: healing ? 0.6 : 1,
              cursor: healing ? 'wait' : 'pointer',
            }"
            :disabled="healing"
            @click="triggerHeal"
          >
            <span class="inline-flex items-center gap-1.5">
              <RefreshCw class="h-3.5 w-3.5" :class="{ 'animate-spin': healing }" />
              {{ healing ? 'Heal en cours…' : 'Lancer Heal' }}
            </span>
          </button>
        </div>

        <div
          v-if="healError"
          class="mt-4 rounded-md border px-3 py-2 text-xs"
          style="border-color: var(--danger); background: color-mix(in srgb, var(--danger) 4%, var(--surface)); color: var(--danger);"
        >
          <AlertCircle class="mr-1 inline-block h-3.5 w-3.5 -mt-0.5" /> {{ healError }}
        </div>

        <div
          v-if="healResult"
          class="mt-4 rounded-md border px-4 py-3 text-xs"
          style="border-color: var(--success); background: color-mix(in srgb, var(--success) 4%, var(--surface));"
        >
          <div class="font-medium" style="color: var(--success);">
            Heal terminé en {{ healResult.duration_sec.toFixed(1) }} s
          </div>
          <div class="mt-2 grid grid-cols-1 gap-2 lg:grid-cols-3" style="color: var(--ink-500);">
            <div>
              <div class="font-mono text-[10px] uppercase" style="color: var(--indigo-700);">enrich_payloads</div>
              <pre class="mt-1 overflow-auto text-[10px]">{{ JSON.stringify(healResult.enrich_payloads, null, 2) }}</pre>
            </div>
            <div>
              <div class="font-mono text-[10px] uppercase" style="color: var(--indigo-700);">migrate_canonical_schema</div>
              <pre class="mt-1 overflow-auto text-[10px]">{{ JSON.stringify(healResult.migrate_canonical_schema, null, 2) }}</pre>
            </div>
            <div>
              <div class="font-mono text-[10px] uppercase" style="color: var(--indigo-700);">migrate_local_images</div>
              <pre class="mt-1 overflow-auto text-[10px]">{{ JSON.stringify(healResult.migrate_local_images, null, 2) }}</pre>
            </div>
          </div>
        </div>
      </section>

      <!-- ═══ Push to Supabase ═══ -->
      <section class="mb-6 rounded-lg border p-5"
               style="border-color: var(--surface-3); background: var(--surface);">
        <div class="flex items-start justify-between gap-4">
          <div class="flex-1">
            <h2 class="flex items-center gap-2 font-mono text-xs uppercase tracking-wider" style="color: var(--ink-500);">
              <CloudUpload class="h-3.5 w-3.5" style="color: var(--indigo-700);" />
              <span style="color: var(--indigo-700);">Push to Supabase</span>
              <span class="opacity-60">· miroir pour l'app Android future</span>
            </h2>
            <p class="mt-2 text-sm" style="color: var(--ink-500);">
              Pousse eurio.db local → Supabase. 4 étapes :
              <strong>rewrite URLs canoniques</strong>,
              <strong>upload Storage</strong> (images locales si absentes côté Supabase),
              <strong>sync tables</strong> (coins / observations / market / i18n / aliases via PostgREST),
              <strong>DELETE zombies</strong> (eurio_id Supabase orphelins).
              Idempotent — re-runner est sûr. Utilise <code>SUPABASE_SERVICE_ROLE_KEY</code>.
            </p>
          </div>
          <button
            class="rounded-md px-4 py-2 text-sm font-medium"
            :style="{
              background: pushing ? 'var(--surface-2)' : 'var(--indigo-700)',
              color: 'var(--surface)',
              opacity: pushing ? 0.6 : 1,
              cursor: pushing ? 'wait' : 'pointer',
            }"
            :disabled="pushing"
            @click="triggerPush"
          >
            <span class="inline-flex items-center gap-1.5">
              <CloudUpload class="h-3.5 w-3.5" :class="{ 'animate-bounce': pushing }" />
              {{ pushing ? 'Push en cours…' : 'Lancer Push' }}
            </span>
          </button>
        </div>

        <div
          v-if="pushError"
          class="mt-4 rounded-md border px-3 py-2 text-xs"
          style="border-color: var(--danger); background: color-mix(in srgb, var(--danger) 4%, var(--surface)); color: var(--danger);"
        >
          <AlertCircle class="mr-1 inline-block h-3.5 w-3.5 -mt-0.5" /> {{ pushError }}
        </div>

        <div
          v-if="pushResult"
          class="mt-4 rounded-md border px-4 py-3 text-xs"
          style="border-color: var(--success); background: color-mix(in srgb, var(--success) 4%, var(--surface));"
        >
          <div class="font-medium" style="color: var(--success);">
            Push terminé en {{ pushResult.duration_sec.toFixed(1) }} s
          </div>
          <div class="mt-2 grid grid-cols-1 gap-2 lg:grid-cols-2" style="color: var(--ink-500);">
            <div v-for="(value, stepKey) in pushResult.summary" :key="stepKey as string">
              <div class="font-mono text-[10px] uppercase" style="color: var(--indigo-700);">{{ stepKey }}</div>
              <pre class="mt-1 overflow-auto text-[10px]">{{ JSON.stringify(value, null, 2) }}</pre>
            </div>
          </div>
        </div>
      </section>

      <!-- ═══ Joint issues ═══ -->
      <section v-if="joints" class="mb-6">
        <h2 class="mb-3 flex items-baseline gap-2 font-mono text-xs uppercase tracking-wider" style="color: var(--ink-500);">
          <Globe class="h-3.5 w-3.5" style="color: var(--indigo-700);" />
          <span style="color: var(--indigo-700);">Joint issues</span>
          <span class="opacity-60">· émissions communes — couverture par pays</span>
        </h2>

        <div class="rounded-lg border" style="border-color: var(--surface-3); background: var(--surface);">
          <table class="w-full text-sm">
            <thead class="text-xs uppercase font-mono" style="background: var(--surface-1); color: var(--ink-500);">
              <tr>
                <th class="px-3 py-2 text-left">Joint issue</th>
                <th class="px-3 py-2 text-right">Année</th>
                <th class="px-3 py-2 text-right">Attendu</th>
                <th class="px-3 py-2 text-right">En db</th>
                <th class="px-3 py-2 text-right">Manquants</th>
                <th class="px-3 py-2 text-left">Pays manquants</th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="j in joints.joint_issues" :key="j.design_group_id"
                  class="border-t" style="border-color: var(--surface-2);">
                <td class="px-3 py-1.5">
                  <div class="text-sm" style="color: var(--ink);">{{ j.designation }}</div>
                  <div class="font-mono text-[10px]" style="color: var(--ink-500);">{{ j.design_group_id }}</div>
                </td>
                <td class="px-3 py-1.5 text-right font-mono text-xs">{{ j.year }}</td>
                <td class="px-3 py-1.5 text-right font-mono text-xs">{{ j.n_expected }}</td>
                <td class="px-3 py-1.5 text-right font-mono text-xs font-semibold"
                    :style="{ color: j.n_in_db === j.n_expected ? 'var(--success)' : 'var(--warning, #d97706)' }">
                  {{ j.n_in_db }}
                </td>
                <td class="px-3 py-1.5 text-right font-mono text-xs"
                    :style="{ color: j.countries_missing.length ? 'var(--warning, #d97706)' : 'var(--success)' }">
                  {{ j.countries_missing.length }}
                </td>
                <td class="px-3 py-1.5">
                  <div class="flex flex-wrap gap-1">
                    <span v-for="c in j.countries_missing" :key="c"
                          class="inline-block rounded-full px-2 py-0.5 font-mono text-[10px]"
                          style="background: color-mix(in srgb, var(--warning, #d97706) 12%, var(--surface)); color: var(--warning, #d97706);">
                      {{ c }}
                    </span>
                    <span v-if="!j.countries_missing.length" class="text-[10px]" style="color: var(--success);">
                      ✓ complet
                    </span>
                  </div>
                </td>
              </tr>
              <tr v-if="!joints.joint_issues.length">
                <td colspan="6" class="px-3 py-6 text-center text-xs" style="color: var(--ink-500);">
                  Aucune joint issue identifiée.
                </td>
              </tr>
            </tbody>
          </table>
        </div>
      </section>

      <!-- ═══ Zero-canon résiduels (BCE-aware) ═══ -->
      <section v-if="zeroCanon" class="mb-6">
        <h2 class="mb-3 flex items-baseline justify-between gap-2 font-mono text-xs uppercase tracking-wider" style="color: var(--ink-500);">
          <span class="flex items-baseline gap-2">
            <AlertCircle class="h-3.5 w-3.5" style="color: var(--indigo-700);" />
            <span style="color: var(--indigo-700);">Zero-canon résiduels</span>
            <span class="opacity-60">
              · {{ zeroCanon.n_residuals }} sans aucune image (DB + BCE FS)
              — couverts BCE : {{ zeroCanon.n_covered_by_bce_fs }}/{{ zeroCanon.n_db_zero_canon }}
            </span>
          </span>
          <span class="flex items-baseline gap-2">
            <router-link to="/referential/fixes"
                         class="rounded-full border px-3 py-1 font-mono text-[10px] normal-case"
                         style="border-color: var(--surface-3); color: var(--indigo-700);">
              Fixes catalog_unlinked →
            </router-link>
            <router-link to="/referential/divergences"
                         class="rounded-full border px-3 py-1 font-mono text-[10px] normal-case"
                         style="border-color: var(--surface-3); color: var(--indigo-700);">
              Voir divergences BCE ↔ Numista →
            </router-link>
            <router-link to="/referential/jo-coverage"
                         class="rounded-full border px-3 py-1 font-mono text-[10px] normal-case"
                         style="border-color: var(--surface-3); color: var(--indigo-700);">
              Couverture Journal Officiel →
            </router-link>
          </span>
        </h2>

        <div class="rounded-lg border" style="border-color: var(--surface-3); background: var(--surface);">
          <table class="w-full text-sm">
            <thead class="text-xs uppercase font-mono" style="background: var(--surface-1); color: var(--ink-500);">
              <tr>
                <th class="px-3 py-2 text-left">Pays</th>
                <th class="px-3 py-2 text-right">Année</th>
                <th class="px-3 py-2 text-left">Thème</th>
                <th class="px-3 py-2 text-right">Numista ID</th>
                <th class="px-3 py-2 text-left">eurio_id</th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="r in zeroCanon.residuals" :key="r.eurio_id"
                  class="border-t" style="border-color: var(--surface-2);">
                <td class="px-3 py-1.5 font-mono text-xs">{{ r.country }}</td>
                <td class="px-3 py-1.5 text-right font-mono text-xs">{{ r.year }}</td>
                <td class="px-3 py-1.5" style="color: var(--ink);">{{ r.theme }}</td>
                <td class="px-3 py-1.5 text-right font-mono text-xs">
                  <a v-if="r.numista_id" :href="`https://en.numista.com/catalogue/pieces${r.numista_id}.html`"
                     target="_blank" rel="noopener" style="color: var(--indigo-700);">
                    {{ r.numista_id }}
                  </a>
                  <span v-else style="color: var(--ink-500);">—</span>
                </td>
                <td class="px-3 py-1.5 font-mono text-[10px]" style="color: var(--ink-500);">
                  {{ r.eurio_id }}
                </td>
              </tr>
              <tr v-if="!zeroCanon.residuals.length">
                <td colspan="5" class="px-3 py-6 text-center text-xs" style="color: var(--success);">
                  ✓ Aucun résiduel — toutes les pièces ont au moins une image (DB ou BCE FS).
                </td>
              </tr>
            </tbody>
          </table>
        </div>
      </section>

      <!-- ═══ Coverage par année ═══ -->
      <section class="mb-6">
        <h2 class="mb-3 flex items-baseline gap-2 font-mono text-xs uppercase tracking-wider" style="color: var(--ink-500);">
          <Database class="h-3.5 w-3.5" style="color: var(--indigo-700);" />
          <span style="color: var(--indigo-700);">Coverage par année</span>
          <span class="opacity-60">· BCE vs eurio.db · with-canonical · with-local-image</span>
        </h2>

        <div class="rounded-lg border p-5" style="border-color: var(--surface-3); background: var(--surface);">
          <div class="space-y-1.5">
            <div
              v-for="y in activeYears"
              :key="y.year"
              class="flex items-center gap-3 text-xs"
            >
              <div class="w-12 font-mono text-right font-medium">{{ y.year }}</div>

              <!-- BCE bar -->
              <div class="flex-1 flex items-center gap-2">
                <div class="relative w-full h-5 rounded" style="background: var(--surface-1);">
                  <div
                    class="absolute inset-y-0 left-0 rounded"
                    :style="{
                      width: `${(y.n_bce_listed / maxBarValue) * 100}%`,
                      background: 'color-mix(in srgb, var(--ink-500) 30%, var(--surface))',
                    }"
                  />
                  <div class="absolute inset-0 flex items-center px-2">
                    <span class="font-mono text-[10px]" style="color: var(--ink-500);">
                      BCE {{ y.n_bce_listed }}
                    </span>
                  </div>
                </div>
                <div class="relative w-full h-5 rounded" style="background: var(--surface-1);">
                  <div
                    class="absolute inset-y-0 left-0 rounded"
                    :style="{
                      width: `${(y.n_with_local_image / maxBarValue) * 100}%`,
                      background: y.n_with_local_image === y.n_eurio_db
                        ? 'color-mix(in srgb, var(--success) 60%, var(--surface))'
                        : 'color-mix(in srgb, var(--warning, #d97706) 60%, var(--surface))',
                    }"
                  />
                  <div
                    v-if="y.n_eurio_db > y.n_with_local_image"
                    class="absolute inset-y-0 rounded"
                    :style="{
                      left: `${(y.n_with_local_image / maxBarValue) * 100}%`,
                      width: `${((y.n_eurio_db - y.n_with_local_image) / maxBarValue) * 100}%`,
                      background: 'color-mix(in srgb, var(--danger) 30%, var(--surface))',
                    }"
                  />
                  <div class="absolute inset-0 flex items-center px-2">
                    <span class="font-mono text-[10px]" style="color: var(--ink-500);">
                      db {{ y.n_eurio_db }} · img {{ y.n_with_local_image }}
                    </span>
                  </div>
                </div>
              </div>

              <div class="w-24 text-right font-mono text-[10px]" style="color: var(--ink-500);">
                <span v-if="y.bce_unmatched_count" :style="{ color: 'var(--warning, #d97706)' }">
                  +{{ y.bce_unmatched_count }} BCE-only
                </span>
              </div>
            </div>
          </div>

          <div class="mt-4 flex items-center gap-4 text-[10px]" style="color: var(--ink-500);">
            <span class="inline-flex items-center gap-1">
              <span class="inline-block h-2 w-3 rounded-sm" style="background: color-mix(in srgb, var(--ink-500) 30%, var(--surface));"></span>
              BCE listed
            </span>
            <span class="inline-flex items-center gap-1">
              <span class="inline-block h-2 w-3 rounded-sm" style="background: color-mix(in srgb, var(--success) 60%, var(--surface));"></span>
              avec image locale
            </span>
            <span class="inline-flex items-center gap-1">
              <span class="inline-block h-2 w-3 rounded-sm" style="background: color-mix(in srgb, var(--warning, #d97706) 60%, var(--surface));"></span>
              partiellement
            </span>
            <span class="inline-flex items-center gap-1">
              <span class="inline-block h-2 w-3 rounded-sm" style="background: color-mix(in srgb, var(--danger) 30%, var(--surface));"></span>
              en gap
            </span>
          </div>
        </div>
      </section>

      <!-- ═══ Gaps tabs ═══ -->
      <section>
        <h2 class="mb-3 flex items-baseline gap-2 font-mono text-xs uppercase tracking-wider" style="color: var(--ink-500);">
          <AlertCircle class="h-3.5 w-3.5" style="color: var(--indigo-700);" />
          <span style="color: var(--indigo-700);">Gaps détaillés</span>
          <span class="opacity-60">· à résoudre par Heal ou Discover</span>
        </h2>

        <div class="rounded-lg border" style="border-color: var(--surface-3); background: var(--surface);">
          <div class="flex border-b" style="border-color: var(--surface-3);">
            <button
              v-for="tab in (['canonical', 'local_image', 'payload', 'bce_only'] as const)"
              :key="tab"
              class="px-4 py-2 text-xs font-medium border-b-2 transition-colors"
              :style="{
                borderColor: activeTab === tab ? 'var(--indigo-700)' : 'transparent',
                color: activeTab === tab ? 'var(--indigo-700)' : 'var(--ink-500)',
              }"
              @click="activeTab = tab"
            >
              {{
                tab === 'canonical' ? 'Sans canonical'
                : tab === 'local_image' ? 'Sans image locale'
                : tab === 'payload' ? 'Sans payload'
                : 'BCE-only'
              }}
              <span
                class="ml-1.5 inline-block rounded-full px-1.5 py-0.5 text-[10px] font-mono"
                :style="{
                  background: tabCount(tab)
                    ? 'color-mix(in srgb, var(--warning, #d97706) 12%, var(--surface))'
                    : 'color-mix(in srgb, var(--success) 12%, var(--surface))',
                  color: tabCount(tab) ? 'var(--warning, #d97706)' : 'var(--success)',
                }"
              >
                {{ tabCount(tab) }}
              </span>
            </button>
          </div>

          <div class="max-h-96 overflow-auto">
            <!-- BCE-only : pas d'eurio_id encore -->
            <table v-if="activeTab === 'bce_only'" class="w-full text-sm">
              <thead class="sticky top-0 text-xs uppercase font-mono"
                     style="background: var(--surface-1); color: var(--ink-500);">
                <tr>
                  <th class="px-3 py-2 text-left">Pays</th>
                  <th class="px-3 py-2 text-left">Année</th>
                  <th class="px-3 py-2 text-left">Feature (BCE)</th>
                  <th class="px-3 py-2 text-left">Image source</th>
                </tr>
              </thead>
              <tbody>
                <tr v-for="b in coverage.bce_only" :key="`${b.country}-${b.year}-${b.feature}`"
                    class="border-t" style="border-color: var(--surface-2);">
                  <td class="px-3 py-1.5 font-mono text-xs">{{ b.country }}</td>
                  <td class="px-3 py-1.5 font-mono text-xs">{{ b.year }}</td>
                  <td class="px-3 py-1.5">{{ b.feature }}</td>
                  <td class="px-3 py-1.5 text-xs">
                    <a :href="b.image_url" target="_blank" class="hover:underline" style="color: var(--indigo-700);">
                      voir
                    </a>
                  </td>
                </tr>
                <tr v-if="!coverage.bce_only.length">
                  <td colspan="4" class="px-3 py-6 text-center text-xs" style="color: var(--ink-500);">
                    Aucune pièce BCE absente d'eurio.db. ✅
                  </td>
                </tr>
              </tbody>
            </table>

            <!-- Eurio.db gaps -->
            <table v-else class="w-full text-sm">
              <thead class="sticky top-0 text-xs uppercase font-mono"
                     style="background: var(--surface-1); color: var(--ink-500);">
                <tr>
                  <th class="px-3 py-2 text-left">Eurio ID</th>
                  <th class="px-3 py-2 text-left">Pays · année</th>
                  <th class="px-3 py-2 text-left">Theme</th>
                  <th class="px-3 py-2 text-right">Numista ID</th>
                </tr>
              </thead>
              <tbody>
                <tr v-for="g in (
                  activeTab === 'canonical' ? coverage.gaps_missing_canonical
                  : activeTab === 'local_image' ? coverage.gaps_missing_local_image
                  : coverage.gaps_missing_payload
                )" :key="g.eurio_id" class="border-t" style="border-color: var(--surface-2);">
                  <td class="px-3 py-1.5 font-mono text-xs">
                    <router-link :to="`/coins/${g.eurio_id}`" class="hover:underline" style="color: var(--indigo-700);">
                      {{ g.eurio_id }}
                    </router-link>
                  </td>
                  <td class="px-3 py-1.5 text-xs" style="color: var(--ink-500);">
                    {{ g.country }} · {{ g.year }}
                  </td>
                  <td class="px-3 py-1.5 text-xs">{{ g.theme || '—' }}</td>
                  <td class="px-3 py-1.5 text-right font-mono text-xs">{{ g.numista_id || '—' }}</td>
                </tr>
                <tr v-if="tabCount(activeTab) === 0">
                  <td colspan="4" class="px-3 py-6 text-center text-xs" style="color: var(--success);">
                    Aucun gap dans cette catégorie. ✅
                  </td>
                </tr>
              </tbody>
            </table>
          </div>
        </div>
      </section>
    </template>
  </div>
</template>
