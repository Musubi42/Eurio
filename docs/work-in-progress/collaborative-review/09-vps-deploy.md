# 09 — Handoff déploiement VPS

> **Doc à confier à une session Claude Code sur le VPS** (façon
> `docs/refacto-ml/chunk6-vps-minio.md`). Le code est déjà écrit et testé en
> local ; ici on déploie le **service review** (toujours allumé) + le **front**.

## Ce qu'on déploie

- `ml/review_service/` — FastAPI + `review.db` (SQLite WAL), n'ouvre QUE review.db.
- `admin/packages/review/` — front statique (build Vite), servi par le service.

Le service est **indépendant du lease eurio.db** : il tourne en continu. Le pont
`publish`/`reconcile` (côté Mac, lease requis) alimente/draine `review.db`.

## Pré-requis sur le VPS

- Le projet `ml/` déployable (venv ou conteneur) avec `fastapi`, `uvicorn`,
  `boto3` (déjà nécessaires pour le reste de ml).
- Accès MinIO (mêmes creds que la couche images) : `MINIO_ENDPOINT`,
  `MINIO_ACCESS_KEY`, `MINIO_SECRET_KEY`, `MINIO_USE_SSL` — la clé doit avoir
  **lecture** sur le bucket `enrichment-crops` (les crops servis aux amis via URL
  présignée).
- Node + pnpm pour builder le front (ou builder sur le Mac et copier `dist/`).

## Variables d'environnement (service)

| Variable | Rôle | Exemple |
|---|---|---|
| `REVIEW_DB_PATH` | chemin de review.db sur le VPS (persistant) | `/var/lib/eurio/review.db` |
| `REVIEW_ADMIN_TOKEN` | secret partagé pour `/admin/*` (publish/reconcile) | (aléatoire long) |
| `REVIEW_SESSION_SECRET` | clé HMAC des cookies de session | (aléatoire long) |
| `REVIEW_CORS_ORIGINS` | origine(s) du front en prod | `https://review.<domaine>` |
| `REVIEW_COOKIE_SECURE` | cookies en HTTPS only | `true` |
| `REVIEW_CLAIM_WINDOW` | taille de fenêtre de claim | `10` (défaut) |
| `REVIEW_LEASE_TTL_SECONDS` | visibility timeout des claims | `1800` (défaut) |
| `MINIO_*` | accès crops | cf. ci-dessus |

> `REVIEW_ADMIN_TOKEN` doit être **identique** côté Mac (env du `publish`/`reconcile`).

## 1. Build du front

Option A (sur le VPS) :
```bash
pnpm -C admin/packages/review install
VITE_REVIEW_API="https://review.<domaine>" pnpm -C admin/packages/review build
```
Option B (sur le Mac, puis rsync) : idem build, puis copier `dist/` sur le VPS.

Le service monte automatiquement `admin/packages/review/dist/` à la racine si le
dossier existe (cf. `ml/review_service/app.py`). Sinon il ne sert que l'API.

> `VITE_REVIEW_API` doit pointer vers l'URL **publique** du service (même origine
> que le front si servi par le service → on peut laisser vide / relatif si
> co-hébergé ; sinon mettre l'URL complète).

## 2. systemd unit

`/etc/systemd/system/eurio-review.service` :
```ini
[Unit]
Description=Eurio Review Service
After=network.target

[Service]
WorkingDirectory=/opt/eurio/ml
Environment=REVIEW_DB_PATH=/var/lib/eurio/review.db
Environment=REVIEW_ADMIN_TOKEN=__set_me__
Environment=REVIEW_SESSION_SECRET=__set_me__
Environment=REVIEW_CORS_ORIGINS=https://review.<domaine>
Environment=REVIEW_COOKIE_SECURE=true
Environment=MINIO_ENDPOINT=eurio-s3.musubi.dev
Environment=MINIO_ACCESS_KEY=__set_me__
Environment=MINIO_SECRET_KEY=__set_me__
Environment=MINIO_USE_SSL=true
ExecStart=/opt/eurio/ml/.venv/bin/uvicorn review_service.app:app --host 127.0.0.1 --port 8048
Restart=always
RestartSec=3

[Install]
WantedBy=multi-user.target
```
```bash
mkdir -p /var/lib/eurio
systemctl daemon-reload
systemctl enable --now eurio-review
systemctl status eurio-review
```

> Secrets : préférer un `EnvironmentFile=` chiffré plutôt que des `Environment=`
> en clair dans l'unit, selon la convention secrets du VPS.

## 3. Reverse-proxy (sous-domaine HTTPS)

Exemple Caddy :
```
review.<domaine> {
    reverse_proxy 127.0.0.1:8048
}
```
(ou bloc nginx équivalent avec `proxy_pass http://127.0.0.1:8048;` + en-têtes).
HTTPS obligatoire (cookies `Secure`).

## 4. Seed des reviewers

Un INSERT par ami (le token = identité **et** mot de passe) :
```bash
cd /opt/eurio/ml
REVIEW_DB_PATH=/var/lib/eurio/review.db .venv/bin/python -m review_service.manage \
  add-reviewer --token Paolo42 --name Paolo
.venv/bin/python -m review_service.manage list-reviewers
```
Puis transmettre à chaque ami son lien privé : `https://review.<domaine>/?u=Paolo42`.

## 5. Alimenter & drainer (depuis le Mac, lease eurio.db détenu)

```bash
export REVIEW_SERVICE_URL=https://review.<domaine>
export REVIEW_ADMIN_TOKEN=<même secret que le service>
go-task ml:db:acquire
go-task ml:review:publish -- --limit 200     # pousse des items à reviewer
# … les amis reviewent …
go-task ml:review:reconcile                   # tire leurs décisions en staging
go-task ml:db:release
```
Puis arbitrer dans le console admin : `/review/peer-arbitration`.

## Checklist à rendre

- [ ] `curl https://review.<domaine>/health` → `{"status":"ok"}`
- [ ] service systemd `enabled` + `active` (survit au reboot)
- [ ] reverse-proxy HTTPS OK, cookies `Secure` posés
- [ ] au moins un reviewer seedé (`list-reviewers`)
- [ ] `?u=Paolo42` connecte ; URL nue → modale code
- [ ] crop d'un item s'affiche (URL présignée MinIO joignable)
- [ ] depuis le Mac : `review:publish` puis `review:reconcile` round-trip OK
- [ ] `review.db` sur un chemin **persistant** (survit aux redéploiements)

## Ce qui n'est PAS ici

- ❌ Backup de `review.db` : c'est un tampon transient (la vérité reste eurio.db).
  Un snapshot périodique est un bonus, pas une nécessité.
- ❌ Auth forte : volontairement minimale (cf. `04-auth.md`).
