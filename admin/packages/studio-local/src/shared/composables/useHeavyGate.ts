/**
 * La règle de rendu des gestes LOURDS — un seul endroit (D11).
 *
 * Deux axes, déjà posés au lot 5 et inchangés :
 *   - MACHINE (`canRunHeavy`) : « ce poste peut-il ? » — l'API ML locale `:8042`
 *     est-elle joignable.
 *   - DROIT (`canArbitrate`)  : « cette personne a-t-elle le droit ? » — le scope
 *     `review:arbitrate`.
 *
 * Ce que D11 ajoute, c'est le RENDU quand la machine ne peut pas :
 *   - pour un **arbitre** (son poste, il sait ce qu'est `:8042` et il peut y aller) :
 *     le geste reste **visible et grisé**, avec son infobulle — c'est le choix du lot 5,
 *     conservé ;
 *   - pour un **ami** (pas d'`review:arbitrate`) : le geste est **absent**. Un bouton
 *     mort qui parle d'un port et d'une machine qu'il n'aura jamais est du bruit
 *     inquiétant, pas une information. Constaté en production le 2026-08-23 :
 *     « pour faire la review, on nous dit que c'est en local ».
 *
 * `showHeavyGesture` porte exactement cette question : « faut-il DESSINER ce geste ? ».
 * Le `:disabled` reste porté par `canRunHeavy` — masquer n'est pas désarmer, et les
 * raccourcis clavier gardent leur propre garde (piège du lot 5).
 *
 * ⚠️ Ce n'est PAS une garde de sécurité : la vraie garde est serveur
 * (`require_scope` / `require_scope_by_method`, lot 4b).
 */
import { computed } from 'vue'

import { useCapabilities } from '@/stores/capabilities'
import { useEurioSession } from '@/stores/eurio-session'

export function useHeavyGate() {
  const caps = useCapabilities()
  const session = useEurioSession()

  /** MACHINE — l'API ML locale répond. */
  const canRunHeavy = computed(() => caps.hasLocalMlApi)
  /** DROIT — le principal arbitre (owner/admin). */
  const canArbitrate = computed(() => session.hasScope('review:arbitrate'))
  /**
   * Faut-il DESSINER ce geste lourd ? (grisé pour l'arbitre, absent pour un ami)
   *
   * 🔴 CORRIGÉ LE 2026-08-24, en revue adversariale. La formule était
   * `canRunHeavy || canArbitrate` : elle dessinait le geste dès que la MACHINE
   * pouvait, **sans regarder le droit**. Un ami qui lance le front en mode local
   * avec l'API ML joignable voyait donc « Re-détecter », « Sync crops »,
   * « Crop manuel » — et leur infobulle « disponible uniquement en local (API ML
   * :8042) ». C'est mot pour mot ce que D11 interdit, à cause du OU.
   *
   * D11 dit une chose simple : le geste lourd s'adresse à l'ARBITRE. Le droit
   * décide qu'on le dessine, la machine décide s'il est cliquable (`:disabled`
   * reste porté par `canRunHeavy` — masquer n'est pas désarmer).
   *
   * Pour un arbitre, rien ne change : `canArbitrate` est vrai, le geste reste
   * visible et grisé hors de son poste, exactement comme au lot 5.
   */
  const showHeavyGesture = computed(() => canArbitrate.value)

  return { canRunHeavy, canArbitrate, showHeavyGesture }
}
