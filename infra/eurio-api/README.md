# infra/eurio-api — API canonique (Modèle B, serve-role)

Stand-up de `eurio.db` derrière l'API FastAPI sur le VPS (writer unique, auth
bearer, Traefik). Image **légère** (pas de torch/cv2) : seuls les routers
interactifs légers + `/ingest/run` sont servis ; les routers de calcul lourd se
skippent au boot (log).

- Déploiement pas-à-pas : **`docs/work-in-progress/model-b/C4-HANDOFF-SERVER.md`**.
- Design d'ensemble : `docs/work-in-progress/model-b/DESIGN.md`.

⚠️ **C4 = stand-up + validation en ISOLATION.** L'API seed une **copie** de
`eurio.db` depuis MinIO et n'y re-pousse jamais. Le Mac reste le writer réel (lease)
jusqu'au cutover (C8). Ne pas faire d'admin réel contre cette API tant que C5/C8
ne sont pas faits.

## Secrets — pattern SOPS via direnv

Aucun fichier secret sur disque côté `infra/eurio-api/`. La source unique est
`/opt/eurio/secrets/dev.env` chiffré SOPS+age. Le `.envrc` racine du repo
déchiffre et exporte automatiquement les vars dans le shell au `cd /opt/eurio`
(via direnv). `docker compose` lit ces vars depuis l'env du process.

### Cas standard — shell interactif (direnv actif)

```bash
cd /opt/eurio/infra/eurio-api
docker compose up -d --build
# Les vars MINIO_ACCESS_KEY / MINIO_SECRET_KEY sont déjà dans l'env du shell
# grâce à direnv. Compose les forwarde au container via `environment:`.
```

Le `:?missing` dans `docker-compose.yml` fait échouer tôt si les vars ne sont
pas définies — utile pour détecter un shell non-direnv ou un secret manquant.

### Cas scripté — pas de direnv (cron, systemd, CI)

```bash
sops exec-env /opt/eurio/secrets/dev.env "docker compose -f /opt/eurio/infra/eurio-api/docker-compose.yml up -d --build"
```

`sops exec-env` ne touche pas au disque (streamé en mémoire). La clé age reste à
`~/.config/sops/age/keys.txt` (gérée par machine, jamais committée).

### Restart automatique

`restart: unless-stopped` couvre les redémarrages Docker (reboot VPS). Docker
conserve les env vars du dernier `up` dans son state — pas besoin de re-sourcer
SOPS pour un restart simple. Seul un `up`/`up --force-recreate` nouveau exige
les vars présentes.

```bash
# Créer un compte owner puis un PAT machine (auth OIDC+PAT, auth-redesign C3) :
docker compose exec eurio-api python -m serving.auth grant-owner --email <ton-email>
# → puis login OIDC une fois (navigateur), puis :
docker compose exec eurio-api python -m serving.auth create-pat \
  --email <ton-email> --name mac --scope "ingest:run coins:read"
```

Procédure complète (DNS, TLS, vérifs) : **`docs/work-in-progress/model-b/C4-HANDOFF-SERVER.md`**.
