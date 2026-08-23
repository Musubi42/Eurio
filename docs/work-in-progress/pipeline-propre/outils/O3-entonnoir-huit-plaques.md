# O3 · L'entonnoir à huit plaques

> **Statut : NON IMPLÉMENTÉ — et c'est le seul outil du chantier qui reste.**
> Débloqué depuis le lot 2 : il consomme `GET /class-need`, qui existe.
> C'est la suite naturelle une fois `/besoin` déployé et vérifié.
> Cf. [`../REPRENDRE-ICI.md`](../REPRENDRE-ICI.md). Station 3 du
> [flow](../FLOW-ADMIN.md). Étend un écran qui existe.

## Le geste

Répondre à *« ce groupe a coûté 240 appels eBay, qu'est-ce qui en est sorti, et
où le reste s'est-il perdu ? »* — et à sa question jumelle, *« cette classe a
consommé deux runs, où sont passés ses crops ? »*.

## Ce qui existe déjà, et qui est bon

`admin/.../features/bench/` porte **deux** entonnoirs, et le modèle est le bon :

| écran | source | maille |
|---|---|---|
| `/bench` | rejeu du gold gelé (196 listings) | recherche eBay, avec label humain → scoring |
| `/bench/runs/{run_id}` | run réel, `route_decision`/`route_reason` persistés | **groupe de découverte** (pays · dénomination · année) |

`BenchFunnel.vue` fait déjà l'essentiel : la largeur d'une plaque est
proportionnelle à son compte — *« le rétrécissement EST l'entonnoir »*, dit son
commentaire — et chaque transition porte ses **drops** avec leur raison
(`BenchRunGroupDrop { node_id, stage, label, reason, route_decision, count }`).

La maille du run-audit est **exactement** celle de l'allocateur. Rien à
réinventer.

## Ce qu'il faut ajouter

### a) Les quatre plaques manquantes

Le run-audit s'arrête à `n_review_single / n_review_lot / n_auto / n_quotes`.
Il ne dit pas ce qu'on cherchait en lançant la recherche. Les plaques à ajouter,
avec leur source :

| plaque | source |
|---|---|
| crops survivant aux portes | `image_assets.resolution_status != 'rejected'` |
| crops **validés par un humain** | `training_eligible = 1` |
| crops éligibles au bake | + `storage_status='present'` et `face != 'reverse'` |
| **exemplaires entrés en banque** | `dino_class_references`, `method='fps'` |

La dernière transition a trois causes de perte distinctes, et elles doivent être
nommées séparément — sinon « 62 validés → 50 ancres » se lit comme une panne :

1. le **plafond** `DEFAULT_EXEMPLARS_PER_CLASS = 10` ;
2. le **plancher de similarité** `floor_sim = 0,45` ;
3. le **FPS** lui-même, qui n'en retient que N.

### b) La fuite P3 → P4, qui n'est pas dans l'écran

Mesuré le 2026-08-21, périmètre eBay :

```sql
SELECT COUNT(*) FROM source_images WHERE source='ebay';                              -- 16241
SELECT COUNT(*) FROM source_images WHERE source='ebay' AND download_status='failed'; --  1290
SELECT COUNT(*) FROM source_images WHERE source='ebay' AND crop_status='zero_crops'; --  7531
SELECT COUNT(*) FROM source_images WHERE source='ebay' AND crop_status='success';    --  6989
```

**7 531 images téléchargées avec succès n'ont produit aucun crop** — 46 % du
total, 50 % des téléchargements réussis, et
`crop_error='normalize_listing returned 0 crops'` sur 7 403 d'entre elles.

C'est la plus grosse plaque de perte de la chaîne et **elle n'apparaît sur aucun
écran.** L'entonnoir doit la montrer, et la rendre cliquable — voir
[O7](O7-reprocess-zero-crops.md). ⚠️ Cette plaque se lit **par annonce** (2 950 / 7 662), pas par image : l'unité de coût eBay est l'`item/{id}`.

### c) L'entrée par classe

Aujourd'hui on entre par `run_id`. Il faut pouvoir entrer par `class_id` et voir
l'entonnoir **agrégé sur tous les runs qui ont servi cette classe**. C'est ce
qui ferme la boucle avec [O2](O2-vue-classe-vers-8.md) : une ligne « goulot =
scrape » avec un historique de deux runs doit pouvoir répondre « on a cherché,
voilà ce qui s'est passé » plutôt que « on n'a jamais cherché ».

⚠️ La distinction est mesurable depuis peu et elle a été mal documentée :
`discovery_searches.status` porte déjà la valeur `'empty'`, et **9 recherches y
sont enregistrées**. La note de l'allocateur affirme qu'aucune preuve de
recherche vide n'existe en base — elle regardait `coin_source_status`, une autre
table. À corriger là-bas.

```sql
SELECT status, COUNT(*), SUM(n_kept_results=0) FROM discovery_searches GROUP BY 1;
-- empty|9|9      success|195|0
```

## Le piège de fraîcheur à traiter

`route_decision` est **périmé sur une grande partie du stock** :

```sql
SELECT si.route_decision, COUNT(*) n_si,
       SUM((SELECT COUNT(*) FROM image_assets a WHERE a.source_image_id=si.id) > 0) avec_crops
  FROM source_images si GROUP BY 1;
-- pending|9262|236        ← 9 026 images « en attente » qui n'auront jamais de crop
```

L'entonnoir lit `route_decision`. S'il l'affiche tel quel, il annonce 9 262
images « en cours de traitement » alors que 7 531 sont définitivement mortes au
crop. **Une valeur par défaut plausible là où il faudrait un état terminal** —
la signature exacte du dépôt.

> **Règle pour cet outil** : ne jamais afficher `pending` sans croiser
> `crop_status`. Un `pending` dont le `crop_status` vaut `zero_crops` est un
> **échec**, pas une attente.

## Comment on vérifie qu'il marche

- La somme des plaques + la somme des drops = la plaque précédente. **À chaque
  transition, sans exception.** Un entonnoir qui ne boucle pas cache une
  catégorie ; c'est le seul test qui compte vraiment.
- Le total de la dernière plaque, agrégé sur tous les runs, doit égaler
  `SELECT COUNT(*) FROM dino_class_references WHERE method='fps'` → **824**.
- Le run du 2026-08-16 doit reproduire sa ligne connue : 740 appels → 801 raws →
  661 crops → 62 validés → **50 ancres**.

## Ce que cet outil n'est pas

- **Ce n'est pas le bench du theme-matcher.** `/bench` note contre un gold
  humain et calcule précision/rappel. Ici il n'y a pas de vérité terrain : on
  compte ce que le pipeline a fait, pas s'il a eu raison.
- **Ce n'est pas une liste de travail.** Il diagnostique. Le travail est en O2.
