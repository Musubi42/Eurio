<script setup lang="ts">
import { useAuthStore } from '@/stores/auth'
import { storeToRefs } from 'pinia'

const auth = useAuthStore()
const { loading } = storeToRefs(auth)
</script>

<template>
  <div v-if="loading" class="boot-loading">
    <span class="spinner" aria-hidden="true" />
    <span>Chargement…</span>
  </div>
  <RouterView v-else />
</template>

<style scoped>
.boot-loading {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: var(--space-3);
  height: 100vh;
  color: var(--text-secondary);
  font-size: var(--text-sm);
}
.spinner {
  width: 18px;
  height: 18px;
  border: 2px solid var(--surface-2);
  border-top-color: var(--brand);
  border-radius: 50%;
  animation: spin 0.8s linear infinite;
}
@keyframes spin {
  to {
    transform: rotate(360deg);
  }
}
</style>
