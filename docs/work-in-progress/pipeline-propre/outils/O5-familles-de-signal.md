# O5 · La table « quel signal décide », par famille de classe

> **Statut : LIVRÉ.** `ml/shared/class_family.py` (stdlib-only).
> Alimente [O1](O1-besoin-par-classe.md)
> (le verdict de goulot) et [O4](O4-filtres-par-signaux.md) (les défauts de
> filtre). Dépend de rien.

## Le geste

Dire, **par classe**, quel signal tranche — parce qu'il n'est pas le même
partout, et que le traiter comme s'il l'était garantit une erreur structurelle
sur une famille entière.

## La mesure qui impose cet outil

Cinq **émissions communes** — un dessin identique frappé par 13 à 19 pays :

```sql
SELECT design_group_id, COUNT(DISTINCT country), COUNT(*) FROM coins
 WHERE design_group_id IS NOT NULL GROUP BY 1 HAVING COUNT(DISTINCT country) > 1;
-- eu-erasmus-2022 19 · eu-eu-flag-2015 19 · eu-euro-cash-2012 18
-- eu-emu-2009 16 · eu-rome-2007 13                    →  87 pièces
```

La banque en fait **87 classes distinctes** — le builder indexe une
commémorative sous son propre `eurio_id`, jamais sous son `design_group_id`.
Précision du top-1 sur les 219 crops de ces pièces déjà labellisés par un
humain :

| ce qu'on demande | précision |
|---|---:|
| le bon **dessin** (pays indifférent) | **97,7 %** |
| le bon **pays** | **64,4 %** |

Le seul écart visible entre un Erasmus autrichien et un Erasmus chypriote est
une inscription de quelques millimètres, illisible à 224 px. **Un tiers des
verdicts est un tirage au sort, et aucune quantité de crops supplémentaires ne
le corrigera** — c'est une propriété de la pièce, pas du modèle.

Coût actuel : **1 029 des 6 617 crops ouverts** (16 %) pointent vers une
émission commune.

## Les trois familles

| famille | définition | signal décisif | signal d'appoint |
|---|---|---|---|
| `nationale` | commémorative propre à un pays | **image** (DINO top-1) | texte, marge |
| `portrait_standard` | courante à effigie | image + **pays** (l'image ne sépare pas les portraits entre pays) | ère (sépare t1/t2 dans un même pays) |
| `emission_commune` | membre d'un `design_group_id` multi-pays | **texte / pays** — l'image ne peut pas | image, pour confirmer le dessin |

La détection de la famille est du SQL pur, aucune donnée nouvelle :

```sql
-- emission_commune
COALESCE(design_group_id,'') IN (
  SELECT design_group_id FROM coins WHERE design_group_id IS NOT NULL
   GROUP BY 1 HAVING COUNT(DISTINCT country) > 1)
-- portrait_standard : is_commemorative = 0 AND face_value = 2.0
-- nationale : le reste
```

Emplacement proposé : `ml/shared/class_family.py`, **stdlib uniquement**, même
contrat d'import que `shared/bank_classes.py`.

## Ce que la famille change, concrètement

**Pour O1 — le verdict de goulot.** Une classe `emission_commune` déficitaire
porte `image_insuffisante` et **ne part pas en review comme les autres** : lui
envoyer 155 crops (le cas de `cy-2012-2eur-10-years-of-euro-cash`) fait trancher
un humain sur une différence qu'il devra lire dans le titre de l'annonce, pas
dans la vignette.

**Pour O4 — les défauts de filtre.** Le filtre pays n'a pas le même statut selon
la famille :

| famille | filtre pays |
|---|---|
| `nationale` | utile, levable |
| `portrait_standard` | **le seul qui sépare** — 90,6 % → 99,6 % sur les singles |
| `emission_commune` | **quasi obligatoire** — sans lui le top-1 est à 64,4 % |

**Pour la review.** Une famille `emission_commune` devrait afficher le titre de
l'annonce **au premier plan**, pas la vignette : c'est là qu'est l'information.
*(Design non spécifié ici — il appartient au proto, cf. R1.)*

## La question ouverte, et elle est lourde

**Faut-il donner 8 exemplaires à une classe `emission_commune` ?**

Arguments dans les deux sens, aucun mesuré :

- **contre** — le pays ne sera jamais mieux que 64 % quel que soit N ; ce sont
  87 classes × 8 = 696 exemplaires, soit 15 % du déficit total (4 663), pour un
  verdict qui restera un tirage au sort ;
- **pour** — la mesure porte sur le **pays**. On n'a jamais mesuré ce que N
  change **sur le dessin** pour ces classes-là, ni si une banque mieux fournie
  aiderait à séparer un Erasmus d'une autre commémorative. Les priver
  d'exemplaires pourrait dégrader autre chose.

✅ **Tranché par la mesure le 2026-08-21 (D4, chiffres dans
[`../DECISIONS.md`](../DECISIONS.md))** : scopé au pays, 90 % à N=0 → 97 % à
N=5, plat après ; sans le pays, 17–29 % quel que soit N. Cible pratique
**5** pour cette famille, pays résolu avant DINO. Le paragraphe qui suit
reste la méthode qui y a mené.

⛔ **Ne pas trancher par le raisonnement.** C'est exactement la faute du plancher
`min_exemplars` : un mécanisme inféré, appliqué, puis réfuté par la mesure. Le
geste qui tranche existe et il est peu coûteux — restreindre la courbe :

```bash
cd ml && EURIO_DB_PATH=$PWD/state/eurio.replica.db ./.venv/bin/python \
  -m scripts.bench_refs_curve --model dinov2_vitl14 --refs 0 1 2 3 5 8 \
  --bank-classes @emissions_communes.txt --gold-classes @emissions_communes.txt
```

⚠️ Avec la réserve connue : les classes visées doivent avoir assez de crops
**held-out** pour être notables. C'est ce qui a rendu la question du plancher
inévaluable (77 crops pour ~70 classes, dont 61 étaient l'ancre elle-même).
**Compter d'abord, mesurer ensuite** — et si la population est trop mince, le
dire, comme la dernière fois.

## Comment on vérifie qu'il marche

- `class_family('cy-2012-2eur-10-years-of-euro-cash')` → `emission_commune`.
- `class_family('be-2014-2eur-standard-philippe')` → `portrait_standard`.
- Le compte total : **87** pièces en `emission_commune`, réparties sur 5 groupes.
- L'invariant qui compte : la famille se calcule sur le **grain banque**. Une
  émission commune donne 18 classes `emission_commune`, pas une classe unique.

## Ce que cet outil n'est pas

- **Ce n'est pas une fusion de classes.** On ne propose pas de replier les 18
  euro-cash 2012 en une seule classe : l'app doit rendre le pays à
  l'utilisateur, et le référentiel a raison de les distinguer.
- **Ce n'est pas un changement de banque.** La famille est une lecture ; aucune
  ancre ne bouge.
