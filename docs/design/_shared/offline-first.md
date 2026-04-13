# Offline-first — qu'est-ce qu'on ship, qu'est-ce qu'on fetch

> **Principe directeur** : l'app fonctionne 100% hors ligne pour son core loop (scan + ajout coffre + consultation fiche + achievements). Le backend est une dépendance **opt-in** pour les features qui en ont vraiment besoin (prix eBay, sync multi-device, modèles ML à jour).
>
> Décidé le 2026-04-13 en conversation avec Raphaël. Ancre : "zéro infra" + "offline par défaut" + "auth silencieuse".

---

## Ce qu'on ship dans l'APK

### Référentiel pièces (seed initial)
- **2 938 coins** × ~1 KB de metadata → ~3 MB JSON
- **419 images canoniques BCE** × ~30 KB → ~13 MB
- **Total estimé** : ~16 MB de seed pour le catalogue

Format : un dump JSON compact dans `assets/seed/eurio_referential.json` + dossier `assets/seed/images/` pour les images canoniques. Au premier lancement, l'app importe ce seed dans Room via une migration initiale.

### Modèle ML
- **CoinDetector** (YOLO ou équivalent) — déjà dans `app/src/main/java/com/musubi/eurio/ml/`
- **CoinEmbedder** (ArcFace TFLite, Phase 2B) — à venir
- **coin_embeddings.npy** pré-calculé — liste d'embeddings canoniques pour le matching KNN local

Le modèle est shippé dans `assets/ml/` dans l'APK. Taille estimée : 5–15 MB selon la version.

### Ce qu'on NE ship PAS
- Les photos Numista (licence à vérifier + volume trop gros)
- Les prix eBay (time series, mutable)
- Les coffres utilisateurs

---

## Ce qu'on fetch depuis le backend

### Au premier lancement — rien
L'app fonctionne immédiatement avec le seed local. Zéro réseau requis pour le core loop.

### En background (Wi-Fi par défaut, opt-in cellulaire)

**1. Delta fetch du référentiel**
Supabase table `coins` avec un filtre `updated_at > last_local_sync`. Patch local via Room. Permet d'ajouter de nouvelles pièces (ex : commémorative JO Paris 2024 frappée après la release de l'app) sans reshipper tout l'APK. Fréquence : une fois par semaine max, contrôlé par l'app.

**2. Photos Numista lazy-fetch**
À l'ouverture de la fiche pièce, si `coin.numista_image_url` est null en local :
- Fetch depuis **Supabase Storage** (pas depuis Numista direct — cf. rate limit 2000/mois épuisé).
- Les photos auront été scrapées one-shot côté `ml/` et uploadées au CDN Supabase avant la release.
- Cache local Room + disque. Une photo téléchargée n'est re-téléchargée que si un champ `image_version` change.

**3. Prix eBay (time series)**
Supabase Edge Function cron hebdomadaire met à jour `coins.observations.ebay_market` (P25/P50/P75). L'app fetch ces valeurs au scan ou à l'ouverture d'une fiche. En cas d'échec réseau, on affiche la dernière valeur connue avec un indicateur de fraîcheur.

**4. Nouveau modèle ML** *(stratégie à décider — voir question ouverte ci-dessous)*

---

## Stratégie de mise à jour du modèle ML — QUESTION OUVERTE

Le problème (vu en conv le 2026-04-13) :
- Quand une nouvelle pièce sort (ex : commémo JO Paris), on ré-entraîne le modèle côté `ml/` et on obtient un nouveau `.tflite` + nouveau `coin_embeddings.npy`.
- On ne peut pas forcer un re-download à chaque ouverture d'app (user friction énorme, abandon quasi garanti).
- On ne peut pas non plus attendre la prochaine release APK, parce qu'une commémo est pertinente *au moment* de sa sortie (JO, événement saisonnier).

### Option A — download du modèle en background, scan serveur en fallback
- Scan local tente d'abord. Si embedding ne matche aucun `eurio_id` connu avec confiance suffisante → upload de la photo à un endpoint serveur, qui a le modèle à jour, et renvoie le match.
- En parallèle, si l'user a opt-in "télécharger les nouveaux modèles en background / Wi-Fi only", l'app fetch la nouvelle version quand elle est dispo.
- **Avantages** : réactif, pas de friction user.
- **Inconvénients** : nécessite un endpoint serveur avec le modèle ArcFace chargé (Python service, pas Edge Function Deno). Coût infra non-nul. Latence réseau sur le fallback.

### Option B — delta embeddings seulement
- Le modèle TFLite ne change pas souvent (on le garde stable). Ce qui change, c'est `coin_embeddings.npy` — la liste des embeddings canoniques.
- Quand une nouvelle pièce est ajoutée, on calcule son embedding côté `ml/` avec le modèle en place, on l'uploade dans `coin_embeddings` sur Supabase, et l'app fait un delta fetch périodique.
- **Avantages** : delta minuscule (~1 KB par pièce), pas besoin d'endpoint serveur pour le scan, pas de changement du binaire TFLite.
- **Inconvénients** : suppose que le modèle TFLite initial généralise assez bien pour embedder correctement une pièce qu'il n'a jamais vue en training (ce qui est l'hypothèse centrale d'ArcFace / metric learning — à valider en Phase 2B).

### Option C — hybride
- Par défaut, Option B : delta embeddings via Supabase.
- Fallback serveur Option A seulement si la qualité du scan dégrade (détecté par taux d'échec côté telemetry).
- Nouveau modèle TFLite shipped uniquement dans les releases APK (tous les 2-3 mois).

### Recommandation provisoire
**Option C**, avec démarrage sur Option B pure en v1. La Phase 2B doit valider que le modèle ArcFace généralise à des classes non vues. Si oui → B suffit longtemps. Si non → on ajoute A comme fallback.

**À re-brainstormer** quand Phase 2B aura tourné et qu'on aura des métriques réelles.

---

## Contraintes connues

- **Numista API** : rate limit 2000 calls/mois (free plan), épuisé en avril 2026. **Jamais** d'appel live Numista depuis le device. Toutes les images Numista passent par un scrape one-shot côté `ml/` → upload Supabase Storage → fetch app depuis CDN.
- **eBay Browse API** : OK pour le backend (cron hebdo), **jamais** depuis le device.
- **Supabase free tier** : limite bandwidth à surveiller si on ship les images via Supabase Storage. Envisager Cloudflare R2 ou équivalent si le volume devient gros.
- **Room migrations** : à chaque évolution du schema canonique (ex : ajout de champ pour la marketplace), migration Room versionnée. Pas de `fallbackToDestructiveMigration`.

---

## Questions ouvertes

- [ ] Option de mise à jour du modèle ML (A / B / C) — à trancher après Phase 2B.
- [ ] Licence d'usage des photos Numista pour un produit commercial — à vérifier côté legal avant la release.
- [ ] Quelle taille max acceptable pour l'APK initial ? (Play Store recommande < 150 MB d'install size, pas de hard limit pour les APK sans bundles.)
- [ ] Faut-il un flag "mode avion total" qui bloque tout fetch même opt-in, pour les users paranos ?
