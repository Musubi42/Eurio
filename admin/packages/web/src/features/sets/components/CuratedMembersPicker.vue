<script setup lang="ts">
import { supabase } from '@/shared/supabase/client'
import type { Coin } from '@/shared/supabase/types'
import { firstImageUrl } from '@/shared/utils/coin-images'
import { useDebounceFn } from '@vueuse/core'
import {
  ArrowDown,
  ArrowUp,
  ImageOff,
  Plus,
  Search,
  X,
} from 'lucide-vue-next'
import { computed, ref, watch } from 'vue'

const props = defineProps<{
  modelValue: Coin[]  // liste ordonnée des membres
}>()

const emit = defineEmits<{
  'update:modelValue': [value: Coin[]]
}>()

const members = computed(() => props.modelValue)
const memberIds = computed(() => new Set(members.value.map(m => m.eurio_id)))

// ───────── Search ─────────
const query = ref('')
const results = ref<Coin[]>([])
const searching = ref(false)
const searchError = ref<string | null>(null)

async function runSearch(q: string) {
  if (!q.trim() || q.trim().length < 2) {
    results.value = []
    return
  }
  searching.value = true
  searchError.value = null

  const s = q.trim()
  const { data, error } = await supabase
    .from('coins')
    .select('*')
    .or(`eurio_id.ilike.%${s}%,theme.ilike.%${s}%,country.ilike.${s}`)
    .limit(40)

  searching.value = false
  if (error) { searchError.value = error.message; return }
  results.value = (data ?? []) as Coin[]
}

const debouncedSearch = useDebounceFn(() => runSearch(query.value), 250)
watch(query, debouncedSearch)

// ───────── Mutations ─────────
function addMember(coin: Coin) {
  if (memberIds.value.has(coin.eurio_id)) return
  emit('update:modelValue', [...members.value, coin])
}

function removeMember(eurio_id: string) {
  emit('update:modelValue', members.value.filter(m => m.eurio_id !== eurio_id))
}

function moveUp(idx: number) {
  if (idx === 0) return
  const next = [...members.value]
  ;[next[idx - 1], next[idx]] = [next[idx], next[idx - 1]]
  emit('update:modelValue', next)
}

function moveDown(idx: number) {
  if (idx === members.value.length - 1) return
  const next = [...members.value]
  ;[next[idx], next[idx + 1]] = [next[idx + 1], next[idx]]
  emit('update:modelValue', next)
}

// ───────── Helpers ─────────
function firstImage(coin: Coin): string | null {
  return firstImageUrl(coin)
}

function formatFaceValue(v: number): string {
  if (v >= 1) return `${v.toFixed(0)}€`
  return `${(v * 100).toFixed(0)}¢`
}
</script>

<template>
  <div class="space-y-4">

    <!-- ══ Search bar ══ -->
    <div>
      <h3 class="mb-2 text-[10px] font-medium uppercase tracking-widest"
          style="color: var(--ink-500);">
        Ajouter des pièces
      </h3>
      <div class="relative">
        <Search class="absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2"
                style="color: var(--ink-400);" />
        <input
          v-model="query"
          type="search"
          placeholder="eurio_id, thème, pays (fr, mc, va…)"
          class="w-full rounded-md border py-2 pl-9 pr-3 text-sm outline-none focus:ring-2"
          style="border-color: var(--surface-3); background: var(--surface); color: var(--ink); --tw-ring-color: var(--indigo-700);"
        />
      </div>
      <p v-if="query.length > 0 && query.length < 2"
         class="mt-1 text-[10px]" style="color: var(--ink-400);">
        Minimum 2 caractères.
      </p>
    </div>

    <!-- ══ Search results ══ -->
    <div v-if="query.length >= 2"
         class="rounded-lg border"
         style="border-color: var(--surface-3); background: var(--surface-1);">

      <div class="border-b px-3 py-2"
           style="border-color: var(--surface-3);">
        <p class="text-[10px] uppercase tracking-wider" style="color: var(--ink-500);">
          Résultats
          <span v-if="!searching && results.length > 0" class="font-mono" style="color: var(--ink);">
            ({{ results.length }})
          </span>
          <span v-if="searching" style="color: var(--ink-400);">· recherche…</span>
        </p>
      </div>

      <div v-if="searchError" class="p-3 text-xs" style="color: var(--danger);">
        {{ searchError }}
      </div>

      <div v-else-if="!searching && results.length === 0"
           class="p-4 text-center text-xs" style="color: var(--ink-400);">
        Aucun résultat
      </div>

      <div v-else class="max-h-64 overflow-y-auto p-2">
        <button
          v-for="coin in results"
          :key="coin.eurio_id"
          type="button"
          class="group flex w-full items-center gap-3 rounded-md border border-transparent p-1.5 text-left transition-colors hover:bg-surface-2 disabled:opacity-40"
          :disabled="memberIds.has(coin.eurio_id)"
          @click="addMember(coin)"
        >
          <!-- thumbnail -->
          <div
            class="flex h-10 w-10 flex-shrink-0 items-center justify-center rounded"
            style="background: var(--surface);"
          >
            <img
              v-if="firstImage(coin)"
              :src="firstImage(coin)!"
              class="h-full w-full object-contain p-0.5"
              loading="lazy"
            />
            <ImageOff v-else class="h-3 w-3" style="color: var(--ink-300);" />
          </div>
          <!-- meta -->
          <div class="min-w-0 flex-1">
            <p class="truncate font-mono text-[10px]" style="color: var(--ink-400);">
              {{ coin.eurio_id }}
            </p>
            <p class="truncate text-xs font-medium" style="color: var(--ink);">
              <span class="font-mono">{{ coin.country }} {{ coin.year }}</span>
              · {{ formatFaceValue(coin.face_value) }}
              <span v-if="coin.theme"> · {{ coin.theme }}</span>
            </p>
          </div>
          <!-- action -->
          <span v-if="memberIds.has(coin.eurio_id)"
                class="flex-shrink-0 text-[10px] font-medium uppercase tracking-wider"
                style="color: var(--success);">
            ✓ ajouté
          </span>
          <Plus v-else
                class="h-4 w-4 flex-shrink-0 opacity-0 transition-opacity group-hover:opacity-100"
                style="color: var(--indigo-700);" />
        </button>
      </div>
    </div>

    <!-- ══ Selected members ══ -->
    <div>
      <div class="mb-2 flex items-center justify-between">
        <h3 class="text-[10px] font-medium uppercase tracking-widest"
            style="color: var(--ink-500);">
          Membres sélectionnés
        </h3>
        <span class="font-mono text-xs" style="color: var(--gold-deep);">
          {{ members.length }}
        </span>
      </div>

      <div v-if="members.length === 0"
           class="flex flex-col items-center justify-center rounded-lg border-2 border-dashed py-8"
           style="border-color: var(--surface-3);">
        <p class="font-display italic text-sm" style="color: var(--ink-400);">
          Aucun membre
        </p>
        <p class="mt-1 text-[10px]" style="color: var(--ink-400);">
          Recherche et clique sur une pièce pour l'ajouter.
        </p>
      </div>

      <ol v-else class="space-y-1.5">
        <li
          v-for="(coin, idx) in members"
          :key="coin.eurio_id"
          class="flex items-center gap-2 rounded-md border px-2 py-1.5"
          style="border-color: var(--surface-3); background: var(--surface);"
        >
          <!-- position -->
          <span class="w-5 flex-shrink-0 text-right font-mono text-[10px]"
                style="color: var(--ink-400);">
            {{ idx + 1 }}
          </span>

          <!-- thumbnail -->
          <div
            class="flex h-9 w-9 flex-shrink-0 items-center justify-center rounded"
            style="background: var(--surface-1);"
          >
            <img
              v-if="firstImage(coin)"
              :src="firstImage(coin)!"
              class="h-full w-full object-contain p-0.5"
              loading="lazy"
            />
            <ImageOff v-else class="h-3 w-3" style="color: var(--ink-300);" />
          </div>

          <!-- meta -->
          <div class="min-w-0 flex-1">
            <p class="truncate text-xs font-medium" style="color: var(--ink);">
              <span class="font-mono">{{ coin.country }} {{ coin.year }}</span>
              · {{ formatFaceValue(coin.face_value) }}
              <span v-if="coin.theme"> · {{ coin.theme }}</span>
            </p>
            <p class="truncate font-mono text-[9px]" style="color: var(--ink-400);">
              {{ coin.eurio_id }}
            </p>
          </div>

          <!-- reorder -->
          <div class="flex gap-0.5">
            <button
              type="button"
              class="rounded p-1 transition-colors hover:bg-surface-2 disabled:opacity-20"
              style="color: var(--ink-500);"
              :disabled="idx === 0"
              title="Monter"
              @click="moveUp(idx)"
            >
              <ArrowUp class="h-3 w-3" />
            </button>
            <button
              type="button"
              class="rounded p-1 transition-colors hover:bg-surface-2 disabled:opacity-20"
              style="color: var(--ink-500);"
              :disabled="idx === members.length - 1"
              title="Descendre"
              @click="moveDown(idx)"
            >
              <ArrowDown class="h-3 w-3" />
            </button>
          </div>

          <!-- remove -->
          <button
            type="button"
            class="rounded p-1 transition-colors hover:bg-surface-2"
            style="color: var(--danger);"
            title="Retirer"
            @click="removeMember(coin.eurio_id)"
          >
            <X class="h-3 w-3" />
          </button>
        </li>
      </ol>
    </div>
  </div>
</template>
