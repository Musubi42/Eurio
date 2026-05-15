# Chunk 1 — MinIO docker bootstrap (VPS NixOS)

> Faire vivre une instance MinIO dockerisée sur le VPS perso, avec 3
> buckets et les ACL voulues. Ne touche ni la DB, ni le code Eurio.
> Pré-requis pour les chunks 3, 6, 7.

## Objectif

À la fin du chunk, depuis Mac et PC, on peut :

```bash
mc alias set eurio https://eurio-s3.musubi.dev $APP_USER $APP_PWD
mc ls eurio/numista-canonical
mc ls eurio/enrichment-raws
mc ls eurio/enrichment-crops
```

Et `curl https://eurio-images.musubi.dev/numista/68395/obverse.jpg` (Cloudflare → MinIO) renvoie 200 sur un objet de test. Les buckets privés répondent 403 sans signed URL.

## Pré-requis

- VPS perso NixOS up, accessible.
- Docker installé via NixOS (`virtualisation.docker.enable = true`).
- Traefik installé sur le VPS (acquis selon utilisateur ; sinon, étape préliminaire).
- Sous-domaine `*.eurio.musubi.dev` pointable sur le VPS via Cloudflare.

## Décisions actées

1. **Docker, pas service NixOS natif** (cf. vision §"Décisions actées" #1). MinIO container officiel.
2. **3 buckets** : `numista-canonical` (public), `enrichment-raws` (privé), `enrichment-crops` (privé).
3. **2 sous-domaines** : `eurio-s3.musubi.dev` (endpoint S3) + `eurio-images.musubi.dev` (CDN public devant `numista-canonical`).
4. **User dédié** `eurio-app` pour le code (pas le root).
5. **Credentials** via fichier monté dans le container, jamais en clair dans le compose ni le flake.

## Implémentation

### 1.1 Docker compose

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
    labels:
      - traefik.enable=true
      # S3 endpoint (signed URL access)
      - traefik.http.routers.minio-s3.rule=Host(`eurio-s3.musubi.dev`)
      - traefik.http.routers.minio-s3.entrypoints=websecure
      - traefik.http.routers.minio-s3.tls.certresolver=cf
      - traefik.http.routers.minio-s3.service=minio-s3
      - traefik.http.services.minio-s3.loadbalancer.server.port=9000
      # Public CDN for numista-canonical bucket
      - traefik.http.routers.minio-images.rule=Host(`eurio-images.musubi.dev`)
      - traefik.http.routers.minio-images.entrypoints=websecure
      - traefik.http.routers.minio-images.tls.certresolver=cf
      - traefik.http.routers.minio-images.middlewares=images-prefix
      - traefik.http.routers.minio-images.service=minio-s3
      - traefik.http.middlewares.images-prefix.addprefix.prefix=/numista-canonical
```

`/etc/eurio/minio/secrets/minio_root_user` et `minio_root_password` : fichiers texte (mode 0400), root MinIO.

### 1.2 NixOS wiring

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
    };
  };
}
```

### 1.3 Cloudflare DNS

Sous-domaines à créer dans la zone `musubi.dev` :

```
s3.eurio        CNAME    <vps-host>      proxied: ON
images.eurio    CNAME    <vps-host>      proxied: ON
```

Cloudflare en mode "Full (strict)" pour valider le certificat Let's Encrypt côté Traefik.

### 1.4 Création des buckets

Depuis le VPS, après que MinIO soit up :

```bash
mc alias set local https://eurio-s3.musubi.dev "$ROOT_USER" "$ROOT_PWD"
mc mb local/numista-canonical
mc mb local/enrichment-raws
mc mb local/enrichment-crops

# Public read pour numista-canonical
mc anonymous set download local/numista-canonical
```

### 1.5 User `eurio-app`

```bash
mc admin user add local eurio-app "$APP_PWD"
mc admin policy create local eurio-app-policy /tmp/policy.json
mc admin policy attach local eurio-app-policy --user eurio-app
```

`policy.json` :

```json
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
```

### 1.6 Smoke test

```bash
# Mac
mc alias set eurio https://eurio-s3.musubi.dev "$APP_USER" "$APP_PWD"
echo hello > /tmp/test.txt
mc cp /tmp/test.txt eurio/enrichment-crops/test.txt
mc cat eurio/enrichment-crops/test.txt   # → hello
mc rm eurio/enrichment-crops/test.txt

# Public read
mc cp /tmp/cat.png eurio/numista-canonical/test.png
curl -sf https://eurio-images.musubi.dev/test.png -o /tmp/cat-back.png
diff /tmp/cat.png /tmp/cat-back.png      # exit 0
```

## Critères d'acceptation

- [ ] `eurio-minio.service` actif, restart à reboot OK
- [ ] 3 buckets créés avec les ACL voulues
- [ ] User `eurio-app` peut R+W sur les 3 buckets, pas d'admin
- [ ] `curl https://eurio-images.musubi.dev/<key>` répond 200 sans auth pour un objet test
- [ ] `curl https://eurio-s3.musubi.dev/enrichment-crops/<key>` répond 403 sans signed URL
- [ ] Credentials root + app stockés dans `/etc/eurio/minio/secrets/` (mode 0400, owner root), jamais commit
- [ ] Cloudflare proxy ON sur les deux sous-domaines, TLS Full (strict)

## Gotchas

- **Cloudflare free + images** : risque TOS si on dépasse plusieurs TB d'egress public/mois. À surveiller via le dashboard CF. Plan B (B2 + bandwidth alliance) documenté en vision §"Ce qui peut faire pivoter le plan".
- **Reverse proxy headers** : Traefik doit forward `Host` correctement, sinon MinIO refuse les multipart uploads. Tester upload de gros fichier (~100 MB) avant de déclarer done.
- **Versioning S3** : NE PAS l'activer (vision §8). Si activé par erreur, désactiver avant chunk 3.
- **CORS** : pas requis V1 (les `<img>` ne déclenchent pas CORS). Si un script JS fait `fetch()` sur signed URL, ajouter `Access-Control-Allow-Origin` au bucket policy.

## Anti-objectifs

- ❌ Pas de write public sur `numista-canonical`.
- ❌ Pas de bucket par-source (`ebay`, `catawiki`). Un seul bucket `enrichment-crops`, le préfixe de la clé porte la source.
- ❌ Pas d'utilisation du root user dans le code applicatif.
- ❌ Pas de service NixOS natif `services.minio`. Docker compose, point.
