---
name: eurio-vps-deploy
description: Déployer et vérifier le canonique Eurio sur le VPS (eurio-api, eurio-admin, MinIO). À consulter avant tout `docker compose up` sur le VPS, ou quand une route répond 404/401/500 en prod alors qu'elle marche en local.
---

# Déployer et vérifier le VPS

Accès : `ssh serverOimNixDontpanic`. Le repo y vit dans `/opt/eurio`.

## Déployer

```bash
ssh serverOimNixDontpanic
cd /opt/eurio && git pull
cd infra/eurio-api && sops exec-env ../../secrets/dev.env "docker compose up -d --build"
```

Le front hébergé est un conteneur séparé, même schéma :
`cd /opt/eurio/infra/eurio-admin && sops exec-env ../../secrets/dev.env "docker compose up -d --build"`.

⚠️ **Le VPS pousse aussi des commits.** Une autre session y travaille parfois :
`git push` peut être rejeté. `git fetch` + rebase, ne force jamais.

⚠️ **`infra/minio/bootstrap.sh` fait un `docker compose up -d` sur MinIO**
(étape 3). MinIO porte `eurio-api`, `eurio-review` et le miroir de backup :
pour créer un bucket, préfère trois `docker exec … mc` ciblés plutôt que de
recréer le conteneur.

## Vérifier — l'ordre compte

**1. Quels routeurs sont montés ?** C'est le contrôle le plus informatif :

```bash
docker logs eurio-api 2>&1 | grep -E "routers (montés|skippés)" | tail -2
```

L'image lean **ne contient pas** `cv2`, `PIL`, ni `ml/sources`. Tout module qui
les importe **au niveau module** fait skipper son routeur **entier**. Corollaire :
un endpoint SQL pur peut être absent de la prod juste parce qu'il cohabite avec
un import lourd → gate les **routes** lourdes, pas le fichier
(cf. `serving/coin_assets_routes.py`, `CROP_EDIT_AVAILABLE`).

Même piège côté fonctions : un `from sources.market… import` **dans** un
handler passe les tests locaux et lève `ModuleNotFoundError` à la requête en prod.

⛔ **Un routeur « skippé » ne veut pas dire que son préfixe est absent.** Les noms
de `_CANDIDATES` sont des étiquettes, pas des préfixes d'URL — et deux modules
distincts peuvent servir le **même** préfixe. Mesuré le 2026-08-17 :

```
WARNING routers skippés : ["review_queue (ModuleNotFoundError: No module named 'cv2')"]
$ curl .../review-queue/stats   →  HTTP 200 {"n_pending":6918,...}
```

Il n'y a pas de contradiction : le skippé est `review.review_queue_routes`
(lourd — `detect`, `manual-crop`, `crop-edit-context`, `requalify-lot/batch`),
tandis que `serving.review_queue` est importé **au niveau module** dans
`server_serve.py` et sert `/review-queue/*` sans cv2. Ce que la prod perd, ce
sont les **routes lourdes** de ce préfixe, pas le préfixe.

Donc : le log dit ce qui a échoué à l'import, **l'OpenAPI dit ce qui est
servi**. Lis les deux, dans cet ordre, et ne conclus jamais du premier seul.

**2. L'OpenAPI fait autorité, pas le code HTTP.** Un middleware d'auth global
répond **401 avant le routage** : une route inexistante répond 401 comme les
autres. Ne conclus jamais d'un 401/404 nu.

```bash
curl -s https://eurio-api.musubi.dev/openapi.json | tr ',' '\n' | grep -oE '"/coins/[^"]*"' | sort -u
```

**3. L'ordre de montage des routeurs.** FastAPI résout dans l'ordre
d'enregistrement. `coins_routes` déclare `GET /coins/{eurio_id}` : monté avant
`coin_assets`, il avale `/coins/enrichment-counts` et répond
`"coin enrichment-counts not found"` — un 404 **crédible**, qui ressemble à une
route absente. `coin_assets` doit rester **avant** `coins` dans `_CANDIDATES`
(`serving/server_serve.py`), comme dans `serving/server.py`. Verrouillé par
`tests/test_serve_router_order.py`.

**4. Tester avec un vrai PAT** (les 401 ne disent rien sinon) :

```bash
sops exec-env secrets/dev.env 'curl -s -o /dev/null -w "%{http_code}\n" \
  -H "Authorization: Bearer $EURIO_API_TOKEN" "$EURIO_API_URL/coins/enrichment-counts"'
```

## URLs signées MinIO — le piège muet

Le conteneur parle à MinIO par le réseau Docker (`MINIO_ENDPOINT=eurio-minio:9000`).
Une URL présignée avec ce client porte un hôte **que le navigateur ne résout pas** :
l'API répond 200 avec une URL parfaitement formée, et seule l'image ne s'affiche
pas. D'où `MINIO_PUBLIC_ENDPOINT=eurio-s3.musubi.dev` dans le compose, utilisé par
`shared/storage._public_client()`.

Vérifier de bout en bout (depuis l'extérieur, sans en-tête d'auth) :

```bash
curl -s -o /tmp/c.png -w "%{http_code} %{size_download}\n" "<file_url renvoyé par l'API>"
file /tmp/c.png     # doit dire « PNG image data »
```

## Déploiements couplés

Front et backend peuvent devoir partir ensemble (ex. la galerie d'enrichissement
bascule sur le canonique : sans le backend redéployé, le front prend des 404).
**Backend d'abord**, toujours.

## Inspecter le canonique

```bash
ssh serverOimNixDontpanic 'docker exec eurio-api python -c "
import sqlite3
c=sqlite3.connect(\"file:/var/lib/eurio/eurio.db?mode=ro\",uri=True)
print(c.execute(\"select count(*) from experiment_cohorts\").fetchone())"'
```
