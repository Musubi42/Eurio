---
name: eurio-verify
description: Comment vérifier un changement dans Eurio — les pannes y sont muettes. Le catalogue des échecs silencieux déjà rencontrés, et la discipline de test qui les attrape. À consulter avant de déclarer qu'un correctif marche.
---

# Vérifier dans un repo où les pannes sont muettes

> La signature d'Eurio n'est pas le crash, c'est le **silence** : un compteur qui
> ne bouge pas, une image qui ne s'affiche pas, un script qui rapporte `0 sur N`,
> une reprise qui ne reprend rien. Presque tous les défauts trouvés le
> 2026-08-16 étaient de cette famille — aucun ne levait d'erreur.

## La règle

**Un test qui ne peut pas échouer ne prouve rien.** Avant de dire qu'un
correctif marche, casse-le et vérifie que le test rougit :

```bash
cp fichier.py /tmp/f.bak
# neutraliser la ligne du correctif (ex. `if det_scale != 1.0:` → `if False:`)
./.venv/bin/python -m pytest tests/test_x.py -q      # DOIT échouer
command cp -f /tmp/f.bak fichier.py                  # `command cp` : `cp` est aliasé -i
./.venv/bin/python -m pytest tests/test_x.py -q      # revert vérifié
```

Cette passe a payé cinq fois dans une seule session — dont une où **mon propre
correctif était du code mort** : l'`ATTACH` employait un nom de fichier URI sur
une connexion sans `uri=True`, échouait toujours, et l'exception était avalée
par l'`except` juste en dessous. Aucun test ne le disait.

## Le second niveau : un test qui échoue peut quand même ne rien prouver

Une fois la mutation validée, pose la question suivante : **le test exerce-t-il
le chemin qui a causé le bug, ou seulement le prédicat qui le corrige ?**

Cas vécu le 2026-08-17, garde de `promote_iteration`. Les quatre mutations font
bien rougir (garde neutralisée, garde inversée, `--force` retiré, message
tronqué) — donc les tests ne sont pas tautologiques. Mais ils font
`monkeypatch.setattr(p, "STATE_DB", store.db_path)` : **`resolve_db_path` et
`EURIO_DB_PATH`, c'est-à-dire la cause même du bug, ne sont jamais exercés.** Une
régression dans la résolution de chemin repasserait au vert.

Le complément coûte deux commandes, et c'est lui qui prouve quelque chose :

```bash
cd ml
EURIO_DB_PATH="$PWD/state/eurio.replica.db" ./.venv/bin/python -m scripts.promote_iteration <iid> --dry-run  # doit refuser
EURIO_DB_PATH="$PWD/state/eurio.work.db"    ./.venv/bin/python -m scripts.promote_iteration <iid> --dry-run  # doit passer
```

Règle : **fais tourner le vrai point d'entrée au moins une fois**, avec la vraie
variable d'environnement. Les tests unitaires gardent le prédicat ; seule
l'exécution garde le câblage.

⚠️ Et ne lis pas le code de sortie à travers un pipe : `cmd | tail -12; echo $?`
rend le statut de `tail`, pas celui de la commande. Un refus manifeste a ainsi
été rapporté comme `exit=0`.

## Catalogue des silences déjà rencontrés

| Symptôme observable | Cause réelle |
|---|---|
| Compteur figé à `0/600` | Le job n'a jamais été créé (écriture refusée) — l'absence de progression *était* l'erreur |
| `0 récupéré sur N`, sans erreur | Un skip de reprise avalait toute la cible du script |
| Widget « 5000/5000 restants » | Écrivain et lecteur sur deux fichiers SQLite différents |
| Image absente, API en 200 | URL signée avec un hôte du réseau Docker |
| 404 « coin X not found » crédible | Une route paramétrée avalait un chemin littéral |
| Crops décentrés, aucune exception | Coordonnées laissées dans l'espace de détection |
| Deux cohortes disparues d'une copie | `cp` sur un SQLite en WAL |
| Reprise qui exclut des images à vie | Un état transitoire (`error` = panne réseau) traité comme un verdict |
| Banque d'ancres 30 % trop petite pendant des semaines, aucun log | Un `DB_PATH` littéral : le script lisait `eurio.db` (6205 assets) au lieu de la réplique (12454). **Une base périmée répond normalement** — cf. `eurio-banque` §5(a) |
| Un garde de calibration qui rend toujours « périmé » | Comparaison de dates **en chaînes** entre deux formats (`' '` 0x20 < `'T'` 0x54) : `12454` contre `0` avec `datetime()` des deux côtés — cf. `eurio-banque` §5(b) |
| Un garde posé, testé, muté — et jamais appelé | Il gardait le CLI ; le chemin réel était la route HTTP. Sept instances en deux jours (`FINDINGS.md` §8.9) |
| « La base n'a pas bougé : son `mtime` est inchangé » | **En WAL, les écritures vont d'abord dans le `-wal`.** Le 2026-08-20 la réplique portait `mtime` 03:22 et son `-wal` la seconde courante ; 64 items de review avaient changé d'état dans la journée. Le `mtime` du `.db` ne prouve rien : regarde `-wal`, ou un `MAX(<colonne de date>)` (`FINDINGS.md` §8.12 S9) |
| Un seuil « réglé », `source='db'`, et un comportement de seuil désarmé | La valeur est un **compte** relu en `int()` : `min_exemplars = 1,9` franchissait les bornes `[0, 50]` et posait un plancher effectif de **1** (S1). Un seuil entier stocké en REAL doit être refusé fractionnaire à l'écriture |
| Un `--dry-run` qui n'empêche rien | Le drapeau existait dans `argparse` et n'était **lu nulle part** : `--dry-run --execute --yes` brûlait le quota (S2). `grep -n <dest>` le montre en une seconde — un drapeau qui n'apparaît qu'une fois dans le fichier ne décide de rien |
| Un plan chiffré « impossible à dépasser » | Le préflight qui devait l'arrêter comptait sur `source_runs.n_calls` (3 pour 740 appels réels) et rendait `estimate=8` pour une vague à 1040 (S3). **Un garde branché sur un compteur faux est un garde absent** |
| Une file de review qui sert **une autre classe** sous le bon en-tête | Le périmètre vit dans l'URL et l'URL se complète en **deux temps** : la vue se monte, demande la file GLOBALE, puis `router.replace` ajoute `dino_class` et une seconde demande part. Deux requêtes à 2 ms d'écart, **et c'est la latence qui décide** laquelle s'affiche. Mesuré le 2026-08-25 : une pièce autrichienne servie sous « PÊCHE lu-2025-…-throne ». Rien ne casse, rien ne loge |
| Un correctif d'affichage qui « marche » après un `location.reload()` | Le rechargement dur **change l'ordonnancement** et cache la course. Rejoue toujours par le **chemin réel** (le lien que l'écran fabrique), pas par une URL collée : le bug de la pêche ci-dessus est invisible en rechargement direct |
| Un garde « strict hold-out » qui protège un **répertoire inexistant** | `REAL_PHOTOS_DIR = ml/data/real_photos` (`train_embedder.py:53`) — un dossier legacy, `test -d` répond « n'existe pas ». Le juge réel (`ml/datasets/eval_real_norm/`) n'y figurait pas. Et **ses deux tests fabriquaient leurs chemins SOUS ce dossier mort** (`tests/test_benchmark.py:122`, `fake_root = tmp_path / "real_photos"`) : ils passaient, ils ne prouvaient rien. Corrigé le 2026-08-25 en `REAL_PHOTO_ROOTS` (3 racines) + un garde de **contenu** sur `val/` |
| Un garde qui ne peut **pas s'importer** | `go-task ml:augment-textures-check` importait `augmentations.overlays` au lieu de `training.augmentations.overlays` — **dans deux fichiers** (`ml/tasks.yml:802` ET `Taskfile.yml:203`). `ModuleNotFoundError` avant tout verdict, depuis la création de la tâche. ⚠️ **Le code de sortie ne le distingue pas** : import cassé et verdict négatif rendent tous les deux `1` (`201` à travers go-task). Seule la SORTIE distingue les deux |
| Une base SQLite « vide » qui contient 451 lignes | `sqlite3 -readonly` sur une base **WAL sans `-shm`** échoue en `unable to open database file (14)`, message qui ne dit rien de WAL et invite à conclure « base absente ou vide ». Voir la fiche WAL ci-dessous |
| Un instantané périmé, `exit=0`, **sans un mot** | `immutable=1` **ignore le `-wal`** : dès qu'un écrivain tourne, il rend le contenu du fichier principal seul. Voir la fiche WAL ci-dessous |
| « La réplique n'a pas bougé de la journée » | **Le `mtime` du `.db` ment en WAL.** Mesuré le 2026-08-25 pendant un `VACUUM INTO` : `.db` à **01:31**, `-wal` à **17:21** — *seize heures d'écart*, et les itérations venaient d'y être écrites. Juger la fraîcheur sur le `.db` fait conclure à une panne ou déclencher un pull inutile |
| Un paramètre accepté par la route, **jamais transporté** | `POST /lab/cohorts/{id}/iterations` acceptait `augmentations_seed` sans le porter : `IterationCreatePayload` n'avait pas le champ, le runner tirait une graine **au hasard** (`iteration_runner.py:314`). Deux runs « jumeaux » auraient reçu des augmentations différentes — **et la scorecard n'affiche pas la graine**, donc l'expérience aurait été fausse sans laisser de trace. Un champ accepté n'est transporté que si un test l'affirme de bout en bout |
| `HTTP 200`, `status: pending`, `error: null` — et rien ne tourne | `POST …/launch-training` sous le flip Direction A : `create_run_row` écrit `training_runs` dans la réplique, le job détaché meurt **en moins d'une seconde** sur `attempt to write a readonly database`. Ni le code HTTP, ni le statut d'itération, ni le champ `error` ne le disent. La vérité est la table `jobs` (`status`, `error`, `log_path`) |
| Une moyenne qui rend **`p = 1,0`** sur un effet massif | La fuite de centroïdes vaut **+14,7 pts** sur les photos qu'elle a vues (McNemar `b/c = 15/0`, `p = 6,1 × 10⁻⁵`) et **−4,4 pts** sur les autres. Le global rend **+0,24 pt, `p = 1,0`** — lu seul : « pas de fuite ». **Le nombre qui trahit est `87 discordantes`** sur 451 : deux modèles qui répondent différemment 87 fois ne font pas « la même chose », ils font deux erreurs opposées qui s'annulent. Une moyenne sur deux populations dont une seule est exposée ne mesure rien |
| Un build qui ne s'exécute pas et sort en **succès** | `pnpm --filter studio-local build` → `No projects matched the filters`, **`exit=0`**. Le paquet s'appelle `eurio-studio-local`. Forme sûre : `pnpm -C packages/studio-local build` (ou `--filter eurio-studio-local`) |

Le motif commun : **une valeur par défaut plausible** (0, vide, absent) là où il
aurait fallu une erreur.

### La fiche WAL — deux pièges **opposés**, à lire ensemble

Ils tirent dans des directions contraires, et corriger l'un en ignorant l'autre
fabrique la panne inverse. **Il n'y a pas de forme universellement sûre.**

| | `-readonly base.db` | `-readonly "file:base.db?immutable=1"` | `"file:base.db?mode=ro"` |
|---|---|---|---|
| Base WAL **au repos**, `-shm` absent | ⛔ `error 14` | ✅ | ✅ |
| Un **écrivain** tourne (`:8042`, un job) | ✅ | ⛔ **sous-compte en silence** | ✅ |

**La règle : `immutable=1` au repos, `mode=ro` sinon.**

Reproduction complète, dans un bac à sable — les deux pièges, dans l'ordre :

```bash
mkdir -p /tmp/waldemo && cd /tmp/waldemo
sqlite3 t.db "PRAGMA journal_mode=WAL; CREATE TABLE x(i INTEGER); INSERT INTO x VALUES(1),(2),(3);"

# ── Piège A : la base au repos rend « erreur », pas « 3 »
rm -f t.db-shm ; chmod 555 .          # -readonly ne peut plus créer le -shm
sqlite3 -readonly t.db                    "SELECT COUNT(*) FROM x;" ; echo "exit=$?"
# Error: in prepare, unable to open database file (14)
# exit=14                    ← le message ne dit RIEN de WAL
sqlite3 -readonly "file:t.db?immutable=1" "SELECT COUNT(*) FROM x;" ; echo "exit=$?"
# 3
# exit=0                     ← immutable=1 n'a besoin d'aucun -shm
chmod 755 .

# ── Piège B : un écrivain tourne, immutable=1 rend un instantané périmé
# (une connexion python ouverte qui a inséré 4 et 5 sans checkpoint)
sqlite3 -readonly "file:t.db?immutable=1" "SELECT COUNT(*) FROM x;" ; echo "exit=$?"
# 3
# exit=0                     ← FAUX, et parfaitement plausible
sqlite3           "file:t.db?mode=ro"     "SELECT COUNT(*) FROM x;" ; echo "exit=$?"
# 5
# exit=0                     ← le vrai compte, le -wal est lu
```

⚠️ **Piège B est le plus dangereux des deux** : A crie (`exit=14`), B se tait
(`exit=0`, un nombre plausible, aucun message). Et il s'est armé tout seul le
jour où l'API a commencé à écrire dans `scan_corpus.db` — la recommandation
`immutable=1` de `LOT1-IMPORT.md` §1 était juste **quand elle a été écrite**, et
fausse trois heures plus tard. Une recette de lecture de base porte donc une
condition d'emploi, jamais seulement une commande.

Dans la même démonstration, la troisième forme du mensonge :

```
db mtime : 23:45:00
wal mtime: 23:45:45     ← les 2 lignes de plus sont là, pas dans le .db
```


## Réflexes

- **Ne conclus pas d'un code HTTP.** Le canonique répond 401 avant le routage :
  une route inexistante répond comme une route protégée. L'OpenAPI tranche.
- **Les jobs détachés ne parlent pas dans ton terminal.** Leur vérité est la
  table `jobs` (`status`, `error`, `log_path`) — cf. `eurio-data-writes`.
- **Mesure dans le bon environnement.** `sqlite3_rsync` n'existe que dans le
  devShell : une mesure faite dehors donnait 20 s au lieu de 1 s, et aurait
  condamné un design correct.
- **Vérifie la sortie complète, pas la queue.** Un `head` sur un grep a masqué
  un importeur et cassé la suite de tests ; un `tail -12` a masqué le message
  d'erreur qu'on cherchait.
- **Le repo est actif en parallèle.** Le VPS pousse des commits pendant que tu
  travailles : `git push` peut être rejeté, rebase.
- **Deux requêtes pour un même écran, c'est un ordre d'arrivée, pas un ordre
  de demande.** Espionne `window.fetch` dans le navigateur (start/end par
  requête) plutôt que de lire le code : la course se voit en trois lignes, et
  un piège armé — réponse retardée *et* empoisonnée — prouve la garde.
- **Un correctif qui touche à la prod se vérifie en prod.** Le rerouting de la
  galerie était vert en test et 404 sur le VPS (ordre de montage). Le
  déploiement fait partie du correctif.

## Ce qu'on peut lancer

```bash
cd ml && ./.venv/bin/python -m pytest tests/test_lab_api.py tests/test_lab_writes.py \
  tests/test_ebay_api.py tests/test_normalize_listing.py tests/test_storage.py \
  tests/test_promote.py tests/test_iteration_augmentations.py -q
go-task front:typecheck        # via nix develop si hors devShell
```

Il n'y a **pas** de tâche « toute la suite ». Cible les fichiers liés à ton
changement, et dis lesquels tu as lancés.

⚠️ **La phrase « la suite complète a des échecs pré-existants hors-scope » est
périmée sur le Mac.** Mesuré le 2026-08-25, sans pipe :

```bash
cd ml && ./.venv/bin/python -m pytest tests -q -p no:randomly ; echo "exit=$?"
# 2358 passed, 40 warnings in 98.18s
# exit=0
```

**0 failed.** La suite entière est donc un filet utilisable, et toute ligne
rouge appartient au changement en cours. Elle a grossi vite — 1878 le
2026-08-20, 2258 le 25 au matin, 2358 le 25 au soir : **cite toujours la
mesure du jour, jamais un chiffre lu dans une doc.** Les 40 warnings sont
préexistants (`datetime.utcnow()`, `EURIO_DB` déprécié) : pas un signal.

⚠️ Sur le PC, `test_sources_base` / `test_ingest_crops` échouent sur
`sqlite3.OperationalError: unable to open database file` — problème
d'environnement PC préexistant, sans rapport avec le code (ils passent sur Mac).
