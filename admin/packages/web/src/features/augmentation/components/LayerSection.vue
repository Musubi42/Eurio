<script setup lang="ts">
import { ChevronDown, ChevronRight } from 'lucide-vue-next'
import { ref } from 'vue'
import type { Layer, LayerSchema } from '../types'
import ParamControl from './ParamControl.vue'

const props = defineProps<{
  schema: LayerSchema
  layer: Layer
  layerIndex: number
  isParamDirty: (paramName: string) => boolean
}>()

const emit = defineEmits<{
  (event: 'update', paramName: string, value: unknown): void
}>()

const open = ref(true)

// `probability` is conceptually always present even if absent from layer
// (default 1.0); resolve here for display + control.
function valueOf(name: string): unknown {
  const v = props.layer[name]
  if (v !== undefined) return v
  const def = props.schema.params.find(p => p.name === name)?.default
  return def
}

const probability = () => {
  const p = valueOf('probability')
  return typeof p === 'number' ? p : 1
}
</script>

<template>
  <section
    class="rounded-md border"
    style="border-color: var(--surface-3); background: var(--surface);"
  >
    <button
      type="button"
      class="flex w-full items-center justify-between gap-2 px-3 py-2 text-left"
      @click="open = !open"
    >
      <div class="flex items-center gap-2 min-w-0">
        <ChevronDown v-if="open" class="h-3.5 w-3.5 flex-shrink-0" style="color: var(--ink-400);" />
        <ChevronRight v-else class="h-3.5 w-3.5 flex-shrink-0" style="color: var(--ink-400);" />
        <span
          class="font-display text-sm italic truncate"
          style="color: var(--ink);"
        >{{ schema.label }}</span>
      </div>
      <span
        class="font-mono text-[10px] tabular-nums"
        style="color: var(--ink-500);"
      >p={{ probability().toFixed(2) }}</span>
    </button>

    <div v-show="open" class="flex flex-col gap-3 border-t px-3 py-3" style="border-color: var(--surface-3);">
      <ParamControl
        v-for="param in schema.params"
        :key="param.name"
        :schema="param"
        :value="valueOf(param.name)"
        :dirty="isParamDirty(param.name)"
        @update="(v) => emit('update', param.name, v)"
      />
    </div>
  </section>
</template>
