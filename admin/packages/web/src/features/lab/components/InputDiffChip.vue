<script setup lang="ts">
defineProps<{
  diff: Record<string, { before: unknown; after: unknown }>
}>()

function formatValue(v: unknown): string {
  if (v == null) return '—'
  if (typeof v === 'number') return v.toString()
  if (typeof v === 'boolean') return v ? 'on' : 'off'
  if (Array.isArray(v)) return `[${v.map(x => formatValue(x)).join(', ')}]`
  if (typeof v === 'object') return JSON.stringify(v)
  return String(v)
}

function shortPath(p: string): string {
  // recipe.perspective.max_tilt_degrees → perspective.max_tilt_degrees
  return p.replace(/^recipe\./, '').replace(/^training_config\./, '')
}
</script>

<template>
  <div class="flex flex-wrap gap-1">
    <span
      v-for="(change, path) in diff"
      :key="path"
      class="inline-flex items-center gap-1 rounded-md border px-1.5 py-0.5 font-mono text-[10px]"
      style="
        border-color: var(--surface-3);
        background: color-mix(in srgb, var(--indigo-700) 4%, var(--surface));
        color: var(--ink);
      "
      :title="path"
    >
      <span style="color: var(--ink-500);">{{ shortPath(path) }}</span>
      <span style="color: var(--ink-400);">·</span>
      <span style="color: var(--ink-400); text-decoration: line-through;">
        {{ formatValue(change.before) }}
      </span>
      <span style="color: var(--indigo-700);">→</span>
      <span style="color: var(--indigo-700);">
        {{ formatValue(change.after) }}
      </span>
    </span>
    <span v-if="Object.keys(diff).length === 0" class="text-[10px]" style="color: var(--ink-400);">
      identique au parent
    </span>
  </div>
</template>
