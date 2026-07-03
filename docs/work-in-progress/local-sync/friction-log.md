# Direction A — journal de friction (à nettoyer)

> Compilation brute des frictions rencontrées pendant la migration Direction A (C2a→C8),
> côté session pilote et côté agents d'implémentation (chunks C4a-C8). Objectif : servir
> de backlog pour une future session de nettoyage/durcissement — pas un post-mortem soigné.
> Chaque item : symptôme → cause → contournement utilisé → piste de fix durable.

## Build / go-task

### 1. `go-task ml:*` invisible depuis un sous-dossier
- **Symptôme** : lancer `go-task ml:xxx` depuis `ml/` ne trouvait pas la tâche (comme si le Taskfile racine n'existait pas).
- **Cause** : `ml/Taskfile.yml` — nom auto-découvert par go-task — court-circuitait la découverte du Taskfile racine.
- **Contournement** : renommé en `ml/tasks.yml` (nom non auto-découvert), inclus explicitement depuis le Taskfile racine.
- **Piste de fix durable** : documenter la règle "aucun fichier nommé `Taskfile.yml` hors racine" dans CLAUDE.md ou un lint pré-commit ; vérifier qu'aucun autre sous-dossier (`admin/`, `infra/*`) n'a la même collision.

## Shell / zsh

### 2. Scripts Python inline cassés en zsh + heredoc
- **Symptôme** : erreurs récurrentes `parse error near \n`, quotes mangées, en particulier via `ssh ... "sh -c ..."`.
- **Cause** : imbrication de guillemets simples/doubles et `\n` littéraux non interprétés à travers plusieurs couches de shell (zsh local → ssh → sh -c distant).
- **Contournement** : systématiquement écrire le script Python dans un fichier `/tmp` (ou scratchpad) puis l'exécuter, jamais d'inline multi-lignes en argument de commande.
- **Piste de fix durable** : adopter par défaut "fichier temporaire + exécution" pour tout script >1 ligne dès le départ, documenté comme convention d'agent ; envisager un helper `scripts/run_remote.sh <local_file>` qui scp+exec au lieu de sh -c inline.

## Déploiement / VPS

### 3. `sops` absent du PATH en SSH non-interactif
- **Symptôme** : la commande documentée dans le commentaire du `docker-compose.yml` (`sops exec-env ...`) échoue silencieusement/en erreur en SSH non-interactif.
- **Cause** : `sops` n'est disponible que via le devShell Nix (direnv), pas dans le PATH système d'une session SSH non-interactive.
- **Contournement** : utiliser `direnv exec /opt/eurio docker compose up -d --build` (charge le devShell Nix qui fournit `sops` et décrypte les secrets) au lieu de la commande en commentaire.
- **Piste de fix durable** : corriger le commentaire dans `infra/*/docker-compose.yml` pour pointer vers la commande `direnv exec` qui marche réellement ; supprimer/remplacer la mention `sops exec-env` trompeuse.

### 4. `db_migrate` ne boote pas sur DB neuve
- **Symptôme** : `serving.server_serve.db_migrate` plante sur une base fraîchement créée pour un smoke test.
- **Cause** : la fonction suppose l'existence préalable d'un canonique déjà bootstrappé (pas de chemin "DB vide → schéma initial" complet).
- **Contournement** : copier `ml/state/eurio.db` existant comme point de départ pour les smokes plutôt que de bootstrapper à froid.
- **Piste de fix durable** : ajouter un vrai chemin bootstrap-from-empty (idempotent) à `db_migrate`, testé en CI sur fichier `:memory:`/tmp vide.

### 5. `serving/server_serve.py` non importable en local
- **Symptôme** : import direct de `serving.server_serve` échoue avec `PermissionError` sur `/var/lib/eurio`.
- **Cause** : chemin de prod hardcodé, évalué au moment de l'import (pas seulement à l'exécution).
- **Contournement** : aucun nécessaire pour la suite de tests (les fixtures `TestClient` contournent le chemin), mais bloque toute exploration manuelle locale de ce module.
- **Piste de fix durable** : déplacer la résolution du chemin prod derrière une fonction/lazy-init ou une variable d'env avec défaut local, pour rendre le module importable partout.

## Git / autonomie

### 6. Commit + push non autorisés par un agent de workflow
- **Symptôme** : un agent du workflow C3 a committé ET poussé 3 commits "WIP" sur codeberg+github sans autorisation, dont un `docs/.../tmp.md` scratch.
- **Cause** : absence de garde-fou explicite empêchant un agent de pousser sans validation humaine dans ce contexte de workflow.
- **Contournement** : nettoyage historique (force-push) identifié comme nécessaire, **encore en attente** au moment de la rédaction de ce log.
- **Piste de fix durable** : renforcer la consigne "jamais de push sans autorisation explicite" dans le prompt système des workflows, et/ou retirer les credentials de push des agents de chunk qui n'en ont pas besoin. Faire le force-push de nettoyage dès qu'une fenêtre est validée avec l'utilisateur.

## Tests / CI

### 7. 19 (puis 18) reds préexistants polluant le signal
- **Symptôme** : la suite complète a en permanence ~18-19 échecs indépendants de tout chunk (`test_benchmark` ModuleNotFoundError sur `train_embedder`, `test_normalize_listing`, `test_wipe_referential`, `test_orchestrator`, `test_runbatch`, `test_eurio_referential`, ingest FK, `test_lab_api`…), rendant impossible un signal propre "0 régression".
- **Cause** : dette de test accumulée (imports ML manquants en environnement lean, assertions obsolètes) jamais isolée/marquée.
- **Contournement** : chaque agent de chunk a dû revérifier au cas par cas via `git stash` (parfois `git stash -u` nécessaire pour ne pas fausser la comparaison en incluant les fichiers untracked) que les échecs étaient bien pré-existants et non liés à son chunk. Un 2e red préexistant (`test_model_b_c2_c3::test_ingest` FK) n'avait pas été documenté au départ.
- **Piste de fix durable** : marquer explicitement ces ~19 tests `@pytest.mark.xfail(reason=...)` ou les isoler dans un fichier "known-broken" exclu du run par défaut, pour que tout futur diff ait un signal net "0 rouge = 0 rouge". Documenter la liste exhaustive à jour dans un seul endroit (ce fichier ou `docs/testing/known-failures.md`).

### 8. `git stash` simple trompeur pour comparer baseline
- **Symptôme** : `git stash` (sans `-u`) laisse les fichiers untracked en place (ex. `client/ingest.py`, nouveaux tests C4d), faussant la comparaison avant/après un chunk.
- **Cause** : comportement par défaut de `git stash` qui n'inclut pas les untracked.
- **Contournement** : utiliser `git stash -u` pour un diff propre, ou comparer des sous-ensembles ciblés de tests plutôt que la suite complète quand plusieurs chunks non commités s'empilent en working tree.
- **Piste de fix durable** : documenter dans le playbook d'agent "toujours `git stash -u` pour vérifier une baseline pré-existante", et committer les chunks plus tôt/plus souvent pour éviter l'empilement de diffs non commités qui complique les comparaisons.

## Architecture lean (image VPS)

### 9. `funnel.py` aurait contaminé le lean avec numpy/torch
- **Symptôme** : risque de crash-loop si `training/foundation` (numpy/torch) se retrouvait importé transitivement dans l'image lean VPS.
- **Cause** : le Dockerfile `infra/eurio-api/` ne copie pas `training/` — tout module lean doit être cv2/torch/numpy-free et ne rien importer de `training/sources/vision/scan` au top-level.
- **Contournement** : relocalisation de la logique de lecture funnel vers `store/funnel.py` (au lieu de rester à proximité de code training).
- **Piste de fix durable** : ajouter un test/lint CI qui scanne les imports top-level de tous les modules copiés dans l'image lean et échoue si un import interdit (torch/numpy/cv2/training.*) apparaît.

### 10. `lab_read_router` monté inconditionnellement
- **Symptôme** : montage inconditionnel du router au lieu d'un montage best-effort → risque de crash-loop en prod si un import lourd traîne dans sa chaîne de dépendances.
- **Cause** : absence de garde try/except au montage, contrairement au pattern "best-effort" attendu pour ce genre de route optionnelle.
- **Contournement** : vérification manuelle de la lean-safety avant chaque deploy (pas automatisé).
- **Piste de fix durable** : ajouter un montage best-effort (try/except ImportError + log) pour tous les routers optionnels côté lean, et un test d'import de l'image lean en CI (`docker run --entrypoint python ... -c "import serving.server"`).

### 11. `IngestCropsPayload` pas typé pour `cache_invalidate`
- **Symptôme** : le client envoie un champ `cache_invalidate` non déclaré côté serveur (juste documenté comme hint futur).
- **Cause** : pydantic v2 ignore silencieusement les champs additionnels par défaut (pas de `model_config extra='forbid'` dans le repo) — donc ça "marche" mais sans contrat explicite.
- **Contournement** : envoyé quand même côté client en prévision d'un futur usage serveur.
- **Piste de fix durable** : soit déclarer le champ côté serveur (même ignoré pour l'instant), soit retirer l'envoi jusqu'à ce que le serveur le consomme réellement — éviter le silence pydantic comme filet de sécurité implicite (mêmes symptôme relevé pour `DinoPredictionRow.to_dict()` qui inclut `computed_at` absent du modèle pydantic de la route).

### 12. Gates qualité non routés au canonique (C4d, différé)
- **Symptôme** : `scripts/gate_standard_vision.py` et `serving/bench_routes.py` restent des `UPDATE image_assets` bruts, non routés au VPS.
- **Cause** : mapper leur sémantique (rejet + fermeture `review_queue` + state event) sur `apply_set_training_eligible` perdrait des effets de bord métier importants (fermeture review_queue, rejet réversible) — décision produit nécessaire avant de coder une solution.
- **Contournement** : laissé tel quel, marqué `status=partial` pour C4d.
- **Piste de fix durable** : trancher avec le PO entre (a) étendre `store/decisions.py` avec un `apply_reject(conn, asset_id, review_id, reason)` canonique + route `/decisions/reject`, ou (b) accepter la perte de sémantique en basculant sur `training_eligible=0` seul. Item ouvert explicite, à ne pas oublier.

### 13. `backfill_face`/`backfill_denom` tournent sur GPU, pas vraiment VPS-only
- **Symptôme** : le garde-fou C7 (refuse de tourner si la machine est cliente) s'applique à des scripts qui, en pratique, doivent tourner sur GPU Mac/PC — tension avec la doctrine "VPS-only".
- **Cause** : dépend d'une décision PO différée (C4d) sur une éventuelle route `/ingest/dino` qui permettrait de déporter le calcul GPU tout en gardant l'écriture canonique côté VPS.
- **Contournement** : documenté comme trou ouvert dans `vps-only-migrations.md`, non résolu.
- **Piste de fix durable** : trancher si ces backfills doivent rester GPU-side avec push explicite au VPS (comme `push_run`), ou être exclus de la doctrine VPS-only avec justification écrite.

### 14. Garde-fou VPS-only pas uniformément posé
- **Symptôme** : seuls les 3 `backfill_*` actifs ont reçu le garde-fou automatique ; `migrate_canonical_schema.py`/`migrate_to_minio.py` ne l'ont pas (déjà DEPRECATED avec leur propre bandeau).
- **Cause** : choix assumé de ne pas dupliquer un garde sur du code déjà marqué mort, plutôt qu'un oubli.
- **Piste de fix durable** : si l'un des deux scripts DEPRECATED redevient actif un jour, ajouter le garde à ce moment-là — noter cette dépendance dans le bandeau DEPRECATED lui-même pour ne pas le perdre.

### 15. `backfill_quality_score.py` invoqué différemment des autres
- **Symptôme** : s'exécute via `python scripts/backfill_quality_score.py` (pas `-m scripts.xxx`), sans `sys.path.insert` préexistant, cassant l'import du garde commun.
- **Cause** : convention d'invocation incohérente entre scripts de la même famille.
- **Contournement** : ajout d'un `sys.path.insert(ML_DIR)` local à ce script pour permettre l'import de `scripts._vps_only_guard`.
- **Piste de fix durable** : harmoniser l'invocation de tous les scripts `backfill_*` sur `-m scripts.xxx` (chemin d'import stable), ou centraliser un bootstrap de path commun.

## Front

### 16. Deux base URLs (VPS vs ML local) au routage subtil
- **Symptôme** : exploration front lente pour déterminer quel endpoint (lecture/écriture) doit taper `eurioApi` (VPS) vs `ML_API` local (`:8042`).
- **Cause** : absence de convention/documentation centralisée sur le routage par-endpoint ; logique implicite dispersée dans le code.
- **Piste de fix durable** : documenter une table endpoint → base URL (dans `docs/work-in-progress/model-b/README.md` ou un fichier dédié `frontend.md` de local-sync), voire un helper unique qui décide la base URL par convention de nommage plutôt que par lecture au cas par cas.

## Autres

### 17. Doc walkthrough référençait un modèle obsolète
- **Symptôme** : `walkthrough-tests.md` décrivait encore le bootstrap Mac, le badge sidebar, l'event-log HLC/outbox — modèle entièrement remplacé par Direction A.
- **Cause** : doc non mise à jour au fil des chunks C6a-C6c (retrait event-log) alors que le contenu documentait l'ancien comportement.
- **Contournement** : réécriture complète du fichier plutôt qu'édition incrémentale (C8).
- **Piste de fix durable** : rattacher la mise à jour de `walkthrough-tests.md` comme item explicite de definition-of-done pour tout chunk qui retire/remplace un mécanisme central (event-log, sync worker, etc.), pour éviter la dérive doc/code.

### 18. Bandeaux ARCHIVÉ posés de façon incohérente
- **Symptôme** : `README.md` avait déjà son bandeau ARCHIVÉ (posé antérieurement, probablement C6/C7) alors que `backend.md`/`frontend.md`/`data-schema.md` ne l'avaient pas encore.
- **Cause** : pas de check systématique "tous les docs du dossier reçoivent le bandeau en même temps".
- **Contournement** : ajouté aux 3 fichiers manquants en C8.
- **Piste de fix durable** : quand un chunk pose un bandeau ARCHIVÉ/DEPRECATED sur de la doc, vérifier via `ls`/`grep` que **tous** les fichiers du même dossier logique reçoivent le même traitement dans le même commit.

### 19. `record_tombstone()` supposé mort mais utilisé en réel (C6b)
- **Symptôme** : le plan supposait `events.py::record_tombstone()` mort (seulement utilisé par les tests sync), mais `serving/crop_edit.py::delete_crop()` l'appelait en usage réel (delete manuel de crop).
- **Cause** : audit du plan basé sur une recherche incomplète des appelants avant de planifier la suppression.
- **Contournement** : retrait de l'appel + simplification de `delete_crop()` pour un DELETE direct (le CASCADE suffit, plus de replay distant à alimenter).
- **Piste de fix durable** : avant toute suppression de fonction "supposée morte", faire un grep exhaustif des appelants (pas seulement dans les tests) et le documenter dans le plan avant exécution — pattern à généraliser à tous les futurs chunks de retrait de code.

### 20. Garde `pull_replica()` retiré sans être dans la liste explicite de suppression
- **Symptôme** : `client/replica.py::pull_replica()` avait un garde-fou actif (refuse si `sync_outbox` pending) couvert par un test (`test_sync_bootstrap.py::test_pull_replica_refuses_pending_ops`) non listé explicitement dans le plan C6b comme à supprimer.
- **Cause** : le plan listait les modules/fonctions à retirer mais pas exhaustivement tous les effets de bord qui en dépendaient (comportement testé, pas juste la fonction).
- **Contournement** : retiré car le comportement testé (le garde) a lui-même été supprimé par design C6b — cohérent mais pas explicitement anticipé dans le plan.
- **Piste de fix durable** : quand un plan de suppression cible un module, lister aussi les tests qui en dépendent (grep sur le nom de fonction dans `tests/`) pour ne pas découvrir les effets de bord en cours d'implémentation.

### 21. Point de bascule push pas où le plan l'attendait (C4c)
- **Symptôme** : router le push uniquement dans `sources/cli.py` (comme suggéré) aurait laissé `serving/sources_routes.py` (appelé depuis l'UI admin) silencieusement en Modèle A, sans jamais pousser au VPS.
- **Cause** : le CLI et la route serving appellent tous deux `run_pipeline`/`process_downloaded` directement, mais seul `sources/_base/orchestrator.py` est un point commun réel aux deux chemins d'appel — le plan visait le mauvais point d'accroche.
- **Contournement** : le push a été déplacé dans l'orchestrateur (`_maybe_push_run`), threadé via un paramètre `push: bool | None` à travers `run_pipeline`/`process_downloaded`/`resume_failed_downloads`, avec `--no-push` comme échappatoire CLI explicite.
- **Piste de fix durable** : quand un plan désigne un point d'intégration pour un comportement transverse (push, gating, etc.), vérifier d'abord tous les call-sites réels (CLI + routes serving + scripts) avant de figer le point d'accroche dans le plan — sinon risque de couverture partielle silencieuse.
