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
 * Le périmètre PAR BESOIN : `?need=1` → ne servir que les crops dont le top-1
 * DINO tombe dans une classe encore en besoin ; les classes pleines sont
 * parquées (D2/D3, `docs/work-in-progress/pipeline-propre/DECISIONS.md`).
 * Côté API : `need_only=true`. Tout autre valeur que `1` = filtre absent.
 */
export function queryNeedOnly(route: RouteLocationNormalizedLoaded): boolean {
  return queryParam(route, 'need') === '1'
}
