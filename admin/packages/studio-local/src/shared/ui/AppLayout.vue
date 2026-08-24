<script setup lang="ts">
import type { NavItem } from '@/app/nav'
import { navSections } from '@/app/nav'
import EurioSessionBanner from '@/shared/ui/EurioSessionBanner.vue'
import LocalOnlyNotice from '@/shared/ui/LocalOnlyNotice.vue'
import { useNavState } from '@/shared/composables/useNavState'
import { useCapabilities } from '@/stores/capabilities'
import { useHeavyGate } from '@/shared/composables/useHeavyGate'
import { useEurioSession } from '@/stores/eurio-session'
import { ChevronsLeft, ChevronsRight } from 'lucide-vue-next'
import { computed, ref } from 'vue'
import { RouterLink, RouterView, useRoute } from 'vue-router'

const route = useRoute()
const session = useEurioSession()
const caps = useCapabilities()
const { badges: navBadges } = useNavState()

// Gating des features lourdes (Model B / R1) : en hébergé (ou API ML locale absente),
// les items `heavy` sont grisés/non-cliquables et les routes `meta.heavy` rendent une
// notice « ceci tourne en local » au lieu de la vue.
//
// D11 — ce rendu grisé est celui de l'ARBITRE sur son poste. Pour un ami (pas de
// `review:arbitrate`), l'entrée n'est pas proposée du tout : elle disparaît de la nav
// comme si elle n'existait pas. Un item grisé portant la pastille « local » lui
// promet un geste qu'il ne pourra jamais faire, et le mène à une page qui parle d'un
// port. Cf. `shared/composables/useHeavyGate`.
const { canArbitrate, showHeavyGesture } = useHeavyGate()
const heavyLocked = computed(() => !caps.hasLocalMlApi)
function isLocked(item: NavItem): boolean {
  return Boolean(item.heavy) && heavyLocked.value
}
const routeLocked = computed(() => Boolean(route.meta.heavy) && heavyLocked.value)

// Gating par DROIT (review-collaborative-v2, lot 4) — second axe, orthogonal au
// précédent. `heavy` répond « cette machine peut-elle ? », `scope` répond « cette
// personne a-t-elle le droit ? ». Un `reviewer` invité ne voit ainsi que Tableau de
// bord / Pièces / Review / Besoin, sans qu'on touche à son rôle.
//
// Tant que le principal n'est pas chargé (`status` idle/loading), on NE filtre PAS :
// sinon la nav clignoterait vide au boot, le temps de l'aller-retour `/me`.
const scopesKnown = computed(() => session.status === 'ok')
function isVisible(item: NavItem): boolean {
  // Tant que le principal n'est pas chargé, on ne filtre RIEN — ni par droit ni
  // par machine. Sans cette garde sur l'axe D11, les entrées lourdes partaient
  // absentes au boot puis réapparaissaient après l'aller-retour `/me` : une nav
  // qui clignote, pour un arbitre qui a le droit de tout voir.
  if (!scopesKnown.value) return true
  // D11 : une entrée lourde hors de portée n'est pas proposée à qui n'arbitre pas.
  if (isLocked(item) && !showHeavyGesture.value) return false
  if (!item.scope) return true
  return session.hasScope(item.scope)
}
// Une section dont tous les items sont masqués disparaît avec son titre.
const visibleSections = computed(() =>
  navSections
    .map((s) => ({ ...s, items: s.items.filter(isVisible) }))
    .filter((s) => s.items.length > 0),
)

// Sidebar repliable en icônes (plus de viewport pour la review). Persisté.
const NAV_COLLAPSED_KEY = 'eurio.nav.collapsed'
const collapsed = ref(localStorage.getItem(NAV_COLLAPSED_KEY) === '1')
function toggleCollapsed() {
  collapsed.value = !collapsed.value
  localStorage.setItem(NAV_COLLAPSED_KEY, collapsed.value ? '1' : '0')
}

function isActive(itemRoute: string) {
  if (itemRoute === '/') return route.path === '/'
  return route.path.startsWith(itemRoute)
}
</script>

<template>
  <div class="flex h-screen overflow-hidden bg-background">
    <!-- Sidebar -->
    <aside class="flex flex-shrink-0 flex-col overflow-y-auto transition-[width] duration-200"
           :class="collapsed ? 'w-16' : 'w-60'"
           style="background: var(--indigo-700);">
      <!-- Brand + bouton repli -->
      <div class="flex h-16 items-center border-b"
           :class="collapsed ? 'justify-center px-0' : 'gap-2 px-5'"
           style="border-color: rgba(255,255,255,0.08);">
        <template v-if="!collapsed">
          <span class="text-xl font-display italic font-semibold leading-none"
                style="color: var(--gold);">
            Eurio
          </span>
          <span class="text-xs font-ui font-medium tracking-widest uppercase mt-0.5"
                style="color: rgba(255,255,255,0.35);">
            Admin
          </span>
        </template>
        <button
          type="button"
          class="flex h-7 w-7 items-center justify-center rounded-md transition-colors hover:bg-white/10"
          :class="collapsed ? '' : 'ml-auto'"
          style="color: rgba(255,255,255,0.5);"
          :title="collapsed ? 'Déplier le menu' : 'Replier le menu'"
          @click="toggleCollapsed"
        >
          <ChevronsRight v-if="collapsed" class="h-4 w-4" />
          <ChevronsLeft v-else class="h-4 w-4" />
        </button>
      </div>

      <!-- Nav -->
      <nav class="flex-1 px-3 py-4" :class="collapsed ? 'space-y-2' : 'space-y-6'">
        <div v-for="section in visibleSections" :key="section.title ?? 'root'">
          <p v-if="section.title && !collapsed"
             class="mb-1 px-2 text-xs font-medium uppercase tracking-widest"
             style="color: rgba(255,255,255,0.3);">
            {{ section.title }}
          </p>
          <div v-else-if="section.title && collapsed"
               class="mx-2 mb-2 h-px" style="background: rgba(255,255,255,0.08);"></div>
          <ul class="space-y-0.5">
            <li v-for="item in section.items" :key="item.id">
              <!-- Item lourd verrouillé (hébergé / API ML absente) → div grisé non-cliquable. -->
              <component
                :is="isLocked(item) ? 'div' : RouterLink"
                :to="isLocked(item) ? undefined : item.route"
                :title="isLocked(item)
                  ? `${item.label} — disponible uniquement en local (lance go-task ml:api puis va sur localhost)`
                  : (collapsed ? item.label : undefined)"
                class="group relative flex items-center rounded-md py-2 text-sm font-medium transition-colors duration-150"
                :class="[
                  collapsed ? 'justify-center px-0' : 'gap-3 px-3',
                  isLocked(item)
                    ? 'cursor-not-allowed opacity-40'
                    : (isActive(item.route) ? 'text-white' : 'hover:bg-white/5'),
                ]"
                :style="!isLocked(item) && isActive(item.route)
                  ? 'background: rgba(255,255,255,0.08); box-shadow: inset 2px 0 0 var(--gold);'
                  : ''"
              >
                <component
                  :is="item.icon"
                  class="h-4 w-4 flex-shrink-0 transition-opacity"
                  :style="isActive(item.route)
                    ? 'color: var(--gold); opacity: 1'
                    : 'color: rgba(255,255,255,0.45); opacity: 0.8'"
                />
                <span v-if="!collapsed" :style="isActive(item.route)
                  ? 'color: white'
                  : 'color: rgba(255,255,255,0.65)'">
                  {{ item.label }}
                </span>
                <!-- Badge : nombre déplié, pastille en icônes-only -->
                <span
                  v-if="navBadges[item.id] && !collapsed"
                  class="ml-auto flex-shrink-0 rounded-full px-1.5 text-xs font-bold leading-5"
                  style="background: var(--gold); color: var(--ink); min-width: 1.25rem; text-align: center;"
                >
                  {{ navBadges[item.id] }}
                </span>
                <span
                  v-else-if="navBadges[item.id] && collapsed"
                  class="absolute top-1 right-1 h-2 w-2 rounded-full"
                  style="background: var(--gold);"
                ></span>
                <!-- Pastille « local » sur les items lourds verrouillés. -->
                <span
                  v-if="isLocked(item) && !collapsed && !navBadges[item.id]"
                  class="ml-auto flex-shrink-0 rounded px-1 text-[10px] font-semibold uppercase tracking-wide"
                  style="background: rgba(255,255,255,0.12); color: rgba(255,255,255,0.7);"
                >
                  local
                </span>
              </component>
            </li>
          </ul>
        </div>
      </nav>

      <!-- User identity (depuis useEurioSession). Pas de signOut : déconnexion
           = retirer/modifier .env.local (cf. PAT-WORKFLOW.md). -->
      <div
        v-if="!collapsed"
        class="p-3 border-t text-xs"
        style="border-color: rgba(255,255,255,0.08); color: rgba(255,255,255,0.55);"
      >
        <template v-if="session.principal">
          <div class="truncate font-medium" style="color: rgba(255,255,255,0.85);">
            {{ session.principal.email }}
          </div>
          <div class="truncate">
            {{ session.principal.roles.join(' · ') }}
          </div>
        </template>
        <template v-else>
          <div class="italic">Non connecté</div>
        </template>
      </div>
    </aside>

    <!-- Main -->
    <main class="flex flex-1 flex-col overflow-hidden">
      <!-- Bandeau eurio-api session (PAT manquant/invalide/erreur) -->
      <EurioSessionBanner />
      <div class="flex-1 overflow-y-auto">
        <LocalOnlyNotice v-if="routeLocked" :technical="canArbitrate" />
        <RouterView v-else />
      </div>
    </main>
  </div>
</template>
