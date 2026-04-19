import type { ConfusionZone } from '@/shared/supabase/types'

export interface ZoneStyle {
  solid: string
  soft: string
  label: string
  emoji: string
  short: string
}

const STYLES: Record<ConfusionZone, ZoneStyle> = {
  green: {
    solid: 'var(--success)',
    soft: 'var(--success-soft)',
    label: 'Zone verte',
    emoji: '🟢',
    short: 'V',
  },
  orange: {
    solid: 'var(--warning)',
    soft: 'var(--warning-soft)',
    label: 'Zone orange',
    emoji: '🟠',
    short: 'O',
  },
  red: {
    solid: 'var(--danger)',
    soft: 'var(--danger-soft)',
    label: 'Zone rouge',
    emoji: '🔴',
    short: 'R',
  },
}

export function zoneStyle(zone: ConfusionZone): ZoneStyle {
  return STYLES[zone]
}

export function zoneFromSimilarity(sim: number): ConfusionZone {
  if (sim >= 0.85) return 'red'
  if (sim >= 0.70) return 'orange'
  return 'green'
}

export function zoneCopy(zone: ConfusionZone, sim: number): string {
  const s = sim.toFixed(3)
  if (zone === 'green') {
    return 'Design visuellement isolé. Entraînement direct possible avec Numista + augmentation.'
  }
  if (zone === 'orange') {
    return `Voisin proche détecté à ${s}. Enrichissement recommandé avant entraînement.`
  }
  return `Paire quasi-jumelle à ${s}. Enrichissement obligatoire — l'entraînement sans photos additionnelles produira des collisions.`
}
