<script setup lang="ts">
import { createCohort } from '@/features/lab/composables/useLabApi'
import { useQueryClient } from '@tanstack/vue-query'
import { ArrowLeft, Loader2, Plus } from 'lucide-vue-next'
import { computed, onMounted, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'

const router = useRouter()
const route = useRoute()
const qc = useQueryClient()

const name = ref<string>('')
const description = ref<string>('')
const zone = ref<'' | 'green' | 'orange' | 'red'>('')
const rawIds = ref<string>('')

const submitting = ref(false)
const error = ref<string | null>(null)

onMounted(() => {
  // Prefill from ?eurio_ids= (handoff from /coins). Optional — the user can
  // also create an empty cohort and attach coins later from the /coins page.
  const prefill = route.query.eurio_ids
  if (typeof prefill === 'string' && prefill.length > 0) {
    rawIds.value = prefill.split(',').join('\n')
  }
})

const parsedIds = computed<string[]>(() => {
  const tokens = rawIds.value
    .split(/[\n,]+/)
    .map(s => s.trim())
    .filter(Boolean)
  return Array.from(new Set(tokens))
})

const nameValid = computed(() => /^[a-z0-9][a-z0-9-]*[a-z0-9]$/.test(name.value))
const canSubmit = computed(() => nameValid.value && !submitting.value)

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
    qc.invalidateQueries({ queryKey: ['lab', 'cohorts'] })
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
        Crée un cohort en draft
      </h1>
      <p class="mt-1.5 text-sm" style="color: var(--ink-500);">
        Crée un cohort vide ou pré-rempli. Les nouveaux cohorts naissent en
        <strong>draft</strong> — tu peux ajouter/retirer des pièces depuis
        <code class="font-mono">/coins</code> tant qu'aucune itération n'a été lancée.
        Le premier run fige le cohort.
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
            eurio_ids (optionnel · un par ligne ou séparés par virgule)
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
          {{ parsedIds.length }} pièce(s) reconnue(s). Vide = cohort créé sans pièces ;
          tu pourras les ajouter depuis <code class="font-mono">/coins</code>.
          La couverture captures s'affichera dans la page detail (§2 Captures).
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
