// Keyboard handler for lot drawer review.
// Nomenclature alignée sur useReviewKeybinds (single) — mêmes touches, sémantique
// adaptée au contexte multi-crop : il y a un "crop actif" dans la liste, J/K
// déplacent le curseur, les actions s'appliquent au crop actif.

import { onMounted, onUnmounted, type Ref } from 'vue'

export interface LotReviewKeybindHandlers {
  onAssignCandidate: (index: number) => void  // 1-5
  onSubmit: () => void                         // Enter (submit listing si allDecided)
  onRejectActive: () => void                   // R (reject reason="other")
  onSkipActive: () => void                     // N
  onOpenSearch: () => void                     // F
  onSetFaceActive: (face: 'obverse' | 'reverse' | 'unknown') => void  // O/V/U
  onNextCrop: () => void                       // J / ↓
  onPrevCrop: () => void                       // K / ↑
  onToggleHelp: () => void                     // ?
  onCloseOverlay: () => void                   // Esc
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

    // Esc passe TOUJOURS — la cascade onCloseOverlay gère la priorité
    // (help → search → bulk reject → bulk → drawer).
    if (e.key === 'Escape') {
      handlers.onCloseOverlay()
      return
    }

    if (!enabled.value) return

    switch (e.key) {
      case '1': case '2': case '3': case '4': case '5': {
        const idx = parseInt(e.key, 10) - 1
        handlers.onAssignCandidate(idx)
        e.preventDefault()
        break
      }
      case 'Enter':
        handlers.onSubmit()
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
      case '?':
        handlers.onToggleHelp()
        e.preventDefault()
        break
    }
  }

  onMounted(() => window.addEventListener('keydown', handle))
  onUnmounted(() => window.removeEventListener('keydown', handle))
}
