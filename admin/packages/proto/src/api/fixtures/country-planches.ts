/* api/fixtures/country-planches.ts — planches pays (fixture démo).
 * Drill-down catalogue /vault/catalog/:iso. Port de vault-catalog-country.js
 * (COUNTRIES). Données démo (pas de vrais eurio_id), fallback FR. */

import type { CountryPlanche } from '../types'

export const COUNTRY_PLANCHES: Record<string, CountryPlanche> = {
  FR: {
    iso: 'FR',
    name: 'France',
    flag: '🇫🇷',
    coins: [
      { eurioId: 'fr-001', type: 'circulation', metal: 'copper', val: '1c', owned: true, scannedAt: '2026-02-22' },
      { eurioId: 'fr-002', type: 'circulation', metal: 'copper', val: '2c', owned: true, scannedAt: '2026-02-22' },
      { eurioId: 'fr-005', type: 'circulation', metal: 'copper', val: '5c', owned: true, scannedAt: '2026-02-28' },
      { eurioId: 'fr-010', type: 'circulation', metal: 'nordic', val: '10c', owned: true, scannedAt: '2026-03-05' },
      { eurioId: 'fr-020', type: 'circulation', metal: 'nordic', val: '20c', owned: true, scannedAt: '2026-03-12' },
      { eurioId: 'fr-050', type: 'circulation', metal: 'nordic', val: '50c', owned: true, scannedAt: '2026-03-18' },
      { eurioId: 'fr-100', type: 'circulation', metal: 'silver', val: '1€', owned: true, scannedAt: '2026-03-25' },
      { eurioId: 'fr-200', type: 'circulation', metal: 'bimetal', val: '2€', owned: true, scannedAt: '2026-03-30' },
      { eurioId: 'fr-c01', type: 'commemo', metal: 'bimetal', val: '2€', owned: true, scannedAt: '2026-04-02' },
      { eurioId: 'fr-c02', type: 'commemo', metal: 'bimetal', val: '2€', owned: true, scannedAt: '2026-04-04' },
      { eurioId: 'fr-c03', type: 'commemo', metal: 'bimetal', val: '2€', owned: true, scannedAt: '2026-04-08' },
      { eurioId: 'fr-c04', type: 'commemo', metal: 'bimetal', val: '2€', owned: true, scannedAt: '2026-04-12' },
      { eurioId: 'fr-c05', type: 'commemo', metal: 'bimetal', val: '2€', owned: false, scannedAt: null },
      { eurioId: 'fr-c06', type: 'commemo', metal: 'bimetal', val: '2€', owned: false, scannedAt: null },
      { eurioId: 'fr-c07', type: 'commemo', metal: 'bimetal', val: '2€', owned: false, scannedAt: null },
      { eurioId: 'fr-c08', type: 'commemo', metal: 'bimetal', val: '2€', owned: false, scannedAt: null },
      { eurioId: 'fr-c09', type: 'commemo', metal: 'bimetal', val: '2€', owned: false, scannedAt: null },
      { eurioId: 'fr-c10', type: 'commemo', metal: 'bimetal', val: '2€', owned: false, scannedAt: null },
    ],
  },
  IT: {
    iso: 'IT',
    name: 'Italie',
    flag: '🇮🇹',
    coins: [
      { eurioId: 'it-001', type: 'circulation', metal: 'copper', val: '1c', owned: true, scannedAt: '2026-03-12' },
      { eurioId: 'it-002', type: 'circulation', metal: 'copper', val: '2c', owned: true, scannedAt: '2026-03-12' },
      { eurioId: 'it-005', type: 'circulation', metal: 'copper', val: '5c', owned: true, scannedAt: '2026-03-18' },
      { eurioId: 'it-010', type: 'circulation', metal: 'nordic', val: '10c', owned: true, scannedAt: '2026-03-29' },
      { eurioId: 'it-020', type: 'circulation', metal: 'nordic', val: '20c', owned: true, scannedAt: '2026-04-02' },
      { eurioId: 'it-050', type: 'circulation', metal: 'nordic', val: '50c', owned: false, scannedAt: null },
      { eurioId: 'it-100', type: 'circulation', metal: 'silver', val: '1€', owned: false, scannedAt: null },
      { eurioId: 'it-200', type: 'circulation', metal: 'bimetal', val: '2€', owned: false, scannedAt: null },
      { eurioId: 'it-c01', type: 'commemo', metal: 'bimetal', val: '2€', owned: false, scannedAt: null },
      { eurioId: 'it-c02', type: 'commemo', metal: 'bimetal', val: '2€', owned: false, scannedAt: null },
    ],
  },
}
