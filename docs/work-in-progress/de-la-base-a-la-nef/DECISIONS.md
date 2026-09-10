# Décisions — de la base à la nef

> Journal daté. 🟡 PROPOSÉ = tranché par l'architecte, en attente du PO.
> Une décision ne se réécrit pas : on en ajoute une qui supersède.

## D0 — L'atelier est gelé le temps du chantier · 2026-09-10 · ✅ PO le 2026-09-10

Aucun commit dans `ml/`, `studio-local/`, ni dans un autre chantier, sauf s'il débloque un critère du `PLAN.md`. Les modifications non commitées de `useLotReview.ts` et des specs `lot-*` restent en l'état.

**Pourquoi** : Kongō Gumi est mort en sortant de son métier. Le métier ici est le scan ; commits Android par mois 16, 10, 10, 3, 5, 0 pendant que l'atelier prenait 250 commits par mois.

**Ce que ça écarte** : « juste un petit lot » sur la review pendant qu'on attend un run CI.

## D1 — Pas de remaster d'historique ; `main` avance par fast-forward · 2026-09-10 · ✅ PO le 2026-09-10

`main` n'a pas divergé (`0 635`). On l'avance, on tague les branches mortes en `archive/<nom>`, on supprime les branches. ADR-005 reste 🟡 et n'est pas jouée ici.

**Pourquoi** : un remaster est une semaine de travail à risque pour un gain cosmétique. Le sol doit être posé en une session.

**Feu vert PO donné le 2026-09-10** : suppression des branches distantes, retrait du remote `codeberg`.

## D2 — CI sur GitHub Actions, via `nix develop .#ci` · 2026-09-10 · 🟡 PROPOSÉ

Un devShell `ci` léger dans `flake.nix` (python + pytest, node + pnpm, JDK + SDK Android, go-task). Le workflow ne contient aucun `pip install`.

**Pourquoi** : github est le dépôt de référence ; ADR-002 dit « tout par le flake ». Une CI qui installe autrement dérive du poste de dev en un mois.

**Ce que ça écarte** : Codeberg CI (remote abandonné), GitLab (migration non planifiée), un runner auto-hébergé sur le VPS (le VPS est le writer canonique, pas une machine de build).

**Réouverture** : si le run dépasse 20 minutes, on scinde `android` dans un job nocturne.

## D3 — `CLAUDE.md` ≤ 150 lignes, sans date · 2026-09-10 · 🟡 PROPOSÉ

Les préceptes restent ; l'état déménage dans `docs/architecture/ETAT.md`. Une règle sans ADR ni skill est écrite en ADR ou retirée.

**Pourquoi** : les préceptes de Kongō Gumi tiennent sur une page. Un fichier de règles qui porte « vérifié le 2026-08-17 » est un changelog.

## D4 — La nef s'ouvre avec ce qui existe · 2026-09-10 · 🟡 PROPOSÉ

Pas de feature, pas de modèle, pas d'écran nouveau avant la piste interne. Une pièce non reconnue est une donnée.

**Pourquoi** : la crypte sert au culte pendant que la tour attend. Une portion utilisable par génération.

## D5 — Comment compter « un scan venu d'ailleurs » · 2026-09-10 · ⏳ À TRANCHER

Options : (a) un compteur local exporté par les testeurs à la fin des 7 jours, (b) un ping minimal vers `eurio-api` à chaque scan, (c) le journal Play Console seul. L'architecte penche pour (a) : zéro réseau ajouté, zéro dépendance, conforme à « offline-first ».

## D6 — Plafond de 1 500 lignes par chantier vivant, rite trimestriel · 2026-09-10 · 🟡 PROPOSÉ

**Pourquoi** : Ise se reconstruit tous les vingt ans pour transmettre le geste. `juge-et-banc` fait 7 538 lignes et `scan-sans-retrain` 5 533 ; personne ne les relit.

## D7 — La `main` locale du VPS est archivée en tag, puis réalignée sur `github/main` · 2026-09-10 · ✅ architecte

Trouvé à l'exécution de l'étape 0 : `/opt/eurio` porte une branche `main` locale divergente (sommet `8cdd7403`, 2026-06-08 ; 23 commits sans équivalent patch dans `github/main`, des `WIP` d'avril à juin et un « update docker compose »). Le conteneur en service est bâti sur `repo-cleanup` @ `e4be1c3f`, pas sur cette `main`.

Geste : `git tag archive/vps-main main`, pousser le tag sur github, puis `git branch -f main github/main && git checkout main`. Retirer le remote `codeberg` du VPS et ses branches locales orphelines, toutes ancêtres de `github/main`.

**Pourquoi** : c'est l'application de D1 au clone du VPS. Rien n'est détruit : le tag garde les 23 commits. Aucun `docker compose` : le conteneur continue de tourner sur `e4be1c3f`, ancêtre de `main`.

## D8 — Le VPS ne pousse jamais ; sa clé github reste en lecture seule · 2026-09-10 · ✅ architecte

Trouvé à l'exécution de D7 : `git push` depuis `/opt/eurio` répond « The key you are authenticating with has been marked as read only ». La skill `eurio-vps-deploy` affirmait le contraire, et `remote.pushDefault github` y était inerte.

Geste : on garde la clé telle quelle. Un tag né sur le VPS remonte par le Mac (`git fetch ssh://serverOimNixDontpanic/opt/eurio refs/tags/<t>:refs/tags/<t>` puis `git push github <t>`). La skill est corrigée.

**Pourquoi** : le VPS est le writer canonique de la **donnée**, pas du **code**. Le code n'a qu'une entrée, le Mac vers github. Une clé en écriture sur un serveur exposé serait une voie de plus, sans lecteur pour la surveiller.

## D9 — `archive/vps-main` ne va PAS sur github ; il vit en bundle hors ligne · 2026-09-10 · ✅ architecte, supersède le push de D7

Mesuré à l'exécution : le tag traîne **201 commits et 13 012 objets** absents de github, **1 308 Mo**, dont 24 objets de plus de 10 Mo et 309 Mo de `eurio.db.bak-*` (requête : `git rev-list --objects github/main..archive/vps-main | git cat-file --batch-check`). Deux `git push` concurrents y ont passé 22 minutes sans atterrir ; tués, rien n'a atteint github.

Les 23 commits sans équivalent sont des `WIP` d'avril et mai, cinq « crop forensics chunk 8 à 12 » du 2026-05-27 et un « update docker compose » du 2026-06-08 (`git cherry github/main archive/vps-main`).

Geste : le tag reste sur le Mac et sur le VPS ; un bundle `../archives/eurio-vps-main-8cdd7403.bundle` est écrit hors dépôt (ADR-005 : « ancien historique archivé en tarball hors ligne »). La chaîne VPS de D7 se joue sans le push.

**Pourquoi** : ADR-004, les artefacts binaires sont hors de git. Pousser ce tag aurait gravé 1,3 Go de sauvegardes SQLite dans le dépôt de référence pour toujours. Rien n'est perdu : deux copies sur deux machines plus un bundle vérifié.

**Reste à faire, BACKLOG** : déposer le bundle sur MinIO pour qu'il entre dans les anneaux de sauvegarde.

## D10 — La CI de l'étape 1 porte trois jobs ; Android attend l'étape 4 · 2026-09-10 · ✅ architecte, amende D2

Mesuré avant de lancer : le `preBuild` Gradle fetch les modèles depuis MinIO avec des identifiants (ADR-004), exige `matc` installé par `go-task filament:install-matc`, et le SDK Android par `androidenv` pèse plusieurs Go. Le dépôt github est **public** (`gh repo view` → `PUBLIC`) : un secret MinIO dans Actions serait exposé aux forks.

Geste : `ci.yml` = `ml` (pytest), `admin` (vitest, typecheck si < 3 min), `tokens` (`go-task tokens:check`). Le job Android est un critère de l'**étape 4**, où la signature et ses secrets sont posés de toute façon.

**Pourquoi** : trois jobs qui crient aujourd'hui valent plus qu'un quatrième qui attend un chantier de secrets. Le fil à plomb se pose sur la pierre qu'on a.

## D11 — `pytest` entre dans le flake, pas dans la venv par accident · 2026-09-10 · ✅ architecte

Mesuré : `nix develop .#mac --command python -m pytest --version` → « No module named pytest » ; `ml/.venv/bin/python -m pytest --version` → `pytest 9.0.3`, non déclaré dans `pyproject.toml` (il arrive par une dépendance transitive). La suite complète passe pourtant : **2 795 passed en 136 s** (`ml/.venv/bin/python -m pytest -q`, 2026-09-10).

Geste : `pytest` s'ajoute à `pythonEnv` dans `flake.nix` (la venv hérite par `--system-site-packages`, comme numpy et fastapi). Le devShell `ci` est un `mkShell` léger : `pythonEnv`, `uv`, `nodejs_22`, `pnpm`, `go-task` ; ni JDK ni SDK Android.

**Pourquoi** : un outil de vérification qui n'est pas déclaré disparaît au premier rebuild de venv. ADR-002 : tout par le flake.
