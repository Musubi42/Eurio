# 09 — Handoff déploiement VPS

> **Doc à confier à une session Claude Code sur le VPS** (façon
> `docs/refacto-ml/chunk6-vps-minio.md`). Le code est déjà écrit et testé en
> local ; ici on déploie le **service review** (toujours allumé) + le **front**.

## Ce qu'on déploie

- `ml/review_service/` — FastAPI + `review.db` (SQLite WAL), n'ouvre QUE review.db.
- `admin/packages/review/` — front statique (build Vite), servi par le service.

Le service est **indépendant du lease eurio.db** : il tourne en continu. Le pont
`publish`/`reconcile` (côté Mac, lease requis) alimente/draine `review.db`.

**Mode de déploiement : docker-compose + Traefik**, même pattern que
`infra/minio/` (sous-domaine HTTPS, secrets en fichiers, bind-mount data).

## Pré-requis sur le VPS

- Docker + Compose v2 installés, network `traefik` déjà créé (partagé avec
  `infra/minio/` et le reste de la stack `musubi.dev`).
- DNS : `eurio-review.musubi.dev` → IP du VPS (sous-domaine déjà créé).
- Accès MinIO : une access/secret key avec **lecture** sur le bucket
  `enrichment-crops` (crops servis aux amis via URL présignée).

## Layout `infra/review/`

```
infra/review/
├── docker-compose.yml      # service `review` + labels Traefik
├── Dockerfile              # multi-stage : node (front) → python:3.12-slim
├── entrypoint.sh           # lit /run/secrets/* → env vars, exec uvicorn
├── data/                   # bind-mount review.db (gitignoré)
└── secrets/                # un fichier par secret, montés en RO (gitignoré)
    ├── review_admin_token
    ├── review_session_secret
    ├── minio_access_key
    └── minio_secret_key
```

Le bind-mount `./data` est persistant : `review.db` survit aux rebuilds et
redéploiements.

## Variables d'environnement & secrets

Posées par `docker-compose.yml` (env publique) et `entrypoint.sh` (secrets
fichiers) :

| Variable | Source | Rôle |
|---|---|---|
| `REVIEW_DB_PATH` | env compose | `/var/lib/eurio/review.db` (dans le conteneur) |
| `REVIEW_CORS_ORIGINS` | env compose | `https://eurio-review.musubi.dev` |
| `REVIEW_COOKIE_SECURE` | env compose | `true` (HTTPS only) |
| `MINIO_ENDPOINT` | env compose | `eurio-s3.musubi.dev` |
| `MINIO_USE_SSL` | env compose | `true` |
| `REVIEW_ADMIN_TOKEN` | `secrets/review_admin_token` | secret partagé pour `/admin/*` (publish/reconcile) |
| `REVIEW_SESSION_SECRET` | `secrets/review_session_secret` | clé HMAC des cookies de session |
| `MINIO_ACCESS_KEY` | `secrets/minio_access_key` | accès crops |
| `MINIO_SECRET_KEY` | `secrets/minio_secret_key` | accès crops |

> `REVIEW_ADMIN_TOKEN` doit être **identique** côté Mac (env des tasks
> `ml:review:publish` / `ml:review:reconcile`).

## 1. Bootstrap

```bash
cd /opt/eurio/infra/review

# Secrets — un fichier par secret, 0600.
umask 077
openssl rand -hex 32 > secrets/review_admin_token
openssl rand -hex 32 > secrets/review_session_secret
$EDITOR secrets/minio_access_key       # clé MinIO avec READ sur enrichment-crops
$EDITOR secrets/minio_secret_key

# Build + start.
docker compose up -d --build

# Vérifier.
docker compose logs -f review
curl https://eurio-review.musubi.dev/health
# → {"status":"ok"}
```

Le build est multi-stage :
- Stage `front-builder` (node:20-alpine) → `pnpm install --filter
  eurio-review-front --frozen-lockfile && pnpm build` ;
- Stage `runtime` (python:3.12-slim) → installe `fastapi`, `uvicorn`, `boto3`
  (pas la stack ml complète), copie `ml/review_service/`, `ml/shared/storage/`,
  et le `dist/` du front.

Image finale ~200 Mo.

## 2. Reverse-proxy

Géré par les labels Traefik du conteneur — pas de bloc nginx/Caddy à éditer
à la main :

```yaml
- traefik.http.routers.eurio-review.rule=Host(`eurio-review.musubi.dev`)
- traefik.http.routers.eurio-review.entrypoints=websecure
- traefik.http.routers.eurio-review.tls=true
- traefik.http.routers.eurio-review.tls.certresolver=letsencryptresolver
- traefik.http.services.eurio-review.loadbalancer.server.port=8048
```

Le cert Let's Encrypt est délivré automatiquement par le `letsencryptresolver`
de l'instance Traefik existante. HTTPS obligatoire pour que les cookies
`Secure` posés par FastAPI fonctionnent.

## 3. Seed des reviewers

Le CLI vit dans le conteneur :

```bash
docker compose exec review python -m review_service.manage \
    add-reviewer --token Paolo42 --name Paolo

docker compose exec review python -m review_service.manage list-reviewers
```

Lien à transmettre à chaque ami : `https://eurio-review.musubi.dev/?u=Paolo42`.

## 4. Alimenter & drainer (depuis le Mac, lease eurio.db détenu)

```bash
export REVIEW_SERVICE_URL=https://eurio-review.musubi.dev
export REVIEW_ADMIN_TOKEN=<même secret que le service>
go-task ml:db:acquire
go-task ml:review:publish -- --limit 200     # pousse des items à reviewer
# … les amis reviewent …
go-task ml:review:reconcile                   # tire leurs décisions en staging
go-task ml:db:release
```

Puis arbitrer dans le console admin : `/review/peer-arbitration`.

## 5. Mise à jour

```bash
cd /opt/eurio && git pull
cd infra/review && docker compose up -d --build
```

`review.db` est en bind-mount → survit. Layer cache Docker → rebuild rapide
tant que `pyproject` et `package.json` ne bougent pas.

## Checklist à rendre

- [ ] `curl https://eurio-review.musubi.dev/health` → `{"status":"ok"}`
- [ ] conteneur `eurio-review` `restart=unless-stopped` + `Up`, survit au reboot
- [ ] Traefik route bien le sous-domaine, cert Let's Encrypt OK, cookies `Secure` posés
- [ ] au moins un reviewer seedé (`list-reviewers`)
- [ ] `?u=Paolo42` connecte ; URL nue → modale code
- [ ] crop d'un item s'affiche (URL présignée MinIO joignable)
- [ ] depuis le Mac : `review:publish` puis `review:reconcile` round-trip OK
- [ ] `infra/review/data/review.db` présent et persistant entre rebuilds

## Ce qui n'est PAS ici

- ❌ Backup de `review.db` : c'est un tampon transient (la vérité reste eurio.db).
  Un snapshot périodique est un bonus, pas une nécessité.
- ❌ Auth forte : volontairement minimale (cf. `04-auth.md`).
- ❌ Stack ml complète dans l'image : le service ne fait que servir review.db
  et générer des URLs présignées MinIO. Image minimale (fastapi/uvicorn/boto3),
  ~200 Mo.
