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
