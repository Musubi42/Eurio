<script setup lang="ts">
import {
  useBuildInfoQuery,
  usePurgeTestBundleMutation,
} from '@/features/lab/composables/useLabQueries'
import type { IterationStatus } from '@/features/lab/types'
import { Check, Copy, Loader2, Trash2 } from 'lucide-vue-next'
import { computed, ref } from 'vue'

const props = defineProps<{
  cohortId: string
  iterationId: string
  status: IterationStatus
}>()

const cohortId = computed(() => props.cohortId)
const iterationId = computed(() => props.iterationId)
const status = computed(() => props.status)

const buildInfoQuery = useBuildInfoQuery(cohortId, iterationId, {
  iterationStatus: status,
})

const data = computed(() => buildInfoQuery.data.value ?? null)
const loading = computed(() => buildInfoQuery.isLoading.value)
const purge = usePurgeTestBundleMutation(cohortId, iterationId)
const purgeMessage = ref<string | null>(null)

async function handlePurge() {
  if (!confirm('Supprimer le bundle TFLite + manifests sur disque ?')) return
  try {
    const res = await purge.mutateAsync()
    purgeMessage.value = res.removed ? 'Bundle supprimé.' : 'Aucun bundle à supprimer.'
    setTimeout(() => { purgeMessage.value = null }, 2500)
  } catch (e) {
    alert(`Purge échouée : ${(e as Error).message}`)
  }
}

const copied = ref(false)
async function copyCommand() {
  const cmd = data.value?.command
  if (!cmd) return
  try {
    await navigator.clipboard.writeText(cmd)
    copied.value = true
    setTimeout(() => { copied.value = false }, 1500)
  } catch (e) {
    alert(`Copie impossible : ${(e as Error).message}`)
  }
}
</script>

<template>
  <div>
    <div class="mb-3 flex items-center justify-between">
      <div>
        <p
          class="text-[10px] font-medium uppercase"
          style="color: var(--ink-400); letter-spacing: var(--tracking-eyebrow);"
        >
          Test app
        </p>
        <p class="text-sm" style="color: var(--ink-300);">
          APK dédiée pour cette cohort + itération
        </p>
      </div>
      <div class="flex items-center gap-2">
        <span v-if="purgeMessage" class="text-[11px]" style="color: var(--ink-500);">
          {{ purgeMessage }}
        </span>
        <button
          v-if="data && data.model_ready"
          class="flex items-center gap-1.5 rounded-md border px-3 py-1.5 text-xs transition-colors hover:bg-[var(--surface-2)]"
          style="border-color: var(--surface-3); color: var(--ink-500);"
          :disabled="purge.isPending.value"
          title="Supprime ml/output/cohort_test_<iid>/ (regen possible via cohort-test:bundle)"
          @click="handlePurge"
        >
          <Loader2 v-if="purge.isPending.value" class="h-3 w-3 animate-spin" />
          <Trash2 v-else class="h-3 w-3" />
          Purger bundle
        </button>
      </div>
    </div>

    <div
      v-if="loading"
      class="flex items-center gap-2 rounded-lg border p-4 text-sm"
      style="border-color: var(--surface-3); color: var(--ink-400);"
    >
      <Loader2 class="h-4 w-4 animate-spin" />
      Chargement…
    </div>

    <div
      v-else-if="data && !data.model_ready"
      class="rounded-lg border p-4 text-sm"
      style="border-color: var(--surface-3); background: var(--surface);"
    >
      <p style="color: var(--ink-300);">
        {{ data.reason || 'Itération pas prête.' }}
      </p>
    </div>

    <div
      v-else-if="data && data.model_ready && data.command"
      class="rounded-lg border p-4"
      style="border-color: var(--surface-3); background: var(--surface);"
    >
      <p class="mb-2 text-xs" style="color: var(--ink-400);">
        Copie cette commande dans un terminal à la racine du repo :
      </p>
      <div class="relative">
        <pre
          class="overflow-x-auto rounded-md p-3 text-xs"
          style="background: var(--ink-900); color: var(--ink-100); font-family: ui-monospace, SFMono-Regular, Menlo, monospace;"
        >{{ data.command }}</pre>
        <button
          type="button"
          class="absolute right-2 top-2 inline-flex items-center gap-1 rounded-md border px-2 py-1 text-[11px]"
          style="border-color: var(--surface-3); background: var(--surface); color: var(--ink-200);"
          @click="copyCommand"
        >
          <Check v-if="copied" class="h-3.5 w-3.5" />
          <Copy v-else class="h-3.5 w-3.5" />
          {{ copied ? 'Copié' : 'Copier' }}
        </button>
      </div>
      <p class="mt-3 text-[11px]" style="color: var(--ink-500);">
        Bundle écrit dans <code>{{ data.bundle_path }}</code>. Cf.
        <code>docs/training-pipeline/sprint-3-cohort-test-app.md</code>.
      </p>
    </div>

    <div
      v-else
      class="rounded-lg border p-4 text-sm"
      style="border-color: var(--surface-3); color: var(--ink-400);"
    >
      Pas de données.
    </div>
  </div>
</template>
