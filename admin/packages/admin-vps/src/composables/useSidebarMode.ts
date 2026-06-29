/**
 * useSidebarMode — détecte le breakpoint courant via matchMedia.
 *
 * Trois modes (cf. admin-vps-FUTURE-WORK.md §F8) :
 *  - `desktop` ≥ 1024px : sidebar fixe
 *  - `tablet`  640–1023px : drawer rétractable (hamburger)
 *  - `mobile`  < 640px   : bottom-nav + overflow drawer
 *
 * Les listeners sont posés au mount et retirés au unmount (pas de fuite).
 */
import { ref, readonly, onMounted, onUnmounted, type Ref } from 'vue'

export type SidebarMode = 'desktop' | 'tablet' | 'mobile'

export function useSidebarMode(): { mode: Readonly<Ref<SidebarMode>> } {
  const mode = ref<SidebarMode>('desktop')

  let mqDesktop: MediaQueryList | null = null
  let mqMobile: MediaQueryList | null = null

  function update() {
    if (mqDesktop?.matches) mode.value = 'desktop'
    else if (mqMobile?.matches) mode.value = 'mobile'
    else mode.value = 'tablet'
  }

  onMounted(() => {
    mqDesktop = window.matchMedia('(min-width: 1024px)')
    mqMobile = window.matchMedia('(max-width: 639px)')
    mqDesktop.addEventListener('change', update)
    mqMobile.addEventListener('change', update)
    update()
  })

  onUnmounted(() => {
    mqDesktop?.removeEventListener('change', update)
    mqMobile?.removeEventListener('change', update)
  })

  return { mode: readonly(mode) }
}
