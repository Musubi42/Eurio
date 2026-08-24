<script setup lang="ts">
/**
 * La vignette d'une pièce — et son vide quand il n'y en a pas.
 *
 * ⛔ TROIS FAÇONS DE N'AVOIR PAS D'IMAGE, UN SEUL RENDU.
 *   1. `undefined` — pas encore demandée (le lot est en vol) ;
 *   2. `null` — le référentiel n'en connaît aucune ;
 *   3. une URL qui échoue au chargement — 72 pièces sur 253 pointent Numista,
 *      dont le serveur refuse les requêtes hors navigateur (403 mesuré le
 *      2026-08-24 en ligne de commande). Un `<img>` cassé affiche l'icône
 *      brisée du navigateur : c'est le rendu le plus laid et le plus inquiétant
 *      qui soit sur une liste, et il se lit « le site est cassé ».
 *
 * Les trois retombent sur le même disque vide, discret. Une liste où 28 % des
 * lignes portent une icône brisée est pire qu'une liste sans images.
 *
 * Le disque n'est pas décoratif : c'est la forme de l'objet dont on parle, et il
 * réserve exactement la place de l'image — sans lui, chaque image qui arrive
 * ferait sauter la ligne (`layout shift`) sur une liste de 253 entrées.
 */
import { ref, watch } from 'vue'

const props = defineProps<{
  /** L'URL, `null` si le référentiel n'a rien, `undefined` si pas encore demandée. */
  url?: string | null
  /** Le nom de la pièce — sert de texte alternatif, jamais de légende visible. */
  nom: string
  /** Diamètre en pixels. 40 sur l'accueil, 26 dans la table dense du besoin. */
  taille?: number
}>()

const echec = ref(false)
// Une nouvelle URL mérite une nouvelle chance : sans ce reset, une ligne qui a
// échoué une fois resterait vide même après un rechargement qui l'a réparée.
watch(() => props.url, () => { echec.value = false })
</script>

<template>
  <span
    class="vignette"
    :style="{ width: `${taille ?? 40}px`, height: `${taille ?? 40}px` }"
  >
    <img
      v-if="url && !echec"
      :src="url" :alt="nom" loading="lazy" decoding="async"
      referrerpolicy="no-referrer"
      @error="echec = true"
    >
    <span v-else class="creux" aria-hidden="true" />
  </span>
</template>

<style scoped>
.vignette {
  display: inline-flex;
  flex: none;
  align-items: center;
  justify-content: center;
  border-radius: 50%;
  overflow: hidden;
  background: var(--surface-2);
}
.vignette img {
  width: 100%;
  height: 100%;
  object-fit: cover;
  display: block;
}
/* Le vide : un disque à peine marqué, qui tient la place sans rien promettre. */
.creux {
  width: 100%;
  height: 100%;
  border-radius: 50%;
  border: 1px dashed var(--surface-3);
  background: var(--surface-1);
}
</style>
