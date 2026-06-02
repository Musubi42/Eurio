<script setup lang="ts">
/* Scène profile (home) — centre de progression. Port de profile.html/.js,
 * recâblé sur le store collection + lib/achievements (chasses) + TIERS. */
import { computed, onMounted } from 'vue'
import { useRouter } from 'vue-router'
import { TIERS } from '@/api/fixtures/achievements'
import { listChases } from '@/lib/achievements'
import { useCollectionStore } from '@/stores/collection'

const router = useRouter()
const store = useCollectionStore()

const ORDINALS = ['I', 'II', 'III', 'IV']
const NODE_LEFTS = [0, 33, 66, 100]
const SEGMENT = 100 / 3

// ── Redirection célébration : un set vient d'être complété → unlock une fois ──
onMounted(() => {
  if (store.level.pendingUnlock) {
    const setId = store.consumePendingUnlock()
    if (setId) router.replace(`/profile/unlock?setId=${encodeURIComponent(setId)}`)
  }
})

const count = computed(() => store.collection.length)
const ownedIds = computed(() => store.ownedIds)

// ── Niveau / rang ──
const tierIdx = computed(() => Math.max(0, TIERS.findIndex((t) => t.name === store.level.tier)))
const tier = computed(() => TIERS[tierIdx.value])
const pct = computed(() => store.level.progressPct || 0)
const ord = computed(() => ORDINALS[tierIdx.value] || 'I')
const caption = computed(() => tier.value.caption)

const fillPct = computed(() => Math.min(100, tierIdx.value * SEGMENT + (pct.value / 100) * SEGMENT))

interface Hint {
  html: string
}
const ladderHint = computed<Hint>(() => {
  const t = tier.value
  if (t.nextAt == null) return { html: 'Tu as atteint le rang le plus élevé.' }
  const remaining = Math.max(0, t.nextAt - count.value)
  const nextName = TIERS[tierIdx.value + 1]?.name ?? ''
  if (remaining === 0) return { html: `Tu peux passer <b>${nextName}</b>` }
  return { html: `Encore <b>${remaining} pièce${remaining > 1 ? 's' : ''}</b> pour devenir ${nextName}` }
})

function nodeClass(i: number): Record<string, boolean> {
  return { 'is-done': i < tierIdx.value, 'is-current': i === tierIdx.value }
}

// ── Stats ──
const distinctCountries = computed(() => new Set([...ownedIds.value].map((id) => id.slice(0, 2).toUpperCase())).size)
const totalValueCents = computed(() => store.collection.reduce((acc, c) => acc + (c.valueAtAddCents ?? 0), 0))
const valueInt = computed(() => (totalValueCents.value > 0 ? String(Math.round(totalValueCents.value / 100)) : '—'))

// ── Chasses en cours (plafonné à 3 prochains, anti-surcharge Zeigarnik) ──
const chases = computed(() => listChases(ownedIds.value).filter((a) => !a.unlocked && a.have > 0).slice(0, 3))

function openSettings() {
  router.push('/profile/settings')
}
</script>

<template>
  <section class="profile-home-root" data-scene="profile">
    <!-- Hero -->
    <div class="profile-home-hero">
      <div class="profile-home-seal" aria-hidden="true"></div>
      <div class="profile-home-year" aria-hidden="true">MMXXVI</div>

      <div class="profile-home-topbar">
        <div class="profile-home-brand">
          <span class="profile-home-brand__dot" aria-hidden="true"></span>
          Eurio
        </div>
        <button type="button" class="profile-home-iconbtn" data-testid="profile-settings" aria-label="Paramètres" @click="openSettings">
          <svg viewBox="0 0 24 24" aria-hidden="true">
            <circle cx="12" cy="12" r="3" />
            <path d="M19.4 15a1.65 1.65 0 00.33 1.82l.06.06a2 2 0 01-2.83 2.83l-.06-.06a1.65 1.65 0 00-1.82-.33 1.65 1.65 0 00-1 1.51V21a2 2 0 01-4 0v-.09A1.65 1.65 0 009 19.4a1.65 1.65 0 00-1.82.33l-.06.06a2 2 0 01-2.83-2.83l.06-.06A1.65 1.65 0 004.6 15a1.65 1.65 0 00-1.51-1H3a2 2 0 010-4h.09A1.65 1.65 0 004.6 9a1.65 1.65 0 00-.33-1.82l-.06-.06a2 2 0 012.83-2.83l.06.06A1.65 1.65 0 009 4.6a1.65 1.65 0 001-1.51V3a2 2 0 014 0v.09a1.65 1.65 0 001 1.51 1.65 1.65 0 001.82-.33l.06-.06a2 2 0 012.83 2.83l-.06.06A1.65 1.65 0 0019.4 9a1.65 1.65 0 001.51 1H21a2 2 0 010 4h-.09a1.65 1.65 0 00-1.51 1z" />
          </svg>
        </button>
      </div>

      <div class="eyebrow eyebrow--gold profile-home-eyebrow">Niveau · rang {{ ord }} de IV</div>
      <h1 class="profile-home-level">
        <span>{{ tier.name }}</span>
        <span class="profile-home-level__ord">{{ ord }} / IV</span>
      </h1>
      <div class="profile-home-level__caption">{{ caption }}</div>

      <div class="profile-home-ladder">
        <div class="profile-home-ladder__labels">
          <span v-for="(t, i) in TIERS" :key="t.name" :class="nodeClass(i)">{{ t.name }}</span>
        </div>
        <div class="profile-home-ladder__bar">
          <div class="profile-home-ladder__fill" :style="{ width: fillPct + '%' }"></div>
          <div v-for="(left, i) in NODE_LEFTS" :key="i" class="profile-home-ladder__node" :class="nodeClass(i)" :style="{ left: left + '%' }"></div>
        </div>
        <div class="profile-home-ladder__hint">
          <span v-html="ladderHint.html"></span>
          <span class="profile-home-ladder__pct">{{ pct }}%</span>
        </div>
      </div>
    </div>

    <!-- Body -->
    <div class="profile-home-body">
      <!-- Stats -->
      <div class="profile-home-stats">
        <div class="profile-home-stat">
          <div class="profile-home-stat__k">Pièces</div>
          <div class="profile-home-stat__v">{{ count }}</div>
          <div class="profile-home-stat__sub">
            <template v-if="count === 0">Aucune encore</template>
            <template v-else><span class="up">+{{ count }}</span> ce mois</template>
          </div>
        </div>
        <div class="profile-home-stat">
          <div class="profile-home-stat__k">Pays</div>
          <div class="profile-home-stat__v"><span>{{ distinctCountries }}</span><small>/21</small></div>
          <div class="profile-home-stat__sub">Zone euro</div>
        </div>
        <div class="profile-home-stat">
          <div class="profile-home-stat__k">Valeur</div>
          <div class="profile-home-stat__v"><span>{{ valueInt }}</span><small v-if="totalValueCents > 0"> €</small></div>
          <div class="profile-home-stat__sub">
            <template v-if="totalValueCents > 0"><span class="up">↑ 34%</span></template>
            <template v-else>Coffre vide</template>
          </div>
        </div>
      </div>

      <!-- Chasses en cours -->
      <div class="profile-home-section">
        <h2>Tes 3 prochains</h2>
        <a href="#/profile/achievements">Tout voir</a>
      </div>
      <div class="profile-home-chases" v-if="chases.length">
        <a v-for="a in chases" :key="a.def.id" :href="`#/profile/set/${a.def.id}`" class="profile-home-ach" style="color:inherit">
          <div class="profile-home-medal" :class="{ 'is-dim': a.pct < 10 }"><span>{{ a.def.icon }}</span></div>
          <div class="profile-home-ach__body">
            <div class="profile-home-ach__title">{{ a.def.title }}</div>
            <div class="profile-home-ach__meta"><b>{{ a.def.difficulty }}</b> · {{ a.have }} / {{ a.total }} acquises</div>
            <div class="profile-home-ach__bar">
              <div class="profile-home-ach__fill" :class="{ 'is-gold': a.hot }" :style="{ width: a.pct + '%' }"></div>
            </div>
          </div>
          <div class="profile-home-ach__count"><b>{{ a.have }}</b>/{{ a.total }}</div>
        </a>
      </div>
      <div class="profile-home-empty" v-else>
        <div class="profile-home-medal is-dim"><span>◐</span></div>
        <p>Les chasses apparaîtront dès ta première pièce scannée.</p>
      </div>

      <!-- Settings preview -->
      <div class="profile-home-section">
        <h2>Paramètres</h2>
        <a href="#/profile/settings">Ouvrir</a>
      </div>
      <div class="profile-home-settings">
        <button type="button" class="profile-home-setrow" @click="openSettings">
          <svg viewBox="0 0 24 24"><circle cx="12" cy="12" r="9" /><path d="M3 12h18M12 3a14 14 0 010 18M12 3a14 14 0 000 18" /></svg>
          <span class="profile-home-setrow__label">Langue</span>
          <span class="profile-home-setrow__val">Français</span>
          <span class="profile-home-setrow__arrow">›</span>
        </button>
        <button type="button" class="profile-home-setrow" @click="openSettings">
          <svg viewBox="0 0 24 24"><path d="M18 8a6 6 0 10-12 0c0 7-3 9-3 9h18s-3-2-3-9" /><path d="M13.73 21a2 2 0 01-3.46 0" /></svg>
          <span class="profile-home-setrow__label">Notifications</span>
          <span class="profile-home-setrow__val">Désactivées</span>
          <span class="profile-home-setrow__arrow">›</span>
        </button>
        <button type="button" class="profile-home-setrow" @click="openSettings">
          <svg viewBox="0 0 24 24"><path d="M21 15v4a2 2 0 01-2 2H5a2 2 0 01-2-2v-4M7 10l5 5 5-5M12 15V3" /></svg>
          <span class="profile-home-setrow__label">Catalogue</span>
          <span class="profile-home-setrow__val">Wi-Fi uniquement</span>
          <span class="profile-home-setrow__arrow">›</span>
        </button>
        <button type="button" class="profile-home-setrow" @click="openSettings">
          <svg viewBox="0 0 24 24"><path d="M12 3v18M3 12h18" /></svg>
          <span class="profile-home-setrow__label">À propos</span>
          <span class="profile-home-setrow__val">v0.1.0</span>
          <span class="profile-home-setrow__arrow">›</span>
        </button>
      </div>
    </div>
  </section>
</template>

<style src="../../styles/profile.css"></style>
