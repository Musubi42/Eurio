# Giga-cohorte 50 — plan de travail

> Objectif : un entraînement sur **les 50 pièces qui comptent** — les plus
> frappées d'Europe et celles de la collection — puis un vrai test sur
> téléphone. Ce fichier suit l'avancement ; on le coche au fur et à mesure.
>
> Établi le **2026-08-18** sur mesures. Tout chiffre ici porte sa source.

## Ce que ça change pour l'app

| | Aujourd'hui | Après |
|---|---:|---:|
| Pièces reconnues | **20** | **50** |
| Pièces perdues au passage | — | **0** |

L'arbre français et le Juan Carlos 2ᵉ type — que l'app reconnaît aujourd'hui et
qu'une promotion mal composée lui ferait oublier — sont dans la cohorte.

---

## Correction : le tirage EXISTE en base

Une première analyse a conclu « le tirage n'est renseigné nulle part ». **C'est
faux**, et l'erreur venait d'avoir interrogé la mauvaise table.

| Où | État |
|---|---|
| `coins.mintage` | colonne dénormalisée, **vide** (0/689) — n'y touchez pas |
| `mint_release_observations` (`fact_type='mintage'`) | ✅ **3 246 observations**, sourcées `numista_api`, par atelier et par année |

La bonne requête, à réutiliser :

```sql
select coalesce(cn.design_group_id, cn.eurio_id) classe,
       sum(cast(o.value_json as integer)) tirage
  from mint_release_observations o
  join coin_mint_releases r on r.id = o.mint_release_id
  join coins cn on cn.eurio_id = r.parent_type_id
 where o.fact_type = 'mintage' and cn.face_value = 2.0
   and r.issue_type = 'CIRC'          -- ⚠️ sinon on additionne les coffrets BU/PROOF
 group by 1 order by tirage desc;
```

⚠️ `issue_type` vaut `CIRC` (929), `PROOF` (1014), `BU` (874), `COIN_CARD` (220),
`OTHER` (271). **Seul `CIRC` circule.** Sans ce filtre, une pièce de coffret
remonte au niveau d'une pièce de poche.

Résultat : **392 classes de 2 €** ont un tirage de circulation connu. Le top :
Allemagne 2 149 M · Italie 835 M · France 661 M · Espagne 499 M · Autriche 461 M.

---

## La cohorte — 50 classes, 144 pièces

25 choisies **par tirage** (les plus frappées), 25 **de la collection**, sans
doublon. `●` = au moins une pièce vous appartient.

### A. Prêtes — rien à faire (29)

| Classe | Tirage | Photos OK | En attente | À valider | Collec |
|---|---:|---:|---:|---:|:---:|
| `de-2euro-standard-t1` | 2149 M | 13 | 90 | — | ● |
| `es-2euro-juan-carlos-i-t1` | 499 M | 13 | 56 | — | ● |
| `at-2euro-standard-t1` | 461 M | 75 | 260 | — | ● |
| `be-2euro-albert-ii-t1` | 325 M | 10 | 16 | — | ● |
| `eu-euro-cash-2012` | 89 M | 62 | 155 | — | ● |
| `eu-rome-2007` | 84 M | 30 | 79 | — |  |
| `eu-emu-2009` | 74 M | 49 | 205 | — | ● |
| `be-2euro-albert-ii-t2` | 72 M | 16 | 20 | — | ● |
| `eu-eu-flag-2015` | 50 M | 15 | 71 | — | ● |
| `eu-erasmus-2022` | 35 M | 13 | 52 | — |  |
| `at-2005-2eur-50th-anniversary-of-the-austrian-state-treaty` | — | 106 | 183 | — | ● |
| `fr-2008-2eur-french-presidency-of-the-council-of-the-european-union` | 20 M | 48 | 78 | — | ● |
| `it-2016-2eur-2200th-anniversary-of-the-death-of-plautus` | 2 M | 47 | 93 | — | ● |
| `be-2011-2eur-100th-international-womens-day` | 5 M | 40 | 76 | — | ● |
| `es-2016-2eur-old-town-of-segovia-and-its-aqueduct` | 3 M | 35 | 77 | — | ● |
| `de-2007-2eur-state-of-mecklenburg-vorpommern` | 30 M | 34 | 60 | — | ● |
| `de-2020-2eur-brandenburg-the-bundeslander-series` | 30 M | 33 | 95 | — | ● |
| `fr-2016-2eur-100th-anniversary-of-the-birth-of-francois-mitterrand` | 10 M | 31 | 30 | — | ● |
| `it-2016-2eur-550th-anniversary-of-the-death-of-donatello` | 2 M | 29 | 26 | — | ● |
| `fi-2017-2eur-100-years-of-independence` | 2 M | 27 | 28 | — | ● |
| `fi-2016-2eur-100th-anniversary-of-the-birth-of-georg-henrik-von-wright` | 1 M | 26 | 87 | — | ● |
| `at-2018-2eur-100-years-republic-of-austria` | 13 M | 26 | 79 | — | ● |
| `fr-2016-2eur-euro-2016-football-championship` | 10 M | 25 | 35 | — | ● |
| `at-2016-2eur-200th-anniversary-of-the-national-bank` | 16 M | 25 | 79 | — | ● |
| `es-2euro-felipe-vi-t1` | 19 M | 24 | 38 | — | ● |
| `ad-2euro-standard-t1` | 13 M | 19 | 60 | — | ● |
| `de-2020-2eur-german-polish-reconciliation` | 30 M | 17 | 50 | — | ● |
| `fr-2018-2eur-simone-veil` | 15 M | 16 | 11 | — | ● |
| `fi-2016-2eur-90th-anniversary-of-the-death-of-the-writer-eino-leino` | 1 M | 16 | 38 | — | ● |

### B. Débloquées par le tri seul (11) — 71 photos

| Classe | Tirage | Photos OK | En attente | À valider | Collec |
|---|---:|---:|---:|---:|:---:|
| `fi-2012-2eur-150th-birthday-of-helene-schjerfbeck` | 2 M | 9 | 38 | 1 | ● |
| `fr-2euro-standard-t1` | 661 M | 5 | 66 | 5 |  |
| `fr-2018-2eur-100th-anniversary-of-the-end-of-the-first-world-war-bleuet-de-france` | 15 M | 5 | 23 | 5 | ● |
| `cy-2euro-standard-t1` | 51 M | 4 | 144 | 6 | ● |
| `be-2euro-philippe-t1` | 3 M | 4 | 97 | 6 | ● |
| `es-2euro-juan-carlos-i-t2` | 20 M | 4 | 16 | 6 | ● |
| `fr-2010-2eur-degaulles-radio-speech-on-june-18th-1940-70th-anniversary-of-the-appeal-of-june-18` | 20 M | 3 | 85 | 7 | ● |
| `be-2012-2eur-75th-anniversary-of-queen-elisabeth-music-competition` | 5 M | 3 | 22 | 7 | ● |
| `it-2euro-standard-t1` | 835 M | 2 | 54 | 8 | ● |
| `de-2009-2eur-federal-state-of-saarland` | 31 M | 0 | 84 | 10 |  |
| `de-2006-2eur-state-of-schleswig-holstein` | 30 M | 0 | 35 | 10 | ● |

### C. À scraper (10)

| Classe | Tirage | Photos OK | En attente | Manquantes | Collec |
|---|---:|---:|---:|---:|:---:|
| `nl-2euro-beatrix-t1` | 215 M | 1 | 0 | 9 | ● |
| `ie-2euro-standard-t1` | 158 M | 1 | 0 | 9 | ● |
| `gr-2euro-standard-t1` | 116 M | 1 | 0 | 9 | ● |
| `fi-2euro-standard-t1` | 90 M | 1 | 0 | 9 | ● |
| `hr-2euro-standard-t1` | 80 M | 0 | 0 | 10 |  |
| `lu-2euro-henri-i-t1` | 79 M | 1 | 0 | 9 |  |
| `sk-2euro-standard-t1` | 76 M | 1 | 0 | 9 | ● |
| `pt-2euro-standard-t1` | 71 M | 1 | 0 | 9 |  |
| `lt-2euro-standard-t1` | 50 M | 0 | 0 | 10 |  |
| `it-2006-2eur-xx-olympic-winter-games-turin-2006` | 40 M | 0 | 2 | 8 |  |

---

## Le plan, en deux vagues

Le système **refuse de lancer un entraînement si une seule classe est sous le
plancher** de 10 photos réelles. Les 10 pièces à scraper sont donc sur le chemin
critique — d'où le découpage.

### 🌊 Vague 1 — 40 classes, sans scraper une image

**Cohorte créée le 2026-08-18 : `888cbc5d3a9e` — `giga-40-vague1`**, 129 pièces,
40 classes, en `draft` (rien n'est figé). Vérifiée au canonique.

Son écran de préparation dit aujourd'hui : `ready=False · block=2 · warn=9`.
Les **11** classes du bloc B sont donc bien les seules à débloquer — dont deux
en refus **dur** (`de-2006-schleswig-holstein`, `de-2009-saarland` : moins de 4
sources au total, pas seulement moins de 10 photos eBay). Même geste pour les
corriger : valider des photos.

Suivre l'avancement :
```
http://localhost:5173/lab/cohorts/888cbc5d3a9e
```

- [x] Créer la cohorte `giga-40-vague1` en `draft`
- [ ] **Trier 71 photos** (bloc B ci-dessus). Elles sont **déjà en base**, il n'y
      a rien à aller chercher.
- [ ] Vérifier l'écran de préparation : tout doit être vert **avant** de créer
      l'itération — la création **gèle** la cohorte, c'est irréversible
- [ ] Lancer bake + entraînement **sur le PC**
- [ ] Lire le benchmark automatique (il tourne seul en fin d'entraînement)

C'est déjà **le double** de ce que l'app reconnaît aujourd'hui.

### 🌊 Vague 2 — les 10 pièces manquantes

- [ ] Scraper 10 pays : **FI, GR, HR, IE, IT, LT, LU, NL, PT, SK**
- [ ] Trier ce que ça ramène
- [ ] Recomposer la cohorte à 50 et ré-entraîner

**Coût honnête** : la découverte se fait **par pays entier**, pas par pièce.
Comptez ~30 min par pays (≈ 5 h), qui ramèneront **2 000 à 2 500 photos** à
trier, dont vous garderez environ **1 sur 4** (mesuré : 61 % de rejets en juin,
75 % en juillet). Ce n'est pas un après-midi.

---

## Les pièges à ne pas retomber dedans

Chacun a déjà coûté du temps au projet.

### Scraping
- ⛔ **`go-task ml:scrape-ebay` est morte** (elle échoue maintenant en le disant).
  La bonne porte est **`go-task ml:src:ebay:run`**.
- ⛔ **Ne jamais lancer `python -m sources.cli` en direct** : ça perd
  `EURIO_CENSUS_RECOVER=1`, que seule la tâche pose. Sans lui, une grosse part
  des pièces bimétal repart en « zéro crop », **en silence**.
- La découverte est **par pays**, jamais par pièce. Cibler une pièce néerlandaise
  ramène tout le 2 € néerlandais.
- Le compteur d'appels du run **ment** (il affiche 3 pour 740 appels réels). Le
  vrai chiffre est dans `eurio.local.db`, table `api_call_log`.

### Tri (review)
- ⛔ **Ne fabriquez pas d'outil de tri parallèle** : le front le fait, et lui
  seul applique la bonne règle **et** écrit.
- ⚠️ Sur les pièces **standard**, la machine n'affiche **aucun score** — banque
  d'ancres incomplète. Vous triez à l'œil, et c'est normal.
- ⚠️ Laissez la face sur **avers**. Un crop passé en « revers » est accepté puis
  **écarté de l'entraînement en silence**.
- ⚠️ Si le réseau lâche, **l'écran affiche un succès et n'écrit rien**. Après
  chaque session, vérifiez que `n_done_today` a bougé.

### Entraînement
- L'entraînement tire aussi des pièces **hors cohorte** (les sœurs de même
  design). Sur 27 pièces, le dernier run en a bakées **61**. C'est voulu.
- Créer une itération **gèle** la cohorte. Pour changer d'avis : **cloner**.
- Sur le PC, lancer l'API **avec les secrets** (`sops exec-env`), sinon
  l'itération est créée, renvoie 200, et **n'atteint jamais** le serveur.

### Mise en production
- ⚠️ La promotion **remplace**, elle n'accumule pas. Lire `reference` **avant**
  `absent_in_promotion` dans le rapport.
- ⚠️ `--no-supabase` est **obligatoire** aujourd'hui : les deux tables cibles
  n'existent pas côté Supabase.

---

## Après l'entraînement — le test téléphone

- [ ] Promouvoir en local (`--no-supabase`) et vérifier ce que l'app gagne/perd
- [ ] Copier les artefacts vers l'APK, publier, reconstruire
- [ ] Scanner chaque pièce ~10 fois en lumières variées
- [ ] Comparer au benchmark automatique

**Déjà outillé** : le jeu d'évaluation contient vos captures en **6 conditions**
(plein jour, forte, faible, fond texturé, gros plan, incliné) — nettoyé le
2026-08-18, il porte **19 pièces / 114 photos** sans doublon. Et la chaîne
`android:bench:pull` → `annotate` → `replay` → `compare` existe pour mesurer de
vraies sessions de scan.

**À traiter plus tard, pas maintenant** : le rangement de la donnée a des
reliquats (tables prévues puis abandonnées, colonnes jamais alimentées, noms qui
se ressemblent). Le flux, lui, fonctionne. Inventaire mesuré :
[`docs/architecture/dette-de-stockage.md`](../../architecture/dette-de-stockage.md).
Rien là-dedans ne bloque cette cohorte.

**Jamais fait** : mettre un modèle entraîné dans l'APK de bout en bout. La chaîne
existe, elle a été exercée à mi-parcours une fois. C'est une première — à faire
ensemble.
