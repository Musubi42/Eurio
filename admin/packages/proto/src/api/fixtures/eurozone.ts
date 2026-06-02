/* api/fixtures/eurozone.ts — progression par pays (fixture démo).
 *
 * owned/total = progression DÉMO (comme les sets : pas une jointure store tant
 * que le catalogue par pays n'est pas câblé sur de vrais eurio_id). Port de
 * _eurozone.js. Portugal complet = cible du scratch-reveal ; Bulgarie à 0 =
 * état « gravé ». La géométrie (paths/centroïdes) vit dans eurozone-geo.js.
 */

import type { CountryProgress } from '../types'

export const EUROZONE_PROGRESS: CountryProgress[] = [
  { iso: 'AT', name: 'Autriche', flag: '🇦🇹', owned: 18, total: 42 },
  { iso: 'BE', name: 'Belgique', flag: '🇧🇪', owned: 22, total: 38 },
  { iso: 'BG', name: 'Bulgarie', flag: '🇧🇬', owned: 0, total: 24 },
  { iso: 'CY', name: 'Chypre', flag: '🇨🇾', owned: 4, total: 26 },
  { iso: 'DE', name: 'Allemagne', flag: '🇩🇪', owned: 38, total: 62 },
  { iso: 'EE', name: 'Estonie', flag: '🇪🇪', owned: 5, total: 28 },
  { iso: 'ES', name: 'Espagne', flag: '🇪🇸', owned: 26, total: 58 },
  { iso: 'FI', name: 'Finlande', flag: '🇫🇮', owned: 14, total: 42 },
  { iso: 'FR', name: 'France', flag: '🇫🇷', owned: 45, total: 68 },
  { iso: 'GR', name: 'Grèce', flag: '🇬🇷', owned: 9, total: 38 },
  { iso: 'HR', name: 'Croatie', flag: '🇭🇷', owned: 3, total: 26 },
  { iso: 'IE', name: 'Irlande', flag: '🇮🇪', owned: 12, total: 34 },
  { iso: 'IT', name: 'Italie', flag: '🇮🇹', owned: 28, total: 58 },
  { iso: 'LT', name: 'Lituanie', flag: '🇱🇹', owned: 6, total: 28 },
  { iso: 'LU', name: 'Luxembourg', flag: '🇱🇺', owned: 19, total: 36 },
  { iso: 'LV', name: 'Lettonie', flag: '🇱🇻', owned: 5, total: 28 },
  { iso: 'MT', name: 'Malte', flag: '🇲🇹', owned: 8, total: 30 },
  { iso: 'NL', name: 'Pays-Bas', flag: '🇳🇱', owned: 20, total: 38 },
  { iso: 'PT', name: 'Portugal', flag: '🇵🇹', owned: 42, total: 42 },
  { iso: 'SI', name: 'Slovénie', flag: '🇸🇮', owned: 22, total: 30 },
  { iso: 'SK', name: 'Slovaquie', flag: '🇸🇰', owned: 8, total: 34 },
]

export function isComplete(c: CountryProgress): boolean {
  return c.total > 0 && c.owned >= c.total
}
