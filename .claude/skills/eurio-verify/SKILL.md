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

Le motif commun : **une valeur par défaut plausible** (0, vide, absent) là où il
aurait fallu une erreur.

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
- **Un correctif qui touche à la prod se vérifie en prod.** Le rerouting de la
  galerie était vert en test et 404 sur le VPS (ordre de montage). Le
  déploiement fait partie du correctif.

## Ce qu'on peut lancer

```bash
cd ml && ./.venv/bin/python -m pytest tests/test_lab_api.py tests/test_lab_writes.py \
  tests/test_ebay_api.py tests/test_normalize_listing.py tests/test_storage.py -q
go-task front:typecheck        # via nix develop si hors devShell
```

Il n'y a **pas** de tâche « toute la suite », et la suite complète a des échecs
pré-existants hors-scope. Cible les fichiers liés à ton changement, et dis
lesquels tu as lancés.

⚠️ Sur le PC, `test_sources_base` / `test_ingest_crops` échouent sur
`sqlite3.OperationalError: unable to open database file` — problème
d'environnement PC préexistant, sans rapport avec le code (ils passent sur Mac).
