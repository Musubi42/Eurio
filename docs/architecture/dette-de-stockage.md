# Dette de stockage — le flux est bon, le rangement l'est moins

> Constat de fin de session **2026-08-18**. Tous les points ci-dessous ont été
> **mesurés**, pas supposés — chacun a coûté du temps à quelqu'un cette
> semaine-là. Ce document n'est pas un plan : c'est l'inventaire à traiter dans
> une passe dédiée, plus tard.
>
> À lire à côté de [`README.md`](./README.md) (par stockage),
> [`parcours.md`](./parcours.md) (par geste) et
> [`artifacts.md`](./artifacts.md) (par artefact).

## Le diagnostic en une phrase

**Le flux fonctionne** — la donnée part au bon endroit, arrive, et les parcours 4
et 5 ont été déroulés de bout en bout. **Le rangement, lui, a des reliquats** :
des tables prévues puis abandonnées, des colonnes dénormalisées jamais
alimentées, et des noms qui se ressemblent trop. Aucun de ces défauts ne casse
quoi que ce soit — c'est précisément le problème : **ils font perdre du temps en
silence**, et ils font conclure faux.

## L'inventaire, mesuré

| Reliquat | Ce qu'on croit | Ce qui est vrai | Coût constaté |
|---|---|---|---|
| **`coins.mintage`** | le tirage | **vide, 0/689** — jamais alimentée | a fait conclure « le tirage n'existe pas » alors qu'il y a **3 246 observations** dans `mint_release_observations` |
| **`cohort_members`** | les membres d'une cohorte | **vide**, aucun writer ne la maintient ; les membres vivent dans `experiment_cohorts.eurio_ids_json` | `/operations/cohorts` annonçait `n_members: 0` pour **toutes** les cohortes. Corrigé le 2026-08-18 |
| **`coin_aliases`** | un journal de renommage | **69 lignes de vocabulaire marché** pour le theme-matcher eBay | a failli servir à consigner des renommages de slug, ce qui l'aurait détournée |
| **`eurio_id_migrations`** | — (on ignore qu'elle existe) | **la bonne table** pour rename/split/merge/retire, classée patrimoine, 3 lignes | aucune route `/ingest/*` ne l'expose : on ne peut pas y écrire depuis une machine de dev |
| **`review.db` / `training.db`** | des bases du projet | **froides**, legacy (juin 2026) | apparaissent dans `ls ml/state/*.db` et se prennent pour des destinations valides |
| **`ml/shared/state/eurio.db`** | — | ancienne DB de quota, plus lue, **encore trackée dans git** | — |
| **`serving/review_queue` vs `review/review_queue_routes`** | un seul module | **deux modules homonymes** servant le même préfixe `/review-queue`, l'un lean et monté, l'autre lourd et skippé | le log de boot du VPS annonce « review_queue skippé » alors que `/review-queue/*` répond 200 |
| **`image_assets.eurio_id` vs `source_images.target_eurio_id`** | la pièce du crop | deux notions distinctes : le **label tranché** et la **cible de découverte** | deux mesures honnêtes de « les candidats de telle classe » ont rendu **59** et **0** |

## Le motif commun

Ce sont tous des cas où **deux représentations coexistent** — une prévue et une
réelle — sans que rien ne dise laquelle fait foi. Le code lit l'une, l'humain
lit l'autre, et personne ne voit l'écart parce qu'aucune des deux ne lève
d'erreur. C'est la même famille que le catalogue des pannes muettes de la skill
`eurio-verify` : *une valeur par défaut plausible là où il fallait une erreur*.

## Ce qu'une passe dédiée devrait faire

Par ordre de rendement, à trancher le moment venu :

1. **Décider, pour chaque table à double, laquelle fait foi** — et supprimer
   l'autre ou la remplir. `cohort_members` et `coins.mintage` sont les deux cas
   nets : soit on les alimente, soit on les retire du schéma.
2. **Exposer `eurio_id_migrations`** par une route d'ingestion : c'est la seule
   table patrimoine qu'on ne peut pas alimenter depuis une machine de dev, et
   elle bloque le remapping du golden set de bench.
3. **Renommer l'un des deux `review_queue`** — le coût est un log de boot qui
   ment, et il a déjà fait chercher un routeur absent qui était monté.
4. **Sortir les bases froides** (`review.db`, `training.db`,
   `ml/shared/state/eurio.db`) du répertoire de travail et de git.
5. **Nommer les deux attributions** (`label tranché` vs `cible de découverte`)
   partout où elles apparaissent — c'est un problème de vocabulaire avant d'être
   un problème de schéma.

⚠️ Aucun de ces points n'est urgent, et aucun ne bloque la giga-cohorte. Ils se
paient en heures perdues, pas en pannes.
