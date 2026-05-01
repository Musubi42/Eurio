<script setup lang="ts">
// Affiche le runtime (cpu/mps/cuda) détecté côté serveur ML.
// `compact` : pour bandeau global. Sinon : carte détaillée pour I3.

import { useRuntimeInfoQuery } from '@/features/lab/composables/useLabQueries'
import { Cpu, Loader2, Zap } from 'lucide-vue-next'
import { computed } from 'vue'

withDefaults(defineProps<{ compact?: boolean }>(), { compact: false })

const query = useRuntimeInfoQuery()
const info = computed(() => query.data.value ?? null)

const tint = computed(() => {
  const b = info.value?.backend
  if (b === 'cuda') return 'var(--success)'
  if (b === 'mps') return 'var(--warning)'
  return 'var(--danger)'
})
</script>

<template>
  <div v-if="query.isLoading.value && !info" class="flex items-center gap-2 text-xs" style="color: var(--ink-400);">
    <Loader2 class="h-3 w-3 animate-spin" />
    Détection runtime…
  </div>

  <!-- Compact -->
  <div
    v-else-if="compact && info"
    class="inline-flex items-center gap-2 rounded-full border px-3 py-1.5 text-xs"
    :style="{
      borderColor: tint,
      background: `color-mix(in srgb, ${tint} 8%, var(--surface))`,
      color: 'var(--ink);',
    }"
    :title="info.hint"
  >
    <Zap v-if="info.backend === 'cuda'" class="h-3.5 w-3.5" :style="{ color: tint }" />
    <Cpu v-else class="h-3.5 w-3.5" :style="{ color: tint }" />
    <span class="font-mono">{{ info.device }}</span>
    <span class="truncate">· {{ info.hint }}</span>
  </div>

  <!-- Full card -->
  <div
    v-else-if="info"
    class="rounded-lg border p-4"
    :style="{
      borderColor: tint,
      background: `color-mix(in srgb, ${tint} 4%, var(--surface))`,
    }"
  >
    <div class="mb-3 flex items-center gap-2">
      <Zap v-if="info.backend === 'cuda'" class="h-4 w-4" :style="{ color: tint }" />
      <Cpu v-else class="h-4 w-4" :style="{ color: tint }" />
      <p class="text-[10px] font-medium uppercase" style="color: var(--ink-500); letter-spacing: var(--tracking-eyebrow);">
        Runtime de cette machine
      </p>
    </div>
    <dl class="grid grid-cols-2 gap-2 text-xs">
      <div>
        <dt style="color: var(--ink-500);">Hôte</dt>
        <dd class="font-mono" style="color: var(--ink);">{{ info.host_os }} {{ info.arch }}</dd>
      </div>
      <div>
        <dt style="color: var(--ink-500);">CPU</dt>
        <dd class="font-mono" style="color: var(--ink);">{{ info.cpu_brand }}</dd>
      </div>
      <div>
        <dt style="color: var(--ink-500);">Torch</dt>
        <dd class="font-mono" style="color: var(--ink);">{{ info.torch_version }}</dd>
      </div>
      <div>
        <dt style="color: var(--ink-500);">Backend</dt>
        <dd class="font-mono" :style="{ color: tint }">{{ info.backend }}</dd>
      </div>
      <div>
        <dt style="color: var(--ink-500);">Device</dt>
        <dd class="font-mono" style="color: var(--ink);">{{ info.device }}</dd>
      </div>
      <div v-if="info.gpu_name">
        <dt style="color: var(--ink-500);">GPU</dt>
        <dd class="font-mono" style="color: var(--ink);">{{ info.gpu_name }}</dd>
      </div>
      <div v-if="info.cuda_version">
        <dt style="color: var(--ink-500);">CUDA</dt>
        <dd class="font-mono" style="color: var(--ink);">{{ info.cuda_version }}</dd>
      </div>
      <div>
        <dt style="color: var(--ink-500);">Workers</dt>
        <dd class="font-mono" style="color: var(--ink);">{{ info.dataloader_workers }}</dd>
      </div>
    </dl>
    <p class="mt-3 text-xs italic" :style="{ color: tint }">→ {{ info.hint }}</p>
  </div>
</template>
