<script setup lang="ts">
import { useRoute, useRouter } from 'vue-router'
import { computed } from 'vue'

const route = useRoute()
const router = useRouter()

const scope = computed(() =>
  typeof route.query.scope === 'string' ? route.query.scope : null,
)
</script>

<template>
  <div class="not-auth">
    <h2>Accès refusé</h2>
    <p v-if="scope">
      Cette page requiert le scope <code>{{ scope }}</code>, que tu ne possèdes
      pas avec tes rôles actuels.
    </p>
    <p v-else>Tu n'as pas les permissions nécessaires.</p>
    <button class="primary" @click="router.push('/')">Retour à l'accueil</button>
  </div>
</template>

<style scoped>
.not-auth {
  padding: var(--space-6);
  max-width: 600px;
  margin: 0 auto;
  text-align: center;
}
h2 {
  margin: 0 0 var(--space-4);
}
p {
  color: var(--text-secondary);
  margin: 0 0 var(--space-4);
}
code {
  background: var(--surface-2);
  padding: 2px 6px;
  border-radius: var(--radius-sm);
  font-size: var(--text-sm);
}
</style>
