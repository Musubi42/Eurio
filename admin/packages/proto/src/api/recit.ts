/* api/recit.ts — récit (transportation) d'une pièce, en DONNÉES (pas en HTML).
 * Porté depuis renderRecit (coin-detail) : ancré sur les champs réels (thème,
 * pays, année, description), cadrage générique tant que le vrai récit n'est pas
 * sourcé. La vue se charge du rendu. */

import type { Coin, Recit } from './types'

export function deriveRecit(coin: Coin): Recit {
  const country = coin.countryName
  const year = coin.year ?? '—'
  const theme = coin.theme
  const desc = coin.designDescription

  const headline =
    theme || (coin.isCommemorative ? `Une commémorative de ${country}` : `La face nationale · ${country}`)
  const lead = theme
    ? "Derrière ce motif, un fragment d'Europe que peu de gens prennent le temps de lire."
    : `Chaque pièce de circulation porte le récit que ${country} a choisi de graver dans la monnaie de tous les jours.`

  return {
    headline,
    lead,
    event: {
      eyebrow: "L'événement",
      title: theme || 'Le motif',
      body: desc || `Ce que ${country} a voulu célébrer sur cette frappe de ${year}.`,
    },
    context: {
      eyebrow: 'Le contexte',
      title: `${country}, ${year}`,
      body: "Replacer la pièce dans son époque : pourquoi ce sujet, à ce moment, et ce qu'il dit du pays.",
    },
    designers: {
      eyebrow: 'Les créateurs',
      title: 'La main du graveur',
      body: "Le dessin, l'atelier et les choix de composition derrière le relief que tu tiens.",
    },
    place: {
      eyebrow: 'Le lieu',
      title: 'Où ça se passe',
      body: 'Le monument, le paysage ou la figure représentée — et l\'endroit réel auquel il renvoie.',
    },
  }
}
