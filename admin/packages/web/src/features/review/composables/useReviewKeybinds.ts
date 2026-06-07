// Keyboard handler for /review.
// Skip si l'utilisateur est en train de taper dans un input/textarea ou si une
// modale couvre l'écran (callsite passe `enabled` en signal).

import { onMounted, onUnmounted, type Ref } from 'vue'

export interface ReviewKeybindHandlers {
  onCandidateFocus: (index: number) => void
  onValidate: () => void
  onReject: () => void
  onSkip: () => void
  onOpenSearch: () => void
  onCloseOverlay: () => void
  onSetFace: (face: 'obverse' | 'reverse' | 'unknown') => void
  // Chunk C4 — correction opt-in du contexte listing. Cycle la valeur
  // du badge ; n'interfère pas avec le ⏎ d'attribution.
  onCycleKind: () => void
  onCycleCondition: () => void
  // Chunk Cr — accepter la suggestion DINOv2 top-1 en 1 clic.
  // No-op si dino_top1 est null (le callsite vérifie avant d'agir).
  onAcceptDino?: () => void
  // E — ouvrir l'éditeur de recadrage manuel (R est pris par Reject).
  onRecrop?: () => void
  // L — requalifier le crop courant (et son listing) en LOT : il quitte la
  // queue single et bascule dans le flow lot. No-op si pas d'item courant.
  onRequalifyLot?: () => void
}

function isTypingTarget(el: EventTarget | null): boolean {
  if (!(el instanceof HTMLElement)) return false
  const tag = el.tagName
  if (tag === 'INPUT' || tag === 'TEXTAREA' || tag === 'SELECT') return true
  if (el.isContentEditable) return true
  return false
}

export function useReviewKeybinds(
  enabled: Ref<boolean>,
  handlers: ReviewKeybindHandlers,
): void {
  function handle(e: KeyboardEvent) {
    if (!enabled.value) return
    if (isTypingTarget(e.target)) return
    if (e.metaKey || e.ctrlKey || e.altKey) return

    // Esc passe TOUJOURS (utile pour fermer overlay même si overlay focus)
    if (e.key === 'Escape') {
      handlers.onCloseOverlay()
      return
    }

    switch (e.key) {
      case '1':
      case '2':
      case '3':
      case '4':
      case '5': {
        const idx = parseInt(e.key, 10) - 1
        handlers.onCandidateFocus(idx)
        e.preventDefault()
        break
      }
      case 'Enter':
        handlers.onValidate()
        e.preventDefault()
        break
      case 'r':
      case 'R':
        handlers.onReject()
        e.preventDefault()
        break
      case 'n':
      case 'N':
        handlers.onSkip()
        e.preventDefault()
        break
      case 'f':
      case 'F':
        handlers.onOpenSearch()
        e.preventDefault()
        break
      case 'o':
      case 'O':
        handlers.onSetFace('obverse')
        e.preventDefault()
        break
      case 'v':
      case 'V':
        handlers.onSetFace('reverse')
        e.preventDefault()
        break
      case 'u':
      case 'U':
        handlers.onSetFace('unknown')
        e.preventDefault()
        break
      case 'k':
      case 'K':
        handlers.onCycleKind()
        e.preventDefault()
        break
      case 'c':
      case 'C':
        handlers.onCycleCondition()
        e.preventDefault()
        break
      case 'd':
      case 'D':
        handlers.onAcceptDino?.()
        e.preventDefault()
        break
      case 'e':
      case 'E':
        handlers.onRecrop?.()
        e.preventDefault()
        break
      case 'l':
      case 'L':
        handlers.onRequalifyLot?.()
        e.preventDefault()
        break
    }
  }

  onMounted(() => window.addEventListener('keydown', handle))
  onUnmounted(() => window.removeEventListener('keydown', handle))
}
