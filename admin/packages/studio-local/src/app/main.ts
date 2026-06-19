import { VueQueryPlugin } from '@tanstack/vue-query'
import { createPinia } from 'pinia'
import { createApp } from 'vue'
import { queryClient } from '../shared/query/client'
import { useEurioSession } from '../stores/eurio-session'
import App from './App.vue'
import router from './router'
import '../styles/index.css'

const app = createApp(App)

app.use(createPinia())
app.use(router)
app.use(VueQueryPlugin, { queryClient })

// Charge la session eurio-api (via PAT) au boot. Silent côté UI — le
// composant EurioSessionBanner affiche le feedback éventuel. Indépendant
// de l'auth Supabase historique qui reste en place pour les données data.
void useEurioSession().load()

app.mount('#app')
