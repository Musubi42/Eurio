<script setup lang="ts">
// Le haut de `/besoin` : où j'en suis, ce que ça coûte de finir, et la boucle.
//
// Trois blocs jamais repliés — couverture (palier 1), profondeur (palier 2),
// rebuild — puis l'histogramme, puis les deux moitiés TRANCHER / ACHETER.
//
// ⚠️ L'EN-TÊTE NOMME LA BANQUE, et ce n'est pas décoratif : elle a été rebâtie
// DEUX fois pendant la seule session de design du 2026-08-22, et 14 classes ont
// changé de verdict sans qu'un crop soit tranché. Sans cette ligne, deux
// personnes lisent deux vérités et se croient en désaccord.
//
// Aucun chiffre n'est calculé ici : tout vient de `totals` / `parked`.

import { computed } from 'vue'
import BesoinAcheter from './BesoinAcheter.vue'
import type { ClassNeedResponse, ClassNeedRow, Palier } from '../composables/useClassNeed'

const props = defineProps<{
  data: ClassNeedResponse
  rows: ClassNeedRow[]
  palier: Palier
  heavyLocked: boolean
}>()

const emit = defineEmits<{
  (e: 'palier', value: Palier): void
  (e: 'bottleneck', value: 'review' | 'scrape' | 'pleine' | 'tous'): void
}>()

const t = computed(() => props.data.totals)

/** L'histogramme `have` — la « répartition » qu'aucun autre écran ne rend.
 *  Dérivé des lignes servies, pas d'un compte parallèle. */
const histo = computed(() => {
  const buckets = new Map<number, number>()
  for (const r of props.data.classes) {
    buckets.set(r.have, (buckets.get(r.have) ?? 0) + 1)
  }
  const keys = [...buckets.keys()].sort((a, b) => a - b)
  const max = Math.max(...buckets.values(), 1)
  return keys.map((k) => ({
    have: k,
    n: buckets.get(k) ?? 0,
    pct: Math.round(((buckets.get(k) ?? 0) / max) * 100),
    // Le seuil de « pleine » varie par famille (8 ou 5) : on colore le zéro et
    // le plafond, qui eux ne dépendent d'aucune famille.
    kind: k === 0 ? 'zero' : k >= 10 ? 'full' : 'wip',
  }))
})

/** Ce que le palier 1 a encore à portée, et ce qu'il reste à acheter. */
const palier1 = computed(() => {
  const zeros = props.data.classes.filter((r) => r.have === 0)
  const avecCandidats = zeros.filter((r) => r.pending_scoped > 0)
  return {
    total: zeros.length,
    aPortee: avecCandidats.length,
    aScraper: zeros.length - avecCandidats.length,
  }
})

function fmt(n: number): string {
  return n.toLocaleString('fr-FR')
}
</script>

<template>
  <div class="space-y-4">
    <!-- La banque lue. Non négociable : sans elle rien n'est reproductible. -->
    <div class="buildline">
      <span>banque <b>{{ data.build.build_id?.slice(0, 8) ?? '—' }}</b></span>
      <span>·</span>
      <span>{{ data.build.anchors_kind }} / {{ data.build.encoder_version }}</span>
      <span>·</span>
      <span>{{ fmt(data.build.n_anchors) }} ancres</span>
      <span>·</span>
      <span>bâtie le <b>{{ data.build.built_at ?? '—' }}</b></span>
      <span>·</span>
      <span>{{ fmt(t.n_classes) }} classes</span>
    </div>

    <p class="note">
      Cette page compte les <b>exemplaires de la banque DINO</b> (voie B).
      L'entraînement ArcFace compte autrement — voir les cohortes.
    </p>

    <!-- Les trois blocs -->
    <div class="grid gap-3 md:grid-cols-3">
      <button
        type="button" class="panel panel--btn"
        :class="{ 'panel--on': palier === 'couverture' }"
        title="Palier 1 — une classe à zéro exemplaire est aveugle. Depuis l'amorce médoïde, le premier exemplaire vaut ~9× les neuf suivants réunis. Clique pour trier par ce palier."
        @click="emit('palier', 'couverture')"
      >
        <span class="eyebrow">Couverture · palier 1</span>
        <span class="big">{{ fmt(t.coverage) }}<small> / {{ fmt(t.n_classes) }}</small></span>
        <span class="bar"><i :style="{ width: `${(t.coverage / t.n_classes) * 100}%` }" /></span>
        <span class="sub">
          <b>{{ fmt(palier1.total) }} classes à zéro.</b>
          {{ fmt(palier1.aPortee) }} ont un candidat, {{ fmt(palier1.aScraper) }} n'ont rien.
        </span>
      </button>

      <button
        type="button" class="panel panel--btn"
        :class="{ 'panel--on': palier === 'profondeur' }"
        title="Palier 2 — la cible D1 : 8 exemplaires par classe, 5 en émission commune. Conservée, mais explicitement seconde."
        @click="emit('palier', 'profondeur')"
      >
        <span class="eyebrow">Profondeur · palier 2</span>
        <span class="big">{{ fmt(t.sum_need) }}<small> exemplaires</small></span>
        <span class="bar">
          <i :style="{ width: `${(t.sum_reachable / Math.max(t.sum_need, 1)) * 100}%` }" />
        </span>
        <span class="sub">
          <b>{{ fmt(t.sum_reachable) }} à portée</b> de la file ·
          {{ fmt(t.sum_need - t.sum_reachable) }} à aller chercher.
        </span>
      </button>

      <div class="panel">
        <span class="eyebrow">Rebuild · la boucle</span>
        <span class="big">{{ fmt(t.accepted_pending) }}<small> acquis</small></span>
        <span class="sub mt">
          un rebuild poserait <b>{{ fmt(t.rebuild_would_place) }} exemplaires</b>
        </span>
        <span class="sub tiny">
          <code>have</code> ne bouge qu'au <code>build_dino_anchors</code> suivant —
          d'ici là ces crops sont acquis, pas bâtis.
        </span>
      </div>
    </div>

    <!-- L'histogramme : la répartition qu'aucun autre écran ne rend -->
    <div class="panel">
      <span class="eyebrow">Répartition — exemplaires par classe</span>
      <div class="histo">
        <div v-for="b in histo" :key="b.have" :class="b.kind" :title="`${b.n} classes à ${b.have} exemplaire(s)`">
          <b>{{ b.n }}</b>
          <span :style="{ height: `${Math.max(b.pct, 1)}%` }" />
          <em>{{ b.have }}</em>
        </div>
      </div>
      <div class="legend">
        <span><i class="dot dot--zero" />à zéro — le palier 1</span>
        <span><i class="dot dot--wip" />en cours</span>
        <span><i class="dot dot--full" />au plafond</span>
      </div>
    </div>

    <!-- Les deux moitiés -->
    <div class="grid gap-3 md:grid-cols-2">
      <div class="panel">
        <span class="eyebrow">Trancher</span>
        <span class="big">{{ fmt(t.sum_reachable) }}<small> exemplaires à portée</small></span>
        <ul class="sub list">
          <li>{{ fmt(t.by_bottleneck.review ?? 0) }} classes · {{ fmt(t.n_open - data.parked.full_class - data.parked.no_prediction) }} crops en file</li>
          <li>palier 1 : {{ fmt(palier1.aPortee) }} classes ont un candidat</li>
          <li>
            <b>{{ fmt(data.parked.full_class) }} crops parqués</b> (classes à leur cible)
            <span v-if="data.parked.no_prediction">
              · {{ fmt(data.parked.no_prediction) }} sans prédiction
            </span>
            <button type="button" class="linkish" @click="emit('bottleneck', 'pleine')">voir</button>
          </li>
        </ul>
        <button type="button" class="btn" @click="emit('bottleneck', 'review')">
          Les {{ fmt(t.by_bottleneck.review ?? 0) }} classes à trancher
        </button>
      </div>

      <!-- La moitié ACHETER est LOURDE (elle lit `eurio.local.db`), la page ne
           l'est pas : elle se grise seule et le dit. Lot 5. -->
      <BesoinAcheter
        :a-chercher="t.sum_need - t.sum_reachable"
        :n-classes-scrape="t.by_bottleneck.scrape ?? 0"
        :heavy-locked="heavyLocked"
      />
    </div>
  </div>
</template>

<style scoped>
.buildline {
  display: flex; flex-wrap: wrap; gap: 10px; align-items: baseline;
  font-family: var(--font-mono); font-size: 11px; color: var(--ink-400);
  border-bottom: 1px solid var(--surface-3); padding-bottom: 10px;
}
.buildline b { color: var(--ink-700); font-weight: 500; }
.note { font-size: 12px; color: var(--ink-500); max-width: 74ch; }
.note b { color: var(--ink); }

.panel {
  display: flex; flex-direction: column;
  background: var(--surface-1); border: 1px solid var(--surface-3);
  border-radius: 12px; padding: 16px; text-align: left;
}
.panel--btn { cursor: pointer; transition: border-color 120ms; }
.panel--btn:hover { border-color: var(--indigo-300); }
.panel--on { border-color: var(--indigo-700); box-shadow: inset 0 0 0 1px var(--indigo-700); }
.eyebrow {
  font-size: 10px; text-transform: uppercase; letter-spacing: 0.2em;
  color: var(--ink-400); font-weight: 600;
}
.big {
  font-family: var(--font-mono); font-size: 25px; color: var(--ink);
  letter-spacing: -0.02em; margin: 8px 0 4px;
}
.big small { font-size: 13px; color: var(--ink-400); }
.bar {
  display: block; height: 7px; border-radius: 999px;
  background: var(--surface-3); overflow: hidden; margin: 8px 0;
}
.bar i { display: block; height: 100%; background: var(--indigo-700); border-radius: 999px; }
.sub { font-size: 11.5px; color: var(--ink-500); }
.sub b { color: var(--ink); }
.sub.mt { margin-top: 12px; }
.tiny { font-size: 10.5px; margin-top: 6px; }
.list { list-style: none; margin: 8px 0 12px; }
.list li { padding: 1px 0; }

.histo { display: flex; align-items: stretch; gap: 3px; height: 92px; margin: 14px 0 8px; }
.histo > div {
  flex: 1; height: 100%; display: flex; flex-direction: column;
  justify-content: flex-end; align-items: center; gap: 3px;
}
.histo span { display: block; width: 100%; border-radius: 2px 2px 0 0; min-height: 2px; background: var(--indigo-700); }
.histo .zero span { background: var(--danger); }
.histo .full span { background: var(--ink-300); }
.histo b { font-family: var(--font-mono); font-size: 10px; color: var(--ink-500); font-weight: 500; }
.histo em { font-family: var(--font-mono); font-size: 9.5px; color: var(--ink-400); font-style: normal; }
.legend { display: flex; gap: 16px; font-size: 11px; color: var(--ink-500); }
.dot { display: inline-block; width: 8px; height: 8px; border-radius: 2px; margin-right: 5px; vertical-align: -1px; }
.dot--zero { background: var(--danger); }
.dot--wip { background: var(--indigo-700); }
.dot--full { background: var(--ink-300); }

.btn {
  font-size: 12.5px; font-weight: 500; padding: 7px 14px; border-radius: 8px;
  border: 1px solid var(--indigo-700); background: var(--indigo-700);
  color: var(--surface); cursor: pointer; align-self: flex-start;
}
.linkish {
  font-size: 11.5px; color: var(--indigo-700); text-decoration: underline;
  text-underline-offset: 2px; cursor: pointer; background: none; border: none; padding: 0 0 0 4px;
}
code {
  font-family: var(--font-mono); font-size: 10.5px;
  background: var(--surface-2); border-radius: 3px; padding: 0 3px;
}
</style>
