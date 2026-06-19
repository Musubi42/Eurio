<script setup lang="ts">
import { useAuthStore } from '@/stores/auth'
import { useRouter } from 'vue-router'
import { computed } from 'vue'

const auth = useAuthStore()
const router = useRouter()

interface NavItem {
  to: string
  label: string
  scope: string
}

const allItems: NavItem[] = [
  { to: '/sources', label: 'Sources', scope: 'sources:read' },
  { to: '/coins', label: 'Coins', scope: 'coins:read' },
  { to: '/audit', label: 'Audit', scope: 'audit:read' },
  { to: '/review', label: 'Review', scope: 'review:read' },
  { to: '/training', label: 'Training', scope: 'training:run' },
  { to: '/users', label: 'Users', scope: 'users:read' },
  { to: '/me/tokens', label: 'Mes tokens', scope: 'tokens:manage_own' },
]

const navItems = computed(() =>
  allItems.filter((item) => auth.hasScope(item.scope)),
)

async function onLogout() {
  await auth.logout()
  router.push({ name: 'login' })
}
</script>

<template>
  <div class="shell">
    <aside class="sidebar">
      <div class="brand">
        <span class="logo" aria-hidden="true">€</span>
        <span class="title">Eurio panel</span>
      </div>
      <nav>
        <RouterLink to="/" class="nav-item" exact-active-class="active">
          Accueil
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
    <main class="main">
      <header class="topbar">
        <div class="user">
          <span class="email">{{ auth.principal?.email }}</span>
          <span v-for="role in auth.principal?.roles" :key="role" class="role">
            {{ role }}
          </span>
        </div>
        <button @click="onLogout">Déconnexion</button>
      </header>
      <div class="outlet">
        <RouterView />
      </div>
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
.sidebar {
  background: var(--brand);
  color: white;
  padding: var(--space-5) var(--space-4);
  display: flex;
  flex-direction: column;
  gap: var(--space-4);
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
nav {
  display: flex;
  flex-direction: column;
  gap: var(--space-1);
}
.nav-item {
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
.main {
  display: flex;
  flex-direction: column;
  min-width: 0;
}
.topbar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: var(--space-3) var(--space-5);
  background: white;
  border-bottom: 1px solid var(--border);
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
.outlet {
  flex: 1;
  overflow-y: auto;
}
</style>
