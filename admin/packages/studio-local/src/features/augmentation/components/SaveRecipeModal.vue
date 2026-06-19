<script setup lang="ts">
import { X } from 'lucide-vue-next'
import { computed, ref, watch } from 'vue'

const props = defineProps<{
  open: boolean
  initialZone?: string | null
  basedOnName?: string | null
  defaultName?: string
}>()

const emit = defineEmits<{
  (e: 'close'): void
  (e: 'save', payload: { name: string; zone: string | null }): void
}>()

const name = ref(props.defaultName ?? '')
const zone = ref<string>(props.initialZone ?? '')
const error = ref<string | null>(null)

watch(() => props.open, (isOpen) => {
  if (isOpen) {
    name.value = props.defaultName ?? ''
    zone.value = props.initialZone ?? ''
    error.value = null
  }
})

const kebabRe = /^[a-z0-9][a-z0-9-]*[a-z0-9]$/

const isValid = computed(() => {
  if (!name.value.trim()) return false
  if (!kebabRe.test(name.value)) return false
  return true
})

function submit() {
  error.value = null
  if (!isValid.value) {
    error.value = 'Nom requis en kebab-case (a-z, 0-9, -)'
    return
  }
  emit('save', { name: name.value.trim(), zone: zone.value || null })
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
              >Sauvegarder la recette</h2>
              <p
                v-if="basedOnName"
                class="mt-0.5 text-[11px]"
                style="color: var(--ink-500);"
              >clone de <span class="font-mono">{{ basedOnName }}</span></p>
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
            <div class="flex flex-col gap-1">
              <label class="text-xs font-medium" style="color: var(--ink);">Nom</label>
              <input
                v-model="name"
                type="text"
                placeholder="red-tuned-v2"
                class="rounded border px-2 py-1.5 font-mono text-sm"
                style="background: var(--surface-1); border-color: var(--surface-3); color: var(--ink);"
                autofocus
              />
              <p class="text-[10px]" style="color: var(--ink-400);">
                Kebab-case, unique. Le serveur rejette les doublons.
              </p>
            </div>

            <div class="flex flex-col gap-1">
              <label class="text-xs font-medium" style="color: var(--ink);">Zone (optionnel)</label>
              <select
                v-model="zone"
                class="rounded border px-2 py-1.5 text-sm"
                style="background: var(--surface-1); border-color: var(--surface-3); color: var(--ink);"
              >
                <option value="">— libre —</option>
                <option value="green">green</option>
                <option value="orange">orange</option>
                <option value="red">red</option>
              </select>
            </div>

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
                class="rounded-md px-3 py-1.5 text-xs font-medium"
                style="background: var(--indigo-700); color: white;"
                :disabled="!isValid"
                :style="{ opacity: isValid ? 1 : 0.5, cursor: isValid ? 'pointer' : 'not-allowed' }"
              >Enregistrer</button>
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
