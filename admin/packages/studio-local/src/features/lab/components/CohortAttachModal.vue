<script setup lang="ts">
// Modal opened from CoinsPage when the user clicks "Cohort lab" with a
// selection. Two paths: create a new cohort (handoff to /lab/cohorts/new)
// or attach the selection to an existing draft cohort (POST /coins).
import { useCohortsQuery } from '@/features/lab/composables/useLabQueries'
import { addCoinsToCohort } from '@/features/lab/composables/useLabApi'
import { useQueryClient } from '@tanstack/vue-query'
import { Loader2, X } from 'lucide-vue-next'
import { computed, ref, watch } from 'vue'
import { useRouter } from 'vue-router'

const props = defineProps<{
  open: boolean
  eurioIds: string[]
}>()

const emit = defineEmits<{
  (e: 'close'): void
}>()

const router = useRouter()
const qc = useQueryClient()

type Mode = 'new' | 'attach'

const mode = ref<Mode>('new')
// Cached in IDB via TanStack Query — opening the modal is instant after
// the first load, even across page reloads.
const draftsQuery = useCohortsQuery(() => ({ status: 'draft' as const }))
const drafts = computed(() => draftsQuery.data.value ?? [])
const draftsLoading = computed(() => draftsQuery.isLoading.value)

const targetCohortId = ref<string>('')
const submitting = ref(false)
const error = ref<string | null>(null)

watch(() => props.open, (isOpen) => {
  if (!isOpen) return
  mode.value = 'new'
  error.value = null
  // Refresh drafts when the modal opens — cheap if cached, ensures we
  // catch any cohort created in another tab.
  draftsQuery.refetch()
})

watch(drafts, (list) => {
  if (!targetCohortId.value && list.length > 0) {
    targetCohortId.value = list[0].id
  }
}, { immediate: true })

const canSubmit = computed(() => {
  if (props.eurioIds.length === 0) return false
  if (mode.value === 'new') return true
  return !!targetCohortId.value && !submitting.value
})

async function submit() {
  error.value = null
  if (!canSubmit.value) return
  if (mode.value === 'new') {
    const ids = props.eurioIds.join(',')
    router.push(`/lab/cohorts/new?eurio_ids=${ids}`)
    emit('close')
    return
  }
  submitting.value = true
  try {
    await addCoinsToCohort(targetCohortId.value, props.eurioIds)
    // Invalidate the queries the detail page depends on so it shows the
    // updated coin list immediately when we navigate.
    qc.invalidateQueries({ queryKey: ['lab', 'cohort', targetCohortId.value] })
    qc.invalidateQueries({ queryKey: ['lab', 'cohorts'] })
    router.push(`/lab/cohorts/${targetCohortId.value}`)
    emit('close')
  } catch (e) {
    error.value = (e as Error).message
  } finally {
    submitting.value = false
  }
}
</script>

<template>
  <Teleport to="body">
    <Transition name="fade">
      <div
        v-if="open"
        class="fixed inset-0 z-50 flex items-center justify-center"
        style="background: rgba(0,0,0,0.5);"
        @click.self="emit('close')"
      >
        <div
          class="w-full max-w-md rounded-lg border px-6 py-5 shadow-xl"
          style="background: var(--surface); border-color: var(--surface-3);"
        >
          <div class="flex items-start justify-between gap-4">
            <div>
              <h2
                class="font-display text-lg italic"
                style="color: var(--indigo-700);"
              >Cohort lab</h2>
              <p class="mt-0.5 text-[11px]" style="color: var(--ink-500);">
                {{ eurioIds.length }} pièce(s) sélectionnée(s)
              </p>
            </div>
            <button
              type="button"
              class="rounded p-1 transition-colors hover:bg-[var(--surface-1)]"
              @click="emit('close')"
            >
              <X class="h-4 w-4" style="color: var(--ink-500);" />
            </button>
          </div>

          <form class="mt-4 flex flex-col gap-3" @submit.prevent="submit">
            <label
              class="flex cursor-pointer items-start gap-2 rounded-md border px-3 py-2"
              :style="{
                borderColor: mode === 'new' ? 'var(--indigo-700)' : 'var(--surface-3)',
                background: mode === 'new' ? 'color-mix(in srgb, var(--indigo-700) 8%, var(--surface))' : 'var(--surface)',
              }"
            >
              <input v-model="mode" type="radio" value="new" class="mt-1" />
              <div class="flex flex-col">
                <span class="text-sm font-medium" style="color: var(--ink);">Créer un nouveau cohort</span>
                <span class="text-[11px]" style="color: var(--ink-500);">
                  Pré-remplit le wizard /lab/cohorts/new avec ta sélection.
                </span>
              </div>
            </label>

            <label
              class="flex cursor-pointer items-start gap-2 rounded-md border px-3 py-2"
              :style="{
                borderColor: mode === 'attach' ? 'var(--indigo-700)' : 'var(--surface-3)',
                background: mode === 'attach' ? 'color-mix(in srgb, var(--indigo-700) 8%, var(--surface))' : 'var(--surface)',
                opacity: drafts.length === 0 && !draftsLoading ? 0.6 : 1,
              }"
            >
              <input
                v-model="mode"
                type="radio"
                value="attach"
                class="mt-1"
                :disabled="drafts.length === 0 && !draftsLoading"
              />
              <div class="flex flex-1 flex-col">
                <span class="text-sm font-medium" style="color: var(--ink);">Ajouter à un cohort existant</span>
                <span v-if="draftsLoading" class="flex items-center gap-1 text-[11px]" style="color: var(--ink-400);">
                  <Loader2 class="h-3 w-3 animate-spin" /> Chargement…
                </span>
                <span v-else-if="drafts.length === 0" class="text-[11px]" style="color: var(--ink-400);">
                  Aucun cohort en draft. Crée-en un d'abord.
                </span>
                <select
                  v-else
                  v-model="targetCohortId"
                  class="mt-1 w-full rounded border px-2 py-1 text-sm"
                  style="background: var(--surface-1); border-color: var(--surface-3); color: var(--ink);"
                  :disabled="mode !== 'attach'"
                >
                  <option v-for="c in drafts" :key="c.id" :value="c.id">
                    {{ c.name }} ({{ c.eurio_ids.length }} pièces)
                  </option>
                </select>
              </div>
            </label>

            <p v-if="error" class="text-xs" style="color: var(--danger);">{{ error }}</p>

            <div class="mt-2 flex items-center justify-end gap-2">
              <button
                type="button"
                class="rounded-md px-3 py-1.5 text-xs"
                style="background: var(--surface-1); color: var(--ink);"
                @click="emit('close')"
              >Annuler</button>
              <button
                type="submit"
                class="flex items-center gap-1.5 rounded-md px-3 py-1.5 text-xs font-medium"
                :disabled="!canSubmit"
                :style="{
                  background: canSubmit ? 'var(--indigo-700)' : 'var(--surface-2)',
                  color: canSubmit ? 'white' : 'var(--ink-400)',
                  cursor: canSubmit ? 'pointer' : 'not-allowed',
                }"
              >
                <Loader2 v-if="submitting" class="h-3 w-3 animate-spin" />
                {{ mode === 'new' ? 'Créer →' : 'Ajouter →' }}
              </button>
            </div>
          </form>
        </div>
      </div>
    </Transition>
  </Teleport>
</template>

<style scoped>
.fade-enter-active,
.fade-leave-active {
  transition: opacity 0.15s ease;
}
.fade-enter-from,
.fade-leave-to {
  opacity: 0;
}
</style>
