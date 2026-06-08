# infra/review — Eurio Review Service (VPS)

Service FastAPI (toujours allumé) + front statique Vue, déployé en
**docker-compose + Traefik** sur le VPS. Sous-domaine HTTPS :
`https://eurio-review.musubi.dev`.

> Spec produit & flow d'usage : voir
> `docs/work-in-progress/collaborative-review/09-vps-deploy.md`.

## Layout

```
infra/review/
├── docker-compose.yml      # service `review` + labels Traefik
├── Dockerfile              # multi-stage : node (front) → python:3.12-slim
├── entrypoint.sh           # lit /run/secrets/* → env vars, exec uvicorn
├── data/                   # bind-mount review.db (gitignoré)
└── secrets/                # un fichier par secret, montés en RO (gitignoré)
    ├── review_admin_token         (à créer)
    ├── review_session_secret      (à créer)
    ├── minio_access_key           (à créer)
    └── minio_secret_key           (à créer)
```

Les `*.example` sont committés pour mémo ; les fichiers réels (sans suffixe)
sont créés à la main sur le VPS, jamais committés.

## Bootstrap initial (VPS)

```bash
cd /opt/eurio/infra/review

# 1. Créer les secrets (long, random — au moins 32 octets chacun).
umask 077
openssl rand -hex 32 > secrets/review_admin_token
openssl rand -hex 32 > secrets/review_session_secret
# Les deux clés MinIO sont celles d'un user avec READ sur enrichment-crops :
$EDITOR secrets/minio_access_key
$EDITOR secrets/minio_secret_key

# 2. Build + start.
docker compose up -d --build

# 3. Vérifier.
docker compose logs -f review        # uvicorn running on 0.0.0.0:8048
curl https://eurio-review.musubi.dev/health
# → {"status":"ok"}
```

> `REVIEW_ADMIN_TOKEN` doit être **identique** côté Mac (env des tasks
> `ml:review:publish` / `ml:review:reconcile`). Note-le dans le password
> manager après génération.

## Seed des reviewers

Le service tourne en conteneur — on appelle le CLI dedans :

```bash
docker compose exec review python -m review_service.manage \
    add-reviewer --token Paolo42 --name Paolo

docker compose exec review python -m review_service.manage list-reviewers
```

Lien à transmettre à chaque ami :
`https://eurio-review.musubi.dev/?u=Paolo42`.

## Mise à jour (déploiement d'une nouvelle version)

```bash
cd /opt/eurio
git pull
cd infra/review
docker compose up -d --build
```

Le rebuild est rapide tant que `pyproject` et `package.json` ne bougent pas
(layer cache). `review.db` est en bind-mount → survit au redéploiement.

## Rotation des secrets

```bash
cd /opt/eurio/infra/review
openssl rand -hex 32 > secrets/review_session_secret   # invalide toutes les sessions
docker compose restart review
```

`REVIEW_ADMIN_TOKEN` se rotate de la même façon, **mais** il faut mettre à
jour la valeur côté Mac (env des tasks) en même temps, sinon publish/reconcile
casse.

## Pourquoi pas la stack ml complète dans l'image ?

`ml/pyproject.toml` tire torch + ultralytics + opencv (~5 Go). Le service
review n'a besoin que de `fastapi`, `uvicorn`, `boto3`. Le Dockerfile
installe ces trois deps explicitement et copie SEULEMENT
`ml/review_service/` + `ml/shared/storage/` (utilisé pour générer les URLs
présignées MinIO). Image finale ~200 Mo.

## Pourquoi pas systemd ?

L'historique : `docs/work-in-progress/collaborative-review/09-vps-deploy.md`
décrivait initialement un service systemd + Caddy. On a basculé sur
docker-compose + Traefik pour homogénéiser avec `infra/minio/` (même
pattern de secrets fichiers, même reverse-proxy déjà déployé).
