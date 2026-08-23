# Plan d'implémentation — `/besoin`

> **Lots 0-2 livrés et déployés le 2026-08-23** (cf. [`../JOURNAL.md`](../JOURNAL.md)).
> **Pas de code avant validation du PO.** Chaque lot porte son test de
> vérification et le déploiement qu'il implique. Écrit le 2026-08-22, en suite
> de [`DESIGN.md`](DESIGN.md).
>
> ⚠️ **Le déploiement VPS est la panne n°1 de ce chantier.** Toute route
> nouvelle sur `eurio-api` exige `git fetch github && git merge --ff-only
> github/repo-cleanup` **puis** `docker compose up -d --build` dans
> `infra/eurio-api`. Le clone `/opt/eurio` suit encore `codeberg` : un `git
> pull` nu y répond « à jour » en toute bonne foi. Skill `eurio-vps-deploy`
> avant chaque lot marqué 🚀.

---

## L'ordre, et pourquoi il n'est pas celui de DECISIONS.md

DECISIONS.md ordonne « design O2 + O4, puis implémentation ». La mesure du
2026-08-22 impose une correction : **O4c (le désarmement du filtre pays) se
livre avant O2**, sinon O2 affiche un écran faux le jour de son branchement —
82 % des classes du palier 1 y apparaîtraient à zéro candidat.

```
Lot 0  ✅ O4c  · désarmement pays + transparence   (643d6487)
Lot 1  ✅ D8   · accepted_pending dans ClassNeed    (e5c879cf)
Lot 2  ✅ 🚀   · GET /class-need — EN PRODUCTION    (881820ce, a10db7d1)
Lot 3       · /besoin — la page                   ← le front, à faire
Lot 4  D9   · need_only par défaut + parqués      ← le renversement
Lot 5       · la moitié ACHETER (heavy)
Lot 6  O4ab · ère + dénomination                  ← après mesure de rejeu
```

---

## Lot 0 · O4c — le filtre pays se désarme au lieu de vider

**Périmètre.** `ml/shared/dino_scope.py` uniquement. Aucun front.

`build_dino_scope` gagne le désarmement par classe et trois champs de
transparence sur `DinoScope` :

```python
country_disarmed: bool      # le filtre s'est retiré, et l'écran doit le dire
n_hidden_by_country: int
n_hidden_by_era: int        # posé à 0 ici, rempli au lot 7
```

Règle, telle qu'elle est déjà écrite pour `class_country` :

```
si pool_filtré == 0 et pool_brut > 0 :
    servir le pool brut
    country_disarmed = True
```

**Vérification.**

- Une classe portugaise (`pt-*`) avec `country_only=True` ne rend plus une liste
  vide mais le pool brut, `country_disarmed=True`.
- **Le compte global se rejoue et rend le même nombre** : 147 des 293 classes
  `review` se désarment, 558 crops redeviennent atteignables.
- **Mutation** : forcer `country_disarmed` à toujours `False` doit faire tomber
  ce compte de 147 à 0 dans le test. Si le test reste vert, il ne teste rien.
- `at-2002-2eur-standard-1st-map` (90 candidats du pays sur 133) **ne se désarme
  pas** — le désarmement ne doit jamais toucher une classe qui a de quoi servir.

**Déploiement.** Aucun (module partagé, consommé en local). Le VPS le prend au
lot 2.

---

## Lot 1 · D8 — `accepted_pending` dans `ClassNeed`

**Périmètre.** `ml/shared/class_need.py` + `ml/tests/test_class_need.py`.

```python
accepted_pending: int   # training_eligible=1, storage_status='present',
                        # face != 'reverse', asset_id absent de
                        # dino_class_references (anchors_kind courant)
```

et `bottleneck_for(have, target, pending_scoped, accepted_pending)` compare
`have + accepted_pending` à `target`.

⛔ **Contrat d'import inchangé : stdlib + `shared.*` seulement.** L'image lean du
VPS doit continuer d'importer ce module sans numpy ni torch. Le test qui vérifie
qu'aucun ordre SQL d'écriture n'apparaît dans le fichier reste vert.

**Vérification.**

- Le compte global se rejoue : **1 451** crops acceptés hors banque, dont **76**
  poseraient un exemplaire, **8** classes deviendraient pleines, **10**
  sortiraient de zéro.
- Une classe à `have=7`, `accepted_pending=1`, `target=8` sort **`pleine`** —
  c'est tout l'intérêt du lot.
- `at-2002-2eur-standard-1st-map` porte `accepted_pending=138` : le test
  verrouille que ce chiffre n'entre dans **aucun** verdict autre que `pleine`.
- Le test existant `test_pleine_a_la_cible_pas_au_plafond` reste vert.

**Déploiement.** Aucun. Pris au lot 2.

---

## Lot 2 · 🚀 `GET /class-need` sur `eurio-api`

**Périmètre.** Une route de lecture, servie par l'image **lean**.

```
GET /class-need?anchors_kind=2eur_all&encoder_version=dinov2-vitl14
  → { build: { build_id, built_at, anchors_kind, encoder_version },
      totals: { n_classes, sum_need, sum_reachable, coverage, cap_at_target },
      parked: { full_class, no_prediction },
      classes: [ ClassNeed + n_hidden_by_country + country_disarmed, … ] }
```

Le bloc `build` n'est pas décoratif : **c'est lui qui rend la page vérifiable.**
Deux lectures d'un même chiffre à deux builds différents ne sont pas un
désaccord, et l'écran doit pouvoir le prouver.

**Vérification.**

- **Le compte à l'écran = le compte en base.** `SELECT COUNT(*)` sur les classes
  à `bottleneck='review'` égale `totals` — c'est la règle qui a coûté le plus
  cher à réapprendre dans ce dépôt.
- La route répond en **hébergé**, sans `:8042` (c'est tout l'enjeu d'O2 §Où elle
  vit) : `curl -b cookie https://eurio-api.musubi.dev/class-need` rend du JSON.
- **Un couple `(anchors_kind, encoder_version)` inexistant rend une erreur
  explicite**, jamais 671 classes en `scrape`. C'est le refus n°2 de
  `class_need.py` : « il ne devine pas `anchors_kind` ».

**Déploiement 🚀.** `git fetch github && git merge --ff-only
github/repo-cleanup` sur `/opt/eurio`, puis `docker compose up -d --build` dans
`infra/eurio-api`. **Témoin** : `curl -s https://eurio-api.musubi.dev/class-need
| jq '.build.build_id'` rend le build courant. Un 404 = l'image n'a pas été
rebâtie ; un JSON vieux = le merge n'a pas eu lieu.

---

## Lot 3 · `/besoin` — la page, en lecture seule

**Périmètre.** `admin/packages/studio-local/src/features/besoin/`, route
`/besoin` **sans** `meta.heavy`, item de nav **sans** `heavy: true`.

Le bandeau (couverture, profondeur, rebuild), l'histogramme, les 671 lignes, les
filtres et le tri de la liste.

**Décision du PO (2026-08-23) : aucune surface spécialisée.** Pas de mode
« session », pas de refonte d'écran pour la pêche, pas d'écran « émission
commune ». Le tri et le choix se font ici ; **trancher se fait dans les pages de
review existantes.**

⛔ **Chaque geste est un lien qui PORTE SON RÉGLAGE.** C'est la seule subtilité
du lot, et elle n'est pas cosmétique :

| ligne | lien |
|---|---|
| `review` | `/review/peche?class=<class_id>&need=1` |
| `review` + « pays désarmé » | `…&need=1&pays=tous` |
| `pleine` | `/review/peche?class=<class_id>&need=0` (voir les parqués) |
| `pleine` réclamée par la voie A | le préflight de cohorte, **jamais** la pêche |
| `scrape` | la moitié ACHETER (lot 5) |

Sans `pays=tous`, une ligne qui annonce « 66 candidats · pays désarmé » ouvre une
file qui en sert **0** : la pêche réapplique son filtre par défaut. C'est
littéralement le « badge qui annonce 4 au-dessus d'une file qui en sert 3 ».

⛔ **Aucun chiffre recalculé côté front.** Le front n'additionne que ce que la
route lui donne. Un total calculé localement finit par diverger du back, et
personne ne sait lequel croire — c'est la leçon de `useCohortFloor.ts`.

**Vérification.**

- **Le scénario du terrain d'essai**, rejoué : `be-2015-…year-for-development`
  (7/8, +2 acquis, 72 candidats) remonte haut ; `ad-2014-…council-of-europe`
  se range en `pleine` avec ses 257 parqués ; `lu-2002-…henri-i` affiche
  « 66 · pays désarmé ».
- **Le zéro qui s'explique** : `va-2019-…sede-vacante` affiche `0 · rien
  scrapé`, jamais une case vide.
- **En hébergé** (`VITE_DEPLOY_TARGET=hosted`) la page s'affiche entièrement,
  gestes grisés. C'est le test qui prouve qu'on n'a pas glissé un appel `:8042`.
- Les trois états dégradés se voient : chargement (structure stable), banque
  inconnue, erreur du canonique.
- **Le lien tient sa promesse** : cliquer le geste d'une ligne « pays désarmé »
  ouvre une file **non vide**, et son compte égale celui de la ligne. C'est le
  test qui rattrape l'oubli de `pays=tous`.

**Déploiement 🚀.** Rebuild `infra/eurio-admin`.

---

## Lot 4 · D9 — `need_only` par défaut, et les parqués visibles

**Périmètre.** Le renversement du défaut, front + API.

- `queryNeedOnly()` : le filtre est **actif** sauf `?need=0`.
- `PechePage.vue` le passe (il ne l'émet pas du tout aujourd'hui).
- `RunParked` est exposé **globalement et par classe**, pas seulement par run.
- Chaque file affiche son compte parqué, en deux causes (`full_class`,
  `no_prediction`), et le lien pour lever.

⚠️ **Renverser un défaut est une écriture de comportement.** Le bandeau doit
dire, une fois, en toutes lettres : *« la file ne sert que le besoin — N crops
parqués »*. Un défaut qui tait son effet ment par omission (D9 de `peche-dino`).

**Vérification.**

- La file par défaut ne sert plus aucun crop de classe pleine :
  `4 804 / 6 574 = 73 %` disparaissent, et le bandeau annonce exactement 4 804.
- `?need=0` les ramène tous, et le dit.
- **Le compteur au-dessus de la file compte ce que la file sert** — pas
  « 0 / 777 » au-dessus d'une file de 500. C'est le piège que `useQueryScope`
  documente déjà.
- Le scénario du PO du 2026-08-21 ne se reproduit pas :
  `/review/manual?run=…` ne ressert plus `at-2euro-standard-t1`.

---

## Lot 5 · La moitié ACHETER

**Périmètre.** Le bloc scrape, `meta: { heavy: true }` (il lit `api_call_log`
dans `eurio.local.db`).

Besoin par pays, coût estimé au rendement mesuré (6,6 annonces/exemplaire),
quota restant, et un lien vers un plan **pré-rempli** de l'allocateur.

⚠️ **Les deux réserves de FLOW-ADMIN §Station 1 sont portées à l'écran, pas
tues** : le préflight quota de `sources/cli.py` est faux d'un facteur ~130 (il
compte sur `source_runs.n_calls`), et le budget vrai est dans
`eurio.local.db`, pas au canonique.

**Vérification.**

- Le compte par pays se rejoue : LU 37, SM 28, VA 27, MT 26, PT 26, GR 22.
- Les 274 classes jamais visées sont comptées comme telles (jointure sur
  `source_images.target_eurio_id`), pas confondues avec les 14 qui l'ont été
  sans résultat.
- En hébergé, le bloc est grisé et `LocalOnlyNotice` s'affiche à sa place.
- **Aucun lancement au fil d'une lecture.** Le lien ouvre un plan ; le plan a
  son propre bouton.

---

## Lot 6 · O4a/b — l'ère et la dénomination

**Périmètre.** `build_dino_scope(era_only=True, min_denom=None)` et
`n_hidden_by_era` / `n_hidden_by_denom` remontés jusqu'à la ligne.

Livré **après** les autres parce qu'il ne débloque rien du palier 1 : son gain
mesuré est la propreté des lots, pas la couverture.

⛔ **La sémantique d'intervalle n'est pas un détail d'implémentation.**
`Y[0] <= era[1] AND era[0] <= Y[-1]`, jamais une énumération.

**Vérification.**

- Les quatre régimes d'O4a se rejouent et rendent les mêmes nombres
  (lots/courantes 45 · 95,6 %, singles/commémos 1234 · 99,1 %).
- **Le lot belge « 14 Stück (1999–2012) » disparaît** de la file
  `be-2014-2eur-standard-philippe`, et l'ordre ne le remet pas en tête —
  l'ordre des lots doit compter les candidats **survivant aux filtres**.
- **Mutation** : forcer l'énumération au lieu de l'intervalle doit faire chuter
  le rappel commémos-lots de 85,4 % à 74,2 %. Si le test reste vert, il ne teste
  pas ce qu'on croit.
- Le script de mesure **déménage du scratchpad vers `ml/scripts/`** — il n'est
  pas rejouable là où il est.

---

## Ce qui reste dehors

| sujet | où c'est traité |
|---|---|
| la courbe « 1 exemplaire partout » (bloque D7) | [`QUESTIONS-OUVERTES.md`](QUESTIONS-OUVERTES.md) Q1 |
| la review hébergée (URLs MinIO) | Q3 — chantier séparé |
| une surface « session » qui enchaîne les classes | **écartée par le PO le 2026-08-23** — le tri de `/besoin` suffit, la review a ses pages |
| le thème sombre | Q5 — passe par R2, pas par cette page |
| O3, l'entonnoir à huit plaques | après ces lots ; il consomme `/class-need` |
| la qualité des requêtes eBay | Q8 — c'est l'allocateur et O3, pas `/besoin` |
