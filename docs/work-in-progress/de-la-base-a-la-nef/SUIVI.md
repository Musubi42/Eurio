# SUIVI — de la base à la nef

> Journal daté. Chaque étape y dépose son contrat, le rapport de l'exécutant, le
> contre-rapport, et le verdict de l'architecte. Rien ne se ferme sans les trois.

## 2026-09-10 — Ouverture

Chantier ouvert sur le constat du même jour (`PLAN.md` §Constat). Six décisions
proposées dans `DECISIONS.md`, D5 laissée ouverte. **En attente du PO** : D0 (gel de
l'atelier) et D1 (feu vert sur la suppression des branches distantes et le retrait de
`codeberg`). L'étape 0 peut être jouée jusqu'à 0.3 inclus sans lui ; 0.4 et 0.5
attendent.

Deux faits trouvés à la vérification, absents des docs jusqu'ici :
- `pytest` n'est pas dans le devShell `mac` : `nix develop .#mac --command python -m pytest --version` → `No module named pytest`. La suite de 204 fichiers ne peut pas tourner depuis le shell du dépôt.
- Le build release signe avec la clé debug : `app-android/build.gradle.kts:57`.

## Étape 0 — Le sol

_Contrat : à écrire à l'ouverture de la session d'exécution._

### Contrat · 2026-09-10 · feu vert PO sur D0 et D1

**Faits établis avant de lancer** (requêtes rejouables) :
- Toutes les branches locales et distantes sont des ancêtres de `matrice-dino` (`git merge-base --is-ancestor <b> HEAD` → oui pour les 7). Rien ne se perd en les supprimant ; on tague pour garder les noms.
- `repo-cleanup` est un ancêtre de HEAD : le VPS peut avancer par fast-forward.
- L'arbre de travail porte des modifications **d'un autre chantier** (`Taskfile.yml`, `useLotReview.ts`, `LotDetailView.vue`, specs `lot-*`, trois docs `juge-du-crop/`, `secrets/dev.env`). Elles ne sont ni commitées ni écartées. `git checkout main` classique refuserait ; le geste est `git checkout -B main` depuis `matrice-dino`, qui ne change pas l'arbre.

**Entrées** : `PLAN.md` §Étape 0. **Sorties** : les six critères avec sortie collée, la table branche → tag, les trois docs corrigées.

**Interdits** : `push --force` ; `branch -D` sur une branche non taguée ; `git add -A` ; toucher aux fichiers modifiés de l'autre chantier ; sur le VPS, autre chose que `git fetch`, `git checkout main`, `git config` — aucun `docker compose`.

### Rapport de l'exécutant · 2026-09-10

Trois passes. La première a fermé 0.1, 0.2, 0.3, 0.5, 0.6 et s'est **arrêtée** sur 0.4 : `/opt/eurio` portait une `main` locale divergente (`8cdd7403`, 201 commits depuis le merge-base `24aa4636`, 23 sans équivalent patch). L'arbre a été remis sur `repo-cleanup`, les deux `docker-compose.yml` retrouvés, aucun conteneur touché. → D7.

La deuxième a buté sur `git push` depuis le VPS : « key marked as read only ». → D8, skill `eurio-vps-deploy` corrigée.

La troisième a tenté de pousser le tag depuis le Mac : 22 minutes, deux pushes concurrents, rien d'atterri. L'architecte a mesuré **1 308 Mo / 13 012 objets** dont 309 Mo de `eurio.db.bak-*`, tué les pushes. → D9, bundle `../archives/eurio-vps-main-8cdd7403.bundle` (911 Mo, `git bundle verify` ok).

Chaîne VPS finale (exit 0) : `main` réalignée sur `github/main`, `repo-cleanup` / `scan-corpus-funnel` / `sources-jo-wikipedia` supprimées avec `-d` (donc fusionnées), `codeberg` retiré, `branch.main.remote=github`. Conteneurs inchangés : `eurio-admin` Up 39 h, `eurio-api` Up 2 j, `eurio-review` et `eurio-minio` Up 2 mois.

| Critère | Sortie | Verdict |
|---|---|---|
| 0.1 | `git rev-list --count main..archive/matrice-dino` → `0` | PASS |
| 0.2 | `main` ; local = github = `122445b6` | PASS |
| 0.3 | `git tag -l 'archive/*' \| wc -l` → 8 ; `git branch \| wc -l` → 1 | PASS |
| 0.4 | VPS HEAD `main` @ `122445b6`, `branch.main.remote` = `github` | PASS |
| 0.5 | `git remote` → `github`, Mac et VPS | PASS |
| 0.6 | trois mentions restantes, toutes datées et au passé | PASS |

Branche → tag : `coin-richness/p3-schema`→`archive/coin-richness-p3-schema` 9051c20b · `data-harmonization` eae5b6da · `debug-data-taxonomy` a82d8cd0 · `repo-cleanup` 21be7b13 · `scan-corpus-funnel` d1f58122 · `source-lmdlp-rebuild` 4cf86e8c · `sources-jo-wikipedia` 36a75a57 · `matrice-dino` e4be1c3f. Les 8 tags sont sur github.

Commits de l'étape sur `main` : `a5e9341f` (ouverture), `d02288b8` (tronc unique dans les instructions), `122445b6` (mention datée dans l'index).

Restes signalés, non traités : le tag local `vps-main-preswitch-20260814` ramené par le fetch (gardé, jamais poussé) ; deux fichiers `ml/bench/gold_crop/sample.py` et `ml/tests/test_gold_crop_sample.py` modifiés par l'autre chantier.

### Contre-rapport · 2026-09-10 · relecteur neuf (sonnet), critères seuls

| Critère | Sortie | Verdict |
|---|---|---|
| 0.1 | `0` | PASS |
| 0.2 | `main` ; local = github = `d3cca1f7` | PASS |
| 0.3 | 9 tags `archive/*` locaux, 8 sur github ; 1 branche ; heads github = `main` seul | PASS |
| 0.4 | première lecture : VPS @ `122445b6` ≠ github @ `d3cca1f7` → **FAIL** ; l'architecte a joué `git fetch github main && git merge --ff-only github/main` sur le VPS ; relecture : `main` / `github` / `d3cca1f7` / une seule branche → PASS | PASS |
| 0.5 | `github` seul, Mac et VPS | PASS |
| 0.6 | trois mentions, toutes datées et au passé, jugées ligne par ligne | PASS |

Falsification : `git branch tmp-x` porte le compte à 2, que le seuil « ≤ 2 » aurait laissé passer. → critère 0.3 resserré à **1** dans `PLAN.md`. Branche supprimée, retour à 1.

Succession : « rien ne manquait ».

### Verdict de l'architecte · 2026-09-10 · **étape 0 fermée**

Le FAIL transitoire de 0.4 est réel et instructif : un commit poussé après la chaîne VPS suffit à désaligner le sol. C'est l'argument de l'étape 1, une machine qui regarde à chaque push. La 9e ref `archive/*` locale est `vps-main` (D9), volontairement absente de github.

**Étape 1 ouverte** : le fil à plomb. Préalable connu : `pytest` absent du devShell.
