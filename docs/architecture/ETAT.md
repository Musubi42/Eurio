# ETAT — la photo datée du système

> **Revu le 2026-09-10.** Ce fichier est le **seul domicile** de l'état daté :
> mesures, chantiers, pièges vérifiés, décisions du PO avec leur date. Les règles
> intemporelles vivent dans [`../../CLAUDE.md`](../../CLAUDE.md) ; le *pourquoi* des
> décisions dans [`../adr/README.md`](../adr/README.md) ; la description par stockage,
> par geste, par artefact dans [`README.md`](./README.md), [`parcours.md`](./parcours.md),
> [`artifacts.md`](./artifacts.md).
>
> **Règle d'écriture.** Chaque fait porte sa date et, quand il en a une, sa requête.
> Un fait sans requête est une opinion. Quand un fait ici devient faux, on le
> corrige ici — jamais en le recopiant dans `CLAUDE.md`. Origine : chantier
> `de-la-base-a-la-nef`, décision D3 (2026-09-10).

## Chantier en cours — `de-la-base-a-la-nef`

Pilotage : [`../work-in-progress/de-la-base-a-la-nef/`](../work-in-progress/de-la-base-a-la-nef/)
(`PLAN.md`, `DECISIONS.md` D0–D11, `SUIVI.md`). Six étapes, jouées dans l'ordre.

| Étape | État au 2026-09-10 |
|---|---|
| 0 — Le sol : un tronc, un nom | ✅ fermée — `main` seule branche, 8 tags `archive/*` sur github, VPS sur `github/main` |
| 1 — Le fil à plomb : la CI | ✅ fermée — `.github/workflows/ci.yml`, devShell `ci`, `pytest` dans le flake |
| 2 — Le gabarit : la suite honnête | ✅ fermée — `main` vert sur un runner sans données ; trois pannes muettes ont un test |
| 3 — Les préceptes : `CLAUDE.md` ≤ 150 lignes | 🟠 en cours — ce fichier en est la sortie |
| 4 — La nef : l'APK sur la piste interne | ⏳ D4 proposé, D5 à trancher |
| 5 — Le rite : `go-task docs:rite` | ⏳ D6 proposé |

L'atelier est **gelé** pendant ce chantier (D0, ✅ PO 2026-09-10) : aucun commit dans
`ml/`, `studio-local/` ni un autre chantier, sauf s'il débloque un critère.

Constat de départ chiffré (commits Android par mois, version `0.1.0`, signature
release sur la clé debug, 635 commits d'avance de `matrice-dino` sur `main`…) :
`PLAN.md` §Constat, chaque ligne avec sa requête.

## CI et tests

- **La CI existe depuis le 2026-09-10** (étape 1, D2/D10/D11). Trois jobs :
  `ml` (pytest), `admin` (vitest + typecheck vue-tsc), `tokens` (`go-task tokens:check`),
  tous par `nix develop .#ci --command …`. Pas de job Android avant l'étape 4 : le dépôt
  est **public** (`gh repo view` → `PUBLIC`) et le `preBuild` Gradle exige des identifiants
  MinIO (ADR-004).
- Dernier run de référence : **34499098202 → success**, `2732 passed, 64 skipped, 0 failed`
  (`gh run view 34499098202 --log | grep -E '[0-9]+ passed'`). Durées : `tokens` 48 s,
  `admin` 1 min 42, `ml` 5 min 37.
- Sur le Mac avec données : `ml/.venv/bin/python -m pytest -q` → `2798 passed in 125 s`.
- **Restes au BACKLOG** (verdict étape 2) : 64 tests ne tournent jamais en CI (skip sur
  `eurio.db` absent, caches Numista, banque DINO) ; écart de collecte Linux = 2
  (`2 796` contre `2 798`, requête `pytest --collect-only -q | tail -1`) ; `pytest` arrive
  dans la venv en `9.1.1` par `ai-edge-torch → litert-torch → torch-xla2` contre `9.0.2`
  dans le flake.
- Piège trouvé à l'étape 2 : `serving/coin_lookup.py` résolvait `_DB_PATH` **à l'import** ;
  sur le Mac, `EURIO_DB_PATH` (direnv) masquait cinq tests rouges. Reproduire le runner =
  worktree propre + `env -u` sur toutes les `EURIO_*`.

## Git — tronc, remotes, VPS

- **Tranché le 2026-09-10** (D1) : `main` est le seul tronc ; les anciennes branches
  (`repo-cleanup`, `matrice-dino`, `coin-richness/p3-schema`, `data-harmonization`,
  `debug-data-taxonomy`, `scan-corpus-funnel`, `source-lmdlp-rebuild`,
  `sources-jo-wikipedia`) sont des tags `archive/*` (`git tag -l 'archive/*'`).
  ADR-005 (remaster d'historique) reste 🟡 et n'a pas été jouée.
- `archive/vps-main` (D7/D9) vit **hors github** : 1 308 Mo / 13 012 objets dont 309 Mo
  de `eurio.db.bak-*` (`git rev-list --objects github/main..archive/vps-main | git
  cat-file --batch-check`). Bundle `../archives/eurio-vps-main-8cdd7403.bundle`
  (911 Mo, `git bundle verify` ok). Reste à faire : le déposer sur MinIO.
- **Le VPS ne pousse jamais** (D8, vérifié 2026-09-10 : `git push` depuis `/opt/eurio`
  → « key marked as read only »). Un tag né sur le VPS remonte par le Mac.
- Le clone du VPS suit `github/main` (`branch.main.remote=github`, vérifié 2026-09-10 par
  le contre-relecteur de l'étape 0 après un `--ff-only`).
- **`codeberg`, historique** : le 2026-08-20 son push HTTPS pendait puis expirait depuis
  le Mac (`exit 124`) ; le 2026-08-25 sa branche `repo-cleanup` avait 90 commits de
  retard sur github ; le remote a été retiré des instructions et du VPS le 2026-09-10
  (critère 0.5). ⚠️ **Mesuré le 2026-09-10 à l'ouverture de l'étape 3** : `git remote`
  sur le clone Mac liste encore `codeberg` — le retrait n'a pas tenu sur ce clone, ou un
  autre clone a servi. À rejouer : `git remote remove codeberg`.
- 📌 À faire, non planifié : passer à GitLab en dépôt principal, github en miroir, et
  repointer le remote du VPS.

## Écritures — Direction A, rerouting, résiduels 503

Décision : ADR-009. Skill : `eurio-data-writes`.

Le rerouting Mac/PC → VPS n'est **pas terminé**, mais un `503 canonical_readonly` ne dit
pas lequel des deux cas on a. **Vérifié le 2026-08-17** : `requalify` / `move-lane` /
`correct-listing` **ont leur jumeau au VPS et le front les y envoie déjà** — leur 503 sur
`:8042` signale un appelant qui tape la mauvaise adresse, pas un rerouting manquant. Les
vrais résiduels mesurés : `POST /review-queue/requalify-lot/batch` et
`POST /coins/assets/reflag-needs-review`. Trancher = lire l'OpenAPI du canonique
(`curl -s https://eurio-api.musubi.dev/openapi.json`).

`README.md` (par stockage) décrit l'état réel au **2026-08-14** ; `artifacts.md` vérifié
le 2026-08-14 ; `parcours.md` §4 mesuré le 2026-08-16.

## Front admin — un seul front, deux cibles

Décision : ADR-011. **Fusion faite le 2026-06-30** : `admin/packages/studio-local` est
servi à deux endroits via `VITE_DEPLOY_TARGET`
(`studio-local/src/shared/config/deploy-target.ts`) ; `admin-vps` est supprimé.

| | **local** (`VITE_DEPLOY_TARGET=local`, défaut) | **hébergé** (`=hosted`) |
|---|---|---|
| Où | Mac/PC, `pnpm dev` sur `localhost:5173` | VPS, `https://eurio-admin.musubi.dev` |
| Auth | Bearer PAT depuis `.env.local` (gitignored) | Cookie OIDC posé par eurio-api après Authentik (ADR-010) |
| Heavy ML `:8042` | actif (crops, scrape, training, lab, bench…) | grisé + notice (`hasLocalMlApi`=false ; mixed-content interdit) |
| Features légères | toutes | toutes (review consultation, users, tokens, KPIs, édition métadonnées) |
| Mobile | non | oui |

Où ça vit : l'auth-adapter `studio-local/src/shared/api/eurio-api.ts` choisit Bearer vs
cookie selon `AUTH_MODE` ; la capacité `hasLocalMlApi` est dans `stores/capabilities.ts`
(baseline `deploy-target` + ping `:8042/health` en local) ; les routes lourdes portent
`meta.heavy` (`app/router.ts`) ; `AppLayout` grise la nav et rend `LocalOnlyNotice`.

**Pile en doublon encore en service** : `admin/packages/review/` est tracké et buildé par
`infra/review/` (`eurio-review.musubi.dev`). Le C9 qui devait le supprimer n'existe plus ;
K2 est **tranché le 2026-08-23** (ADR-012) : les amis passent par `studio-local` hébergé en
rôle `reviewer`. L'exécution est le **lot 9** de
`docs/work-in-progress/review-collaborative-v2/`, **non joué**. N'y ajoute rien.

Déploiement : front hébergé via `infra/eurio-admin/` (nginx static derrière Traefik), pas
de Vercel. Vercel ne porte que `packages/proto/` (`go-task proto:deploy`). L'ancien proto
HTML `docs/design/prototype/` est archivé sous `docs/archive/design/prototype/`.

## Secrets — frontières et legacy

Décision : ADR-015. `loan` est **sorti du monorepo le 2026-08-14** (ADR-006) et vit dans
`../loan` ; ses secrets sont dans le dashboard Vercel.

Sur le VPS, le pattern est **SOPS via direnv** : `.envrc` déchiffre `secrets/dev.env` au
`cd /opt/eurio`, `docker compose up` forwarde par `environment: { VAR: ${VAR:?missing} }`.
Contexte scripté (cron, systemd) : `sops exec-env /opt/eurio/secrets/dev.env "docker compose up …"`.
Le geste complet de redéploiement (`eurio-api` comme `eurio-admin`) : `CLAUDE.md` §« Déployer sur le VPS ».
Le pattern legacy Docker secrets (`infra/*/secrets/<name>` + `*_FILE`) est **déprécié** :
`infra/eurio-api/` a migré en **juin 2026** ; `infra/review/` reste en service sur l'ancien
schéma jusqu'au lot 9 (cf. §Front admin).

Les clés Numista sont **8, en rotation**, via `referential.numista_keys.KeyManager` — il
n'existe pas de `NUMISTA_API_KEY` au singulier.

## Sauvegarde

Décision : ADR-014. Skill : `eurio-backup`. Chantier `backup-pipeline` : **lots 0 à 4
livrés, lot 5 🟡** (code fait, monitors à créer), lot 6 clos. Hub :
`docs/work-in-progress/backup-pipeline/HANDOFF-NEXT-SESSION.md` (état, pièges, chiffres de
référence) ; `DECISIONS.md` y compte **32 entrées**.

`go-task backup:stage` · `backup:verify` · `backup:test` dépendent de conteneurs Docker
locaux (`eurio-api`, `eurio-review`, MinIO), d'un staging de **6,6 Go** et de
`infra/backup/notify.conf` — tous gitignorés, donc absents sur Mac/PC.
`infra/backup/staging/` contient ces 6,6 Go de **données** sur le VPS : un
`git clean -xdf` les détruit.

## Tokens et fixtures

Le générateur `scripts/generate_tokens.mjs` est **multi-cible depuis le 2026-08-14** :
`android` est la seule cible ; en ajouter une = une entrée dans son registre `TARGETS`.
`go-task tokens:check` ne dépend plus de git : il compare le contenu généré au contenu
sur disque et sort en 2 sur dérive (c'est le job `tokens` de la CI). Côté Android QA, les
fixtures sont copiées au build par la tâche Gradle `syncQaFixtures` — l'ancien symlink
`src/qa/assets/fixtures` a été retiré parce qu'il cassait au clone.

## Supabase et catalogue embarqué

- Le catalogue packagé est `app-android/src/main/assets/app_core.db` (`go-task
  ml:build-app-core`) ; il **remplace** `catalog_snapshot.json` (phase P6).
- Pas d'auth utilisateur en v1 : le vault est 100 % local côté Room.
- ⚠️ `supabase/types/database.ts` n'est **ni généré ni importé** par quoi que ce soit —
  doc de schéma historique, pas une source. Le schéma de vérité est `ml/state/schema.sql`.
- `AppCoreBootstrapper.kt` gate le rechargement sur `APP_CORE_VERSION`, constante codée en
  dur (valeur **2** au 2026-08-25) qu'aucun outillage n'écrit — détail dans `README.md`.

## Stack Android (versions au 2026-09-10)

Kotlin + Jetpack Compose + Material 3 · Navigation Compose 2.8.x · Room 2.6.1 (KSP, pas
Kapt) · Supabase-kt (postgrest-kt) · Coil · CameraX + LiteRT (ADR-001) · OpenCV 4.10
(Hough) · Koin déclaré, **pas encore câblé** · minSdk 26, target 36.

## Pipeline ML du scan

Doc : `docs/research/detection-pipeline-unified.md`. Détecteur : **YOLOv8-nano**
(`ml/training/train_detector.py:46` : `YOLO("yolov8n.pt")`) — le « YOLO11 » que `CLAUDE.md`
a porté depuis avril 2026 était faux. Puis OpenCV Hough en parallèle → merge
IoU → rerank ArcFace spread-based → consensus buffer 5/3 sticky.

## ArcFace ou DINO — mesuré le 2026-08-26, ArcFace gagne

Le départage est **fait**. 260 frames eBay jamais vues à l'entraînement, 52 classes, la
même banque de 1 813 ancres pour les quatre bras, McNemar apparié. Détail et réserves :
[`../work-in-progress/juge-et-banc/SUIVI-MATRICE.md`](../work-in-progress/juge-et-banc/SUIVI-MATRICE.md).

| Modèle | M params | **r@1** | ms/img | McNemar vs ArcFace |
|---|---:|---:|---:|---|
| **ArcFace** `392205b7f725` (40 ep) | **1,1** | **99,2 %** | **4** | — |
| `dinov2_vitl14` | 304,4 | 98,1 % | 113 | p = 0,375 — indistinguable |
| `dinov2_vitb14` | 86,6 | 96,9 % | 31 | p = 0,070 — indistinguable |
| `dinov2_vits14` | 22,1 | 94,2 % | 12 | **p = 0,00098 — ArcFace meilleur** |

**À justesse égale ou supérieure, ArcFace est 276× plus petit et 28× plus rapide.** Ne
relance pas ce départage sans lire les deux réserves : (1) ArcFace a été **entraîné sur les
crops de la banque** (perte → 0,0000), son avantage sur les *références* n'est pas partagé
par DINO ; (2) la mesure porte sur **52 classes, le produit en aura 671+** — et ArcFace se
réentraîne à chaque classe nouvelle (1 h 45 ici) là où DINO n'a rien à réentraîner.
ADR-008 (deux voies) reste 🟡.

## Capture device — décision du PO, 2026-08-26

On n'en fait plus. Les **451 captures existantes sont conservées** (archivées, répliquées
sur MinIO) et restent lisibles comme témoin ; **le jeu d'évaluation vient désormais des
crops eBay**. Suivi : `SUIVI-MATRICE.md`. Le PO juge par ailleurs que l'app de capture est
inadaptée — elle prend une photo là où il faudrait un scan. Sujet distinct, à rouvrir par
lui seul.

## Chantiers vivants — où reprendre

Index : [`../work-in-progress/README.md`](../work-in-progress/README.md). Reste-à-faire des
chantiers archivés : [`../BACKLOG.md`](../BACKLOG.md). Points d'entrée qui portaient une
date dans `CLAUDE.md` :

| Sujet | Entrée | État |
|---|---|---|
| Auto-validation de la review | `review-autovalidation/MESURE-2026-08-25.md` d'abord | le geste zéro est joué et dément deux prémisses de `PROBLEME.md` ; `REPRENDRE-ICI.md` dit ce qui est déployé |
| Banque d'ancres DINO, seuils | note d'état en tête de `scan-sans-retrain/PREREQUIS.md`, puis `banque-dino/CONSTAT.md` | où on en est, ce qui attend le PO, dans quel ordre |
| Le crop | `juge-du-crop/README.md`, puis ADR-017 | sept chantiers ont échoué en définissant leur propre oracle |
| Corpus de scan | `scan-quality/DURABILITE-CORPUS.md`, `scan-sans-retrain/PROTOCOLE-CAPTURE.md` | témoin conservé ; plus de capture (cf. §Capture device) |
| Review collaborative v2 | `review-collaborative-v2/` | lot 9 (chute de `infra/review/`) non joué |
| Sauvegarde | `backup-pipeline/HANDOFF-NEXT-SESSION.md` | lot 5 🟡 |
