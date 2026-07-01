import { VueQueryPlugin } from '@tanstack/vue-query'
import { createPinia } from 'pinia'
import { createApp } from 'vue'
import { queryClient } from '../shared/query/client'
import { useCapabilities } from '../stores/capabilities'
import { useEurioSession } from '../stores/eurio-session'
import App from './App.vue'
import router from './router'
import '../styles/index.css'

const app = createApp(App)

app.use(createPinia())
app.use(router)
app.use(VueQueryPlugin, { queryClient })

// Charge la session eurio-api (PAT en local / cookie en hébergé) au boot. Silent
// côté UI — le composant EurioSessionBanner affiche le feedback éventuel.
// eurio-api est désormais la seule source (Supabase retiré côté front, D7).
void useEurioSession().load()

// Résout la capacité ML locale (ping :8042 en local, no-op en hébergé) → gate les
// features lourdes (cf. AppLayout + stores/capabilities).
void useCapabilities().probe()

app.mount('#app')
