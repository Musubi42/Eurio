# Chunk 6 — Publication Supabase Storage (chaîne prod)

> Publier les images canoniques optimisées vers Supabase Storage,
> servies à l'app Android prod. Indépendant de la chaîne dev MinIO.
> Pré-requis : chunks 1 et 2 livrés.

## Objectif

À la fin du chunk :

- Bucket Supabase `app-coins-public` peuplé avec les obverses optimisés (WebP, max 1024 px côté long).
- Un script `ml/scripts/publish_to_supabase.py` re-pousse les delta à chaque exécution (idempotent, par sha256).
- App Android consomme `https://<project>.supabase.co/storage/v1/object/public/app-coins-public/<numista_id>/obverse.webp`.
- Vercel admin **n'utilise pas** Supabase Storage en runtime (continue de lire MinIO via API ML proxy).

## Pourquoi pas MinIO directement pour l'app

| Critère | MinIO/VPS perso | Supabase Storage Pro |
|---|---|---|
| SLA | aucun (VPS dev) | géré, CDN intégré |
| Si VPS down | app cassée | indépendant |
| Egress | dépend du fournisseur VPS | 250 GB/mois inclus |
| Coût | infra perso à maintenir | $25/mois forfait |
| Memory project | "no VPS prod" | aligné |

Supabase Pro à $25/mois couvre largement le besoin (270 MB → <100 MB après opti, 250 GB egress = ~2.5M téléchargements/mois).

## Pré-requis

- Chunk 1 livré (canoniques dans MinIO comme source de vérité).
- Chunk 2 livré (clés `numista/<numista_id>/<face>.jpg` figées).
- Projet Supabase actif, bucket `app-coins-public` créé en mode public.
- Service-role key Supabase via direnv (`SUPABASE_SERVICE_ROLE_KEY`).

## Décisions actées

1. **Source = MinIO `numista-canonical`**, pas le filesystem local. Le script lit depuis MinIO et pousse vers Supabase. Le filesystem local est en lecture seule post-migration.
2. **Optimisation à la publication** :
   - Convertir JPG → WebP qualité 85
   - Resize : côté long max 1024 px (les détails fins ne sont pas requis pour l'UX app)
   - Cible : <100 MB total post-opti pour ~700 coins, dimension de référence avant scale-up.
3. **Idempotence par sha256** : on stocke le sha256 source dans la metadata Supabase. Si match → skip.
4. **Nom de bucket** : `app-coins-public` (pas `numista-canonical`, pour éviter de polluer le namespace canonique avec les versions optimisées web).
5. **V1 = obverse seul**. Reverse en V2 si l'UX le justifie (fiche détaillée).
6. **Pas de mécanisme de purge**. Si une image change, on la re-pousse (overwrite + cache busting via versioning de clé : `numista/<id>/obverse-v2.webp`). En pratique, Numista canonique change rarement.

## Implémentation

### 6.1 Script `ml/scripts/publish_to_supabase.py`

```python
from io import BytesIO
from PIL import Image
import boto3, hashlib, os
from supabase import create_client

# MinIO source
s3 = boto3.client("s3", endpoint_url="https://s3.eurio.musubi.dev", ...)

# Supabase target
sb = create_client(
    os.environ["SUPABASE_URL"],
    os.environ["SUPABASE_SERVICE_ROLE_KEY"],
)
BUCKET = "app-coins-public"

def list_canonical_obverses() -> list[str]:
    """Yields storage_keys like 'numista/68395/obverse.jpg'."""
    paginator = s3.get_paginator("list_objects_v2")
    for page in paginator.paginate(Bucket="numista-canonical", Prefix="numista/"):
        for obj in page.get("Contents", []):
            if obj["Key"].endswith("/obverse.jpg"):
                yield obj["Key"]

def optimize(jpg_bytes: bytes) -> bytes:
    im = Image.open(BytesIO(jpg_bytes)).convert("RGB")
    im.thumbnail((1024, 1024))
    out = BytesIO()
    im.save(out, format="WEBP", quality=85, method=6)
    return out.getvalue()

def publish_one(src_key: str):
    src_obj = s3.get_object(Bucket="numista-canonical", Key=src_key)
    src_bytes = src_obj["Body"].read()
    src_sha = hashlib.sha256(src_bytes).hexdigest()

    # numista/68395/obverse.jpg → 68395/obverse.webp
    numista_id = src_key.split("/")[1]
    dst_key = f"{numista_id}/obverse.webp"

    # Idempotence : check Supabase metadata
    try:
        meta = sb.storage.from_(BUCKET).info(dst_key)
        if meta and meta.get("metadata", {}).get("source_sha256") == src_sha:
            return "skipped"
    except Exception:
        pass

    optimized = optimize(src_bytes)
    sb.storage.from_(BUCKET).upload(
        path=dst_key,
        file=optimized,
        file_options={
            "content-type": "image/webp",
            "cache-control": "public, max-age=604800, immutable",
            "x-upsert": "true",
            "metadata": {"source_sha256": src_sha},
        },
    )
    return "uploaded"

def main():
    counts = {"uploaded": 0, "skipped": 0, "failed": 0}
    for key in list_canonical_obverses():
        try:
            counts[publish_one(key)] += 1
        except Exception as e:
            print(f"FAIL {key}: {e}")
            counts["failed"] += 1
    print(counts)

if __name__ == "__main__":
    main()
```

### 6.2 Wiring app Android

L'URL publique Supabase est stable :

```
https://<project-ref>.supabase.co/storage/v1/object/public/app-coins-public/<numista_id>/obverse.webp
```

Helper dans le snapshot Android (`catalog_snapshot.json`) : juste stocker `<numista_id>` par coin, l'URL est dérivable côté Kotlin.

```kotlin
fun coinObverseUrl(numistaId: String) =
    "https://$SUPABASE_PROJECT.supabase.co/storage/v1/object/public/app-coins-public/$numistaId/obverse.webp"
```

Coil cache HTTP standard fait le job côté app.

### 6.3 Vercel admin : ne pas changer

L'admin web continue de pointer vers l'API ML qui redirect 302 vers MinIO signed URL (chunk 4). **Aucun consumer admin ne lit Supabase Storage en runtime**. C'est ce qui protège le quota egress de la chaîne prod.

### 6.4 Tâche go-task

```yaml
ml:publish-supabase:
  desc: Push canonical obverses (optimized) to Supabase Storage
  cmds: [python -m ml.scripts.publish_to_supabase]
```

À tourner manuellement quand le référentiel canonique change. Pas de cron auto V1.

## Critères d'acceptation

- [ ] Bucket Supabase `app-coins-public` créé en mode public
- [ ] Script publie ~700 obverses en WebP optimisé
- [ ] Taille totale post-opti < 100 MB
- [ ] `curl https://<project>.supabase.co/storage/v1/object/public/app-coins-public/68395/obverse.webp` → 200
- [ ] Re-run idempotent : `skipped == n_total`, `uploaded == 0`, `failed == 0`
- [ ] App Android : un coin random affiche son obverse via cette URL

## Gotchas

- **`info()` API Supabase** : la lib varie selon version. Si pas dispo, fallback : HEAD HTTP sur l'URL publique + lire le header `Etag` ou metadata custom.
- **Metadata custom Supabase** : Supabase storage permet `metadata` dans `file_options`, mais selon la version SDK, peut être ignoré silencieusement. Tester explicitement après le 1er push.
- **Cache busting** : `Cache-Control: immutable` + clé fixe = pas de purge possible côté CDN Supabase. Si une image doit être corrigée, re-push avec sha source différent overwrite, mais le CDN peut servir la vieille version pendant 7 jours. Acceptable.
- **Reverse en V2** : ajouter `<numista_id>/reverse.webp` quand l'UX le demande. Le script publish supporte trivialement (boucler sur les deux faces).
- **Limite Supabase free tier** : 1 GB Storage, 5 GB egress. Le plan Pro est requis dès la mise en prod.

## Anti-objectifs

- ❌ Pas de Vercel pour les images. Cf. push-back acté en vision.
- ❌ Pas de Cloudflare CDN devant MinIO pour l'app prod. La chaîne dev `images.eurio.musubi.dev` reste pour l'admin/Vercel, pas pour Android.
- ❌ Pas d'image-resizing on-the-fly Supabase (payant). Tout est pré-généré au push.
- ❌ Pas de R2 / B2 pour V1.
- ❌ Pas de publication automatique sur write MinIO. Manuel pour V1.
- ❌ Pas de purge côté Supabase. Cache busting via versioning de clé si jamais besoin.
