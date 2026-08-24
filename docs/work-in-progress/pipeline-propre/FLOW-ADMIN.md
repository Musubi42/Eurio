# Le flow admin — comment on pilote la chaîne

> Suite de [`VISION.md`](VISION.md), qui pose l'objectif et les quatre vérités.
> Celui-ci répond à une seule question : **par quels écrans passe-t-on, dans
> quel ordre, et que fait-on à chaque station.** Les outils qui en découlent
> ont chacun leur spec dans [`outils/`](outils/).
>
> Écrit le **2026-08-21**. Mesures sur `ml/state/eurio.replica.db`, lecture
> seule. Chaque chiffre porte sa requête.

---

## 1. Le principe : un seul modèle, lu dans les deux sens

L'admin a déjà la bonne idée, et elle est enterrée dans `/bench`.
`BenchFunnel.vue` part d'une **recherche eBay** et empile des plaques dont la
largeur est proportionnelle à ce qui reste. `/bench/runs/{run_id}` fait la même
chose sur un run réel, à la maille **groupe de découverte** (pays · dénomination
· année) — exactement la maille de l'allocateur.

C'est le bon modèle. Il lui manque deux choses :

1. **Il s'arrête trop tôt.** Ses dernières plaques sont
   `n_review_single / n_review_lot / n_auto`. Il ne dit pas combien de crops ont
   été *validés*, ni combien d'*exemplaires* sont entrés en banque — c'est-à-dire
   la seule chose qu'on cherchait en lançant la recherche.
2. **Il ne se lit que dans un sens.** Il répond à *« qu'est devenue cette
   recherche ? »*. Il ne répond pas à *« cette classe manque de 5 exemplaires,
   qu'est-ce que je fais ? »*.

> **Le flow, en une phrase :** le même entonnoir, étendu jusqu'à la banque, se
> lit **en avant** comme un diagnostic et **à rebours** comme une liste de
> travail.

---

## 2. Les sept plaques

Une plaque par transition réelle du pipeline, avec la table qui la porte.
Les comptes ci-dessous sont le **cumul eBay**, mesuré le 2026-08-21 :

| | plaque | volume | table / colonne |
|---|---|---:|---|
| P1 | recherches émises | 204 | `discovery_searches` (195 `success`, **9 `empty`**) |
| P2 | annonces retenues | 16 241 | `source_images` (source `ebay`) |
| P3 | images téléchargées | 14 951 | `download_status != 'failed'` |
| P4 | images ayant produit un crop | **6 989** | `crop_status = 'success'` |
| P5 | crops détectés | 12 449 | `image_assets` |
| P6 | crops survivant aux portes | 9 375 | `resolution_status != 'rejected'` |
| P7 | crops validés par un humain | 2 157 | `training_eligible = 1` |
| P8 | exemplaires retenus en banque | **824** | `dino_class_references`, `method='fps'` |

*(Huit plaques, pas sept — P4 et P5 se sont révélées distinctes à la mesure,
et c'est justement là qu'est la plus grosse fuite.)*

```sql
SELECT COUNT(*) FROM source_images WHERE source='ebay';                        -- 16241
SELECT COUNT(*) FROM source_images WHERE source='ebay' AND download_status='failed'; -- 1290
SELECT COUNT(*) FROM source_images WHERE source='ebay' AND crop_status='zero_crops'; -- 7531
SELECT COUNT(*) FROM source_images WHERE source='ebay' AND crop_status='success';    --  6989
SELECT status, COUNT(*) FROM discovery_searches GROUP BY 1;                    -- empty|9 success|195
```

### 🔴 La fuite qu'on ne regardait pas : P3 → P4

**7 531 images (46 % du total, 50 % des téléchargements réussis) ont été
téléchargées puis jetées** parce que la détection n'a rien trouvé :
`crop_status='zero_crops'`, `crop_error='normalize_listing returned 0 crops'`
sur 7 403 d'entre elles.

C'est **la plus grosse perte de toute la chaîne**, et elle arrive **après**
qu'on a payé l'appel eBay. À ~15 appels par exemplaire gagné, la moitié de ce
coût est dépensée sur des images qui ne produiront jamais rien.

✅ **Corrigé le 2026-08-21** — c'est **bien** le chantier
[`crop-recovery`](../../archive/crop-recovery/README.md) (même diagnostic, même jeu D2), on
**a** regardé les images (60 au hasard : **70 % sont une pièce seule, propre,
plein cadre**, que YOLO ne voit pas), et le remède livré (`score_recover`,
OFF par défaut) en rattrape **76 %**. Au grain **annonce** — l'unité de coût
eBay — **2 950 annonces sur 7 662 n'ont aucun crop**, 808 visent des classes
déficitaires. Détail, mesures et requêtes : [`VISION.md`](VISION.md) §2 et
[`outils/O7`](outils/O7-reprocess-zero-crops.md). La plaque P3 → P4 de
l'entonnoir doit se lire **par annonce**, pas par image.

---

## 3. Les quatre stations

```
                    ┌──────────────────────────────┐
                    │   STATION 0 — LE BESOIN      │  ← la porte d'entrée
                    │   « quelle classe, pourquoi »│
                    └───┬───────┬───────┬──────┬───┘
         goulot=scrape  │       │       │      │  goulot=impossible
                        ↓       │       │      └──→ (famille « émission
        ┌───────────────────┐   │       │             commune » : on sait
        │ 1 · PLAN DE SCRAPE│   │       │             que l'image ne suffit
        │  groupe · coût    │   │       │             pas — on ne dépense pas)
        └─────────┬─────────┘   │       │
                  │   goulot=review     │  « ça a coûté et rien n'est sorti »
                  │             ↓       ↓
                  │   ┌──────────────┐ ┌────────────────────┐
                  │   │ 2 · LA PÊCHE │ │ 3 · L'ENTONNOIR    │
                  │   │  déjà cadrée │ │  où ça s'est perdu │
                  │   └──────┬───────┘ └────────────────────┘
                  │          │
                  └──────────┴──→ le rebuild recalcule le besoin
                                  et la STATION 0 change
```

### Station 0 — Le besoin

**Nouvelle. C'est la porte d'entrée de tout le reste, et elle n'existe pas.**

Une liste de classes, ordonnée par *ce que l'action peut débloquer aujourd'hui*.
Chaque ligne porte `have/8`, les candidats disponibles, et surtout un **verdict
de goulot** qui décide vers quelle station elle envoie :

| verdict | condition | envoie vers |
|---|---|---|
| `review` | des candidats attendent en file | Station 2 · la pêche |
| `scrape` | 0 candidat en file | Station 1 · le plan |
| `pleine` | `have ≥ 10` | nulle part — **on arrête de servir cette classe** |
| `image_insuffisante` | famille « émission commune » | à part (cf. `outils/O5`) |

Sans elle, l'admin ne sait pas ce qu'il doit faire : mesuré, **3 612 des
6 617 crops ouverts appartiennent à des classes qui n'ont besoin de rien**, et
**347 classes déficitaires n'ont aucun crop en file** — les envoyer en review
est du temps perdu par construction.

→ outils [`O1`](outils/O1-besoin-par-classe.md) (le calcul) et
[`O2`](outils/O2-vue-classe-vers-8.md) (l'écran).

### Station 1 — Le plan de scrape

**Existe à moitié.** L'allocateur (`go-task ml:ebay:allocate`) fait le calcul et
le plan ; il n'a pas de surface admin. `/sources` montre les runs passés, pas le
plan à venir.

Ce qu'elle doit faire : depuis une ligne « goulot = scrape », montrer le groupe
de découverte concerné, son coût estimé (130 appels commémo / 240 standard), ce
qu'il sert d'autre, et le quota restant du jour. Lancer reste un geste explicite.

⚠️ **Deux réserves à porter à l'écran**, sinon la station ment :
le préflight quota de `sources/cli.py` est faux d'un facteur ~130 (il compte sur
`source_runs.n_calls`), et le budget vrai est dans `ml/state/eurio.local.db`
(`api_call_log`), pas au canonique.

*(Hors périmètre de cette session — l'allocateur tourne en CLI et ça suffit pour
l'instant. Noté ici pour que le flow soit complet.)*

### Station 2 — La pêche

**Existe et fonctionne.** `/review/peche?class=<class_id>` — unité/lots, top
1-3-5, paliers de marge, pastille pays, déroulé des lots un par un.

Ce qui lui manque n'est pas l'écran mais **ce qu'on met dedans** : elle ne lit
aucun des signaux de `listing_text_signals` (peuplé à 100 % sur les crops
ouverts) ni `denom_2eur_score`, et son filtre pays vide entièrement la file pour
137 classes sur 338.

→ outil [`O4`](outils/O4-filtres-par-signaux.md).

### Station 3 — L'entonnoir

**Existe pour 4 plaques.** `/bench/runs/{run_id}` montre
`route_decision`/`route_reason` par groupe de découverte, avec le détail des
drops. Il s'arrête avant la review et avant la banque.

Ce qu'il doit devenir : les **huit** plaques du §2, avec la fuite P3→P4 nommée,
et une entrée **par classe** en plus de l'entrée par run — pour répondre à
« cette classe a coûté deux runs, où sont passés les crops ? ».

→ outil [`O3`](outils/O3-entonnoir-huit-plaques.md).

### La boucle

Elle se ferme au rebuild de la banque : `have` change, donc le besoin change,
donc la Station 0 change. **C'est la seule arête qui n'existe aujourd'hui sous
aucune forme** — ni écran, ni calcul, ni tâche.

---

## 4. Le piège de nommage à trancher avant de coder

**Il y a deux « N par classe » dans le projet, et ils ne comptent pas la même
chose.** Les afficher tous deux « x/10 » dans le même admin produirait
exactement le genre de panne muette que ce dépôt collectionne.

| | **voie A — cohorte / ArcFace** | **voie B — banque DINO** |
|---|---|---|
| ce qu'on compte | crops eBay validés et éligibles au bake | vecteurs retenus par le FPS |
| seuil | `min_real` (10), cible d'entraînement 100 après augmentation | cible **8**, plafond dur **10** |
| où c'est calculé | préflight de cohorte, `useCohortFloor.ts` | `dino_class_references` |
| grain | `COALESCE(design_group_id, eurio_id)` | **`eurio_id` du représentant** |

Mesuré : les deux rails avancent ensemble — seules **2 classes** ont ≥ 10 crops
validés et < 8 exemplaires en banque. Mais la **médiane des classes pleines est
de 25 crops validés** pour un plafond de 10 : au-delà de 10, le travail de
review nourrit encore la voie A et ne nourrit **plus du tout** la voie B.

Et le grain diverge violemment sur les émissions communes : `eu-euro-cash-2012`
est **une** classe côté `coins` (73 crops validés) et **dix-huit** classes en
banque, une par pays.

> ✅ **Décision prise le 2026-08-21 (D1) :** la Station 0 compte la **voie B**, et le dit dans son
> en-tête. Une classe pleine côté banque affiche « pleine pour la banque » et,
> si une cohorte la réclame, renvoie vers le préflight de cohorte plutôt que de
> mélanger les deux barres.

---

## 5. Les outils qui en découlent

| | outil | station | dépend de |
|---|---|---|---|
| [O1](outils/O1-besoin-par-classe.md) | Le besoin par classe, calculé en un seul endroit | 0 | — |
| [O2](outils/O2-vue-classe-vers-8.md) | La vue « classe → 8 » | 0 | O1 |
| [O3](outils/O3-entonnoir-huit-plaques.md) | L'entonnoir étendu, lisible par run et par classe | 3 | O1 |
| [O4](outils/O4-filtres-par-signaux.md) | Les filtres par signaux dans le périmètre de pêche | 2 | O5 |
| [O5](outils/O5-familles-de-signal.md) | La table « quel signal décide », par famille de classe | 0 · 2 | — |
| [O6](outils/O6-amorce-fps-medoide.md) | L'amorce du FPS au médoïde | — (la racine) | — |
| [O7](outils/O7-reprocess-zero-crops.md) | Reprocesser les 2 950 annonces sans crop | 3 | — |

**Ordre arbitré le 2026-08-21** (détail : [`DECISIONS.md`](DECISIONS.md)) :
**O7 d'abord** — ~2 000 crops sans quota, code existant, et ça change le
`pending` de toutes les classes. Puis O6 (la racine côté banque, avec le
préalable `min_exemplars`). Puis O5 et O1, du calcul sans écran. Puis la
**phase de design** d'O2 et O4 (écrans admin : pas de proto, mais une
conception posée avant le code — cf. D6), puis leur implémentation. O3 ensuite.

⚠️ **O6 a un préalable non négociable** : la banque servie porte encore
`min_exemplars=2` alors que le code ne l'applique plus. Un rebuild ferait
bouger deux choses à la fois et **le garde P1 ne le dirait pas**. Il faut
décider avant de rebâtir — cf. la spec.
