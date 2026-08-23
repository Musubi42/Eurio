# Reprendre ici — `/besoin`, état au 2026-08-23

> **Point d'entrée de la prochaine session.** Lis ce fichier en premier, puis
> [`DECISIONS.md`](DECISIONS.md). Le reste ne sert qu'au moment où tu en as besoin.
>
> Tout le code est **écrit, testé et commité**. Rien n'a été vu à l'écran pour
> les deux derniers lots. **La suite commence par un déploiement et une
> vérification, pas par du code.**

---

## En une phrase

On voulait 8 exemplaires propres par classe dans la banque DINO, avec le moins
de temps humain et de quota eBay possible. On a maintenant un écran qui dit
**quelle classe nourrir, par quel geste, et quand s'arrêter** — et une file qui
ne sert plus que ça.

---

## L'état, mesuré (instantané figé, à rejouer)

Banque `a55e6594da3247ec80bc609f93342f51`, `built_at 2026-08-22 18:06:23`,
1909 ancres. **Ces nombres bougent** : la banque a été rebâtie deux fois pendant
la seule journée du 22. Rejoue, ne recopie pas.

```bash
cd ml && ./.venv/bin/python -c "
import sqlite3, collections, sys; sys.path.insert(0,'.')
from shared.class_need import all_needs
c = sqlite3.connect('file:state/eurio.replica.db?mode=ro', uri=True); c.row_factory = sqlite3.Row
n = all_needs(c, anchors_kind='2eur_all', encoder_version='dinov2-vitl14')
print(len(n), dict(collections.Counter(x.bottleneck for x in n)), sum(x.need for x in n))
print('scoped', sum(x.pending_scoped for x in n), '/ brut', sum(x.pending for x in n))"
# 671 {'pleine': 109, 'review': 213, 'scrape': 349} 4066
# scoped 3150 / brut 6371
```

| | |
|---|---:|
| couverture (palier 1, `have ≥ 1`) | **250 / 671** |
| Σ `need` (palier 2) | 4 066 |
| file ouverte | 6 371 crops |
| — parqués (classes à leur cible) | **5 041** |
| — écartés par l'ère · par le pays | 1 985 · 1 236 |
| — **servis** (`pending_scoped`) | **3 150** |
| exemplaires à portée de la file | **557** |
| acquis, pas encore bâtis | 1 610 → un rebuild en poserait **184** |
| classes à zéro avec un candidat servable | **92** (dont 30 à marge ≥ 0,10) |
| classes à scraper | 349, dont **323 jamais visées** |
| pays du manque | LU 44 · SM 35 · PT 31 · MT 29 · VA 29 · GR 26 · FI 22 · SK 17 |

---

## Ce qui est en production, et ce qui ne l'est pas

| | état | vérifié à l'écran |
|---|---|---|
| Lot 0 · O4c désarmement pays | ✅ déployé | oui |
| Lot 1 · D8 `accepted_pending` | ✅ déployé | oui |
| Lot 2 · `GET /class-need` | ✅ déployé | oui |
| Lot 3 · la page `/besoin` | ✅ déployé | oui |
| Lot 4 · D9 besoin par défaut | ✅ déployé | oui |
| **Lot 5 · moitié ACHETER** | ⛔ **commité, PAS déployé** | **non** |
| **Lot 6 · ère + dénomination** | ⛔ **commité, PAS déployé** | **non** |
| **Correctifs de revue** | ⛔ **commité, PAS déployé** | **non** |

Commits : `643d6487` → `64409be8`. Suite **2089 verts**, typecheck et build verts.

---

## 🔴 PAR OÙ COMMENCER — dans cet ordre

### 1. Déployer, et prévenir avant

Le déploiement est **couplé** (backend d'abord), et il **change ce que la file
sert**. À annoncer au PO avant, pas après :

```
Σ « à portée »   840  →  557 exemplaires
review 262 → 213 · scrape 300 → 349   (49 classes basculent)
```

Ce n'est **pas** une régression : les 49 classes qui basculent ne pèsent que
100 crops, tous contredits par l'ère. Exemple : `lu-2016-…charlotte-bridge`,
20 candidats, les 20 écartés — des annonces dont le titre couvre des années où
la pièce n'existait pas. Le « 840 » d'avant était surévalué de 27 %.

⚠️ **`docker compose up -d --build` sur `eurio-api` redémarre le writer
canonique.** Demander au PO s'il tranche avant de lancer.

```bash
git push github repo-cleanup
ssh serverOimNixDontpanic
cd /opt/eurio && git fetch github repo-cleanup && git merge --ff-only github/repo-cleanup
cd infra/eurio-api  && sops exec-env ../../secrets/dev.env "docker compose up -d --build"
cd ../eurio-admin   && sops exec-env ../../secrets/dev.env "docker compose up -d --build"
```

⛔ **Le clone du VPS suit toujours `codeberg`.** Un `git pull` nu y répond « à
jour » en toute bonne foi. Passer par `fetch github` + `merge --ff-only`.
Skill : `eurio-vps-deploy`.

Vérifier **dans cet ordre** (les logs, PUIS l'OpenAPI qui fait autorité, PUIS
un appel avec un vrai PAT) :

```bash
docker logs eurio-api 2>&1 | grep -E "routers (montés|skippés)" | tail -2
# attendus et SEULS attendus : referential (PIL), review_queue (cv2)
curl -s https://eurio-api.musubi.dev/openapi.json | tr ',' '\n' | grep -oE '"/class-need"'
sops exec-env secrets/dev.env 'curl -s -H "Authorization: Bearer $EURIO_API_TOKEN" \
  "https://eurio-api.musubi.dev/class-need" | head -c 400'
```

⚠️ **`/scrape-plan/*` n'est PAS sur l'image lean** — elle lit
`ml/state/eurio.local.db`, qui n'existe pas sur le VPS. C'est délibéré et
verrouillé par un test. La moitié ACHETER se grise en hébergé.

### 2. Vérifier à l'écran — rien ne l'a été pour les lots 5 et 6

`vue-tsc` et `vite build` valident les templates. **Ce n'est pas la même chose
que d'avoir regardé.** Il faut :

- lancer l'API ML locale (`go-task ml:api`) — la moitié ACHETER en dépend, et
  la pêche n'affichera `country_disarmed` qu'après ce redémarrage ;
- ouvrir `/besoin` et vérifier que la moitié ACHETER affiche des groupes, un
  coût et un quota, pas une erreur ;
- ouvrir une ligne « écarté par l'ère » et vérifier que la pêche sert bien ce
  que la ligne annonce ;
- ouvrir une **cohorte** (`/review/manual?cohort=…`) et vérifier qu'elle sert
  la file COMPLÈTE (cf. le défaut n°1 ci-dessous).

### 3. Les trois gestes qui font avancer l'objectif

1. **Trancher les 30 classes à marge ≥ 0,10.** Une soirée. C'est le seul moyen
   de savoir ce que vaut vraiment le palier 1 : sur les 92 classes « à portée »,
   beaucoup ont des files dont le modèle n'est net sur aucun candidat.
2. **Un rebuild.** 1 610 crops acquis attendent, 184 poseraient un exemplaire.
   Tant qu'il n'a pas lieu, `have` ne bouge pas.
3. **Scraper les 323 jamais visées.** ~1 800 annonces pour sortir 323 classes de
   zéro : le meilleur rapport du chantier. C'est ce que la moitié ACHETER
   prépare.

---

## Ce qui reste à faire, par ordre de valeur

### Défauts connus, non corrigés

| | quoi | où |
|---|---|---|
| 🟠 | **La pêche est muette sur l'ère**, qui retire pourtant 1 985 crops. Le back le calcule (`DinoScope.n_hidden_by_era`), `DinoCandidatesSummary` ne le porte pas. C'est « un filtre par défaut qui tait son effet » — le défaut que ce chantier combat. | `serving/review_queue/{models,repository}.py`, `PecheBar.vue` |
| 🟠 | **La pêche affiche « classe pleine 2/8 »** sur 17 classes : le résumé ne porte pas `accepted_pending`, donc l'écran se contredit dans la même phrase. | idem |
| 🟠 | **Les parqués sont invisibles sur `/review/manual` sans périmètre.** 79 % des crops sont retirés et rien ne le dit ; `RunProgressLine` n'est monté que si `?run=`. D3 exige que le compte s'affiche. | `ReviewPage.vue` |
| 🟠 | **« rien scrapé — jamais interrogé » est faux 25 fois** : la ligne l'affirme dès `pending == 0`, alors que 25 de ces classes ont déjà été visées. Le back sait faire la différence (`n_never_targeted` / `n_targeted_no_result`), la ligne non. | `BesoinTable.vue` |
| 🟠 | **Les mentions de masquage ne sont pas des liens.** O2 propriété 3 et DESIGN §4.3 exigent « le lien qui les ramène » ; ce sont des `<span title=…>`. | `BesoinTable.vue` |
| 🟡 | **La porte dénomination n'a aucun appelant.** Le paramètre traverse ~15 signatures et 8 endpoints ; aucun front ne l'arme, donc `n_hidden_by_denom` vaut structurellement 0. Soit on câble un bouton, soit on retire le paramètre (le prédicat et sa mesure restent utiles dans `scripts/measure_o4_filters.py`). **Décision à prendre.** | partout |
| 🟡 | **`/besoin` lit deux bases et n'en nomme qu'une.** TRANCHER lit le canonique, ACHETER lit la réplique via `:8042`. Si la réplique retarde, les deux moitiés chiffrent deux catalogues et rien ne le signale. Correctif : comparer les deux `build_id` et le dire. | `BesoinAcheter.vue` |
| 🟡 | **`BuildInfo` est dupliqué** — deux modèles identiques (`class_need_routes`, `scrape_plan_routes`) et deux types front. À factoriser. | — |
| 🟡 | Vocabulaire : « écarté » et « masqué » désignent le même concept. DESIGN §5 n'en veut qu'un. | `BesoinTable.vue` |
| 🟡 | `dino_candidates_summary` calcule deux fois « cette classe est-elle pleine » (`need_filter_clause` à 562 paramètres, puis `need_for`). **Équivalent au rang 1 seulement** — ne pas simplifier sèchement. | `repository.py` |
| 🟡 | Code mort prouvé : prop `rows` de `BesoinBandeau`, `DinoScope.rank`, `class_need.BOTTLENECKS`, `_suggestions_join()`, 4 champs de réponse jamais rendus dans `/scrape-plan`. | — |
| 🟡 | Bornes `ge/le` manquantes sur `dino_min_denom` dans le jumeau lourd ; indentation cassée à `repository.py:1678`. | — |

### Questions ouvertes qui décident de la suite

Détail dans [`design/QUESTIONS-OUVERTES.md`](design/QUESTIONS-OUVERTES.md).

- **Q1 — la courbe « 1 exemplaire partout »** (bloque D7). Le `N` de
  `bench_refs_curve` est plafonné par ce que chaque classe possède : « +10,8 pts
  entre N=0 et N=1 » ne dit pas encore « donner 1 exemplaire aux 421 classes
  vides vaut plus qu'amener 90 classes de 5 à 8 ». **À demander à la session ML.**
- **Q3 — la review hébergée.** Elle est `heavy` pour deux raisons seulement : la
  résolution des URLs d'images et l'édition de lots (cv2). Les décisions partent
  déjà au canonique, et les crops vivent dans MinIO public. Trancher 338 crops
  dans le train est à portée.
- **Q8 — la qualité des requêtes eBay.** Savoir *quelles* requêtes rendent des
  crops est le prérequis d'une meilleure requête. C'est de l'entonnoir O3.

### Ce qui n'a jamais été fait

- **O3 — l'entonnoir à huit plaques**, lisible par run ET par classe. Il consomme
  `/class-need`, donc il est débloqué. Spec : [`outils/O3`](outils/O3-entonnoir-huit-plaques.md).

---

## Les pièges de ce dépôt, appris à leurs dépens

Ils ont tous coûté quelque chose pendant cette session.

1. **`pytest` sort en code 0 sur un argument inconnu**, et un `| tail` masque le
   code de sortie. Rediriger vers un fichier, lire `echo $?`. Une suite qui
   n'avait pas tourné a failli passer pour verte.
2. **Le défaut V4 s'est présenté QUATRE fois** : `class_id` désigne trois
   conventions (`coins` = `COALESCE(design_group_id, eurio_id)`, banque =
   `eurio_id` du représentant, gold = encore autre chose). Passer l'un pour
   l'autre rend `None` ou zéro ligne **sans lever**. Réflexe : devant une
   requête qui compare un `class_id`, demander *lequel*.
3. **La banque bouge sous la mesure.** Deux rebuilds le 22, la réplique se
   resynchronise en continu. Toute mesure comparative se fait sur un
   **instantané figé** (`cp` de la réplique), sinon on attribue à son code ce
   qui vient d'un pull.
4. **Un test vert ne prouve rien tant qu'il n'a pas échoué.** Toutes les
   fonctionnalités de ce chantier ont leur mutation jouée. Trois trous ont été
   trouvés ainsi — le code était juste, rien ne le tenait.
5. **Les trois revues ont trouvé six défauts que les tests verts n'ont pas vus**,
   dont trois écrits par l'auteur principal. La revue croisée n'est pas un luxe
   ici.
6. **Ne pas éditer l'arbre pendant qu'un agent y joue ses mutations** — un
   fichier lu au mauvais moment fait « corriger » un bug qui n'existe pas.

---

## Le motif à surveiller

Les trois revues ont convergé, sous trois angles différents, sur **la même
faute** : *un filtre par défaut qui ne dit pas son effet.*

C'est exactement ce que le chantier existe pour éliminer — et il l'a reproduit
chez lui trois fois : le lien qui éteignait l'avertissement du désarmement, la
banque illisible qui vidait la file en silence, l'ère qui retire 1 985 crops
sans que la pêche en dise un mot.

**Quand tu ajoutes un filtre ici, la question n'est pas « est-ce qu'il
marche » — c'est « qu'est-ce que l'écran dit quand il mord ».**
