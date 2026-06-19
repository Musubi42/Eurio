<script setup lang="ts">
import { useAuthStore } from '@/stores/auth'

const auth = useAuthStore()
</script>

<template>
  <section class="home">
    <h2>Bienvenue {{ auth.principal?.name || auth.principal?.email }}</h2>
    <p class="lead">
      Tu es connecté avec
      <strong>{{ auth.principal?.email }}</strong>
      via <code>{{ auth.principal?.auth_method }}</code>.
    </p>
    <div class="grid">
      <article class="info">
        <h3>Rôles</h3>
        <ul>
          <li v-for="r in auth.principal?.roles" :key="r">
            <span class="badge">{{ r }}</span>
          </li>
        </ul>
      </article>
      <article class="info">
        <h3>Scopes effectifs</h3>
        <ul class="scopes">
          <li v-for="s in auth.principal?.scopes" :key="s">
            <code>{{ s }}</code>
          </li>
        </ul>
      </article>
    </div>
  </section>
</template>

<style scoped>
.home {
  padding: var(--space-5) var(--space-6);
  max-width: 960px;
}
h2 {
  margin: 0 0 var(--space-3);
  font-size: var(--text-xl);
}
.lead {
  color: var(--text-secondary);
  margin: 0 0 var(--space-5);
}
.grid {
  display: grid;
  grid-template-columns: 1fr 2fr;
  gap: var(--space-5);
}
.info {
  background: white;
  border: 1px solid var(--border);
  border-radius: var(--radius-md);
  padding: var(--space-5);
}
.info h3 {
  margin: 0 0 var(--space-3);
  font-size: var(--text-sm);
  color: var(--text-secondary);
  text-transform: uppercase;
  letter-spacing: 0.04em;
}
ul {
  list-style: none;
  padding: 0;
  margin: 0;
  display: flex;
  flex-wrap: wrap;
  gap: var(--space-2);
}
.scopes li {
  font-size: var(--text-xs);
}
.badge {
  background: var(--brand);
  color: white;
  padding: var(--space-1) var(--space-3);
  border-radius: 999px;
  font-size: var(--text-xs);
  text-transform: capitalize;
}
code {
  background: var(--surface-2);
  padding: 2px 6px;
  border-radius: var(--radius-sm);
  font-size: var(--text-xs);
}
</style>
