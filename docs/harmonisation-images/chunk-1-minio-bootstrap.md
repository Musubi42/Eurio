# Chunk 1 — MinIO bootstrap (VPS)

> Faire vivre une instance MinIO sur le VPS, avec 3 buckets et les ACL
> qu'il faut. Ne touche ni la DB, ni le code Eurio. Pré-requis pour les
> chunks 3, 6, 7.

## Objectif

À la fin du chunk, depuis Mac et PC, on peut :

```bash
mc alias set eurio https://minio.eurio.lan ACCESS SECRET
mc ls eurio/numista-canonical
mc ls eurio/enrichment
mc ls eurio/source-images
```

Et un `curl https://images.eurio.com/test.png` (Cloudflare → MinIO) renvoie un objet test (preuve que le bucket public est servable). Les 2 autres buckets répondent 403 sans signed URL.

## Pré-requis

- VPS NixOS ou Linux générique up & reachable.
- Domaine `eurio.com` (ou autre) avec DNS contrôlable pour pointer sur le VPS.
- Reverse proxy Traefik déjà installé sur le VPS (acquis selon mémoire utilisateur).

## Décisions à acter avant de coder

1. **NixOS module vs docker-compose** ?
   - Si `nixos-rebuild`-managé : `services.minio` du module officiel + `services.traefik` route. Reproductible, propre.
   - Sinon : `docker-compose.yml` avec MinIO + Traefik label routes.
   - **Reco** : NixOS module si possible (le VPS est NixOS d'après l'utilisateur).
2. **Sous-domaines** :
   - `images.eurio.com` → bucket public `numista-canonical` via Cloudflare (chunk 6)
   - `s3.eurio.com` → endpoint S3 (signed URLs pour `enrichment`, `source-images`)
   - `console.eurio.com` → console MinIO admin (basic auth Traefik en plus)
3. **Credentials** : root MinIO via `pass` ou `agenix` côté VPS, pas en clair dans le flake.

## Implémentation — étapes

### 1.1 Installation

**NixOS** (recommandé) :
```nix
# /etc/nixos/services/minio.nix
{ config, ... }: {
  services.minio = {
    enable = true;
    region = "eu-west-1";
    rootCredentialsFile = "/run/secrets/minio-root-creds";
    dataDir = [ "/var/lib/minio/data" ];
    listenAddress = "127.0.0.1:9000";
    consoleAddress = "127.0.0.1:9001";
  };
}
```

Puis Traefik labels pour exposer `s3.eurio.com` → `127.0.0.1:9000`.

**Docker-compose** (alternative) :
```yaml
services:
  minio:
    image: minio/minio:latest
    command: server /data --console-address :9001
    volumes:
      - /var/lib/minio/data:/data
    environment:
      MINIO_ROOT_USER_FILE: /run/secrets/minio_user
      MINIO_ROOT_PASSWORD_FILE: /run/secrets/minio_password
    labels:
      - traefik.http.routers.minio-s3.rule=Host(`s3.eurio.com`)
      - traefik.http.services.minio-s3.loadbalancer.server.port=9000
```

### 1.2 Création des buckets

Via `mc` (MinIO Client) depuis le VPS, après que MinIO soit up :

```bash
mc alias set local https://s3.eurio.com $ROOT_USER $ROOT_PWD
mc mb local/numista-canonical
mc mb local/enrichment
mc mb local/source-images

# Numista : public read (anonyme)
mc anonymous set download local/numista-canonical

# Enrichment + source-images : privé par défaut, pas de policy anonyme
```

### 1.3 Création d'un user "eurio-app"

Le code Eurio (Mac dev, PC dev) ne doit jamais utiliser le root user.

```bash
mc admin user add local eurio-app $APP_PWD
mc admin policy create local eurio-app-policy /tmp/policy.json
mc admin policy attach local eurio-app-policy --user eurio-app
```

Policy `eurio-app-policy` (read+write sur les 3 buckets, pas d'admin) :
```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Effect": "Allow",
      "Action": ["s3:GetObject","s3:PutObject","s3:DeleteObject","s3:ListBucket"],
      "Resource": [
        "arn:aws:s3:::numista-canonical/*",
        "arn:aws:s3:::numista-canonical",
        "arn:aws:s3:::enrichment/*",
        "arn:aws:s3:::enrichment",
        "arn:aws:s3:::source-images/*",
        "arn:aws:s3:::source-images"
      ]
    }
  ]
}
```

### 1.4 Smoke test

Depuis Mac :
```bash
mc alias set eurio https://s3.eurio.com $APP_USER $APP_PWD
echo "hello" > /tmp/test.txt
mc cp /tmp/test.txt eurio/enrichment/test.txt
mc ls eurio/enrichment
mc rm eurio/enrichment/test.txt
```

Depuis browser (test public read) :
```bash
mc cp /tmp/cat.png eurio/numista-canonical/cat.png
curl https://s3.eurio.com/numista-canonical/cat.png > /tmp/cat-back.png
diff /tmp/cat.png /tmp/cat-back.png  # exit 0
```

## Critères d'acceptation

- [ ] MinIO up sur le VPS, restart à reboot OK
- [ ] 3 buckets créés avec les ACL voulues
- [ ] User `eurio-app` peut R+W sur les 3 buckets, pas d'admin
- [ ] `curl https://s3.eurio.com/numista-canonical/<key>` répond 200 sans auth
- [ ] `curl https://s3.eurio.com/enrichment/<key>` répond 403 sans signed URL
- [ ] Credentials root + app-user stockés dans le secret-store du VPS, **jamais commit**

## Gotchas

- **CORS** : si jamais le front admin (`admin.eurio.com`) doit lire un objet privé via fetch (signed URL), MinIO doit avoir CORS configuré pour autoriser l'origine. À ajouter dans la policy bucket si besoin avéré.
- **Reverse proxy headers** : Traefik doit forward `Host` correctement, sinon MinIO refuse les multipart uploads. Bien tester un upload de gros fichier (500 MB+) avant de déclarer le chunk done.
- **Versioning S3** : ne PAS l'activer (cf. vision §"Décisions actées" point 7). Si activé par erreur, désactiver avant migration.

## Anti-objectifs

- ❌ Pas de write public sur le bucket Numista (read-only).
- ❌ Pas de bucket par-source (`ebay`, `catawiki`) pour l'enrichment. Un seul bucket, le préfixe de la clé porte la source (cf. chunk 2).
- ❌ Pas de policy "à plat" sur le user root. Un user dédié pour l'app, principle of least privilege.
