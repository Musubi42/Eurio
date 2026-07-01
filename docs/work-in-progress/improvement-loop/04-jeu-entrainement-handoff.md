# Handoff — refonte du panneau « Jeu d'entraînement » (ex-« QA crops d'entraînement »)

> Pour une session Claude Code fraîche. Tout le contexte est ici. Préparé le
> 2026-07-01. Branche : `sources-jo-wikipedia` (remotes `codeberg` + `github`).
> Spec d'origine : [`03-crop-triage-ux.md`](./03-crop-triage-ux.md) (l'outil est
> **déjà construit** — ici on le raffine suite au retour PO).

## Mission

Améliorer le panneau existant sur la page cohorte (`/lab/cohorts/:id`) qui liste,
par classe, **les crops eBay reviewés qui partent réellement à l'entraînement**.
Le PO l'a validé sur le fond (« le truc automatique est plutôt pas mal ») mais a
demandé 1 renommage + 6 raffinements UX/fonctionnels (§Changements).

**Doctrine** : outil interne admin (pas une scène produit) → **R1 proto-first ne
s'applique pas** (cf. `parity-rules.md` §exclusions ; confirmé pour ce composant).
R0 (pas de dette) + R2 (couleurs via tokens, jamais de hex en dur) s'appliquent.

## État actuel (ne pas refaire)

- **Composant** : `admin/packages/studio-local/src/features/lab/components/CohortTrainingQa.vue`
  — accordéon par classe (rangé par R@1 croissant), vignettes suspect-first, clic
  = inclure/exclure du train (réversible, effet au re-bake). Monté comme drawer C5
  sur `CohortDetailPage.vue`.
- **Backend (existe)** :
  - `GET /lab/cohorts/{id}/training-crops` (`ml/serving/lab_routes.py:2137`, cœur
    `_cohort_training_crops` :2054) → par classe (maille design_group) : crops +
    R@1 de la dernière itération.
  - `POST /lab/assets/{asset_id}/training-eligible` (`lab_routes.py:2148`) →
    flippe `training_eligible` (exclure/réinclure).
- **Front API** : `fetchCohortTrainingCrops`, `setAssetTrainingEligible`
  (`features/lab/composables/useLabApi.ts:253/262`), query dans `useLabQueries`.

## Changements demandés (retour PO 2026-07-01)

### 1. Renommer « QA crops d'entraînement » → **« Jeu d'entraînement »**
Ce n'est pas de la QA, c'est **le produit** = le set exact qui entraîne le modèle.
- `CohortTrainingQa.vue` : `DrawerSection title="QA crops d'entraînement"` (~ligne
  98) → `« Jeu d'entraînement »`. Ajuster le sous-titre/description pour dire
  clairement « voici les photos qui partent au modèle » (rassurer : c'est validé,
  suspect-first).
- Renommer le fichier composant en `CohortTrainingSet.vue` (+ import dans
  `CohortDetailPage.vue`) — optionnel mais propre. À trancher.

### 2. Badge R@1 `—` : clarifier l'état vide
`r1Label` (~ligne 66) renvoie `—` quand `r_at_1 == null` (aucun benchmark de la
dernière itération ne couvre la classe). Ce n'est pas un bug — c'est « pas encore
benché ». → au survol / en légende, expliciter « pas de benchmark récent » plutôt
que juste `—` (sinon on croit à une barre / valeur manquante).

### 3. Overlay d'exclusion trop prononcé
Les crops exclus ont `opacity: 0.32` (~ligne 172) → trop fort, et les vignettes
sont petites → on ne voit plus l'image. **Alléger à ~0.55** (garder le filtre,
juste moins opaque). Le PO aime le filtre (simple/efficace), c'est l'intensité.

### 4. Bordure VERTE pour les crops inclus (qui partent au train)
Aujourd'hui l'anneau (`ringColor` ~lignes 73-79) : rouge (rejeté/`not_2eur`),
ambre (face ≠ obverse), sinon neutre (`surface-3`). → **ajouter vert**
(`var(--success)`) quand le crop est **éligible ET propre** (obverse, 2€) = « part
au modèle ». Garder rouge/ambre pour les problèmes. Le vert = signal « ça
s'entraîne » plus lisible que l'orange.

### 5. Recrop EN PLACE (réutiliser Review)
Un crop « dégueulasse » mais bien attribué mérite un re-crop, pas une exclusion.
Aujourd'hui impossible depuis ce panneau.
- **Réutilisables prêts** : modale `features/review/components/CircleCropEditor.vue`
  + fonction `manualCropAsset(assetId, circle)` (`useReviewApi.ts:425` →
  `POST /coins/assets/{asset_id}/manual-crop`, asset-keyé, écrase cache+MinIO+DB
  au format prod). **Les crops du panneau SONT des assets** → ça marche direct.
- **UX** : au survol d'une vignette, petit bouton en haut-à-droite → ouvre la
  modale de recrop → valider → cache-bust `?v=` sur la vignette.
- Extraire la modale en composant partagé si elle est trop couplée à Review
  (sinon l'importer telle quelle).

### 6. Réassigner un crop à la BONNE classe (réutiliser Review)
Certains crops (ex. exclus de `at-2005`) ne sont **pas** la bonne pièce → pouvoir
les **rediriger vers la bonne classe** en 1 clic.
- Mécanisme Review : `decideReviewItem` pose `eurio_id` — mais c'est **queue-keyé**
  (`/review-queue/{id}/decide`). Pour un **asset** hors file, **pas d'endpoint
  asset-level de réassignation aujourd'hui** → **décision** :
  - (a) ajouter `POST /lab/assets/{asset_id}/reassign {eurio_id}` (met à jour
    `image_assets.eurio_id`, garde `training_eligible`) — petit, propre, symétrique
    de `training-eligible` ; OU
  - (b) router via `reflag-needs-review` → `decide` (plus lourd, passe par une row
    review_queue).
  Recommandation : **(a)**.
- **UX** : le bouton hover (§5) ouvre un mini-panneau avec **deux actions** —
  « Re-cropper » et « Réassigner » (sélecteur de classe). Parfois les deux sont
  nécessaires (mauvais crop **et** mauvaise classe) → les deux boutons coexistent.

### 7. Cadrage de confiance (copy)
Rendre explicite, en tête du panneau, que **cette vue = le set exact qui part à
l'entraînement** (validé), suspect-first. Petit texte, pas une refonte.

## Découpage proposé (incrémental, testable)

1. **Cosmétique** (rapide, zéro backend) : renommage §1 + overlay §3 + bordure
   verte §4 + copy §2/§7. → livrer, montrer.
2. **Recrop en place** §5 : bouton hover + modale `CircleCropEditor` +
   `manualCropAsset` + cache-bust. (Endpoint existe.)
3. **Réassignation** §6 : trancher (a)/(b), ajouter l'endpoint si (a) + tests,
   puis le sélecteur de classe dans le mini-panneau hover.

## Comment vérifier

- Lancer le front : `pnpm -C admin/packages/studio-local dev` → `/lab/cohorts/<id>`
  (cohorte `mix-zone-17` = `b0299ca0252b`). Le ML local `:8042` doit tourner
  (`go-task ml:api-replica-prod`) pour `training-crops`.
- Recrop : re-cropper un crop suspect → il se met à jour en place (cache-bust),
  et le prochain re-bake le reprend au bon format.
- Réassignation : rediriger un intrus → il quitte la classe source, apparaît dans
  la cible.
- Backend : `pnpm`/`pytest` sur les tests lab (`ml/tests/test_lab_api.py`) +
  ajouter des tests pour l'endpoint reassign si (a).

## Pointeurs

- Boucle d'amélioration : [`README.md`](./README.md) (le maillon INSPECT).
- Spec d'origine : [`03-crop-triage-ux.md`](./03-crop-triage-ux.md).
- Carte pipeline data (où exclure / réassigner) : [`02-pipeline-map.md`](./02-pipeline-map.md).
- Diagnostic classe-par-classe : [`01-diagnosis-iter-1fcac3c9.md`](./01-diagnosis-iter-1fcac3c9.md).
- Mémoire projet : `project_review_improvements`, `project_lab_streamline`.
