<script setup lang="ts">
import { computed, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useCollectionStore } from '@/stores/collection'

const route = useRoute()
const router = useRouter()
const store = useCollectionStore()

const chrome = computed(() => route.meta.chrome ?? 'light')
const nav = computed(() => route.meta.nav ?? null)

function go(path: string) {
  router.push(path)
}

// ── Version badge : 7 taps → toggle debug (port de router.js) ──
let taps = 0
let tapTimer: ReturnType<typeof setTimeout> | null = null
const debugOn = ref(store.debugMode)
function tapBadge() {
  taps += 1
  if (tapTimer) clearTimeout(tapTimer)
  tapTimer = setTimeout(() => (taps = 0), 2000)
  if (taps >= 7) {
    taps = 0
    debugOn.value = store.toggleDebug()
  }
}
</script>

<template>
  <div class="app-root">
    <div class="screen" :data-chrome="chrome">
      <!-- Version badge -->
      <button type="button" class="version-badge" data-testid="version-badge" :data-debug="debugOn ? 'on' : 'off'" aria-label="Version v0.1.0, tape 7 fois pour le mode développeur" @click="tapBadge">
        <span>v0.1.0</span>
        <span class="version-badge__led" aria-hidden="true"></span>
      </button>

      <!-- Scene viewport -->
      <main id="view" aria-live="polite">
        <router-view />
      </main>

      <!-- Bottom navigation (masquée sur les sous-pages nav:null — ex. fiche pièce) -->
      <nav v-if="nav" class="bottomnav" aria-label="Navigation principale">
        <button type="button" class="bottomnav__tab" data-nav="vault" data-testid="nav-vault" :aria-current="nav === 'vault' ? 'page' : undefined" @click="go('/vault')">
          <span class="bottomnav__icon" aria-hidden="true">
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round">
              <rect x="3" y="5" width="18" height="14" rx="2" />
              <path d="M3 9h18" />
              <circle cx="8" cy="14" r="1.4" />
            </svg>
          </span>
          <span class="bottomnav__label">Coffre</span>
        </button>

        <button type="button" class="bottomnav__tab bottomnav__tab--scan" data-nav="scan" data-testid="nav-scan" :aria-current="nav === 'scan' ? 'page' : undefined" aria-label="Scanner" @click="go('/scan')">
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">
            <path d="M3 7V5a2 2 0 0 1 2-2h2" />
            <path d="M17 3h2a2 2 0 0 1 2 2v2" />
            <path d="M21 17v2a2 2 0 0 1-2 2h-2" />
            <path d="M7 21H5a2 2 0 0 1-2-2v-2" />
            <circle cx="12" cy="12" r="4" />
          </svg>
        </button>

        <button type="button" class="bottomnav__tab" data-nav="profile" data-testid="nav-profile" :aria-current="nav === 'profile' ? 'page' : undefined" @click="go('/profile')">
          <span class="bottomnav__icon" aria-hidden="true">
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round">
              <circle cx="12" cy="9" r="3.5" />
              <path d="M5 20c1.5-3.5 4.2-5 7-5s5.5 1.5 7 5" />
            </svg>
          </span>
          <span class="bottomnav__label">Profil</span>
        </button>
        <!-- Onglet Marché retiré (T1) : nav à 3 icônes Coffre · Scan · Profil.
             Le marketplace (North Star) reste en germe via les liens « où trouver »
             de la fiche, à réintroduire plus tard. -->
      </nav>
    </div>
  </div>
</template>
