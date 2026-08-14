import { createPinia } from 'pinia'
import { createApp } from 'vue'
import App from './App.vue'
import { initApi } from './api'
import { router } from './router'
import { useCollectionStore } from './stores/collection'

// CSS — ordre canonique : tokens (R2, shared/) → components → shell.
import '@eurio/shared/tokens.css'
import './styles/components.css'
import './styles/shell.css'

// Hook de test exposé pour Playwright (reset d'état déterministe + navigation + seed).
declare global {
  interface Window {
    __eurio?: {
      reset: () => void
      goto: (path: string) => void
      seed: (name: string) => void
    }
  }
}

// Charge le snapshot AVANT de monter : les getters api sont ensuite synchrones.
async function bootstrap() {
  await initApi()
  const app = createApp(App)
  const pinia = createPinia()
  app.use(pinia)
  app.use(router)

  const collection = useCollectionStore(pinia)
  window.__eurio = {
    reset: () => collection.reset(),
    goto: (path: string) => router.push(path),
    // Applique un état de collection nommé (contrat PARITY_STATE des flows
    // parité). Déterminisme géré dans le store (seedFixture + horloge figée).
    seed: (name: string) => collection.seedFixture(name),
  }

  app.mount('#app')
}

bootstrap().catch((err) => {
  console.error('[proto] bootstrap failed', err)
  const el = document.getElementById('app')
  if (el) el.textContent = `Erreur de chargement : ${err?.message ?? err}`
})
