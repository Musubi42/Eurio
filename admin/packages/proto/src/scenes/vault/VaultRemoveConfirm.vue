<script setup lang="ts">
/* Overlay de confirmation de retrait (non-routé). Port de vault-remove-confirm.
 * Sur confirmation : retire + toast undo 5s. */
import type { Coin } from '@/api'

const props = defineProps<{ coin: Coin }>()
const emit = defineEmits<{ cancel: []; confirm: [] }>()

function faceLabel(cents: number): string {
  if (cents >= 100) return cents % 100 === 0 ? `${cents / 100} €` : `${(cents / 100).toFixed(2).replace('.', ',')} €`
  return `${cents} c`
}
const meta = `${props.coin.countryName} · ${faceLabel(props.coin.faceValueCents)} · ${props.coin.year ?? '—'}`
</script>

<template>
  <div class="vault-remove-backdrop" data-scene="vault-remove-confirm" role="dialog" aria-modal="true" aria-labelledby="vault-remove-title" @click.self="emit('cancel')">
    <div class="vault-remove-dialog">
      <div class="vault-remove-icon" aria-hidden="true">
        <svg viewBox="0 0 24 24"><path d="M3 6h18M8 6V4a2 2 0 012-2h4a2 2 0 012 2v2m1 0v14a2 2 0 01-2 2H9a2 2 0 01-2-2V6" /></svg>
      </div>
      <h2 id="vault-remove-title" class="vault-remove-title">Retirer cette pièce<br />du coffre ?</h2>
      <p class="vault-remove-sub">{{ meta }}</p>
      <div class="vault-remove-actions">
        <button type="button" class="btn btn-ghost" @click="emit('cancel')">Annuler</button>
        <button type="button" class="btn vault-remove-destructive" data-testid="overlay-confirm-remove" @click="emit('confirm')">Retirer</button>
      </div>
    </div>
  </div>
</template>

<style src="../../styles/vault-remove-confirm.css"></style>
