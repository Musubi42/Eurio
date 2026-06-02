/* api/svg.ts — rendu SVG stylisé d'une pièce (placeholder déterministe).
 * Porté tel quel depuis data.js : couleur métal par valeur faciale, inclinaison
 * seedée par eurio_id. Fonction PURE. */

import type { Coin, CoinSvgOpts } from './types'
import { hashInt } from './util'

interface Metal {
  outer: string[]
  inner: string[]
  text: string
}

const METALS: Record<'copper' | 'nordic' | 'bimetal', Metal> = {
  copper: { outer: ['#E8B892', '#B8714A', '#6B3A1A'], inner: ['#D49A6A', '#8F5120'], text: '#3A1F08' },
  nordic: { outer: ['#F5D98A', '#C8A864', '#8F7637'], inner: ['#E0C078', '#9B7D3A'], text: '#5A4824' },
  bimetal: { outer: ['#F5D98A', '#C8A864', '#8F7637'], inner: ['#E6E4C8', '#B7B59A', '#6B6A52'], text: '#2A2A1A' },
}

function metalFor(cents: number): Metal {
  if (cents <= 5) return METALS.copper
  if (cents <= 50) return METALS.nordic
  return METALS.bimetal
}

function formatFaceValue(cents: number): string {
  if (cents >= 100) {
    const eur = cents / 100
    return Number.isInteger(eur) ? `${eur} €` : `${eur.toFixed(2).replace('.', ',')} €`
  }
  return `${cents} c`
}

export function coinSvg(coin: Coin, opts: CoinSvgOpts = {}): string {
  const size = opts.size ?? 200
  const showLabel = opts.showLabel ?? true
  const metal = metalFor(coin.faceValueCents)
  const isBi = coin.faceValueCents >= 100
  const seed = hashInt(coin.eurioId)
  const tilt = ((seed % 20) - 10) / 20
  const uid = `cg-${seed.toString(36)}`
  const label = formatFaceValue(coin.faceValueCents)
  const labelFont = size * 0.28
  const subFont = size * 0.07

  return `
<svg viewBox="0 0 ${size} ${size}" class="coin-svg" xmlns="http://www.w3.org/2000/svg" role="img" aria-label="${coin.countryName} ${label}">
  <defs>
    <radialGradient id="${uid}-outer" cx="35%" cy="30%" r="80%">
      <stop offset="0%"  stop-color="${metal.outer[0]}"/>
      <stop offset="55%" stop-color="${metal.outer[1]}"/>
      <stop offset="100%" stop-color="${metal.outer[2]}"/>
    </radialGradient>
    <radialGradient id="${uid}-inner" cx="40%" cy="32%" r="75%">
      <stop offset="0%"  stop-color="${metal.inner[0]}"/>
      <stop offset="100%" stop-color="${metal.inner[metal.inner.length - 1]}"/>
    </radialGradient>
  </defs>
  <g transform="rotate(${tilt} ${size / 2} ${size / 2})">
    <circle cx="${size / 2}" cy="${size / 2}" r="${size / 2 - 2}" fill="url(#${uid}-outer)"/>
    <circle cx="${size / 2}" cy="${size / 2}" r="${size / 2 - 2}" fill="none" stroke="rgba(0,0,0,0.35)" stroke-width="1"/>
    <circle cx="${size / 2}" cy="${size / 2}" r="${size * (isBi ? 0.32 : 0.4)}" fill="url(#${uid}-inner)" stroke="rgba(0,0,0,0.25)" stroke-width="0.8"/>
    ${
      showLabel
        ? `<text x="50%" y="52%" text-anchor="middle" dominant-baseline="middle" font-family="Fraunces, Georgia, serif" font-style="italic" font-size="${labelFont}" fill="${metal.text}" letter-spacing="-0.02em">${label}</text>
    <text x="50%" y="${size * 0.76}" text-anchor="middle" font-family="'JetBrains Mono', monospace" font-size="${subFont}" letter-spacing="0.18em" fill="${metal.text}" opacity="0.75">${(coin.year ?? '').toString()}</text>`
        : ''
    }
  </g>
</svg>`
}
