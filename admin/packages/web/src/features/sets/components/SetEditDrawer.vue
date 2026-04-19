<script setup lang="ts">
import { supabase } from '@/shared/supabase/client'
import type {
  Coin,
  I18nField,
  Set,
  SetCategory,
  SetCriteria,
  SetKind,
} from '@/shared/supabase/types'
import { useEventListener } from '@vueuse/core'
import { Archive, ArchiveRestore, Save, Trash2, X } from 'lucide-vue-next'
import { computed, ref, watch } from 'vue'
import CriteriaBuilder from './CriteriaBuilder.vue'
import CuratedMembersPicker from './CuratedMembersPicker.vue'
import LivePreview from './LivePreview.vue'
import SetMetadataForm from './SetMetadataForm.vue'

type EditableSet = Partial<Set> & { id: string; kind: SetKind; category: SetCategory }

const props = defineProps<{
  open: boolean
  setId: string | null  // null = create mode
}>()

const emit = defineEmits<{
  close: []
  saved: [set: Set]
}>()

// ───────── State ─────────
const loading = ref(false)
const saving = ref(false)
const archiving = ref(false)
const deleting = ref(false)
const confirmingDelete = ref(false)
const error = ref<string | null>(null)
const edited = ref<EditableSet>(emptySet())
const original = ref<Set | null>(null)
const kindPicked = ref(false)
const members = ref<Coin[]>([])  // pour kind='curated', ordonnés par position

const creating = computed(() => props.setId === null)

function emptySet(): EditableSet {
  return {
    id: '',
    kind: 'structural',
    category: 'country',
    name_i18n: { fr: '' },
    description_i18n: { fr: '' },
    criteria: null,
    reward: {},
    display_order: 1000,
    active: true,
    expected_count: null,
    icon: null,
    param_key: null,
  }
}

// ───────── Load / reset ─────────
watch(
  () => [props.open, props.setId] as const,
  async ([isOpen, id]) => {
    if (!isOpen) return
    error.value = null
    kindPicked.value = false
    confirmingDelete.value = false
    members.value = []

    if (id === null) {
      // Create mode
      edited.value = emptySet()
      original.value = null
      return
    }

    // Edit mode — fetch the set
    loading.value = true
    kindPicked.value = true
    const { data, error: err } = await supabase
      .from('sets')
      .select('*')
      .eq('id', id)
      .maybeSingle()

    if (err) { loading.value = false; error.value = err.message; return }
    if (!data) { loading.value = false; error.value = 'Set introuvable'; return }

    original.value = data as Set
    edited.value = { ...(data as Set) }

    // Si curated, fetch aussi les membres avec leur position + coin data
    if ((data as Set).kind === 'curated') {
      const { data: memberRows, error: memberErr } = await supabase
        .from('set_members')
        .select('position, coins(*)')
        .eq('set_id', id)
        .order('position', { ascending: true, nullsFirst: false })

      if (memberErr) {
        loading.value = false
        error.value = `Erreur chargement membres : ${memberErr.message}`
        return
      }

      members.value = (memberRows ?? [])
        .map(r => (r as { coins: Coin }).coins)
        .filter(Boolean)
    }

    loading.value = false
  },
  { immediate: true },
)

// ───────── Criteria v-model pass-through ─────────
const criteria = computed<SetCriteria | null>({
  get: () => edited.value.criteria ?? null,
  set: (v) => {
    edited.value = { ...edited.value, criteria: v }
  },
})

// ───────── Kind picker (create flow) ─────────
function pickKind(k: SetKind) {
  edited.value = { ...edited.value, kind: k }
  kindPicked.value = true
}

// ───────── Validation ─────────
const validationErrors = computed<string[]>(() => {
  const errs: string[] = []
  const s = edited.value

  if (!s.id.trim()) errs.push('Identifiant requis')
  else if (!/^[a-z0-9-]+$/.test(s.id)) errs.push('Identifiant en kebab-case (a-z, 0-9, -)')

  const name = (s.name_i18n ?? {}) as I18nField
  if (!name.fr?.trim()) errs.push('Nom (fr) requis')
  if (!name.en?.trim()) errs.push('Nom (en) requis')

  if (s.kind !== 'curated' && (!s.criteria || Object.keys(s.criteria).length === 0)) {
    errs.push('Au moins un critère requis')
  }

  if (s.kind === 'curated' && members.value.length === 0) {
    errs.push('Au moins un membre requis')
  }

  if (s.kind === 'parametric' && !s.param_key?.trim()) {
    errs.push('param_key requis pour un set paramétré')
  }

  return errs
})

const canSave = computed(() => validationErrors.value.length === 0 && !saving.value && !loading.value)

// ───────── Save ─────────
async function save() {
  if (!canSave.value) return
  saving.value = true
  error.value = null

  const s = edited.value
  const payload = {
    id: s.id,
    kind: s.kind,
    category: s.category,
    name_i18n: s.name_i18n,
    description_i18n: s.description_i18n,
    criteria: s.criteria,
    param_key: s.param_key,
    reward: s.reward,
    display_order: s.display_order ?? 1000,
    icon: s.icon,
    expected_count: s.expected_count,
    active: s.active ?? true,
    updated_at: new Date().toISOString(),
  }

  // Supabase JS typing conflicts with our narrowed JSONB shapes — cast pragmatiquement
  const { data, error: err } = creating.value
    ? await supabase.from('sets').insert(payload as never).select().single()
    : await supabase.from('sets').update(payload as never).eq('id', s.id).select().single()

  if (err) {
    saving.value = false
    error.value = err.message
    return
  }

  // Sync set_members pour les sets curés (delete all + insert all)
  if (s.kind === 'curated') {
    const { error: delErr } = await supabase
      .from('set_members')
      .delete()
      .eq('set_id', s.id)

    if (delErr) {
      saving.value = false
      error.value = `Erreur suppression membres : ${delErr.message}`
      return
    }

    if (members.value.length > 0) {
      const memberRows = members.value.map((coin, idx) => ({
        set_id: s.id,
        eurio_id: coin.eurio_id,
        position: idx,
      }))
      const { error: insErr } = await supabase
        .from('set_members')
        .insert(memberRows as never)

      if (insErr) {
        saving.value = false
        error.value = `Erreur insertion membres : ${insErr.message}`
        return
      }
    }
  }

  // Audit log
  await supabase.from('sets_audit').insert({
    set_id: s.id,
    action: creating.value ? 'create' : 'update',
    before: (original.value ?? null) as never,
    after: data as never,
    actor: 'admin-dev-bypass',
  } as never)

  saving.value = false
  emit('saved', data as Set)
  emit('close')
}

// ───────── Archive (toggle active) ─────────
async function toggleArchive() {
  if (creating.value || !original.value) return
  archiving.value = true
  error.value = null

  const newActive = !original.value.active
  const { data, error: err } = await supabase
    .from('sets')
    .update({ active: newActive, updated_at: new Date().toISOString() } as never)
    .eq('id', original.value.id)
    .select()
    .single()

  if (err) {
    archiving.value = false
    error.value = err.message
    return
  }

  await supabase.from('sets_audit').insert({
    set_id: original.value.id,
    action: newActive ? 'activate' : 'deactivate',
    before: original.value as never,
    after: data as never,
    actor: 'admin-dev-bypass',
  } as never)

  archiving.value = false
  emit('saved', data as Set)
  emit('close')
}

// ───────── Hard delete ─────────
async function hardDelete() {
  if (creating.value || !original.value) return
  deleting.value = true
  error.value = null

  // Audit FIRST car après DELETE la row n'existe plus
  await supabase.from('sets_audit').insert({
    set_id: original.value.id,
    action: 'delete',
    before: original.value as never,
    after: null,
    actor: 'admin-dev-bypass',
  } as never)

  // set_members sera cascade-deleted via FK ON DELETE CASCADE
  const { error: err } = await supabase
    .from('sets')
    .delete()
    .eq('id', original.value.id)

  if (err) {
    deleting.value = false
    error.value = err.message
    return
  }

  deleting.value = false
  emit('saved', original.value)  // trigger refetch
  emit('close')
}

// ───────── ESC to close ─────────
useEventListener('keydown', (e: KeyboardEvent) => {
  if (e.key === 'Escape' && props.open) emit('close')
})

const KINDS: { value: SetKind; title: string; desc: string }[] = [
  {
    value: 'structural',
    title: 'Structurel',
    desc: 'Dérivé du référentiel via DSL (95% des cas). Ex: circulation-fr-2022.',
  },
  {
    value: 'curated',
    title: 'Curé',
    desc: 'Liste explicite d\'eurio_id. Réservé à Grande Chasse et cas éditoriaux.',
  },
  {
    value: 'parametric',
    title: 'Paramétré',
    desc: 'Structurel + variable utilisateur. Ex: année de naissance.',
  },
]
</script>

<template>
  <Teleport to="body">
    <!-- Backdrop -->
    <Transition
      enter-active-class="transition-opacity duration-200"
      enter-from-class="opacity-0"
      enter-to-class="opacity-100"
      leave-active-class="transition-opacity duration-150"
      leave-from-class="opacity-100"
      leave-to-class="opacity-0"
    >
      <div
        v-if="open"
        class="fixed inset-0 z-50"
        style="background: rgba(14,14,31,0.45); backdrop-filter: blur(2px);"
        @click="emit('close')"
      />
    </Transition>

    <!-- Drawer -->
    <Transition
      enter-active-class="transition-transform duration-300"
      enter-from-class="translate-x-full"
      enter-to-class="translate-x-0"
      leave-active-class="transition-transform duration-200"
      leave-from-class="translate-x-0"
      leave-to-class="translate-x-full"
    >
      <div
        v-if="open"
        class="fixed right-0 top-0 z-50 flex h-screen w-full max-w-[900px] flex-col"
        style="background: var(--surface); box-shadow: var(--shadow-lg);"
      >
        <!-- Header -->
        <header class="flex items-center justify-between border-b px-6 py-4"
                style="border-color: var(--surface-3); background: var(--surface-1);">
          <div>
            <p class="text-[10px] font-medium uppercase tracking-widest"
               style="color: var(--ink-500);">
              {{ creating ? 'Nouveau set' : 'Édition' }}
            </p>
            <h2 class="font-display text-xl italic font-semibold"
                style="color: var(--indigo-700);">
              {{ creating ? 'Créer un set d\'achievement' : (edited.name_i18n as I18nField)?.fr || edited.id }}
            </h2>
          </div>
          <button
            class="rounded-md p-2 transition-colors hover:bg-surface-2"
            style="color: var(--ink-500);"
            @click="emit('close')"
          >
            <X class="h-4 w-4" />
          </button>
        </header>

        <!-- Body -->
        <div class="flex-1 overflow-y-auto">
          <!-- Loading -->
          <div v-if="loading" class="flex items-center justify-center py-16">
            <div class="text-xs" style="color: var(--ink-500);">Chargement…</div>
          </div>

          <!-- Kind picker (create step 1) -->
          <div v-else-if="creating && !kindPicked" class="p-8">
            <h3 class="mb-1 font-display text-lg italic" style="color: var(--indigo-700);">
              Quelle est la nature de ce set ?
            </h3>
            <p class="mb-6 text-sm" style="color: var(--ink-500);">
              Choisis comment les membres seront déterminés.
            </p>
            <div class="grid grid-cols-1 gap-3 md:grid-cols-3">
              <button
                v-for="k in KINDS"
                :key="k.value"
                type="button"
                class="rounded-lg border p-5 text-left transition-all hover:-translate-y-0.5"
                style="border-color: var(--surface-3); background: var(--surface); box-shadow: var(--shadow-sm);"
                @click="pickKind(k.value)"
              >
                <h4 class="font-display text-base italic font-semibold"
                    style="color: var(--indigo-700);">
                  {{ k.title }}
                </h4>
                <p class="mt-1 text-xs leading-relaxed" style="color: var(--ink-500);">
                  {{ k.desc }}
                </p>
              </button>
            </div>
          </div>

          <!-- Main form -->
          <div v-else class="grid grid-cols-1 gap-6 p-6 lg:grid-cols-[1fr_1.2fr]">

            <!-- LEFT : metadata -->
            <div>
              <h3 class="mb-3 text-[10px] font-medium uppercase tracking-widest"
                  style="color: var(--ink-500);">
                Metadata
              </h3>
              <SetMetadataForm v-model="edited" :creating="creating" />
            </div>

            <!-- RIGHT : criteria or members + preview -->
            <div class="space-y-4">
              <template v-if="edited.kind === 'curated'">
                <h3 class="text-[10px] font-medium uppercase tracking-widest"
                    style="color: var(--ink-500);">
                  Membres curés
                </h3>
                <CuratedMembersPicker v-model="members" />
              </template>

              <template v-else>
                <h3 class="text-[10px] font-medium uppercase tracking-widest"
                    style="color: var(--ink-500);">
                  Critères (DSL)
                </h3>
                <CriteriaBuilder v-model="criteria" />
                <LivePreview :criteria="criteria" :expected-count="edited.expected_count" />
              </template>
            </div>
          </div>
        </div>

        <!-- Footer -->
        <footer class="border-t px-6 py-4"
                style="border-color: var(--surface-3); background: var(--surface-1);">

          <!-- Validation / error row -->
          <div v-if="error || validationErrors.length > 0" class="mb-3">
            <div v-if="error"
                 class="rounded-md px-3 py-1.5 text-xs"
                 style="background: var(--danger-soft); color: var(--danger);">
              {{ error }}
            </div>
            <div v-else-if="validationErrors.length > 0"
                 class="text-[10px]" style="color: var(--warning);">
              {{ validationErrors.join(' · ') }}
            </div>
          </div>

          <!-- Actions row -->
          <div class="flex items-center justify-between">
            <!-- Destructive actions (edit only) -->
            <div class="flex items-center gap-2">
              <template v-if="!creating && original && !confirmingDelete">
                <button
                  type="button"
                  class="flex items-center gap-1.5 rounded-md border px-3 py-1.5 text-xs transition-colors hover:bg-surface-2 disabled:opacity-40"
                  style="border-color: var(--surface-3); color: var(--ink-500);"
                  :disabled="archiving || deleting"
                  @click="toggleArchive"
                >
                  <component :is="original.active ? Archive : ArchiveRestore" class="h-3.5 w-3.5" />
                  {{ archiving
                    ? '…'
                    : original.active ? 'Désactiver' : 'Réactiver' }}
                </button>
                <button
                  type="button"
                  class="flex items-center gap-1.5 rounded-md border px-3 py-1.5 text-xs transition-colors hover:bg-danger-soft disabled:opacity-40"
                  style="border-color: var(--danger); color: var(--danger);"
                  :disabled="archiving || deleting"
                  @click="confirmingDelete = true"
                >
                  <Trash2 class="h-3.5 w-3.5" />
                  Supprimer
                </button>
              </template>

              <template v-else-if="confirmingDelete">
                <span class="text-xs font-medium" style="color: var(--danger);">
                  Supprimer définitivement ?
                  <span v-if="edited.kind === 'curated' && members.length > 0"
                        class="font-normal" style="color: var(--ink-500);">
                    ({{ members.length }} membre{{ members.length > 1 ? 's' : '' }} en cascade)
                  </span>
                </span>
                <button
                  type="button"
                  class="rounded-md border px-3 py-1.5 text-xs transition-colors hover:bg-surface-2"
                  style="border-color: var(--surface-3); color: var(--ink-500);"
                  @click="confirmingDelete = false"
                >
                  Non
                </button>
                <button
                  type="button"
                  class="flex items-center gap-1.5 rounded-md px-3 py-1.5 text-xs font-medium transition-opacity"
                  style="background: var(--danger); color: white;"
                  :disabled="deleting"
                  @click="hardDelete"
                >
                  <Trash2 class="h-3.5 w-3.5" />
                  {{ deleting ? 'Suppression…' : 'Oui, supprimer' }}
                </button>
              </template>
            </div>

            <!-- Save / cancel -->
            <div class="flex items-center gap-2">
              <button
                type="button"
                class="rounded-md border px-4 py-2 text-sm transition-colors hover:bg-surface-2"
                style="border-color: var(--surface-3); color: var(--ink-500);"
                @click="emit('close')"
              >
                Annuler
              </button>
              <button
                type="button"
                class="flex items-center gap-2 rounded-md px-4 py-2 text-sm font-medium transition-opacity disabled:opacity-40"
                style="background: var(--indigo-700); color: white;"
                :disabled="!canSave || archiving || deleting || confirmingDelete"
                @click="save"
              >
                <Save class="h-4 w-4" />
                {{ saving ? 'Enregistrement…' : creating ? 'Créer' : 'Enregistrer' }}
              </button>
            </div>
          </div>
        </footer>
      </div>
    </Transition>
  </Teleport>
</template>
