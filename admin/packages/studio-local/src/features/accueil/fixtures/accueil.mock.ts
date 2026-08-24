/**
 * Les états de l'accueil, pour la maquette (`/accueil/maquette`).
 *
 * POURQUOI DES FIXTURES ET PAS LA VRAIE DONNÉE
 * --------------------------------------------
 * Un écran se juge sur ses cas limites autant que sur son cas nominal, et les
 * cas limites ne se commandent pas en base : un ami qui n'a encore rien trié,
 * une file vide, une erreur réseau. Les fixtures les rendent regardables en un
 * clic — c'est ce qui permet de trancher le visuel AVANT de brancher.
 *
 * ⛔ CE FICHIER NE SERT QU'À LA MAQUETTE. Aucun écran branché ne l'importe : la
 * page réelle lit `/class-need` et `/me/review-stats`, et rien d'autre. Une
 * fixture qui fuit dans un écran de production, c'est un chiffre inventé montré
 * à quelqu'un qui le croit.
 *
 * Les valeurs viennent du dessin d'`ACCUEIL-AMI.md` §5, cibles comprises : 8
 * partout sauf une émission commune à 5, pour que la maquette prouve que la
 * ligne lit bien le `target` de SA pièce.
 */
import type { PieceATrier } from '../composables/usePiecesATrier'

export interface EtatAccueil {
  id: string
  titre: string
  /** Ce que cet état met à l'épreuve — affiché dans le sélecteur. */
  enjeu: string
  nTriees: number | null
  nCompletees: number | null
  butCommun: { atteint: number; total: number } | null
  pieces: PieceATrier[]
  chargement: boolean
  erreur: string | null
}

/** Deux vraies URLs du CDN public (`numista-canonical`, sans signature) : la
 *  maquette doit montrer de VRAIES vignettes, sinon elle ne dit rien de la
 *  densité réelle de la liste. Les autres lignes portent `null` ou `undefined`
 *  — les deux cas de vide, qu'il faut voir côte à côte avec les pleins. */
const CDN = 'https://eurio-images.musubi.dev'
const IMG_FI = `${CDN}/fi-2015-2eur-150th-anniversary-of-the-birth-of-artist-akseli-gallen-kallela/obverse_bce_thumb.webp`

const PIECES: PieceATrier[] = [
  { key: 'be-2016-2eur-rio', nom: '2 € Belgique 2016 — Jeux de Rio', pays: 'BE', acquis: 3, cible: 8, href: '/review/peche?class=be-2016-2eur-rio', image: IMG_FI },
  { key: 'at-2018-2eur-republique', nom: '2 € Autriche 2018 — 100 ans de la République', pays: 'AT', acquis: 0, cible: 8, href: '/review/peche?class=at-2018-2eur-republique', image: null },
  { key: 'si-2011-2eur-rozman', nom: '2 € Slovénie 2011 — Franc Rozman', pays: 'SI', acquis: 5, cible: 8, href: '/review/peche?class=si-2011-2eur-rozman', image: IMG_FI },
  { key: 'fr-2024-2eur-jo', nom: '2 € France 2024 — Jeux Olympiques', pays: 'FR', acquis: 1, cible: 8, href: '/review/peche?class=fr-2024-2eur-jo', image: 'https://exemple.invalide/cassee.webp' },
  // Émission commune : cible 5, pas 8. Si la maquette dessine 8 ronds ici,
  // c'est que la ligne écrit la cible en dur — le défaut que §5.1 signale.
  { key: 'de-2015-2eur-drapeau', nom: '2 € Allemagne 2015 — 30 ans du drapeau européen', pays: 'DE', acquis: 4, cible: 5, href: '/review/peche?class=de-2015-2eur-drapeau' },
  { key: 'pt-2017-2eur-police', nom: '2 € Portugal 2017 — Sécurité publique', pays: 'PT', acquis: 2, cible: 8, href: '/review/peche?class=pt-2017-2eur-police' },
  { key: 'lu-2019-2eur-charlotte', nom: '2 € Luxembourg 2019 — Grande-Duchesse Charlotte', pays: 'LU', acquis: 6, cible: 8, href: '/review/peche?class=lu-2019-2eur-charlotte' },
  // Sans pays : la pastille ne doit pas laisser un trou dans la colonne.
  { key: 'xx-2007-2eur-traite', nom: '2 € 2007 — Traité de Rome', pays: null, acquis: 2, cible: 5, href: '/review/peche?class=xx-2007-2eur-traite' },
]

export const ETATS: EtatAccueil[] = [
  {
    id: 'nominal',
    titre: 'Un ami qui a déjà trié',
    enjeu: 'Le cas du dessin : trois chiffres sur une ligne, la liste qui domine.',
    nTriees: 47,
    nCompletees: 6,
    butCommun: { atteint: 412, total: 671 },
    pieces: PIECES,
    chargement: false,
    erreur: null,
  },
  {
    id: 'debutant',
    titre: 'Sa toute première visite',
    enjeu: "Zéro partout. L'écran doit inviter, jamais constater un échec — et les singuliers doivent tomber juste.",
    nTriees: 0,
    nCompletees: 0,
    butCommun: { atteint: 412, total: 671 },
    pieces: PIECES,
    chargement: false,
    erreur: null,
  },
  {
    id: 'premiere-piece',
    titre: 'Après sa première pièce complétée',
    enjeu: 'Les singuliers : « 1 image triée », « 1 pièce complétée ».',
    nTriees: 1,
    nCompletees: 1,
    butCommun: { atteint: 413, total: 671 },
    pieces: PIECES.slice(0, 3),
    chargement: false,
    erreur: null,
  },
  {
    id: 'file-vide',
    titre: 'Plus rien à trier',
    enjeu: "Un écran vide est une invitation, pas un « tu as fini ». Ses chiffres à lui restent affichés.",
    nTriees: 47,
    nCompletees: 6,
    butCommun: { atteint: 412, total: 671 },
    pieces: [],
    chargement: false,
    erreur: null,
  },
  {
    id: 'chargement',
    titre: 'Pendant le chargement',
    enjeu: "Ne JAMAIS montrer une liste vide en attendant : ça se lit « il n'y a rien à faire », ce qui est plausible et faux.",
    nTriees: null,
    nCompletees: null,
    butCommun: null,
    pieces: [],
    chargement: true,
    erreur: null,
  },
  {
    id: 'erreur',
    titre: 'La liste ne répond pas',
    enjeu: "L'erreur dit quoi faire, dans sa langue. Elle ne l'accuse pas et ne lui parle pas d'un port.",
    nTriees: 47,
    nCompletees: 6,
    butCommun: null,
    pieces: [],
    chargement: false,
    erreur: 'HTTP 503 — service indisponible',
  },
  {
    id: 'stats-muettes',
    titre: 'Ses compteurs ne répondent pas',
    enjeu: "Une gêne, pas une panne : les tirets remplacent ses chiffres et il peut continuer à trier.",
    nTriees: null,
    nCompletees: null,
    butCommun: { atteint: 412, total: 671 },
    pieces: PIECES,
    chargement: false,
    erreur: null,
  },
]
