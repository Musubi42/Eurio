<script setup lang="ts">
/**
 * `/coins/eval-images/maquette` — la section « images d'évaluation » sur
 * fixtures, tous ses états à un clic.
 *
 * POURQUOI ELLE EXISTE
 * --------------------
 * R1 (proto-first) ne couvre que l'app Android : le proto est la PWA du
 * collectionneur, et `scene-parity.md` mappe chacune de ses scènes vers une
 * destination Compose. Un écran d'admin n'en a aucune. Mais l'INTENTION de R1
 * vaut ici aussi, et cette page la sert : elle monte le composant DÉFINITIF
 * (`EvalImagesVue`) sur des fixtures. Ce qu'on regarde est ce qu'on livre.
 *
 * Elle sert deux fois : maintenant pour trancher le visuel, et ensuite pour
 * regarder les cas qu'on ne sait pas provoquer en base — une classe sans
 * photos, un `:8042` éteint, une pièce dont AUCUNE photo n'est la sienne.
 *
 * ⛔ HORS NAV, et sans accès réseau. Les gestes (garder / écarter / remap) n'y
 * font rien : on affiche ce qui aurait été envoyé, sans l'envoyer. Un écran de
 * maquette qui écrirait vraiment serait un piège.
 */
import { computed, ref } from 'vue'

import EvalImagesVue from '../components/EvalImagesVue.vue'
import type { EvalDecision, ScanCapture } from '../composables/useScanCorpus'
import { ETATS } from '../fixtures/eval-images.mock'

const choisi = ref(ETATS[0].id)
const etat = computed(() => ETATS.find((e) => e.id === choisi.value) ?? ETATS[0])

/** Dernier geste tenté — la maquette le montre au lieu de l'exécuter. */
const dernierGeste = ref<string | null>(null)

function onDecide(capture: ScanCapture, decision: EvalDecision) {
  dernierGeste.value =
    `eval-decision · ${capture.capture_id} → ${decision ?? 'à juger'} (non envoyé)`
}

function onRemap(capture: ScanCapture, eurioId: string, reason: string) {
  dernierGeste.value =
    `remap · ${capture.capture_id} : ${capture.eurio_id} → ${eurioId}` +
    `${reason ? ` (${reason})` : ''} (non envoyé)`
}
</script>

<template>
  <div>
    <div class="barre">
      <p class="avert">
        <b>Maquette</b> — fixtures, aucune photo réelle, aucun geste envoyé
      </p>
      <div class="onglets">
        <button
          v-for="e in ETATS" :key="e.id" type="button"
          class="onglet" :class="{ actif: e.id === choisi }"
          :title="e.enjeu" @click="choisi = e.id"
        >{{ e.titre }}</button>
      </div>
      <p class="enjeu">{{ etat.enjeu }}</p>
      <p v-if="dernierGeste" class="geste">{{ dernierGeste }}</p>
    </div>

    <div class="corps">
      <EvalImagesVue
        :data="etat.data"
        :loading="etat.loading"
        :error="etat.error"
        :pending="null"
        @decide="onDecide"
        @remap="onRemap"
      />
    </div>
  </div>
</template>

<style scoped>
.barre {
  padding: var(--space-4) var(--space-9);
  background: var(--indigo-800);
  border-bottom: 2px solid var(--gold);
}
.avert {
  font-family: var(--font-mono);
  font-size: 10px;
  text-transform: uppercase;
  letter-spacing: var(--tracking-eyebrow);
  color: var(--gold);
}
.avert b { color: var(--gold-300); }

.onglets { display: flex; flex-wrap: wrap; gap: var(--space-2); margin-top: var(--space-3); }
.onglet {
  font-family: var(--font-ui);
  font-size: var(--text-xs);
  color: var(--indigo-200);
  background: rgba(255, 255, 255, 0.06);
  border: 1px solid rgba(255, 255, 255, 0.12);
  border-radius: 999px;
  padding: 4px 12px;
  cursor: pointer;
}
.onglet:hover { color: #fff; border-color: rgba(255, 255, 255, 0.3); }
.onglet.actif { background: var(--gold); border-color: var(--gold); color: var(--indigo-900); }
.onglet:focus-visible { outline: 2px solid var(--gold-300); outline-offset: 2px; }

.enjeu {
  margin-top: var(--space-3);
  font-family: var(--font-ui);
  font-size: var(--text-xs);
  color: var(--indigo-200);
  max-width: 80ch;
}
.geste {
  margin-top: var(--space-2);
  font-family: var(--font-mono);
  font-size: 10px;
  color: var(--gold-300);
}

.corps { padding: var(--space-6) var(--space-9); }
</style>
