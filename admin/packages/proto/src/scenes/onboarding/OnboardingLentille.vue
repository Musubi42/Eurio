<script setup lang="ts">
import { onMounted } from 'vue'
import { useRouter } from 'vue-router'
import { useCollectionStore } from '@/stores/collection'
import type { Lens } from '@/stores/collection'
const router = useRouter(); const store = useCollectionStore()
let selected: string | null = store.lens && store.lens !== 'discovery' ? store.lens : null
function paint(root: HTMLElement) {
  root.querySelectorAll('.onb-lens-opt').forEach((o) => o.setAttribute('aria-pressed', (o as HTMLElement).dataset.lens === selected ? 'true' : 'false'))
}
onMounted(() => { const r = document.querySelector('[data-scene="onboarding-lentille"]') as HTMLElement | null; if (r) paint(r) })
function onClick(e: MouseEvent) {
  const root = e.currentTarget as HTMLElement
  const opt = (e.target as HTMLElement).closest('.onb-lens-opt') as HTMLElement | null
  if (opt) { const l = opt.dataset.lens!; selected = selected === l ? null : l; paint(root); return }
  const a = (e.target as HTMLElement).closest('[data-action]')?.getAttribute('data-action')
  if (a === 'next') { store.setLens((selected || 'discovery') as Lens); router.push('/onboarding/permission') }
  else if (a === 'skip') { store.setLens('discovery'); router.push('/onboarding/permission') }
  else if (a === 'back') router.push('/onboarding/3')
}
</script>

<template>
<section @click="onClick" class="onb-lens-root" data-scene="onboarding-lentille">
  <header class="onb-lens-topbar">
    <div class="onb-lens-brand">Eur<em>io</em></div>
    <button type="button" class="onb-lens-skip" data-action="skip">Plus tard</button>
  </header>

  <div class="onb-lens-copy">
    <span class="eyebrow">Ta lentille</span>
    <h1>Qu'est-ce qui t'attire le plus dans une pièce ?</h1>
    <p>Ça oriente ce qu'on met en avant juste après un scan. Modifiable à tout moment.</p>
  </div>

  <div class="onb-lens-options" role="group" aria-label="Choisis ta lentille">
    <button type="button" class="onb-lens-opt" data-lens="histoire" aria-pressed="false">
      <span class="onb-lens-opt__icon" aria-hidden="true">
        <svg viewBox="0 0 24 24"><path d="M4 5a2 2 0 0 1 2-2h7v16H6a2 2 0 0 0-2 2z"/><path d="M13 3h5a2 2 0 0 1 2 2v14a2 2 0 0 0-2 2h-5"/></svg>
      </span>
      <span class="onb-lens-opt__body">
        <span class="onb-lens-opt__title">Histoire</span>
        <span class="onb-lens-opt__desc">Le récit et le sens derrière chaque frappe.</span>
      </span>
      <span class="onb-lens-opt__check" aria-hidden="true"><span>✓</span></span>
    </button>

    <button type="button" class="onb-lens-opt" data-lens="valeur" aria-pressed="false">
      <span class="onb-lens-opt__icon" aria-hidden="true">
        <svg viewBox="0 0 24 24"><circle cx="12" cy="12" r="9"/><path d="M14.5 9.2c-.5-.9-1.5-1.4-2.6-1.4-1.7 0-2.9 1-2.9 2.3 0 3 5.8 1.6 5.8 4.6 0 1.4-1.3 2.3-3 2.3-1.2 0-2.2-.5-2.7-1.5"/><path d="M12 6v12"/></svg>
      </span>
      <span class="onb-lens-opt__body">
        <span class="onb-lens-opt__title">Valeur</span>
        <span class="onb-lens-opt__desc">La cote, la rareté, le tirage.</span>
      </span>
      <span class="onb-lens-opt__check" aria-hidden="true"><span>✓</span></span>
    </button>

    <button type="button" class="onb-lens-opt" data-lens="completer" aria-pressed="false">
      <span class="onb-lens-opt__icon" aria-hidden="true">
        <svg viewBox="0 0 24 24"><rect x="3" y="3" width="7" height="7" rx="1.5"/><rect x="14" y="3" width="7" height="7" rx="1.5"/><rect x="3" y="14" width="7" height="7" rx="1.5"/><path d="M14.5 17.5l2 2 4-4"/></svg>
      </span>
      <span class="onb-lens-opt__body">
        <span class="onb-lens-opt__title">Compléter</span>
        <span class="onb-lens-opt__desc">Boucler les séries et la carte.</span>
      </span>
      <span class="onb-lens-opt__check" aria-hidden="true"><span>✓</span></span>
    </button>
  </div>

  <p class="onb-lens-note">Par défaut : <strong>Découverte</strong> — un peu de tout. Tu changes quand tu veux.</p>

  <div class="onb-lens-cta">
    <button type="button" class="onb-lens-back" data-action="back" aria-label="Retour">←</button>
    <button type="button" class="btn btn-gold" data-action="next">
      <span>Continuer</span>
      <span aria-hidden="true">→</span>
    </button>
  </div>
</section>
</template>

<style src="../../styles/onboarding-lentille.css"></style>
