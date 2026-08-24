# Constat — faire reviewer des amis à distance

> Mesuré le 2026-08-23 sur `ml/state/eurio.replica.db`. Chaque chiffre porte sa
> requête : sans elle il est irreproductible, donc inutilisable.

## Le problème

Raphaël ne tient pas seul le volume de review. Il veut que des amis non-techniques
l'aident depuis leur propre ordinateur.

```sql
SELECT status, count(*) FROM review_queue GROUP BY 1;
-- done|11510   open|9579   skipped|134
```

Attention : ces lignes comptent la table brute. Celles qui ont encore un `image_asset`
— les seules affichables — sont moins nombreuses (`JOIN image_assets` : 6 397 done,
**6 356 open**, 70 skipped). C'est 6 356 que l'écran affiche comme « LEFT ».

**Le travail délégué, ce sont trois gestes, pas un** : valider le cadrage, le
réajuster si besoin, trancher l'identité. Un ami qui ne recadre pas ne fait gagner
que la moitié du travail — et le recadrage n'est pas marginal :

```sql
SELECT detection_method, count(*) FROM image_assets GROUP BY 1 ORDER BY 2 DESC;
-- yolo+hough+rimrefine|6738  yolo+hough+polish+rimrefine|2672
-- manual|2448   score_recover|1418   ...   manual_add|13
```

**18,4 %** des crops (2 448 + 13 sur 13 390) ont été recadrés à la main.

## Ce qui existe déjà — trois piles pour le même geste

C'est la découverte de l'exploration : le back est écrit, en triple.

| Pile | Où | Auth | État |
|---|---|---|---|
| `ml/review_service/` + `admin/packages/review/` | `eurio-review.musubi.dev` (`infra/review`) | token dans l'URL (`?u=Paolo42`) | **en service**, front standalone |
| `ml/serving/review_routes.py` (`/review/claim`, `/review/flow`…) | monté sur `eurio-api.musubi.dev` | OIDC + scopes | **livré, sans aucun front** |
| `ml/serving/review_queue/` (`/review-queue/*`) | `eurio-api.musubi.dev` | OIDC + `review:write` | **livré, c'est ce que `studio-local` utilise** |

Le chantier [`collaborative-review/`](../../archive/collaborative-review/) (juin 2026) avait posé
le problème, l'avait implémenté et testé E2E, puis l'avait différé — c'est le chunk
**K2** de [`auth-redesign/ROADMAP.md`](../../archive/auth-redesign/ROADMAP.md), encore ⬜.

Le rôle existe aussi (`ml/serving/auth_principal.py:60`) :

```python
# état AVANT ce chantier
"reviewer": {"coins:read", "review:read", "review:write", "lab:read", "tokens:manage_own"}
```

(Le lot 4 lui retire `tokens:manage_own` — un ami s'authentifie par cookie, il n'a aucun
usage d'un PAT — et ajoute `review:arbitrate` à `owner`/`admin` seulement, cf. D7.)

## Pourquoi le tampon `review.db` n'a plus lieu d'être

Les deux premières piles reposent sur un tampon `review.db` alimenté par un pont
`publish` / `reconcile` (`ml/review/publish_cli.py`). Il a été conçu quand `eurio.db`
vivait **derrière un lease sur le Mac** : il fallait un endroit toujours allumé où
écrire.

Depuis la Direction A, le canonique **est** sur le VPS. Le tampon recopie donc la
donnée d'un serveur vers lui-même, avec une désynchronisation possible à chaque
aller-retour. On le supprime : les amis écrivent directement le canonique.

## Les trois blocages réels

### 1. Les images sont mortes à distance

`crop_url` est un chemin relatif (`repository.py:407`, `:790`, `:1632`) que le front
préfixe par l'API ML locale :

```ts
// useReviewApi.ts:208
function promoteUrl(url: string): string {
  if (!url) return url
  return url.startsWith('http') ? url : `${ML_API}${url}`   // ML_API = 127.0.0.1:8042
}
```

Hors du Mac, toutes les images sont cassées. Or `eurio-api` sait déjà signer MinIO —
il le fait dans `review_routes.py:61`. C'est le blocage le plus bête et le plus
bloquant : rien d'autre n'est testable tant qu'il tient.

### 2. Les décisions sont anonymes

```python
# serving/review_queue/writes.py:122, :215, :239
decided_by = 'admin',   # littéral — le `principal` est reçu dans la signature puis jeté
```

```sql
SELECT decided_by, count(*) FROM review_queue WHERE decided_by IS NOT NULL GROUP BY 1;
-- admin|3809   pipeline|2156   auto_dino|235   human|68   vision_gate|51   consensus|1
```

3 809 décisions humaines, toutes anonymes. Savoir « qui a validé quoi » est
aujourd'hui impossible — pas par manque de vue, par littéral dans le code.

Et le circuit d'arbitrage prévu pour ça n'a jamais servi :

```sql
SELECT count(*) FROM peer_review_decisions;   -- 0
```

### 3. Le recadrage — un faux problème

`cv2` est absent de l'image VPS, donc `manual-crop` n'y tourne pas. Mais en lisant
`crop_edit.py` et `normalize_snap.py`, le crop se décompose en trois, et **une seule
partie est lourde** :

| Étape | Nature | Où c'en est |
|---|---|---|
| **Détecter** le cercle | `cv2.HoughCircles` — vrai CV | **déjà persisté** : `detections_json` sur 15 040 / 16 792 `source_images` (89,6 %), via `ml:backfill-detections` |
| **Dessiner / ajuster** | interaction | **déjà dans le navigateur** (`CircleCropEditor.vue`) — le payload est `{cx, cy, r}`, trois flottants |
| **Appliquer** | crop, masque circulaire, resize 224 `INTER_AREA`, PNG, phash, MinIO | `cv2` n'y est **qu'une bibliothèque d'images**. Aucun ML |

`cv2` a été exclu de l'image lean par association avec torch — le Dockerfile dit « PAS
de torch/cv2/ultralytics », une seule phrase pour trois raisons différentes. Le seul
vrai lourd est le **ré-encodage DINO** après recadrage (torch), et il est déjà traité
en *best-effort* dans le code.

Même constat pour les suggestions DINO, classées « lourdes » à cause d'un fallback qui
encode à la demande. La mesure doit porter sur la clé EXACTE que lisent les suggestions
(`2eur_all` / `dinov2-vitl14`, cf. `shared/verdict_scope.py`) — compter « une prédiction
quelconque » ne prouve rien, puisque la banque du verdict (`2eur_commemo` / `vits14`)
est une autre table logique :

```sql
SELECT rq.status, count(*) AS items,
       sum(CASE WHEN sug.asset_id IS NULL THEN 1 ELSE 0 END) AS sans_suggestions,
       sum(CASE WHEN ver.asset_id IS NULL THEN 1 ELSE 0 END) AS sans_verdict
  FROM review_queue rq
  JOIN image_assets a ON a.id = rq.image_asset_id
  LEFT JOIN image_asset_dino_predictions sug ON sug.asset_id = rq.image_asset_id
        AND sug.encoder_version = 'dinov2-vitl14' AND sug.anchors_kind = '2eur_all'
  LEFT JOIN image_asset_dino_predictions ver ON ver.asset_id = rq.image_asset_id
        AND ver.encoder_version = 'dinov2-vits14' AND ver.anchors_kind = '2eur_commemo'
 GROUP BY rq.status;
-- done    | 6397 | 0 | 1139
-- open    | 6356 | 0 | 3278
-- skipped |   70 | 0 |    6
```

**Zéro crop sans prédiction de SUGGESTIONS sur les 12 823** qui ont encore un
`image_asset`. Le chemin lourd ne s'allume jamais → la route est portable en lecture
pure sur l'image lean.

> ⚠️ Deux pièges que cette requête corrige, et qu'une première version de ce document
> avait tous les deux :
> 1. **La jointure sur `image_assets`.** Sans elle on compte 21 223 lignes de
>    `review_queue`, dont ~8 400 n'ont plus d'`image_asset` — elles ne sont ni
>    affichables ni reviewables. Le chiffre qui compte est 12 823.
> 2. **La clé de la banque.** La banque du VERDICT, elle, a de vrais trous
>    (3 278 crops ouverts sans prédiction) — ce n'est pas la même chose et ça ne
>    concerne pas les suggestions.

Vérifié en bout de chaîne le 2026-08-23 : `GET /review-queue/{id}/dino-suggestions`
répond 200 avec `duration_ms: 0` et un `computed_at` antérieur — la réponse vient de la
base, aucun encodage n'a eu lieu.

### Corollaire : ce qui doit rester chez Raphaël

Rien, sauf le ré-encodage DINO. Et une règle non négociable :

> **Le navigateur envoie trois flottants ; le serveur possède les pixels.**

`_crop_mask_resize_float` produit le format qui nourrit l'entraînement (le code dit
« Format IDENTIQUE à la prod », et une variante entière est maintenue « bit-for-bit »
pour le port Kotlin). Un crop fait en Canvas rééchantillonnerait autrement
qu'`INTER_AREA`, et différemment selon le navigateur et le GPU : une dérive invisible
du jeu d'entraînement, jamais signalée. Cf. skill `eurio-verify`.

## Le coût réseau, chiffré

Mesuré sur `~/.cache/eurio` (échantillon de 500 fichiers par bucket) :

| | moyenne | médiane | p90 |
|---|---|---|---|
| crop 224px PNG | **97 Ko** | 99 Ko | 101 Ko |
| raw source | **499 Ko** | 536 Ko | 944 Ko |

Un lot de 40 pièces = **~3,9 Mo** de crops, servis en URLs MinIO présignées, en
parallèle, cachés par le navigateur. Le raw n'est chargé qu'à l'ouverture de
l'éditeur de cercle, un à la fois.

**Conclusion : pas de base locale, pas de PWA.** La réplique SQLite (186 Mo) est un
outil de process Python sur le Mac, pas un cache navigateur ; le front tape déjà
l'API en HTTP. Une PWA n'apporterait que l'offline, dont personne n'a besoin ici.

## DINO dans le navigateur : écarté, avec les chiffres

La banque servie est téléchargeable — `1909 × 1024` float32 = **7,8 Mo**. Mais elle est
encodée en **vitl14** (~300 M paramètres), hors budget navigateur. Le modèle qui
passerait, `vits14` (~21 M), est l'encodeur faible : le repo mesure **77,8 %** contre
**41,6-45,5 %** sur ses propres bancs. On servirait aux amis un DINO deux fois moins
bon. Écarté.

## Ce que l'arbitrage coûtera vraiment

```sql
SELECT count(*), sum(p.top1_eurio_id = rq.decided_eurio_id),
                sum(p.top1_country_eurio_id = rq.decided_eurio_id)
  FROM review_queue rq JOIN image_asset_dino_predictions p
    ON p.asset_id = rq.image_asset_id
 WHERE rq.status='done' AND rq.decided_eurio_id IS NOT NULL;
-- 5309 | 3323 | 3571
```

Sur les décisions humaines passées, DINO top-1 tombe juste **62,6 %** du temps
(**67,3 %** avec le re-rank pays). Donc quand un ami rejoint DINO, il y a **deux
jugements indépendants concordants** — approuvables en lot. Seul le tiers restant, où
l'humain contredit la machine, mérite vraiment l'œil de Raphaël.

C'est ce qui rend la passe d'arbitrage mensuelle tenable, et c'est aussi pourquoi la
vue bulk doit trier les **désaccords en tête** (cf. [`DECISIONS.md`](DECISIONS.md) D8).

## À lire ensuite

- [`DECISIONS.md`](DECISIONS.md) — ce qu'on a tranché et ce que ça écarte
- [`ROADMAP.md`](ROADMAP.md) — les lots
- [`NETTOYAGE.md`](NETTOYAGE.md) — l'inventaire de ce qui meurt à la fin
