# ADR-007 — Ne pas découper Eurio avant d'avoir des artefacts publiés

**Date :** 2026-08-14
**Statut :** 🟡 Proposée — arbitrage PO non rendu sur le split lui-même.
**Étapes 1 et 2 exécutées le 2026-08-14** (voir §Exécution).

## Contexte

Le PO envisage de découper le monorepo en plusieurs dépôts : « un projet Android, un
projet iOS futur, un projet ml, un projet admin ». Motivation légitime : Eurio a grossi,
un dépôt unique pour tout gérer ne suffit plus.

Une cartographie exhaustive des couplages a été faite. Ce découpage **traverse les deux
couplages les plus coûteux du repo** :

**1. `ml/` écrit directement dans `app-android/` et `admin/packages/proto/`.**
`ml/export/build_app_core.py` écrit dans `admin/packages/proto/public/data/` **et**
`app-android/src/main/assets/`. Six chemins d'écriture croisés au total
(`build_app_core_qa.py`, `ml/scripts/promote_prod_assets.py`, `ml/tasks.yml`,
`build_shared_reverse_assets.py`, et l'endpoint HTTP `POST /export/deploy`), plus deux
lectures en sens inverse — `ml/training/foundation/anchors.py` lit les assets Android
**comme entrée d'entraînement**. Tous ces scripts résolvent `_REPO_ROOT = ml/..` : dans
des dépôts séparés, ils échouent immédiatement.

**2. `shared/tokens.css` a cinq consommateurs** (proto, studio-local, review, loan,
et le générateur Kotlin), tous par imports relatifs remontant **au-dessus** de la racine
du package. Et `app-android/src/qa/assets/fixtures` est un **symlink** vers
`../../../../shared/fixtures` : un clone du seul dépôt Android donne un symlink cassé.

Ces deux couplages portent précisément les règles non-négociables du projet :
**R2** exige que `tokens.css` et les `.kt` générés soient committés **dans le même commit** ;
**R1** (proto-first) est en revanche **100 % documentaire** — aucune ligne Kotlin ne dépend
du proto, `settings.gradle.kts` n'inclut que `:app-android`.

Enfin, la proposition **oublie deux modules** : `shared/` (consommé par cinq modules) et
`infra/` (dont les images se construisent depuis `../../ml`, `../../admin`, `../../shared`).

## Décision

**Ne pas découper par dossier. Découper par artefact publié — et construire les artefacts
d'abord, à l'intérieur du monorepo.**

Ordre proposé :
1. Extraire `loan/` ([ADR-006](./006-extraction-loan.md)) — vraie ligne de faille, risque nul.
2. Publier `@eurio/tokens` (`tokens.css` + `shared/fixtures/`) et rendre
   `scripts/generate_tokens.mjs` **multi-cible** — il est aujourd'hui mono-cible,
   chemin Compose codé en dur.
3. Publier les artefacts `app_core` et modèles ([ADR-004](./004-artefacts-binaires-hors-git.md)).
4. **Seulement ensuite**, découper ml / android / admin si ça se justifie encore.

**Argument central** : les étapes 2 et 3 sont **dues de toute façon**. Le jour où iOS
arrive, il faudra un générateur de tokens multi-cible et un catalogue publié — il
n'existe aujourd'hui **aucun** chemin pour qu'un dépôt iOS consomme l'un ou l'autre.
Ce ne sont donc pas des prérequis au split : le split en est le **sous-produit gratuit**.
Une fois ces coutures propres, découper devient une journée de travail. Sans elles, c'est
impossible sans casser R1/R2.

## Alternatives considérées

| Option | Verdict |
|---|---|
| Split immédiat android / ml / admin | Casse `go-task proto:deploy`, `parity:capture-proto` et la chaîne `app_core` dès le premier jour |
| Rester en monorepo indéfiniment | Ne règle pas le vrai problème : la duplication du contrat `app_core` en 3 langages, et l'arrivée d'iOS |
| **Coutures d'abord, split ensuite** | Bénéfice immédiat même si le split n'a jamais lieu |

## Exécution (2026-08-14)

**Étape 1** — `loan/` extrait ([ADR-006](./006-extraction-loan.md)). ✅

**Étape 2** — couture des tokens et fixtures. ✅

| Fait | Détail | Vérifié par |
|---|---|---|
| `shared/` devient `@eurio/shared` | package workspace privé, `exports` sur `./tokens.css` et `./fixtures/*.json` ; entrée `../shared` dans `admin/pnpm-workspace.yaml` | `pnpm install`, lien créé dans les 3 packages |
| 5 imports relatifs supprimés | proto (`@shared` ×3 + alias Vite retiré), studio-local (`../../../../../shared/…`), review (`../../../../shared/…`) → `@eurio/shared/…` | **builds proto + studio-local + review verts**, `--indigo-700` présent dans le CSS produit |
| Générateur **multi-cible** | `generate_android_tokens.mjs` → `generate_tokens.mjs` : parsing/CLI/rapport mutualisés, registre `TARGETS`, `--target`, `--check`, `--help` | sortie Kotlin **identique au bit près** hors la ligne d'en-tête qui nomme le script |
| `tokens:check` ne dépend plus de git | comparait via `git diff --exit-code` ; compare désormais le contenu généré au disque, sortie 2 sur dérive → marche sur arbre sale et hors dépôt | dérive simulée → exit 2 ; arbre propre → exit 0 |
| **Symlink Android supprimé** | `src/qa/assets/fixtures -> ../../../../shared/fixtures` remplacé par la tâche Gradle `syncQaFixtures` (`Sync`, wired sur `preBuild`, sortie gitignorée) | `./gradlew :app-android:syncQaFixtures` exécuté, 3 presets matérialisés |
| 🔴 `infra/review/Dockerfile` réparé | il ne copiait que `tokens.css` vers `/shared/` : sans `package.json`, `pnpm install --frozen-lockfile` aurait **échoué au déploiement** | layout `/admin` + `/shared` simulé, install verte |

`lockfileVersion` reste `9.0` — compatible avec le pnpm 9.12.0 des images.
`infra/eurio-admin/Dockerfile` copiait déjà `shared/` en entier : rien à changer.

**Reste ouvert** : le middleware `/shared/` de `studio-local/vite.config.ts` n'a plus
aucun demandeur (vérifié : aucune source, aucun bundle). Il est annoté VESTIGE et
conservé — le viewer de parité n'a pas pu être testé. À supprimer dès qu'une session
confirme que `go-task parity:*` s'en passe.

## Conséquences

- Le gain est immédiat **même sans split** : les coutures répondent à la fiche F06
  (contrat `app_core` dupliqué en Python, TS et Kotlin, **sans aucun générateur ni test
  de comparaison**) et à la dérive des types studio-local ↔ ml.
- Une **vraie CI reste à créer** : il n'y en a aucune (`.github/` absent, aucun hook).
  `go-task tokens:check` n'est qu'une garde locale. Un `tokens:check` inter-dépôts ne
  serait plus un `git diff --exit-code` mais une comparaison de version.
- La frontière **admin ↔ ml est déjà propre** (HTTP `:8042` + `eurio-api.musubi.dev`,
  URLs configurables) : c'est le seul trait du découpage proposé qui suit une faille
  naturelle. Elle pourra être coupée en premier si le besoin devient pressant.
- **Décision reportée, pas annulée.** À revisiter quand iOS démarre pour de bon.
