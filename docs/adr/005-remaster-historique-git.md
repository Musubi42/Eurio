# ADR-005 — Remaster de l'historique git sur une base propre

**Date :** 2026-08-14
**Statut :** 🟡 Proposée — méthode arrêtée avec le PO, exécution non commencée

## Contexte

L'historique du dépôt n'est plus exploitable :

- **60 commits au message `WIP`** dans l'historique poussé.
- **`main` (`a82d8cd`) est abandonné** : la branche de travail `scan-corpus-funnel` a
  **374 commits d'avance**. `sources-jo-wikipedia` (+365) en est un ancêtre, donc redondante.
  `source-lmdlp-rebuild` (+4) porte du travail fini jamais mergé.
- Des secrets ont fuité dans l'historique des **deux** remotes (service_role Supabase,
  eBay PROD, Numista). **Les clés ont été révoquées par le PO** — l'urgence est retombée,
  mais les valeurs restent lisibles dans l'historique.
- ~50 Mo d'artefacts binaires y sont gravés (cf. [ADR-004](./004-artefacts-binaires-hors-git.md)).

Un `filter-repo` a **déjà eu lieu** le 2026-06-30 (purge de `ml/lab/iterations` et
`ml/cache`) : le PO en connaît le coût et la coordination `reset --hard` qu'il impose.

## Décision

Repartir d'un `main` propre, avec l'ancien historique archivé **hors ligne**.

1. **Tarball complet** de l'arbre de travail — `loan/`, poids, artefacts de toolchain,
   `.git` compris — vers pCloud, **restauration testée** avant de continuer.
2. Nettoyer d'abord, remaster ensuite (voir Conséquences).
3. Nouveau `main` reconstruit en **une dizaine de commits thématiques**
   (`chore: base`, `feat(ml): …`, `feat(android): …`) plutôt qu'un commit racine unique.
4. Ancien historique conservé **uniquement dans le tarball**, jamais poussé.

## Alternatives considérées

| Option | Verdict |
|---|---|
| `filter-repo` seul (purge blobs, garde la forme) | Réécrit **tous** les hashes de toute façon ; garde 60 commits `WIP` sans valeur |
| Commit racine unique | `git log` inutilisable, `git bisect` impossible sur 4700 fichiers. **Rejeté** |
| Dépôt `eurio-archive` poussé en ligne | Imposerait de **filtrer les secrets** de l'archive — refait tout le travail. **Rejeté** |
| **Commits thématiques + archive en tarball hors ligne** | Historique lisible, aucune purge de secrets nécessaire dans l'archive |

**Corollaire important** : parce que l'archive reste hors ligne, **il n'y a pas besoin de
`filter-repo` sur les secrets**. Ça supprime une étape entière. Si un jour l'archive est
mise en ligne, il faudra la filtrer d'abord.

## Conséquences

**Ordre imposé — nettoyer AVANT de remaster.** Remaster d'abord graverait les déchets
(packages morts, chemins morts, artefacts de toolchain) dans le nouveau commit racine.
Le remaster est la **photo finale**, pas le point de départ.

**Les hashes cités dans la doc vont pointer dans le vide.** Les HANDOFF renvoient à
`8dc06b3`, `ce3a802`, `11dd11b`, `96ed9cb`… Ces références restent retrouvables **dans le
tarball d'archive uniquement**. À accepter consciemment ; c'est le prix de la base propre.

**Le PC doit être resynchronisé** par `reset --hard` après le remaster, comme en juin.
À coordonner : ne pas remaster pendant qu'un entraînement tourne.

**Les 3 branches mortes** (`coin-richness/p3-schema`, `data-harmonization`,
`debug-data-taxonomy`) disparaissent. `source-lmdlp-rebuild` porte du travail fini —
**à merger ou abandonner explicitement avant le remaster**, sinon il est perdu.
