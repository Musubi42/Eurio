<script setup lang="ts">
/* Scène scan-idle — pseudo-caméra + anneau-guide L. Auto-advance (mock ML) vers
 * la fiche du scan. Au Chunk D, l'auto-advance passera par transition+reveal 3D ;
 * ici on route directement vers coin-detail?ctx=scan (le flux cœur). */
import { onBeforeUnmount, onMounted } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { simulateScan } from '@/api'
import { useCollectionStore } from '@/stores/collection'

const route = useRoute()
const router = useRouter()
const store = useCollectionStore()
const AUTO_MATCH_DELAY_MS = 2000

let timer: ReturnType<typeof setTimeout> | null = null

function resolveScan() {
  // Le faux-scan : l'api choisit une pièce (avec textures). Demain = vraie ML.
  // ?seed=N rend le tirage déterministe (tests automatisés).
  const rawSeed = route.query.seed
  const seed = rawSeed != null && rawSeed !== '' ? Number(rawSeed) : undefined
  const eurioId = simulateScan(Number.isFinite(seed) ? seed : undefined)
  // Flux complet : scan → transition diégétique 3D → reveal → (fiche).
  router.push(`/scan/transition?id=${encodeURIComponent(eurioId)}`)
}

onMounted(() => {
  timer = setTimeout(resolveScan, AUTO_MATCH_DELAY_MS)
})
onBeforeUnmount(() => {
  if (timer) clearTimeout(timer)
})
</script>

<template>
  <section class="scan-idle-root" data-scene="scan-idle">
    <svg class="scan-idle-noise" aria-hidden="true" xmlns="http://www.w3.org/2000/svg">
      <filter id="scan-idle-turb">
        <feTurbulence type="fractalNoise" baseFrequency="1.6" numOctaves="2" seed="4" />
        <feColorMatrix type="matrix" values="0 0 0 0 1  0 0 0 0 1  0 0 0 0 1  0 0 0 0.55 0" />
      </filter>
      <rect width="100%" height="100%" filter="url(#scan-idle-turb)" />
    </svg>

    <div class="scan-idle-header">
      <div class="eyebrow eyebrow--paper">Scan · Eurio</div>
      <div class="scan-idle-header__title">Approche une pièce</div>
    </div>

    <div class="scan-idle-guide" aria-hidden="true">
      <div class="scan-idle-corner scan-idle-corner--tl"></div>
      <div class="scan-idle-corner scan-idle-corner--tr"></div>
      <div class="scan-idle-corner scan-idle-corner--bl"></div>
      <div class="scan-idle-corner scan-idle-corner--br"></div>
    </div>

    <div class="scan-idle-hint">
      <span class="scan-idle-hint__dot" aria-hidden="true"></span>
      <span>En attente — centre la pièce dans le cadre</span>
    </div>

    <button v-if="store.debugMode" type="button" class="scan-idle-debug btn btn-ghost btn-ghost--on-dark" data-debug="on" data-testid="force-match" @click="resolveScan">
      <span class="u-mono">FORCER UN MATCH</span>
    </button>
  </section>
</template>

<style>
.scan-idle-root {
  position: absolute;
  inset: 0;
  background: radial-gradient(ellipse 70% 50% at 50% 55%, var(--ink-soft) 0%, var(--ink) 55%, #000 100%);
  overflow: hidden;
  color: var(--surface);
}
.scan-idle-noise {
  position: absolute;
  inset: 0;
  opacity: 0.14;
  mix-blend-mode: overlay;
  pointer-events: none;
  animation: scan-idle-noise-drift 8s linear infinite;
}
@keyframes scan-idle-noise-drift {
  0% { transform: translate3d(0, 0, 0); }
  50% { transform: translate3d(-4px, -2px, 0); }
  100% { transform: translate3d(0, 0, 0); }
}
.scan-idle-header {
  position: absolute;
  top: 62px;
  left: 50%;
  transform: translateX(-50%);
  text-align: center;
  z-index: 2;
}
.scan-idle-header__title {
  font-family: var(--font-display);
  font-style: italic;
  font-size: var(--text-xl);
  font-weight: 400;
  color: var(--surface);
  letter-spacing: 0.01em;
}
.scan-idle-guide {
  position: absolute;
  top: 48%;
  left: 50%;
  transform: translate(-50%, -50%);
  width: 280px;
  height: 280px;
  pointer-events: none;
  animation: scan-idle-guide-pulse 2.2s var(--ease-in-out) infinite;
}
@keyframes scan-idle-guide-pulse {
  0%, 100% { opacity: 0.55; transform: translate(-50%, -50%) scale(1); }
  50% { opacity: 0.9; transform: translate(-50%, -50%) scale(1.03); }
}
.scan-idle-corner {
  position: absolute;
  width: 26px;
  height: 26px;
  border: 1.6px solid rgba(255, 255, 255, 0.85);
}
.scan-idle-corner--tl { top: 0; left: 0; border-right: 0; border-bottom: 0; border-top-left-radius: 6px; }
.scan-idle-corner--tr { top: 0; right: 0; border-left: 0; border-bottom: 0; border-top-right-radius: 6px; }
.scan-idle-corner--bl { bottom: 0; left: 0; border-right: 0; border-top: 0; border-bottom-left-radius: 6px; }
.scan-idle-corner--br { bottom: 0; right: 0; border-left: 0; border-top: 0; border-bottom-right-radius: 6px; }
.scan-idle-hint {
  position: absolute;
  left: 50%;
  transform: translateX(-50%);
  bottom: 220px;
  display: inline-flex;
  align-items: center;
  gap: var(--space-2);
  padding: 10px 18px;
  background: rgba(0, 0, 0, 0.55);
  backdrop-filter: blur(14px);
  border: 1px solid rgba(255, 255, 255, 0.1);
  border-radius: var(--radius-full);
  font-size: var(--text-sm);
  color: rgba(255, 255, 255, 0.92);
}
.scan-idle-hint__dot {
  width: 7px;
  height: 7px;
  border-radius: 50%;
  background: var(--surface);
  box-shadow: 0 0 10px rgba(255, 255, 255, 0.7);
  animation: scan-idle-dot 1.6s var(--ease-in-out) infinite;
}
@keyframes scan-idle-dot {
  0%, 90%, 100% { opacity: 1; }
  95% { opacity: 0.4; }
}
.scan-idle-debug {
  position: absolute;
  left: 50%;
  transform: translateX(-50%);
  bottom: 140px;
  z-index: 3;
}
</style>
