<script setup lang="ts">
// La planche comparative du banc du crop (chantier `juge-du-crop`, L3.3).
//
// « J'aimerais bien observer cette planche de mes propres yeux puisque je pense
// être le meilleur juge de si c'est bon ou pas bon. » — le PO, 2026-08-28.
//
// Ce qu'elle montre, et pourquoi dans cet ordre :
//
//   1. **RE-4 en premier.** C'est le point d'arrêt : si le juge ne sépare pas
//      les crops acceptés des rejetés par l'humain, le juge est faux et tout ce
//      qui suit dans la page ne vaut rien. Le bloc est rendu VERBATIM depuis le
//      run — aucun recalcul, aucune reformulation ;
//   2. **le tableau des bras**, bornes en tête et JAMAIS classées ;
//   3. **les cas, image par image** — parce qu'un taux d'amputation ne se
//      vérifie qu'à l'œil, sur l'image où il a été compté.
//
// Page LOURDE : elle lit `:8042`, qui lit `state/gold_crop/<v>/run_*.json` sur
// la machine du banc. En hébergé, `AppLayout` rend `LocalOnlyNotice` à sa
// place — rien à gater ici.
import { computed, onMounted, ref } from 'vue'
import { useRoute } from 'vue-router'

import CalqueCrop from '../components/CalqueCrop.vue'
import { RUNS_DEMO } from '../fixtures'
import {
  BORNES,
  type CasRun,
  ECART_NON_SIGNIFICATIF,
  type RunBras,
  type RunsBanc,
  classerBras,
  ordonnerBras,
  urlRaw,
  useGoldCropApi,
  useGoldCropRuns,
} from '../composables/useGoldCropApi'

const route = useRoute()
const demo = computed(() => route.query.demo === '1')
const version = ref((route.query.version as string) || 'v1')

const { banc, chargement, erreur, sansRun, chargerRuns } = useGoldCropRuns(version.value)
// Le gel vient du CANONIQUE, pas du run : une planche qui tairait qu'elle juge
// contre un or encore modifiable laisserait croire ses chiffres reproductibles.
const { jeu, charger } = useGoldCropApi(version.value)

const donnees = computed<RunsBanc | null>(() => (demo.value ? RUNS_DEMO : banc.value))
const runs = computed<RunBras[]>(() => donnees.value?.runs ?? [])
const rangs = computed(() => classerBras(runs.value))
const lignes = computed(() =>
  ordonnerBras(runs.value).map((run) => ({
    run,
    rang: rangs.value.find((r) => r.run.bras === run.bras)!,
    borne: BORNES[run.bras] ?? null,
  })),
)

/** Le bras dont le cercle se dessine sur la grille. Un candidat par défaut. */
const brasActif = ref<string>('')
const runActif = computed(
  () => runs.value.find((r) => r.bras === brasActif.value) ?? runs.value[0] ?? null,
)

/** RE-4 : celui du bras affiché s'il en a un, sinon le premier candidat. */
const re4 = computed(
  () => runActif.value?.re4 ?? runs.value.find((r) => r.re4)?.re4 ?? null,
)

const COULEURS = [
  'var(--indigo-500)',
  'var(--danger)',
  'var(--success)',
  'var(--warning)',
  'var(--indigo-800)',
]
function couleurBras(nom: string): string {
  const i = runs.value.findIndex((r) => r.bras === nom)
  return COULEURS[(i < 0 ? 0 : i) % COULEURS.length]
}

const filtreStrate = ref<string | null>(null)
const filtreVerdict = ref<string | null>(null)
const seulementAmputes = ref(false)
const montrerBande = ref(true)

const strates = computed(() =>
  [...new Set((runActif.value?.cas ?? []).map((c) => c.strate_retenue || c.strate))].sort(),
)

const cas = computed<CasRun[]>(() =>
  (runActif.value?.cas ?? []).filter(
    (c) =>
      !c.absent &&
      (!filtreStrate.value || (c.strate_retenue || c.strate) === filtreStrate.value) &&
      (!filtreVerdict.value || c.verdict_humain === filtreVerdict.value) &&
      (!seulementAmputes.value || c.ampute === true),
  ),
)

/** L'ellipse d'or d'un cas — `theta` est en RADIANS dans le run, en degrés au tracé. */
function ellipseDeCas(c: CasRun) {
  return c.gold
    ? { cx: c.gold.cx, cy: c.gold.cy, a: c.gold.a, b: c.gold.b,
        thetaDeg: (c.gold.theta * 180) / Math.PI }
    : null
}

function cercleDe(run: RunBras | null, asset: string) {
  const c = run?.cas.find((x) => x.asset_id === asset)
  return c?.pred ? { ...c.pred, couleur: couleurBras(run!.bras), nom: run!.bras } : null
}

/** Le cas ouvert en grand : tous les bras superposés, une couleur chacun. */
const ouvert = ref<string | null>(null)
const casOuvert = computed(() =>
  ouvert.value ? (runActif.value?.cas ?? []).find((c) => c.asset_id === ouvert.value) ?? null : null,
)
const cerclesOuverts = computed(() =>
  ouvert.value
    ? runs.value.map((r) => cercleDe(r, ouvert.value!)).filter((c) => c !== null)
    : [],
)
const detailsOuverts = computed(() =>
  ouvert.value
    ? runs.value
        .map((r) => ({ bras: r.bras, couleur: couleurBras(r.bras),
                       cas: r.cas.find((c) => c.asset_id === ouvert.value) }))
        .filter((d) => d.cas)
    : [],
)

function pct(x: number | undefined | null): string {
  return x == null || Number.isNaN(x) ? '—' : `${x.toFixed(1)} %`
}
function nb(x: number | undefined | null, d = 3): string {
  return x == null || Number.isNaN(x) ? '—' : x.toFixed(d)
}

onMounted(() => {
  if (demo.value) {
    brasActif.value = RUNS_DEMO.runs.find((r) => !r.borne)?.bras ?? ''
    return
  }
  void charger()
  void chargerRuns().then(() => {
    brasActif.value = runs.value.find((r) => !r.borne)?.bras ?? runs.value[0]?.bras ?? ''
  })
})
</script>

<template>
  <div class="planche">
    <header>
      <div>
        <h1>Planche du banc — {{ version }}</h1>
        <p class="doux">
          L'ellipse d'or contre ce que chaque bras a proposé, image par image.
          Toute grandeur part de l'or ; aucune ne part de ce que la méthode pense
          d'elle-même.
        </p>
      </div>
      <div class="etat">
        <span v-if="demo" class="pastille ouvert">démo — fixtures, aucun banc lu</span>
        <span v-else-if="jeu?.version?.frozen_at" class="pastille gele">
          or gelé le {{ jeu.version.frozen_at.slice(0, 10) }}
        </span>
        <span v-else class="pastille ouvert">or NON gelé — les chiffres bougeront</span>
      </div>
    </header>

    <p v-if="chargement" class="doux">chargement…</p>

    <div v-else-if="sansRun" class="vide">
      <b>Le banc n'a pas encore tourné pour {{ version }}.</b>
      <p class="doux">
        Ce n'est pas une panne : les runs sont des fichiers locaux, produits par le
        harness sur la machine qui exécute le banc.
      </p>
      <pre>cd ml &amp;&amp; python -m bench.gold_crop.harness --out state/gold_crop/{{ version }}</pre>
    </div>

    <p v-else-if="erreur" class="erreur">{{ erreur }}</p>

    <template v-else-if="runs.length">
      <!-- ⛔ RE-4 — le point d'arrêt, avant tout le reste. -->
      <section v-if="re4" class="re4" :class="re4.verdict === 'sépare' ? 'ok' : 'suspens'">
        <div class="re4-titre">
          ⛔ RE-4 — le juge sépare-t-il les acceptés des rejetés ?
          <b>{{ re4.verdict }}</b>
        </div>
        <p v-if="re4.raison" class="doux">{{ re4.raison }}</p>
        <ul v-if="re4.n_accept != null" class="re4-detail">
          <li>{{ re4.n_accept }} acceptés · {{ re4.n_reject }} rejetés</li>
          <li>amputation : {{ pct(re4.amputation_pct_accept) }} chez les acceptés,
            {{ pct(re4.amputation_pct_reject) }} chez les rejetés</li>
          <li>Fisher exact p = {{ nb(re4.fisher_p, 4) }}</li>
        </ul>
        <p class="doux">
          Si le juge ne les sépare pas, il est faux et le banc s'arrête là — quelle
          que soit sa cohérence géométrique.
        </p>
      </section>

      <section class="tableau">
        <table>
          <thead>
            <tr>
              <th>bras</th><th>rang</th><th>amput.</th><th>marge &lt; 2 %</th>
              <th>amp C2</th><th>BIoU méd.</th><th>BIoU p10</th><th>n</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="l in lignes" :key="l.run.bras" :class="{ borne: !!l.borne }">
              <td>
                <code>{{ l.run.bras }}</code>
                <span v-if="l.borne" class="badge borne-badge">borne · {{ l.borne }}</span>
              </td>
              <td class="rang">
                <span v-if="l.borne" :title="'une borne ne se classe pas : elle borne'">—</span>
                <template v-else-if="l.rang.rang">
                  {{ l.rang.rang }}
                  <span
                    v-if="l.rang.nonDepartages.length" class="badge re7"
                    :title="`RE-7 : moins de ${ECART_NON_SIGNIFICATIF} points d'amputation d'écart sur 60 images ne départagent pas`"
                  >non départagé avec {{ l.rang.nonDepartages.join(', ') }}</span>
                </template>
                <span v-else>—</span>
              </td>
              <td class="chiffre"><b>{{ pct(l.run.resume.amputation_pct) }}</b></td>
              <td class="chiffre">{{ pct(l.run.resume.marge_promise_ko_pct) }}</td>
              <td class="chiffre">{{ pct(l.run.resume.amp_C2_pct) }}</td>
              <td class="chiffre">{{ nb(l.run.resume.biou_med) }}</td>
              <td class="chiffre">{{ nb(l.run.resume.biou_p10) }}</td>
              <td class="chiffre">{{ l.run.resume.n }}</td>
            </tr>
          </tbody>
        </table>
        <p class="doux note">
          Les bornes ne se classent pas : <code>gold_replay</code> est le plafond du
          format, <code>human_2nd_pass</code> le plancher de crédit (le bruit de la
          main qui a tracé l'or). Deux bras à moins de
          {{ ECART_NON_SIGNIFICATIF }} points d'amputation d'écart ne sont pas
          départagés — RE-7.
        </p>
      </section>

      <section class="filtres">
        <label>
          bras tracé
          <select v-model="brasActif">
            <option v-for="r in runs" :key="r.bras" :value="r.bras">{{ r.bras }}</option>
          </select>
        </label>
        <span class="sep"></span>
        <button :class="{ actif: !filtreStrate }" @click="filtreStrate = null">
          toutes strates
        </button>
        <button
          v-for="s in strates" :key="s"
          :class="{ actif: filtreStrate === s }" @click="filtreStrate = s"
        >{{ s }}</button>
        <span class="sep"></span>
        <button :class="{ actif: !filtreVerdict }" @click="filtreVerdict = null">
          tous verdicts
        </button>
        <button :class="{ actif: filtreVerdict === 'accept' }" @click="filtreVerdict = 'accept'">
          acceptés
        </button>
        <button :class="{ actif: filtreVerdict === 'reject' }" @click="filtreVerdict = 'reject'">
          rejetés
        </button>
        <span class="sep"></span>
        <label class="bascule">
          <input v-model="seulementAmputes" type="checkbox" /> seulement les amputés
        </label>
        <label class="bascule">
          <input v-model="montrerBande" type="checkbox" /> bande du juge (0,08·a)
        </label>
        <span class="doux compte">{{ cas.length }} cas</span>
      </section>

      <section class="grille">
        <figure
          v-for="c in cas" :key="c.asset_id" class="cas"
          :class="{ ampute: c.ampute }" @click="ouvert = c.asset_id"
        >
          <CalqueCrop
            :url="urlRaw(c)" :alt="c.asset_id"
            :largeur="c.largeur" :hauteur="c.hauteur"
            :ellipse="ellipseDeCas(c)"
            :cercles="cercleDe(runActif, c.asset_id) ? [cercleDe(runActif, c.asset_id)!] : []"
            :montrer-bande="montrerBande" bande-exterieure
            vide="pas d'or"
          />
          <figcaption>
            <span class="strate">{{ c.strate_retenue || c.strate }}</span>
            <span :class="['verdict', c.verdict_humain === 'accept' ? 'acc' : 'rej']">
              {{ c.verdict_humain === 'accept' ? 'accepté' : 'rejeté' }}
            </span>
            <span
              :class="['badge', c.ampute ? 'mauvais' : 'bon']"
              :title="'C1 sur la région retenue, seuil 0 : a-t-on perdu des pixels de la pièce ?'"
            >{{ c.ampute ? 'amputé' : 'entier' }}</span>
            <span class="doux" :title="'marge minimale, en fraction du grand axe'">
              marge {{ nb(c.C1_marge_min_frac) }}
            </span>
            <span class="doux">BIoU {{ nb(c.boundary_iou) }}</span>
          </figcaption>
        </figure>
      </section>

      <p v-if="!cas.length" class="doux">Aucun cas sous ces filtres.</p>

      <!-- Le cas en grand : tous les bras superposés. -->
      <div v-if="casOuvert" class="loupe" @click.self="ouvert = null">
        <div class="loupe-boite">
          <header class="loupe-tete">
            <code>{{ casOuvert.asset_id }}</code>
            <button class="fermer" @click="ouvert = null">fermer</button>
          </header>
          <CalqueCrop
            :url="urlRaw(casOuvert)" :alt="casOuvert.asset_id"
            :largeur="casOuvert.largeur" :hauteur="casOuvert.hauteur"
            :ellipse="ellipseDeCas(casOuvert)" :cercles="cerclesOuverts"
            :montrer-bande="montrerBande" bande-exterieure
          />
          <ul class="legende">
            <li class="or"><i></i> ellipse d'or (tracée à la main)</li>
            <li v-for="d in detailsOuverts" :key="d.bras">
              <i :style="{ background: d.couleur }"></i>
              <code>{{ d.bras }}</code>
              <span :class="['badge', d.cas!.ampute ? 'mauvais' : 'bon']">
                {{ d.cas!.ampute ? 'amputé' : 'entier' }}
              </span>
              <span class="doux">
                marge {{ nb(d.cas!.C1_marge_min_frac) }} · BIoU {{ nb(d.cas!.boundary_iou) }}
                · IoU {{ nb(d.cas!.mask_iou) }}
              </span>
            </li>
          </ul>
        </div>
      </div>
    </template>
  </div>
</template>

<style scoped>
/* Thème CLAIR, tokens de `shared/tokens.css` uniquement (R2). */
.planche { padding: 1.5rem; max-width: 1400px; margin: 0 auto; color: var(--ink-700); }
header { display: flex; justify-content: space-between; align-items: flex-start; gap: 1rem; }
h1 { font-size: var(--text-lg); margin: 0 0 0.2rem; font-family: var(--font-display); }
.doux { color: var(--ink-500); }
.erreur { color: var(--danger); }
.pastille { display: inline-block; white-space: nowrap; padding: 0.15rem 0.6rem;
            border-radius: 99px; font-size: var(--text-xs); font-weight: 600; }
.gele { background: var(--indigo-100); color: var(--indigo-700); }
.ouvert { background: var(--gold-100); color: var(--gold-700); }
.vide { margin-top: 2rem; padding: 1.25rem; border: 1px dashed var(--surface-3);
        border-radius: 10px; background: var(--surface-1); }
.vide pre { margin: 0.6rem 0 0; padding: 0.6rem 0.75rem; background: var(--surface-3);
            color: var(--ink-700); border-radius: 6px; overflow-x: auto;
            font-family: var(--font-mono); font-size: var(--text-xs); }
.re4 { margin: 1.25rem 0; padding: 0.9rem 1rem; border-radius: 10px;
       border: 1px solid var(--surface-3); background: var(--surface-1); }
.re4.ok { border-color: var(--success); background: var(--success-soft); }
.re4.suspens { border-color: var(--warning); background: var(--warning-soft); }
.re4-titre { font-weight: 600; display: flex; gap: 0.5rem; flex-wrap: wrap; }
.re4-detail { margin: 0.4rem 0; padding-left: 1.1rem; font-size: var(--text-sm); }
.tableau { overflow-x: auto; }
table { width: 100%; border-collapse: collapse; font-size: var(--text-sm); }
th, td { text-align: left; padding: 0.35rem 0.6rem; border-bottom: 1px solid var(--surface-3); }
th { font-size: var(--text-xs); color: var(--ink-500); font-weight: 600; }
.chiffre { text-align: right; font-variant-numeric: tabular-nums; }
tr.borne { background: var(--surface-2); }
.badge { display: inline-block; margin-left: 0.35rem; padding: 0 0.4rem;
         border-radius: 99px; font-size: var(--text-xs); font-weight: 600; }
.borne-badge { background: var(--indigo-100); color: var(--indigo-700); }
.re7 { background: var(--warning-soft); color: var(--warning); }
.bon { background: var(--success-soft); color: var(--success); }
.mauvais { background: var(--danger-soft); color: var(--danger); }
.note { font-size: var(--text-xs); margin-top: 0.5rem; }
.filtres { display: flex; gap: 0.4rem; align-items: center; flex-wrap: wrap;
           margin: 1.25rem 0 1rem; font-size: var(--text-xs); }
.filtres button, .filtres select { font: inherit; font-size: var(--text-xs);
                  padding: 0.25rem 0.6rem; border: 1px solid var(--surface-3);
                  border-radius: 6px; background: var(--surface); color: var(--ink-700);
                  cursor: pointer; }
.filtres button.actif { background: var(--indigo-600); border-color: var(--indigo-600);
                        color: #fff; font-weight: 600; }
.sep { width: 1px; height: 1.2rem; background: var(--surface-3); margin: 0 0.3rem; }
.bascule { display: flex; gap: 0.35rem; align-items: center; cursor: pointer;
           color: var(--ink-500); }
.compte { margin-left: auto; }
.grille { display: grid; gap: 0.75rem;
          grid-template-columns: repeat(auto-fill, minmax(190px, 1fr)); }
.cas { margin: 0; background: var(--surface-1); border: 1px solid var(--surface-3);
       border-radius: 10px; overflow: hidden; cursor: zoom-in; }
.cas.ampute { border-color: var(--danger); }
figcaption { display: flex; gap: 0.4rem; align-items: center; flex-wrap: wrap;
             padding: 0.4rem 0.55rem; font-size: var(--text-xs); }
.verdict { padding: 0 0.45rem; border-radius: 99px; font-weight: 600; }
.acc { background: var(--success-soft); color: var(--success); }
.rej { background: var(--danger-soft); color: var(--danger); }
.loupe { position: fixed; inset: 0; z-index: var(--z-modal); background: rgba(0, 0, 0, 0.6);
         display: grid; place-items: center; padding: 1rem; }
.loupe-boite { background: var(--surface); border-radius: 12px; padding: 0.9rem;
               max-width: min(900px, 92vw); max-height: 92vh; overflow: auto; }
.loupe-tete { display: flex; justify-content: space-between; align-items: center;
              margin-bottom: 0.5rem; }
.fermer { font: inherit; font-size: var(--text-xs); padding: 0.2rem 0.6rem;
          border: 1px solid var(--surface-3); border-radius: 6px; background: var(--surface);
          color: var(--ink-700); cursor: pointer; }
.legende { list-style: none; margin: 0.6rem 0 0; padding: 0; font-size: var(--text-xs); }
.legende li { display: flex; gap: 0.4rem; align-items: center; padding: 0.15rem 0; }
.legende i { width: 12px; height: 12px; border-radius: 3px; display: inline-block; }
.legende .or i { background: #ffd166; }
</style>
