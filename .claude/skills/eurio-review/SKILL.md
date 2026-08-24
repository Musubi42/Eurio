---
name: eurio-review
description: Trancher les crops scrapés et décider ce qui entre en training (training_eligible). À lire avant d'accepter des crops, de bricoler une planche de contrôle, ou de lire `image_asset_dino_predictions` à la main.
---

# Trancher les crops

> La review est le seul endroit du projet où une **décision humaine** entre dans
> la donnée. Ce qu'elle produit — `training_eligible = 1` — n'est régénérable par
> aucun calcul : c'est la vérité-terrain de l'entraînement. Une erreur ici ne
> plante rien, elle dégrade le modèle des mois plus tard.

## La review se fait DANS le front de review

`go-task front:dev` → `http://localhost:5173/review`. Les pages existent déjà et
sont marquées `meta.heavy` (donc locales, cf. `CLAUDE.md` §R0bis) :

| Page | Ce qu'elle fait |
|---|---|
| `/review` | tableau de bord, stats de triage |
| `/review/manual` | trancher un crop à la fois |
| `/review/auto-accept` | valider en lot ce que le moteur juge sûr |
| `/review/lot/:listing_key` | annonces multi-pièces (kind `lot`) |
| `/review/recover` | rattraper des crops écartés |
| `/review/peer-arbitration` | désaccords entre décisions |

Les cinq premières sont `meta.heavy` (donc locales). **`peer-arbitration` ne l'est
pas, volontairement** — « GET arbitrage léger + URLs images ML », accessible en
hébergé (`router.ts`).

### Les paramètres d'URL — sans eux la page ne sert à rien

C'est la moitié du travail d'orientation, et c'est le seul endroit où elle est
écrite. Le front écoute sur `[::1]:5173` : `localhost` répond, `127.0.0.1` non.

| But | URL |
|---|---|
| **Lots d'une classe** (le vrai gisement) | `/review/manual?mode=lot&design_group=<design_group_id>` |
| Une annonce précise | `/review/lot/<listing_key urlencodé>` |
| Singles d'une pièce | `/review/manual?eurio_id=<eurio_id d'un MEMBRE>` |

⛔ **`?eurio_id=` n'accepte pas un `design_group_id`.** Passer
`fr-2euro-standard-t1` renvoie **0 item, sans erreur** — la requête tombe dans la
branche `s.target_eurio_id = ?`. Il faut l'`eurio_id` d'un membre.

⛔ **Et pour une pièce non commémorative, `?eurio_id=` n'est pas un filtre de
classe.** `repository.py::list_queue` élargit à tout le pool ambigu du pays
(`source='ebay' AND listing_country=? AND listing_year IS NULL`). Mesuré sur
`fr-1999-2eur-standard-1st-map` : **98 items affichés, ~8 utiles**. Le reste
cible des commémoratives françaises ou une **autre** classe standard (t2). Sur
une classe standard, passe par les lots.

`?design_group=` n'existe **que** côté lot (`LotReviewView.vue`). Côté single,
il n'y a pas d'équivalent — c'est un manque connu, pas une erreur d'usage.

⛔ **Ne fabrique pas d'outil de review parallèle.** Vécu le 2026-08-17 : une
planche HTML de 111 vignettes a été produite pour faire trancher un humain, alors
que le front existait — et elle affichait 24 candidats espagnols dont **2** bons,
parce qu'elle interrogeait la table brute au lieu du verdict du projet. Le front,
lui, applique la bonne règle, et son bouton **écrit**.

*(Incident consigné, pas règle cardinale : une épreuve de contrôle du 2026-08-17
a montré qu'un agent sans cette skill trouve le front seul et renonce de lui-même
à la planche. Ce qui suit — les paramètres d'URL et la cécité du verdict sur les
standards — est ce que cette skill apporte réellement.)*

## Le verdict, et pourquoi la marge compte plus que le seuil

`serving/review_queue/service.py::compute_auto_validate_verdict` classe chaque
crop en `auto_candidate` / `partial` / `divergent` / `unknown`, **dans cet ordre** :

1. aucune prédiction DINO → `unknown`
2. signal **texte** `contradict` → `divergent`
3. cible de découverte absente → `unknown`
4. **`top1 != target` → `divergent`** ← la règle qui tranche le plus souvent
5. sim ≥ seuil **ET** marge ≥ seuil **ET** texte `convergent` → `auto_candidate`
6. sinon → `partial`

Donc le verdict **ne se joue pas que sur les scores** : un crop qui passe les deux
seuils reste `partial` si le signal texte n'est pas `convergent`, et bascule
`divergent` si le top1 contredit la cible de découverte.

Seuils canoniques — ⚠️ **depuis le 2026-08-19 ils ne sont plus « dans le
code »** : ils vivent en base (`dino_thresholds`), scopés par couple
`(banque, encodeur)`, avec des défauts stdlib dans
`shared/dino_threshold_defaults.py` et une résolution par
`store/dino_thresholds.py`. `training/foundation/thresholds.py` ne porte plus
que les valeurs historiques du verdict. Ne lis pas un seuil dans un fichier —
résous-le, et regarde d'où il vient :

```bash
cd ml && ./.venv/bin/python -c "
import sqlite3, store.dino_thresholds as dt
c = sqlite3.connect('file:state/eurio.replica.db?mode=ro', uri=True)
r = dt.resolve(c, anchors_kind='2eur_all', encoder_version='dinov2-vitl14')
print(r.values); print(r.source)"
# {'top1_country_sim_min': 0.55, 'country_spread_min': 0.05, 'spread_uncertain_max': 0.02,
#  'spread_confident_min': 0.05, 'spread_auto_accept_min': 0.1, 'min_exemplars': 1}
#                                            ↑ 1 = plancher d'exemplaires INACTIF
# {…: 'code', …}   ← 'code' partout : la table est encore VIDE, ce sont les défauts
```

```
top1_country_sim_min = 0.55      # similarité, comparaison scopée au PAYS cible
country_spread_min   = 0.05      # écart top1 − top2  ← le garde-fou qui compte
```

Le commentaire de `thresholds.py` dit pourquoi : *« la SIM top1 ne sépare RIEN —
médiane hors-scope 0,834 ≈ médiane des top1 corrects 0,836 ; le SPREAD sépare
bien »*.

⛔ **Un seuil appartient à un encodeur.** Les sims de vits14 et vitl14 ne sont
pas sur la même échelle ; servir la mauvaise valeur ne lève aucune erreur, elle
déplace silencieusement le taux de faux positifs. Voir **`eurio-banque`** §4.

### Le palier d'auto-acceptation, et sa précision mesurée

`spread_auto_accept_min = 0,10` (banque `2eur_all` / `vitl14`). Vérifié le
2026-08-20 contre le gold figé `0ecbb1d70e3c`, précision du top-1
(`top1_eurio_id == truth_eurio_id`, `spread` global ≥ 0,10) :

| population | n | précision |
|---|---:|---:|
| crops **hors** banque | 463 | **98,5 %** |
| crops qui **sont** des ancres | 821 | 97,4 % |

Le palier tient donc **mieux** sur ce que la banque n'a jamais vu : il n'est pas
un artefact du fait que 858 des 1958 crops du gold soient eux-mêmes des ancres.
La requête complète est dans **`eurio-banque`** §4 — recopie-la, pas le nombre.

### ⛔ ~~Le piège qui invalide tout le reste : la review est AVEUGLE sur les standards~~ — RÉSOLU le 2026-08-24

> **Lis ce bloc comme de l'histoire, pas comme l'état courant.** Il décrit
> pourquoi la bascule ci-dessous a eu lieu. La jointure ne porte plus
> `'2eur_commemo'` en dur : elle interpole `VERDICT_ANCHORS_KIND`, qui vaut
> `2eur_all`. Un crop de pièce standard PEUT désormais être `auto_candidate`.

`repository.py::fetch_verdict_signal_rows` (l. 1091) joint **en dur** :

```sql
AND p.anchors_kind = '2eur_commemo'
```

Or cette banque ne contient **aucune** pièce standard. **Toujours vrai après le
rebuild du 2026-08-19**, remesuré le 2026-08-20 sur les `.npz` servis :

```bash
cd ml && ./.venv/bin/python -c "
import numpy as np
for k in ('2eur_all','2eur_commemo'):
    d = np.load(f'state/foundation_anchors_{k}.npz', allow_pickle=True)
    ids = set(d['eurio_ids'].tolist())
    print(k, 'lignes', len(d['eurio_ids']), 'étiquettes', len(ids),
          'dont standard', sum('standard' in i for i in ids))"
# 2eur_all     lignes 1533 étiquettes 671 dont standard 41
# 2eur_commemo lignes  508 étiquettes 508 dont standard  0
```

*(Le rebuild a fait passer `2eur_all` de 378 à 671 étiquettes et de 18 à 41
standard ; `2eur_commemo` reste à 0 sur 508. Les vieux chiffres 0/446 et 18/378
sont périmés — remesure, ne cite pas.)*

```sql
-- items de review OUVERTS ciblant la classe, ayant une prédiction (2026-08-17) :
fr-2euro-standard-t1        66 ouverts → 2eur_commemo:  0   2eur_all: 66
es-2euro-juan-carlos-i-t2   16 ouverts → 2eur_commemo:  0   2eur_all: 16
```

Conséquence : **aucun crop de pièce standard ne peut jamais être
`auto_candidate`** — tous tombent en `unknown` par la règle 1. Vérifié dans le
payload de l'API : à l'écran de lot, chaque crop porte `candidate_eurio_ids`
avec **`score: 0.0`** et `current_eurio_id: null`. Il n'y a pas de suggestion
DINO à l'écran, juste la liste plate des membres du groupe.

Donc pour une classe standard : n'attends pas l'auto-accept, il ne se
déclenchera pas ; la décision est **100 % à l'œil**, et le calibrage « ~10 % de
faux à 0,855 » ne s'applique pas puisqu'aucun score n'est affiché.

⚠️ Les prédictions existent (`2eur_all`, 66/66) — c'est la jointure qui les
ignore.

### ✅ La bascule est FAITE — `2eur_all` / `dinov2-vitl14` depuis le 2026-08-24

**Tout ce qui précède décrivait l'état d'avant.** Le verdict lit désormais la
même banque que les suggestions. Ce qui a autorisé la bascule — les deux banques
rejouées sur le MÊME gold, même base, même processus (`scripts/verdict_gold.py`,
1009 entrées / 811 labellisées, dont 464 **hors banque** c'est-à-dire qui ne
sont pas elles-mêmes des ancres) :

| gold labellisé hors banque (464) | `2eur_commemo`/vits14 | `2eur_all`/vitl14 |
|---|---:|---:|
| auto-accepts produits | 104 | **185** |
| dont justes | 104 | 184 |
| précision | 100 % | **99,5 %** |
| top-1 exact (in-scope) | 58,2 % | **92,6 %** |

Et sur la file ouverte (réplique, 2026-08-24 18:10) : **4 237 items sur 8 496
avaient une prédiction sous `2eur_commemo`, 8 495 en ont une sous `2eur_all`**.
La moitié de la file tombait en `unknown` par la règle 1 — pas parce que le
modèle hésitait, mais parce que le JOIN cherchait dans la mauvaise banque.

⚠️ **Les seuils n'ont pas été recalibrés.** `top1_country_sim_min` (0,55) et
`country_spread_min` (0,05) viennent de la confusion map vits14 ; ils tiennent
sur vitl14 (les 99,5 % ci-dessus). L'unique faux est à spread 0,1036, au milieu
de la distribution — 30 auto-accepts justes ont un spread plus bas. Le racheter
demanderait un seuil ≥ 0,15, qui coûte 41 % du volume. Calibration souhaitable,
pas urgente.

⛔ **Trois modules rebrodaient le littéral hors du point de bascule** et ont été
corrigés le même jour : `review/validation/experts.py` (le pire — c'est le
chemin de routage LIVE, `sources/_base/steps/enqueue.py` l'appelle sans kwargs
puis écrit la lane), `review/validation/replay.py`, et
`training/foundation/anchors.py::CONSENSUS_ANCHORS_KIND`. Ils sont désormais
dans le paramétrage de `tests/test_verdict_anchors_scope.py`. Si tu ajoutes un
site qui lit la prédiction du verdict, ajoute-le à `VERDICT_MODULES`.

### Le point de bascule est unique depuis le 2026-08-18

`ml/shared/verdict_scope.py` — **stdlib pure**, parce que l'image lean du VPS
n'embarque pas `training/` (le `Dockerfile` copie `shared/`, pas `training/` :
y mettre la constante aurait fait disparaître une route du VPS en silence, son
montage étant dans un `try/except`).

```python
VERDICT_ANCHORS_KIND     = "2eur_all"          # basculé le 2026-08-24
VERDICT_ENCODER_VERSION  = "dinov2-vitl14"
```

Les **10 sites** du chemin du verdict l'importent (repository lean, jumeau lourd
`review_queue_routes`, `auto_validate`, `review_lanes`, `peer_arbitration`,
`publish_cli`). Un test paramétré rougit si quelqu'un rebrode le littéral.

⛔ **`anchors_kind` et `encoder_version` sont indissociables.** En base :
`2eur_all` n'existe **qu'en `dinov2-vitl14`**, `2eur_commemo` **qu'en
`dinov2-vits14`**. Basculer le seul kind donne un JOIN à **zéro ligne** — donc
tout en `unknown`, sans la moindre erreur. Ne touche jamais l'un sans l'autre.

### Ce que la bascule a coûté — mesuré le 2026-08-24, le jour où elle a été faite

> Les chiffres de l'estimation du 2026-08-17 (« 2221 items changent, 130 faux
> positifs sur les crops non labellisés ») **ne sont plus la référence** : ils
> datent d'avant deux rebuilds de banque. Ce qui suit est la mesure réelle.

Protocole : les DEUX banques rejouées sur le même gold, la même base, dans le
même processus (`scripts/verdict_gold.py`, 1009 entrées / 811 labellisées).
La seule variable est le périmètre — on ne compare pas au `before_level` figé
en juin, qui mélangerait la bascule et trois mois de dérive.

| gold labellisé **hors banque** (464 crops) | `2eur_commemo` | `2eur_all` |
|---|---:|---:|
| auto-accepts produits | 104 | **185** |
| dont justes | 104 | 184 |
| précision | 100 % | **99,5 %** |

Sur les 1009 entrées, **283 changent** de verdict ou de lane, dont 182
promotions vers `auto_accept` (92 depuis `partial`, 90 depuis `divergent`) et
4 rétrogradations.

**Ce que la mesure ne couvre PAS, et qu'il faut garder en tête** : elle porte
sur les crops **labellisés par un humain**. L'estimation du 2026-08-17
s'inquiétait des crops que l'humain avait *refusé* de labelliser — là, aucune
vérité terrain n'existe, donc aucune précision n'est mesurable. La surveillance
de cette population reste ouverte.

⛔ **Le repli « `2eur_commemo` puis `2eur_all` si vide » aurait été la pire
option** : le scope serait devenu dépendant de l'item, deux crops voisins jugés
sur deux banques et deux encodeurs avec des seuils calibrés sur un seul, et
`decision_engine_version` n'aurait plus rien tracé. C'est aussi pour ça que
cette chaîne porte désormais la banque et l'encodeur, pas seulement les seuils.

### La marge, quand elle s'applique (classes commémoratives)

**Une similarité élevée ne prouve rien sans marge.** Mesuré le 2026-08-17, par
la requête ci-dessous — *candidats par PRÉDICTION* (crops dont le `top1` tombe
dans la classe), à ne pas confondre avec les crops qui la **ciblent** :

```sql
select count(*), avg(coalesce(p.country_spread, p.spread))
  from image_asset_dino_predictions p join image_assets a on a.id = p.asset_id
 where p.anchors_kind = '2eur_all' and a.training_eligible IS NOT 1
   and p.top1_eurio_id in (select eurio_id from coins where design_group_id = ?)
```

| Classe | top1 ∈ classe | dont marge ≥ 0,05 | marge moyenne |
|---|---|---|---|
| `fr-2euro-standard-t1` | 62 | **59** | 0,216 |
| `es-2euro-juan-carlos-i-t2` | 89 | **29** | 0,037 |

Les 2ᵉˢ hypothèses des crops espagnols sont Philippe, Benoît XVI, Albert II :
pour DINO, **tous les standards à portrait se ressemblent**, et le top1 gagne au
bruit. La marge élimine les deux tiers.

⚠️ **Tout chiffre ici porte sa requête, et pas seulement sa date.** Sans elle il
est irreproductible : deux mesures honnêtes de « les candidats de
`fr-2euro-standard-t1` » ont donné **59** et **0** parce qu'elles comptaient
deux populations différentes.

⚠️ Ces candidats incluent des items **déjà tranchés**. Ajoute
`and rq.status in ('open','in_progress')` si tu veux le stock exploitable.

⚠️ Donc : **ne jamais trier sur `top1_sim` seul.** Mieux : ne pas interroger la
table du tout et passer par le verdict. Si tu dois vraiment écrire du SQL, sache
que le service utilise `country_spread` **avec repli sur le `spread` global**
quand la bande pays est NULL — un filtre naïf sur la seule colonne country exclut
en silence des crops que le verdict, lui, évalue :

```sql
coalesce(p.country_spread, p.spread) >= 0.05      -- et non p.top1_sim seul
```

(La colonne `country_spread` existe déjà : ne la recalcule pas à la main. Et
attention, `training_eligible != 1` exclut les NULL en SQL — préfère
`training_eligible IS NOT 1`.)

## La file

`review_queue` (schéma : `ml/state/schema.sql`) —
`status` ∈ `open` / `in_progress` / `done` / `skipped` ·
`kind` ∈ `single` / `lot` ·
`lane` ∈ `manual` / `auto_accept` / `ccproxy` / NULL ·
`lane_source` ∈ `auto` / `human`.

État au **2026-08-20 à 14:03 UTC** : **6798 items ouverts** (5413 lot, 1385
single), 5060 `done`, 54 `skipped` — `SELECT status, kind, COUNT(*) FROM
review_queue GROUP BY 1,2` sur `ml/state/eurio.replica.db`. ⚠️ **Ce compte bouge
d'heure en heure** : le même jour à 09:00 UTC il rendait 6894 ouverts / 4964
`done` (le total 11 858 est stable, ce sont des items qui se décident). Cite
l'horodatage **à la minute** avec le chiffre, ou relance la requête. Le stock
est profond : une session de
review n'a de sens que **cadrée** — par classe, par lane, ou par run. Ne pas
« vider la file ».

### Combien viser par classe — la courbe l'a chiffré le 2026-08-20

Ce n'est plus une question d'intuition. Précision held-out en fonction du nombre
de crops validés qui entrent en banque pour la classe (`dinov2_vits14`,
`COURBE-REFERENCES.md`) :

```
N=0 : 53,1 %   N=1 : 50,1 % ← RÉGRESSION   N=2 : 54,6 %
N=3 : 57,3 %   N=5 : 66,4 %   N=8 : 73,9 %   N=10 : 75,5 %
```

⚠️ **« Ne laisse jamais une classe à UN seul crop validé » : cette règle a été
RETIRÉE le 2026-08-20.** Elle avait été codée en plancher `min_exemplars = 2` ;
la mesure restreinte l'a réfutée — donner à 57 classes exactement un exemplaire
**améliore** leurs propres crops (`vitl14` 67,6 → 69,1 %, p=0,048 ; `vits14`
41,6 → 45,5 %, p=4,5e-10). Le creux à N=1 de la courbe ci-dessus est un agrégat
« toutes les classes plafonnées à 1 », pas une règle par classe, et il vient de
l'**ordre** du FPS, pas du nombre. Défaut revenu à `min_exemplars = 1`
(inactif). Détail : **`eurio-banque` §3**.

**Ce qui reste vrai côté review** : un crop de plus rapporte toujours, et le
premier crop d'une classe est le plus atypique de son pool. **Cadrer une session
sur une classe pauvre rapporte plus que d'approfondir une classe riche** — mais
un crop unique n'est plus une raison de s'abstenir.

**La cible pratique est 8 crops validés par classe** — arbitrage coût/bénéfice
(~2,5 pt/réf avant, ~0,8 après), *pas* un plateau. Au-delà de 10, le plafond
`exemplars_per_class` fait que les crops n'entrent plus dans la banque du tout :
ils servent l'entraînement ArcFace, pas les suggestions. Or la médiane du pool
des 55 classes déjà pleines est de **25 crops décidés** — ces classes ont été
sur-reviewées d'un facteur 2,5 pour rien. **Cadrer par classe pauvre rapporte
plus que d'approfondir une classe riche.** Détail et budget : **`eurio-banque`**
§8.

Lecture : `GET /review-queue` (+ `/triage-stats`, `/stats`, `/lots`, `/rejected`).
Décision : `POST /review-queue/{review_id}/decide` · `/skip` · `/reject` ·
`/move-lane` (`serving/review_queue/writes.py`) ; les lots ont la leur :
`POST /review-queue/lots/{listing_key}/decide` (`serving/funnel_writes.py`).
Côté lab, sur un asset précis : `POST /lab/assets/{id}/accept-training` ·
`/training-eligible` · `/reassign` · `/reopen-review`.

⚠️ **Ne pas confondre avec `/review/items/{id}/decide|skip|claim`** : ces
routes-là (`serving/review_routes.py`) appartiennent au **service de peer-review
multi-utilisateur**, qui vit sur une **autre base** (`review_items` dans
`review.db`) et sert `eurio-review.musubi.dev`. Deux systèmes homonymes ; le front
`studio-local` n'appelle que `/review-queue/*`.

## Ce qui compte pour l'entraînement, précisément

Le bake ne prend un crop eBay que si **tout** est vrai (`iteration_augmentations
._ebay_training_sources`) :

- `training_eligible = 1` — la décision de review ;
- `storage_status = 'present'` ;
- `face IS NULL` ou `face != 'reverse'` — le revers commun 2 € n'entre jamais ;
- l'attribution qui fait foi est **`image_assets.eurio_id`** (le label tranché),
  pas `source_images.target_eurio_id` (la cible de découverte). Un crop réattribué
  suit son nouveau label ;
- ⚠️ **et une 5ᵉ condition, mais pas celle qu'on croit.** `_ebay_training_sources`
  fait `p = local_path("enrichment-crops", sp)` puis `if p.exists()`. Ce
  `p.exists()` **ne filtre jamais rien** : `local_path` télécharge depuis MinIO
  au premier appel et **lève `FileNotFoundError`** si l'objet est réellement
  absent (`shared/storage/local_cache.py` l. 71-116). Un cache local vide ne
  fait donc rien perdre — il ralentit.

  Le vrai silence est en amont : sur un 404 confirmé, `local_path` appelle
  `cascade.mark_missing_in_storage()`, qui bascule `storage_status` en base.
  C'est le bake **suivant** qui verra moins de sources — sans rien dire, puisque
  le filtre `storage_status='present'` les écarte proprement. Voilà comment un
  bake « réussit » avec moins de sources que prévu.

Et le compte se fait **par classe**, pas par pièce (cf. `eurio-enrichment`).

## Où va l'écriture

**Le reroutage est fait côté FRONT, pas côté API.** `useReviewApi.ts` /
`useLotReview.ts` appellent `eurioApi` (base `https://eurio-api.musubi.dev`,
Bearer PAT) et **jamais** `ML_API`. L'API locale `:8042` n'est pas dans le
chemin — elle tourne sous le flip et traduirait toute écriture en
`503 canonical_readonly`.

Corollaire : **le Mac ne voit pas ses propres décisions** tant qu'il n'a pas fait
`go-task ml:db:pull-replica`. Un préflight relancé sans ce pull affichera encore
l'ancien compte.

### ⛔ L'échec muet du front — celui qui coûtera le plus cher

`useReviewApi.ts` (l. ~145-159) : sur `TypeError` — réseau coupé, DNS lent, VPS
injoignable — `safeFetchEurioWrite` renvoie `null` et le code se contente d'un
`console.info('[mock fallback] decide', …)`. **L'UI affiche un succès et rien
n'est écrit.** Les 401/503 remontent proprement ; c'est la coupure réseau qui est
silencieuse. Quelqu'un peut « trancher » quarante crops et n'en avoir écrit
aucun.

Le contrôle le plus rapide, après une session de review :

```bash
sops exec-env secrets/dev.env 'curl -s -H "Authorization: Bearer $EURIO_API_TOKEN" \
  "$EURIO_API_URL/review-queue/stats"'      # n_done_today doit avoir bougé
```

Si une route répond `503 canonical_readonly`, elle n'a pas encore été reroutée —
lire **`eurio-data-writes`**, ne pas contourner en écrivant en local.

## Ensuite

→ **`eurio-banque`** : dès que tu touches à un seuil, à la banque d'ancres, ou
  que tu veux savoir combien de crops une classe mérite.
→ **`eurio-run-local`** : créer l'itération sur la cohorte enfin nourrie.
→ Puis la promotion : `docs/architecture/parcours.md` §5.

## Ce que cette skill ne couvre PAS

- La **banque d'ancres** elle-même — comment elle se lit, ce que valent ses
  suggestions, ce que coûte un rebuild : **`eurio-banque`**.
- Le moteur de décision complet : `ml/serving/review_queue/service.py` (~400 l.)
  et `ml/training/foundation/auto_validate.py` pour les signaux (face, denom,
  texte, DINO).
- La review de **lots** (annonces multi-pièces, 77 % de la file ouverte) : elle a
  sa propre plaque d'examen, cf. `detections_json` sur `source_images`.
- La provenance des crops : `eurio-enrichment`.
