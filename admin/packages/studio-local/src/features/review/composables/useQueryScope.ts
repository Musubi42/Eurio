// Lire un paramètre de périmètre dans l'URL — sans jamais l'élargir en silence.
//
// LE BUG QUE CE MODULE EXISTE POUR ÉVITER, vécu le 2026-08-20
// ----------------------------------------------------------
// Les vues lisaient leur périmètre ainsi :
//
//     typeof route.query.eurio_id === 'string' ? route.query.eurio_id : null
//
// Or vue-router rend un **tableau** quand un paramètre apparaît deux fois dans
// l'URL — ce qui arrive dès qu'on recolle à la main une URL déjà complète. Le
// test échoue, la valeur tombe à `null`, et le scope ne disparaît pas : il
// RETOMBE sur le suivant, plus large. En séance, une file cadrée sur l'italienne
// standard s'est ainsi élargie à toute la cohorte et a servi une Saarland
// allemande, tri DINO allumé, sans le moindre signe à l'écran.
//
// La règle : un périmètre qui rate doit se FERMER, jamais s'ouvrir. À défaut de
// pouvoir échouer bruyamment ici, on prend la dernière valeur — celle que
// l'utilisateur vient d'ajouter, donc celle qu'il croit avoir demandée.

import type { RouteLocationNormalizedLoaded } from 'vue-router'

export function queryParam(
  route: RouteLocationNormalizedLoaded,
  name: string,
): string | null {
  const raw = route.query[name]
  if (Array.isArray(raw)) {
    // Dernière valeur non vide : `?a=&a=x` doit valoir « x ».
    for (let i = raw.length - 1; i >= 0; i--) {
      const v = raw[i]
      if (typeof v === 'string' && v) return v
    }
    return null
  }
  return typeof raw === 'string' && raw ? raw : null
}

/**
 * Le périmètre PAR RUN SOURCE : `?run=a,b` → `['a', 'b']`, `null` sans param.
 *
 * Un seul endroit pour le découpage, parce que trois écrans le lisent (file
 * single, grille des lots, détail d'un lot) et que le bandeau d'avancement
 * doit compter EXACTEMENT ce que la file sert : deux parsings qui divergent
 * donneraient un « 0 / 777 » au-dessus d'une file de 500.
 */
export function queryRunIds(route: RouteLocationNormalizedLoaded): string[] | null {
  const raw = queryParam(route, 'run')
  if (!raw) return null
  const ids = raw.split(',').map((s) => s.trim()).filter(Boolean)
  return ids.length ? ids : null
}

/**
 * Le périmètre PAR BESOIN — **ACTIF PAR DÉFAUT** (D9, 2026-08-23).
 *
 * Ne servir que les crops dont le top-1 DINO tombe dans une classe encore en
 * besoin ; les classes à leur cible sont **parquées** (D2/D3) — ni fermées ni
 * supprimées, et le compte s'affiche. Côté API : `need_only=true`.
 *
 * LE DÉFAUT EST RENVERSÉ, ET C'EST LE CŒUR DU LOT 4.
 * Mesuré le 2026-08-23 sur le canonique : **4 999 des 6 574 crops ouverts
 * (76 %)** tombent dans une classe qui n'a plus besoin de rien. Les servir,
 * c'est du temps humain perdu par construction — et c'est ce que faisait
 * l'admin, parce que le filtre existait mais était opt-in (`?need=1`) et que
 * la pêche ne le passait pas du tout.
 *
 * On lève donc explicitement (`?need=0`), jamais l'inverse. Un opérateur qui
 * VEUT voir les parqués le demande ; il n'a pas à savoir qu'un filtre existe
 * pour éviter d'en perdre les trois quarts.
 *
 * ⛔ Toute valeur autre que `0` laisse le filtre ACTIF — y compris `?need=1`,
 * qui reste valide et redondant (les liens déjà partagés continuent de
 * marcher). Un typo ne doit pas rendre 76 % de bruit en silence.
 *
 * 🔴 SAUF SUR UNE FILE DE COHORTE, ET C'EST UNE CORRECTION DE D9.
 * Le besoin est un critère de la VOIE B (la banque DINO : « cette classe a ses
 * 8 exemplaires »). Une cohorte, elle, sert la VOIE A — l'entraînement ArcFace,
 * dont le critère d'arrêt est `min_real = 10` crops validés par classe. Les
 * deux comptent autre chose, et `design/DESIGN.md` §5 interdit explicitement de
 * les confondre : « les deux peuvent être en désaccord légitime sur la même
 * classe ».
 *
 * Appliquer B à une file A retirait, mesuré le 2026-08-23 sur la réplique :
 *
 *     cohorte giga-40-vague1        2 825 ouverts →   484 servis  (83 % parqués)
 *     cohorte again                   493 ouverts →   100 servis  (80 %)
 *     cohorte parcours4-exercice-1    187 ouverts →    48 servis  (74 %)
 *
 * — en silence, et sur un écran dont le message de fin de file dit « Tout est
 * résolu ». Exactement la panne muette que ce chantier combat.
 *
 * Le cadrage reste DEMANDABLE sur une cohorte (`?need=1`) : ce qu'on retire,
 * c'est le défaut, pas la capacité.
 */
export function queryNeedOnly(route: RouteLocationNormalizedLoaded): boolean {
  const raw = queryParam(route, 'need')
  if (raw === '0') return false
  if (raw === '1') return true
  // Défaut : actif — sauf si la file est cadrée par une cohorte (voie A).
  return !queryParam(route, 'cohort')
}
