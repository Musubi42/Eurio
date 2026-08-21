# O1 · Le besoin par classe, calculé en un seul endroit

> **Statut : spec, non implémentée.** Station 0 du
> [flow](../FLOW-ADMIN.md). Dépend de rien ; tout le reste en dépend.

## Le geste

Répondre, pour n'importe quelle classe de la banque : **combien lui manque-t-il,
et à quoi tient son manque.** Un seul module, appelé par l'écran (O2),
l'entonnoir (O3) et, à terme, l'allocateur.

## Pourquoi un module et pas une requête dans l'écran

Parce que ce calcul est déjà écrit **trois fois** dans le dépôt, à trois mailles
différentes, et que deux d'entre elles sont fausses selon le point de vue :

| endroit | maille | ce qu'il compte |
|---|---|---|
| `scripts/allocate_ebay_scrape.py` | groupe de découverte | `need = max(0, 8 − have − pending)` |
| `useCohortFloor.ts` | classe **coins** | `n_ebay` (voie A, seuil `min_real`) |
| `repository.dino_candidates_summary` | classe **coins** | `n_training_eligible` |

Et la banque, elle, indexe à une **quatrième** maille : l'`eurio_id` du
représentant. Une requête écrite avec la convention `coins` rend **2 166 crops
« hors banque »** qui sont pourtant en banque, sans lever quoi que ce soit
(défaut Q13, cf. [`VISION.md`](../VISION.md) §V4).

## Le contrat

Emplacement proposé : `ml/shared/class_need.py` — **stdlib uniquement**
(`sqlite3`), même contrat d'import que `shared/dino_scope.py` et
`shared/bank_classes.py` : l'image lean du VPS doit pouvoir l'importer sans
tirer numpy ni torch.

```python
@dataclass(frozen=True)
class ClassNeed:
    class_id: str            # maille BANQUE (eurio_id du représentant)
    label: str               # désignation lisible
    country: str | None
    family: str              # cf. O5 : nationale | portrait_standard | emission_commune
    have: int                # exemplaires 'fps' en banque
    cap: int                 # DEFAULT_EXEMPLARS_PER_CLASS, lu, jamais écrit en dur
    target: int              # 8, résolu depuis dino_thresholds, jamais littéral
    pending: int             # crops en file OUVERTE dont le top-1 tombe ici
    pending_scoped: int      # idem, après les filtres par signaux (O4)
    need: int                # max(0, target − have)
    bottleneck: str          # review | scrape | pleine | image_insuffisante
    n_train_eligible: int    # voie A, pour affichage seulement — JAMAIS pour le verdict
```

### Les règles, et ce que chacune écarte

**`have`** — grain banque, `method='fps'` :

```sql
SELECT class_id, SUM(method='fps') FROM dino_class_references
 WHERE anchors_kind = :kind GROUP BY 1;
```

⛔ **Pas de `COALESCE(design_group_id, eurio_id)` ici.** C'est le piège Q13.
La traduction dans l'autre sens passe par `shared.bank_classes`.

**`pending`** — crops en file **ouverte** dont le top-1 tombe dans la classe :

```sql
SELECT COUNT(*) FROM review_queue rq
  JOIN image_asset_dino_predictions p ON p.asset_id = rq.image_asset_id
 WHERE rq.status = 'open' AND p.anchors_kind = :kind
   AND p.encoder_version = :enc AND p.top1_eurio_id IN (:bank_class_ids);
```

⛔ `status='open'` **exactement**, jamais `IN ('open','in_progress')` : c'est ce
que `list_queue` sert, et deux populations pour un même fait produisent un badge
qui annonce 4 au-dessus d'une file qui en sert 3. Le précédent est écrit dans
`dino_candidates_summary`.

**`target` et `cap`** — résolus, jamais littéraux. `cap` vient de
`DEFAULT_EXEMPLARS_PER_CLASS` (`anchors.py`), `target` de `dino_thresholds` avec
défaut stdlib. Écrire `8` en dur reproduirait le défaut déjà corrigé dans
`useCohortFloor.ts`, où `FLOOR = 10` et `GOAL = 30` étaient inventés localement.

**`bottleneck`** — l'ordre compte, il est exclusif, et il est le cœur de l'outil :

```
1. have >= cap                    → 'pleine'                (on arrête de servir)
2. family == 'emission_commune'   → 'image_insuffisante'    (cf. O5)
3. pending_scoped > 0             → 'review'
4. sinon                          → 'scrape'
```

⛔ **`pending_scoped`, pas `pending`.** Une classe dont les 44 candidats
disparaissent tous une fois les filtres appliqués doit dire `scrape`, pas
`review` — sinon l'écran envoie l'opérateur vers une file vide, ce qui se lit
« rien à trancher » : plausible, et faux.

**`n_train_eligible`** — la voie A, calculée avec les **quatre** conditions du
bake (`source='ebay'`, `training_eligible=1`, `storage_status='present'`,
`face IS NULL OR face != 'reverse'`), à la maille `coins`. Affichée à côté, sur
une ligne distincte, avec son propre libellé. **Elle n'entre dans aucun
verdict** — voir [`FLOW-ADMIN.md`](../FLOW-ADMIN.md) §4.

## Ce que l'outil doit refuser de faire

1. **Il n'écrit rien.** Connexion ouverte en `mode=ro`. Le besoin est une
   lecture ; toute écriture déclenchée au fil d'une lecture est invisible à
   celui qui la provoque (précédent : les orphelins de la pêche, D6).
2. **Il ne devine pas `anchors_kind`.** Le couple `(kind, encoder_version)` est
   un paramètre obligatoire, jamais un défaut : basculer l'un sans l'autre donne
   un JOIN à zéro ligne et tout en `unknown`, sans une erreur.
3. **Il ne masque pas les classes pleines.** Elles sortent de la liste avec le
   verdict `pleine` — c'est l'information la plus utile de l'outil (3 612 crops
   ouverts les concernent).

## Comment on vérifie qu'il marche

**Les invariants**, en test :

- `sum(need)` sur toutes les classes reproduit le déficit mesuré à la main
  — **4 663** vers 8, le 2026-08-21 ;
- `count(bottleneck == 'scrape')` reproduit **347** ;
- `count(bottleneck == 'pleine')` reproduit **64** ;
- une classe courante non-représentante (`it-2008-2eur-standard-2nd-map`)
  et son représentant rendent **le même** `ClassNeed` ;
- `eu-euro-cash-2012` en entrée rend **18** `ClassNeed`, pas un.

**La mutation** — casser puis vérifier que le test rougit (`eurio-verify`) :
remplacer la traduction `bank_classes` par un `COALESCE(design_group_id,
eurio_id)` naïf doit faire tomber le test des 2 166, pas passer au vert.

**Le câblage** — faire tourner le vrai point d'entrée avec la vraie variable
d'environnement, pas seulement le prédicat :

```bash
cd ml && EURIO_DB_PATH=$PWD/state/eurio.replica.db \
  ./.venv/bin/python -c "…; print(len(all_needs(c, kind='2eur_all', enc='dinov2-vitl14')))"
# 671
```

## Ce qui reste à trancher

- **`target = 8` par classe, ou par famille ?** Une émission commune ne
  dépassera jamais 64 % sur le pays quel que soit N (cf. O5). Lui allouer 8 est
  peut-être du gaspillage — mais on n'a pas mesuré ce que N change **sur le
  dessin** pour ces classes-là.
- **`pending` doit-il exiger une marge minimale ?** L'allocateur utilise
  `marge ≥ 0,05`. Sur les trois classes du terrain d'essai, cette exigence fait
  passer les classes comblables de 66 à 36. Deux chiffres également honnêtes ;
  il faut en choisir un et le dire à l'écran.
