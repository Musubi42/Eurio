<script setup lang="ts">
/**
 * Section « Références Dino » (improvement-loop B) — page coin-detail.
 *
 * La banque de suggestions ne garde plus 1 ancre canonique/classe : par classe,
 * le canonique + jusqu'à ~10 vrais crops choisis pour la DIVERSITÉ d'apparence
 * (farthest-point sampling). Cette section montre CE QUI SERT au calcul Dino
 * (suggestions de réassignation + détection d'intrus) et laisse l'humain
 * épingler (garder à coup sûr) ou bannir (jamais) un crop. Les overrides
 * s'appliquent au PROCHAIN build d'ancres — la banque n'est pas rebuild live.
 */
import { HAS_LOCAL_ML_API } from '@/shared/config/deploy-target'
import {
  fetchDinoReferences,
  setDinoReference,
  type DinoReferenceEntry,
  type DinoReferencesResponse,
} from '../composables/useCoinAssets'
import { Ban, Loader2, Pin, RotateCcw, Sparkles } from 'lucide-vue-next'
import { onMounted, ref, watch } from 'vue'

const props = defineProps<{ eurioId: string }>()

const data = ref<DinoReferencesResponse | null>(null)
const loading = ref(false)
const error = ref<string | null>(null)
const pending = ref<string | null>(null) // asset_id en cours d'action

async function load() {
  if (!HAS_LOCAL_ML_API) return
  loading.value = true
  error.value = null
  try {
    data.value = await fetchDinoReferences(props.eurioId)
  } catch (e) {
    error.value = e instanceof Error ? e.message : String(e)
  } finally {
    loading.value = false
  }
}

onMounted(load)
watch(() => props.eurioId, load)

async function act(entry: DinoReferenceEntry, action: 'pin' | 'exclude' | 'clear') {
  if (!entry.asset_id || pending.value) return
  pending.value = entry.asset_id
  try {
    await setDinoReference(entry.asset_id, action)
    await load()
  } catch (e) {
    error.value = e instanceof Error ? e.message : String(e)
  } finally {
    pending.value = null
  }
}

function methodLabel(m: string): string {
  return m === 'canonical' ? 'canonique Numista'
    : m === 'manual_pin' ? 'épinglé'
      : m === 'manual_exclude' ? 'banni'
        : 'exemplaire (auto)'
}
function methodColor(m: string): string {
  return m === 'canonical' ? 'var(--indigo-700)'
    : m === 'manual_pin' ? 'var(--success)'
      : m === 'manual_exclude' ? 'var(--danger)'
        : 'var(--ink-400)'
}
</script>

<template>
  <section v-if="HAS_LOCAL_ML_API" class="mt-6">
    <header class="mb-2 flex items-center gap-2">
      <Sparkles class="h-4 w-4" style="color: var(--indigo-700);" />
      <h3 class="font-display text-sm italic font-semibold" style="color: var(--indigo-700);">
        Références Dino
      </h3>
      <span
        v-if="data && !data.never_built"
        class="text-xs" style="color: var(--ink-400);"
        title="Crops qui servent de référence à la classe pour les suggestions Dino et la détection d'intrus. Le canonique + des exemplaires réels choisis pour la diversité d'apparence (lumière/tilt/usure)."
      >{{ data.entries.filter((e) => e.method !== 'manual_exclude').length }} exemplaires
        · classe <span class="font-mono">{{ data.class_id }}</span></span>
    </header>

    <div v-if="loading" class="flex items-center gap-2 text-xs" style="color: var(--ink-400);">
      <Loader2 class="h-3.5 w-3.5 animate-spin" /> Chargement…
    </div>
    <p v-else-if="error" class="text-xs" style="color: var(--danger);">{{ error }}</p>

    <p
      v-else-if="data?.never_built"
      class="rounded-md border px-3 py-2 text-xs"
      style="border-color: var(--surface-3); color: var(--ink-400); background: var(--surface-1);"
    >
      Banque multi-exemplaires pas encore bâtie pour cette classe — lance
      <span class="font-mono" style="color: var(--ink-200);">go-task ml:dino-anchors:build -- --kind 2eur_all --force</span>
      pour la générer (canonique + exemplaires FPS).
    </p>

    <template v-else-if="data">
      <p class="mb-2 text-[11px]" style="color: var(--ink-400);">
        Ce qui sert au calcul Dino. <span style="color: var(--success);">Épingler</span> =
        toujours garder ; <span style="color: var(--danger);">bannir</span> = jamais.
        Effet au prochain build d'ancres.
      </p>
      <div class="flex flex-wrap gap-2.5">
        <div
          v-for="e in data.entries"
          :key="(e.asset_id ?? 'canonical') + e.method"
          class="relative w-28 overflow-hidden rounded-md border"
          :style="{
            borderColor: methodColor(e.method),
            opacity: e.method === 'manual_exclude' ? 0.5 : 1,
          }"
        >
          <div class="relative h-28 w-28" style="background: var(--surface-1);">
            <img
              v-if="e.file_url"
              :src="e.file_url"
              loading="lazy"
              class="h-full w-full object-cover"
              :style="{ filter: e.method === 'manual_exclude' ? 'grayscale(1)' : 'none' }"
            />
            <div
              v-else
              class="flex h-full w-full items-center justify-center text-center text-[10px] font-medium"
              style="color: var(--indigo-700);"
            >avers<br />Numista</div>
            <span
              v-if="e.rank != null"
              class="absolute left-0 top-0 rounded-br-md px-1 text-[10px] font-semibold text-white"
              style="background: rgba(14,14,31,.65);"
            >#{{ e.rank }}</span>
          </div>
          <div class="px-1.5 py-1">
            <p class="text-[10px] font-medium" :style="{ color: methodColor(e.method) }">
              {{ methodLabel(e.method) }}
            </p>
            <p
              v-if="e.selected_sim != null"
              class="text-[10px]" style="color: var(--ink-400);"
              title="Similarité au set déjà retenu au moment du choix (basse = plus diversifiant)"
            >sim {{ (e.selected_sim).toFixed(2) }}</p>

            <!-- Actions (jamais sur le canonique) -->
            <div v-if="e.asset_id" class="mt-1 flex flex-wrap gap-1">
              <template v-if="e.method === 'manual_pin'">
                <button type="button" class="ref-btn" :disabled="pending === e.asset_id"
                        title="Retirer l'épingle (retour au choix auto)" @click="act(e, 'clear')">
                  <RotateCcw class="h-3 w-3" /> retirer
                </button>
              </template>
              <template v-else-if="e.method === 'manual_exclude'">
                <button type="button" class="ref-btn" :disabled="pending === e.asset_id"
                        title="Réintégrer (retour au choix auto)" @click="act(e, 'clear')">
                  <RotateCcw class="h-3 w-3" /> réintégrer
                </button>
              </template>
              <template v-else>
                <button type="button" class="ref-btn ref-btn--pin" :disabled="pending === e.asset_id"
                        title="Épingler : toujours garder comme référence" @click="act(e, 'pin')">
                  <Pin class="h-3 w-3" /> épingler
                </button>
                <button type="button" class="ref-btn ref-btn--ban" :disabled="pending === e.asset_id"
                        title="Bannir : jamais utiliser comme référence" @click="act(e, 'exclude')">
                  <Ban class="h-3 w-3" /> bannir
                </button>
              </template>
            </div>
          </div>
        </div>
      </div>
    </template>
  </section>
</template>

<style scoped>
.ref-btn {
  display: inline-flex;
  align-items: center;
  gap: 3px;
  padding: 2px 5px;
  border: 1px solid var(--surface-3);
  border-radius: 4px;
  font-size: 10px;
  color: var(--ink-500);
  background: var(--surface);
}
.ref-btn:disabled { opacity: 0.5; }
.ref-btn--pin:hover { border-color: var(--success); color: var(--success); }
.ref-btn--ban:hover { border-color: var(--danger); color: var(--danger); }
</style>
