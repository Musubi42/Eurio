# ADR-009 — Direction A : un seul writer du canonique, le VPS

- **Statut** : ✅ Acceptée
- **Date** : 2026-07-03 (décision PO) · migration engagée le jour même, `lab_writes` livré le 2026-08-16
- **Supersède** : l'event-log de `local-sync/` (2026-07-03, invalidé le jour de son écriture),
  le double-write de `model-b/`, et le lease MinIO sur `eurio.db` décrit dans `refacto-ml/adr.md`

## Contexte

Trois machines travaillent sur la même donnée : le Mac (dev, scrape, crop, review),
le PC (entraînement GPU), le VPS (toujours allumé). Pendant six mois on a essayé de
faire vivre **plusieurs copies inscriptibles** de `eurio.db` et de les faire converger —
d'abord par un lease MinIO (« hack dégueu » assumé), puis par un event-log avec outbox
et `op_id` de déduplication.

L'event-log a été **réfuté par la mesure**, le jour même de sa livraison. Diagnostic
triangulé Mac / VPS / PC sur `at-2005-2eur-50th-anniversary-…` :

| | crops | train-elig | needs_review | rejetés | outbox |
|---|---:|---:|---:|---:|---|
| Mac | 273 | 91 | 65 | 106 | vide |
| VPS | 252 | 100 | 42 | 106 | (hub) |
| PC | 252 | 100 | 42 | 106 | vide |

**Même log d'events, outbox vides, dernier sync vert — et trois états différents.**
Rejouer le même log ne donne pas le même résultat selon la machine. Deux causes,
toutes deux structurelles :

1. **Le bulk ne voyage pas.** 21 crops n'existaient que sur le Mac. Un event-log
   transporte des décisions *sur* des lignes, jamais l'**existence** d'une ligne.
2. **Le log est partiel par construction.** Chaque colonne autoritative a des
   écrivains eventés **et** non-eventés — les colonnes dérivées (`face`, `denom`,
   `resolution_status`, `training_eligible`) sont recalculées localement par la
   pipeline ML, et les eventer ferait s'entre-écraser les machines en LWW.

Compléter les events aurait été du whack-a-mole permanent : chaque nouveau chemin
d'écriture rouvre la fuite.

## Décision

**Une seule copie de `eurio.db` est inscriptible : celle du VPS, et seul `eurio-api`
l'ouvre en écriture.**

- Mac et PC lisent une **réplique read-only** (`ml/state/eurio.replica.db`), rafraîchie
  par `sqlite3_rsync` incrémental (`go-task ml:db:pull-replica`), fallback
  `GET /db/replica` (snapshot `VACUUM INTO` + sha).
- Toute écriture part en **HTTP vers le VPS** : `POST /ingest/run`, `/ingest/crops`,
  `/ingest/dino`, `lab_writes` pour les dimensions du lab.
- Le VPS **applique dans l'ordre de réception**. Pas de merge, pas de LWW par champ,
  donc pas de divergence possible.
- Le **compute lourd reste local** (le VPS n'a pas de GPU) mais n'écrit rien
  localement : il calcule, puis POST son résultat.
- L'UI optimiste est une **couche d'affichage**, jamais un canonique : un clic patche
  le cache local pour le rendu immédiat et enfile un forward ; l'état vrai revient au
  prochain pull.

La donnée ne passe **jamais** par git.

## Alternatives considérées

| Option | Verdict |
|---|---|
| Lease MinIO sur `eurio.db`, une machine à la fois | ❌ Sérialise le travail humain, et le lease s'oublie. Bloque toute review collaborative |
| Event-log + outbox + `op_id` (LWW par champ) | ❌ **Mesuré divergent.** Le bulk ne voyage pas, et le log ne peut posséder une colonne à plusieurs écrivains |
| Compléter la couverture d'events | ❌ Whack-a-mole. Et les colonnes dérivées, eventées, s'entre-écraseraient entre machines |
| Postgres partagé sur le VPS | ❌ Une infra de plus pour un problème que le writer unique résout à coût nul. SQLite en WAL encaisse largement la charge (une décision humaine toutes les 10-30 s) |
| CRDT / réplication multi-maître | ❌ Hors de proportion. Le vrai besoin est « une seule vérité », pas « écrire partout hors ligne » |

## Conséquences

**Bonnes.** Le problème d'appartenance de colonne disparaît : `face`, `denom`,
`resolution_status`, `training_eligible`, `bbox` sont calculés et stockés à un seul
endroit. Zéro divergence par construction. La review collaborative devient possible
sans tampon (cf. [ADR-012](./012-review-collaborative-ecriture-directe.md)).

**Mauvaises, et assumées.**

- **Le devShell pose le flip Direction A** : une écriture locale échoue par défaut,
  en `readonly database` ou `503 canonical_readonly`. C'est **le piège n°1 du dépôt** —
  un 503 n'est pas une panne, c'est un appelant qui tape la mauvaise adresse. Lire la
  skill `eurio-data-writes` **avant** de contourner.
- **Le rerouting n'est pas terminé.** Résiduels mesurés le 2026-08-17 :
  `POST /review-queue/requalify-lot/batch` et `POST /coins/assets/reflag-needs-review`.
  Trancher = lire l'OpenAPI du canonique, pas deviner.
- **Tout dépend du VPS.** Hors ligne, on lit la réplique et on ne décide rien.
- **`ml/state/eurio.db` existe encore et est périmée** (6205 assets contre 12454
  dans la réplique le 2026-08-20). Toute mesure se fait sur `eurio.replica.db`.
- Les scripts de migration one-shot doivent tourner **contre le VPS**, jamais en local.

## Voir aussi

- État courant : [`../architecture/README.md`](../architecture/README.md) §Les flux réels
- Par geste : [`../architecture/parcours.md`](../architecture/parcours.md)
- Skill : `eurio-data-writes`
- Raisonnement d'origine, conservé : [`../archive/local-sync/`](../archive/local-sync/)
