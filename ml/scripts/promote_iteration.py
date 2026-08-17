"""Promote a lab iteration to ``ml/prod/current/`` (phase 3, lab-prod-refacto).

Une seule action déclenche : copie atomique des artefacts lab → prod,
backup de la prod précédente sous ``prod/archive/``, écriture de
``promoted_from.json`` (avec sha256), puis push Supabase via
``seed_supabase.py``.

Usage::

    .venv/bin/python -m scripts.promote_iteration <iteration_id>
    .venv/bin/python -m scripts.promote_iteration <iid> --dry-run
    .venv/bin/python -m scripts.promote_iteration <iid> --force
    .venv/bin/python -m scripts.promote_iteration <iid> --replace-all

Voir ``docs/lab-prod-refacto/phase-3-promote.md`` pour la sémantique
complète (Option B équivalence, accumulate par défaut, lock concurrent).
"""

from __future__ import annotations

import argparse
import contextlib
import getpass
import hashlib
import json
import logging
import os
import shutil
import subprocess
import sys
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path

ML_DIR = Path(__file__).parent.parent
if str(ML_DIR) not in sys.path:
    sys.path.insert(0, str(ML_DIR))

from store import Store, resolve_db_path  # noqa: E402

LAB_ITERATIONS_DIR = ML_DIR / "lab" / "iterations"
PROD_DIR = ML_DIR / "prod"
PROD_CURRENT = PROD_DIR / "current"
PROD_ARCHIVE = PROD_DIR / "archive"
PROD_LOCK = PROD_DIR / ".promote.lock"
# Même DB que le serveur et que les entrypoints détachés (`training/run_*.py`) :
# `EURIO_DB_PATH` d'abord, `state/eurio.db` en repli. Le chemin était codé en dur
# ici, ce qui rendait la promotion IMPOSSIBLE dès que l'itération avait été
# calculée ailleurs — le mode compute du flip Direction A écrit dans
# `state/eurio.work.db`, et `promote_iteration <iid>` répondait « not found in
# …/eurio.db » alors que le modèle et ses artefacts étaient complets sur disque.
STATE_DB = resolve_db_path(ML_DIR / "state" / "eurio.db")
VENV_PYTHON = str(ML_DIR / ".venv" / "bin" / "python")
# L'asset RÉELLEMENT embarqué dans l'APK — l'état de production observable
# quand `ml/prod/` n'existe pas sur cette machine. Clé = `numista_id` (c'est
# `EmbeddingMatcher` qui le lit, et c'est lui qui décide ce que l'app reconnaît).
APK_EMBEDDINGS = (
    ML_DIR.parent / "app-android" / "src" / "main" / "assets" / "data"
    / "coin_embeddings.json"
)

VALID_VERDICTS = {"baseline", "better"}
ARTIFACT_SUBDIRS = ("checkpoints", "embeddings", "tflite")
# Tables que `bootstrap/seed_supabase.py` upserte. Vérifiées AVANT toute
# écriture locale : au 2026-08-17 elles n'existent pas dans le projet ciblé.
SUPABASE_MODEL_TABLES = ("model_classes", "coin_embeddings")

logger = logging.getLogger("promote")


def _iso_now() -> str:
    return (
        datetime.now(timezone.utc)
        .replace(microsecond=0)
        .isoformat()
        .replace("+00:00", "Z")
    )


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _hash_tree(root: Path) -> dict[str, str]:
    """sha256 every regular file under root, keyed by repo-relative path."""
    out: dict[str, str] = {}
    for p in sorted(root.rglob("*")):
        if p.is_file():
            out[str(p.relative_to(root))] = _sha256(p)
    return out


@contextlib.contextmanager
def _promote_lock():
    """File lock — bails out if another promotion is in flight.

    Cf. phase-3-promote.md §"Pièges à éviter — Supabase eventually
    consistent". Si plusieurs promotions s'enchaînent, l'ordre des
    PATCH/POST/DELETE peut donner un état intermédiaire incohérent.
    """
    PROD_DIR.mkdir(parents=True, exist_ok=True)
    if PROD_LOCK.exists():
        try:
            pid = int(PROD_LOCK.read_text().strip())
        except (ValueError, OSError):
            pid = -1
        raise SystemExit(
            f"Promotion already in flight (lock {PROD_LOCK} owned by pid {pid}). "
            "Si le processus est mort, supprime le fichier à la main."
        )
    PROD_LOCK.write_text(str(os.getpid()))
    try:
        yield
    finally:
        with contextlib.suppress(FileNotFoundError):
            PROD_LOCK.unlink()


def _warn_force(message: str) -> None:
    """Un override doit être BRUYANT. stderr, pas logging : le script est lu à
    travers un pipe qui ne garde souvent que la queue de stdout (le JSON)."""
    print(f"⚠️  {message}", file=sys.stderr, flush=True)


def _validate_iteration(iid: str, *, force: bool) -> dict:
    """Check that the iteration exists, is completed, and has a valid verdict."""
    store = Store(STATE_DB)
    it = store.get_iteration(iid)
    if it is None:
        raise SystemExit(
            f"Iteration {iid} not found in {STATE_DB} "
            f"(EURIO_DB_PATH={os.environ.get('EURIO_DB_PATH') or '<absent>'}). "
            "Si l'itération a été calculée sous un autre EURIO_DB_PATH (mode "
            "compute, réplique…), relance la promotion avec le même."
        )
    # `--force` couvre TROIS contrôles à la fois (statut, verdict, traçabilité).
    # Quelqu'un qui le pose pour un verdict `pending` désarme la traçabilité sans
    # le savoir. On enregistre donc ce qu'il a réellement désarmé, et on le crie.
    force_overrides: list[str] = []
    if it.status != "completed":
        if not force:
            raise SystemExit(
                f"Iteration {iid} is status={it.status!r}, expected 'completed' "
                "(use --force to override)."
            )
        force_overrides.append("status")
        _warn_force(
            f"--force : statut={it.status!r} (attendu 'completed') — promotion "
            "d'une itération non terminée."
        )
    verdict = it.verdict_override or it.verdict
    if verdict not in VALID_VERDICTS:
        if not force:
            raise SystemExit(
                f"Iteration {iid} verdict={verdict!r}, expected one of "
                f"{sorted(VALID_VERDICTS)} (use --force to override)."
            )
        force_overrides.append("verdict")
        _warn_force(
            f"--force : verdict={verdict!r} (attendu {sorted(VALID_VERDICTS)}) — "
            "aucun benchmark ne soutient cette promotion."
        )
    # Promouvoir depuis une base qui ne porte pas le run, c'est perdre la
    # traçabilité en silence : `promoted_from.json` enregistrerait
    # `training_run_id: null`, et plus rien ne relierait le modèle en prod à ce
    # qui l'a produit. Le cas est atteignable sans le vouloir — le devShell
    # pointe `EURIO_DB_PATH` sur la RÉPLIQUE.
    #
    # ⚠️ Le message disait que la réplique « n'a jamais reçu les tables de run ».
    # C'est FAUX : mesuré le 2026-08-17, elle porte 34 `training_runs`, et des
    # itérations `completed` y gardent leur lien. Le vrai mécanisme est au
    # canonique — `serving/iteration_sync_routes.py:126-129` annule le lien AU
    # CAS PAR CAS, quand la ligne de run ne lui a pas été poussée :
    #     if data.get("training_run_id") and store.get_run(...) is None:
    #         data["training_run_id"] = None
    # Corollaire : « promeus depuis la base de calcul » n'est pas toujours une
    # sortie — le 2026-08-17, 3 itérations `completed` étaient sans run dans les
    # DEUX bases. D'où le libellé prudent ci-dessous.
    if it.training_run_id is None:
        if not force:
            raise SystemExit(
                f"Iteration {iid} est 'completed' mais SANS training_run_id dans "
                f"{STATE_DB}. Le lien vers le run a été annulé au cas par cas "
                "par le canonique à la synchro (serving/iteration_sync_routes.py"
                ":126-129 : le run référencé ne lui avait pas été poussé), ou "
                "n'a jamais existé. Essaie la base de CALCUL, celle où "
                "l'entraînement a tourné : EURIO_DB_PATH=<…/eurio.work*.db> — "
                "mais elle peut refuser aussi (mesuré : 3 itérations sans run "
                "des deux côtés). --force passe outre, au prix d'un "
                "promoted_from.json avec training_run_id: null."
            )
        force_overrides.append("traceability")
        _warn_force(
            "--force : TRAÇABILITÉ DÉSARMÉE — training_run_id est NULL dans "
            f"{STATE_DB}. `promoted_from.json` sera écrit avec "
            "training_run_id: null : rien ne reliera le modèle en production "
            "au run qui l'a produit."
        )
    iter_dir = LAB_ITERATIONS_DIR / iid
    missing = [
        sub for sub in ARTIFACT_SUBDIRS
        if not (iter_dir / sub).is_dir()
        or not any((iter_dir / sub).iterdir())
    ]
    if missing:
        raise SystemExit(
            f"Iteration {iid} missing artifact dirs: {missing}. "
            f"Expected non-empty under {iter_dir}/. "
            "Re-run training before promoting."
        )
    return {
        "id": it.id,
        "name": it.name,
        "cohort_id": it.cohort_id,
        "status": it.status,
        "verdict": verdict,
        "training_run_id": it.training_run_id,
        "benchmark_run_id": it.benchmark_run_id,
        "force_overrides": force_overrides,
        "iter_dir": iter_dir,
    }


def _apk_numista_ids() -> set[str]:
    """Les numista_id que l'APK reconnaît aujourd'hui (asset embarqué)."""
    data = json.loads(APK_EMBEDDINGS.read_text())
    if isinstance(data, dict) and isinstance(data.get("coins"), dict):
        data = data["coins"]
    return {str(k) for k in data}


def _diff_classes(iter_dir: Path) -> dict:
    """Ce que la promotion AJOUTE et ce qu'elle FAIT PERDRE, contre une référence.

    La promotion REMPLACE : les entrées listées `absent_in_promotion` sont
    exactement celles que l'app cessera de reconnaître.

    Le choix de la référence, du plus fidèle au moins fidèle :

    1. ``prod/current/embeddings/embeddings_v1.json`` — la prod locale, espace
       `class_id`. C'est la comparaison exacte quand elle est disponible.
    2. À défaut, l'asset **réellement embarqué dans l'APK**
       (``app-android/.../coin_embeddings.json``), espace `numista_id`. C'est
       un espace d'identifiants différent, donc une comparaison approchée — mais
       c'est l'état RÉEL de la production, et il est disponible sur toutes les
       machines du repo. `numista_ids` est porté par chaque classe de
       `embeddings_v1.json`, la traduction est donc exacte dans ce sens.
    3. Aucune des deux : le diff est **aveugle** et le dit (`blind: True`,
       champs à `None`). Il ne renvoie SURTOUT pas `absent_in_promotion: []`.

    L'ancien code prenait `set()` comme référence quand `prod/current` manquait :
    `absent_in_promotion` valait alors TOUJOURS `[]`. Sur le Mac, où `ml/prod/`
    n'existe pas, le dry-run de `4aaac6865ca9` annonçait « rien de perdu » alors
    que la comparaison à l'asset de l'APK donne 16 pièces perdues sur 23. Un
    défaut plausible (la liste vide) là où il fallait un aveu d'ignorance.
    """
    new_path = iter_dir / "embeddings" / "embeddings_v1.json"
    new_coins = json.loads(new_path.read_text()).get("coins", {})

    cur_path = PROD_CURRENT / "embeddings" / "embeddings_v1.json"
    reference = "none"
    id_space = None
    reference_path = None
    new_ids: set[str] = set()
    cur_ids: set[str] = set()

    if cur_path.exists():
        reference, id_space, reference_path = "prod_current", "class_id", cur_path
        new_ids = {str(k) for k in new_coins}
        cur_ids = {str(k) for k in json.loads(cur_path.read_text()).get("coins", {})}
    elif APK_EMBEDDINGS.exists():
        new_ids = {
            str(nid)
            for payload in new_coins.values()
            if isinstance(payload, dict)
            for nid in (payload.get("numista_ids") or [])
        }
        if new_ids:
            reference, id_space = "apk_asset", "numista_id"
            reference_path = APK_EMBEDDINGS
            cur_ids = _apk_numista_ids()

    if reference == "none":
        # Ni prod locale, ni asset APK exploitable : on ne sait pas ce qui se
        # perd. `None` — jamais `[]`, qui se lirait « rien ne se perd ».
        return {
            "reference": "none",
            "reference_path": None,
            "id_space": None,
            "blind": True,
            "added": None,
            "kept": None,
            "absent_in_promotion": None,
            "n_new": len(new_coins),
            "n_current": None,
        }

    return {
        "reference": reference,
        "reference_path": str(reference_path),
        "id_space": id_space,
        "blind": False,
        "added": sorted(new_ids - cur_ids),
        "kept": sorted(new_ids & cur_ids),
        "absent_in_promotion": sorted(cur_ids - new_ids),
        "n_new": len(new_ids),
        "n_current": len(cur_ids),
    }


def _atomic_copy(src_iter_dir: Path, dest_dir: Path) -> None:
    """Copy iter_dir/{checkpoints,embeddings,tflite}/ → dest_dir/, atomically.

    The atomic guarantee : we build the full new tree under a sibling
    ``<dest>.new-<ts>/`` directory, then ``os.replace`` it onto dest_dir
    after backing dest_dir up. A concurrent reader sees either the old
    tree or the new one — never a half-written one.
    """
    dest_dir.parent.mkdir(parents=True, exist_ok=True)
    staging = dest_dir.parent / f"{dest_dir.name}.new-{int(time.time() * 1000)}"
    if staging.exists():
        shutil.rmtree(staging)
    staging.mkdir(parents=True)
    for sub in ARTIFACT_SUBDIRS:
        shutil.copytree(src_iter_dir / sub, staging / sub)
    # os.replace is atomic on POSIX for same-filesystem renames. We move
    # the old dest aside first (already done by caller via _archive), so
    # this rename is into a non-existent path.
    os.replace(staging, dest_dir)


def _archive_current(promoted_from_iid: str | None) -> Path | None:
    """Move PROD_CURRENT → PROD_ARCHIVE/<previous_iid>-<timestamp>/.

    Returns the archive path, or None if there was nothing to archive.
    """
    if not PROD_CURRENT.exists():
        return None
    PROD_ARCHIVE.mkdir(parents=True, exist_ok=True)
    label = promoted_from_iid or "unknown"
    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    target = PROD_ARCHIVE / f"{label}-{ts}"
    # Defensive : if the same-second target exists (very unlikely), append a
    # microsecond suffix so we never collide.
    while target.exists():
        target = PROD_ARCHIVE / f"{label}-{ts}-{int(time.time_ns())}"
    shutil.move(str(PROD_CURRENT), str(target))
    logger.info("Archived previous prod → %s", target)
    return target


def _read_prev_iid() -> str | None:
    meta = PROD_CURRENT / "promoted_from.json"
    if not meta.exists():
        return None
    try:
        return json.loads(meta.read_text()).get("iteration_id")
    except (json.JSONDecodeError, OSError):
        return None


def _write_promoted_from(iter_meta: dict, hashes: dict[str, str]) -> Path:
    payload = {
        "iteration_id": iter_meta["id"],
        "iteration_name": iter_meta["name"],
        "cohort_id": iter_meta["cohort_id"],
        "training_run_id": iter_meta["training_run_id"],
        "benchmark_run_id": iter_meta["benchmark_run_id"],
        "verdict": iter_meta["verdict"],
        # Trace de ce que `--force` a réellement désarmé (statut / verdict /
        # traçabilité). Sans ça, un promoted_from.json avec
        # `training_run_id: null` ne dit pas si c'était un accident ou un choix.
        "force_overrides": iter_meta.get("force_overrides", []),
        "promoted_at": _iso_now(),
        "promoted_by": getpass.getuser(),
        "sha256": hashes,
    }
    out = PROD_CURRENT / "promoted_from.json"
    out.write_text(json.dumps(payload, indent=2, sort_keys=True))
    return out


def _supabase_credentials() -> tuple[str, str]:
    from training.eval.class_resolver import load_env

    env = load_env()
    url = env.get("SUPABASE_URL", "")
    key = env.get("SUPABASE_SERVICE_ROLE_KEY", "")
    if not url or not key:
        raise SystemExit(
            "Push Supabase demandé mais SUPABASE_URL / "
            "SUPABASE_SERVICE_ROLE_KEY sont absents de l'environnement "
            "(devShell + secrets/dev.env). Utilise --no-supabase pour "
            "promouvoir en local seulement."
        )
    return url, key


def _check_supabase_target() -> None:
    """Préflight : la cible Supabase existe-t-elle, AVANT le point de non-retour ?

    `promote()` remplaçait `prod/current` puis poussait Supabase. Or les deux
    tables upsertées par `bootstrap/seed_supabase.py` n'existent pas dans le
    projet ciblé (2026-08-17, `to_regclass` → null pour les deux ; le projet
    porte la projection catalogue `coin`/`design_group`/`sets`). La promotion
    réussissait donc localement puis plantait : état à moitié promu, sans que
    rien ne le dise. On vérifie ici, avant tout écrasement.

    Aucune DDL n'est émise : créer ces tables serait une modification de schéma
    en production, hors périmètre de ce script.
    """
    import httpx

    url, key = _supabase_credentials()
    rest_base = url.rstrip("/") + "/rest/v1"
    headers = {"apikey": key, "Authorization": f"Bearer {key}"}
    missing: list[str] = []
    unreachable: list[str] = []
    with httpx.Client(headers=headers, timeout=30) as client:
        for table in SUPABASE_MODEL_TABLES:
            try:
                resp = client.get(f"{rest_base}/{table}?select=*&limit=0")
            except Exception as exc:  # réseau, DNS, TLS…
                unreachable.append(f"{table}: {type(exc).__name__}: {exc}")
                continue
            if resp.status_code == 404:
                missing.append(table)
            elif resp.status_code >= 400:
                unreachable.append(
                    f"{table}: HTTP {resp.status_code} {resp.text[:200]}"
                )
    if missing or unreachable:
        details = []
        if missing:
            details.append("absente(s) du projet : " + ", ".join(missing))
        if unreachable:
            details.append("injoignable(s) : " + " | ".join(unreachable))
        raise SystemExit(
            "Cible Supabase inutilisable — " + " ; ".join(details) + ". "
            f"Projet : {url}. Rien n'a été écrit : prod/current est INTACT. "
            "Ne crée pas ces tables depuis ce script (DDL en production). "
            "Relance avec --no-supabase pour promouvoir en local seulement, "
            "et pousse la projection séparément quand le schéma existe."
        )
    logger.info("Préflight Supabase OK (%s)", ", ".join(SUPABASE_MODEL_TABLES))


def _delete_supabase_classes_not_in(coin_class_ids: set[str]) -> None:
    """--replace-all : DELETE rows from model_classes / coin_embeddings whose
    class_id (or eurio_id) is absent from the new promotion. Cf.
    phase-3-promote.md §"Mismatch class set"."""
    import httpx
    from training.eval.class_resolver import load_env

    env = load_env()
    url = env.get("SUPABASE_URL", "")
    key = env.get("SUPABASE_SERVICE_ROLE_KEY", "")
    if not url or not key:
        raise SystemExit(
            "--replace-all requires SUPABASE_URL/SUPABASE_SERVICE_ROLE_KEY"
        )
    headers = {
        "apikey": key,
        "Authorization": f"Bearer {key}",
        "Prefer": "return=minimal",
    }
    rest_base = url.rstrip("/") + "/rest/v1"
    keep_quoted = ",".join(f'"{cid}"' for cid in sorted(coin_class_ids))
    if not keep_quoted:
        return
    with httpx.Client(headers=headers, timeout=60) as client:
        resp = client.delete(
            f"{rest_base}/model_classes?class_id=not.in.({keep_quoted})",
        )
        if resp.status_code >= 400:
            raise RuntimeError(
                f"Supabase DELETE model_classes failed ({resp.status_code}): "
                f"{resp.text}"
            )
        resp = client.delete(
            f"{rest_base}/coin_embeddings?eurio_id=not.in.({keep_quoted})",
        )
        if resp.status_code >= 400:
            raise RuntimeError(
                f"Supabase DELETE coin_embeddings failed ({resp.status_code}): "
                f"{resp.text}"
            )
    logger.info("--replace-all: pruned Supabase rows outside %d-class set",
                len(coin_class_ids))


def _push_supabase(embeddings_path: Path) -> None:
    cmd = [
        VENV_PYTHON,
        str(ML_DIR / "bootstrap" / "seed_supabase.py"),
        "--embeddings", str(embeddings_path),
    ]
    logger.info("Pushing Supabase via %s", " ".join(cmd))
    rc = subprocess.call(cmd, cwd=str(ML_DIR))
    if rc != 0:
        raise RuntimeError(f"seed_supabase.py exited with {rc}")


def promote(args: argparse.Namespace) -> int:
    iter_meta = _validate_iteration(args.iteration_id, force=args.force)
    iter_dir: Path = iter_meta["iter_dir"]

    diff = _diff_classes(iter_dir)
    print(json.dumps({
        "iteration": iter_meta["id"],
        "verdict": iter_meta["verdict"],
        "diff": diff,
        "replace_all": args.replace_all,
        "dry_run": args.dry_run,
    }, indent=2))

    if diff["blind"] and not getattr(args, "allow_blind_diff", False):
        raise SystemExit(
            "Diff de perte AVEUGLE : ni prod/current ni asset APK exploitable "
            f"comme référence ({APK_EMBEDDINGS}). Impossible de dire ce que "
            "cette promotion fera perdre — et la promotion REMPLACE. "
            "Rapatrie une prod de référence, ou passe --allow-blind-diff pour "
            "promouvoir en assumant de ne pas savoir."
        )
    if diff["blind"]:
        _warn_force(
            "--allow-blind-diff : aucune référence de production. Ce que cette "
            "promotion fait perdre est INCONNU."
        )
    elif diff["absent_in_promotion"]:
        _warn_force(
            f"{len(diff['absent_in_promotion'])} entrée(s) sur "
            f"{diff['n_current']} ({diff['id_space']}) présentes en production "
            f"et ABSENTES de cette promotion — l'app cessera de les "
            f"reconnaître. Référence : {diff['reference']}."
        )

    if args.dry_run:
        print("--dry-run: no copy, no Supabase write.")
        return 0

    # Préflight AVANT le point de non-retour : `_archive_current` +
    # `_atomic_copy` sont irréversibles du point de vue de l'opérateur.
    if not args.no_supabase:
        _check_supabase_target()

    with _promote_lock():
        prev_iid = _read_prev_iid()
        archived = _archive_current(prev_iid)

        try:
            _atomic_copy(iter_dir, PROD_CURRENT)
        except Exception:
            # Recovery : restore archive if the copy died mid-way and the
            # archive is the only surviving snapshot.
            if archived is not None and not PROD_CURRENT.exists():
                shutil.move(str(archived), str(PROD_CURRENT))
                logger.warning(
                    "Atomic copy failed — restored prod from archive %s",
                    archived,
                )
            raise

        hashes: dict[str, str] = {}
        for sub in ARTIFACT_SUBDIRS:
            hashes.update(
                {f"{sub}/{k}": v for k, v in _hash_tree(PROD_CURRENT / sub).items()}
            )
        meta_path = _write_promoted_from(iter_meta, hashes)
        logger.info("Wrote %s", meta_path)

        embeddings_path = PROD_CURRENT / "embeddings" / "embeddings_v1.json"
        if args.no_supabase:
            # Séparer le geste LOCAL (prod/current + assets APK) du geste de
            # PRODUCTION (Supabase, que consomme l'app). Sans cette option, la
            # chaîne était intestable à blanc : `--dry-run` ne fait rien du tout,
            # et tout le reste écrivait en prod. Même raison que le découplage de
            # `build_app_core` d'avec Supabase (cf. architecture/README.md).
            print(
                "--no-supabase : prod/current écrit, Supabase INTACT. "
                "La projection est donc en retard sur prod/current — pousse-la "
                f"avec `.venv/bin/python bootstrap/seed_supabase.py --embeddings "
                f"{embeddings_path}` quand c'est voulu."
            )
        else:
            if args.replace_all:
                new_classes = set(
                    json.loads(embeddings_path.read_text()).get("coins", {})
                )
                _delete_supabase_classes_not_in(new_classes)
            _push_supabase(embeddings_path)

    print(json.dumps({
        "promoted": iter_meta["id"],
        "prod_current": str(PROD_CURRENT),
        "archived_previous": str(archived) if archived else None,
    }, indent=2))
    return 0


def main() -> int:
    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s",
    )
    parser = argparse.ArgumentParser(
        description="Promote a lab iteration to prod/current/",
    )
    parser.add_argument("iteration_id")
    parser.add_argument(
        "--force", action="store_true",
        help="Désarme TROIS contrôles à la fois : statut, verdict ET "
             "traçabilité (training_run_id). Chaque override est annoncé sur "
             "stderr et enregistré dans promoted_from.json.force_overrides.",
    )
    parser.add_argument(
        "--allow-blind-diff", action="store_true",
        help="Promouvoir alors qu'aucune référence de production n'est "
             "disponible (ni prod/current, ni asset APK) : on ne peut alors "
             "PAS dire ce que la promotion fait perdre.",
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="Print the diff and exit without copying or writing Supabase.",
    )
    parser.add_argument(
        "--replace-all", action="store_true",
        help="DELETE Supabase rows whose class_id/eurio_id is absent from the "
             "promotion before upserting. Default: accumulate (keep stale rows). "
             "N'affecte QUE Supabase : les artefacts de prod/current sont "
             "remplacés en bloc dans tous les cas.",
    )
    parser.add_argument(
        "--no-supabase", action="store_true",
        help="Promeut en LOCAL seulement (prod/current + promoted_from.json), "
             "sans écrire dans Supabase. Permet d'exercer la chaîne sans "
             "toucher à la production.",
    )
    args = parser.parse_args()
    if args.no_supabase and args.replace_all:
        raise SystemExit(
            "--replace-all et --no-supabase sont contradictoires : "
            "--replace-all n'agit QUE sur Supabase, que --no-supabase ne touche pas."
        )
    return promote(args)


if __name__ == "__main__":
    sys.exit(main())
