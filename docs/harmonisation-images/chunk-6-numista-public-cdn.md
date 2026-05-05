# Chunk 6 — Numista bucket public + Cloudflare

> Servir les images Numista canoniques publiquement via un CDN
> Cloudflare devant le bucket public MinIO. Pas Vercel. Pré-requis :
> chunks 1 et 2 livrés.

## Objectif

À la fin du chunk :
- Le bucket `numista-canonical` est lisible publiquement.
- Le domaine `images.eurio.com` (CNAME → Cloudflare) sert ces images avec mise en cache edge.
- Toute consommation côté admin / Android / scrape construit ses URLs `https://images.eurio.com/numista/<numista_id>/<face>.png`.

## Pourquoi pas Vercel (push-back acté)

| Critère | Vercel free | MinIO + CF free |
|---|---|---|
| Storage | 1 GB Blob | Illimité (limité par le disque VPS) |
| Bandwidth | 100 GB / mois | Illimité (CDN cache hit) + ~Hetzner 20 TB / mois (cache miss) |
| Build deploy | Image bundle dans `/public` ralentit le build | Indépendant du déploy admin |
| Source de vérité | Dupliquée (Vercel + MinIO si on garde MinIO) | Unique (MinIO) |
| Coût | Free puis $20/mois quand cap | Free quasi-illimité |

Catalogue Numista 2€ : ~5k pièces × 2 faces × ~150 KB ≈ **1.5 GB** déjà au-dessus du Vercel Blob free.

À catalogue complet (toutes les pièces euros, pas que 2€) : 50k+ pièces × 2 faces ≈ **15 GB**. Hors Vercel.

→ Vercel n'est pas une option scalable. MinIO + Cloudflare l'est.

## Pré-requis

- Chunk 1 livré (bucket `numista-canonical` créé + ACL public-read).
- Chunk 2 livré (clés `numista/<numista_id>/<face>.<ext>` définies).
- Domaine `eurio.com` (ou autre) géré sur Cloudflare.

## Décisions à acter

1. **Sous-domaine** : `images.eurio.com`. Confirme ou propose autre.
2. **Cache edge TTL** : 7 jours (`Cache-Control: public, max-age=604800`). Les images Numista changent rarissime ; si on a besoin de purger, `mc cp --metadata` + Cloudflare purge URL.
3. **Compression** : Cloudflare le fait par défaut (Brotli sur la HTML, pas sur PNG/JPG). Pas besoin de pré-compresser côté MinIO.

## Implémentation

### 6.1 Configuration Cloudflare DNS

```
images.eurio.com   CNAME   s3.eurio.com   (proxied: ON)
```

Cloudflare en mode "proxied" = orange cloud → caching + DDOS protection + SSL.

Côté Traefik VPS, ajouter une règle :
```yaml
http:
  routers:
    minio-images:
      rule: "Host(`images.eurio.com`)"
      service: minio-s3
      tls: { certResolver: cf }
```

Et un middleware de rewrite pour préfixer `/numista-canonical` automatiquement :
```yaml
middlewares:
  numista-prefix:
    addPrefix:
      prefix: "/numista-canonical"
```

→ `images.eurio.com/numista/12345/obverse.png` → `s3.eurio.com/numista-canonical/numista/12345/obverse.png`.

### 6.2 ACL bucket

(Déjà fait au chunk 1, mais re-checké ici.)

```bash
mc anonymous set download eurio/numista-canonical
```

Vérification :
```bash
curl -I https://images.eurio.com/numista/68395/obverse.png
# HTTP/2 200
# cf-cache-status: HIT (après le 2e hit)
```

### 6.3 Cache headers

MinIO permet de définir `Cache-Control` à l'upload. On le pose via le script de migration (chunk 3) sur tous les objets numista :

```python
client.put_object(
    "numista-canonical",
    f"numista/{numista_id}/{face}.png",
    data,
    metadata={"Cache-Control": "public, max-age=604800, immutable"},
)
```

`immutable` est OK car les images Numista canoniques ne changent jamais — un re-fetch crée une nouvelle key.

### 6.4 Code consommateur

`ml/storage/__init__.py` (rappel) :
```python
def storage_url(storage_key, bucket="numista-canonical", **_):
    if bucket == "numista-canonical":
        return f"https://images.eurio.com/{storage_key}"
    ...
```

Tous les consommateurs (admin web, app Android, scrape) appellent ce helper. Aucun ne hardcode `s3.eurio.com` ou `minio.local`.

### 6.5 Front admin

Mettre à jour `firstImageUrl` (helper existant) pour qu'il utilise `https://images.eurio.com/numista/<numista_id>/obverse.png` au lieu de la ressource locale ou Supabase.

## Critères d'acceptation

- [ ] `curl https://images.eurio.com/numista/12345/obverse.png` → 200 + `cache-control: public, max-age=604800`
- [ ] Cloudflare cache hit ratio > 90 % après 1 jour de trafic admin
- [ ] Admin coin detail page : images chargées depuis `images.eurio.com`, pas de hit MinIO direct
- [ ] App Android : URL Numista pointe vers `images.eurio.com` (à wirer dans le snapshot Android)

## Gotchas

- **Cloudflare free et le "Service unavailable for streaming non-HTML files"** : c'est un mythe pour les images statiques < 100 MB. Les CGU autorisent images, audio, vidéo (court). Si jamais Cloudflare bloque (jamais vu en pratique pour des PNG d'1 MB), on bascule sur Backblaze B2 + Cloudflare Bandwidth Alliance (free egress entre les deux).
- **Cache busting** : si jamais une image Numista doit être ré-uploadée (corrigée), changer la clé (ajouter un suffixe `-v2`) plutôt que purger le cache CF. C'est la stratégie `immutable`.
- **CORS sur images publiques** : pas nécessaire — les `<img src="">` ne déclenchent pas CORS. Si un script JS fait `fetch()` (jamais le cas dans Eurio), il faudra ajouter `Access-Control-Allow-Origin: *` côté MinIO bucket policy.
- **HTTPS strict** : Cloudflare doit être en "Full (strict)" mode pour valider le certificat MinIO derrière. Si Traefik gère bien Let's Encrypt, no-op.

## Anti-objectifs

- ❌ Pas de Vercel pour les images Numista. Cf. push-back acté en intro.
- ❌ Pas de Supabase Storage. Free tier explose à 1 GB.
- ❌ Pas d'image-resizing on-the-fly Cloudflare (payant). On sert les images 1:1 à leur résolution d'origine. Si besoin de thumbs en V2 → générer côté MinIO à l'upload (tâche dédiée), pas Cloudflare.
- ❌ Pas de R2 / B2 pour V1. MinIO est suffisant et déjà en place.
