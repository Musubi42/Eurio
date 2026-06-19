<script setup lang="ts">
import { computed } from 'vue'
import type { ParamSchema } from '../types'

const props = defineProps<{
  schema: ParamSchema
  value: unknown
  dirty?: boolean
}>()

const emit = defineEmits<{
  (event: 'update', value: unknown): void
}>()

const isRange = computed(() => props.schema.type === 'list[float]' && props.schema.length === 2)
const isMulti = computed(() => props.schema.type === 'list[string]' && !!props.schema.options)

const numberValue = computed<number>(() => {
  const v = props.value
  if (typeof v === 'number') return v
  const n = Number(v)
  return Number.isFinite(n) ? n : (props.schema.default as number)
})

const rangeValues = computed<[number, number]>(() => {
  const v = props.value
  if (Array.isArray(v) && v.length >= 2) {
    return [Number(v[0]) || 0, Number(v[1]) || 0]
  }
  const def = props.schema.default as [number, number]
  return [def[0], def[1]]
})

const multiValues = computed<string[]>(() => {
  if (Array.isArray(props.value)) return (props.value as unknown[]).map(String)
  return (props.schema.default as string[]) ?? []
})

const step = computed(() => props.schema.step ?? 0.01)
const min = computed(() => props.schema.min ?? 0)
const max = computed(() => props.schema.max ?? 1)

function emitNumber(n: number) {
  if (props.schema.type === 'int') {
    emit('update', Math.round(n))
  } else {
    emit('update', n)
  }
}

function emitRange(idx: 0 | 1, n: number) {
  const next = [...rangeValues.value] as [number, number]
  next[idx] = n
  // Enforce ordering min <= max.
  if (next[0] > next[1]) {
    if (idx === 0) next[1] = next[0]
    else next[0] = next[1]
  }
  emit('update', next)
}

function toggleMulti(opt: string) {
  const set = new Set(multiValues.value)
  if (set.has(opt)) set.delete(opt)
  else set.add(opt)
  // Preserve schema-defined option order for stable output.
  const opts = props.schema.options ?? []
  emit('update', opts.filter(o => set.has(o)))
}
</script>

<template>
  <div class="flex flex-col gap-1.5">
    <div class="flex items-baseline justify-between gap-2">
      <label
        class="text-xs font-medium"
        style="color: var(--ink);"
        :title="schema.description"
      >
        {{ schema.name }}
        <span
          v-if="dirty"
          class="ml-1 rounded px-1 text-[9px] font-mono uppercase tracking-wider"
          style="background: var(--indigo-700); color: white;"
        >modifié</span>
      </label>
      <span
        v-if="schema.type === 'float' || schema.type === 'int'"
        class="font-mono text-[10px] tabular-nums"
        style="color: var(--ink-500);"
      >{{ typeof numberValue === 'number' ? numberValue.toFixed(schema.type === 'int' ? 0 : 2) : '—' }}</span>
    </div>

    <!-- float / int scalar → slider + input -->
    <div
      v-if="schema.type === 'float' || schema.type === 'int'"
      class="flex items-center gap-2"
    >
      <input
        type="range"
        :min="min"
        :max="max"
        :step="step"
        :value="numberValue"
        class="flex-1 accent-indigo-700"
        @input="(e) => emitNumber(Number((e.target as HTMLInputElement).value))"
      />
      <input
        type="number"
        :min="min"
        :max="max"
        :step="step"
        :value="numberValue"
        class="w-16 rounded border px-1.5 py-0.5 text-right font-mono text-[11px] tabular-nums"
        style="background: var(--surface-1); border-color: var(--surface-3); color: var(--ink);"
        @input="(e) => emitNumber(Number((e.target as HTMLInputElement).value))"
      />
    </div>

    <!-- range list[float] length=2 → dual slider -->
    <div v-else-if="isRange" class="flex flex-col gap-1">
      <div class="flex items-center gap-2">
        <input
          type="range"
          :min="min"
          :max="max"
          :step="step"
          :value="rangeValues[0]"
          class="flex-1 accent-indigo-700"
          @input="(e) => emitRange(0, Number((e.target as HTMLInputElement).value))"
        />
        <input
          type="number"
          :min="min"
          :max="max"
          :step="step"
          :value="rangeValues[0]"
          class="w-14 rounded border px-1.5 py-0.5 text-right font-mono text-[11px] tabular-nums"
          style="background: var(--surface-1); border-color: var(--surface-3); color: var(--ink);"
          @input="(e) => emitRange(0, Number((e.target as HTMLInputElement).value))"
        />
      </div>
      <div class="flex items-center gap-2">
        <input
          type="range"
          :min="min"
          :max="max"
          :step="step"
          :value="rangeValues[1]"
          class="flex-1 accent-indigo-700"
          @input="(e) => emitRange(1, Number((e.target as HTMLInputElement).value))"
        />
        <input
          type="number"
          :min="min"
          :max="max"
          :step="step"
          :value="rangeValues[1]"
          class="w-14 rounded border px-1.5 py-0.5 text-right font-mono text-[11px] tabular-nums"
          style="background: var(--surface-1); border-color: var(--surface-3); color: var(--ink);"
          @input="(e) => emitRange(1, Number((e.target as HTMLInputElement).value))"
        />
      </div>
    </div>

    <!-- bool → toggle -->
    <button
      v-else-if="schema.type === 'bool'"
      type="button"
      class="h-6 w-10 rounded-full transition-colors"
      :style="{
        background: value ? 'var(--indigo-700)' : 'var(--surface-3)',
      }"
      @click="emit('update', !value)"
    >
      <span
        class="block h-5 w-5 rounded-full transition-transform"
        :style="{
          background: 'white',
          transform: value ? 'translateX(18px)' : 'translateX(2px)',
        }"
      />
    </button>

    <!-- string + options → select -->
    <select
      v-else-if="schema.type === 'string' && schema.options"
      class="rounded border px-2 py-1 text-xs"
      style="background: var(--surface-1); border-color: var(--surface-3); color: var(--ink);"
      :value="value as string"
      @change="(e) => emit('update', (e.target as HTMLSelectElement).value)"
    >
      <option v-for="opt in schema.options" :key="opt" :value="opt">{{ opt }}</option>
    </select>

    <!-- list[string] options → multi checkbox -->
    <div v-else-if="isMulti" class="flex flex-wrap gap-1.5">
      <button
        v-for="opt in schema.options"
        :key="opt"
        type="button"
        class="rounded border px-2 py-0.5 text-[11px] transition-colors"
        :style="{
          background: multiValues.includes(opt) ? 'var(--indigo-700)' : 'var(--surface-1)',
          borderColor: multiValues.includes(opt) ? 'var(--indigo-700)' : 'var(--surface-3)',
          color: multiValues.includes(opt) ? 'white' : 'var(--ink)',
        }"
        @click="toggleMulti(opt)"
      >
        {{ opt }}
      </button>
    </div>

    <p
      v-if="schema.description"
      class="text-[10px] leading-snug"
      style="color: var(--ink-400);"
    >{{ schema.description }}</p>
  </div>
</template>
