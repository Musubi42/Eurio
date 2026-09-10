# CLAUDE.md — les préceptes d'Eurio

> Règles intemporelles et pointeurs, rien d'autre. Ce qui porte une date, une mesure ou un état
> de chantier vit dans [`docs/architecture/ETAT.md`](docs/architecture/ETAT.md) ; le *pourquoi*
> des règles dans [`docs/adr/README.md`](docs/adr/README.md). Lis ce fichier avant de toucher au dépôt.

## Mission

Eurio est une app Android de collection de pièces euro. L'acte central est le **scan** : l'utilisateur
pointe sa caméra sur une pièce, l'app l'identifie et propose de l'ajouter à son coffre. Tout le reste
de l'UX tourne autour de cet acte. Plan : `docs/app-implem-phases/README.md`.

## Monorepo

```
app-android/        App Kotlin/Compose (Material 3) — le produit
admin/              pnpm workspace : studio-local/ (le SEUL front admin), proto/ (source de vérité du design), parity/ (QA)
ml/                 Python standalone (hors pnpm) : FastAPI, entraînement, fetch Numista/Wiki/eBay
shared/             package `@eurio/shared` : tokens.css (R2) + fixtures/ ; scripts/ = générateurs cross-module (Node)
infra/              eurio-api/, eurio-admin/, minio/ (VPS) ; backup/ (VPS uniquement) ; supabase/ = migrations SQL legacy
docs/               adr/ (le SEUL journal de décisions) · architecture/ (état réel) · work-in-progress/ · archive/ · BACKLOG.md · design/_shared/ · research/
Taskfile.yml        point d'entrée des commandes (go-task)
```

## Règles non-négociables

**R0. Pas de dette technique.** Jamais de raccourci qui crée de la dette. Si la solution propre
n'est pas claire, on discute avant d'implémenter, pas après — en ADR si c'est structurant
(`docs/adr/README.md` §Écrire une ADR). La dette qui reste est écrite dans `docs/BACKLOG.md`, jamais enfouie dans le code.

**R0bis. Un seul front admin, le lourd se grise.** `admin/packages/studio-local` est le seul front
à faire vivre, servi en local (PAT, ML `:8042` actif) et hébergé (cookie OIDC, ML grisé) par
`VITE_DEPLOY_TARGET`. Une feature qui tape `:8042` marque sa route `meta: { heavy: true }` et son item
nav `heavy: true` ; le gating est fait ailleurs. Pas de second package front. Décision : ADR-011 ; état : `ETAT.md` §Front admin.

**R1. Proto-first, pour l'app Android et elle seule.** Tout nouveau design de `app-android/` (scène,
composant, layout, état empty/loading/error) existe d'abord dans le proto `admin/packages/proto/`
avant d'être implémenté en Compose. Si tu inventes un rendu côté Android sans équivalent proto,
**arrête-toi et demande**. R1 ne porte ni sur les fronts admin ni sur les outils de recette : pour un
écran d'admin, maquette d'abord dans le front où il vivra (fixtures, états vides/erreur). Spec : `docs/design/_shared/parity-rules.md`.

**R2. Tokens générés, jamais édités.** `shared/tokens.css` est la source des couleurs, espacements,
rayons, durées. `Color.kt`, `Shape.kt`, `Spacing.kt` sont générés (`AUTO-GENERATED — DO NOT EDIT`) :
éditer `tokens.css` → `go-task tokens:generate` → committer les deux dans le même commit. `Type.kt` et
`Theme.kt` restent manuels. Côté JS, `shared/` se consomme comme un package (`@eurio/shared/tokens.css`,
`@eurio/shared/fixtures/<nom>.json`), jamais en chemin relatif. Contrat : `parity-rules.md` §Générateur ; la CI joue `tokens:check`.

**R3. Parité proto ↔ Android trackée en tables.** Avant un écran ou un composant, lis `docs/design/_shared/scene-parity.md`
et `components-parity.md`. Une entrée `❌ à proto'er` **bloque** le code Android ; une entrée sans delta documenté est du drift à corriger.

## Trois machines, trois stockages

| Machine | Rôle |
|---|---|
| **Mac** (`Musubi42s-MacBook-Air-Oim`) | dev, admin, scraping, crop, review — pas de GPU |
| **PC** (`desktop`, NixOS) | entraînement — la seule machine à GPU |
| **VPS** (`nixos`) | **writer canonique** de la donnée, MinIO, API, fronts — devShell allégé |

| Stockage | Rôle |
|---|---|
| `eurio.db` (SQLite WAL, VPS) | **le canonique** — référentiel, review, cohortes, itérations |
| MinIO (`eurio-s3.musubi.dev`) | images : raws, crops, canoniques, artefacts de modèle |
| Supabase | projection read-only pour l'app en prod |

Mac et PC lisent une **réplique read-only** du canonique et écrivent par HTTP (Direction A, ADR-009).
Le calcul — bake, entraînement, artefacts — reste local à la machine qui calcule. Un `503
canonical_readonly` n'est jamais une panne : lis la skill `eurio-data-writes` avant de contourner ;
résiduels connus dans `ETAT.md` §Écritures. Détail : `docs/architecture/README.md`, `parcours.md`, `artifacts.md`.

## Skills (`.claude/skills/`) — lis-les AVANT d'agir
| Skill | Quand |
|---|---|
| `eurio-enrichment` | une classe est trop pauvre pour entraîner — scrape eBay, crop, ancres DINO |
| `eurio-banque` | avant de toucher à la banque d'ancres, aux seuils DINO, ou de comparer deux encodeurs |
| `eurio-review` | trancher des crops, décider ce qui entre en training |
| `eurio-cohort` | composer une cohorte, passer le préflight, comprendre l'expansion `design_group` |
| `eurio-run-local` | lancer la stack locale, dérouler le lab (bake → entraînement) |
| `eurio-promote` | mettre un modèle dans l'APK — la promotion remplace, elle n'accumule pas |
| `eurio-backup` | sauvegarde et restauration — avant de toucher `infra/backup/`, et le jour J |
| `eurio-data-writes` | avant de toucher une route qui écrit ; devant un `readonly database` / 503 `canonical_readonly` |
| `eurio-verify` | avant de déclarer qu'un correctif marche — ici les pannes sont muettes |
| `eurio-vps-deploy` | tout `docker compose up` sur le VPS ; une route qui marche en local et pas en prod |
| `eurio-driver` | actions méta exposées à musu-os (`actions.yml`) |

Chacune existe parce qu'on a payé le prix de son absence. Si tu t'apprêtes à improviser un outil ou une
procédure, une skill manque : cherche, puis écris-la à la fin. Méthode : `docs/skills/comment-tester-une-skill.md`.

## Commandes, devShell, secrets

- **Tout passe par `go-task`** (jamais `task`, jamais l'outil direct) : `android:build` · `android:install` · `android:run` ·
  `android:logs` · `ml:build-app-core` (catalogue `app_core.db` packagé) · `tokens:generate` · `tokens:check` · `secrets:edit`.
- **DevShell Nix + direnv** (ADR-002) : `flake.nix` expose `mac`, `pc`, `vps`, `ci` (`default` = `mac`) ; `.envrc`
  dispatche sur `hostname -s`. Jamais de `use flake` nu en plus du `case`. Hostname inconnu = ajouter au `case` ou `.envrc.local`.
- **Secrets** (ADR-015) : `secrets/dev.env`, chiffré SOPS + age, est la **source unique** ;
  `.envrc` le déchiffre et exporte les vars. Éditer : `go-task secrets:edit`, puis
  `direnv reload`. Le code lit `os.environ` (`shared.env.load_env()` / `require()`), jamais
  un fichier. Clés age dans `~/.config/sops/age/keys.txt`, jamais committées. Sur le VPS,
  même schéma via `sops exec-env` (skill `eurio-vps-deploy`). Bootstrap : `README.md` §Secrets.
- **Supabase** : accès Postgrest pour l'admin et l'export ; l'app est **offline-first** avec le
  catalogue packagé dans l'APK. Schéma de vérité : `ml/state/schema.sql`.
- **Sauvegarde** : `go-task backup:*` ne tourne **que sur le VPS** (skill `eurio-backup`, ADR-014).
  `infra/backup/staging/` y contient des données gitignorées : pas de `git clean -xdf`.

## Git — un tronc, un remote, le VPS tire

`main` est le seul tronc ; `github` le seul remote de référence. Pousse là ; le VPS **ne pousse jamais**, le
code n'entre que par le Mac. Les branches mortes sont des tags `archive/*`. Historique et pièges : `ETAT.md` §Git.

**Redéployer `eurio-api` (ou `eurio-admin`) sur le VPS**, en trois commandes : `ssh serverOimNixDontpanic` ;
`cd /opt/eurio && git fetch github main && git merge --ff-only github/main` (le `--ff-only` refuse au lieu de
fabriquer un merge) ; `cd infra/eurio-api && sops exec-env ../../secrets/dev.env "docker compose up -d --build"`.
Puis vérifie comme le dit la skill `eurio-vps-deploy` (routeurs montés, OpenAPI) — une panne y est muette.

## La CI juge

`.github/workflows/ci.yml` tourne à chaque push sur `main` et sur chaque PR : `pytest` (`ml`),
`vitest` + typecheck (`admin`), `go-task tokens:check` (`tokens`), chacun par `nix develop .#ci
--command …` — même toolchain que le poste. Suivre un run : `gh run watch --exit-status`. Rejouer un
job en local : `nix develop .#ci --command <commande du job>`. **Un test rouge ne se masque pas** : ni
`skip` sans `reason=`, ni seuil élargi, ni assert retiré — on corrige ce que le test dénonce. Ce qu'elle ne couvre pas encore : `ETAT.md` §CI.

## Interdictions

- ❌ Éditer `Color.kt`, `Shape.kt`, `Spacing.kt` à la main (R2)
- ❌ Coder un écran de l'app Android sans scène proto correspondante (R1)
- ❌ Hardcoder des couleurs dans du Compose — `MaterialTheme.colorScheme.*` ou les vals générées (R2)
- ❌ Créer des `TODO:` dans le code — la dette va dans `docs/BACKLOG.md` ou une task (R0)
- ❌ `git add -A` / `git add .` — staging explicite par fichier, contre les fuites de secrets (ADR-015)
- ❌ Éditer `secrets/dev.env` directement ou créer un `.env` en clair — `go-task secrets:edit` (ADR-015)
- ❌ Écrire `task` au lieu de `go-task` dans les commandes ou les docs
- ❌ Proposer, relancer ou planifier des séances de **capture device** — décision du PO ;
  le jeu d'évaluation vient des crops eBay (`ETAT.md` §Capture device, `juge-et-banc/SUIVI-MATRICE.md`)
- ❌ Ajouter quoi que ce soit à `admin/packages/review/` — pile en doublon en attente de chute (ADR-012)

## Lis d'abord

| Tu touches à… | Lis… |
|---|---|
| N'importe quoi de structurant | `docs/adr/README.md` — l'index, puis **une seule** ADR |
| L'état courant, un chiffre, un « où en est-on » | `docs/architecture/ETAT.md` |
| « Qu'est-ce qui reste à faire ? » | `docs/BACKLOG.md` (archivés) et `docs/work-in-progress/README.md` (vivants) |
| Où vit la donnée, où part une écriture | `docs/architecture/README.md`, `parcours.md`, `artifacts.md` ; skill `eurio-data-writes` |
| Déployer sur le VPS, une route KO en prod | skill `eurio-vps-deploy` |
| UX, nav shell / FAB / bottom bar, phase N | `docs/app-implem-phases/README.md`, `research-02-nav-patterns.md`, `phase-N-*.md` |
| Pipeline ML du scan ; ArcFace ↔ DINO, encodeurs, corpus d'éval | `docs/research/detection-pipeline-unified.md` ; `docs/work-in-progress/juge-et-banc/SUIVI-MATRICE.md` puis `CORPUS-EVAL-EBAY.md` ; état : `ETAT.md` |
| Banque d'ancres DINO, seuils | skill `eurio-banque`, puis `ETAT.md` §Chantiers vivants |
| Le crop : détection, recadrage | `docs/work-in-progress/juge-du-crop/README.md` avant d'écrire une ligne, puis ADR-017 |
| Review : file « pêche », auto-validation | `docs/work-in-progress/peche-dino/CONSTAT.md` ; `ETAT.md` §Chantiers vivants |
| Sets, schéma Room, offline/sync, parité | `docs/design/_shared/` : `sets-architecture.md`, `data-contracts.md`, `offline-first.md`, `parity-rules.md` |
| Sauvegarde / restauration | skill `eurio-backup`, puis `docs/work-in-progress/backup-pipeline/ROADMAP.md` |
