// Banc de test unitaire du front admin.
//
// Il existe parce que la review en lot perdait des décisions par quatre
// mécanismes distincts, tous côté composant, et qu'aucun n'était vérifiable :
// le package n'avait pas une seule ligne de test. Une décision de review est la
// seule donnée du projet qu'aucun calcul ne régénère — elle mérite un filet.
//
// `vite.config.ts` n'est pas réutilisé tel quel : son plugin `devMiddleware`
// lit `../parity/flows` et `ml/datasets` au démarrage du serveur, ce qui n'a
// aucun sens sous un runner de test. On ne reprend que ce dont les tests ont
// besoin — le plugin Vue et l'alias `@`.
import path from 'node:path'
import vue from '@vitejs/plugin-vue'
import { defineConfig } from 'vitest/config'

export default defineConfig({
  plugins: [vue()],
  resolve: {
    alias: {
      '@': path.resolve(__dirname, './src'),
    },
  },
  test: {
    environment: 'jsdom',
    setupFiles: ['./vitest.setup.ts'],
    include: ['src/**/*.spec.ts'],
  },
})
