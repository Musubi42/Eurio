<script setup lang="ts">
import {
  checkMlApiOnline,
  fetchCoinDetail,
  type CoinConfusionDetail,
} from '@/features/confusion/composables/useConfusionMap'
import { zoneCopy, zoneStyle } from '@/features/confusion/composables/useConfusionZone'
import { supabase } from '@/shared/supabase/client'
import type { Coin, CoinImage, CoinImageDict, CoinSeries, IssueType } from '@/shared/supabase/types'
import {
  ArrowLeft,
  ArrowUpRight,
  Brain,
  Calendar,
  Check,
  Coins as CoinsIcon,
  Copy,
  ExternalLink,
  ImageOff,
  Info,
  Layers,
  Loader2,
  MapPin,
  Network,
  Play,
  ShieldAlert,
} from 'lucide-vue-next'
import { computed, onMounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'

const route = useRoute()
const router = useRouter()

const coin = ref<Coin | null>(null)
const series = ref<CoinSeries | null>(null)
const loading = ref(true)
const error = ref<string | null>(null)
const selectedImage = ref<CoinImage | null>(null)
const trainedModelVersion = ref<string | null>(null)

// Training enqueue
const ML_API = 'http://localhost:8042'
const enqueueState = ref<'idle' | 'loading' | 'success'>('idle')

// Confusion-map detail (Phase 1 ML scalability)
const confusion = ref<CoinConfusionDetail | null>(null)
const confusionLoading = ref(false)

const issueLabel: Record<IssueType, string> = {
  'circulation':       'Circulation',
  'commemo-national':  'Commémo nationale',
  'commemo-common':    'Commémo commune',
  'starter-kit':       'Starter kit',
  'bu-set':            'BU set',
  'proof':             'Proof',
}

const roleLabel: Record<string, string> = {
  obverse: 'Avers',
  reverse: 'Revers',
  edge:    'Tranche',
  detail:  'Détail',
}

async function fetchCoin(eurioId: string) {
  loading.value = true
  error.value = null
  coin.value = null
  series.value = null
  selectedImage.value = null

  const { data, error: err } = await supabase
    .from('coins')
    .select('*')
    .eq('eurio_id', eurioId)
    .maybeSingle()

  if (err) { error.value = err.message; loading.value = false; return }
  if (!data) { error.value = 'Pièce introuvable'; loading.value = false; return }

  coin.value = data as Coin

  // Normalize images: dict format → array for consistent UI handling
  const raw = coin.value.images
  if (raw && !Array.isArray(raw)) {
    const dict = raw as CoinImageDict
    const normalized: CoinImage[] = []
    if (dict.obverse) normalized.push({ url: dict.obverse, role: 'obverse', source: 'numista' })
    if (dict.reverse) normalized.push({ url: dict.reverse, role: 'reverse', source: 'numista' })
    coin.value.images = normalized
  }
  const imgs = coin.value.images as CoinImage[]
  selectedImage.value = imgs[0] ?? null

  // Fetch series si applicable
  if (coin.value.series_id) {
    const { data: s } = await supabase
      .from('coin_series')
      .select('*')
      .eq('id', coin.value.series_id)
      .maybeSingle()
    if (s) series.value = s as CoinSeries
  }

  // Check training status
  trainedModelVersion.value = null
  const { data: emb } = await supabase
    .from('coin_embeddings')
    .select('model_version')
    .eq('eurio_id', coin.value.eurio_id)
    .maybeSingle() as { data: { model_version: string } | null }
  if (emb) trainedModelVersion.value = emb.model_version

  loading.value = false

  // Confusion map — non-blocking; prefer ML API if reachable, fallback to Supabase
  loadConfusion(coin.value.eurio_id)
}

async function loadConfusion(eurioId: string) {
  confusionLoading.value = true
  confusion.value = null
  try {
    const online = await checkMlApiOnline()
    confusion.value = await fetchCoinDetail(eurioId, online)
  } catch {
    confusion.value = null
  } finally {
    confusionLoading.value = false
  }
}

onMounted(() => fetchCoin(route.params.eurio_id as string))
watch(() => route.params.eurio_id, (v) => { if (v) fetchCoin(v as string) })

function formatFaceValue(v: number): string {
  if (v >= 1) return `${v.toFixed(0)} €`
  return `${(v * 100).toFixed(0)} centimes`
}

function formatDate(iso: string | null) {
  if (!iso) return null
  return new Date(iso).toLocaleDateString('fr-FR', {
    year: 'numeric', month: 'long', day: 'numeric',
  })
}

const seriesMintingPeriod = computed(() => {
  if (!series.value) return null
  const start = new Date(series.value.minting_started_at).getFullYear()
  const end = series.value.minting_ended_at
    ? new Date(series.value.minting_ended_at).getFullYear()
    : null
  return end ? `${start} – ${end}` : `${start} – présent`
})

async function enqueueForTraining() {
  if (!coin.value) return
  const c = coin.value
  // The ArcFace class is the design_group when present (all members share the
  // label), else the eurio_id. No numista_id is needed — the resolver expands
  // the class into source numista dirs at augment time.
  if (!c.design_group_id && !c.cross_refs?.numista_id) return
  const classId = c.design_group_id || c.eurio_id
  const classKind: 'eurio_id' | 'design_group_id' =
    c.design_group_id ? 'design_group_id' : 'eurio_id'
  enqueueState.value = 'loading'
  try {
    const resp = await fetch(`${ML_API}/training/stage`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ items: [{ class_id: classId, class_kind: classKind }] }),
    })
    if (resp.ok) {
      enqueueState.value = 'success'
      setTimeout(() => router.push('/training'), 1000)
    } else {
      enqueueState.value = 'idle'
    }
  } catch {
    enqueueState.value = 'idle'
  }
}

// ─── Clipboard copy ───

const copiedToast = ref<{ label: string, value: string } | null>(null)
let copiedToastTimer: ReturnType<typeof setTimeout> | null = null

function copyToClipboard(value: string, label: string, event: Event) {
  event.stopPropagation()
  navigator.clipboard?.writeText(value)
  copiedToast.value = { label, value }
  if (copiedToastTimer) clearTimeout(copiedToastTimer)
  copiedToastTimer = setTimeout(() => { copiedToast.value = null }, 1500)
}

function goToConfusionCoin(eurioId: string) {
  router.push(`/coins/${encodeURIComponent(eurioId)}`)
}

const confusionNearest = computed(() => {
  if (!confusion.value) return null
  // The API contract puts nearest as first neighbor; fallback: find by nearest_eurio_id
  if (confusion.value.nearest_eurio_id) {
    const match = confusion.value.top_k_neighbors.find(
      n => n.eurio_id === confusion.value!.nearest_eurio_id,
    )
    if (match) return match
  }
  return confusion.value.top_k_neighbors[0] ?? null
})

const confusionOtherNeighbors = computed(() => {
  if (!confusion.value || !confusionNearest.value) return []
  return confusion.value.top_k_neighbors.filter(
    n => n.eurio_id !== confusionNearest.value!.eurio_id,
  )
})

const crossRefLinks = computed(() => {
  if (!coin.value) return []
  const links: { label: string; url: string }[] = []
  const refs = coin.value.cross_refs
  if (refs.wikipedia_url) links.push({ label: 'Wikipedia', url: refs.wikipedia_url })
  if (refs.lmdlp_url) links.push({ label: 'La Monnaie de la Pièce', url: refs.lmdlp_url })
  if (refs.mdp_urls) refs.mdp_urls.forEach((u, i) =>
    links.push({ label: `Monnaie de Paris ${refs.mdp_urls!.length > 1 ? `#${i+1}` : ''}`, url: u }),
  )
  if (refs.numista_url) links.push({ label: 'Numista', url: refs.numista_url })
  return links
})
</script>

<template>
  <div class="mx-auto max-w-5xl p-8">
    <!-- Back -->
    <button
      class="mb-6 flex items-center gap-2 text-sm transition-opacity hover:opacity-70"
      style="color: var(--ink-500);"
      @click="router.back()"
    >
      <ArrowLeft class="h-4 w-4" />
      Retour au référentiel
    </button>

    <!-- Loading -->
    <div v-if="loading" class="grid grid-cols-1 gap-8 lg:grid-cols-2">
      <div class="aspect-square animate-pulse rounded-lg" style="background: var(--surface-1);" />
      <div class="space-y-3">
        <div class="h-8 w-3/4 animate-pulse rounded" style="background: var(--surface-1);" />
        <div class="h-4 w-1/2 animate-pulse rounded" style="background: var(--surface-1);" />
        <div class="h-4 w-2/3 animate-pulse rounded" style="background: var(--surface-1);" />
      </div>
    </div>

    <!-- Error -->
    <div v-else-if="error"
         class="flex flex-col items-center justify-center rounded-lg border-2 border-dashed py-16"
         style="border-color: var(--surface-3);">
      <ShieldAlert class="mb-3 h-8 w-8" style="color: var(--danger);" />
      <p class="font-display italic text-lg" style="color: var(--ink);">{{ error }}</p>
    </div>

    <!-- Content -->
    <div v-else-if="coin" class="grid grid-cols-1 gap-8 lg:grid-cols-2">

      <!-- ═══ LEFT : Images ═══ -->
      <div>
        <!-- Main image frame -->
        <div
          class="relative flex aspect-square items-center justify-center overflow-hidden rounded-lg"
          style="background: linear-gradient(160deg, var(--surface-1), var(--surface-2)); box-shadow: var(--shadow-card);"
        >
          <template v-if="selectedImage">
            <img
              :src="selectedImage.url"
              :alt="coin.theme ?? coin.eurio_id"
              class="h-full w-full object-contain p-8"
            />
            <!-- Role label -->
            <span
              class="absolute bottom-3 left-3 rounded-full px-3 py-1 text-[10px] font-mono font-medium uppercase tracking-wider"
              style="background: rgba(14,14,31,0.8); color: white; backdrop-filter: blur(4px);"
            >
              {{ roleLabel[selectedImage.role] ?? selectedImage.role }}
            </span>
            <span
              class="absolute bottom-3 right-3 rounded-full px-3 py-1 text-[10px] font-mono uppercase tracking-wider"
              style="background: rgba(14,14,31,0.8); color: rgba(255,255,255,0.6); backdrop-filter: blur(4px);"
            >
              src: {{ selectedImage.source }}
            </span>
          </template>
          <div v-else class="flex flex-col items-center gap-2" style="color: var(--ink-300);">
            <ImageOff class="h-12 w-12" />
            <p class="text-xs uppercase tracking-wider">Aucune image disponible</p>
            <p class="text-[10px]" style="color: var(--ink-400);">
              Pipeline Numista à venir (phase 4)
            </p>
          </div>
        </div>

        <!-- Thumbnails -->
        <div v-if="Array.isArray(coin.images) && coin.images.length > 1"
             class="mt-3 flex gap-2 overflow-x-auto">
          <button
            v-for="(img, i) in (coin.images as CoinImage[])"
            :key="i"
            class="flex h-16 w-16 flex-shrink-0 items-center justify-center rounded-md border-2 transition-all"
            :style="selectedImage === img
              ? 'border-color: var(--gold); background: var(--surface-1)'
              : 'border-color: var(--surface-3); background: var(--surface)'"
            @click="selectedImage = img"
          >
            <img :src="img.url" :alt="img.role" class="h-full w-full object-contain p-1" />
          </button>
        </div>
      </div>

      <!-- ═══ RIGHT : Metadata ═══ -->
      <div>
        <!-- Header -->
        <div class="mb-5">
          <p class="mb-1 text-xs font-medium uppercase"
             style="color: var(--ink-500); letter-spacing: var(--tracking-eyebrow);">
            {{ coin.country }} · {{ coin.year }}
          </p>
          <h1 class="font-display text-3xl italic font-semibold leading-tight"
              style="color: var(--indigo-700);">
            {{ coin.theme ?? formatFaceValue(coin.face_value) }}
          </h1>
          <p v-if="coin.theme" class="mt-1 font-mono text-sm" style="color: var(--ink-400);">
            {{ formatFaceValue(coin.face_value) }}
          </p>
        </div>

        <!-- Gold separator -->
        <div class="mb-5 h-px w-16" style="background: var(--gold);" />

        <!-- Quick facts grid -->
        <div class="space-y-3">
          <!-- Face value -->
          <div class="flex items-start gap-3">
            <CoinsIcon class="mt-0.5 h-4 w-4 flex-shrink-0" style="color: var(--ink-400);" />
            <div class="flex-1">
              <p class="text-[10px] uppercase tracking-wider" style="color: var(--ink-500);">
                Valeur faciale
              </p>
              <p class="font-mono text-sm" style="color: var(--ink);">
                {{ formatFaceValue(coin.face_value) }}
              </p>
            </div>
          </div>

          <!-- Country + year -->
          <div class="flex items-start gap-3">
            <MapPin class="mt-0.5 h-4 w-4 flex-shrink-0" style="color: var(--ink-400);" />
            <div class="flex-1">
              <p class="text-[10px] uppercase tracking-wider" style="color: var(--ink-500);">
                Pays · année
              </p>
              <p class="text-sm" style="color: var(--ink);">
                <span class="font-mono uppercase">{{ coin.country }}</span> ·
                <span class="font-mono">{{ coin.year }}</span>
              </p>
            </div>
          </div>

          <!-- Issue type -->
          <div v-if="coin.issue_type" class="flex items-start gap-3">
            <Info class="mt-0.5 h-4 w-4 flex-shrink-0" style="color: var(--ink-400);" />
            <div class="flex-1">
              <p class="text-[10px] uppercase tracking-wider" style="color: var(--ink-500);">
                Type d'émission
              </p>
              <p class="text-sm" style="color: var(--ink);">{{ issueLabel[coin.issue_type] }}</p>
            </div>
          </div>

          <!-- Series -->
          <div v-if="series" class="flex items-start gap-3">
            <Layers class="mt-0.5 h-4 w-4 flex-shrink-0" style="color: var(--ink-400);" />
            <div class="flex-1">
              <p class="text-[10px] uppercase tracking-wider" style="color: var(--ink-500);">
                Série
              </p>
              <p class="text-sm" style="color: var(--ink);">
                {{ series.designation_i18n?.fr ?? series.designation }}
              </p>
              <p class="font-mono text-[11px]" style="color: var(--ink-400);">
                {{ series.id }} · {{ seriesMintingPeriod }}
                <span v-if="series.minting_ended_at">· frappe arrêtée</span>
              </p>
            </div>
          </div>

          <!-- Withdrawal -->
          <div v-if="coin.is_withdrawn" class="flex items-start gap-3">
            <ShieldAlert class="mt-0.5 h-4 w-4 flex-shrink-0" style="color: var(--danger);" />
            <div class="flex-1">
              <p class="text-[10px] uppercase tracking-wider" style="color: var(--danger);">
                Retirée de circulation
              </p>
              <p class="text-sm" style="color: var(--ink);">
                {{ formatDate(coin.withdrawn_at) }}
                <span v-if="coin.withdrawal_reason">· {{ coin.withdrawal_reason }}</span>
              </p>
            </div>
          </div>

          <!-- Mintage -->
          <div v-if="coin.mintage" class="flex items-start gap-3">
            <Calendar class="mt-0.5 h-4 w-4 flex-shrink-0" style="color: var(--ink-400);" />
            <div class="flex-1">
              <p class="text-[10px] uppercase tracking-wider" style="color: var(--ink-500);">
                Tirage
              </p>
              <p class="font-mono text-sm" style="color: var(--ink);">
                {{ coin.mintage.toLocaleString('fr-FR') }} ex.
              </p>
            </div>
          </div>
        </div>

        <!-- Design description -->
        <div v-if="coin.design_description" class="mt-6">
          <p class="mb-2 text-[10px] uppercase tracking-wider" style="color: var(--ink-500);">
            Description du design
          </p>
          <p class="text-sm leading-relaxed" style="color: var(--ink);">
            {{ coin.design_description }}
          </p>
        </div>

        <!-- Cross references -->
        <div v-if="crossRefLinks.length > 0" class="mt-6">
          <p class="mb-2 text-[10px] uppercase tracking-wider" style="color: var(--ink-500);">
            Références externes
          </p>
          <div class="flex flex-wrap gap-2">
            <a
              v-for="link in crossRefLinks"
              :key="link.url"
              :href="link.url"
              target="_blank"
              rel="noopener"
              class="inline-flex items-center gap-1.5 rounded-full border px-3 py-1 text-xs transition-colors hover:bg-surface-1"
              style="border-color: var(--surface-3); color: var(--ink-500);"
            >
              {{ link.label }}
              <ExternalLink class="h-3 w-3" />
            </a>
          </div>
        </div>

        <!-- Training status -->
        <div class="mt-6">
          <p class="mb-2 text-[10px] uppercase tracking-wider" style="color: var(--ink-500);">
            Reconnaissance ML
          </p>
          <div
            class="flex items-center justify-between rounded-lg border px-4 py-3"
            :style="{
              borderColor: trainedModelVersion ? 'var(--success)' : 'var(--surface-3)',
              background: trainedModelVersion
                ? 'color-mix(in srgb, var(--success) 6%, var(--surface))'
                : 'var(--surface)',
            }"
          >
            <div class="flex items-center gap-2.5">
              <Brain
                class="h-4 w-4"
                :style="{ color: trainedModelVersion ? 'var(--success)' : 'var(--ink-400)' }"
              />
              <div>
                <p class="text-sm font-medium" :style="{ color: trainedModelVersion ? 'var(--success)' : 'var(--ink-500)' }">
                  {{ trainedModelVersion ? 'Design entraîné' : 'Non entraîné' }}
                </p>
                <p v-if="trainedModelVersion" class="font-mono text-[10px]" style="color: var(--ink-400);">
                  Modèle {{ trainedModelVersion }}
                </p>
              </div>
            </div>
            <div v-if="coin.cross_refs?.numista_id" class="flex items-center gap-2">
              <button
                v-if="!trainedModelVersion"
                class="flex items-center gap-1.5 rounded-md px-3 py-1.5 text-xs font-medium transition-all"
                :style="{
                  background: enqueueState === 'success' ? 'var(--success)' : 'var(--indigo-700)',
                  color: 'white',
                  opacity: enqueueState === 'loading' ? '0.7' : '1',
                }"
                :disabled="enqueueState !== 'idle'"
                @click="enqueueForTraining"
              >
                <Loader2 v-if="enqueueState === 'loading'" class="h-3 w-3 animate-spin" />
                <Check v-else-if="enqueueState === 'success'" class="h-3 w-3" />
                <Play v-else class="h-3 w-3" />
                {{ enqueueState === 'success' ? 'Ajouté !' : 'Entraîner' }}
              </button>
              <button
                class="flex items-center gap-1 rounded-md border px-3 py-1.5 text-xs font-medium transition-colors hover:border-current"
                style="border-color: var(--surface-3); color: var(--ink-500);"
                @click="router.push('/training')"
              >
                Voir training
                <ArrowUpRight class="h-3 w-3" />
              </button>
            </div>
          </div>
        </div>

        <!-- Identifiants (copyables) -->
        <div class="mt-8 space-y-2">
          <p class="text-[10px] uppercase tracking-wider" style="color: var(--ink-500);">
            Identifiants
          </p>
          <div
            class="flex items-center justify-between gap-2 rounded-md border px-3 py-2"
            style="border-color: var(--surface-3); background: var(--surface-1);"
          >
            <div class="min-w-0 flex-1">
              <p class="text-[10px] uppercase tracking-wider" style="color: var(--ink-500);">Eurio ID</p>
              <p class="truncate font-mono text-xs" style="color: var(--ink);" :title="coin.eurio_id">
                {{ coin.eurio_id }}
              </p>
            </div>
            <button
              class="flex shrink-0 items-center gap-1 rounded-md border px-2 py-1 text-xs font-medium transition-colors hover:border-current"
              style="border-color: var(--surface-3); color: var(--ink-500);"
              :title="`Copier ${coin.eurio_id}`"
              @click="copyToClipboard(coin.eurio_id, 'EurioID', $event)"
            >
              <Copy class="h-3 w-3" />
              Copier
            </button>
          </div>

          <div
            v-if="coin.cross_refs?.numista_id"
            class="flex items-center justify-between gap-2 rounded-md border px-3 py-2"
            style="border-color: var(--surface-3); background: var(--surface-1);"
          >
            <div class="min-w-0 flex-1">
              <p class="text-[10px] uppercase tracking-wider" style="color: var(--ink-500);">Numista ID</p>
              <p class="font-mono text-xs" style="color: var(--ink);">
                N{{ coin.cross_refs.numista_id }}
              </p>
            </div>
            <button
              class="flex shrink-0 items-center gap-1 rounded-md border px-2 py-1 text-xs font-medium transition-colors hover:border-current"
              style="border-color: var(--surface-3); color: var(--ink-500);"
              :title="`Copier ${coin.cross_refs.numista_id}`"
              @click="copyToClipboard(String(coin.cross_refs.numista_id), 'NumistaID', $event)"
            >
              <Copy class="h-3 w-3" />
              Copier
            </button>
          </div>

          <div
            v-if="coin.design_group_id"
            class="flex items-center justify-between gap-2 rounded-md border px-3 py-2"
            style="border-color: var(--surface-3); background: var(--surface-1);"
          >
            <div class="min-w-0 flex-1">
              <p class="text-[10px] uppercase tracking-wider" style="color: var(--ink-500);">Design Group</p>
              <p class="truncate font-mono text-xs" style="color: var(--ink);" :title="coin.design_group_id">
                {{ coin.design_group_id }}
              </p>
            </div>
            <button
              class="flex shrink-0 items-center gap-1 rounded-md border px-2 py-1 text-xs font-medium transition-colors hover:border-current"
              style="border-color: var(--surface-3); color: var(--ink-500);"
              :title="`Copier ${coin.design_group_id}`"
              @click="copyToClipboard(coin.design_group_id!, 'DesignGroupID', $event)"
            >
              <Copy class="h-3 w-3" />
              Copier
            </button>
          </div>
        </div>
      </div>
    </div>

    <!-- Clipboard copy toast -->
    <Teleport to="body">
      <Transition name="copy-toast">
        <div
          v-if="copiedToast"
          class="fixed bottom-4 left-1/2 z-50 flex -translate-x-1/2 items-center gap-2 rounded-md border px-3 py-2 text-xs"
          style="background: var(--surface); border-color: var(--surface-3); box-shadow: var(--shadow-md); color: var(--ink)"
        >
          <Check class="h-3 w-3" style="color: var(--success)" />
          <span><strong>{{ copiedToast.label }}</strong> copié</span>
          <code
            class="truncate rounded px-1.5 py-0.5 font-mono text-[10px]"
            style="background: var(--surface-1); color: var(--ink-500); max-width: 320px;"
          >{{ copiedToast.value }}</code>
        </div>
      </Transition>
    </Teleport>

    <!-- ═══ Cartographie de confusion (Phase 1 ML scalability) — pleine largeur ═══ -->
    <div v-if="coin" class="mt-12">
      <div class="mb-5 flex items-end justify-between border-b pb-3"
           style="border-color: var(--surface-3);">
        <div>
          <p class="text-[10px] uppercase"
             style="color: var(--ink-500); letter-spacing: var(--tracking-eyebrow);">
            Cartographie de confusion
          </p>
          <h2 class="mt-0.5 font-display text-2xl italic font-semibold"
              style="color: var(--indigo-700);">
            Voisins visuels
          </h2>
        </div>
        <router-link
          to="/confusion"
          class="flex items-center gap-1 text-xs transition-opacity hover:opacity-70"
          style="color: var(--ink-500);"
        >
          Voir la carte complète
          <ArrowUpRight class="h-3 w-3" />
        </router-link>
      </div>

      <!-- Loading -->
      <div
        v-if="confusionLoading"
        class="h-64 animate-pulse rounded-lg"
        style="background: var(--surface-1);"
      />

      <!-- Unmapped -->
      <div
        v-else-if="!confusion"
        class="flex items-center gap-3 rounded-lg border px-5 py-4"
        style="border-color: var(--surface-3); background: var(--surface);"
      >
        <Network class="h-5 w-5" style="color: var(--ink-400);" />
        <div class="flex-1">
          <p class="text-sm font-medium" style="color: var(--ink);">Non cartographié</p>
          <p class="mt-0.5 text-xs" style="color: var(--ink-500);">
            Lance une cartographie depuis
            <router-link to="/confusion" class="underline" style="color: var(--indigo-700);">
              /confusion
            </router-link>
            pour évaluer la proximité visuelle de ce design.
          </p>
        </div>
      </div>

      <!-- Confusion content -->
      <template v-else>
        <!-- Zone banner (full-width) -->
        <div
          class="flex items-start gap-4 rounded-lg border p-5"
          :style="{
            borderColor: zoneStyle(confusion.zone).solid,
            background: zoneStyle(confusion.zone).soft,
          }"
        >
          <div
            class="flex h-11 w-11 flex-shrink-0 items-center justify-center rounded-full"
            :style="{ background: zoneStyle(confusion.zone).solid, color: 'white' }"
          >
            <span class="text-sm font-mono font-bold">{{ zoneStyle(confusion.zone).short }}</span>
          </div>
          <div class="flex-1">
            <div class="flex items-baseline gap-3">
              <p
                class="font-display text-xl italic font-semibold"
                :style="{ color: zoneStyle(confusion.zone).solid }"
              >
                {{ zoneStyle(confusion.zone).label }}
              </p>
              <span class="font-mono text-sm tabular-nums" :style="{ color: zoneStyle(confusion.zone).solid }">
                voisin @ {{ confusion.nearest_similarity.toFixed(3) }}
              </span>
            </div>
            <p class="mt-1.5 text-sm leading-snug" style="color: var(--ink);">
              {{ zoneCopy(confusion.zone, confusion.nearest_similarity) }}
            </p>
          </div>
        </div>

        <!-- Nearest neighbor — SIDE-BY-SIDE comparison (grand) -->
        <div v-if="confusionNearest" class="mt-6">
          <p class="mb-3 text-[10px] uppercase"
             style="color: var(--ink-500); letter-spacing: var(--tracking-eyebrow);">
            Voisin le plus proche
          </p>
          <div
            class="overflow-hidden rounded-lg border"
            style="border-color: var(--surface-3); background: var(--surface); box-shadow: var(--shadow-card);"
          >
            <!-- Image comparison -->
            <div class="grid grid-cols-1 md:grid-cols-2">
              <!-- Current coin (left) -->
              <div
                class="relative flex aspect-square items-center justify-center overflow-hidden"
                style="background: linear-gradient(160deg, var(--surface-1), var(--surface-2));"
              >
                <img
                  v-if="selectedImage?.url"
                  :src="selectedImage.url"
                  :alt="coin.theme ?? coin.eurio_id"
                  class="h-full w-full object-contain p-6"
                />
                <ImageOff v-else class="h-12 w-12" style="color: var(--ink-300);" />
                <span
                  class="absolute left-4 top-4 rounded-full px-3 py-1 text-[10px] font-mono font-medium uppercase"
                  style="background: rgba(14,14,31,0.85); color: white; letter-spacing: var(--tracking-eyebrow); backdrop-filter: blur(4px);"
                >
                  Cette pièce
                </span>
                <span
                  class="absolute bottom-4 left-4 rounded-full px-3 py-1 text-[10px] font-mono uppercase"
                  style="background: rgba(14,14,31,0.85); color: rgba(255,255,255,0.85); backdrop-filter: blur(4px);"
                >
                  {{ coin.country }} · {{ coin.year }}
                </span>
              </div>

              <!-- Nearest neighbor (right) -->
              <button
                class="group relative flex aspect-square items-center justify-center overflow-hidden transition-all hover:brightness-95 md:border-l"
                :style="{
                  background: 'linear-gradient(200deg, var(--surface-1), var(--surface-2))',
                  borderColor: 'var(--surface-3)',
                }"
                @click="goToConfusionCoin(confusionNearest.eurio_id)"
              >
                <img
                  v-if="confusionNearest.coin?.image_url"
                  :src="confusionNearest.coin.image_url"
                  :alt="confusionNearest.coin.theme ?? confusionNearest.eurio_id"
                  class="h-full w-full object-contain p-6 transition-transform duration-300 group-hover:scale-105"
                  loading="lazy"
                />
                <ImageOff v-else class="h-12 w-12" style="color: var(--ink-300);" />
                <span
                  class="absolute left-4 top-4 rounded-full px-3 py-1 text-[10px] font-mono font-medium uppercase"
                  :style="{
                    background: zoneStyle(confusion.zone).solid,
                    color: 'white',
                    letterSpacing: 'var(--tracking-eyebrow)',
                  }"
                >
                  Voisin
                </span>
                <span
                  v-if="confusionNearest.coin"
                  class="absolute bottom-4 left-4 rounded-full px-3 py-1 text-[10px] font-mono uppercase"
                  style="background: rgba(14,14,31,0.85); color: rgba(255,255,255,0.85); backdrop-filter: blur(4px);"
                >
                  {{ confusionNearest.coin.country }}{{ confusionNearest.coin.year ? ` · ${confusionNearest.coin.year}` : '' }}
                </span>
                <span
                  class="absolute right-4 top-4 flex items-center gap-1 rounded-full px-3 py-1 text-[10px] font-medium uppercase opacity-0 transition-opacity group-hover:opacity-100"
                  style="background: rgba(14,14,31,0.85); color: white; backdrop-filter: blur(4px); letter-spacing: var(--tracking-eyebrow);"
                >
                  Ouvrir
                  <ArrowUpRight class="h-3 w-3" />
                </span>
              </button>
            </div>

            <!-- Footer bar with meta + similarity -->
            <div
              class="flex items-center justify-between gap-4 border-t px-5 py-4"
              style="border-color: var(--surface-3); background: var(--surface-1);"
            >
              <button
                class="min-w-0 flex-1 text-left transition-opacity hover:opacity-80"
                @click="goToConfusionCoin(confusionNearest.eurio_id)"
              >
                <p class="truncate font-display italic text-lg font-semibold"
                   style="color: var(--ink);">
                  {{ confusionNearest.coin?.theme ?? confusionNearest.eurio_id }}
                </p>
                <p class="truncate font-mono text-[11px]" style="color: var(--ink-400);">
                  {{ confusionNearest.eurio_id }}
                </p>
              </button>
              <div class="flex flex-col items-end flex-shrink-0">
                <span
                  class="font-mono text-3xl font-semibold tabular-nums leading-none"
                  :style="{ color: zoneStyle(confusion.zone).solid }"
                >
                  {{ confusionNearest.similarity.toFixed(3) }}
                </span>
                <span
                  class="mt-1 font-mono text-[10px] uppercase"
                  style="color: var(--ink-400); letter-spacing: var(--tracking-eyebrow);"
                >
                  cosine similarity
                </span>
              </div>
            </div>
          </div>
        </div>

        <!-- Other neighbors — larger grid (4 columns on desktop) -->
        <div v-if="confusionOtherNeighbors.length > 0" class="mt-8">
          <p class="mb-3 text-[10px] uppercase"
             style="color: var(--ink-500); letter-spacing: var(--tracking-eyebrow);">
            Autres voisins proches
          </p>
          <div class="grid grid-cols-2 gap-4 md:grid-cols-4">
            <button
              v-for="n in confusionOtherNeighbors"
              :key="n.eurio_id"
              class="group flex flex-col overflow-hidden rounded-lg border text-left transition-all hover:-translate-y-0.5"
              style="border-color: var(--surface-3); background: var(--surface); box-shadow: var(--shadow-sm);"
              @click="goToConfusionCoin(n.eurio_id)"
            >
              <div
                class="relative flex aspect-square items-center justify-center overflow-hidden"
                style="background: linear-gradient(160deg, var(--surface-1), var(--surface-2));"
              >
                <img
                  v-if="n.coin?.image_url"
                  :src="n.coin.image_url"
                  :alt="n.coin.theme ?? n.eurio_id"
                  class="h-full w-full object-contain p-4 transition-transform duration-300 group-hover:scale-105"
                  loading="lazy"
                />
                <ImageOff v-else class="h-8 w-8" style="color: var(--ink-300);" />
                <span
                  class="absolute right-2 top-2 rounded-full px-2 py-0.5 font-mono text-xs font-semibold tabular-nums"
                  :style="{
                    background: 'rgba(14,14,31,0.85)',
                    color: 'white',
                    backdropFilter: 'blur(4px)',
                  }"
                >
                  {{ n.similarity.toFixed(3) }}
                </span>
              </div>
              <div class="flex flex-1 flex-col justify-between p-3">
                <p class="line-clamp-2 text-sm font-medium leading-snug" style="color: var(--ink);">
                  {{ n.coin?.theme ?? n.eurio_id }}
                </p>
                <div class="mt-2 flex items-center justify-between">
                  <span v-if="n.coin" class="font-mono text-[10px] uppercase" style="color: var(--ink-400);">
                    {{ n.coin.country }}{{ n.coin.year ? ` · ${n.coin.year}` : '' }}
                  </span>
                  <span
                    class="h-1.5 w-1.5 rounded-full"
                    :style="{ background: n.similarity >= 0.85 ? 'var(--danger)' : n.similarity >= 0.70 ? 'var(--warning)' : 'var(--success)' }"
                  />
                </div>
              </div>
            </button>
          </div>
        </div>
      </template>
    </div>
  </div>
</template>

<style scoped>
.copy-toast-enter-active,
.copy-toast-leave-active {
  transition: transform 0.18s ease, opacity 0.18s ease;
}
.copy-toast-enter-from,
.copy-toast-leave-to {
  transform: translate(-50%, 16px);
  opacity: 0;
}
</style>
