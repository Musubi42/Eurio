<script setup lang="ts">
// Reusable drawer wrapper used by Cohort/Iteration tiroirs.
// Header summarises the state at a glance ; body collapses.

import type { DrawerState } from '@/features/lab/types'
import { ChevronDown, ChevronRight, Lock } from 'lucide-vue-next'
import { computed, nextTick, onMounted, onUnmounted, ref, watch } from 'vue'
import { useRoute } from 'vue-router'

const props = withDefaults(
  defineProps<{
    number: string
    title: string
    state: DrawerState
    summary: string
    defaultOpen?: boolean
    locked?: boolean
    lockReason?: string
  }>(),
  {
    defaultOpen: undefined,
    locked: false,
    lockReason: '',
  },
)

// ── Lien profond : `?tiroir=c3` ouvre le tiroir §C3 et le fait défiler à vue.
// Posé ICI plutôt que dans chaque page : tous les tiroirs (cohorte, itération)
// en héritent d'un coup, sans prop à faire descendre.
// ⚠ La clé est le NUMÉRO du tiroir : il doit rester unique par page. La page
// cohorte va de C1 à C6 sans collision depuis que le Jeu d'entraînement est
// passé de C5 à C6 — deux tiroirs au même numéro s'ouvriraient ensemble.
const route = useRoute()
const anchor = computed(() => `tiroir-${props.number.toLowerCase()}`)
const targeted = computed(
  () => String(route.query.tiroir ?? '').toLowerCase() === props.number.toLowerCase(),
)

const userToggled = ref(false)
const open = ref(false)
const root = ref<HTMLElement | null>(null)

// Le corps des tiroirs se remplit APRÈS leurs requêtes — le funnel eBay met
// ~3,6 s — et la page grandit d'autant au-dessus de la cible. Un seul scroll
// viserait une position déjà périmée. On repasse donc plusieurs fois pendant
// que la mise en page se stabilise, et on ARRÊTE dès que l'utilisateur touche
// la molette ou le clavier : jamais reprendre la main à quelqu'un qui l'a prise.
const RETRIES_MS = [0, 400, 1200, 2600, 4200]
let timers: ReturnType<typeof setTimeout>[] = []

function cancelReveal() {
  timers.forEach(clearTimeout)
  timers = []
  window.removeEventListener('wheel', cancelReveal)
  window.removeEventListener('touchmove', cancelReveal)
  window.removeEventListener('keydown', cancelReveal)
}

async function revealIfTargeted() {
  cancelReveal()
  if (!targeted.value) return
  userToggled.value = false   // la cible reprend la main sur l'état auto
  open.value = true
  await nextTick()
  window.addEventListener('wheel', cancelReveal, { passive: true })
  window.addEventListener('touchmove', cancelReveal, { passive: true })
  window.addEventListener('keydown', cancelReveal)
  // Saut DIRECT, pas « smooth » : un défilement animé sur une longue distance
  // se fait interrompre par chaque recalcul de mise en page au-dessus de la
  // cible, et n'arrive jamais au bout (constaté le 2026-08-18).
  timers = RETRIES_MS.map(ms =>
    setTimeout(() => root.value?.scrollIntoView({ behavior: 'auto', block: 'start' }), ms),
  )
}
watch(targeted, revealIfTargeted)
onMounted(revealIfTargeted)
onUnmounted(cancelReveal)

function autoOpen(state: DrawerState, defaultOpen: boolean | undefined) {
  if (defaultOpen !== undefined) return defaultOpen
  return state === 'empty' || state === 'partial' || state === 'running'
}

watch(
  () => [props.state, props.defaultOpen] as const,
  ([s, d]) => {
    if (userToggled.value || targeted.value) return
    open.value = autoOpen(s, d)
  },
  { immediate: true },
)

function toggle() {
  if (props.locked) {
    if (props.lockReason) alert(props.lockReason)
    return
  }
  userToggled.value = true
  open.value = !open.value
}

const stateColor = computed(() => {
  switch (props.state) {
    case 'ready':
      return 'var(--success)'
    case 'partial':
      return 'var(--warning)'
    case 'running':
      return 'var(--indigo-700)'
    default:
      return 'var(--ink-400)'
  }
})

const stateLabel = computed(() => {
  switch (props.state) {
    case 'ready':
      return 'Ready'
    case 'partial':
      return 'Partial'
    case 'running':
      return 'Running'
    default:
      return 'Empty'
  }
})
</script>

<template>
  <section
    :id="anchor"
    ref="root"
    class="overflow-hidden rounded-lg border scroll-mt-4"
    :style="{
      borderColor: targeted ? 'var(--gold)' : 'var(--surface-3)',
      background: 'var(--surface)',
      opacity: locked ? 0.65 : 1,
    }"
  >
    <button
      type="button"
      class="flex w-full items-center gap-3 px-4 py-3 text-left transition-colors"
      :style="{
        background: 'var(--surface-1)',
        cursor: locked ? 'not-allowed' : 'pointer',
      }"
      :title="locked ? lockReason : ''"
      @click="toggle"
    >
      <span
        class="rounded-full px-2 py-0.5 text-[10px] font-medium uppercase"
        :style="{
          background: `color-mix(in srgb, ${stateColor} 14%, var(--surface))`,
          color: stateColor,
          letterSpacing: 'var(--tracking-eyebrow)',
        }"
      >
        {{ stateLabel }}
      </span>
      <span
        class="font-mono text-[11px]"
        style="color: var(--ink-400);"
      >§{{ number }}</span>
      <span class="font-medium text-sm" style="color: var(--ink);">{{ title }}</span>
      <span
        class="truncate text-xs"
        style="color: var(--ink-500);"
      >· {{ summary }}</span>
      <span class="ml-auto flex items-center gap-1" style="color: var(--ink-400);">
        <Lock v-if="locked" class="h-3.5 w-3.5" />
        <ChevronDown v-else-if="open" class="h-4 w-4" />
        <ChevronRight v-else class="h-4 w-4" />
      </span>
    </button>
    <div
      v-show="open && !locked"
      class="border-t px-4 py-4"
      :style="{ borderColor: 'var(--surface-3)' }"
    >
      <slot name="body" />
    </div>
  </section>
</template>
