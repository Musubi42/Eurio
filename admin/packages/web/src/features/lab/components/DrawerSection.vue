<script setup lang="ts">
// Reusable drawer wrapper used by Cohort/Iteration tiroirs.
// Header summarises the state at a glance ; body collapses.

import type { DrawerState } from '@/features/lab/types'
import { ChevronDown, ChevronRight, Lock } from 'lucide-vue-next'
import { computed, ref, watch } from 'vue'

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

const userToggled = ref(false)
const open = ref(false)

function autoOpen(state: DrawerState, defaultOpen: boolean | undefined) {
  if (defaultOpen !== undefined) return defaultOpen
  return state === 'empty' || state === 'partial' || state === 'running'
}

watch(
  () => [props.state, props.defaultOpen] as const,
  ([s, d]) => {
    if (!userToggled.value) open.value = autoOpen(s, d)
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
    class="overflow-hidden rounded-lg border"
    :style="{
      borderColor: 'var(--surface-3)',
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
