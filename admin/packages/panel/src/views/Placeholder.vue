<script setup lang="ts">
import { useRoute } from 'vue-router'

const route = useRoute()
</script>

<template>
  <section class="placeholder">
    <h2>{{ route.meta.title || route.name }}</h2>
    <p class="lead">
      Cette section sera portée dans un prochain chunk (C6 review, C7a editorial,
      C7b sets & analytics, C8 users/tokens).
    </p>
    <ul class="meta">
      <li>route : <code>{{ route.fullPath }}</code></li>
      <li v-if="route.meta.scope">scope requis : <code>{{ String(route.meta.scope) }}</code></li>
    </ul>
  </section>
</template>

<style scoped>
.placeholder {
  padding: var(--space-5) var(--space-6);
  max-width: 720px;
}
h2 {
  margin: 0 0 var(--space-3);
  text-transform: capitalize;
}
.lead {
  color: var(--text-secondary);
  margin: 0 0 var(--space-4);
}
.meta {
  list-style: none;
  padding: 0;
  margin: 0;
  display: flex;
  flex-direction: column;
  gap: var(--space-2);
  font-size: var(--text-sm);
  color: var(--text-secondary);
}
code {
  background: var(--surface-2);
  padding: 2px 6px;
  border-radius: var(--radius-sm);
}
</style>
