# Kickoff — MinIO bootstrap sur VPS NixOS (session serveur)

> Ce doc est destiné à une **session Claude Code tournant sur le VPS**.
> Il est autonome : l'agent n'a pas accès au repo Eurio. Tout le
> contexte nécessaire est ici. Côté Mac (repo), une autre session
> prépare en parallèle le code Python (cache, migration scripts).
>
> **Objectif de ta session** : faire vivre une instance MinIO
> dockerisée, avec 3 buckets, exposée derrière Traefik sur 2
> sous-domaines, et un user applicatif aux droits limités.

## Contexte projet (résumé)

**Eurio** = projet perso de reconnaissance de pièces euros (app Android Kotlin + admin web Vue + pipeline ML Python).

Aujourd'hui les images training/scrape vivent sur le filesystem du Mac dev. On migre vers un stockage S3-compatible (MinIO sur ce VPS) pour que le Mac, le PC fixe et l'admin web Vercel partagent une source de vérité unique.

**Ce que ce VPS porte** :
- MinIO dockerisé (3 buckets : canonique, raws, crops scrapés)
- Backup hebdo automatisé vers pCloud (tarball écrasé)

**Ce que ce VPS ne porte PAS** :
- L'app Android prod consomme **Supabase Storage** (chaîne prod indépendante).
- Pas d'API applicative, pas de DB. Juste MinIO + Traefik + backup.

**Stack VPS** :
- NixOS, géré via `nixos-rebuild switch`
- Traefik déjà installé et fonctionnel (TLS via Cloudflare DNS challenge, certResolver `cf` configuré)
- Docker activé (`virtualisation.docker.enable = true`)
- Sous-domaines DNS déjà créés : `eurio-s3.musubi.dev` + `eurio-images.musubi.dev` (CNAME proxied vers le VPS)

## Mission

À la fin de ta session, depuis n'importe quelle machine externe (Mac dev) :

```bash
# 1. mc client peut lister les 3 buckets
mc alias set eurio https://eurio-s3.musubi.dev $APP_USER $APP_PWD
mc ls eurio/numista-canonical eurio/enrichment-raws eurio/enrichment-crops

# 2. Bucket public lisible sans auth via le sous-domaine images
echo "test-public" > /tmp/t.txt
mc cp /tmp/t.txt eurio/numista-canonical/test.txt
curl -sf https://eurio-images.musubi.dev/test.txt           # → "test-public"

# 3. Buckets privés rejettent les requêtes anonymes
curl -I https://eurio-s3.musubi.dev/enrichment-crops/anything   # → 403
```

Et sur le VPS :

```bash
systemctl status eurio-minio          # active (oneshot, RemainAfterExit)
docker ps | grep eurio-minio          # running
ls /var/lib/eurio-minio/data/         # numista-canonical/ enrichment-raws/ enrichment-crops/
```

## Architecture cible

```
Internet ─► Cloudflare (proxy ON) ─► VPS:443 ─► Traefik
                                                  │
                                ┌─────────────────┼─────────────────┐
                                │                                   │
                  Host(eurio-s3.musubi.dev)            Host(eurio-images.musubi.dev)
                                │                                   │
                                │           middleware addPrefix=/numista-canonical
                                │                                   │
                                └────────────► docker eurio-minio :9000
                                                  │
                                                  ▼
                                       /var/lib/eurio-minio/data/
                                            ├── numista-canonical/   (public-read)
                                            ├── enrichment-raws/     (privé)
                                            └── enrichment-crops/    (privé)
```

**Pourquoi le middleware addPrefix sur eurio-images.musubi.dev** :
- Le bucket public `numista-canonical` est servi via un sous-domaine dédié pour caching CDN propre.
- Côté code applicatif, l'URL est `https://eurio-images.musubi.dev/numista/12345/obverse.jpg`
- Traefik réécrit en `https://eurio-s3.musubi.dev/numista-canonical/numista/12345/obverse.jpg` côté MinIO
- Donc le client n'a jamais besoin de connaître le nom du bucket, et MinIO sait routeur.

## Décisions actées (ne pas re-débattre)

1. **Docker compose**, pas `services.minio` NixOS natif. (Plus simple, image officielle, mises à jour faciles.)
2. **3 buckets** : `numista-canonical` (public-read), `enrichment-raws` (privé), `enrichment-crops` (privé).
3. **2 user MinIO** : root (admin) + `eurio-app` (user applicatif R/W sur les 3 buckets, pas d'admin).
4. **Credentials** dans `/etc/eurio/minio/secrets/` (mode 0400 root), montés en volume read-only dans le container. **Jamais en clair dans le compose.**
5. **Pas de versioning S3** sur les buckets. Protection = backup pCloud hebdo (chunk séparé, pas dans cette session).
6. **Pas de console MinIO exposée publiquement** en V1. Si besoin admin GUI, on tunnelera plus tard.
7. **Volume data** : `/var/lib/eurio-minio/data/`, propriété container.
8. **TLS** : Traefik termine TLS via Cloudflare DNS challenge (certResolver `cf` déjà en place). MinIO écoute en HTTP côté container, Traefik fait le HTTPS.
9. **Cloudflare en mode "Full (strict)"** sur les deux sous-domaines (à vérifier ; l'utilisateur l'a probablement déjà configuré pour ses autres services).

## Étapes d'implémentation

### Étape 1 — Préparer secrets et data dir

```bash
sudo mkdir -p /etc/eurio/minio/secrets
sudo mkdir -p /var/lib/eurio-minio/data

# Generate strong creds
openssl rand -base64 24 | sudo tee /etc/eurio/minio/secrets/minio_root_password >/dev/null
echo -n "eurio-root" | sudo tee /etc/eurio/minio/secrets/minio_root_user >/dev/null

openssl rand -base64 24 | sudo tee /etc/eurio/minio/secrets/eurio_app_password >/dev/null
echo -n "eurio-app" | sudo tee /etc/eurio/minio/secrets/eurio_app_user >/dev/null

sudo chmod -R 0400 /etc/eurio/minio/secrets/*
sudo chown -R root:root /etc/eurio/minio/secrets/
```

> **NOTE pour l'agent** : à la fin de la session, transmettre les credentials `eurio-app` à l'utilisateur (par un canal hors-doc) pour qu'il les mette dans son direnv côté Mac. Ne **pas** les écrire dans ce fichier ni dans aucun fichier commit.

### Étape 2 — Docker compose

`/etc/eurio/minio/docker-compose.yml` :

```yaml
services:
  minio:
    image: minio/minio:latest
    container_name: eurio-minio
    restart: unless-stopped
    command: server /data --console-address :9001
    volumes:
      - /var/lib/eurio-minio/data:/data
      - /etc/eurio/minio/secrets:/run/secrets:ro
    environment:
      MINIO_ROOT_USER_FILE: /run/secrets/minio_root_user
      MINIO_ROOT_PASSWORD_FILE: /run/secrets/minio_root_password
    networks:
      - traefik
    labels:
      - traefik.enable=true
      - traefik.docker.network=traefik

      # ── S3 endpoint (signed URL access for private buckets) ──
      - traefik.http.routers.minio-s3.rule=Host(`eurio-s3.musubi.dev`)
      - traefik.http.routers.minio-s3.entrypoints=websecure
      - traefik.http.routers.minio-s3.tls.certresolver=cf
      - traefik.http.routers.minio-s3.service=minio-s3
      - traefik.http.services.minio-s3.loadbalancer.server.port=9000

      # ── Public CDN: eurio-images.musubi.dev → numista-canonical bucket ──
      - traefik.http.middlewares.images-prefix.addprefix.prefix=/numista-canonical
      - traefik.http.routers.minio-images.rule=Host(`eurio-images.musubi.dev`)
      - traefik.http.routers.minio-images.entrypoints=websecure
      - traefik.http.routers.minio-images.tls.certresolver=cf
      - traefik.http.routers.minio-images.middlewares=images-prefix
      - traefik.http.routers.minio-images.service=minio-s3   # même backend

networks:
  traefik:
    external: true
```

> **À adapter** : si le réseau Docker que Traefik utilise n'est pas `traefik`, mets le bon nom (vérifier via `docker network ls` ou le compose Traefik existant).
>
> **À adapter aussi** : si Traefik tourne hors Docker (binaire systemd direct), il faut exposer MinIO sur un port host (ex. `127.0.0.1:9000:9000`) et configurer Traefik via fichier statique au lieu des labels. **Demander à l'utilisateur** quelle est la config Traefik avant de finaliser ce fichier.

### Étape 3 — NixOS unit pour activer le compose au boot

`/etc/nixos/eurio-minio.nix` :

```nix
{ pkgs, ... }: {
  systemd.services.eurio-minio = {
    description = "Eurio MinIO (docker compose)";
    after = [ "docker.service" "network-online.target" ];
    wants = [ "docker.service" "network-online.target" ];
    wantedBy = [ "multi-user.target" ];
    serviceConfig = {
      Type = "oneshot";
      RemainAfterExit = true;
      ExecStart = "${pkgs.docker}/bin/docker compose -f /etc/eurio/minio/docker-compose.yml up -d";
      ExecStop  = "${pkgs.docker}/bin/docker compose -f /etc/eurio/minio/docker-compose.yml down";
      ExecReload = "${pkgs.docker}/bin/docker compose -f /etc/eurio/minio/docker-compose.yml up -d --force-recreate";
    };
  };
}
```

Importer dans `/etc/nixos/configuration.nix` :

```nix
imports = [ ./eurio-minio.nix ];
```

Puis :

```bash
sudo nixos-rebuild switch
systemctl status eurio-minio
docker ps | grep eurio-minio
```

### Étape 4 — Création des buckets et ACL

Une fois MinIO up, depuis le VPS :

```bash
# Install mc si pas déjà là (NixOS : nix-shell -p minio-client)
nix-shell -p minio-client --run '
  ROOT_USER=$(cat /etc/eurio/minio/secrets/minio_root_user)
  ROOT_PWD=$(cat /etc/eurio/minio/secrets/minio_root_password)

  # Alias local — passe par localhost pour bypass Traefik au bootstrap
  mc alias set local http://localhost:9000 "$ROOT_USER" "$ROOT_PWD"

  # Buckets
  mc mb -p local/numista-canonical
  mc mb -p local/enrichment-raws
  mc mb -p local/enrichment-crops

  # numista-canonical : lecture publique anonyme
  mc anonymous set download local/numista-canonical
'
```

> Si `mc` ne peut pas joindre `localhost:9000`, c'est que le port n'est pas exposé sur le host. Soit ajouter `ports: ["127.0.0.1:9000:9000"]` au compose, soit faire la config via le réseau Docker (`docker exec` dans le container, ou un alias mc qui passe par `eurio-s3.musubi.dev`).

### Étape 5 — User applicatif `eurio-app`

```bash
nix-shell -p minio-client --run '
  ROOT_USER=$(cat /etc/eurio/minio/secrets/minio_root_user)
  ROOT_PWD=$(cat /etc/eurio/minio/secrets/minio_root_password)
  APP_USER=$(cat /etc/eurio/minio/secrets/eurio_app_user)
  APP_PWD=$(cat /etc/eurio/minio/secrets/eurio_app_password)

  mc alias set local http://localhost:9000 "$ROOT_USER" "$ROOT_PWD"

  # Create user
  mc admin user add local "$APP_USER" "$APP_PWD"

  # Policy
  cat > /tmp/eurio-app-policy.json <<EOF
{
  "Version": "2012-10-17",
  "Statement": [{
    "Effect": "Allow",
    "Action": ["s3:GetObject","s3:PutObject","s3:DeleteObject","s3:ListBucket"],
    "Resource": [
      "arn:aws:s3:::numista-canonical/*", "arn:aws:s3:::numista-canonical",
      "arn:aws:s3:::enrichment-raws/*",   "arn:aws:s3:::enrichment-raws",
      "arn:aws:s3:::enrichment-crops/*",  "arn:aws:s3:::enrichment-crops"
    ]
  }]
}
EOF
  mc admin policy create local eurio-app-policy /tmp/eurio-app-policy.json
  mc admin policy attach local eurio-app-policy --user "$APP_USER"
  rm /tmp/eurio-app-policy.json
'
```

### Étape 6 — Smoke tests (must-pass)

Tous depuis le VPS d'abord, puis idéalement répétés depuis l'extérieur (l'utilisateur fera le test depuis son Mac une fois fini).

#### 6.1 — Endpoint S3 répond et accepte les credentials

```bash
APP_USER=$(cat /etc/eurio/minio/secrets/eurio_app_user)
APP_PWD=$(cat /etc/eurio/minio/secrets/eurio_app_password)

nix-shell -p minio-client --run "
  mc alias set eurio https://eurio-s3.musubi.dev '$APP_USER' '$APP_PWD'
  mc ls eurio/
"
# Doit lister les 3 buckets
```

#### 6.2 — Bucket public servi via eurio-images.musubi.dev

```bash
# Upload un fichier test dans numista-canonical
echo "smoke-test-$(date)" > /tmp/smoke.txt
mc cp /tmp/smoke.txt eurio/numista-canonical/smoke.txt

# Curl anonyme
curl -sf https://eurio-images.musubi.dev/smoke.txt
# Doit afficher le contenu

# Cleanup
mc rm eurio/numista-canonical/smoke.txt
```

#### 6.3 — Buckets privés inaccessibles sans signature

```bash
echo "private" > /tmp/priv.txt
mc cp /tmp/priv.txt eurio/enrichment-crops/priv.txt

# Anonyme → 403
curl -I https://eurio-s3.musubi.dev/enrichment-crops/priv.txt
# HTTP/2 403

mc rm eurio/enrichment-crops/priv.txt
```

#### 6.4 — Multipart upload (gros fichier)

Vérifier que Traefik forward correctement les headers pour les uploads > 5 MB :

```bash
dd if=/dev/urandom of=/tmp/big.bin bs=1M count=100
mc cp /tmp/big.bin eurio/enrichment-crops/big.bin
mc ls eurio/enrichment-crops/big.bin   # doit montrer ~100 MiB
mc rm eurio/enrichment-crops/big.bin
rm /tmp/big.bin
```

Si ça échoue → c'est probablement un problème de `Host` header ou de `Content-Length` côté Traefik. Voir gotcha §1.

#### 6.5 — Restart résilience

```bash
sudo systemctl restart eurio-minio
sleep 5
mc ls eurio/
# doit toujours marcher
```

## Gotchas connus

1. **Traefik `Host` header sur multipart uploads** : si un upload de gros fichier échoue avec 400/411, ajouter sur le router `minio-s3` :
   ```yaml
   - traefik.http.middlewares.minio-headers.headers.customrequestheaders.Host=
   ```
   ou plus simplement vérifier que `passHostHeader` est `true` (default en Traefik v2+).

2. **Cloudflare timeout sur uploads longs** : Cloudflare free tier coupe les requêtes après 100 s. Si on upload 500 MB sur une connexion modeste, ça peut couper. Pour les uploads massifs (migration future), passer par MinIO direct via IP/port temporaire ou monter la limite Cloudflare (plan payant). En V1 on n'a pas ce problème (objets < 10 MB).

3. **Cloudflare "Full (strict)" SSL** : si Traefik a un cert valide via Let's Encrypt DNS challenge, Cloudflare peut être en Full strict. Si jamais Cloudflare répond 525/526 → revérifier le cert via `curl -v https://eurio-s3.musubi.dev` directement (sans CF en proxy en mode dev) puis remettre proxy ON.

4. **Versioning S3 activé par accident** : ne PAS faire `mc version enable`. Si activé par erreur, `mc version suspend` immédiatement.

5. **MinIO console (port 9001)** : NE PAS l'exposer publiquement V1. Pas de label Traefik dessus. Si besoin admin GUI, faire un tunnel SSH ad-hoc (`ssh -L 9001:localhost:9001 vps`).

6. **Réseau Docker partagé avec Traefik** : la valeur `networks: traefik:` du compose suppose qu'un réseau Docker `traefik` existe déjà (créé par le compose Traefik). Vérifier avec `docker network ls`. Si Traefik tourne hors Docker, voir étape 2 note.

7. **Permissions volume data** : MinIO container tourne en root par défaut. `/var/lib/eurio-minio/data` doit être writable par root, ce qui est le cas si tu l'as créé via `sudo mkdir`. Si tu vois des "permission denied" dans les logs MinIO, vérifier `ls -la /var/lib/eurio-minio/`.

## Critères d'acceptation (à valider avant de clore la session)

- [ ] `systemctl status eurio-minio` → active, RemainAfterExit
- [ ] `docker ps` montre `eurio-minio` running, restart count 0
- [ ] 3 buckets créés, `numista-canonical` en `anonymous=download`
- [ ] User `eurio-app` créé avec policy R/W sur les 3 buckets
- [ ] Smoke test 6.1 (`mc ls eurio/` depuis le VPS) → liste les 3 buckets
- [ ] Smoke test 6.2 (`curl eurio-images.musubi.dev/smoke.txt`) → 200 + contenu
- [ ] Smoke test 6.3 (curl anonyme sur enrichment-crops) → 403
- [ ] Smoke test 6.4 (multipart 100 MB) → success
- [ ] Smoke test 6.5 (restart service) → tout remarche
- [ ] Reboot test : `sudo reboot`, attendre, vérifier que MinIO remonte tout seul
- [ ] Credentials `eurio-app` transmis à l'utilisateur (canal sécurisé, pas dans ce doc ni dans un fichier git)

## Ce que tu NE fais PAS dans cette session

- Pas de migration de données (un autre script Python tournera depuis le Mac, pas depuis le VPS)
- Pas de backup pCloud (chunk dédié plus tard, sur le même VPS, mais pas maintenant)
- Pas de monitoring / alerting (V2)
- Pas de chiffrement at-rest (V2 si nécessaire)
- Pas d'ouverture de la console MinIO publiquement
- Pas de modification du Traefik existant **sauf** ajout des labels MinIO. Si Traefik nécessite reload pour picker les labels Docker, le faire proprement (généralement Traefik watch Docker events automatiquement).

## Output attendu de la session

À la fin :

1. Un message de status récap (services up, smoke tests passed).
2. Les credentials `eurio-app` à transmettre à l'utilisateur (hors doc, hors git).
3. La liste des fichiers créés/modifiés sur le VPS :
   - `/etc/eurio/minio/docker-compose.yml`
   - `/etc/eurio/minio/secrets/{minio_root_user,minio_root_password,eurio_app_user,eurio_app_password}`
   - `/etc/nixos/eurio-minio.nix`
   - `/etc/nixos/configuration.nix` (1 ligne import)
   - `/var/lib/eurio-minio/data/` (créé, contient les 3 buckets)
4. Les 2 sous-domaines DNS sont déjà en place (l'utilisateur a confirmé) : pas d'action DNS requise.

## Si quelque chose part en vrille

- **Container ne démarre pas** : `docker logs eurio-minio` puis `journalctl -u eurio-minio.service`.
- **TLS échoue** : vérifier le certResolver Traefik, regarder les logs Traefik (`docker logs traefik` ou équivalent).
- **404 sur eurio-s3.musubi.dev** : router pas matché, vérifier les labels et `docker inspect eurio-minio | grep traefik`.
- **403 systématique sur le bucket public** : `mc anonymous get local/numista-canonical` doit retourner `download`. Si vide, refaire `mc anonymous set download local/numista-canonical`.
- **Reboot et MinIO ne remonte pas** : vérifier `systemctl is-enabled eurio-minio`, et que docker.service est `wantedBy = multi-user.target`.

Quand tu finis, si tu as touché à des trucs hors scope (Traefik global, NixOS hors le module dédié), liste-les explicitement dans le récap final pour que l'utilisateur audit.
