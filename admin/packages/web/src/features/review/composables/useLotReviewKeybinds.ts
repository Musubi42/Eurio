// Keyboard handler for lot review.
// Aligné sur useReviewKeybinds (single) avec deux spécificités lot :
//   - J/K (et ↓/↑) naviguent entre crops actionables ;
//   - ←/→ naviguent entre raws (multi-image listing) ;
//   - 1-5 focusent un candidat (pas d'assign immédiat → cohérent single).
//
// Enter = validate (assigne le focused au crop actif puis advance, ou
// submit le listing si toutes les décisions sont prises). Esc remonte
// la cascade onCloseOverlay (help / free mode / page).

import { onMounted, onUnmounted, type Ref } from 'vue'

export interface LotReviewKeybindHandlers {
  /** 1-5 : focus un candidat Top N du crop actif (pas d'assign). */
  onCandidateFocus: (index: number) => void
  /** Enter : assigne le focused candidate au crop actif puis advance,
   *  ou submit le listing si allDecided. */
  onValidate: () => void
  /** R : reject le crop actif (raison "other"). */
  onRejectActive: () => void
  /** N : skip le crop actif. */
  onSkipActive: () => void
  /** F : entre en mode 'free' (FreeSelectorPanel inline). */
  onOpenSearch: () => void
  /** O / V / U : face du crop actif (sur assign). */
  onSetFaceActive: (face: 'obverse' | 'reverse' | 'unknown') => void
  /** J / K / ↓ / ↑ : crop suivant / précédent. */
  onNextCrop: () => void
  onPrevCrop: () => void
  /** ← / → : raw suivant / précédent (multi-image listing). */
  onNextRaw: () => void
  onPrevRaw: () => void
  /** ? : toggle help overlay. */
  onToggleHelp: () => void
  /** Esc : cascade fermeture (help → free → bulk → page). */
  onCloseOverlay: () => void
  /** S : requalifier le listing en single (ce n'est pas un lot). */
  onRequalifySingle?: () => void
  /** E : ouvre l'éditeur de re-crop sur le crop actif (aligné single). */
  onRecropActive?: () => void
}

function isTypingTarget(el: EventTarget | null): boolean {
  if (!(el instanceof HTMLElement)) return false
  const tag = el.tagName
  if (tag === 'INPUT' || tag === 'TEXTAREA' || tag === 'SELECT') return true
  if (el.isContentEditable) return true
  return false
}

export function useLotReviewKeybinds(
  enabled: Ref<boolean>,
  handlers: LotReviewKeybindHandlers,
): void {
  function handle(e: KeyboardEvent) {
    if (isTypingTarget(e.target)) return
    if (e.metaKey || e.ctrlKey || e.altKey) return

    // Esc passe TOUJOURS — la cascade onCloseOverlay gère la priorité.
    if (e.key === 'Escape') {
      handlers.onCloseOverlay()
      return
    }

    if (!enabled.value) return

    switch (e.key) {
      case '1': case '2': case '3': case '4': case '5': {
        const idx = parseInt(e.key, 10) - 1
        handlers.onCandidateFocus(idx)
        e.preventDefault()
        break
      }
      case 'Enter':
        handlers.onValidate()
        e.preventDefault()
        break
      case 'r': case 'R':
        handlers.onRejectActive()
        e.preventDefault()
        break
      case 'n': case 'N':
        handlers.onSkipActive()
        e.preventDefault()
        break
      case 'f': case 'F':
        handlers.onOpenSearch()
        e.preventDefault()
        break
      case 'o': case 'O':
        handlers.onSetFaceActive('obverse')
        e.preventDefault()
        break
      case 'v': case 'V':
        handlers.onSetFaceActive('reverse')
        e.preventDefault()
        break
      case 'u': case 'U':
        handlers.onSetFaceActive('unknown')
        e.preventDefault()
        break
      case 'j': case 'J':
      case 'ArrowDown':
        handlers.onNextCrop()
        e.preventDefault()
        break
      case 'k': case 'K':
      case 'ArrowUp':
        handlers.onPrevCrop()
        e.preventDefault()
        break
      case 'ArrowLeft':
        handlers.onPrevRaw()
        e.preventDefault()
        break
      case 'ArrowRight':
        handlers.onNextRaw()
        e.preventDefault()
        break
      case 's': case 'S':
        handlers.onRequalifySingle?.()
        e.preventDefault()
        break
      case 'e': case 'E':
        handlers.onRecropActive?.()
        e.preventDefault()
        break
      case '?':
        handlers.onToggleHelp()
        e.preventDefault()
        break
    }
  }

  onMounted(() => window.addEventListener('keydown', handle))
  onUnmounted(() => window.removeEventListener('keydown', handle))
}
