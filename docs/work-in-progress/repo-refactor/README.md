# Chantier — remise au propre du dépôt

> **Mémoire de travail.** Ce chantier survit à plusieurs sessions. Avant de lancer la
> moindre recherche, **lis la section « Déjà établi »** : elle contient des faits vérifiés
> qui ont coûté cher à découvrir. Ne les re-cherche pas, complète-les.
>
> Démarré le 2026-08-14 · Branche `repo-cleanup` (partie de `scan-corpus-funnel`)

## Objectif

Repartir sur une base propre : un dépôt sans déchets, une architecture documentée, un
historique git lisible — et `loan/` sorti dans son propre dépôt.

## Décisions déjà prises (ne pas rouvrir sans raison)

| Sujet | Décision | ADR |
|---|---|---|
| Archive de l'ancien historique | **Tarball hors ligne uniquement**, jamais poussé en ligne | [005](../../adr/005-remaster-historique-git.md) |
| Forme du nouveau `main` | **~10 commits thématiques**, pas un commit racine unique | [005](../../adr/005-remaster-historique-git.md) |
| Modèles `.tflite` de l'APK | **Sortis de git, fetchés au build** | [004](../../adr/004-artefacts-binaires-hors-git.md) |
| `loan/` | **Extrait**, alimenté par MinIO au lieu de Supabase | [006](../../adr/006-extraction-loan.md) |
| Découpage d'Eurio | **Reporté** : artefacts publiés d'abord | [007](../../adr/007-pas-de-split-eurio-avant-artefacts.md) |
| Ordre général | **Nettoyer d'abord, remaster ensuite** — sinon on grave les déchets | [005](../../adr/005-remaster-historique-git.md) |
| Secrets fuités | Clés **révoquées** par le PO. Pas de `filter-repo` requis puisque l'archive reste hors ligne | [005](../../adr/005-remaster-historique-git.md) |

## Déjà établi — faits vérifiés, ne pas re-chercher

**Le dataset de détection vient de Roboflow.** `coin-gva2j`, CC BY 4.0,
`universe.roboflow.com/yolocoin/coin-gva2j/dataset/1`. 1878 des 1908 images de
`coin_detect/` en viennent (signature `.rf.<hash>`, noms `KakaoTalk_2022…`). Les 30
autres sont des `negative_*.jpg` **à nous**. Donc `best.pt` **est régénérable**.
⚠️ Le script de re-fetch Roboflow a été retiré du repo — seule l'URL du `data.yaml` reste.

**`best.pt` est un YOLOv8-nano mono-classe.** Il ne reconnaît pas la pièce, il dit **où**
elle est : il fournit le prior à la passe Hough qui raffine le rim. Sans lui, Hough vote
sur les lettres et motifs circulaires des fonds eBay.

**Le backend VPS est du SQLite, pas du Postgres.** Le Postgres du projet, c'est Supabase.
Détail : [`../../architecture/README.md`](../../architecture/README.md).

**Les 3 packages admin « à supprimer » sont déjà supprimés de git.**
`admin-vps`, `review-admin`, `web` : **0 fichier tracké** chacun. Il ne reste que
`dist/` + `node_modules/` gitignorés sur le disque. Rien à committer, juste un `rm -rf` local.

**`admin/packages/review/` est vivant** — 10 fichiers trackés, buildé par
`infra/review/Dockerfile`, servi sur `eurio-review.musubi.dev`. C'est le chantier **K2
non tranché**, et son déclencheur de suppression a disparu (`CLAUDE.md` dit « supprimé
à C9 », or C9 n'existe plus).

**Supabase n'est pas décoratif** : `build_app_core.py` **lit Supabase** pour produire
`app_core.db`, le catalogue offline de l'APK. Le retrait de Supabase et la publication
d'`app_core` sont donc **le même chantier**.

**git est le transport Mac→PC des poids.** Le casser est **silencieux** : au prochain
`reset --hard`, les fichiers disparaissent, l'échec n'arrive qu'au premier appel de
`normalize_snap.py`.

**Il n'y a aucune CI**, aucun hook, et aucune tâche « lancer toute la suite de tests ».
17 tests étaient rouges au 2026-06-30 (documenté, non revérifié depuis).

**Chiffres corrigés** (des docs anciennes en citent de faux) :
`scan-corpus-funnel` est **+374** sur `main` (pas 21) · `ml/datasets/` tracké = **33 Mo**
(pas 2,5 Go) · `.git` = **198 Mo**.

## Lots

### ✅ Lot 0 — Filet de sécurité *(partiel)*
- [x] Tarball des 30 négatifs + provenance Roboflow →
      `~/Documents/Musubi42/eurio-backups/eurio-detection-negatives-20260814.tar.gz`
      (2,5 Mo, sha256 `85ba18d5…`)
- [ ] **Pousser ce tarball sur pCloud** ← PO
- [ ] Tarball complet de l'arbre de travail (`.git` inclus) → pCloud, **restauration testée**

### 🟡 Lot 1 — Déchets francs *(en cours)*
- [x] `05be2dd` — 6 variantes de quantization + 3 résidus onnx2tf + 2 `labels.cache`
      retirés de l'index (`--cached`, rien ne quitte le disque). −30 395 lignes, ~33 Mo
- [ ] `rm -rf` local des 3 packages admin morts
- [ ] `ml/swagger.yaml` — c'est la spec **de Numista**, zéro référence dans le repo
- [ ] Chemins morts `ml/api/` → `ml/serving/` dans **12 docs vivantes**
      (`docs/roadmap.md`, `docs/refacto-ml/README.md`, `docs/work-in-progress/README.md`,
      `hardening-2026-07/README.md`, `dino-suggestions/KICKOFF.md`,
      `cohort-readiness/HANDOFF.md`…)
- [ ] Cocher **K1 ✅** dans `auth-redesign/ROADMAP.md` (travail fait, doc en retard)
- [ ] Ré-adresser `docs/research/sources-admin-page.md` (pointe `admin/packages/web/`)
- [ ] `local-sync/HANDOFF-next-session.md` → `docs/archive/` (**périmé et trompeur** :
      dit « C4-C8 pas déployé » alors que si)
- [ ] Réconcilier ou archiver `docs/DECISIONS.md` (2026-04-15, contredit par le repo)

### ⬜ Lot 2 — Extraction de `loan/`
Couper `loan/src/app/globals.css:2`, créer le dépôt, basculer l'alimentation sur MinIO.

### ⬜ Lot 3 — `@eurio/tokens` + générateur multi-cible
Package = `tokens.css` + `shared/fixtures/`. Tue au passage le symlink
`app-android/src/qa/assets/fixtures`.

### ⬜ Lot 4 — Registre d'artefacts MinIO
Le gros morceau. Sort les binaires de git **et** rend le split possible.
**Le fetch doit être vérifié sur le PC avant tout `git rm`.**

### ⬜ Lot 5 — Remaster git
Sur un arbre déjà propre. Statuer sur `source-lmdlp-rebuild` (+4, travail fini non mergé)
**avant**, sinon il est perdu.

### ⬜ Lot 6 — Split d'Eurio
Quand iOS arrive. Après le lot 4, c'est du déplacement de dossiers.

## Questions ouvertes — bloquantes

| # | Question | Bloque |
|---|---|---|
| 1 | **Le build APK doit-il rester possible hors ligne ?** `local_path()` n'a pas de fallback par design | Lot 4 |
| 2 | Nom du **dossier parent** (`Documents/Musubi42/bizz/…`) accueillant `eurio/` et `loan/` | Lot 2 |
| 3 | `loan` lit-il le **même artefact `app_core`** que l'app (schéma v2), ou garde-t-il son `catalog.json` ? | Lot 2 |
| 4 | **K2** : le service `eurio-review.musubi.dev` tourne-t-il encore, feature abandonnée ou différée ? | Lot 1 |
| 5 | Plan de retrait de **Supabase** : par quoi est-il remplacé pour l'app ? | Lot 4 |
| 6 | `source-lmdlp-rebuild` : merger ou abandonner ? | Lot 5 |

## Pièges à ne pas réintroduire

1. **`APP_CORE_VERSION = 1`**, codé en dur, jamais incrémenté. Un `app_core.db` neuf sans
   incrément ⇒ l'app **skippe le bootstrap en silence**.
2. **`POST /export/deploy` skippe silencieusement** les sources manquantes : renvoie
   `200 {count: 0}`. Un déploiement raté ne lève pas.
3. **`ml/tasks.yml` → `ml:deploy`** copie depuis `ml/output/`, que `ml/serving/server.py`
   déclare supprimé. Trois mécanismes de déploiement concurrents.
4. **`ml/tests/conftest.py`** a une fixture **autouse** qui mocke MinIO : tout nouveau code
   de fetch sera **stubbé, donc non testé**, sauf opt-out explicite.
5. **`coin_detect/data.yaml`** a des chemins absolus périmés (`…/Musubi42/Eurio/…` au lieu
   de `…/bizz/Eurio/…`) — déjà cassé sur le Mac.
6. **Ne jamais juger la fraîcheur d'un chantier au `git log` du dossier** : 14 dossiers de
   `work-in-progress/` datent du 2026-06-07, qui est un **déplacement en masse**, pas de
   l'activité.
7. **`crop-forensics` est gelé, pas vieux** : ses signaux ont été **réfutés au bench**.
   Le coder en l'état serait une erreur.
