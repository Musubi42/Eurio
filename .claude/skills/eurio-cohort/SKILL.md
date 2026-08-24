---
name: eurio-cohort
description: Composer une cohorte d'entraînement et la faire passer le préflight — maille classe, gel irréversible, expansion design_group. À lire avant de créer ou modifier une cohorte, ou quand la création d'itération répond 409.
---

# Composer une cohorte

> Une cohorte est **une liste d'`eurio_id`** dans un champ JSON. Tout le reste —
> ce qui sera réellement entraîné, ce qui bloque, ce qui est visible d'où — est
> contre-intuitif. Cette skill couvre la composition ; l'entraînement lui-même
> est dans **`eurio-run-local`**, la promotion dans **`eurio-promote`**.

## Les trois faits qui font échouer tout le reste

### 1. Tu choisis des PIÈCES, le bake entraîne des CLASSES — et il en ajoute

La maille de tout le pipeline est `COALESCE(design_group_id, eurio_id)`. Le bake
étend la cohorte à **tous les membres des groupes** représentés, y compris ceux
que tu n'as pas choisis.

Mesuré le 2026-08-16 sur la cohorte `ab28928bcdc2` (« owned-ready-24 ») :

| | |
|---|---|
| pièces dans la cohorte | 27 |
| **pièces réellement bakées** | **61** — dont **56 % hors cohorte** |
| classes | 24 |
| samples produits | 5051 |

C'est le design, pas un bug. Conséquences pratiques : le temps de bake et le
volume ne se déduisent pas du nombre de pièces choisies, et **une pièce pauvre
peut entrer par la porte de derrière** parce qu'une sœur de groupe est dans la
cohorte.

### 2. Le gel est irréversible, et il arrive plus tôt qu'on croit

Créer une **itération** gèle la cohorte (`draft → frozen`, `frozen_at` stampé).
Les `eurio_ids` ne bougent plus — c'est ce qui rend les benchmarks comparables.

Le préflight tombe **avant** le gel (409), donc un refus ne gèle rien. Mais dès
qu'une itération est créée, la composition est figée. Pour changer d'avis :
`POST /lab/cohorts/{id}/clone`.

### 3. Le préflight refuse sur `warn` autant que sur `block`

`lab_routes.py::_require_classes_ready` fait `not_ready = blocked + warned`.

| Verdict | Condition | Défaut |
|---|---|---|
| `block` | `seed < m_per_class` — total des sources réelles (Numista + eBay + réfs officielles) | 4 |
| `warn` | `n_ebay < MIN_REAL` — **seulement** les crops eBay | 10 (`store/funnel_constants.py`) |

Les deux rendent **409** à `POST /lab/cohorts/{id}/iterations`. Le **run**
d'entraînement, lui, ne s'arrête que sur `block`.

Mesure le verdict avant d'essayer, plutôt que de lire le 409 :

```bash
curl -s "http://127.0.0.1:8042/lab/cohorts/<cohort_id>/training-readiness" | python3 -m json.tool
# → { ready, n_classes, preflight: {...}, unresolved: [...] }
```

⚠️ **Une classe pauvre peut ne pas être la tienne.** Sur `mix-owned-42`, la
classe visée était en `warn` mais la cohorte était de toute façon bloquée par
`ee-2euro-standard-t1` en `block` dur, plus 9 autres `warn`. Enrichir une seule
classe n'aurait rien débloqué. Lis la liste entière.

Réparer un `warn` : **d'abord la review, pas le scrape** — cf.
`eurio-enrichment` §« Avant de scraper ».

⚠️ **Mesure la réserve de review sur `review_queue.status='open'`, jamais sur
`image_assets.needs_review`.** Les deux compteurs répondent à des questions
différentes et le second fait conclure à tort qu'il n'y a plus rien à trancher —
donc qu'un scrape est obligatoire. Mesuré le 2026-08-17, écart d'un facteur 60 :

```sql
select count(*) from review_queue rq
  join image_assets a  on a.id = rq.image_asset_id
  join source_images s on s.id = a.source_image_id
 where rq.status = 'open'
   and s.target_eurio_id in (select eurio_id from coins where design_group_id = ?);
```

| Classe | acceptés | manque | `needs_review` | **file ouverte** |
|---|---|---|---|---|
| `fr-2euro-standard-t1` | 5 | 5 | 0 | **66** (48 lot / 18 single) |
| `es-2euro-juan-carlos-i-t2` | 4 | 6 | 1 | **16** (9 lot / 7 single) |

## Où vit une cohorte, et ce qu'on peut en lire d'où

L'écriture passe par `serving/lab_writes.py` : sous le flip Direction A, elle va
**d'abord au canonique VPS**, et l'échec du VPS est l'échec de la requête (cf.
`eurio-data-writes`).

| Ce que tu veux | Où le lire |
|---|---|
| la liste des cohortes, au canonique | `GET /operations/cohorts` |
| **les membres d'une cohorte** | ⛔ **aucune route canonique** — voir ci-dessous |
| une cohorte en local (id **ou nom**) | `GET /lab/cohorts/{id_or_name}` sur `:8042` |
| le verdict de préflight | `GET /lab/cohorts/{id}/training-readiness` sur `:8042` |

### ⛔ Deux pièges de lecture, tous deux muets

> ✅ **CORRIGÉ — ce piège n'est plus actif. Conservé pour la trace du motif.**

`/operations/cohorts` renvoyait `n_members: 0` pour TOUTES les cohortes (mesuré le
2026-08-17) : le handler comptait `SELECT COUNT(*) FROM cohort_members`, une table
qui **existe et reste vide** — seul `scripts/migrate_canonical_schema.py` la
backfille, aucun writer ne la maintient. Le `COALESCE(…, 0)` transformait
l'absence en zéro plausible, et la page Operations affichait `0` partout.

**Depuis, `operations_routes.py:398` décode `experiment_cohorts.eurio_ids_json`
(`_n_members`)**, là où les membres vivent réellement ; `cohort_members` n'y
apparaît plus qu'en commentaire. Le motif, lui, reste à connaître : *un `COUNT`
sur une table qu'aucun writer ne remplit rend zéro, et zéro est plausible.*

Pour connaître les membres, lis la réplique (ou le canonique par SSH) :

```bash
sqlite3 -readonly ml/state/eurio.replica.db \
  "select id, name, status, eurio_ids_json from experiment_cohorts order by created_at desc;"
```

**`GET /lab/cohorts/{id}` répond 404 sur le VPS.** L'image lean ne monte pas les
routes lab — c'est normal, le lab est local par conception. Seule
`/lab/cohorts/{id}/training-crops` y existe. Ne conclus pas à une cohorte
absente : cf. `eurio-vps-deploy` §« un routeur skippé ne veut pas dire que le
préfixe est absent ».

## Composer

Le geste normal est le front : `/lab` → **Nouveau cohort**. En API :

| Geste | Route (`:8042`) |
|---|---|
| créer / lister | `POST` · `GET /lab/cohorts` |
| ajouter / retirer une pièce | `POST /lab/cohorts/{id}/coins` · `DELETE …/coins/{eurio_id}` |
| dupliquer (contourner un gel) | `POST /lab/cohorts/{id}/clone` |
| supprimer | `DELETE /lab/cohorts/{id}` — **propage au canonique** |
| simuler avant de geler | `POST /lab/cohorts/{id}/preview-iteration` |

Trouver des pièces entraînables :

```bash
sops exec-env secrets/dev.env 'curl -s -H "Authorization: Bearer $EURIO_API_TOKEN" \
  "$EURIO_API_URL/coins/enrichment-counts"' | python3 -c "
import json,sys; d=json.load(sys.stdin)
for k,v in sorted(d.items(), key=lambda kv:-kv[1])[:15]: print(f'{v:4d}  {k}')"
```

## Composer une cohorte d'UNION avec la production

Cas réel : promouvoir sans **perdre** de classes. La promotion **remplace**, elle
n'accumule pas (cf. `eurio-promote`) — toute classe absente de l'itération
disparaît de l'APK.

Établir ce que la production couvre aujourd'hui, à la maille classe :

```bash
python3 - <<'PY'
import json, sqlite3
emb = json.load(open('app-android/src/main/assets/data/coin_embeddings.json'))  # clés = numista_id
c = sqlite3.connect('file:ml/state/eurio.replica.db?mode=ro', uri=True)
q = ",".join("?" * len(emb))
rows = c.execute(f"select coalesce(design_group_id, eurio_id) from coins "
                 f"where cast(numista_id as text) in ({q})", [str(i) for i in emb]).fetchall()
print(len(emb), "embeddings →", len({r[0] for r in rows}), "classes")
PY
```

Mesuré le 2026-08-17 : **23 embeddings → 20 classes**. Une cohorte d'union doit
couvrir ces 20 **plus** les nouvelles. Attention au piège de cardinalité :
`coin_embeddings.json` est clé par `numista_id`, `model_meta.json` liste 17
classes sous des slugs périmés, et l'itération raisonne en `class_id`. Trois
cardinalités pour un même modèle — ne les compare jamais directement.

## Ce que cette skill ne couvre PAS

- Le bake, l'entraînement, le benchmark : **`eurio-run-local`** et
  `docs/architecture/parcours.md` §4.
- Nourrir une classe pauvre : **`eurio-enrichment`**, puis **`eurio-review`**.
- Où part l'écriture, et le flip : **`eurio-data-writes`**.
- Le détail du préflight : `ml/training/foundation/preflight.py` ; le gate de
  création : `ml/serving/lab_routes.py::_require_classes_ready`.
