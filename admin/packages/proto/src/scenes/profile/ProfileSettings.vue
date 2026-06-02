<script setup lang="ts">
/* Scène profile-settings — préférences + debug. Port de profile-settings.html/.js,
 * recâblé sur le store (prefs typées, lens, reset, seed démo). */
import { onBeforeUnmount, ref } from 'vue'
import { useRouter } from 'vue-router'
import { useCollectionStore } from '@/stores/collection'
import type { Lens } from '@/stores/collection'

const router = useRouter()
const store = useCollectionStore()

// ── Toast éphémère ──
const toastText = ref('—')
const toastOn = ref(false)
let toastTimer: ReturnType<typeof setTimeout> | null = null
function toast(text: string) {
  toastText.value = text
  toastOn.value = true
  if (toastTimer) clearTimeout(toastTimer)
  toastTimer = setTimeout(() => (toastOn.value = false), 1800)
}

let navTimer: ReturnType<typeof setTimeout> | null = null
onBeforeUnmount(() => {
  if (toastTimer) clearTimeout(toastTimer)
  if (navTimer) clearTimeout(navTimer)
})

// ── Options ──
const LENS_OPTIONS: { value: Lens; label: string }[] = [
  { value: 'discovery', label: 'Découverte' },
  { value: 'histoire', label: 'Histoire' },
  { value: 'valeur', label: 'Valeur' },
  { value: 'collection', label: 'Série' },
]
const NOTIF_TOGGLES: { key: 'notifHunting' | 'notifSetDone' | 'notifNewCoins'; label: string; help: string }[] = [
  { key: 'notifHunting', label: 'Rappels de chasse', help: 'Un petit signal quand une série est proche' },
  { key: 'notifSetDone', label: 'Complétion de set', help: 'Quand une médaille devient débloquable' },
  { key: 'notifNewCoins', label: 'Nouvelles pièces disponibles', help: "Dès qu'une émission arrive au catalogue" },
]
const FREQ_OPTIONS = [
  { value: 'discrete', label: 'Discrète' },
  { value: 'normale', label: 'Normale' },
] as const
const CATALOG_OPTIONS = [
  { value: 'wifi', label: 'Wi-Fi' },
  { value: 'cell', label: '+ Cellulaire' },
  { value: 'manual', label: 'Manuel' },
] as const

// ── Handlers ──
function onLocale(ev: Event) {
  store.prefs.locale = (ev.target as HTMLSelectElement).value
  store.persist()
  toast('Langue mise à jour')
}
function setLens(value: Lens) {
  store.setLens(value)
  toast('Lentille mise à jour')
}
function toggleNotif(key: 'notifHunting' | 'notifSetDone' | 'notifNewCoins') {
  store.prefs[key] = !store.prefs[key]
  store.persist()
}
function toggleTelemetry() {
  store.prefs.telemetry = !store.prefs.telemetry
  store.persist()
}
function setFreq(value: 'discrete' | 'normale') {
  store.prefs.notifFreq = value
  store.persist()
}
function setCatalog(value: 'wifi' | 'cell' | 'manual') {
  store.prefs.catalogUpdate = value
  store.persist()
}
function goBack() {
  if (window.history.length > 1) router.back()
  else router.push('/profile')
}
function seedDemo() {
  store.seedDemoCollection()
  toast('Démo ajoutée · 15 pièces')
  navTimer = setTimeout(() => router.push('/vault'), 600)
}

const confirmOpen = ref(false)
function doReset() {
  store.reset()
  router.push('/')
}
</script>

<template>
  <section class="profile-settings-root" data-scene="profile-settings">
    <div class="profile-settings-head">
      <button type="button" class="profile-settings-head__back" data-testid="settings-back" aria-label="Retour" @click="goBack">
        <svg viewBox="0 0 24 24"><path d="M15 18l-6-6 6-6" /></svg>
      </button>
      <h1 class="profile-settings-head__title">Paramètres</h1>
    </div>

    <!-- 1. Général -->
    <div class="profile-settings-group">
      <div class="profile-settings-group__head">
        <div class="eyebrow eyebrow--gold">Général</div>
      </div>
      <div class="profile-settings-row">
        <div class="profile-settings-row__label">Langue</div>
        <select class="profile-settings-select" data-testid="pref-locale" :value="store.prefs.locale" @change="onLocale">
          <option value="fr">Français</option>
          <option value="en">English</option>
          <option value="de">Deutsch</option>
          <option value="it">Italiano</option>
        </select>
      </div>
      <div class="profile-settings-row" style="flex-direction:column;align-items:stretch;gap:0;">
        <div style="display:flex;align-items:center;width:100%;">
          <div class="profile-settings-row__label">Thème</div>
          <span class="pill">Bientôt · v2</span>
        </div>
        <div class="profile-settings-seg" role="radiogroup" aria-disabled="true" style="opacity:0.45;pointer-events:none;">
          <button type="button" role="radio" aria-pressed="true" disabled>Clair</button>
          <button type="button" role="radio" aria-pressed="false" disabled>Sombre</button>
          <button type="button" role="radio" aria-pressed="false" disabled>Auto</button>
        </div>
      </div>
    </div>

    <!-- 1bis. Reveal · lentille -->
    <div class="profile-settings-group">
      <div class="profile-settings-group__head">
        <div class="eyebrow eyebrow--gold">Reveal</div>
      </div>
      <div class="profile-settings-row" style="flex-direction:column;align-items:stretch;gap:0;">
        <div style="display:flex;align-items:center;width:100%;">
          <div style="flex:1;">
            <div class="profile-settings-row__label">Ta lentille</div>
            <div class="profile-settings-row__help">Ce qu'on met en avant juste après un scan. Réversible à tout moment.</div>
          </div>
        </div>
        <div class="profile-settings-seg" role="radiogroup" data-testid="pref-lens">
          <button v-for="o in LENS_OPTIONS" :key="o.value" type="button" role="radio" :aria-pressed="store.lens === o.value" @click="setLens(o.value)">{{ o.label }}</button>
        </div>
      </div>
    </div>

    <!-- 2. Notifications -->
    <div class="profile-settings-group">
      <div class="profile-settings-group__head">
        <div class="eyebrow eyebrow--gold">Notifications</div>
        <span class="profile-settings-group__badge">Opt-in</span>
      </div>
      <button v-for="t in NOTIF_TOGGLES" :key="t.key" type="button" class="profile-settings-row" :data-testid="`toggle-${t.key}`" @click="toggleNotif(t.key)">
        <div style="flex:1;">
          <div class="profile-settings-row__label">{{ t.label }}</div>
          <div class="profile-settings-row__help">{{ t.help }}</div>
        </div>
        <div class="profile-settings-toggle" :aria-pressed="store.prefs[t.key]"></div>
      </button>
      <div class="profile-settings-row" style="flex-direction:column;align-items:stretch;gap:0;">
        <div style="display:flex;align-items:center;width:100%;">
          <div style="flex:1;">
            <div class="profile-settings-row__label">Fréquence</div>
            <div class="profile-settings-row__help">Un cadeau, pas du harcèlement — discrète par défaut.</div>
          </div>
        </div>
        <div class="profile-settings-seg" role="radiogroup" data-testid="pref-notif-freq">
          <button v-for="o in FREQ_OPTIONS" :key="o.value" type="button" role="radio" :aria-pressed="store.prefs.notifFreq === o.value" @click="setFreq(o.value)">{{ o.label }}</button>
        </div>
      </div>
    </div>

    <!-- 3. Catalogue -->
    <div class="profile-settings-group">
      <div class="profile-settings-group__head">
        <div class="eyebrow eyebrow--gold">Catalogue</div>
      </div>
      <div class="profile-settings-row" style="flex-direction:column;align-items:stretch;gap:0;">
        <div style="display:flex;align-items:center;width:100%;">
          <div class="profile-settings-row__label">Mise à jour</div>
        </div>
        <div class="profile-settings-seg" role="radiogroup" data-testid="pref-catalog">
          <button v-for="o in CATALOG_OPTIONS" :key="o.value" type="button" role="radio" :aria-pressed="store.prefs.catalogUpdate === o.value" @click="setCatalog(o.value)">{{ o.label }}</button>
        </div>
      </div>
    </div>

    <!-- 4. Données -->
    <div class="profile-settings-group">
      <div class="profile-settings-group__head">
        <div class="eyebrow eyebrow--gold">Données</div>
      </div>
      <div class="profile-settings-btnrow">
        <button type="button" class="btn btn-ghost" @click="toast('Export PDF · bientôt')">
          <span>Exporter le coffre (PDF)</span>
          <svg viewBox="0 0 24 24"><path d="M21 15v4a2 2 0 01-2 2H5a2 2 0 01-2-2v-4M7 10l5 5 5-5M12 15V3" /></svg>
        </button>
        <button type="button" class="btn btn-ghost" @click="toast('Export CSV · bientôt')">
          <span>Exporter le coffre (CSV)</span>
          <svg viewBox="0 0 24 24"><path d="M21 15v4a2 2 0 01-2 2H5a2 2 0 01-2-2v-4M7 10l5 5 5-5M12 15V3" /></svg>
        </button>
      </div>

      <div class="profile-settings-debug">
        <div class="eyebrow profile-settings-debug__eyebrow">Debug</div>
        <div class="profile-settings-btnrow">
          <button type="button" class="btn btn-ghost" data-testid="seed-demo" @click="seedDemo">
            <span>Ajouter 15 pièces de démo</span>
            <svg viewBox="0 0 24 24"><path d="M12 5v14M5 12h14" /></svg>
          </button>
          <button type="button" class="btn btn-ghost btn-danger" data-testid="reset" @click="confirmOpen = true">
            <span>Réinitialiser le prototype</span>
            <svg viewBox="0 0 24 24"><path d="M3 6h18M8 6V4h8v2M10 11v6M14 11v6M5 6l1 14h12l1-14" /></svg>
          </button>
        </div>
        <div class="profile-settings-confirm" :class="{ 'is-on': confirmOpen }">
          <div>Cette action vide ta collection et ramène à l'onboarding. Irréversible.</div>
          <div class="profile-settings-confirm__row">
            <button type="button" class="btn btn-ghost" @click="confirmOpen = false">Annuler</button>
            <button type="button" class="btn btn-danger" data-testid="reset-confirm" @click="doReset">Réinitialiser</button>
          </div>
        </div>
      </div>
    </div>

    <!-- 5. Vie privée -->
    <div class="profile-settings-group">
      <div class="profile-settings-group__head">
        <div class="eyebrow eyebrow--gold">Vie privée</div>
      </div>
      <button type="button" class="profile-settings-row" data-testid="toggle-telemetry" @click="toggleTelemetry">
        <div style="flex:1;">
          <div class="profile-settings-row__label">Télémétrie anonyme</div>
          <div class="profile-settings-row__help">Aide à améliorer l'identification. Aucune donnée perso.</div>
        </div>
        <div class="profile-settings-toggle" :aria-pressed="store.prefs.telemetry"></div>
      </button>
    </div>

    <!-- 6. Compte -->
    <div class="profile-settings-group">
      <div class="profile-settings-group__head">
        <div class="eyebrow eyebrow--gold">Compte</div>
      </div>
      <div class="profile-settings-signin">
        <div class="profile-settings-signin__logo">G</div>
        <div class="profile-settings-signin__label">Google Sign-in</div>
        <span class="pill">Bientôt · v2</span>
      </div>
    </div>

    <!-- 7. À propos -->
    <div class="profile-settings-group">
      <div class="profile-settings-group__head">
        <div class="eyebrow eyebrow--gold">À propos</div>
      </div>
      <div class="profile-settings-about">
        Eurio <b>v0.1.0</b><br />
        <a href="#/profile/settings" @click.prevent="toast('Licences · bientôt')">Licences</a>
        ·
        <a href="#/profile/settings" @click.prevent="toast('Contact · bientôt')">Contact</a>
      </div>
    </div>

    <div class="toast" :class="{ 'is-on': toastOn }">{{ toastText }}</div>
  </section>
</template>

<style src="../../styles/profile-settings.css"></style>
