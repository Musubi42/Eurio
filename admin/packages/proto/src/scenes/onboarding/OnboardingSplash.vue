<script setup lang="ts">
import { onBeforeUnmount, onMounted } from 'vue'
import { useRouter } from 'vue-router'
const router = useRouter()
let timer: ReturnType<typeof setTimeout> | null = null
onMounted(() => { timer = setTimeout(() => router.push('/onboarding/1'), 1400) })
onBeforeUnmount(() => { if (timer) clearTimeout(timer) })
function onClick() { if (timer) clearTimeout(timer); router.push('/onboarding/1') }
</script>

<template>
<section @click="onClick" class="onboarding-splash-root" data-scene="onboarding-splash">
  <div class="onboarding-splash-coin" aria-hidden="true">
    <span class="onboarding-splash-coin__label">2€</span>
  </div>

  <div class="onboarding-splash-wordmark" aria-label="Eurio">
    Eur<em>io</em>
  </div>

  <div class="onboarding-splash-tagline">Numismatique &middot; Europ&eacute;enne</div>

  <div class="onboarding-splash-progress" aria-hidden="true">
    <div class="onboarding-splash-progress__track">
      <div class="onboarding-splash-progress__fill"></div>
    </div>
    <div class="onboarding-splash-progress__copy">Musubi &middot; 2026</div>
  </div>
</section>
</template>

<style src="../../styles/onboarding-splash.css"></style>
