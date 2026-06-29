<script setup lang="ts">
/**
 * Notice plein-panneau rendue à la place d'une vue lourde quand `hasLocalMlApi` est faux
 * (hébergé, ou API ML `:8042` non lancée). Model B / R1 — cf. AppLayout + stores/capabilities.
 */
import { useRoute } from 'vue-router'

import { IS_HOSTED } from '@/shared/config/deploy-target'
import { useCapabilities } from '@/stores/capabilities'

const route = useRoute()
const caps = useCapabilities()
</script>

<template>
  <div class="local-only">
    <div class="card">
      <div class="icon">🖥️</div>
      <h2>Cette vue tourne en local</h2>
      <p v-if="IS_HOSTED">
        Les outils de calcul lourd (crop, scrape, training, lab, bench…) appellent l'API ML
        locale et ne sont pas disponibles depuis le panel hébergé.
      </p>
      <p v-else>
        L'API ML locale (<code>http://127.0.0.1:8042</code>) n'est pas joignable
        (statut : <strong>{{ caps.mlStatus }}</strong>).
      </p>
      <ol>
        <li v-if="!IS_HOSTED">Lance l'API ML : <code>go-task ml:api</code></li>
        <li v-else>Sur ta machine : <code>cd admin/packages/studio-local &amp;&amp; pnpm dev</code></li>
        <li v-if="!IS_HOSTED">Recharge cette page.</li>
        <li v-else>
          Ouvre <code>http://localhost:5173{{ route.path }}</code> (auth via ton PAT).
        </li>
      </ol>
    </div>
  </div>
</template>

<style scoped>
.local-only {
  display: flex;
  align-items: center;
  justify-content: center;
  min-height: 60vh;
  padding: var(--space-6, 24px);
}
.card {
  max-width: 32rem;
  text-align: center;
  padding: var(--space-6, 28px);
  border: 1px solid var(--border, #e2e2e2);
  border-radius: var(--radius-lg, 12px);
  background: var(--surface, #fff);
}
.icon {
  font-size: 40px;
  line-height: 1;
  margin-bottom: 12px;
}
h2 {
  font-size: 18px;
  font-weight: 600;
  margin-bottom: 8px;
  color: var(--text, #1a1a1a);
}
p {
  font-size: 14px;
  color: var(--text-secondary, #555);
  margin-bottom: 14px;
}
ol {
  text-align: left;
  display: inline-block;
  font-size: 14px;
  color: var(--text-secondary, #555);
  padding-left: 18px;
}
ol li {
  margin: 4px 0;
}
code {
  font-family: ui-monospace, monospace;
  font-size: 12.5px;
  background: var(--surface-2, #f3f3f3);
  padding: 1px 5px;
  border-radius: 4px;
}
</style>
