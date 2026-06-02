<script setup lang="ts">
/* Scène profile-achievements — tabs En cours / Débloqués / Verrouillés.
 * Port de profile-achievements.html/.js, recâblé sur lib/achievements. */
import { computed, ref } from 'vue'
import { listChases } from '@/lib/achievements'
import type { ChaseProgress } from '@/lib/achievements'
import { useCollectionStore } from '@/stores/collection'

const store = useCollectionStore()

type Tab = 'in-progress' | 'unlocked' | 'locked'
const activeTab = ref<Tab>('in-progress')

const list = computed(() => listChases(store.ownedIds))
const inProgress = computed(() => list.value.filter((a) => a.started && !a.unlocked).sort((a, b) => b.pct - a.pct))
const unlocked = computed(() => list.value.filter((a) => a.unlocked))
const locked = computed(() => list.value.filter((a) => !a.started))

const hots = computed(() => inProgress.value.filter((a) => a.hot))
const regular = computed(() => inProgress.value.filter((a) => !a.hot))
const achCount = computed(() => `${unlocked.value.length} / ${list.value.length}`)

function chips(a: ChaseProgress): string[] {
  return (a.missing || []).slice(0, 6)
}
</script>

<template>
  <section class="profile-ach-root" data-scene="profile-achievements">
    <div class="profile-ach-topbar">
      <a class="profile-ach-back" href="#/profile">
        <svg viewBox="0 0 24 24"><path d="M15 18l-6-6 6-6" /></svg>
        Profil
      </a>
      <div class="profile-ach-titlerow">
        <h1>Chasses &amp; médailles</h1>
        <div class="profile-ach-titlerow__meta">{{ achCount }}</div>
      </div>
      <div class="profile-ach-tabs" role="tablist">
        <button class="profile-ach-tab" role="tab" :aria-selected="activeTab === 'in-progress'" data-testid="tab-in-progress" @click="activeTab = 'in-progress'">
          En cours <span class="profile-ach-tab__c">{{ inProgress.length }}</span>
        </button>
        <button class="profile-ach-tab" role="tab" :aria-selected="activeTab === 'unlocked'" data-testid="tab-unlocked" @click="activeTab = 'unlocked'">
          Débloqués <span class="profile-ach-tab__c">{{ unlocked.length }}</span>
        </button>
        <button class="profile-ach-tab" role="tab" :aria-selected="activeTab === 'locked'" data-testid="tab-locked" @click="activeTab = 'locked'">
          Verrouillés <span class="profile-ach-tab__c">{{ locked.length }}</span>
        </button>
      </div>
    </div>

    <div class="profile-ach-body">
      <!-- En cours -->
      <div class="profile-ach-pane" :class="{ 'is-active': activeTab === 'in-progress' }" data-pane="in-progress">
        <template v-if="inProgress.length">
          <template v-if="hots.length">
            <div class="eyebrow eyebrow--gold profile-ach-section-eyebrow">Presque complètes</div>
            <a v-for="a in hots" :key="a.def.id" class="profile-ach-hot" :href="`#/profile/set/${a.def.id}`" style="display:block;color:inherit">
              <div class="profile-ach-hot__head">
                <div class="profile-ach-hot__medal"></div>
                <div>
                  <div class="profile-ach-hot__title">{{ a.def.title }}</div>
                  <div class="profile-ach-hot__sub">Plus que {{ a.total - a.have }} pièce{{ a.total - a.have > 1 ? 's' : '' }}</div>
                </div>
              </div>
              <div class="profile-ach-hot__bar"><div class="profile-ach-hot__fill" :style="{ width: a.pct + '%' }"></div></div>
              <template v-if="chips(a).length">
                <div class="profile-ach-hot__missing-lbl">À trouver</div>
                <div class="profile-ach-chips"><span v-for="m in chips(a)" :key="m" class="chip">{{ m }}</span></div>
              </template>
            </a>
          </template>
          <template v-if="regular.length">
            <div class="eyebrow profile-ach-section-eyebrow" :style="{ marginTop: hots.length ? 'var(--space-6)' : '0' }">Autres chasses</div>
            <a v-for="a in regular" :key="a.def.id" class="profile-ach-row" :href="`#/profile/set/${a.def.id}`" style="color:inherit;text-decoration:none">
              <div class="profile-ach-row__medal" :class="{ 'is-dim': a.pct < 10 }">{{ a.def.icon }}</div>
              <div style="flex:1;min-width:0">
                <div class="profile-ach-row__title">{{ a.def.title }}</div>
                <div class="profile-ach-row__meta"><b>{{ a.def.difficulty }}</b> · {{ a.have }} / {{ a.total }}</div>
                <div class="profile-ach-row__bar"><div class="profile-ach-row__fill" :style="{ width: a.pct + '%' }"></div></div>
              </div>
              <div class="profile-ach-row__count"><b>{{ a.have }}</b>/{{ a.total }}</div>
            </a>
          </template>
        </template>
        <div v-else class="profile-ach-empty"><p>Les chasses apparaîtront dès ta première pièce scannée.</p></div>
      </div>

      <!-- Débloqués -->
      <div class="profile-ach-pane" :class="{ 'is-active': activeTab === 'unlocked' }" data-pane="unlocked">
        <template v-if="unlocked.length">
          <div class="profile-ach-featured">
            <div class="profile-ach-featured__medal"></div>
            <div class="profile-ach-featured__title">{{ unlocked[0].def.title }}</div>
            <div class="profile-ach-featured__sub">Dernière médaille débloquée</div>
          </div>
          <div v-if="unlocked.length > 1" class="profile-ach-grid">
            <div v-for="a in unlocked.slice(1)" :key="a.def.id" class="profile-ach-tile">
              <div class="profile-ach-tile__medal"></div>
              <div class="profile-ach-tile__title">{{ a.def.title }}</div>
              <div class="profile-ach-tile__date">Débloqué</div>
            </div>
          </div>
        </template>
        <div v-else class="profile-ach-empty"><p>Aucune médaille débloquée pour l'instant — continue à collectionner.</p></div>
      </div>

      <!-- Verrouillés -->
      <div class="profile-ach-pane" :class="{ 'is-active': activeTab === 'locked' }" data-pane="locked">
        <template v-if="locked.length">
          <div v-for="a in locked" :key="a.def.id" class="profile-ach-row" style="opacity:0.55;border-style:dashed">
            <div class="profile-ach-row__medal is-dim">{{ a.def.icon }}</div>
            <div style="flex:1;min-width:0">
              <div class="profile-ach-row__title">{{ a.def.title }}</div>
              <div class="profile-ach-row__meta">{{ a.def.difficulty }} · {{ a.total }} pièces</div>
            </div>
            <div class="profile-ach-row__count">0/{{ a.total }}</div>
          </div>
        </template>
        <div v-else class="profile-ach-empty"><p>Tu as déjà démarré toutes les chasses disponibles.</p></div>
      </div>
    </div>
  </section>
</template>

<style src="../../styles/profile-achievements.css"></style>
