<script setup lang="ts">
/**
 * AppShell — layout responsive mobile-first (cf. F8, admin-vps-FUTURE-WORK.md).
 *
 *  - desktop ≥ 1024px : sidebar fixe (comme avant)
 *  - tablet 640–1023px : top app bar + drawer rétractable (hamburger)
 *  - mobile < 640px : bottom-nav (icônes) + overflow "Plus" → drawer
 *
 * Touch targets ≥ 44px sur tous les éléments interactifs nav.
 */
import { useAuthStore } from '@/stores/auth'
import { useRouter, useRoute } from 'vue-router'
import { computed, ref, watch } from 'vue'

import { useSidebarMode } from '@/composables/useSidebarMode'
import { NAV_ICONS, type IconName } from './navIcons'

const auth = useAuthStore()
const router = useRouter()
const route = useRoute()
const { mode } = useSidebarMode()

interface NavItem {
  to: string
  label: string
  scope: string
  icon: IconName
}

const allItems: NavItem[] = [
  { to: '/sources', label: 'Sources', scope: 'sources:read', icon: 'sources' },
  { to: '/coins', label: 'Coins', scope: 'coins:read', icon: 'coins' },
  { to: '/audit', label: 'Audit', scope: 'audit:read', icon: 'audit' },
  { to: '/training', label: 'Training', scope: 'training:run', icon: 'training' },
  { to: '/users', label: 'Users', scope: 'users:read', icon: 'users' },
  { to: '/me/tokens', label: 'Mes tokens', scope: 'tokens:manage_own', icon: 'tokens' },
]

const homeItem: NavItem = { to: '/', label: 'Accueil', scope: '', icon: 'home' }

const navItems = computed(() =>
  allItems.filter((item) => auth.hasScope(item.scope)),
)

// Bottom-nav : Accueil + 3 premiers items autorisés, le reste sous "Plus".
const bottomItems = computed(() => [homeItem, ...navItems.value.slice(0, 3)])
const hasOverflow = computed(() => navItems.value.length > 3)

const userInitial = computed(() =>
  (auth.principal?.name || auth.principal?.email || '?').charAt(0).toUpperCase(),
)

// Drawer (tablet + overflow mobile)
const drawerOpen = ref(false)
function closeDrawer() {
  drawerOpen.value = false
}

// Fermer le drawer au changement de route et quand on repasse desktop.
watch(() => route.fullPath, closeDrawer)
watch(mode, (m) => {
  if (m === 'desktop') drawerOpen.value = false
})

async function onLogout() {
  await auth.logout()
  router.push({ name: 'login' })
}
</script>

<template>
  <div class="shell" :data-mode="mode">
    <!-- Sidebar fixe (desktop) -->
    <aside v-if="mode === 'desktop'" class="sidebar">
      <div class="brand">
        <span class="logo" aria-hidden="true">€</span>
        <span class="title">Eurio panel</span>
      </div>
      <nav>
        <RouterLink :to="homeItem.to" class="nav-item" exact-active-class="active">
          {{ homeItem.label }}
        </RouterLink>
        <RouterLink
          v-for="item in navItems"
          :key="item.to"
          :to="item.to"
          class="nav-item"
          active-class="active"
        >
          {{ item.label }}
        </RouterLink>
      </nav>
    </aside>

    <!-- Drawer overlay (tablet + overflow mobile) -->
    <Transition name="drawer">
      <div
        v-if="drawerOpen"
        class="drawer-backdrop"
        @click.self="closeDrawer"
      >
        <aside class="drawer">
          <div class="brand">
            <span class="logo" aria-hidden="true">€</span>
            <span class="title">Eurio panel</span>
            <button class="icon-btn close" aria-label="Fermer" @click="closeDrawer">✕</button>
          </div>
          <nav>
            <RouterLink :to="homeItem.to" class="nav-item" exact-active-class="active">
              {{ homeItem.label }}
            </RouterLink>
            <RouterLink
              v-for="item in navItems"
              :key="item.to"
              :to="item.to"
              class="nav-item"
              active-class="active"
            >
              {{ item.label }}
            </RouterLink>
          </nav>
          <button class="drawer-logout" @click="onLogout">Déconnexion</button>
        </aside>
      </div>
    </Transition>

    <main class="main">
      <header class="topbar">
        <button
          v-if="mode !== 'desktop'"
          class="icon-btn hamburger"
          aria-label="Menu"
          @click="drawerOpen = true"
        >
          ☰
        </button>
        <span v-if="mode !== 'desktop'" class="topbar-brand">Eurio</span>
        <div class="spacer" />
        <div class="user">
          <template v-if="mode === 'desktop'">
            <span class="email">{{ auth.principal?.email }}</span>
            <span v-for="role in auth.principal?.roles" :key="role" class="role">
              {{ role }}
            </span>
          </template>
          <span v-else class="avatar" :title="auth.principal?.email">{{ userInitial }}</span>
        </div>
        <button v-if="mode === 'desktop'" @click="onLogout">Déconnexion</button>
      </header>

      <div class="outlet" :class="{ 'has-bottom-nav': mode === 'mobile' }">
        <RouterView />
      </div>

      <!-- Bottom-nav (mobile) -->
      <nav v-if="mode === 'mobile'" class="bottom-nav">
        <RouterLink
          v-for="item in bottomItems"
          :key="item.to"
          :to="item.to"
          class="bn-item"
          :exact-active-class="item.to === '/' ? 'active' : undefined"
          :active-class="item.to === '/' ? undefined : 'active'"
        >
          <svg viewBox="0 0 24 24" aria-hidden="true"><path :d="NAV_ICONS[item.icon]" /></svg>
          <span>{{ item.label }}</span>
        </RouterLink>
        <button v-if="hasOverflow" class="bn-item" @click="drawerOpen = true">
          <svg viewBox="0 0 24 24" aria-hidden="true"><path :d="NAV_ICONS.more" /></svg>
          <span>Plus</span>
        </button>
      </nav>
    </main>
  </div>
</template>

<style scoped>
.shell {
  display: grid;
  grid-template-columns: 240px 1fr;
  height: 100vh;
  background: var(--surface);
}
.shell[data-mode='tablet'],
.shell[data-mode='mobile'] {
  grid-template-columns: 1fr;
}

/* ── Sidebar / drawer partagent le style nav ──────────────────────────── */
.sidebar,
.drawer {
  background: var(--brand);
  color: white;
  padding: var(--space-5) var(--space-4);
  display: flex;
  flex-direction: column;
  gap: var(--space-4);
}
.drawer {
  width: 264px;
  max-width: 80vw;
  height: 100%;
}
.brand {
  display: flex;
  align-items: center;
  gap: var(--space-3);
  padding: var(--space-2) var(--space-3);
}
.logo {
  display: grid;
  place-items: center;
  width: 28px;
  height: 28px;
  border-radius: 50%;
  background: rgba(255, 255, 255, 0.12);
  color: var(--accent);
  font-weight: 700;
}
.title {
  font-weight: 600;
}
.close {
  margin-left: auto;
  color: white;
}
nav {
  display: flex;
  flex-direction: column;
  gap: var(--space-1);
}
.nav-item {
  display: flex;
  align-items: center;
  min-height: 44px;
  color: rgba(255, 255, 255, 0.78);
  padding: var(--space-2) var(--space-3);
  border-radius: var(--radius-sm);
  font-size: var(--text-sm);
}
.nav-item:hover {
  background: rgba(255, 255, 255, 0.08);
  color: white;
  text-decoration: none;
}
.nav-item.active {
  background: rgba(255, 255, 255, 0.16);
  color: white;
}
.drawer-logout {
  margin-top: auto;
  background: rgba(255, 255, 255, 0.12);
  color: white;
  border-color: transparent;
  min-height: 44px;
}
.drawer-logout:hover {
  background: rgba(255, 255, 255, 0.2);
}

/* ── Drawer overlay ───────────────────────────────────────────────────── */
.drawer-backdrop {
  position: fixed;
  inset: 0;
  background: rgba(0, 0, 0, 0.45);
  z-index: 100;
  display: flex;
}
.drawer-enter-active,
.drawer-leave-active {
  transition: opacity 0.18s ease;
}
.drawer-enter-active .drawer,
.drawer-leave-active .drawer {
  transition: transform 0.18s ease;
}
.drawer-enter-from,
.drawer-leave-to {
  opacity: 0;
}
.drawer-enter-from .drawer,
.drawer-leave-to .drawer {
  transform: translateX(-100%);
}

/* ── Main ─────────────────────────────────────────────────────────────── */
.main {
  display: flex;
  flex-direction: column;
  min-width: 0;
}
.topbar {
  display: flex;
  align-items: center;
  gap: var(--space-3);
  padding: var(--space-3) var(--space-5);
  background: white;
  border-bottom: 1px solid var(--border);
}
.spacer {
  flex: 1;
}
.icon-btn {
  display: grid;
  place-items: center;
  width: 44px;
  height: 44px;
  border: none;
  background: transparent;
  font-size: var(--text-lg);
  border-radius: var(--radius-sm);
  cursor: pointer;
}
.icon-btn:hover {
  background: var(--surface-2);
}
.topbar-brand {
  font-weight: 600;
}
.user {
  display: flex;
  align-items: center;
  gap: var(--space-3);
}
.email {
  font-size: var(--text-sm);
  color: var(--text-primary);
}
.role {
  font-size: var(--text-xs);
  background: var(--surface-2);
  color: var(--text-secondary);
  padding: 2px 8px;
  border-radius: 999px;
  text-transform: capitalize;
}
.avatar {
  display: grid;
  place-items: center;
  width: 34px;
  height: 34px;
  border-radius: 50%;
  background: var(--brand);
  color: white;
  font-weight: 600;
  font-size: var(--text-sm);
}
.outlet {
  flex: 1;
  overflow-y: auto;
}
.outlet.has-bottom-nav {
  /* laisser respirer le contenu au-dessus de la bottom-nav (56px + safe area) */
  padding-bottom: calc(56px + env(safe-area-inset-bottom, 0px));
}

/* ── Bottom-nav (mobile) ──────────────────────────────────────────────── */
.bottom-nav {
  position: fixed;
  left: 0;
  right: 0;
  bottom: 0;
  display: flex;
  flex-direction: row;
  background: white;
  border-top: 1px solid var(--border);
  padding-bottom: env(safe-area-inset-bottom, 0px);
  z-index: 50;
}
.bn-item {
  flex: 1;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 2px;
  min-height: 56px;
  padding: var(--space-2) 0;
  border: none;
  background: transparent;
  color: var(--text-secondary);
  font-size: var(--text-xs);
  cursor: pointer;
}
.bn-item svg {
  width: 22px;
  height: 22px;
  fill: currentColor;
}
.bn-item.active {
  color: var(--brand);
}
.bn-item:hover {
  text-decoration: none;
  color: var(--text-primary);
}
</style>
