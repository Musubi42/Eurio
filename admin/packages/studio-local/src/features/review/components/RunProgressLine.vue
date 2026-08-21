<script setup lang="ts">
// Le compteur « n / N tranchés » d'une file cadrée par run (`?run=a,b`).
//
// Il compte ce que `GET /review-queue/run-progress` compte : TOUTES les rows
// review_queue des crops créés par ces runs, pas seulement l'ouvert que la
// file sert. C'est ce qui permet de fermer l'onglet et de retrouver « 312 /
// 777 » le lendemain — l'avancement vit en base, pas dans l'écran.
//
// `refreshKey` : l'hôte le change après chaque décision ÉCRITE (le POST a
// répondu) — un compteur qu'il incrémente, ou la clé du lot affiché quand
// trancher mène forcément au lot suivant. Rafraîchir avant, c'est afficher un
// compteur que la base contredit ; rafraîchir jamais, c'est un compteur mort.

import { ref, watch } from 'vue'
import { fetchRunProgress, type RunProgress } from '../composables/useReviewApi'

const props = withDefaults(defineProps<{
  runIds: string[]
  refreshKey?: number | string
}>(), { refreshKey: 0 })

const progress = ref<RunProgress | null>(null)
const error = ref<string | null>(null)

async function load() {
  if (!props.runIds.length) { progress.value = null; return }
  try {
    progress.value = await fetchRunProgress(props.runIds)
    error.value = null
  } catch (err) {
    // On garde le dernier chiffre connu et on dit que celui-ci a échoué :
    // un compteur qui disparaît en silence se lit « plus rien à faire ».
    error.value = err instanceof Error ? err.message : String(err)
  }
}

watch(
  [() => props.runIds.join(','), () => props.refreshKey],
  () => { void load() },
  { immediate: true },
)

function short(id: string): string {
  return id.length > 8 ? `${id.slice(0, 8)}…` : id
}
</script>

<template>
  <div
    class="flex flex-wrap items-center gap-x-3 gap-y-1 border-b px-8 py-1.5 font-mono text-[11px] tabular-nums"
    style="border-color: var(--surface-3); background: var(--surface-1); color: var(--ink-500);"
    :title="runIds.join(', ')"
  >
    <span class="uppercase tracking-wider" style="color: var(--ink-400);">Run</span>
    <span style="color: var(--ink);">{{ runIds.map(short).join(', ') }}</span>
    <span class="opacity-50">—</span>
    <template v-if="progress">
      <span>
        <span class="font-semibold" style="color: var(--indigo-700);">{{ progress.done.toLocaleString('fr-FR') }}</span>
        <span style="color: var(--ink-400);"> / </span>
        <span class="font-semibold" style="color: var(--ink);">{{ progress.total.toLocaleString('fr-FR') }}</span>
        <span class="ml-1 uppercase tracking-wider" style="color: var(--ink-400);">tranchés</span>
      </span>
      <span class="opacity-50">·</span>
      <span>
        <span class="font-semibold" style="color: var(--ink);">{{ progress.by_kind.single.open.toLocaleString('fr-FR') }}</span>
        <span class="ml-1" style="color: var(--ink-400);">singles</span>
      </span>
      <span class="opacity-50">·</span>
      <span>
        <span class="font-semibold" style="color: var(--gold-600);">{{ progress.by_kind.lot.open.toLocaleString('fr-FR') }}</span>
        <span class="ml-1" style="color: var(--ink-400);">lots restants</span>
      </span>
      <span v-if="progress.skipped" class="opacity-50">·</span>
      <span v-if="progress.skipped">
        <span class="font-semibold" style="color: var(--ink);">{{ progress.skipped.toLocaleString('fr-FR') }}</span>
        <span class="ml-1" style="color: var(--ink-400);">passés</span>
      </span>
    </template>
    <span v-else-if="!error" style="color: var(--ink-400);">…</span>
    <span v-if="error" style="color: var(--danger);">compteur indisponible — {{ error }}</span>
  </div>
</template>
