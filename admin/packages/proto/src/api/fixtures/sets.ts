/* api/fixtures/sets.ts — sets (fixture démo).
 *
 * Données NON dans le snapshot : pas (encore) de table sets référençant de
 * vrais eurio_id. SET_PREVIEWS alimente la liste, SET_DETAILS les planches.
 * owned/scannedAt/completedAt sont de la démo (remplacés par la jointure store
 * quand les sets référenceront le catalogue réel). Port de vault-sets-list.js
 * (MOCK_SETS) + vault-sets-detail.js (MOCK_DETAILS).
 */

import type { SetDetail, SetPreview } from '../types'

export const SET_PREVIEWS: SetPreview[] = [
  {
    id: 'it-circulation',
    title: 'Italie — circulation',
    description: 'Les 8 pièces euro de circulation italienne, de 1c à 2€.',
    category: 'country',
    kind: 'structural',
    owned: 5,
    total: 8,
    completedAt: null,
    preview: [
      { metal: 'copper', val: '1c' },
      { metal: 'copper', val: '2c' },
      { metal: 'copper', val: '5c' },
      { metal: 'nordic', val: '10c' },
      { metal: 'nordic', val: '20c' },
      { metal: 'missing', val: '50c' },
      { metal: 'missing', val: '1€' },
      { metal: 'missing', val: '2€' },
    ],
  },
  {
    id: 'fr-commemo-2024',
    title: 'Commémoratives France 2024',
    description: 'Les 2€ commémoratives françaises émises en 2024.',
    category: 'country',
    kind: 'curated',
    owned: 2,
    total: 4,
    completedAt: null,
    preview: [
      { metal: 'bimetal', val: '2€' },
      { metal: 'bimetal', val: '2€' },
      { metal: 'missing', val: '2€' },
      { metal: 'missing', val: '2€' },
      { metal: null, val: '' },
      { metal: null, val: '' },
      { metal: null, val: '' },
      { metal: null, val: '' },
    ],
  },
  {
    id: 'vatican-benoit',
    title: 'Vatican — Benoît XVI',
    description: 'La série complète des pièces émises sous Benoît XVI (2005–2013).',
    category: 'theme',
    kind: 'curated',
    owned: 3,
    total: 16,
    completedAt: null,
    preview: [
      { metal: 'nordic', val: '1€' },
      { metal: 'bimetal', val: '2€' },
      { metal: 'copper', val: '5c' },
      { metal: 'missing', val: '1c' },
      { metal: 'missing', val: '2c' },
      { metal: 'missing', val: '10c' },
      { metal: 'missing', val: '20c' },
      { metal: 'missing', val: '50c' },
    ],
  },
  {
    id: 'tier-2-euro-all',
    title: 'Toutes les 2€ courantes',
    description: 'Une 2€ face nationale de chaque pays eurozone.',
    category: 'tier',
    kind: 'parametric',
    owned: 14,
    total: 21,
    completedAt: null,
    preview: [
      { metal: 'bimetal', val: '2€' },
      { metal: 'bimetal', val: '2€' },
      { metal: 'bimetal', val: '2€' },
      { metal: 'bimetal', val: '2€' },
      { metal: 'bimetal', val: '2€' },
      { metal: 'bimetal', val: '2€' },
      { metal: 'missing', val: '2€' },
      { metal: 'missing', val: '2€' },
    ],
  },
  {
    id: 'hunt-rare-2007',
    title: 'Chasse — Traité de Rome 2007',
    description: '13 pays, un design commun, un seul millésime. Le Graal européen.',
    category: 'hunt',
    kind: 'curated',
    owned: 0,
    total: 13,
    completedAt: null,
    preview: Array.from({ length: 8 }, () => ({ metal: 'missing' as const, val: '2€' })),
  },
  {
    id: 'starter-ie',
    title: 'Starter kit Irlande 2002',
    description: 'Les 8 pièces du starter kit distribué en 2002.',
    category: 'country',
    kind: 'curated',
    owned: 8,
    total: 8,
    completedAt: '2026-04-03',
    preview: [
      { metal: 'copper', val: '1c' },
      { metal: 'copper', val: '2c' },
      { metal: 'copper', val: '5c' },
      { metal: 'nordic', val: '10c' },
      { metal: 'nordic', val: '20c' },
      { metal: 'nordic', val: '50c' },
      { metal: 'silver', val: '1€' },
      { metal: 'bimetal', val: '2€' },
    ],
  },
]

export const SET_DETAILS: Record<string, SetDetail> = {
  'it-circulation': {
    id: 'it-circulation',
    title: 'Italie — <em>circulation</em>',
    description:
      'La série complète des 8 pièces euro italiennes en circulation, du cent de cuivre à la bimétallique de 2€.',
    kindLabel: 'structural',
    chips: ['country', 'italie 🇮🇹', 'depuis 2002'],
    completedAt: null,
    reward: { title: 'Badge « Botte complète »' },
    coins: [
      { eurioId: 'it-001', metal: 'copper', val: '1c', owned: true, scannedAt: '2026-03-12' },
      { eurioId: 'it-002', metal: 'copper', val: '2c', owned: true, scannedAt: '2026-03-12' },
      { eurioId: 'it-005', metal: 'copper', val: '5c', owned: true, scannedAt: '2026-03-18' },
      { eurioId: 'it-010', metal: 'nordic', val: '10c', owned: true, scannedAt: '2026-03-29' },
      { eurioId: 'it-020', metal: 'nordic', val: '20c', owned: true, scannedAt: '2026-04-02' },
      { eurioId: 'it-050', metal: 'nordic', val: '50c', owned: false, scannedAt: null },
      { eurioId: 'it-100', metal: 'silver', val: '1€', owned: false, scannedAt: null },
      { eurioId: 'it-200', metal: 'bimetal', val: '2€', owned: false, scannedAt: null },
    ],
  },
  'starter-ie': {
    id: 'starter-ie',
    title: 'Starter kit Irlande <em>2002</em>',
    description:
      "Les 8 pièces du starter kit irlandais distribué à la veille du passage à l'euro en 2002.",
    kindLabel: 'curated',
    chips: ['country', 'irlande 🇮🇪', 'starter 2002'],
    completedAt: '2026-04-03',
    reward: { title: "Badge « Pionnier d'Éire »" },
    coins: [
      { eurioId: 'ie-001', metal: 'copper', val: '1c', owned: true, scannedAt: '2026-02-08' },
      { eurioId: 'ie-002', metal: 'copper', val: '2c', owned: true, scannedAt: '2026-02-14' },
      { eurioId: 'ie-005', metal: 'copper', val: '5c', owned: true, scannedAt: '2026-02-18' },
      { eurioId: 'ie-010', metal: 'nordic', val: '10c', owned: true, scannedAt: '2026-03-01' },
      { eurioId: 'ie-020', metal: 'nordic', val: '20c', owned: true, scannedAt: '2026-03-11' },
      { eurioId: 'ie-050', metal: 'nordic', val: '50c', owned: true, scannedAt: '2026-03-20' },
      { eurioId: 'ie-100', metal: 'silver', val: '1€', owned: true, scannedAt: '2026-03-29' },
      { eurioId: 'ie-200', metal: 'bimetal', val: '2€', owned: true, scannedAt: '2026-04-03' },
    ],
  },
}
