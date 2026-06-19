<script setup lang="ts">
// FilterRulesPanel — panneau « Règles de filtrage » : ce que le pipeline
// garde, ce qu'il écarte, et pourquoi. Config statique (lecture seule)
// servie par /sources/ebay/filter-config. À mettre en regard de
// l'entonnoir : l'entonnoir dit « 95 year_mismatch », ce panneau dit
// « year_mismatch = … ».

import { computed, onMounted, ref } from 'vue'
import { ChevronRight } from 'lucide-vue-next'
import { fetchFilterConfig, type EbayFilterConfig } from '../composables/useFilterConfig'

const config = ref<EbayFilterConfig | null>(null)
const open = ref(false)

onMounted(async () => {
  config.value = await fetchFilterConfig()
})

const rejectRules = computed(() => (config.value?.rules ?? []).filter((r) => r.kind === 'reject'))
const flagRules = computed(() => (config.value?.rules ?? []).filter((r) => r.kind === 'flag'))
</script>

<template>
  <section
    class="rounded-lg border"
    style="border-color: var(--surface-3); background: var(--surface);"
  >
    <button
      type="button"
      class="flex w-full items-center gap-2 px-4 py-3 text-left"
      @click="open = !open"
    >
      <ChevronRight
        class="h-3.5 w-3.5 shrink-0 transition-transform"
        :style="{ color: 'var(--ink-400)', transform: open ? 'rotate(90deg)' : 'none' }"
      />
      <span class="font-mono text-[11px] uppercase tracking-wider" style="color: var(--ink-500);">
        Règles de filtrage
      </span>
      <span v-if="config" class="font-mono text-[11px]" style="color: var(--ink-400);">
        · {{ rejectRules.length }} reject · {{ flagRules.length }} flag
      </span>
    </button>

    <div v-if="open" class="border-t px-4 py-3" style="border-color: var(--surface-2);">
      <p v-if="!config" class="font-mono text-[11px]" style="color: var(--ink-400);">
        Config indisponible (API ML injoignable).
      </p>
      <template v-else>
        <p class="mb-3 text-[11px] leading-relaxed" style="color: var(--ink-500);">
          Appliquées à chaque listing avant ingestion. Les <strong>reject</strong>
          écartent le listing ; les <strong>flag</strong> le gardent mais le
          taguent (ex. lot → review).
        </p>
        <ul class="flex flex-col gap-2">
          <li
            v-for="rule in config.rules"
            :key="rule.name"
            class="rounded-md border px-3 py-2"
            style="border-color: var(--surface-2); background: var(--surface-1);"
          >
            <div class="flex items-baseline gap-2">
              <span
                class="rounded px-1.5 py-0.5 font-mono text-[10px] uppercase"
                :style="{
                  color: rule.kind === 'reject' ? 'var(--danger)' : 'var(--warning)',
                  background: `color-mix(in srgb, ${
                    rule.kind === 'reject' ? 'var(--danger)' : 'var(--warning)'
                  } 12%, var(--surface))`,
                }"
              >
                {{ rule.kind }}
              </span>
              <span class="font-mono text-[12px] font-semibold" style="color: var(--ink);">
                {{ rule.name }}
              </span>
              <span
                v-if="rule.policy"
                class="font-mono text-[10px]"
                style="color: var(--ink-400);"
              >
                · {{ rule.policy }}
              </span>
            </div>
            <p class="mt-1 text-[11px] leading-relaxed" style="color: var(--ink-700);">
              {{ rule.description }}
            </p>
            <p
              v-if="rule.pattern"
              class="mt-1 truncate font-mono text-[10px]"
              style="color: var(--ink-400);"
              :title="rule.pattern"
            >
              /{{ rule.pattern }}/
            </p>
          </li>
        </ul>
        <p class="mt-3 font-mono text-[10px]" style="color: var(--ink-400);">
          Source : {{ config.source_path }}
        </p>
      </template>
    </div>
  </section>
</template>
