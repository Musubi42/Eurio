"""Artefacts de modèle de l'APK : publication vers MinIO et récupération.

Les modèles embarqués dans l'APK ne vivent plus dans git (ADR-004). Ils sont
publiés dans le bucket `model-artifacts` et **épinglés par un manifeste
committé**, `shared/model-assets.json`, qui porte pour chaque fichier sa clé
d'objet et son sha256.

Pourquoi un manifeste committé plutôt qu'un « latest » côté serveur : le commit
détermine alors entièrement quels poids partent dans l'APK. Un `git checkout`
d'un commit ancien récupère les modèles de ce commit — la reproductibilité que
donnait le fait de committer les binaires est conservée, sans les binaires.

**Adressage par contenu** : la clé est `models/<nom>/<sha256[:12]>/<fichier>`.
Le versioning S3 étant banni côté MinIO (`infra/minio/README.md`), la version
est portée par la clé. Republier un contenu identique est un no-op ; publier un
contenu différent crée une nouvelle clé et ne peut jamais écraser l'ancienne.

Commandes ::

    python -m scripts.model_assets status    # état local vs manifeste
    python -m scripts.model_assets publish   # upload + réécrit le manifeste
    python -m scripts.model_assets fetch     # télécharge + place dans les assets

Codes de sortie : 0 ok · 1 erreur · 2 dérive détectée (`status`).
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path

from shared.storage import local_cache
from shared.storage.local_cache import ARTIFACTS_BUCKET, sha256_of

_ML_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = _ML_ROOT.parent
MANIFEST_PATH = REPO_ROOT / "shared" / "model-assets.json"

# Les 4 artefacts embarqués dans l'APK. `name` sert de segment de clé ; `dest`
# est relatif à la racine du repo.
#
# NOTE app_core.db n'est PAS ici : `.gitignore` documente le choix délibéré de
# le committer (« reproducible builds without Supabase access ») et il naît de
# Supabase, pas d'un run d'entraînement. Le sortir de git est le même chantier
# que le retrait de Supabase — cf. docs/architecture/README.md.
ASSETS = [
    ("coin_detector", "app-android/src/main/assets/models/coin_detector.tflite"),
    ("eurio_embedder_v1", "app-android/src/main/assets/models/eurio_embedder_v1.tflite"),
    ("coin_embeddings", "app-android/src/main/assets/data/coin_embeddings.json"),
    ("model_meta", "app-android/src/main/assets/data/model_meta.json"),
]


def _key_for(name: str, dest: str, digest: str) -> str:
    return f"models/{name}/{digest[:12]}/{Path(dest).name}"


def _load_manifest() -> dict:
    if not MANIFEST_PATH.exists():
        return {"assets": []}
    return json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))


def _manifest_index(manifest: dict) -> dict[str, dict]:
    return {a["dest"]: a for a in manifest.get("assets", [])}


def _require_credentials() -> None:
    """Sort avec un message actionnable si les creds MinIO ne sont pas dans
    l'environnement.

    Sans ça, l'absence de creds remonte en `KeyError: 'MINIO_ACCESS_KEY'` depuis
    `shared.storage._client()` — illisible, et surtout indiscernable d'un vrai
    problème de bucket ou de policy. Le cas est fréquent : shell non interactif,
    build lancé depuis Android Studio, cron — tous des contextes où direnv n'a
    pas tourné.
    """
    missing = [k for k in ("MINIO_ACCESS_KEY", "MINIO_SECRET_KEY") if k not in os.environ]
    if missing:
        raise SystemExit(
            f"\nerror: {', '.join(missing)} absent(s) de l'environnement.\n"
            f"\nLes secrets vivent dans `secrets/dev.env` (SOPS+age) et sont exportés\n"
            f"par direnv. Si le shell n'a pas direnv (non interactif, Android Studio,\n"
            f"cron), utilise le fallback documenté :\n"
            f"    sops exec-env secrets/dev.env 'go-task ml:assets:fetch'\n"
        )


def _ensure_bucket() -> None:
    """Vérifie l'accès au bucket. Ne le crée PAS : la clé applicative n'a pas
    (et ne doit pas avoir) le droit `CreateBucket`.

    La création est une opération d'administration versionnée dans
    `infra/minio/bootstrap.sh` + `infra/minio/policies/eurio-app-policy.json`,
    à jouer sur le VPS avec les creds admin.
    """
    _require_credentials()
    try:
        local_cache._client().head_bucket(Bucket=ARTIFACTS_BUCKET)
    except Exception as e:  # noqa: BLE001
        status = getattr(e, "response", {}).get("ResponseMetadata", {}).get("HTTPStatusCode")
        if status == 403:
            raise SystemExit(
                f"\nerror: bucket `{ARTIFACTS_BUCKET}` refusé (403) — la clé eurio-app\n"
                f"existe mais sa policy ne couvre pas ce bucket.\n"
                f"Sur le VPS, réapplique la policy versionnée :\n"
                f"    infra/minio/policies/eurio-app-policy.json\n"
            ) from e
        raise SystemExit(
            f"\nerror: bucket `{ARTIFACTS_BUCKET}` inaccessible ({e.__class__.__name__}).\n"
            f"\nLa clé applicative eurio-app ne peut pas créer de bucket — c'est voulu.\n"
            f"Sur le VPS, avec les creds admin :\n"
            f"    cd /opt/eurio/infra/minio && ./bootstrap.sh\n"
            f"Le script est idempotent : il crée `{ARTIFACTS_BUCKET}` s'il manque et\n"
            f"réapplique la policy (qui l'inclut depuis 2026-08-14).\n"
        ) from e


# ─── status ──────────────────────────────────────────────────────────────────

def cmd_status(_args) -> int:
    index = _manifest_index(_load_manifest())
    drift = 0
    for name, dest in ASSETS:
        path = REPO_ROOT / dest
        entry = index.get(dest)
        if not path.exists():
            state = "absent du disque"
            drift += 1 if entry is None else 0
        else:
            digest = sha256_of(path)
            if entry is None:
                state = f"NON PUBLIÉ (sha {digest[:12]})"
                drift += 1
            elif entry["sha256"] != digest:
                state = f"DÉRIVE — disque {digest[:12]} ≠ manifeste {entry['sha256'][:12]}"
                drift += 1
            else:
                state = f"à jour ({digest[:12]})"
        print(f"  {name:20} {state}")
    if drift:
        print(f"\n{drift} artefact(s) à publier — `go-task ml:assets:publish`")
        return 2
    return 0


# ─── publish ─────────────────────────────────────────────────────────────────

def cmd_publish(args) -> int:
    _ensure_bucket()
    client = local_cache._client()
    entries, uploaded, skipped = [], 0, 0

    for name, dest in ASSETS:
        path = REPO_ROOT / dest
        if not path.exists():
            print(f"  ✗ {name}: {dest} absent — rien à publier", file=sys.stderr)
            return 1
        digest = sha256_of(path)
        key = _key_for(name, dest, digest)
        size = path.stat().st_size

        exists = True
        try:
            client.head_object(Bucket=ARTIFACTS_BUCKET, Key=key)
        except Exception:  # noqa: BLE001
            exists = False

        if exists:
            print(f"  = {name:20} déjà publié ({digest[:12]})")
            skipped += 1
        elif args.dry_run:
            print(f"  + {name:20} À PUBLIER {key} ({size/1e6:.1f} Mo)")
        else:
            client.upload_file(str(path), ARTIFACTS_BUCKET, key)
            print(f"  ↑ {name:20} publié {key} ({size/1e6:.1f} Mo)")
            uploaded += 1

        entries.append({"dest": dest, "key": key, "sha256": digest, "size": size})

    if args.dry_run:
        print("\n(dry-run — manifeste non réécrit)")
        return 0

    manifest = {
        "_comment": (
            "Épingle les artefacts de modèle de l'APK. Généré par "
            "`go-task ml:assets:publish` — ne pas éditer à la main. "
            "Le build Android les récupère via `go-task ml:assets:fetch`."
        ),
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "bucket": ARTIFACTS_BUCKET,
        "assets": entries,
    }
    MANIFEST_PATH.parent.mkdir(parents=True, exist_ok=True)
    MANIFEST_PATH.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    print(f"\n✓ {uploaded} publié(s), {skipped} déjà présent(s)")
    print(f"✓ manifeste écrit : {MANIFEST_PATH.relative_to(REPO_ROOT)}")
    print("  → committe-le avec le code qui l'utilise (il épingle la version).")
    return 0


# ─── fetch ───────────────────────────────────────────────────────────────────

def cmd_fetch(_args) -> int:
    manifest = _load_manifest()
    entries = manifest.get("assets", [])
    if not entries:
        print(
            f"error: manifeste vide ou absent ({MANIFEST_PATH}).\n"
            f"Lance `go-task ml:assets:publish` depuis une machine qui a les "
            f"artefacts sur disque.",
            file=sys.stderr,
        )
        return 1

    placed = fresh = 0
    for entry in entries:
        dest = REPO_ROOT / entry["dest"]
        if dest.exists() and sha256_of(dest) == entry["sha256"]:
            print(f"  = {entry['dest']} déjà conforme")
            fresh += 1
            continue
        # Seulement ici : un fetch dont tout est déjà conforme ne doit exiger ni
        # réseau ni creds — c'est ce qui rend le branchement sur `preBuild` sûr.
        _require_credentials()
        cached = local_cache.artifact_path(entry["key"], sha256=entry["sha256"])
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(cached, dest)
        print(f"  ↓ {entry['dest']} ({entry['size']/1e6:.1f} Mo)")
        placed += 1

    print(f"\n✓ {placed} récupéré(s), {fresh} déjà à jour")
    return 0


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(prog="model_assets", description=__doc__)
    sub = parser.add_subparsers(dest="cmd", required=True)
    sub.add_parser("status", help="compare disque et manifeste")
    p_pub = sub.add_parser("publish", help="upload vers MinIO + réécrit le manifeste")
    p_pub.add_argument("--dry-run", action="store_true")
    sub.add_parser("fetch", help="télécharge et place les artefacts dans les assets")
    args = parser.parse_args(argv)
    return {"status": cmd_status, "publish": cmd_publish, "fetch": cmd_fetch}[args.cmd](args)


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
