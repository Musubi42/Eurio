<script setup lang="ts">
/* Scène profile-set — planche d'une chase. Port de profile-set.html/.js,
 * recâblé sur lib/achievements.resolveSetView (dérivé de la collection). */
import { computed } from 'vue'
import { useRoute } from 'vue-router'
import { resolveSetView } from '@/lib/achievements'
import { useCollectionStore } from '@/stores/collection'

const route = useRoute()
const store = useCollectionStore()

const setId = computed(() => String(route.params.setId ?? 'circulation-fr'))
const view = computed(() => resolveSetView(setId.value, store.ownedIds))

const ctaSub = computed(() =>
  view.value.missing.length
    ? `Il t'en manque ${view.value.missing.length}`
    : "Série complète — continue d'explorer",
)
</script>

<template>
  <section class="profile-set-root" data-scene="profile-set">
    <div class="profile-set-hero">
      <a class="profile-set-back" href="#/profile/achievements">
        <svg viewBox="0 0 24 24"><path d="M15 18l-6-6 6-6" /></svg>
        Chasses
      </a>
      <div class="eyebrow eyebrow--gold profile-set-eyebrow">{{ view.eyebrow }}</div>
      <h1>{{ view.titleHead }}<br /><em>{{ view.titleEm }}</em></h1>
      <p class="profile-set-hero__sub">{{ view.desc }}</p>
      <div class="profile-set-herometa">
        <div class="profile-set-herometa__prog">
          <div class="profile-set-herometa__lbl">Progression</div>
          <div class="profile-set-herometa__bar">
            <div class="profile-set-herometa__fill" :style="{ width: view.pct + '%' }"></div>
          </div>
        </div>
        <div>
          <div class="profile-set-herometa__big">
            <span>{{ view.have }}</span><small>/<span>{{ view.total }}</span></small>
          </div>
        </div>
      </div>
    </div>

    <div class="profile-set-body">
      <div class="profile-set-planche-head">
        <h2>Le plateau</h2>
        <div class="profile-set-legend">
          <span class="profile-set-legend__item"><span class="profile-set-legend__dot"></span>Acquise</span>
          <span class="profile-set-legend__item"><span class="profile-set-legend__dot is-missing"></span>Manquante</span>
        </div>
      </div>

      <div class="profile-set-planche">
        <div v-for="(cell, i) in view.cells" :key="i" class="profile-set-cell" :class="{ 'is-missing': !cell.owned }">
          <div class="profile-set-disc" :class="cell.owned ? cell.metal : 'is-missing'">
            <div class="profile-set-disc__val">{{ cell.label }}</div>
            <div v-if="cell.owned" class="profile-set-disc__check">✓</div>
          </div>
          <div class="profile-set-cell__info">
            <div class="profile-set-cell__title">{{ cell.label }}</div>
            <div class="profile-set-cell__meta">{{ cell.meta }}</div>
          </div>
        </div>
      </div>

      <div v-if="!view.missing.length" class="profile-set-missing">
        <h3>Série complète</h3>
        <p style="font-size:var(--text-sm);color:var(--ink-400);margin-top:4px;">
          Toutes les pièces du plateau sont à toi. Magnifique.
        </p>
      </div>
      <div v-else class="profile-set-missing">
        <h3>Encore {{ view.missing.length }} pièce{{ view.missing.length > 1 ? 's' : '' }}</h3>
        <ul>
          <li v-for="(m, i) in view.missing" :key="i">
            <span class="profile-set-missing__name">{{ m.label }}</span>
            <span class="profile-set-missing__cta">Scanner</span>
          </li>
        </ul>
      </div>

      <a class="profile-set-cta" href="#/scan">
        <div>
          <div class="profile-set-cta__l">Scanner une pièce manquante</div>
          <div class="profile-set-cta__s">{{ ctaSub }}</div>
        </div>
        <div class="profile-set-cta__ico">
          <svg viewBox="0 0 24 24">
            <rect x="3" y="6" width="18" height="13" rx="2" />
            <path d="M9 6V4h6v2" />
            <circle cx="12" cy="12.5" r="3" />
          </svg>
        </div>
      </a>
    </div>
  </section>
</template>

<style src="../../styles/profile-set.css"></style>
