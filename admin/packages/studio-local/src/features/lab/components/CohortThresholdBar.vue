<script setup lang="ts">
// Le plancher, affiché avec sa PROVENANCE et réglable ici.
//
// Trois notions portent le mot « assez » et ne doivent jamais fusionner :
//   · refus dur (m_per_class) — technique, imposé par la composition d'un batch
//   · plancher (min_real)     — choix produit, celui qu'on fait bouger
//   · cible (training_target) — paramètre de bake, après augmentation
//
// Deux choses que cet écran doit dire, et qu'aucun écran ne disait :
//
// 1. QUAND LE PLANCHER MONTE, des classes prêtes redeviennent incomplètes. Ce
//    n'est pas une régression, c'est la règle qui a changé — l'historique du
//    back le nomme, et on l'affiche ici plutôt que de laisser douze classes
//    repasser au rouge sans explication.
// 2. LE PRÉFLIGHT MET JUSQU'À 2 MIN À SUIVRE. On écrit au canonique (effet
//    immédiat sur cette page), mais le préflight tourne en local sur une
//    réplique rafraîchie toutes les 120 s. Tant qu'ils divergent, on le dit.
//
// Cf. docs/work-in-progress/refacto-page-cohorte/DECISIONS.md §D1/§D5

import { computed, ref } from 'vue'
import { setCohortThreshold, setGlobalThreshold } from '@/features/lab/composables/useLabApi'
import type { ResolvedThresholds, ThresholdKey, ThresholdState } from '@/features/lab/types'

const props = defineProps<{
  cohortId: string
  thresholds: ResolvedThresholds
  state: ThresholdState | null
  /** Non-null quand le préflight local n'a pas encore vu le nouveau seuil. */
  lag: { keys: ThresholdKey[]; local: ResolvedThresholds; canonical: ResolvedThresholds } | null
}>()

const emit = defineEmits<{ (e: 'changed'): void }>()

const LABELS: Record<ThresholdKey, { name: string; what: string }> = {
  min_real: {
    name: 'Plancher',
    what: 'photos réelles validées sous lesquelles une classe est trop pauvre',
  },
  m_per_class: {
    name: 'Refus dur',
    // Ce n'est pas QUE un seuil de refus : la valeur est gelée dans l'itération
    // et passée telle quelle au MPerClassSampler du run (pipeline.py). La
    // changer change donc la composition des batches, pas seulement le verdict.
    what: "sous ce nombre de sources, l'entraînement est refusé — et c'est aussi "
      + 'le nombre d’exemplaires par classe dans un batch du run',
  },
  training_target: {
    name: 'Cible',
    what: "images par classe APRÈS augmentation — le facteur en est déduit",
  },
}

const ORIGIN: Record<string, string> = {
  code: 'défaut du code — personne ne l’a réglé',
  global: 'défaut global',
  cohort: 'réglage de cette cohorte',
  class: 'réglage de cette classe',
}

/** Un 404 ici ne veut pas dire « ça ne marche pas » : il veut dire que le
 *  canonique n'a pas encore la migration 0006 et ses routes. Le dire, plutôt que
 *  de renvoyer un message HTTP brut qu'on relira comme une panne. */
function explain(e: unknown): string {
  const msg = (e as Error).message ?? String(e)
  if (msg.includes('404')) {
    return "Le serveur canonique n'expose pas encore le réglage des seuils : il "
      + 'faut y déployer la migration 0006 et les routes /lab/thresholds. En '
      + "attendant, la valeur affichée est celle du code — elle est juste, "
      + 'simplement pas réglable.'
  }
  if (msg.includes('403')) {
    return 'Ce jeton n’a pas le droit `training:run` — déplacer le plancher '
      + 'redéfinit « entraînable » pour toutes les cohortes, il est réservé aux '
      + 'rôles owner et admin.'
  }
  return msg
}

const open = ref(false)
const editing = ref<ThresholdKey | null>(null)
const draft = ref('')
const scope = ref<'cohort' | 'global'>('cohort')
const busy = ref(false)
const error = ref<string | null>(null)

function startEdit(key: ThresholdKey) {
  editing.value = key
  draft.value = String(props.thresholds[key])
  // Par défaut on surcharge la cohorte : régler le global depuis une page de
  // cohorte doit rester un geste explicite, il touche toutes les autres.
  scope.value = 'cohort'
  error.value = null
}

/** Miroir de store/thresholds.BOUNDS. Repli utilisé quand le canonique n'a pas
 *  répondu : un [1, 5000] uniforme laissait saisir m_per_class=1 (le serveur
 *  refuse à 2) et cible=9999, pour ne récolter qu'un 400 relayé brut. */
const FALLBACK_BOUNDS: Record<ThresholdKey, [number, number]> = {
  m_per_class: [2, 64],
  min_real: [1, 5000],
  training_target: [10, 5000],
}
const bounds = computed<[number, number]>(() =>
  editing.value
    ? (props.state?.bounds?.[editing.value] ?? FALLBACK_BOUNDS[editing.value])
    : [1, 5000],
)

async function save() {
  const key = editing.value
  if (!key) return
  const value = Number.parseInt(draft.value, 10)
  if (!Number.isFinite(value)) {
    error.value = 'Donne un nombre entier.'
    return
  }
  busy.value = true
  error.value = null
  try {
    if (scope.value === 'global') await setGlobalThreshold(key, value)
    else await setCohortThreshold(props.cohortId, key, value)
    editing.value = null
    emit('changed')
  } catch (e) {
    error.value = explain(e)
  } finally {
    busy.value = false
  }
}

/** Rendre la cohorte à la règle générale (≠ figer la valeur actuelle). */
async function release(key: ThresholdKey) {
  busy.value = true
  error.value = null
  try {
    await setCohortThreshold(props.cohortId, key, null)
    editing.value = null
    emit('changed')
  } catch (e) {
    error.value = explain(e)
  } finally {
    busy.value = false
  }
}

/** Les changements de plancher, les plus récents d'abord — ceux qui expliquent
 *  qu'une classe soit repassée sous la ligne. */
const floorChanges = computed(
  () => (props.state?.history ?? []).filter(h => h.key === 'min_real').slice(0, 5),
)
function when(iso: string): string {
  const d = new Date(iso.replace(' ', 'T') + (iso.endsWith('Z') ? '' : 'Z'))
  return Number.isNaN(d.getTime())
    ? iso
    : d.toLocaleDateString('fr-FR', { day: 'numeric', month: 'long' })
}
/**
 * Le changement de plancher à ANNONCER — pas simplement le dernier connu.
 *
 * Deux filtres, chacun pour un mensonge évité :
 *  · la portée. L'historique mêle le global et la cohorte. Si cette cohorte a
 *    sa propre surcharge, un changement du défaut global ne déplace PAS son
 *    plancher : l'annoncer ferait croire à des classes retombées sous la ligne.
 *  · la fraîcheur. Une hausse d'il y a trois mois n'explique pas ce qu'on voit
 *    aujourd'hui ; la présenter au présent est faux. Fenêtre : 7 jours.
 */
const FRESH_DAYS = 7
const lastFloorChange = computed(() => {
  const from = props.thresholds.source.min_real
  const h = floorChanges.value.find(
    x => (x.scope === 'cohort' && from === 'cohort') || (x.scope === 'global' && from === 'global'),
  )
  if (!h || h.old_value === null) return null
  const at = new Date(h.changed_at.replace(' ', 'T') + (h.changed_at.endsWith('Z') ? '' : 'Z'))
  if (Number.isNaN(at.getTime())) return null
  const days = (Date.now() - at.getTime()) / 86_400_000
  return days <= FRESH_DAYS ? h : null
})
</script>

<template>
  <div class="tb">
    <div class="tb__head">
      <button type="button" class="tb__toggle" @click="open = !open">
        <span class="tb__key">Plancher</span>
        <b class="tb__val">{{ thresholds.min_real }}</b>
        <span class="tb__src">{{ ORIGIN[thresholds.source.min_real] }}</span>
        <span class="tb__chev">{{ open ? '▴' : '▾' }}</span>
      </button>

      <!-- La hausse d'un plancher fait « régresser » des classes prêtes. Le
           dire, c'est la différence entre une règle qui change et une panne. -->
      <p v-if="lastFloorChange" class="tb__news">
        Le plancher est passé de <b>{{ lastFloorChange.old_value }}</b> à
        <b>{{ lastFloorChange.new_value }}</b> le {{ when(lastFloorChange.changed_at) }} —
        les classes qui franchissaient l'ancien ne franchissent plus le nouveau.
      </p>

      <p v-if="lag" class="tb__lag">
        ⚠ Le contrôle avant entraînement tourne encore avec
        <template v-for="(k, i) in lag.keys" :key="k">
          <template v-if="i > 0">, </template>
          {{ LABELS[k].name.toLowerCase() }} {{ lag.local[k] }}
        </template>
        — il lit une copie locale rafraîchie toutes les 120 s. Son verdict suivra
        d'ici deux minutes ; ce n'est pas un blocage.
      </p>
    </div>

    <div v-if="open" class="tb__body">
      <p class="tb__intro">
        Trois réglages différents, souvent confondus. Ils vivent au serveur : les
        changer ne demande aucun redéploiement, et la valeur utilisée par un
        entraînement est <b>gelée dans son itération</b> — les runs déjà lancés ne
        bougent pas.
      </p>

      <div v-for="key in (['min_real', 'm_per_class', 'training_target'] as ThresholdKey[])" :key="key" class="row">
        <div class="row__id">
          <div class="row__name">{{ LABELS[key].name }}</div>
          <div class="row__what">{{ LABELS[key].what }}</div>
        </div>

        <div class="row__val">
          <b>{{ thresholds[key] }}</b>
          <span class="row__src">{{ ORIGIN[thresholds.source[key]] }}</span>
        </div>

        <div v-if="editing === key" class="row__edit">
          <input
            v-model="draft"
            class="in"
            type="number"
            :min="bounds[0]"
            :max="bounds[1]"
            :aria-label="`Nouvelle valeur pour ${LABELS[key].name}`"
          />
          <select v-model="scope" class="in in--sel" aria-label="Portée du réglage">
            <option value="cohort">pour cette cohorte</option>
            <option value="global">pour toutes les cohortes</option>
          </select>
          <button type="button" class="btn btn--go" :disabled="busy" @click="save()">
            Enregistrer
          </button>
          <button type="button" class="btn" :disabled="busy" @click="editing = null">
            Annuler
          </button>
        </div>
        <div v-else class="row__edit">
          <button type="button" class="btn" @click="startEdit(key)">Régler</button>
          <button
            v-if="state?.cohort?.[key] !== undefined"
            type="button"
            class="btn btn--ghost"
            :disabled="busy"
            title="Retirer la surcharge : la cohorte suivra le défaut global, y compris s'il rebouge"
            @click="release(key)"
          >
            Suivre le global
          </button>
        </div>
      </div>

      <p v-if="error" class="tb__err">{{ error }}</p>

      <div v-if="floorChanges.length > 0" class="hist">
        <div class="hist__t">Changements de plancher</div>
        <ul>
          <li v-for="(h, i) in floorChanges" :key="i">
            <span class="hist__when">{{ when(h.changed_at) }}</span>
            {{ h.old_value ?? '—' }} → {{ h.new_value ?? 'retiré' }}
            <span class="hist__scope">{{ h.scope === 'global' ? 'global' : 'cette cohorte' }}</span>
            <span v-if="h.note" class="hist__note">« {{ h.note }} »</span>
          </li>
        </ul>
      </div>
    </div>
  </div>
</template>

<style scoped>
.tb { margin: 0 0 18px; }
.tb__head { display: flex; flex-wrap: wrap; align-items: center; gap: 10px 16px; }
.tb__toggle {
  display: inline-flex;
  align-items: baseline;
  gap: 8px;
  background: none;
  border: 1px solid var(--surface-3);
  border-radius: 20px;
  padding: 5px 13px;
  font: inherit;
  cursor: pointer;
}
.tb__toggle:hover { background: var(--surface-1); }
.tb__toggle:focus-visible { outline: 2px solid var(--gold); outline-offset: 1px; }
.tb__key {
  font-family: var(--font-mono);
  font-size: 9.5px;
  text-transform: uppercase;
  letter-spacing: var(--tracking-eyebrow);
  color: var(--ink-400);
}
.tb__val { font-family: var(--font-display); font-size: 17px; color: var(--gold-700); }
.tb__src { font-size: 11px; color: var(--ink-400); }
.tb__chev { font-size: 10px; color: var(--ink-300); }

.tb__news { margin: 0; font-size: 12px; color: var(--ink-700); max-width: 62ch; }
.tb__lag {
  margin: 0;
  font-size: 12px;
  color: var(--warning);
  max-width: 62ch;
}

.tb__body {
  margin-top: 14px;
  border: 1px solid var(--surface-3);
  border-radius: 10px;
  padding: 15px 17px;
  background: var(--surface);
}
.tb__intro { margin: 0 0 14px; font-size: 12.5px; color: var(--ink-500); max-width: 76ch; }

.row {
  display: grid;
  grid-template-columns: minmax(0, 1fr) 190px auto;
  gap: 14px;
  align-items: center;
  padding: 10px 0;
  border-top: 1px solid var(--surface-2);
}
.row__name { font-size: 13px; font-weight: 600; }
.row__what { font-size: 11.5px; color: var(--ink-400); }
.row__val { display: flex; align-items: baseline; gap: 8px; }
.row__val b { font-family: var(--font-display); font-size: 20px; }
.row__src { font-family: var(--font-mono); font-size: 9.5px; color: var(--ink-400); }
.row__edit { display: flex; gap: 6px; justify-content: flex-end; flex-wrap: wrap; }

.in {
  font: inherit;
  font-size: 12px;
  padding: 4px 8px;
  border: 1px solid var(--ink-200);
  border-radius: 6px;
  background: var(--surface);
  width: 88px;
}
.in--sel { width: auto; }
.btn {
  font: inherit;
  font-size: 12px;
  padding: 4px 11px;
  border: 1px solid var(--ink-200);
  border-radius: 6px;
  background: var(--surface);
  cursor: pointer;
}
.btn:hover { background: var(--surface-1); }
.btn:disabled { opacity: 0.5; cursor: not-allowed; }
.btn--go { background: var(--indigo-700); border-color: var(--indigo-700); color: white; }
.btn--go:hover { background: var(--indigo-800); }
.btn--ghost { border-style: dashed; color: var(--ink-500); }

.tb__err { margin: 10px 0 0; font-size: 12px; color: var(--danger); }

.hist { margin-top: 16px; border-top: 1px solid var(--surface-2); padding-top: 12px; }
.hist__t {
  font-family: var(--font-mono);
  font-size: 9.5px;
  text-transform: uppercase;
  letter-spacing: var(--tracking-eyebrow);
  color: var(--ink-400);
  margin-bottom: 7px;
}
.hist ul { list-style: none; margin: 0; padding: 0; font-size: 12px; }
.hist li { padding: 3px 0; color: var(--ink-700); }
.hist__when { font-family: var(--font-mono); font-size: 10px; color: var(--ink-400); margin-right: 8px; }
.hist__scope { font-family: var(--font-mono); font-size: 10px; color: var(--ink-400); margin-left: 8px; }
.hist__note { color: var(--ink-500); font-style: italic; margin-left: 8px; }

@media (max-width: 820px) {
  .row { grid-template-columns: 1fr; gap: 6px; }
  .row__edit { justify-content: flex-start; }
}
</style>
