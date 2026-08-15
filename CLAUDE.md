# CLAUDE.md — Eurio repo-level guidance

> Instructions durables pour Claude Code dans ce dépôt. Lis ce fichier avant de toucher le code ou les docs.

## Mission produit

Eurio est une app Android de collection de pièces euro. L'acte central de l'app est le **scan** : l'utilisateur ouvre l'app, pointe sa caméra sur une pièce, et l'app l'identifie + lui propose de l'ajouter à son coffre. Tout le reste de l'UX tourne autour de cet acte — comme TikTok tourne autour de la création de contenu.

Voir `docs/app-implem-phases/README.md` pour le plan détaillé en 6 phases (0 à 5), et `docs/app-implem-phases/phase-*.md` pour chaque phase individuellement.

## Monorepo

```
Eurio/
├── app-android/                       # App Kotlin/Compose (Material 3)
├── admin/                             # pnpm workspace
│   ├── packages/studio-local/         # Front UNIQUE (R1) : local (PAT, :5173, ML lourd) + hébergé (cookie OIDC, lourd grisé), piloté par VITE_DEPLOY_TARGET
│   ├── packages/proto/                # Prototype design = Vue+Pinia PWA (SOURCE DE VÉRITÉ du design)
│   └── packages/parity/               # Tooling QA local-only (Playwright, Maestro flows, screenshots)
├── ml/                                # Python standalone : FastAPI, entraînement, fetch (Numista/Wiki/eBay)
├── supabase/                          # Migrations SQL + types générés (legacy, en cours de retrait)
├── shared/                            # Package workspace `@eurio/shared` : tokens.css (R2) + fixtures/
├── scripts/                           # Générateurs et utilitaires cross-module (Node)
├── infra/
│   ├── eurio-api/                     # FastAPI léger sur VPS (eurio-api.musubi.dev)
│   ├── eurio-admin/                   # Nginx static sur VPS (eurio-admin.musubi.dev)
│   ├── minio/                         # MinIO assets (eurio-s3.musubi.dev)
│   └── backup/                        # Chaîne de sauvegarde — VPS UNIQUEMENT (cf. §Sauvegarde)
├── docs/
│   ├── work-in-progress/auth-redesign/# DESIGN.md + ARCHITECTURE.md + RESUME + chunks
│   ├── app-implem-phases/             # Plan des 6 phases d'implémentation Android
│   ├── design/                        # Design docs
│   │   └── _shared/                   # parity-rules, components-parity, scene-parity, data-contracts, etc.
│   └── research/                      # Recherche et décisions techniques
└── Taskfile.yml                       # Point d'entrée des commandes (go-task)
```

### Architecture frontend (CRITIQUE — à graver)

> ✅ **Fusion faite (R1, 2026-06-30).** **UN seul front** = `admin/packages/studio-local`,
> servi à deux endroits via **un seul réglage de build** `VITE_DEPLOY_TARGET` (cf.
> `studio-local/src/shared/config/deploy-target.ts`). `admin-vps` **supprimé**.

**Un seul codebase, un seul backend** `eurio-api.musubi.dev`, deux modes :

| | **local** (`VITE_DEPLOY_TARGET=local`, défaut) | **hébergé** (`=hosted`) |
|---|---|---|
| **Où** | Mac/PC, `pnpm dev` sur `localhost:5173` | VPS, `https://eurio-admin.musubi.dev` |
| **Auth** | Bearer PAT depuis `.env.local` (gitignored) | Cookie OIDC posé par eurio-api après Authentik |
| **Heavy ML `:8042`** | actif (crops, scrape, training, lab, bench…) | **grisé + notice** (`hasLocalMlApi`=false ; mixed-content interdit) |
| **Features légères** | toutes | toutes (review consultation, users, tokens, KPIs, édition métadonnées) |
| **Mobile** | non | oui |

- **Auth-adapter** : `studio-local/src/shared/api/eurio-api.ts` choisit Bearer (pat) vs
  cookie (`credentials:'include'`) selon `AUTH_MODE` dérivé de `VITE_DEPLOY_TARGET`.
- **Capacité `hasLocalMlApi`** : `stores/capabilities.ts` (baseline `deploy-target` + ping
  `:8042/health` en local). Les **routes lourdes** sont marquées `meta.heavy` (`app/router.ts`) ;
  `AppLayout` grise la nav et rend `LocalOnlyNotice` à leur place quand `hasLocalMlApi` est faux.
- **Ajouter une feature lourde** (tape `:8042`) : marque sa route `meta: { heavy: true }` +
  l'item nav `heavy: true`. Pas besoin de gérer le gating ailleurs. Aucune feature n'est
  « interdite » par mode — le lourd se grise tout seul en hébergé.

Cible/raisonnement complet : `docs/work-in-progress/model-b/README.md` §Front.

### Déploiement admin

- **Front hébergé** (`studio-local` mode hosted) : déployé sur le VPS via `infra/eurio-admin/`
  (nginx static derrière Traefik). Rebuild = `cd /opt/eurio/infra/eurio-admin && direnv exec
  /opt/eurio docker compose up -d --build` (les build args Supabase publics viennent de l'env SOPS).
  Servi à `https://eurio-admin.musubi.dev`. Pas de Vercel.
- **Front local** (`studio-local` mode local) : `pnpm dev` sur Mac/PC, jamais déployé — c'est
  le même codebase, juste lancé avec PAT + ML local.
- **Vercel** : seul `packages/proto/` y est déployé (prototype design en prebuilt, cf.
  `go-task proto:deploy`).
- `ml/` est un projet Python standalone, **pas** dans le workspace pnpm.

## Règles non-négociables

### R0. Pas de dette technique
Jamais de shortcut qui crée de la dette. Construire proprement depuis le POC. Si une solution propre n'est pas claire, on discute avant d'implémenter, pas après.

### R0bis. Front unique — gater le lourd, pas le séparer

Il n'y a **qu'un** front (`admin/packages/studio-local`). Avant d'ajouter une feature qui
appelle le ML API local (`http://127.0.0.1:8042`) : marque sa **route** `meta: { heavy: true }`
et son **item nav** `heavy: true`. Elle marche en local et se grise automatiquement en hébergé
(`hasLocalMlApi` faux) — `AppLayout` rend `LocalOnlyNotice`. Ne réintroduis **pas** un second
package front. Spec : `docs/work-in-progress/model-b/README.md` §Front.

### R1. Proto-first design (STRICT)

**Tout nouveau design doit d'abord exister dans le prototype** (`admin/packages/proto/`, Vue+Pinia PWA — source de vérité du design) avant d'être implémenté en Compose Android. _(L'ancien proto HTML `docs/design/prototype/` est archivé sous `docs/archive/design/prototype/`.)_

- Cela inclut : nouvelles scènes, nouveaux composants visuels, nouveaux layouts, nouveaux états (empty/loading/error).
- Cela n'inclut pas : adaptations techniques Android (back gesture, permission dialog), ni les deltas systémiques documentés dans `docs/design/_shared/parity-rules.md` §R6.
- Si Claude se retrouve à inventer un rendu visuel côté Android sans équivalent proto, il **doit s'arrêter et demander** à ajouter d'abord la scène proto.

Spec complète : `docs/design/_shared/parity-rules.md`.

### R2. Tokens auto-générés, jamais édités à la main

`shared/tokens.css` est la source canonique des couleurs, espacements, rayons, durées.

Les fichiers Kotlin suivants sont **auto-générés** et commencent par un header `AUTO-GENERATED — DO NOT EDIT` :

- `app-android/src/main/java/com/musubi/eurio/ui/theme/Color.kt`
- `app-android/src/main/java/com/musubi/eurio/ui/theme/Shape.kt`
- `app-android/src/main/java/com/musubi/eurio/ui/theme/Spacing.kt`

Pour modifier un token :
1. Éditer `shared/tokens.css`
2. Lancer `go-task tokens:generate`
3. Committer les deux fichiers dans le même commit

**Jamais d'édition manuelle de Color.kt / Shape.kt / Spacing.kt.** Les fichiers Type.kt et Theme.kt restent hand-written (dépendent de ressources Android et de slots M3 sémantiques).

Le générateur (`scripts/generate_tokens.mjs`) est **multi-cible** depuis 2026-08-14 :
`android` est la seule cible aujourd'hui, en ajouter une (iOS…) = une entrée dans son
registre `TARGETS`. `go-task tokens:check` ne dépend plus de git — il compare le contenu
généré au contenu sur disque et sort en 2 sur dérive. Contrat détaillé :
`docs/design/_shared/parity-rules.md` §Générateur.

**Côté JS, `shared/` se consomme comme un package** : `@eurio/shared/tokens.css` et
`@eurio/shared/fixtures/<nom>.json` — jamais en chemin relatif remontant la racine.
Côté Android QA, les fixtures sont copiées au build par la tâche Gradle `syncQaFixtures`
(l'ancien symlink `src/qa/assets/fixtures` a été retiré : il cassait au clone).

### R3. Parité proto ↔ Android trackée en tables

Avant de créer un écran ou un composant, vérifier :

- `docs/design/_shared/scene-parity.md` — table des scènes proto ↔ destinations Android
- `docs/design/_shared/components-parity.md` — table des classes CSS ↔ composables

Une entrée `❌ à proto'er` **bloque** le démarrage du code Android correspondant. Une entrée sans delta documenté est considérée comme du drift à corriger.

## Conventions de travail

### Commandes

Toutes les commandes de build, install, sync passent par **`go-task`** (jamais `task` ni invocation directe).

Commandes fréquentes :

```bash
go-task android:build            # Assemble debug APK
go-task android:install          # Build + push APK sur device
go-task android:run              # install + start
go-task android:logs             # tail logcat filtré Eurio
go-task ml:build-app-core        # Regen l'asset catalogue packagé (app_core.db) — remplace catalog_snapshot.json (P6)
go-task tokens:generate          # Regen Color/Shape/Spacing depuis tokens.css
go-task tokens:check             # Vérifier que la génération est à jour (CI)
```

### Dev shell (Nix + direnv)

`flake.nix` expose 4 devShells :

- `mac` — full stack (Android + ML CPU + admin web + maestro)
- `pc` — idem `mac` + `LD_LIBRARY_PATH` NVIDIA pour CUDA/OpenCV
- `vps` — léger : `go-task` + `minio-client` (`mc`) uniquement (Minio tourne en docker natif côté système)
- `default` — alias de `mac`, fallback pour `nix develop` hors direnv

Le `.envrc` dispatche automatiquement via `hostname -s` :

| Hostname | Profil |
|---|---|
| `Musubi42s-MacBook-Air-Oim` | `mac` |
| `desktop` | `pc` |
| `nixos` | `vps` |

Un hostname inconnu fait échouer `direnv allow` avec un message d'aide listant les options (ajouter au `case`, ou créer un `.envrc.local` avec `use flake .#<profil>`).

**Ne jamais avoir un `use flake` nu dans `.envrc`** en plus du `case` — sinon les deux shells se chargent en séquence et le premier est gaspillé.

### Secrets (SOPS + age)

**`secrets/dev.env` (chiffré SOPS+age) est la SOURCE UNIQUE de tous les secrets.** Pas de `.env` en clair, pas de second store. Chaque machine perso a sa propre clé age ; les pubkeys sont listées dans `.sops.yaml`.

- `.envrc` (committé, template `.envrc.example`) déchiffre `secrets/dev.env` au chargement du shell via `sops -d` et **exporte** les vars dans l'environnement.
- Clés privées : `~/.config/sops/age/keys.txt` sur chaque machine, jamais committées. Backup dans le password manager perso.
- **Éditer un secret : `go-task secrets:edit`** (ouvre déchiffré dans `$EDITOR`, re-chiffre à la sauvegarde). `go-task secrets:list` (noms) · `go-task secrets:check` (déchiffrable). Après édition : `direnv reload`.
- **Côté code** : le Python lit les secrets via `shared.env.load_env()` / `require()` / `numista_api_key()` (lecture `os.environ` uniquement, peuplé par `.envrc`). Jamais de parsing de `.env` à la main. Les clés Numista (8, en rotation) passent par `referential.numista_keys.KeyManager` — il n'existe **pas** de `NUMISTA_API_KEY` au singulier.
- Frontières hors-SOPS (runtimes distants) :
  - **Vercel** : `loan` (sorti du monorepo le 2026-08-14, cf. [ADR-006](docs/adr/006-extraction-loan.md)) gère ses secrets via le dashboard Vercel. Il vit maintenant dans `../loan`, dépôt séparé.
  - **VPS** : pattern **SOPS via direnv**. Le `.envrc` racine déchiffre `secrets/dev.env` (SOPS+age) au `cd /opt/eurio` et exporte les vars dans le shell. `docker compose up` les forwarde au container via `environment: { VAR: ${VAR:?missing} }` dans `docker-compose.yml`. Aucun fichier secret en clair sur disque côté `infra/*/`. La clé age reste sur la machine (`~/.config/sops/age/keys.txt`, jamais committée). Pour les contextes scriptés (cron, systemd), fallback explicite : `sops exec-env /opt/eurio/secrets/dev.env "docker compose up ..."`. Le pattern legacy Docker secrets (fichiers `infra/*/secrets/<name>` + `*_FILE` env var) est **déprécié** : `infra/eurio-api/` a migré (juin 2026). `infra/review/` reste **en service** (`eurio-review.musubi.dev`) : le C9 qui devait le supprimer n'existe plus — le sujet vivant est le chantier **K2** (`docs/work-in-progress/auth-redesign/ROADMAP.md`), non tranché.
- Bootstrap d'une nouvelle machine : voir `README.md §Secrets`.

### Sauvegarde — tourne sur le VPS, jamais sur Mac/PC

Chantier `backup-pipeline`, lots 0 à 5 livrés. **Hub :
`docs/work-in-progress/backup-pipeline/HANDOFF-NEXT-SESSION.md`** (état, pièges, chiffres
de référence) ; les décisions et ce qu'elles écartent sont dans `DECISIONS.md` (27
entrées).

`go-task backup:stage` · `backup:verify` · `backup:test` **ne fonctionnent que sur le
VPS** : ils dépendent de conteneurs Docker locaux (`eurio-api`, `eurio-review`, MinIO),
d'un staging de 6,6 Go et de `infra/backup/notify.conf` — tous **gitignorés**, donc
absents sur Mac/PC. Ne pas tenter de les lancer ailleurs ni de « réparer » leur absence.

⚠️ **`infra/backup/staging/` contient 6,6 Go de DONNÉES** gitignorées sur le VPS. Un
`git clean -xdf` les détruit.

### Supabase

- Accès via clé API (Postgrest) pour l'admin et l'export snapshot
- L'app Android est **offline-first** avec un catalogue packagé dans l'APK (`app-android/src/main/assets/app_core.db`, généré par `go-task ml:build-app-core`). L'ancien `catalog_snapshot.json` n'existe plus depuis P6
- Pas d'auth utilisateur pour v1 (le vault est 100% local côté Room)
- Schéma de vérité : `ml/state/schema.sql` (le canonique SQLite). ⚠️ `supabase/types/database.ts` n'est **ni généré ni importé** par quoi que ce soit — c'est de la doc de schéma historique, pas une source

### Stack technique Android

- Kotlin + Jetpack Compose + Material 3
- Navigation Compose (2.8.x)
- Room 2.6.1 (KSP, pas Kapt)
- Supabase-kt (postgrest-kt)
- Coil (chargement images)
- CameraX + LiteRT (ML on-device)
- OpenCV 4.10 (Hough circle detection)
- Koin (DI, pas encore câblé, à activer si besoin)
- minSdk 26, target 36

### ML pipeline

Voir `docs/research/detection-pipeline-unified.md`. Pipeline actuelle : YOLO11-nano + OpenCV Hough en parallèle → merge IoU → rerank ArcFace spread-based → consensus buffer 5/3 sticky.

## Documents à lire avant d'attaquer un changement

| Tu touches à… | Lis d'abord… |
|---|---|
| Nav shell / FAB / bottom bar | `docs/app-implem-phases/research-02-nav-patterns.md` |
| UX décisions produit | `docs/app-implem-phases/README.md` (14 décisions) |
| Pipeline ML scan | `docs/research/detection-pipeline-unified.md` |
| Sets (DSL, criteria, types) | `docs/design/_shared/sets-architecture.md` |
| Schéma local Room | `docs/design/_shared/data-contracts.md` |
| Stratégie offline/sync | `docs/design/_shared/offline-first.md` |
| Parité proto ↔ Android | `docs/design/_shared/parity-rules.md` |
| **Sauvegarde / restauration** | `docs/work-in-progress/backup-pipeline/HANDOFF-NEXT-SESSION.md` |
| Phase spécifique | `docs/app-implem-phases/phase-N-*.md` |

## Interdictions

- ❌ Éditer `Color.kt`, `Shape.kt`, `Spacing.kt` à la main
- ❌ Coder un écran Android sans scène proto correspondante
- ❌ Hardcoder des couleurs dans du Compose (toujours passer par `MaterialTheme.colorScheme.*` ou les vals générées)
- ❌ Créer des `TODO:` dans le code (la dette est explicite via docs ou tasks, pas enfouie dans le code)
- ❌ Utiliser `git add -A` ou `git add .` (staging explicite par fichier pour éviter les fuites de secrets)
- ❌ Éditer `secrets/dev.env` directement ou créer un `.env` en clair (fichier chiffré — utiliser `go-task secrets:edit`)
- ❌ Utiliser `task` au lieu de `go-task` dans les commandes ou les docs
