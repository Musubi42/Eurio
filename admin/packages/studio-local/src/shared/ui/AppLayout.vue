<script setup lang="ts">
import { navSections } from '@/app/nav'
import EurioSessionBanner from '@/shared/ui/EurioSessionBanner.vue'
import { DEV_BYPASS, supabase } from '@/shared/supabase/client'
import { useNavState } from '@/shared/composables/useNavState'
import { ChevronsLeft, ChevronsRight, LogOut } from 'lucide-vue-next'
import { ref } from 'vue'
import { RouterLink, RouterView, useRoute } from 'vue-router'
import { useRouter } from 'vue-router'

const router = useRouter()
const route = useRoute()
const signingOut = ref(false)
const { badges: navBadges } = useNavState()

// Sidebar repliable en icônes (plus de viewport pour la review). Persisté.
const NAV_COLLAPSED_KEY = 'eurio.nav.collapsed'
const collapsed = ref(localStorage.getItem(NAV_COLLAPSED_KEY) === '1')
function toggleCollapsed() {
  collapsed.value = !collapsed.value
  localStorage.setItem(NAV_COLLAPSED_KEY, collapsed.value ? '1' : '0')
}

async function signOut() {
  signingOut.value = true
  await supabase.auth.signOut()
  router.push('/login')
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
        <div v-for="section in navSections" :key="section.title ?? 'root'">
          <p v-if="section.title && !collapsed"
             class="mb-1 px-2 text-xs font-medium uppercase tracking-widest"
             style="color: rgba(255,255,255,0.3);">
            {{ section.title }}
          </p>
          <div v-else-if="section.title && collapsed"
               class="mx-2 mb-2 h-px" style="background: rgba(255,255,255,0.08);"></div>
          <ul class="space-y-0.5">
            <li v-for="item in section.items" :key="item.id">
              <RouterLink
                :to="item.route"
                :title="collapsed ? item.label : undefined"
                class="group relative flex items-center rounded-md py-2 text-sm font-medium transition-colors duration-150"
                :class="[
                  collapsed ? 'justify-center px-0' : 'gap-3 px-3',
                  isActive(item.route) ? 'text-white' : 'hover:bg-white/5',
                ]"
                :style="isActive(item.route)
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
              </RouterLink>
            </li>
          </ul>
        </div>
      </nav>

      <!-- Sign out -->
      <div class="p-3 border-t" style="border-color: rgba(255,255,255,0.08);">
        <button
          @click="signOut"
          :disabled="signingOut"
          :title="collapsed ? 'Se déconnecter' : undefined"
          class="flex w-full items-center rounded-md py-2 text-sm transition-colors hover:bg-white/5 disabled:opacity-50"
          :class="collapsed ? 'justify-center px-0' : 'gap-3 px-3'"
          style="color: rgba(255,255,255,0.45);"
        >
          <LogOut class="h-4 w-4 flex-shrink-0" />
          <span v-if="!collapsed">{{ signingOut ? 'Déconnexion…' : 'Se déconnecter' }}</span>
        </button>
      </div>
    </aside>

    <!-- Main -->
    <main class="flex flex-1 flex-col overflow-hidden">
      <!-- Bandeau eurio-api session (PAT manquant/invalide/erreur) -->
      <EurioSessionBanner />
      <!-- Bandeau dev bypass -->
      <div v-if="DEV_BYPASS"
           class="flex items-center justify-center gap-2 px-4 py-1.5 text-xs font-mono font-medium"
           style="background: var(--warning); color: var(--ink);">
        ⚠ MODE DEV — service_role key active, auth bypassée, RLS désactivée
      </div>
      <div class="flex-1 overflow-y-auto">
        <RouterView />
      </div>
    </main>
  </div>
</template>
