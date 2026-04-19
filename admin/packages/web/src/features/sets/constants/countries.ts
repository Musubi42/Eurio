/**
 * Pays euros — 21 eurozone + 4 micro-états utilisant l'euro + 'EU' pseudo-country
 * pour les émissions communes (bce_comm).
 *
 * Bulgarie rejointe le 2026-01-01. Codes en MAJUSCULES (alignés sur coins.country en DB).
 */

export interface Country {
  code: string
  name: string
  flag: string
  group: 'eurozone' | 'microstate' | 'pseudo'
}

export const EUROZONE_COUNTRIES: Country[] = [
  { code: 'AT', name: 'Autriche',   flag: '🇦🇹', group: 'eurozone' },
  { code: 'BE', name: 'Belgique',   flag: '🇧🇪', group: 'eurozone' },
  { code: 'BG', name: 'Bulgarie',   flag: '🇧🇬', group: 'eurozone' },
  { code: 'CY', name: 'Chypre',     flag: '🇨🇾', group: 'eurozone' },
  { code: 'DE', name: 'Allemagne',  flag: '🇩🇪', group: 'eurozone' },
  { code: 'EE', name: 'Estonie',    flag: '🇪🇪', group: 'eurozone' },
  { code: 'ES', name: 'Espagne',    flag: '🇪🇸', group: 'eurozone' },
  { code: 'FI', name: 'Finlande',   flag: '🇫🇮', group: 'eurozone' },
  { code: 'FR', name: 'France',     flag: '🇫🇷', group: 'eurozone' },
  { code: 'GR', name: 'Grèce',      flag: '🇬🇷', group: 'eurozone' },
  { code: 'HR', name: 'Croatie',    flag: '🇭🇷', group: 'eurozone' },
  { code: 'IE', name: 'Irlande',    flag: '🇮🇪', group: 'eurozone' },
  { code: 'IT', name: 'Italie',     flag: '🇮🇹', group: 'eurozone' },
  { code: 'LT', name: 'Lituanie',   flag: '🇱🇹', group: 'eurozone' },
  { code: 'LU', name: 'Luxembourg', flag: '🇱🇺', group: 'eurozone' },
  { code: 'LV', name: 'Lettonie',   flag: '🇱🇻', group: 'eurozone' },
  { code: 'MT', name: 'Malte',      flag: '🇲🇹', group: 'eurozone' },
  { code: 'NL', name: 'Pays-Bas',   flag: '🇳🇱', group: 'eurozone' },
  { code: 'PT', name: 'Portugal',   flag: '🇵🇹', group: 'eurozone' },
  { code: 'SI', name: 'Slovénie',   flag: '🇸🇮', group: 'eurozone' },
  { code: 'SK', name: 'Slovaquie',  flag: '🇸🇰', group: 'eurozone' },
]

export const MICRO_STATES: Country[] = [
  { code: 'AD', name: 'Andorre',     flag: '🇦🇩', group: 'microstate' },
  { code: 'MC', name: 'Monaco',      flag: '🇲🇨', group: 'microstate' },
  { code: 'SM', name: 'Saint-Marin', flag: '🇸🇲', group: 'microstate' },
  { code: 'VA', name: 'Vatican',     flag: '🇻🇦', group: 'microstate' },
]

export const PSEUDO_COUNTRIES: Country[] = [
  { code: 'EU', name: 'Union Européenne (communes)', flag: '🇪🇺', group: 'pseudo' },
]

export const ALL_COUNTRIES: Country[] = [
  ...EUROZONE_COUNTRIES,
  ...MICRO_STATES,
  ...PSEUDO_COUNTRIES,
]

export const COUNTRY_BY_CODE: Record<string, Country> = Object.fromEntries(
  ALL_COUNTRIES.map(c => [c.code, c]),
)

export const FACE_VALUES = [0.01, 0.02, 0.05, 0.10, 0.20, 0.50, 1.00, 2.00] as const

export function formatFaceValue(v: number): string {
  if (v >= 1) return `${v.toFixed(0)}€`
  return `${(v * 100).toFixed(0)}¢`
}
