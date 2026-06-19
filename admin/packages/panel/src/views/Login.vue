<script setup lang="ts">
import { useAuthStore } from '@/stores/auth'
import { useRoute } from 'vue-router'
import { computed } from 'vue'

const auth = useAuthStore()
const route = useRoute()

const devBypass = import.meta.env.VITE_EURIO_DEV_BYPASS === '1'
const returnTo = computed(() =>
  typeof route.query.return_to === 'string' ? route.query.return_to : undefined,
)

function startLogin() {
  auth.login(returnTo.value)
}
function startDevLogin() {
  auth.devLogin()
}
</script>

<template>
  <div class="login">
    <div class="card">
      <div class="brand">
        <span class="logo" aria-hidden="true">€</span>
        <h1>Eurio panel</h1>
      </div>
      <p class="lead">Connecte-toi via Authentik pour accéder au panel admin.</p>
      <div class="actions">
        <button class="primary" @click="startLogin">Se connecter avec Authentik</button>
        <button v-if="devBypass" class="secondary" @click="startDevLogin">
          Dev bypass (local)
        </button>
      </div>
      <p v-if="auth.error" class="error">{{ auth.error }}</p>
    </div>
  </div>
</template>

<style scoped>
.login {
  min-height: 100vh;
  display: grid;
  place-items: center;
  padding: var(--space-5);
  background: var(--surface);
}
.card {
  width: 100%;
  max-width: 380px;
  padding: var(--space-6);
  background: white;
  border: 1px solid var(--border);
  border-radius: var(--radius-lg);
  box-shadow: 0 4px 20px rgba(20, 20, 47, 0.06);
}
.brand {
  display: flex;
  align-items: center;
  gap: var(--space-3);
  margin-bottom: var(--space-4);
}
.logo {
  display: grid;
  place-items: center;
  width: 36px;
  height: 36px;
  border-radius: 50%;
  background: var(--brand);
  color: var(--accent);
  font-weight: 700;
  font-size: var(--text-lg);
}
h1 {
  margin: 0;
  font-size: var(--text-lg);
  color: var(--text-primary);
}
.lead {
  color: var(--text-secondary);
  font-size: var(--text-sm);
  margin: 0 0 var(--space-5);
}
.actions {
  display: flex;
  flex-direction: column;
  gap: var(--space-3);
}
.actions button {
  width: 100%;
  padding: var(--space-3) var(--space-4);
}
.error {
  color: var(--danger);
  font-size: var(--text-sm);
  margin-top: var(--space-4);
}
</style>
