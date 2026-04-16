<script setup lang="ts">
import type { I18nField, Set, SetCategory, SetKind, SetReward } from '@/shared/supabase/types'
import { computed } from 'vue'

type EditableSet = Partial<Set> & { id: string; kind: SetKind; category: SetCategory }

const props = defineProps<{
  modelValue: EditableSet
  creating: boolean
}>()

const emit = defineEmits<{
  'update:modelValue': [value: EditableSet]
}>()

const set = computed(() => props.modelValue)

function patch<K extends keyof EditableSet>(key: K, value: EditableSet[K]) {
  emit('update:modelValue', { ...set.value, [key]: value })
}

function patchI18n(
  field: 'name_i18n' | 'description_i18n',
  lang: keyof I18nField,
  value: string,
) {
  const current = (set.value[field] ?? { fr: '' }) as I18nField
  const next = { ...current, [lang]: value }
  emit('update:modelValue', { ...set.value, [field]: next })
}

function patchReward(partial: Partial<SetReward>) {
  const current = (set.value.reward ?? {}) as SetReward
  const next = { ...current, ...partial }
  emit('update:modelValue', { ...set.value, reward: next })
}

const CATEGORIES: { value: SetCategory; label: string }[] = [
  { value: 'country',  label: 'Pays' },
  { value: 'theme',    label: 'Thème' },
  { value: 'tier',     label: 'Tier' },
  { value: 'personal', label: 'Personnel' },
  { value: 'hunt',     label: 'Chasse' },
]

const BADGES: SetReward['badge'][] = ['bronze', 'silver', 'gold']

const name = computed(() => (set.value.name_i18n ?? { fr: '' }) as I18nField)
const desc = computed(() => (set.value.description_i18n ?? { fr: '' }) as I18nField)
const reward = computed(() => (set.value.reward ?? {}) as SetReward)
</script>

<template>
  <div class="space-y-5">

    <!-- ID (lecture seule si edit) -->
    <div>
      <label class="mb-1.5 block text-[10px] font-medium uppercase tracking-widest"
             style="color: var(--ink-500);">
        Identifiant
      </label>
      <input
        type="text"
        :value="set.id"
        :disabled="!creating"
        placeholder="circulation-fr-2022"
        class="w-full rounded-md border px-3 py-2 font-mono text-sm outline-none focus:ring-2 disabled:opacity-60"
        style="border-color: var(--surface-3); background: var(--surface); color: var(--ink); --tw-ring-color: var(--indigo-700);"
        @input="patch('id', ($event.target as HTMLInputElement).value)"
      />
      <p v-if="creating" class="mt-1 text-[10px]" style="color: var(--ink-400);">
        Identifiant stable, kebab-case, non modifiable après création.
      </p>
    </div>

    <!-- Nom i18n -->
    <div>
      <label class="mb-1.5 block text-[10px] font-medium uppercase tracking-widest"
             style="color: var(--ink-500);">
        Nom <span style="color: var(--danger);">*</span>
      </label>
      <div class="space-y-1.5">
        <div v-for="lang in (['fr','en','de','it'] as const)" :key="lang" class="flex items-center gap-2">
          <span class="w-6 font-mono text-[10px] uppercase" style="color: var(--ink-400);">
            {{ lang }}
          </span>
          <input
            type="text"
            :value="name[lang] ?? ''"
            :placeholder="lang === 'fr' ? 'Circulation France — Type 2022' : '(optionnel)'"
            class="flex-1 rounded-md border px-3 py-1.5 text-sm outline-none focus:ring-2"
            style="border-color: var(--surface-3); background: var(--surface); color: var(--ink); --tw-ring-color: var(--indigo-700);"
            @input="patchI18n('name_i18n', lang, ($event.target as HTMLInputElement).value)"
          />
        </div>
      </div>
      <p class="mt-1 text-[10px]" style="color: var(--ink-400);">
        <code>fr</code> et <code>en</code> requis pour publier.
      </p>
    </div>

    <!-- Description i18n -->
    <div>
      <label class="mb-1.5 block text-[10px] font-medium uppercase tracking-widest"
             style="color: var(--ink-500);">
        Description
      </label>
      <div class="space-y-1.5">
        <div v-for="lang in (['fr','en'] as const)" :key="lang" class="flex items-start gap-2">
          <span class="mt-1.5 w-6 font-mono text-[10px] uppercase" style="color: var(--ink-400);">
            {{ lang }}
          </span>
          <textarea
            :value="desc[lang] ?? ''"
            rows="2"
            placeholder="(optionnel)"
            class="flex-1 rounded-md border px-3 py-1.5 text-sm outline-none focus:ring-2"
            style="border-color: var(--surface-3); background: var(--surface); color: var(--ink); --tw-ring-color: var(--indigo-700);"
            @input="patchI18n('description_i18n', lang, ($event.target as HTMLTextAreaElement).value)"
          />
        </div>
      </div>
    </div>

    <!-- Catégorie + ordre -->
    <div class="grid grid-cols-2 gap-4">
      <div>
        <label class="mb-1.5 block text-[10px] font-medium uppercase tracking-widest"
               style="color: var(--ink-500);">
          Catégorie
        </label>
        <select
          :value="set.category"
          class="w-full rounded-md border px-3 py-2 text-sm outline-none focus:ring-2"
          style="border-color: var(--surface-3); background: var(--surface); color: var(--ink); --tw-ring-color: var(--indigo-700);"
          @change="patch('category', ($event.target as HTMLSelectElement).value as SetCategory)"
        >
          <option v-for="c in CATEGORIES" :key="c.value" :value="c.value">
            {{ c.label }}
          </option>
        </select>
      </div>

      <div>
        <label class="mb-1.5 block text-[10px] font-medium uppercase tracking-widest"
               style="color: var(--ink-500);">
          Ordre d'affichage
        </label>
        <input
          type="number"
          :value="set.display_order ?? 1000"
          min="0"
          step="10"
          class="w-full rounded-md border px-3 py-2 font-mono text-sm outline-none focus:ring-2"
          style="border-color: var(--surface-3); background: var(--surface); color: var(--ink); --tw-ring-color: var(--indigo-700);"
          @input="patch('display_order', parseInt(($event.target as HTMLInputElement).value) || 1000)"
        />
      </div>
    </div>

    <!-- Expected count -->
    <div>
      <label class="mb-1.5 block text-[10px] font-medium uppercase tracking-widest"
             style="color: var(--ink-500);">
        Nombre attendu (sanity check)
      </label>
      <input
        type="number"
        :value="set.expected_count ?? ''"
        min="0"
        placeholder="(optionnel)"
        class="w-28 rounded-md border px-3 py-2 font-mono text-sm outline-none focus:ring-2"
        style="border-color: var(--surface-3); background: var(--surface); color: var(--ink); --tw-ring-color: var(--indigo-700);"
        @input="patch('expected_count', parseInt(($event.target as HTMLInputElement).value) || null)"
      />
      <p class="mt-1 text-[10px]" style="color: var(--ink-400);">
        Si défini, la Live preview flag en orange si <code>actual ≠ expected</code>.
      </p>
    </div>

    <!-- Reward -->
    <div>
      <label class="mb-1.5 block text-[10px] font-medium uppercase tracking-widest"
             style="color: var(--ink-500);">
        Récompense
      </label>
      <div class="space-y-2 rounded-md border p-3"
           style="border-color: var(--surface-3); background: var(--surface-1);">
        <div>
          <p class="mb-1 text-[10px] uppercase tracking-wider" style="color: var(--ink-400);">Badge</p>
          <div class="flex gap-1.5">
            <button
              v-for="b in BADGES"
              :key="b"
              type="button"
              class="rounded-md border px-3 py-1 text-xs font-medium capitalize transition-all"
              :style="reward.badge === b
                ? b === 'gold' ? 'border-color: var(--gold); background: var(--gold); color: var(--ink)'
                : b === 'silver' ? 'border-color: var(--ink-300); background: var(--ink-300); color: var(--ink)'
                : 'border-color: #B87333; background: #B87333; color: white'
                : 'border-color: var(--surface-3); background: var(--surface); color: var(--ink-500)'"
              @click="patchReward({ badge: reward.badge === b ? undefined : b })"
            >
              {{ b }}
            </button>
          </div>
        </div>
        <div class="flex items-center gap-3">
          <label class="flex items-center gap-2 text-xs" style="color: var(--ink);">
            XP
            <input
              type="number"
              :value="reward.xp ?? ''"
              min="0"
              step="50"
              placeholder="0"
              class="w-20 rounded-md border px-2 py-1 font-mono text-xs outline-none"
              style="border-color: var(--surface-3); background: var(--surface); color: var(--ink);"
              @input="patchReward({ xp: parseInt(($event.target as HTMLInputElement).value) || undefined })"
            />
          </label>
          <label class="flex cursor-pointer items-center gap-1.5 text-xs" style="color: var(--ink);">
            <input
              type="checkbox"
              :checked="reward.level_bump ?? false"
              class="h-3.5 w-3.5 rounded"
              @change="patchReward({ level_bump: ($event.target as HTMLInputElement).checked || undefined })"
            />
            Level bump
          </label>
        </div>
      </div>
    </div>

    <!-- Active toggle -->
    <div class="flex items-center justify-between rounded-md border p-3"
         style="border-color: var(--surface-3); background: var(--surface);">
      <div>
        <p class="text-xs font-medium" style="color: var(--ink);">Actif</p>
        <p class="text-[10px]" style="color: var(--ink-500);">
          Seuls les sets actifs sont exposés à l'app mobile.
        </p>
      </div>
      <button
        type="button"
        class="relative h-5 w-9 rounded-full transition-colors"
        :style="(set.active ?? true) ? 'background: var(--success)' : 'background: var(--ink-300)'"
        @click="patch('active', !(set.active ?? true))"
      >
        <span
          class="absolute top-0.5 h-4 w-4 rounded-full bg-white transition-all"
          :style="(set.active ?? true) ? 'left: 1.125rem' : 'left: 0.125rem'"
        />
      </button>
    </div>
  </div>
</template>
