"""Import d'un pull device « eval_real » dans le corpus de scan (juge-et-banc, L1).

Pourquoi ce script existe, à côté de ``import_scan_corpus``
-----------------------------------------------------------
``scripts.import_scan_corpus`` importe des **sessions live-tests** : un JSONL
``ml/state/live_test_logs/<iteration>.jsonl`` produit par une itération connue,
avec ``raw_sha``, ``iteration_id`` et ``bundle_source`` déjà écrits par l'APK.

Les deux pulls d'évaluation de 2026 n'ont rien de tout ça. Ce sont des **arbres
de fichiers** ::

    <pull>/[eurio_debug/]eval_real/<slug>/<step>[_pN]_raw.jpg
                                         /<step>[_pN]_crop.jpg
                                         /<step>[_pN].json      ← sidecar

Ils précèdent toute cohorte et toute itération de lab. Les importer par le
chemin live-tests demanderait de fabriquer un ``iteration_id`` : ce serait un
mensonge de provenance. Ici ``cohort_id`` et ``source_iteration_id`` restent
**NULL**, et c'est ``bundle_source`` qui porte le protocole de prise de vue.

⛔ **Ne pas passer par ``vision.sync_eval_real``.** Ce module normalise (raw →
crop 224 px) et écrit un dataset d'entraînement dans ``ml/datasets/`` ; le
corpus, lui, archive les **octets d'origine** — c'est ce qui permet de le
rejouer plus tard sous un autre normaliseur. L'arbre est donc lu directement.

Pourquoi ``_ingest_frame`` de ``import_scan_corpus`` n'est PAS réutilisé
-----------------------------------------------------------------------
Son contrat impose ``source_iteration_id=str(line["iteration_id"])`` : sans
``iteration_id``, il écrirait la chaîne ``"None"`` en base — une provenance
inventée, exactement ce qu'on refuse ci-dessus. Le reste du geste (copie
append-only, transcodage du crop, mesure des tailles) est reproduit ici, dix
lignes, plutôt que d'élargir un contrat partagé pour un seul appelant.

Le remap des slugs morts
------------------------
Le pull du 2026-04-29 nomme ses dossiers d'après l'``eurio_id`` que l'APK
portait **au moment de la capture** : 14 de ces slugs sont morts. La table de
vérité est ``scripts.remap_bench_golden_set.MAPPING`` — tranchée à l'œil, jamais
par ressemblance de chaînes.

Elle ne couvre pas 4 des 19 dossiers de ce pull (cf. ``EXTRA_MAPPING``). Ces
quatre-là ne sont pas devinés non plus : ils sont **mesurés** par
renormalisation + sha256 contre ``ml/datasets/eval_real_norm/``, dont les noms
de dossier portent déjà le remap appliqué. Détail et commande :
``docs/work-in-progress/juge-et-banc/LOT1-IMPORT.md`` §2.

Tout ``eurio_id`` résolu est enfin confronté au **référentiel** (via
``store.class_resolver``, LECTURE SEULE). Un slug qui n'y existe pas est un slug
mort de plus : le script le **refuse** au lieu de l'écrire (``--allow-unknown``
pour passer outre, en connaissance de cause).

Usage ::

    python -m scripts.import_device_pull \
        --pull ../debug_pull/20260429_170852 --bundle-source device_pull_20260429
    python -m scripts.import_device_pull \
        --pull ../debug_pull/20260601_154135 --bundle-source device_pull_20260601 --execute

``--dry-run`` est le DÉFAUT. ⚠️ Même en dry-run, ``ScanCorpusStore()`` crée sa
base si elle est absente : un fichier qui passe de 0 à 12 ko ne prouve rien, le
seul critère est le ``COUNT(*)``.

Interdit ici, comme dans tout le corpus : aucune référence à ``eurio.db`` /
``eurio.replica.db`` **en écriture**. La seule lecture du référentiel est le
garde-fou ci-dessus, et elle est facultative.
"""
from __future__ import annotations

import argparse
import hashlib
import io
import json
import shutil
import socket
import subprocess
import sys
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path

ML_DIR = Path(__file__).resolve().parent.parent
if str(ML_DIR) not in sys.path:
    sys.path.insert(0, str(ML_DIR))

from store.scan_corpus import (  # noqa: E402
    ScanCapture,
    ScanCorpusStore,
    corpus_version,
)

DEFAULT_MANIFEST = (
    ML_DIR / "state" / "validation_gold" / "device_corpus_manifest.jsonl"
)

#: Slugs morts du pull d'avril **absents de** ``remap_bench_golden_set.MAPPING``.
#: Établis par mesure (renormalisation déterministe + sha256 contre
#: ``ml/datasets/eval_real_norm/``, 114/114 appariés), pas par ressemblance de
#: chaînes. Cf. ``LOT1-IMPORT.md`` §2 pour la commande et sa sortie.
EXTRA_MAPPING: dict[str, str] = {
    "ad-2014-2eur-standard": "ad-2014-2eur-standard-1st-type",
    "de-2007-2eur-schwerin-castle-mecklenburg-vorpommern":
        "de-2007-2eur-state-of-mecklenburg-vorpommern",
    "de-2020-2eur-50-years-since-the-kniefall-von-warschau":
        "de-2020-2eur-german-polish-reconciliation",
    # ⚠️ Corrigé en revue le 2026-08-25. L'appariement par sha256 renvoyait
    # `fr-1999-2eur-standard-1st-map`, et il ne pouvait pas faire mieux : les
    # deux cibles appartiennent au MÊME groupe de dessin `fr-2euro-standard-t1`,
    # donc elles sont indiscernables à la maille classe — la seule que la mesure
    # sache voir. Le catalogue tranche à la maille pièce :
    #   sqlite3 -readonly ml/state/eurio.replica.db \
    #     "select eurio_id, year, design_group_id from coins
    #        where eurio_id like 'fr-%standard%' order by year;"
    #   fr-1999-2eur-standard-1st-map|1999|fr-2euro-standard-t1
    #   fr-2007-2eur-standard-2nd-map|2007|fr-2euro-standard-t1   ← millésime du dossier
    # Envoyer un dossier « 2007 » vers la pièce de 1999 aurait posé une vérité
    # terrain fausse à la pièce alors que la bonne cible existe. Sans effet sur
    # la notation à la classe ; l'écart n'aurait resurgi qu'au premier usage à
    # la maille pièce, sans rien lever.
    "fr-2007-2eur-standard": "fr-2007-2eur-standard-2nd-map",
}


# ── résolution des slugs ──────────────────────────────────────────────────


def build_remap() -> dict[str, str]:
    """``old_eurio_id → new_eurio_id``, table de vérité d'abord, mesures ensuite.

    ``MAPPING`` gagne toujours : c'est la table tranchée à l'œil. ``EXTRA_MAPPING``
    ne comble que ce qu'elle ignore, et un recouvrement contradictoire est une
    erreur dure — pas une préférence silencieuse.
    """
    from scripts.remap_bench_golden_set import MAPPING  # noqa: PLC0415

    remap = {m.old_eurio_id: m.new_eurio_id for m in MAPPING}
    for old, new in EXTRA_MAPPING.items():
        if old in remap and remap[old] != new:
            raise SystemExit(
                f"EXTRA_MAPPING contredit MAPPING sur {old} "
                f"({remap[old]} vs {new}) — à trancher à la main."
            )
        remap.setdefault(old, new)
    return remap


def build_class_level_only() -> set[str]:
    """Slugs dont le remap est **juste à la classe et faux à la pièce**.

    ``MAPPING`` le dit déjà (``class_level_only=True`` sur ``be-2008-2eur-standard``,
    dont la photo montre une pièce datée 2011 que le référentiel ne possède
    pas) ; le corpus, lui, n'avait aucune colonne pour le porter — donc rien à
    l'écran ne pouvait distinguer « bien labellisé » de « rattaché faute de
    mieux ». Un écran qui permet de remapper doit savoir exprimer ce cas, sinon
    il fait remapper à l'aveugle.

    ``EXTRA_MAPPING`` n'a aucune ligne de ce genre : ses 4 cibles sont des
    pièces existantes du référentiel, à la bonne pièce.
    """
    from scripts.remap_bench_golden_set import MAPPING  # noqa: PLC0415

    return {m.old_eurio_id for m in MAPPING if m.class_level_only}


def load_referential_ids() -> set[str]:
    """``eurio_id`` vivants du référentiel, en LECTURE SEULE. Vide si injoignable."""
    try:
        from store.class_resolver import coin_refs_from_sqlite  # noqa: PLC0415

        return {r.eurio_id for r in coin_refs_from_sqlite()}
    except Exception:
        return set()


# ── lecture de l'arbre ────────────────────────────────────────────────────


def resolve_eval_real(pull_dir: Path) -> Path:
    """Accepte la racine du pull, son ``eurio_debug/``, ou ``eval_real/`` lui-même."""
    for candidate in (
        pull_dir / "eurio_debug" / "eval_real",
        pull_dir / "eval_real",
        pull_dir,
    ):
        if candidate.is_dir() and any(candidate.glob("*/*_raw.jpg")):
            return candidate
    raise SystemExit(
        f"eval_real/ introuvable sous {pull_dir} "
        "(attendu <pull>/[eurio_debug/]eval_real/<slug>/<step>_raw.jpg)"
    )


def parse_ts(ts: str) -> str | None:
    """``20260429_164750_336`` → ``2026-04-29T16:47:50.336``.

    ⚠️ Heure **locale du device**, sans fuseau : le sidecar n'en porte pas. On
    ne fabrique pas un ``Z`` qu'on ne sait pas vrai.
    """
    try:
        head, ms = ts.rsplit("_", 1)
        dt = datetime.strptime(head, "%Y%m%d_%H%M%S")
    except (ValueError, AttributeError):
        return None
    return f"{dt.isoformat()}.{ms}"


@dataclass
class Frame:
    slug: str
    eurio_id: str
    condition: str
    position: int
    raw_path: Path
    crop_path: Path | None
    sidecar: dict
    captured_at: str
    class_level_only: bool = False


def scan_tree(
    eval_real: Path,
    remap: dict[str, str],
    class_level_only: set[str] | None = None,
) -> tuple[list[Frame], list[str]]:
    """Lit l'arbre et rend ``(frames, slugs sans sidecar)``.

    ``condition`` = le ``step_id`` **brut** du sidecar (repli : le nom de fichier
    amputé de son suffixe de position). Deux protocoles partagent des noms
    d'étape (``bright_plain``, ``bright_textured``) : c'est ``bundle_source`` qui
    les sépare, jamais la condition.
    """
    frames: list[Frame] = []
    missing_sidecar: list[str] = []
    flagged = class_level_only or set()
    for slug_dir in sorted(p for p in eval_real.iterdir() if p.is_dir()):
        slug = slug_dir.name
        eurio_id = remap.get(slug, slug)
        for raw in sorted(slug_dir.glob("*_raw.jpg")):
            stem = raw.name[: -len("_raw.jpg")]
            side_path = slug_dir / f"{stem}.json"
            crop = slug_dir / f"{stem}_crop.jpg"
            sidecar: dict = {}
            if side_path.exists():
                try:
                    sidecar = json.loads(side_path.read_text(encoding="utf-8"))
                except json.JSONDecodeError:
                    sidecar = {}
            if not sidecar:
                missing_sidecar.append(f"{slug}/{stem}")
            base, position = _split_position(stem)
            condition = str(sidecar.get("step_id") or base)
            captured_at = parse_ts(str(sidecar.get("ts") or "")) or _mtime_iso(raw)
            frames.append(
                Frame(
                    slug=slug,
                    eurio_id=eurio_id,
                    condition=condition,
                    position=int(sidecar.get("photo_index", position)),
                    raw_path=raw,
                    crop_path=crop if crop.exists() else None,
                    sidecar=sidecar,
                    captured_at=captured_at,
                    class_level_only=slug in flagged,
                )
            )
    return frames, missing_sidecar


def _split_position(stem: str) -> tuple[str, int]:
    """``bright_plain_p2`` → ``("bright_plain", 2)`` ; ``bright_plain`` → ``(…, 0)``."""
    head, sep, tail = stem.rpartition("_")
    if sep and tail.startswith("p") and tail[1:].isdigit():
        return head, int(tail[1:])
    return stem, 0


def _mtime_iso(path: Path) -> str:
    return datetime.fromtimestamp(path.stat().st_mtime, timezone.utc).isoformat(
        timespec="milliseconds"
    )


# ── ingestion ─────────────────────────────────────────────────────────────


@dataclass
class ImportStats:
    seen: int = 0
    inserted: int = 0
    updated: int = 0
    duplicate_bytes: int = 0
    no_crop: int = 0
    unknown_eurio_id: int = 0

    def summary(self) -> str:
        return (
            f"seen={self.seen} inserted={self.inserted} updated={self.updated} "
            f"duplicate_bytes={self.duplicate_bytes} no_crop={self.no_crop} "
            f"unknown_eurio_id={self.unknown_eurio_id}"
        )


def _image_size(path: Path) -> tuple[int | None, int | None]:
    try:
        from PIL import Image

        with Image.open(path) as im:
            return im.width, im.height
    except Exception:
        return None, None


def _jpeg_to_png(path: Path) -> bytes:
    from PIL import Image

    with Image.open(path) as im:
        buf = io.BytesIO()
        im.convert("RGB").save(buf, format="PNG")
        return buf.getvalue()


def ingest(
    store: ScanCorpusStore,
    frames: list[Frame],
    bundle_source: str,
    stats: ImportStats,
    *,
    execute: bool,
) -> list[str]:
    """Copie append-only + upsert. Rend les ``capture_id`` du pull, dans l'ordre lu."""
    frames_dir = store.frames_dir
    if execute:
        frames_dir.mkdir(parents=True, exist_ok=True)
    seen_ids: dict[str, Frame] = {}
    ordered: list[str] = []
    for f in frames:
        raw_bytes = f.raw_path.read_bytes()
        capture_id = hashlib.sha256(raw_bytes).hexdigest()[:16]
        stats.seen += 1
        if capture_id in seen_ids:
            # Deux fichiers octet-pour-octet identiques dans le MÊME pull : le
            # capture_id les fusionne par construction. On le dit.
            stats.duplicate_bytes += 1
            print(
                f"  ~ {capture_id} : {f.slug}/{f.raw_path.name} identique à "
                f"{seen_ids[capture_id].slug}/{seen_ids[capture_id].raw_path.name}"
            )
            continue
        seen_ids[capture_id] = f
        ordered.append(capture_id)
        if f.crop_path is None:
            stats.no_crop += 1

        raw_dst = frames_dir / f"{capture_id}.raw.jpg"
        crop_dst = frames_dir / f"{capture_id}.crop.png"
        if execute:
            if not raw_dst.exists():
                shutil.copyfile(f.raw_path, raw_dst)
            if not crop_dst.exists() and f.crop_path is not None:
                crop_dst.write_bytes(_jpeg_to_png(f.crop_path))

        raw_w, raw_h = _image_size(raw_dst if raw_dst.exists() else f.raw_path)
        crop_w = crop_h = None
        if crop_dst.exists():
            crop_w, crop_h = _image_size(crop_dst)
        elif f.crop_path is not None:
            crop_w, crop_h = _image_size(f.crop_path)

        quality = {
            "source_slug": f.slug,
            "source_file": f.raw_path.name,
            "position": f.position,
            "step_index": f.sidecar.get("step_index"),
            "step_label": f.sidecar.get("step_label"),
            "protocol_mode": f.sidecar.get("protocol_mode"),
            "normalize": f.sidecar.get("normalize"),
        }
        capture = ScanCapture(
            capture_id=capture_id,
            eurio_id=f.eurio_id,
            condition=f.condition,
            captured_at=f.captured_at,
            raw_path=str(raw_dst.relative_to(store.frames_root)),
            crop_path=str(crop_dst.relative_to(store.frames_root)),
            cohort_id=None,            # antérieur à toute cohorte — jamais inventé
            source_iteration_id=None,  # idem : provenance, pas décoration
            bundle_source=bundle_source,
            raw_w=raw_w,
            raw_h=raw_h,
            crop_w=crop_w,
            crop_h=crop_h,
            device_model=None,
            quality_json=json.dumps(quality, ensure_ascii=False, sort_keys=True),
            notes=(
                f"import device pull ({bundle_source}) ; slug d'origine "
                f"{f.slug} ; crop transcodé JPEG→PNG (perte amont actée)"
            ),
            class_level_only=f.class_level_only,
        )
        if not execute:
            existing = store.get_capture(capture_id)
            stats.updated += 1 if existing else 0
            stats.inserted += 0 if existing else 1
            continue
        if store.upsert_capture(capture):
            stats.inserted += 1
        else:
            stats.updated += 1
    return ordered


# ── manifeste committé ────────────────────────────────────────────────────


@dataclass(frozen=True)
class ManifestRow:
    capture_id: str
    eurio_id: str
    condition: str
    bundle_source: str | None
    captured_at: str


def build_manifest_rows(store: ScanCorpusStore) -> list[ManifestRow]:
    """Vérité terrain du corpus device, **aucune prédiction, jamais** — motif
    ``ml/review/bench_gold.py``. Trié par ``capture_id``."""
    return sorted(
        (
            ManifestRow(
                capture_id=c.capture_id,
                eurio_id=c.eurio_id,
                condition=c.condition,
                bundle_source=c.bundle_source,
                captured_at=c.captured_at,
            )
            for c in store.list_captures()
        ),
        key=lambda r: r.capture_id,
    )


def _git_commit() -> str | None:
    try:
        out = subprocess.run(
            ["git", "-C", str(ML_DIR), "rev-parse", "HEAD"],
            capture_output=True, text=True, timeout=5, check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    return out.stdout.strip() or None


def build_manifest_meta(rows: list[ManifestRow]) -> dict:
    by_bundle: dict[str, int] = {}
    classes: dict[str, set] = {}
    for r in rows:
        key = r.bundle_source or "∅"
        by_bundle[key] = by_bundle.get(key, 0) + 1
        classes.setdefault(key, set()).add(r.eurio_id)
    return {
        "corpus_version": corpus_version([r.capture_id for r in rows]),
        "built_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "n_captures": len(rows),
        "n_eurio_ids": len({r.eurio_id for r in rows}),
        "n_by_bundle_source": dict(sorted(by_bundle.items())),
        "n_eurio_ids_by_bundle_source": {
            k: len(v) for k, v in sorted(classes.items())
        },
        "git_commit": _git_commit(),
        "builder": socket.gethostname(),
        "contains_predictions": False,
        "scoring_path": "full",
        "scoring_path_reason": (
            "Les crops STOCKÉS ont été produits par QUATRE normaliseurs "
            "différents (mesuré : hough_tight 113 + hough_relaxed 1 pour avril, "
            "hough_strict 280 + hough_loose 57 pour juin — cf. "
            "quality_json.normalize.method). Noter en --path fast comparerait "
            "des crops incomparables et mesurerait l'écart des normaliseurs, "
            "pas celui des modèles. La notation se fait en --path full "
            "(renormalisation depuis le raw, port bit-for-bit de "
            "SnapNormalizer.kt)."
        ),
    }


def write_manifest(store: ScanCorpusStore, path: Path) -> dict:
    rows = build_manifest_rows(store)
    meta = build_manifest_meta(rows)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as fh:
        for r in rows:
            fh.write(json.dumps(asdict(r), ensure_ascii=False, sort_keys=True) + "\n")
    path.with_suffix(".meta.json").write_text(
        json.dumps(meta, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return meta


# ── main ──────────────────────────────────────────────────────────────────


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--pull", type=Path, help="racine du pull device")
    parser.add_argument(
        "--bundle-source",
        help="étiquette de protocole, ex. device_pull_20260429 (obligatoire avec --pull)",
    )
    parser.add_argument("--db", type=Path, default=None, help="override scan_corpus.db")
    parser.add_argument(
        "--execute", action="store_true",
        help="écrit réellement (défaut : dry-run, rien n'est écrit)",
    )
    parser.add_argument(
        "--allow-unknown", action="store_true",
        help="accepte un eurio_id absent du référentiel au lieu de refuser",
    )
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    parser.add_argument(
        "--no-manifest", action="store_true",
        help="n'écrit pas le manifeste committé après import",
    )
    parser.add_argument(
        "--manifest-only", action="store_true",
        help="régénère seulement le manifeste depuis la base, sans importer",
    )
    args = parser.parse_args(argv)

    store = ScanCorpusStore(db_path=args.db)

    if args.manifest_only:
        meta = write_manifest(store, args.manifest)
        print(f"Manifeste → {args.manifest}")
        print(json.dumps(meta, ensure_ascii=False, indent=2, sort_keys=True))
        return 0

    if not args.pull or not args.bundle_source:
        parser.error("--pull et --bundle-source sont requis (ou --manifest-only)")

    mode = "EXECUTE" if args.execute else "DRY-RUN"
    eval_real = resolve_eval_real(args.pull)
    remap = build_remap()
    flagged = build_class_level_only()
    frames, missing_sidecar = scan_tree(eval_real, remap, flagged)

    print(f"── import device pull · {mode}")
    print(f"   source        : {eval_real}")
    print(f"   bundle_source : {args.bundle_source}")
    print(f"   base          : {store.db_path}")
    print(f"   frames lues   : {len(frames)}")
    remapped = {f.slug: f.eurio_id for f in frames if f.slug != f.eurio_id}
    print(f"   slugs remappés: {len(remapped)}")
    for old, new in sorted(remapped.items()):
        origin = "EXTRA (mesuré)" if old in EXTRA_MAPPING else "MAPPING (à l'œil)"
        flag = "  🔴 juste à la CLASSE, faux à la PIÈCE" if old in flagged else ""
        print(f"      {old} → {new}   [{origin}]{flag}")
    n_cl = sum(1 for f in frames if f.class_level_only)
    if n_cl:
        print(
            f"   🔴 {n_cl} capture(s) class_level_only : le label vaut à la "
            "classe, pas à la pièce — à exclure d'une notation stricte"
        )
    if missing_sidecar:
        print(f"   ⚠ {len(missing_sidecar)} frame(s) sans sidecar JSON exploitable")

    referential = load_referential_ids()
    stats = ImportStats()
    if referential:
        unknown = sorted({f.eurio_id for f in frames if f.eurio_id not in referential})
        stats.unknown_eurio_id = len(unknown)
        if unknown:
            print(f"   🔴 {len(unknown)} eurio_id absents du référentiel :")
            for u in unknown:
                print(f"      {u}")
            if not args.allow_unknown:
                print(
                    "   → refus. Ces slugs sont morts : ajouter leur ligne à "
                    "MAPPING (à l'œil) ou à EXTRA_MAPPING (par mesure), "
                    "ou passer --allow-unknown en connaissance de cause."
                )
                return 2
    else:
        print("   ⚠ référentiel injoignable — garde-fou eurio_id NON exercé")

    ids = ingest(store, frames, args.bundle_source, stats, execute=args.execute)
    print(f"\n{stats.summary()}")
    print(f"version de ce pull : {corpus_version(ids)} ({len(ids)} captures)")
    if not args.execute:
        print("→ rien écrit (dry-run ; --execute pour écrire).")
        return 0

    print(f"Corpus total : {store.count()} captures")
    if not args.no_manifest:
        meta = write_manifest(store, args.manifest)
        print(f"Manifeste → {args.manifest}")
        print(
            f"   corpus_version={meta['corpus_version']} "
            f"n_captures={meta['n_captures']} "
            f"n_by_bundle_source={meta['n_by_bundle_source']}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
