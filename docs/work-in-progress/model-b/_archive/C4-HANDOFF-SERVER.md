# RUNBOOK — déployer eurio-api sur le VPS (Modèle B, C4-deploy)

> **Pour qui** : une session Claude Code (ou un humain) connecté en SSH au VPS
> (NixOS, flake `vps`, là où tournent déjà MinIO + review_service via Docker).
> **But** : bâtir et démarrer le conteneur `eurio-api` (canonique `eurio.db`
> derrière FastAPI, writer unique, auth OIDC+PAT, Traefik).
>
> Tout le code applicatif est dans le repo — ne pas en écrire ici. Ce doc est
> un runbook de déploiement. Si tu dois dévier, fais-le et note la déviation
> dans le résumé (§7).

## 0. Contexte rapide

`server_serve.py` (lean, sans torch/cv2) est déjà codé + testé. `infra/eurio-api/`
contient le Dockerfile, `docker-compose.yml` (Traefik, OIDC, SOPS) et
`entrypoint.sh`. **Ce chunk = le mettre en production.**

⚠️ C4 est un stand-up de **validation en ISOLATION**. La DB VPS (`/var/lib/eurio/eurio.db`)
diverge volontairement du canonique Mac (lease). Ne branche pas la console admin
dessus pour du travail réel (C5 ensuite). Toute écriture testée ici est jetable
(re-seedée au cutover C8).

## 1. Prérequis (vérifier, ne pas supposer)

```bash
docker --version && docker compose version          # compose ≥ 2.17 (additional_contexts)
docker network ls | grep traefik                    # réseau 'traefik' externe existe
docker ps | grep -iE 'traefik|minio|review'         # Traefik + MinIO up
ls /opt/eurio || echo "repo absent ?"
```

- Repo présent et à jour : `cd /opt/eurio && git pull` (vérifier la branche avec l'utilisateur).
- Si `data/` absent dans `infra/eurio-api/` : c'est normal (DB créée au 1er boot par FastAPI).
- DNS : enregistrement `eurio-api.musubi.dev` → IP du VPS (comme `eurio-review.musubi.dev`).
  Si absent, créer chez le même provider ou noter dans le résumé.
- **cold-start VPS vierge** : restaurer un backup avant de lancer (`infra/backup/eurio-backup.sh`).
  Le conteneur crée `data/eurio.db` via les migrations FastAPI au boot — il ne seed plus depuis MinIO
  (l'ancien `bootstrap_canonical.py` est supprimé depuis auth-redesign C2).

## 2. Secrets (SOPS via direnv)

Aucun fichier secret en clair dans `infra/eurio-api/`. La source est
`/opt/eurio/secrets/dev.env` (chiffré SOPS+age). Le `.envrc` racine déchiffre
et exporte tout dans le shell.

```bash
cd /opt/eurio          # direnv reload automatique (age key dans ~/.config/sops/age/keys.txt)
echo $MINIO_ACCESS_KEY # doit être non-vide (sinon : direnv allow ; sops -d secrets/dev.env)
```

Vars obligatoires au boot (vérifiées par `entrypoint.sh` + `:?missing` dans
`docker-compose.yml`) : `MINIO_ACCESS_KEY`, `MINIO_SECRET_KEY`,
`EURIO_OIDC_CLIENT_SECRET`, `EURIO_SESSION_SECRET`.

Cas scripté sans direnv (cron, systemd) :
```bash
sops exec-env /opt/eurio/secrets/dev.env \
  "docker compose -f /opt/eurio/infra/eurio-api/docker-compose.yml up -d --build"
```

## 3. Vérifier la config avant de lancer

```bash
cd /opt/eurio/infra/eurio-api
grep -E 'MINIO_ENDPOINT|CORS_ORIGINS|eurio-api\.musubi\.dev' docker-compose.yml
```

- `MINIO_ENDPOINT` = `eurio-s3.musubi.dev` (même que `infra/review`).
- `EURIO_API_CORS_ORIGINS` = `https://eurio-admin.musubi.dev,http://localhost:5173`.
- Domaine Traefik = `eurio-api.musubi.dev`, certresolver = même que `infra/review/docker-compose.yml`.

## 4. Build et démarrage

```bash
cd /opt/eurio/infra/eurio-api
docker compose up -d --build
docker compose logs -f eurio-api        # Ctrl-C quand stable
```

Au boot, les logs attendus :
```
serve-role prêt | DB=/var/lib/eurio/eurio.db | auth=True
routers montés : [coins, sets, operations, referential, ...]
routers skippés : [review_queue (...), coin_assets (...)]   ← attendu sur l'image lean
```

> Les routers `review_queue` (legacy) et `coin_assets` seront skippés (dépendances cv2
> absentes de l'image lean). Tout autre router skipé = noter l'erreur exacte dans le résumé.

## 5. Créer un compte admin et un PAT machine

L'auth est OIDC+PAT (auth-redesign). Pas de `add-token` legacy.

```bash
# Étape 1 : promouvoir ton compte Authentik en owner (1 seule fois)
docker compose exec eurio-api python -m serving.auth grant-owner --email raphaelthi59@gmail.com

# Étape 2 : se connecter une fois via OIDC (navigateur → https://eurio-api.musubi.dev/auth/oidc/login)
# afin que le compte existe dans la DB locale. Sans ce premier login, create-pat échoue.

# Étape 3 : créer un PAT pour le Mac (et un pour le PC si besoin)
docker compose exec eurio-api python -m serving.auth create-pat \
  --email raphaelthi59@gmail.com --name mac --scope "ingest:run coins:read"
```

Copier le token affiché (non ré-affichable) et l'ajouter dans `secrets/dev.env`
côté Mac comme `EURIO_API_TOKEN`. **Ne jamais coller les tokens en clair dans le résumé.**

## 6. Vérifications

```bash
# a) Liveness (sans auth)
curl -s https://eurio-api.musubi.dev/healthz ; echo
#   → {"ok":true,"role":"serve","db":"/var/lib/eurio/eurio.db"}

# b) Sans token → 401
curl -s -o /dev/null -w "%{http_code}\n" https://eurio-api.musubi.dev/ingest/run/none

# c) Avec PAT → 200 (run inexistant = applied:false)
TOKEN=<token_mac_ici_localement>
curl -s -H "Authorization: Bearer $TOKEN" \
     https://eurio-api.musubi.dev/ingest/run/does-not-exist ; echo
#   → {"run_id":"does-not-exist","applied":false}
```

Note : TLS Let's Encrypt via Traefik — si `curl` se plaint du cert, attendre la
propagation ou vérifier `docker compose logs traefik`.

## 7. Garde-fous / dépannage

- **`additional_contexts` non supporté** → `docker compose` (plugin v2), pas `docker-compose` v1.
- **Router léger inattendu skippé** → copier l'erreur exacte dans le résumé (dep Python
  manquante, ex. `httpx` ; ne pas tenter d'installer torch/cv2).
- **OOM / conteneur tué** → ne devrait pas arriver (image lean). Si ça arrive : `docker compose
  logs` + `free -m` dans le résumé.
- **Ne jamais** faire `mc cp` / push vers `eurio-db/` depuis le serveur : le serve-role
  ne doit jamais écrire le canonique MinIO (pas de split-brain avec le lease Mac).
- **`MINIO_ACCESS_KEY missing`** au boot → direnv non actif : utiliser `sops exec-env` (§2).

## 8. Résumé à produire (handoff retour)

```
## C4-deploy — résumé

- Repo : <commit sha> (branche <…>)
- Build : OK / KO (+ erreur)
- Conteneur : up depuis <…> / restart-loop / KO
- Boot log — routers MONTÉS : [...]
- Boot log — routers SKIPPÉS : [...]   (review_queue/coin_assets attendus ; noter tout autre + erreur exacte)
- Auth : grant-owner OK ? premier login OIDC fait ? PAT créés (NOMS uniquement) : [mac, ...]
- Vérifs HTTP :
    - /healthz : <réponse>
    - /ingest/run/none sans token : <code HTTP>   (attendu 401)
    - /ingest/run/... avec PAT : <réponse>        (attendu applied:false)
- TLS / DNS : cert émis ? domaine résout ?
- Déviations vs ce runbook : <…>
- Erreurs / blocages : <…>
- Questions pour la session Mac : <…>
```
