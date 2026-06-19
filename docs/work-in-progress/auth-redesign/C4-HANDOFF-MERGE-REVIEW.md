# C4 — Absorption `review_service` dans `eurio-api`

> **But (1 phrase)** : déplacer les routes de `ml/review_service/` dans
> `ml/serving/` (sous des routers FastAPI préfixés `/review/...`), avec la
> nouvelle auth (Principal/scopes), pour qu'il n'y ait plus qu'une seule API
> sur le VPS.
>
> **Ne fait PAS** : décommissionner le container `eurio-review` (ça se fait au
> cutover C9). Le code legacy reste en place tant que C9 n'a pas eu lieu.
> Ne pas non plus toucher au front `admin/packages/review-admin` (C6).

## 0. Pré-requis

- C2 ✅ — `Principal`, scopes opérationnels.
- C3 ✅ (recommandé) — pour pouvoir tester avec des tokens propres.
- Branche : `auth-redesign-c4`.

## 1. Inventaire des routes existantes

Source : `ml/review_service/routes_*.py`. À porter vers `ml/serving/review_routes.py` (ou un sous-package `ml/serving/review/`).

| Route legacy | Méthode | Module | Nouveau préfixe | Scope nouveau |
|---|---|---|---|---|
| `/auth` | POST | `routes_reviewer.py` | **supprimé** | (remplacé par OIDC C2) |
| `/me` (reviewer) | GET | `routes_reviewer.py` | **supprimé** | (remplacé par `/me` C2) |
| `/me/items` | GET | `routes_reviewer.py` | `/review/me/items` | `review:read` |
| `/items/{id}/decide` | POST | `routes_reviewer.py` | `/review/items/{id}/decide` | `review:write` |
| `/items/{id}/skip` | POST | `routes_reviewer.py` | `/review/items/{id}/skip` | `review:write` |
| `/claim` | POST | `routes_reviewer.py` | `/review/claim` | `review:write` |
| `/me/stats` | GET | `routes_reviewer.py` | `/review/me/stats` | `review:read` |
| `/reviewers` | GET/POST | `routes_admin_reviewers.py` | **supprimé** | (remplacé par `/users` C2) |
| `/reviewers/{token}` | DELETE | `routes_admin_reviewers.py` | **supprimé** | (idem) |
| `/flow` | GET | `routes_admin.py` | `/review/flow` | `review:read` |
| `/publish` | POST | `routes_admin.py` | `/review/publish` | `review:write` |
| `/decisions` | GET | `routes_admin.py` | `/review/decisions` | `review:read` |
| `/decisions/ack` | POST | `routes_admin.py` | `/review/decisions/ack` | `review:write` |
| `/health` | GET | `app.py` | déjà sur `eurio-api` (`/healthz`) | — |

## 2. Migration du modèle

`review.db` existant contient :
- `items` (queue de review)
- `decisions` (historique)
- `reviewers` (tokens reviewers — **legacy auth**, sera supprimé)

Décision (à valider) : **on garde `review.db` séparé** de `eurio.db` (volumes
différents, bind-mount du legacy `infra/review/data` vers le nouveau container
ou copie). Raison : pas de couplage transactionnel entre la queue de review et
le canonique. C'est une décision **réversible** en C9 si on veut tout fusionner.

> **OQ5 (DESIGN.md §11)** — `review.db` à conserver tel quel ou à fusionner ?
> Si conservation : monter le volume actuel `infra/review/data` dans le
> container `eurio-api` en `/var/lib/eurio/review.db`. Si fusion : script SQL
> `INSERT INTO eurio.db FROM review.db`. **Recommandation** : conservation tant
> qu'on n'a pas une raison concrète de fusionner.

La table `reviewers` est **abandonnée** : les identités viennent de Authentik.
Les liens `decisions.reviewer_token` → mapper sur `users.id` lors d'une
migration data (script ponctuel : pour chaque `reviewer_token` historique,
demander à l'opérateur l'email correspondant et créer la correspondance).

## 3. Réutilisation du code

- `ml/review_service/db.py`, `meta.py`, `reviewers.py` → la logique métier
  utile (queue, decisions, publish) est portée. La logique auth (`auth.py`)
  est jetée.
- Les helpers `claim()`, `decide()`, `skip()`, `publish()` deviennent des
  fonctions pures appelées par les nouveaux routers, avec `Principal` en
  paramètre.

## 4. Câblage

Dans `ml/serving/server_serve.py`, ajouter le router `review_routes` à la
liste des routers montés. Toutes les dépendances : `require_scope("review:...")`.

## 5. Critères d'acceptation

```bash
TOKEN=<token reviewer créé via C3>

# Read
curl -s -H "Authorization: Bearer $TOKEN" \
  https://eurio-api.musubi.dev/review/me/items | jq .

# Write (claim + decide)
curl -s -X POST -H "Authorization: Bearer $TOKEN" \
  https://eurio-api.musubi.dev/review/claim | jq .

# Un user reviewer ne peut PAS publish
curl -si -X POST -H "Authorization: Bearer $TOKEN" \
  https://eurio-api.musubi.dev/review/publish
# → 403

# Un admin/owner peut
ADMIN_TOKEN=<token owner>
curl -s -X POST -H "Authorization: Bearer $ADMIN_TOKEN" \
  https://eurio-api.musubi.dev/review/publish | jq .
```

Le container `eurio-review` legacy continue à tourner en parallèle pendant
ce chunk — pas de cutover ici.

## 6. Garde-fous

- **Ne pas modifier** `review.db` côté legacy pendant que le nouveau tourne en parallèle (split-brain).
- Pour la phase de test : pointer `eurio-api` sur une **copie** de `review.db` (snapshot), pas sur le fichier live. Cutover real en C9.
- Conserver `routes_*.py` legacy non touchés dans `ml/review_service/` — leur suppression est en C9.

## 7. Résumé à produire

```
## C4 — résumé absorption review_service

- Branche / commits : <…>
- Routes portées : <liste>
- Routes supprimées : <liste>
- review.db : conservé séparé / fusionné dans eurio.db (préciser)
- Migration data decisions.reviewer_token → users.id : faite / différée
- Tests scopés (reviewer can't publish, etc.) : OK / KO
- Container eurio-review legacy : toujours up OUI/NON
- Déviations vs DESIGN.md : <…>
```
