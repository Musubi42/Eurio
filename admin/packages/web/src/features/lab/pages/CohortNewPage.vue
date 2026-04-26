<script setup lang="ts">
import { createCohort } from '@/features/lab/composables/useLabApi'
import { fetchLibrary } from '@/features/benchmark/composables/useBenchmarkApi'
import type { BenchmarkLibrary } from '@/features/benchmark/types'
import { ArrowLeft, Check, Loader2, Plus, X } from 'lucide-vue-next'
import { computed, onMounted, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'

const router = useRouter()
const route = useRoute()

const name = ref<string>('')
const description = ref<string>('')
const zone = ref<'' | 'green' | 'orange' | 'red'>('')
const rawIds = ref<string>('')

const library = ref<BenchmarkLibrary | null>(null)

const submitting = ref(false)
const error = ref<string | null>(null)

onMounted(async () => {
  // Prefill from ?eurio_ids= (handoff from /coins)
  const prefill = route.query.eurio_ids
  if (typeof prefill === 'string' && prefill.length > 0) {
    rawIds.value = prefill.split(',').join('\n')
  }
  try {
    library.value = await fetchLibrary()
  } catch {
    library.value = null
  }
})

const parsedIds = computed<string[]>(() => {
  const tokens = rawIds.value
    .split(/[\n,]+/)
    .map(s => s.trim())
    .filter(Boolean)
  return Array.from(new Set(tokens))
})

const photoReady = computed<Record<string, boolean>>(() => {
  const map: Record<string, boolean> = {}
  if (!library.value) return map
  for (const c of library.value.coins) {
    map[c.eurio_id] = c.num_photos > 0
  }
  return map
})

const readiness = computed(() => {
  const ready: string[] = []
  const pending: string[] = []
  for (const id of parsedIds.value) {
    if (photoReady.value[id]) ready.push(id)
    else pending.push(id)
  }
  return { ready, pending }
})

const nameValid = computed(() => /^[a-z0-9][a-z0-9-]*[a-z0-9]$/.test(name.value))
const canSubmit = computed(() => nameValid.value && parsedIds.value.length > 0 && !submitting.value)

async function submit() {
  if (!canSubmit.value) return
  submitting.value = true
  error.value = null
  try {
    const created = await createCohort({
      name: name.value,
      description: description.value || undefined,
      zone: zone.value || null,
      eurio_ids: parsedIds.value,
    })
    router.push(`/lab/cohorts/${created.id}`)
  } catch (e) {
    error.value = (e as Error).message
  } finally {
    submitting.value = false
  }
}
</script>

<template>
  <div class="p-8 max-w-3xl">
    <button
      class="mb-4 flex items-center gap-1 text-sm"
      style="color: var(--ink-500);"
      @click="router.push('/lab')"
    >
      <ArrowLeft class="h-3.5 w-3.5" />
      Retour au Lab
    </button>

    <header class="mb-8">
      <p
        class="mb-1 text-[10px] font-medium uppercase"
        style="color: var(--ink-400); letter-spacing: var(--tracking-eyebrow);"
      >
        Nouveau cohort
      </p>
      <h1
        class="font-display text-3xl italic font-semibold leading-tight"
        style="color: var(--indigo-700);"
      >
        Fige un ensemble de pièces pour itérer dessus
      </h1>
      <p class="mt-1.5 text-sm" style="color: var(--ink-500);">
        Les eurio_ids sont frozen dès création — pour en ajouter/retirer tu devras forker.
      </p>
      <div class="mt-6 h-px w-16" style="background: var(--gold);" />
    </header>

    <form class="space-y-6" @submit.prevent="submit">
      <div>
        <label class="block">
          <span class="mb-1 block text-[10px] font-medium uppercase" style="color: var(--ink-500);">
            Nom (kebab-case)
          </span>
          <input
            v-model="name"
            type="text"
            placeholder="green-v1"
            class="w-full rounded-md border px-3 py-2 text-sm font-mono"
            :style="{
              borderColor: name && !nameValid ? 'var(--danger)' : 'var(--surface-3)',
            }"
          />
        </label>
        <p
          v-if="name && !nameValid"
          class="mt-1 text-[10px]"
          style="color: var(--danger);"
        >
          Format invalide — lowercase, chiffres, tirets.
        </p>
      </div>

      <div>
        <label class="block">
          <span class="mb-1 block text-[10px] font-medium uppercase" style="color: var(--ink-500);">
            Description (optionnel)
          </span>
          <textarea
            v-model="description"
            rows="2"
            placeholder="5 coins verts pour calibrer la recette green"
            class="w-full rounded-md border px-3 py-2 text-sm"
            style="border-color: var(--surface-3);"
          />
        </label>
      </div>

      <div>
        <p class="mb-2 text-[10px] font-medium uppercase" style="color: var(--ink-500);">
          Zone (optionnel)
        </p>
        <div class="flex gap-2">
          <button
            v-for="z in ['', 'green', 'orange', 'red']"
            :key="z"
            type="button"
            class="rounded-full px-3 py-1 text-xs font-medium transition-all"
            :style="{
              background: zone === z
                ? (z ? `color-mix(in srgb, var(--${z === 'green' ? 'success' : z === 'orange' ? 'warning' : z === 'red' ? 'danger' : 'indigo-700'}) 20%, var(--surface))` : 'color-mix(in srgb, var(--indigo-700) 10%, var(--surface))')
                : 'var(--surface-1)',
              color: zone === z
                ? (z === 'green' ? 'var(--success)' : z === 'orange' ? 'var(--warning)' : z === 'red' ? 'var(--danger)' : 'var(--indigo-700)')
                : 'var(--ink-500)',
              border: `1px solid ${zone === z ? 'currentColor' : 'var(--surface-3)'}`,
            }"
            @click="zone = z as any"
          >
            {{ z || 'aucune' }}
          </button>
        </div>
      </div>

      <div>
        <label class="block">
          <span class="mb-1 block text-[10px] font-medium uppercase" style="color: var(--ink-500);">
            eurio_ids (un par ligne ou séparés par virgule)
          </span>
          <textarea
            v-model="rawIds"
            rows="5"
            placeholder="fr-2007-2eur-standard&#10;de-2005-2eur-standard&#10;…"
            class="w-full rounded-md border px-3 py-2 text-xs font-mono"
            style="border-color: var(--surface-3);"
          />
        </label>
        <p class="mt-1 text-[10px]" style="color: var(--ink-400);">
          {{ parsedIds.length }} pièce(s) reconnue(s). Les doublons sont dédupliqués automatiquement.
        </p>
      </div>

      <!-- Photo-readiness panel -->
      <div
        v-if="parsedIds.length > 0"
        class="rounded-lg border p-4"
        style="border-color: var(--surface-3); background: var(--surface);"
      >
        <p class="mb-2 text-[10px] font-medium uppercase" style="color: var(--ink-500);">
          Couverture photos réelles
        </p>
        <div v-if="!library" class="text-xs" style="color: var(--ink-400);">
          Bibliothèque indisponible (lance <code class="font-mono">go-task ml:benchmark:photos:check</code>)
        </div>
        <div v-else class="grid grid-cols-2 gap-2 text-xs">
          <div
            v-for="id in parsedIds"
            :key="id"
            class="flex items-center gap-1.5"
            :style="{ color: photoReady[id] ? 'var(--success)' : 'var(--warning)' }"
          >
            <Check v-if="photoReady[id]" class="h-3 w-3" />
            <X v-else class="h-3 w-3" />
            <span class="font-mono">{{ id }}</span>
          </div>
        </div>
        <p
          v-if="library && readiness.pending.length > 0"
          class="mt-3 text-[10px]"
          style="color: var(--warning);"
        >
          ⚠ {{ readiness.pending.length }} pièce(s) sans photos. Tu peux créer le cohort,
          mais les itérations ne pourront pas benchmarker ces pièces jusqu'à ce que
          leurs photos soient déposées.
        </p>
      </div>

      <div
        v-if="error"
        class="rounded-md border px-4 py-3 text-sm"
        style="border-color: var(--danger); color: var(--ink);"
      >
        {{ error }}
      </div>

      <div class="flex justify-end gap-2">
        <button
          type="button"
          class="rounded-md border px-4 py-2 text-sm"
          style="border-color: var(--surface-3); color: var(--ink);"
          @click="router.push('/lab')"
        >
          Annuler
        </button>
        <button
          type="submit"
          :disabled="!canSubmit"
          class="flex items-center gap-1.5 rounded-md px-4 py-2 text-sm font-medium"
          :style="{
            background: canSubmit ? 'var(--indigo-700)' : 'var(--surface-2)',
            color: canSubmit ? 'white' : 'var(--ink-400)',
            cursor: canSubmit ? 'pointer' : 'not-allowed',
          }"
        >
          <Loader2 v-if="submitting" class="h-3.5 w-3.5 animate-spin" />
          <Plus v-else class="h-3.5 w-3.5" />
          Créer le cohort
        </button>
      </div>
    </form>
  </div>
</template>
