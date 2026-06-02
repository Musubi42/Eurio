<script setup lang="ts">
import { onMounted } from 'vue'
import { useRoute, useRouter } from 'vue-router'
const route = useRoute(); const router = useRouter()
const PRESETS: Record<string, { glyph: string; title: string; sub: string }> = {
  'circulation-fr': { glyph: '★', title: 'Série complète France', sub: 'Série 8 / 8 pièces' },
  'circulation-de': { glyph: '✦', title: 'Série complète Allemagne', sub: 'Série 8 / 8 pièces' },
  'eurozone-founding': { glyph: '◎', title: 'Eurozone founding', sub: '12 / 12 pays fondateurs' },
  'grande-chasse': { glyph: '◐', title: 'La grande chasse', sub: '21 / 21 pays de la zone euro' },
  'commemoratives-2e': { glyph: '◇', title: 'Dix 2 € commémoratives', sub: '10 / 10 pièces' },
}
onMounted(() => {
  const setId = String(route.query.setId ?? '') || 'circulation-fr'
  const p = PRESETS[setId] ?? PRESETS['circulation-fr']
  const root = document.querySelector('[data-scene="profile-unlock"]')
  if (!root) return
  const g = root.querySelector('[data-bind="medal-glyph"]'); if (g) g.textContent = p.glyph
  const t = root.querySelector('[data-bind="set-title"]'); if (t) t.textContent = p.title
  const s = root.querySelector('[data-bind="set-sub"]'); if (s) s.textContent = p.sub
})
function onClick(e: MouseEvent) {
  const a = (e.target as HTMLElement).closest('[data-action]')?.getAttribute('data-action')
  if (a === 'continue') router.push('/profile')
}
</script>

<template>
<section @click="onClick" class="profile-unlock-root" data-scene="profile-unlock">
  <div class="profile-unlock-rays" aria-hidden="true"></div>
  <div class="profile-unlock-halo" aria-hidden="true"></div>

  <div class="profile-unlock-medal-wrap">
    <svg class="profile-unlock-arc" viewBox="0 0 260 260" aria-hidden="true">
      <defs>
        <path id="profile-unlock-arc-path"
              d="M 130,130 m -118,0 a 118,118 0 1,1 236,0 a 118,118 0 1,1 -236,0"/>
      </defs>
      <text>
        <textPath href="#profile-unlock-arc-path" startOffset="0">
          · COLLECTION EURIO · MMXXVI · COLLECTION EURIO · MMXXVI ·
        </textPath>
      </text>
    </svg>

    <div class="profile-unlock-medal" role="img" aria-label="Médaille débloquée">
      <span class="profile-unlock-medal__glyph" data-bind="medal-glyph">★</span>
    </div>
  </div>

  <div class="profile-unlock-copy">
    <div class="eyebrow eyebrow--gold profile-unlock-eyebrow">Médaille débloquée</div>
    <h1 class="profile-unlock-title" data-bind="set-title">Série complète France</h1>
    <div class="profile-unlock-sub" data-bind="set-sub">Série 8 / 8 pièces</div>
  </div>

  <button type="button" class="btn btn-gold profile-unlock-cta" data-action="continue">
    Continuer
  </button>
</section>
</template>

<style src="../../styles/profile-unlock.css"></style>
