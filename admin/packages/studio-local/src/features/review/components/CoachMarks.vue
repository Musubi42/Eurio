<script setup lang="ts">
/**
 * Les coach marks — des repères POSÉS SUR les boutons, pas une page d'aide.
 *
 * POURQUOI ILS VIVENT DANS L'ÉCRAN DE REVIEW (`ACCUEIL-AMI.md` §7)
 * ----------------------------------------------------------------
 * L'aide se range à l'endroit où on en a besoin. « Ça, c'est pour recadrer ;
 * ça, pour chercher une pièce à la main ; ça, pour passer » sont des repères sur
 * des boutons : hors de l'écran qui les porte, ils ne veulent rien dire. Le
 * métier — qu'est-ce qui fait qu'une image sert — s'apprend au calme, et vit
 * donc sur l'accueil (`PanneauAide`).
 *
 * ⛔ AUCUN TOUR IMPOSÉ AU PREMIER PASSAGE. Ils ne se déclenchent que sur clic de
 * « Comment ça marche », et c'est ce bouton qui les rend « toujours
 * accessibles » — sans faire traverser un carrousel à quelqu'un qui n'en veut
 * pas. Pas de `localStorage`, pas de « déjà vu » : rien à retenir, donc rien à
 * se tromper de retenir.
 *
 * ⛔ UNE ÉTAPE SANS CIBLE À L'ÉCRAN EST SAUTÉE, jamais montrée dans le vide. Les
 * gestes qui restent locaux sont MASQUÉS pour un ami (D11) : pointer un bouton
 * absent lui promettrait un geste qu'il ne peut pas faire — exactement le bruit
 * inquiétant que D11 a supprimé.
 *
 * La cible est désignée par un attribut `data-coach="<clé>"` posé sur le vrai
 * bouton, et non par une classe CSS : une classe se renomme au fil d'un
 * refactor de style sans que personne ne pense au repère qui s'y accrochait.
 */
import { computed, nextTick, onBeforeUnmount, ref, watch } from 'vue'

export interface EtapeCoach {
  /** Valeur de l'attribut `data-coach` portée par le bouton visé. */
  cle: string
  titre: string
  texte: string
}

const props = defineProps<{
  ouvert: boolean
  etapes: EtapeCoach[]
}>()
const emit = defineEmits<{ (e: 'update:ouvert', v: boolean): void }>()

interface Cible { etape: EtapeCoach; el: HTMLElement }

const cibles = ref<Cible[]>([])
const rect = ref<DOMRect | null>(null)
const index = ref(0)
const courant = computed<Cible | null>(() => cibles.value[index.value] ?? null)

/** Ne garde que les étapes dont la cible est RÉELLEMENT dessinée. Un bouton
 *  masqué a un rect de 0×0 : le tester évite de dessiner un halo sur un point. */
function recenser(): void {
  const out: Cible[] = []
  for (const etape of props.etapes) {
    const el = document.querySelector<HTMLElement>(`[data-coach="${etape.cle}"]`)
    if (!el) continue
    const r = el.getBoundingClientRect()
    if (r.width === 0 || r.height === 0) continue
    out.push({ etape, el })
  }
  cibles.value = out
  if (index.value >= out.length) index.value = Math.max(0, out.length - 1)
}

/**
 * Amène la cible SOUS LES YEUX, puis mesure — dans cet ordre.
 *
 * ⛔ Sans le défilement, un repère parfaitement positionné est parfaitement
 * invisible. Mesuré le 2026-08-24 : l'étape « passer » visait un bouton à
 * y ≈ 2 680 px ; le halo et la bulle étaient géométriquement justes, et l'écran
 * ne montrait qu'un voile sombre et vide. Un repère qu'il faut chercher n'est
 * plus un repère.
 *
 * Défilement INSTANTANÉ (`behavior: 'auto'`) et non « smooth » : avec une
 * animation il faut deviner quand elle finit, et une mesure prise trop tôt pose
 * le halo à l'ancienne position — un défaut qui ne se voit qu'une fois sur
 * trois, donc qu'on ne reproduit pas.
 */
function placer(): void {
  const c = courant.value
  if (!c) { rect.value = null; return }
  const r = c.el.getBoundingClientRect()
  const marge = 80
  if (r.top < marge || r.bottom > window.innerHeight - marge) {
    c.el.scrollIntoView({ block: 'center', inline: 'nearest', behavior: 'auto' })
  }
  rect.value = c.el.getBoundingClientRect()
}

function mesurer(): void {
  recenser()
  placer()
}

function fermer(): void {
  emit('update:ouvert', false)
  index.value = 0
}
function suivant(): void {
  if (index.value < cibles.value.length - 1) { index.value += 1; placer() }
  else fermer()
}
function precedent(): void {
  if (index.value > 0) { index.value -= 1; placer() }
}

function surTouche(e: KeyboardEvent): void {
  if (!props.ouvert) return
  if (e.key === 'Escape') { e.preventDefault(); fermer() }
  else if (e.key === 'ArrowRight' || e.key === 'Enter') { e.preventDefault(); suivant() }
  else if (e.key === 'ArrowLeft') { e.preventDefault(); precedent() }
}

watch(() => props.ouvert, async (v) => {
  if (!v) return
  index.value = 0
  await nextTick()
  mesurer()
  // Rien à montrer : on ne laisse pas un voile sombre sur un écran sans repère.
  if (!cibles.value.length) fermer()
})

// Le halo suit la page : sans l'écoute du défilement, il reste collé à sa
// position d'origine dès que l'utilisateur fait rouler la molette derrière le
// voile — et pointe alors un endroit vide.
const suivre = () => { if (props.ouvert) placer() }
window.addEventListener('resize', suivre)
window.addEventListener('scroll', suivre, true)
window.addEventListener('keydown', surTouche)
onBeforeUnmount(() => {
  window.removeEventListener('resize', suivre)
  window.removeEventListener('scroll', suivre, true)
  window.removeEventListener('keydown', surTouche)
})

/** Le trou dans le voile — une `box-shadow` géante plutôt qu'un masque SVG :
 *  elle suit la boîte du bouton au pixel, sans second calcul de géométrie. */
function styleTrou(r: DOMRect) {
  return {
    top: `${r.top - 6}px`, left: `${r.left - 6}px`,
    width: `${r.width + 12}px`, height: `${r.height + 12}px`,
  }
}

/** La bulle se place SOUS la cible, ou au-dessus si elle déborderait. Elle est
 *  bornée à la fenêtre : une bulle coupée est une bulle illisible. */
function styleBulle(r: DOMRect) {
  const large = 320
  const dessous = r.bottom + 14
  const dessus = r.top - 14
  const place = dessous + 160 < window.innerHeight
  const gauche = Math.min(
    Math.max(12, r.left + r.width / 2 - large / 2),
    Math.max(12, window.innerWidth - large - 12),
  )
  return place
    ? { top: `${dessous}px`, left: `${gauche}px`, width: `${large}px` }
    : { bottom: `${window.innerHeight - dessus}px`, left: `${gauche}px`, width: `${large}px` }
}
</script>

<template>
  <div
    v-if="ouvert && courant && rect" class="voile" role="dialog" aria-modal="true"
    :aria-label="courant.etape.titre" @click="fermer"
  >
    <div class="trou" :style="styleTrou(rect)" />

    <article class="bulle" :style="styleBulle(rect)" @click.stop>
      <p class="pas">{{ index + 1 }} / {{ cibles.length }}</p>
      <h3 class="titre">{{ courant.etape.titre }}</h3>
      <p class="texte">{{ courant.etape.texte }}</p>
      <div class="actions">
        <button v-if="index > 0" type="button" class="lien" @click="precedent">
          Précédent
        </button>
        <button type="button" class="lien lien--discret" @click="fermer">
          Fermer
        </button>
        <button type="button" class="principal" @click="suivant">
          {{ index === cibles.length - 1 ? "J'ai compris" : 'Suivant' }}
        </button>
      </div>
    </article>
  </div>
</template>

<style scoped>
.voile { position: fixed; inset: 0; z-index: 40; }

.trou {
  position: fixed;
  border-radius: 8px;
  /* Le voile EST cette ombre : le rectangle reste net, tout le reste s'assombrit. */
  box-shadow: 0 0 0 9999px rgba(14, 14, 31, 0.62);
  outline: 2px solid var(--gold);
  outline-offset: 0;
  transition: all 220ms cubic-bezier(0.22, 1, 0.36, 1);
  pointer-events: none;
}
@media (prefers-reduced-motion: reduce) {
  .trou { transition: none; }
}

.bulle {
  position: fixed;
  background: var(--surface);
  border: 1px solid var(--surface-3);
  border-radius: 8px;
  padding: var(--space-4) var(--space-5) var(--space-4);
  box-shadow: 0 8px 28px rgba(14, 14, 31, 0.28);
}

.pas {
  font-family: var(--font-ui);
  font-size: 10px;
  font-weight: 600;
  letter-spacing: var(--tracking-eyebrow);
  color: var(--ink-300);
}
.titre {
  margin-top: var(--space-2);
  font-family: var(--font-display);
  font-size: var(--text-base);
  color: var(--indigo-700);
}
.texte {
  margin-top: var(--space-2);
  font-family: var(--font-ui);
  font-size: var(--text-sm);
  color: var(--ink-500);
  line-height: var(--leading-base);
}

.actions {
  display: flex; align-items: center; justify-content: flex-end;
  gap: var(--space-3); margin-top: var(--space-4);
}
.lien {
  font-family: var(--font-ui); font-size: var(--text-xs);
  color: var(--ink-500); background: none; border: 0; cursor: pointer;
}
.lien:hover { color: var(--indigo-700); }
.lien--discret { margin-right: auto; color: var(--ink-300); }
.principal {
  font-family: var(--font-ui); font-size: var(--text-sm); font-weight: 500;
  color: var(--surface); background: var(--indigo-700);
  border: 0; border-radius: 6px; padding: var(--space-2) var(--space-4);
  cursor: pointer;
}
.principal:hover { background: var(--indigo-600); }
.lien:focus-visible, .principal:focus-visible {
  outline: 2px solid var(--gold); outline-offset: 2px;
}
</style>
