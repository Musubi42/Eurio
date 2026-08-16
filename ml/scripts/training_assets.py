"""Artefacts d'entraînement : ce dont une machine de compute a besoin, hors git.

Pendant que `model_assets.py` gère ce que l'**APK embarque**, ce module gère ce
qu'une machine doit recevoir pour **ré-entraîner** : le dataset de détection et
les poids du détecteur. Même principe qu'ADR-004 — bucket MinIO, adressage par
contenu, manifeste committé (`shared/training-assets.json`) — mais l'unité
n'est plus seulement un fichier : c'est aussi un **arbre de fichiers**.

Pourquoi c'est nécessaire (mesuré le 2026-08-16) : git ne transporte que les
3 788 labels `.txt`, **aucune image**. Les 1 908 images (67 Mo, dont nos 30
négatifs irremplaçables) n'existaient que sur un seul disque. Les labels
arrivaient au PC sans ce qu'ils annotent.

**Identité d'un arbre.** Elle ne vient pas du sha de l'archive : un tar n'est
pas reproductible par défaut (ordre, mtime, uid), donc deux publications du
même contenu créeraient deux clés. L'identité est un `tree_digest` calculé sur
le **contenu seul** ::

    sha256( concat, trié par chemin, de "<chemin relatif>\\0<sha256 du fichier>\\n" )

L'archive n'est qu'un conteneur de transport ; elle est tout de même produite
de façon déterministe (entrées triées, mtime/uid/gid neutralisés, modes
normalisés) pour que republier un contenu identique soit un vrai no-op.

Commandes ::

    python -m scripts.training_assets status
    python -m scripts.training_assets publish [--dry-run]
    python -m scripts.training_assets fetch

Codes de sortie : 0 ok · 1 erreur · 2 dérive détectée (`status`).
"""

from __future__ import annotations

import argparse
import gzip
import hashlib
import io
import json
import os
import shutil
import sys
import tarfile
import tempfile
from datetime import datetime, timezone
from pathlib import Path

from shared.storage import local_cache
from shared.storage.local_cache import ARTIFACTS_BUCKET, sha256_of

_ML_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = _ML_ROOT.parent
MANIFEST_PATH = REPO_ROOT / "shared" / "training-assets.json"

# `kind` vaut "tree" (dossier → archive) ou "file" (fichier tel quel).
# `dest` est relatif à la racine du dépôt.
ASSETS: list[tuple[str, str, str]] = [
    ("detection_dataset", "tree", "ml/datasets/detection"),
    ("coin_detector_weights", "file", "ml/output/detection/coin_detector/weights/best.pt"),
]

# Résidus d'outils qui n'appartiennent pas au contenu du dataset. Les inclure
# rendrait le tree_digest dépendant de la machine qui publie.
_EXCLUDED_NAMES = {".DS_Store", "Thumbs.db"}
_EXCLUDED_DIRS = {"__pycache__", ".ipynb_checkpoints"}


# ─── identité ────────────────────────────────────────────────────────────────

def _iter_tree(root: Path):
    """Fichiers de l'arbre, triés par chemin relatif POSIX, résidus exclus."""
    files = []
    for p in root.rglob("*"):
        if p.is_dir():
            continue
        if p.name in _EXCLUDED_NAMES:
            continue
        if any(part in _EXCLUDED_DIRS for part in p.relative_to(root).parts):
            continue
        if p.is_symlink():
            raise SystemExit(
                f"error: {p} est un lien symbolique. Un artefact rapatriable ne "
                f"peut pas en contenir — il casserait au déballage sur une autre "
                f"machine."
            )
        files.append(p)
    return sorted(files, key=lambda p: p.relative_to(root).as_posix())


def _tree_digest(root: Path) -> tuple[str, int, int]:
    """(digest, nombre de fichiers, octets) — dépend du contenu, pas du tar."""
    h = hashlib.sha256()
    n = size = 0
    for p in _iter_tree(root):
        rel = p.relative_to(root).as_posix()
        h.update(rel.encode("utf-8"))
        h.update(b"\0")
        h.update(sha256_of(p).encode("ascii"))
        h.update(b"\n")
        n += 1
        size += p.stat().st_size
    return h.hexdigest(), n, size


def _content_digest(kind: str, path: Path) -> tuple[str, int, int]:
    if kind == "file":
        return sha256_of(path), 1, path.stat().st_size
    return _tree_digest(path)


# ─── archive déterministe ────────────────────────────────────────────────────

def _make_archive(root: Path, out: Path) -> None:
    """tar.gz reproductible : entrées triées, mtime/uid/gid neutres, modes fixes.

    Le gzip est écrit à part avec `mtime=0` — `tarfile` en mode "w:gz" y mettrait
    l'heure courante, ce qui suffirait à changer le sha de l'archive à chaque
    publication d'un contenu pourtant identique.
    """
    raw = io.BytesIO()
    with tarfile.open(fileobj=raw, mode="w", format=tarfile.PAX_FORMAT) as tar:
        for p in _iter_tree(root):
            info = tar.gettarinfo(str(p), arcname=p.relative_to(root).as_posix())
            info.mtime = 0
            info.uid = info.gid = 0
            info.uname = info.gname = ""
            info.mode = 0o644
            with p.open("rb") as fh:
                tar.addfile(info, fh)
    out.parent.mkdir(parents=True, exist_ok=True)
    # `filename=""` est indispensable : sans lui, GzipFile déduit un nom du
    # `fileobj` et l'écrit dans le champ FNAME de l'en-tête gzip. Le sha de
    # l'archive dépendrait alors du nom du fichier temporaire — vérifié, ça
    # produisait deux sha différents pour un tar strictement identique.
    with out.open("wb") as fh, gzip.GzipFile(filename="", fileobj=fh, mode="wb", mtime=0) as gz:
        gz.write(raw.getvalue())


def _extract_archive(archive: Path, dest: Path) -> None:
    with tarfile.open(archive, mode="r:gz") as tar:
        for member in tar.getmembers():
            # Un tar hostile peut viser hors du dossier cible. Le dataset vient
            # de notre bucket, mais la garde coûte trois lignes.
            target = (dest / member.name).resolve()
            if not str(target).startswith(str(dest.resolve()) + os.sep):
                raise SystemExit(f"error: entrée d'archive hors périmètre : {member.name}")
            if not (member.isfile() or member.isdir()):
                raise SystemExit(f"error: entrée d'archive non régulière : {member.name}")
        # `filter="data"` : refuse liens, périphériques et métadonnées exotiques.
        # Ce sera le défaut en 3.14 ; l'expliciter évite un changement de
        # comportement silencieux à la montée de version.
        tar.extractall(dest, filter="data")


# ─── manifeste ───────────────────────────────────────────────────────────────

def _load_manifest() -> dict:
    if not MANIFEST_PATH.exists():
        return {"assets": []}
    return json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))


def _index(manifest: dict) -> dict[str, dict]:
    return {a["dest"]: a for a in manifest.get("assets", [])}


def _key_for(name: str, kind: str, dest: str, digest: str) -> str:
    leaf = f"{name}.tar.gz" if kind == "tree" else Path(dest).name
    return f"training/{name}/{digest[:12]}/{leaf}"


def _require_credentials() -> None:
    missing = [k for k in ("MINIO_ACCESS_KEY", "MINIO_SECRET_KEY") if k not in os.environ]
    if missing:
        raise SystemExit(
            f"\nerror: {', '.join(missing)} absent(s) de l'environnement.\n"
            f"\nLes secrets vivent dans `secrets/dev.env` (SOPS+age) et sont exportés\n"
            f"par direnv. Hors shell interactif :\n"
            f"    sops exec-env secrets/dev.env 'go-task ml:training-assets:fetch'\n"
        )


# ─── status ──────────────────────────────────────────────────────────────────

def cmd_status(_args) -> int:
    index = _index(_load_manifest())
    drift = 0
    for name, kind, dest in ASSETS:
        path = REPO_ROOT / dest
        entry = index.get(dest)
        if not path.exists():
            if entry is None:
                print(f"  {name:24} absent du disque, jamais publié")
                drift += 1
            else:
                print(f"  {name:24} absent du disque — `training-assets:fetch` le rapatrie")
            continue
        digest, n, size = _content_digest(kind, path)
        if entry is None:
            print(f"  {name:24} NON PUBLIÉ ({n} fichiers, {size/1e6:.1f} Mo, {digest[:12]})")
            drift += 1
        elif entry["content_digest"] != digest:
            # Une dérive est ambiguë : le disque peut être EN AVANCE (à publier)
            # ou INCOMPLET (à rapatrier). Ne jamais suggérer `publish` par défaut
            # — sur une machine au dataset appauvri, ça écraserait le manifeste
            # avec une version pire. Vécu sur le PC le 2026-08-16 : 0 image sur
            # disque, et le message d'alors disait « à publier ».
            delta = n - entry["n_files"]
            sense = (
                "disque INCOMPLET" if delta < 0
                else "disque EN AVANCE" if delta > 0
                else "contenu MODIFIÉ à nombre de fichiers égal"
            )
            print(
                f"  {name:24} DÉRIVE, {sense} — disque {digest[:12]} "
                f"({n} fichiers) ≠ manifeste {entry['content_digest'][:12]} "
                f"({entry['n_files']} fichiers)"
            )
            drift += 1
        else:
            print(f"  {name:24} à jour ({n} fichiers, {size/1e6:.1f} Mo, {digest[:12]})")
    if drift:
        print(
            f"\n{drift} artefact(s) en écart. Choisis selon le sens :\n"
            f"  · le disque fait autorité  → `go-task ml:training-assets:publish`\n"
            f"  · le manifeste fait autorité → `go-task ml:training-assets:fetch`"
        )
        return 2
    return 0


# ─── publish ─────────────────────────────────────────────────────────────────

def cmd_publish(args) -> int:
    _require_credentials()
    client = local_cache._client()
    previous = _index(_load_manifest())
    entries: list[dict] = []
    uploaded = skipped = 0

    with tempfile.TemporaryDirectory(prefix="eurio-training-assets-") as tmpdir:
        for name, kind, dest in ASSETS:
            path = REPO_ROOT / dest
            if not path.exists():
                print(f"  ✗ {name}: {dest} absent — rien à publier", file=sys.stderr)
                return 1

            digest, n_files, size = _content_digest(kind, path)
            key = _key_for(name, kind, dest, digest)

            exists = True
            try:
                client.head_object(Bucket=ARTIFACTS_BUCKET, Key=key)
            except Exception:  # noqa: BLE001
                exists = False

            if kind == "file":
                object_sha, object_size = digest, size
            else:
                archive = Path(tmpdir) / f"{name}.tar.gz"
                if exists and (prev := previous.get(dest)) and prev.get("content_digest") == digest:
                    # Contenu déjà publié : pas besoin de reconstruire l'archive
                    # pour retrouver son sha, le manifeste précédent le porte.
                    object_sha, object_size = prev["object_sha256"], prev["object_size"]
                else:
                    _make_archive(path, archive)
                    object_sha, object_size = sha256_of(archive), archive.stat().st_size

            if exists:
                print(f"  = {name:24} déjà publié ({digest[:12]})")
                skipped += 1
            elif args.dry_run:
                print(
                    f"  + {name:24} À PUBLIER {key} "
                    f"({n_files} fichiers, {object_size/1e6:.1f} Mo transportés)"
                )
            else:
                src = path if kind == "file" else Path(tmpdir) / f"{name}.tar.gz"
                client.upload_file(str(src), ARTIFACTS_BUCKET, key)
                print(f"  ↑ {name:24} publié {key} ({object_size/1e6:.1f} Mo)")
                uploaded += 1

            entries.append(
                {
                    "name": name,
                    "kind": kind,
                    "dest": dest,
                    "key": key,
                    "content_digest": digest,
                    "n_files": n_files,
                    "content_size": size,
                    "object_sha256": object_sha,
                    "object_size": object_size,
                }
            )

    if args.dry_run:
        print("\n(dry-run — manifeste non réécrit)")
        return 0

    # Une publication sans changement ne doit pas salir `git status` : sans
    # cette garde, `generated_at` seul suffirait à produire un diff à chaque
    # appel, et on prendrait l'habitude d'ignorer un manifeste modifié.
    if MANIFEST_PATH.exists() and _load_manifest().get("assets") == entries:
        print(f"\n✓ 0 publié(s), {skipped} déjà présent(s)")
        print(f"= manifeste inchangé : {MANIFEST_PATH.relative_to(REPO_ROOT)}")
        return 0

    MANIFEST_PATH.parent.mkdir(parents=True, exist_ok=True)
    MANIFEST_PATH.write_text(
        json.dumps(
            {
                "_comment": (
                    "Épingle les artefacts nécessaires à un ré-entraînement. Généré par "
                    "`go-task ml:training-assets:publish` — ne pas éditer à la main. "
                    "Une machine de compute les rapatrie via "
                    "`go-task ml:training-assets:fetch`."
                ),
                "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                "bucket": ARTIFACTS_BUCKET,
                "assets": entries,
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    print(f"\n✓ {uploaded} publié(s), {skipped} déjà présent(s)")
    print(f"✓ manifeste écrit : {MANIFEST_PATH.relative_to(REPO_ROOT)}")
    print("  → committe-le : c'est lui qui épingle la version du dataset.")
    return 0


# ─── fetch ───────────────────────────────────────────────────────────────────

def _place_tree(entry: dict, dest: Path) -> None:
    """Déballe dans un dossier voisin, vérifie, puis échange. L'ancien contenu
    n'est retiré qu'après une vérification réussie — un déballage interrompu ne
    doit jamais laisser un dataset à moitié écrasé.
    """
    _require_credentials()
    archive = local_cache.artifact_path(entry["key"], sha256=entry["object_sha256"])
    incoming = dest.with_name(dest.name + ".incoming")
    if incoming.exists():
        shutil.rmtree(incoming)
    incoming.mkdir(parents=True)
    try:
        _extract_archive(archive, incoming)
        got, n, _ = _tree_digest(incoming)
        if got != entry["content_digest"]:
            raise SystemExit(
                f"error: contenu déballé non conforme pour {entry['dest']} — "
                f"attendu {entry['content_digest'][:12]}, obtenu {got[:12]}. "
                f"Rien n'a été remplacé."
            )
        if n != entry["n_files"]:
            raise SystemExit(
                f"error: {n} fichiers déballés, {entry['n_files']} attendus. "
                f"Rien n'a été remplacé."
            )
        aside = dest.with_name(dest.name + f".replaced-{os.getpid()}")
        if dest.exists():
            dest.rename(aside)
        try:
            incoming.rename(dest)
        except Exception:
            if aside.exists():
                aside.rename(dest)
            raise
        if aside.exists():
            shutil.rmtree(aside)
    finally:
        if incoming.exists():
            shutil.rmtree(incoming, ignore_errors=True)


def cmd_fetch(_args) -> int:
    entries = _load_manifest().get("assets", [])
    if not entries:
        print(
            f"error: manifeste vide ou absent ({MANIFEST_PATH}).\n"
            f"Lance `go-task ml:training-assets:publish` depuis une machine qui a "
            f"les artefacts sur disque.",
            file=sys.stderr,
        )
        return 1

    placed = fresh = 0
    for entry in entries:
        dest = REPO_ROOT / entry["dest"]
        kind = entry["kind"]
        if dest.exists():
            current, _, _ = _content_digest(kind, dest)
            if current == entry["content_digest"]:
                print(f"  = {entry['dest']} déjà conforme")
                fresh += 1
                continue
        if kind == "file":
            _require_credentials()
            cached = local_cache.artifact_path(entry["key"], sha256=entry["object_sha256"])
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(cached, dest)
        else:
            _place_tree(entry, dest)
        print(f"  ↓ {entry['dest']} ({entry['n_files']} fichiers, {entry['content_size']/1e6:.1f} Mo)")
        placed += 1

    print(f"\n✓ {placed} récupéré(s), {fresh} déjà à jour")
    return 0


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(prog="training_assets", description=__doc__)
    sub = parser.add_subparsers(dest="cmd", required=True)
    sub.add_parser("status", help="compare disque et manifeste")
    p = sub.add_parser("publish", help="upload vers MinIO + réécrit le manifeste")
    p.add_argument("--dry-run", action="store_true")
    sub.add_parser("fetch", help="rapatrie les artefacts épinglés")
    args = parser.parse_args(argv)
    return {"status": cmd_status, "publish": cmd_publish, "fetch": cmd_fetch}[args.cmd](args)


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
