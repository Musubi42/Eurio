<script setup lang="ts">
import { useRoute } from 'vue-router'
const route = useRoute()
</script>

<template>
  <div class="scene-placeholder">
    <div class="eyebrow eyebrow--gold">À venir</div>
    <h2>Scène <code>{{ route.path }}</code> bientôt</h2>
    <p>Cette scène sera migrée dans un chunk ultérieur.</p>
    <p class="eyebrow"><router-link to="/scan" style="color: var(--indigo-700); text-decoration: underline">Retour au scan</router-link></p>
  </div>
</template>

<style>
.scene-placeholder {
  position: absolute;
  inset: 0;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: var(--space-3);
  text-align: center;
  padding: var(--space-8);
  background: var(--surface);
  color: var(--ink);
}
.scene-placeholder h2 {
  font-family: var(--font-display);
  font-style: italic;
  font-weight: 400;
  font-size: var(--text-xl);
}
.scene-placeholder code {
  font-family: var(--font-mono);
  font-size: 0.85em;
  color: var(--indigo-700);
}
</style>
