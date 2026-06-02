/* api/fixtures/achievements.ts — définitions de chasses + paliers (DÉMO).
 *
 * SOURCE UNIQUE des tables chases/médailles. Consommée par :
 *   - lib/achievements.ts        (dérivation de la progression)
 *   - scenes/profile/*           (home, achievements, set)
 *   - stores/collection.ts       (checkSetCompletions → célébration unlock)
 *
 * ⚠️ Données DÉMO. Le catalogue réel (app_core.json) ne couvre AUJOURD'HUI que
 * les 2€ : aucune pièce de circulation (1c–1€) n'a d'eurio_id dans le snapshot
 * courant. Les séries `circulation-*` restent donc à 0/8 tant que le chantier
 * data n'a pas ajouté la circulation — c'est volontaire et honnête, pas un bug.
 * La jointure live (Chunk F) prendra le relais dès que le catalogue couvrira
 * toutes les dénominations. Les chasses par pays (founding/grande) et par
 * comptage (2€ commémoratives) progressent, elles, avec le vrai catalogue.
 *
 * Port des tables de scenes/profile.js + profile-achievements.js + profile-set.js,
 * dédupliquées ici (R0 : une seule source au lieu de trois copies).
 */

// ───────── Paliers (niveau / rang) ─────────
// Référence pour les libellés + captions du profil ET pour le calcul de niveau
// du store (recomputeLevel dérive ses seuils d'ici — pas de table dupliquée).

export interface TierDef {
  name: string
  min: number
  nextAt: number | null
  caption: string
}

export const TIERS: TierDef[] = [
  { name: 'Découvreur', min: 0, nextAt: 5, caption: '« Ton aventure commence »' },
  { name: 'Passionné', min: 5, nextAt: 30, caption: '« Tu prends goût à la collection »' },
  { name: 'Expert', min: 30, nextAt: 100, caption: '« La collection devient une discipline »' },
  { name: 'Maître', min: 100, nextAt: null, caption: '« Tu as atteint le rang le plus élevé »' },
]

// ───────── Tables de référence ─────────

export interface Denom {
  cents: number
  label: string
}

/** Les 8 dénominations d'une série de circulation, du cent à 2 €. */
export const STANDARD_DENOMS: Denom[] = [
  { cents: 1, label: '1 c' },
  { cents: 2, label: '2 c' },
  { cents: 5, label: '5 c' },
  { cents: 10, label: '10 c' },
  { cents: 20, label: '20 c' },
  { cents: 50, label: '50 c' },
  { cents: 100, label: '1 €' },
  { cents: 200, label: '2 €' },
]

export const COUNTRY_NAMES: Record<string, string> = {
  AT: 'Autriche', BE: 'Belgique', BG: 'Bulgarie', CY: 'Chypre',
  DE: 'Allemagne', EE: 'Estonie', ES: 'Espagne', FI: 'Finlande',
  FR: 'France', GR: 'Grèce', HR: 'Croatie', IE: 'Irlande',
  IT: 'Italie', LT: 'Lituanie', LU: 'Luxembourg', LV: 'Lettonie',
  MT: 'Malte', NL: 'Pays-Bas', PT: 'Portugal', SI: 'Slovénie',
  SK: 'Slovaquie',
}

/** Adjectif gentilé français pour la description des séries de circulation. */
export const COUNTRY_ADJECTIVES: Record<string, string> = {
  France: 'françaises',
  Allemagne: 'allemandes',
  Italie: 'italiennes',
  Espagne: 'espagnoles',
  Portugal: 'portugaises',
  Belgique: 'belges',
  'Pays-Bas': 'néerlandaises',
  Autriche: 'autrichiennes',
  Irlande: 'irlandaises',
  Finlande: 'finlandaises',
}

/** 12 pays fondateurs de la zone euro. */
export const FOUNDING = ['BE', 'DE', 'ES', 'FI', 'FR', 'GR', 'IE', 'IT', 'LU', 'NL', 'AT', 'PT']

/** 21 pays de la zone euro (Bulgarie incluse depuis 2026). */
export const ALL_EZ = [
  'AT', 'BE', 'BG', 'CY', 'DE', 'EE', 'ES', 'FI', 'FR', 'GR', 'HR',
  'IE', 'IT', 'LT', 'LU', 'LV', 'MT', 'NL', 'PT', 'SI', 'SK',
]

// ───────── Définitions de chasses ─────────

export type ChaseKind = 'circulation' | 'founding' | 'grande' | 'commem'

export interface ChaseDef {
  id: string
  title: string
  difficulty: string
  icon: string
  kind: ChaseKind
  /** Pour `kind === 'circulation'`. */
  countryCode?: string
}

export const CHASE_DEFINITIONS: ChaseDef[] = [
  { id: 'circulation-fr', title: 'Série complète France', difficulty: 'Facile', icon: '★', kind: 'circulation', countryCode: 'FR' },
  { id: 'eurozone-founding', title: 'Eurozone founding', difficulty: 'Moyen', icon: '◎', kind: 'founding' },
  { id: 'grande-chasse', title: 'Grande chasse', difficulty: 'Difficile', icon: '◐', kind: 'grande' },
  { id: 'circulation-de', title: 'Série complète Allemagne', difficulty: 'Facile', icon: '✦', kind: 'circulation', countryCode: 'DE' },
  { id: 'commemoratives-2e', title: 'Dix 2€ commémoratives', difficulty: 'Moyen', icon: '◇', kind: 'commem' },
]

export function chaseDef(id: string): ChaseDef | null {
  return CHASE_DEFINITIONS.find((c) => c.id === id) ?? null
}
