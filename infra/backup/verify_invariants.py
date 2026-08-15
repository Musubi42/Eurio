#!/usr/bin/env python3
"""Suite d'invariants de la sauvegarde Eurio.

Répond à une question que ni un code de retour ni un `integrity_check` ne
tranchent : **le contenu sauvegardé est-il crédible ?** Une base tronquée,
fidèlement transportée, passe le sha ET l'`integrity_check` — une base vide est
une base SQLite parfaitement valide.

Le même script sert deux usages, et c'est délibéré (cf. DECISIONS.md D-13) :

  * chaque nuit, sur `infra/backup/staging/` ;
  * après une restauration, comme **critère d'acceptation**.

Ils ne peuvent donc pas diverger, et l'exercice de restauration ne peut pas
devenir du théâtre.

Règle qui gouverne tous les invariants (D-10) : ils sont **calculés**, jamais
**lus**. Contre-exemple vécu : `storage_status` vaut 'present' sur 100 % des
lignes, y compris sur celles qui pointent vers un objet absent.

Usage :
  verify_invariants.py <staging_dir> [--baseline FICHIER] [--accept-baseline]
                                     [--max-age-hours N] [--repo-root DIR]

Sortie : 0 si tous les invariants passent, 2 sinon.
Spec : docs/work-in-progress/backup-pipeline/VERIFICATION.md §3
"""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import os
import sqlite3
import sys

# Un `mock/` ou un chemin absolu de machine de dev n'a jamais eu d'objet MinIO
# correspondant : les compter en dangling ferait naître l'invariant 4 en rouge.
# Cf. DONNEES.md §4 bug n°2 — 546 chemins `/Users/...` + 10 lignes `mock/`.
EXCLUDED_PREFIXES = ("mock/", "/")

DB_TO_BUCKET = {
    "image_assets": "enrichment-crops",
    "source_images": "enrichment-raws",
}


class Report:
    """Collecte les verdicts pour n'afficher qu'un seul bilan, lisible d'un coup."""

    def __init__(self) -> None:
        self.rows: list[tuple[str, bool, str]] = []
        self.needs_ack = False

    def add(self, name: str, ok: bool, detail: str = "") -> bool:
        self.rows.append((name, ok, detail))
        return ok

    @property
    def failed(self) -> list[tuple[str, bool, str]]:
        return [r for r in self.rows if not r[1]]

    def render(self) -> None:
        for name, ok, detail in self.rows:
            print(f"  {'✅' if ok else '🔴'} {name}" + (f" — {detail}" if detail else ""))


def load_json(path: str):
    with open(path) as fh:
        return json.load(fh)


def sha256_of(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def parse_utc(value: str) -> dt.datetime:
    return dt.datetime.strptime(value, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=dt.UTC)


# ── Niveau 1 — intégrité du transport ────────────────────────────────────────

def check_transport(staging: str, manifest: dict, report: Report) -> None:
    """sha256 recalculé ≡ manifeste.

    Sert aussi de **contrôle d'atomicité** : le manifeste est écrit en dernier,
    donc un fichier modifié après lui se signale ici.
    """
    for name, info in manifest["files"].items():
        path = os.path.join(staging, name)
        if not os.path.exists(path):
            report.add(f"[1] {name} présent", False, "absent du staging")
            continue
        got = sha256_of(path)
        report.add(
            f"[1] {name} sha256 ≡ manifeste",
            got == info["sha256"],
            "" if got == info["sha256"] else f"attendu {info['sha256'][:16]}…, obtenu {got[:16]}…",
        )


# ── Niveau 2 — validité structurelle ─────────────────────────────────────────

def check_structure(staging: str, manifest: dict, repo_root: str | None, report: Report) -> None:
    for name in manifest["files"]:
        path = os.path.join(staging, name)
        if not os.path.exists(path):
            continue
        con = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
        try:
            integrity = con.execute("pragma integrity_check").fetchone()[0]
            fk = con.execute("pragma foreign_key_check").fetchall()
        finally:
            con.close()
        report.add(f"[2] {name} integrity_check", integrity == "ok", integrity)
        report.add(f"[2] {name} foreign_key_check", not fk, f"{len(fk)} violation(s)")

    # Le schéma appliqué correspond-il aux migrations du dépôt ? Une base
    # restaurée d'une génération antérieure se signale ici et nulle part ailleurs.
    applied = manifest["files"].get("eurio.db", {}).get("migrations", [])
    if repo_root:
        migrations_dir = os.path.join(repo_root, "ml", "serving", "migrations")
        if os.path.isdir(migrations_dir):
            on_disk = sorted(f for f in os.listdir(migrations_dir) if f.endswith(".sql"))
            missing = [m for m in on_disk if m not in applied]
            report.add(
                "[2] migrations appliquées ≡ dépôt",
                not missing,
                "" if not missing else f"non appliquées : {', '.join(missing)}",
            )
        else:
            report.add("[2] migrations appliquées ≡ dépôt", True, "répertoire absent, contrôle ignoré")


# ── Niveau 3 — plausibilité sémantique ───────────────────────────────────────

def check_non_decreasing(manifest: dict, baseline: dict | None, report: Report) -> None:
    """L'invariant qui attrape une base tronquée mais parfaitement valide.

    Une décroissance peut être légitime (purge volontaire) ; elle ne doit jamais
    passer en silence. On échoue, et un humain tranche avec --accept-baseline.
    """
    if baseline is None:
        report.add("[3] non-décroissance", True, "pas de baseline — première exécution, référence posée")
        return

    regressions = []
    for name, info in manifest["files"].items():
        previous = baseline.get("files", {}).get(name)
        if not previous:
            continue
        for table in info.get("watched", []):
            was = previous.get("row_counts", {}).get(table)
            now = info.get("row_counts", {}).get(table)
            if was is None or now is None:
                continue
            if now < was:
                regressions.append(f"{name}:{table} {was} → {now} ({now - was:+d})")

    ok = report.add(
        "[3] non-décroissance des tables surveillées",
        not regressions,
        "" if not regressions else "; ".join(regressions),
    )
    if not ok:
        report.needs_ack = True


def check_canary(staging: str, report: Report) -> None:
    """Une pièce connue se résout de bout en bout.

    Ne teste pas que la base est *valide* — que le contenu est **utilisable**.
    Une base vide passe integrity_check ; elle échoue ici.
    """
    path = os.path.join(staging, "eurio.db")
    if not os.path.exists(path):
        return
    con = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    try:
        row = con.execute(
            "select c.eurio_id,"
            " (select count(*) from coin_names_i18n n where n.eurio_id = c.eurio_id),"
            " (select count(*) from coin_canonical_images i where i.eurio_id = c.eurio_id)"
            " from coins c order by c.eurio_id limit 1"
        ).fetchone()
    finally:
        con.close()

    if not row:
        report.add("[3] pièce canari résolue", False, "aucune ligne dans `coins`")
        return
    eurio_id, names, images = row
    report.add(
        "[3] pièce canari résolue",
        names > 0 and images > 0,
        f"{eurio_id} → {names} nom(s), {images} image(s)",
    )


def check_cross_store(staging: str, manifest: dict, report: Report) -> None:
    """Intégrité référentielle DB ↔ MinIO — l'invariant propre à Eurio.

    Ignoré tant que le miroir n'existe pas (lot 3), signalé explicitement pour
    qu'un contrôle absent ne se confonde pas avec un contrôle réussi.
    """
    minio_root = os.path.join(staging, "minio")
    if not manifest.get("minio") or not os.path.isdir(minio_root):
        report.add("[3] cohérence DB ↔ MinIO", True, "miroir absent — contrôle non applicable (lot 3)")
        return

    path = os.path.join(staging, "eurio.db")
    con = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    try:
        for table, bucket in DB_TO_BUCKET.items():
            bucket_dir = os.path.join(minio_root, bucket)
            if not os.path.isdir(bucket_dir):
                report.add(f"[3] {table} ↔ {bucket}", False, "bucket absent du miroir")
                continue
            present = set()
            for dirpath, _dirnames, filenames in os.walk(bucket_dir):
                rel = os.path.relpath(dirpath, bucket_dir)
                for filename in filenames:
                    present.add(filename if rel == "." else f"{rel}/{filename}")
            referenced = {
                r[0]
                for r in con.execute(
                    f"select storage_path from {table} where storage_path is not null and storage_path <> ''"
                )
                if not r[0].startswith(EXCLUDED_PREFIXES)
            }
            dangling = referenced - present
            report.add(
                f"[3] {table} ↔ {bucket} : aucun dangling",
                not dangling,
                f"{len(dangling)} référence(s) sans objet"
                if dangling
                else f"{len(referenced)} référence(s) résolues, {len(present - referenced)} orphelin(s)",
            )
    finally:
        con.close()


def check_freshness(manifest: dict, max_age_hours: float, report: Report) -> None:
    """Un staging figé passe tous les invariants précédents (D-17).

    « Les comptages n'ont pas baissé » et « les données sont à jour » sont deux
    propriétés distinctes ; celle-ci est la seconde.
    """
    created = manifest.get("created_utc")
    if not created:
        report.add("[3] fraîcheur du staging", False, "created_utc absent du manifeste")
        return
    age = (dt.datetime.now(dt.UTC) - parse_utc(created)).total_seconds() / 3600
    report.add(
        "[3] fraîcheur du staging",
        age <= max_age_hours,
        f"{age:.1f} h (plafond {max_age_hours:.0f} h)",
    )


def main() -> int:
    parser = argparse.ArgumentParser(description="Vérifie les invariants d'un staging de sauvegarde Eurio.")
    parser.add_argument("staging")
    parser.add_argument("--baseline", default=None, help="Manifeste du dernier verify réussi")
    parser.add_argument(
        "--accept-baseline",
        action="store_true",
        help="Acquitte une décroissance constatée et promeut le manifeste courant en référence",
    )
    parser.add_argument("--max-age-hours", type=float, default=36.0)
    parser.add_argument("--repo-root", default=None)
    args = parser.parse_args()

    manifest_path = os.path.join(args.staging, "manifest.json")
    if not os.path.exists(manifest_path):
        print(f"🔴 manifeste absent : {manifest_path}", file=sys.stderr)
        print("   Le manifeste est la sentinelle du staging : son absence signifie", file=sys.stderr)
        print("   que `stage` n'a pas terminé. Relancer `eurio-backup.sh stage`.", file=sys.stderr)
        return 2

    manifest = load_json(manifest_path)
    baseline = load_json(args.baseline) if args.baseline and os.path.exists(args.baseline) else None

    report = Report()
    print(f"=== Invariants — staging {args.staging}")
    print(f"    manifeste du {manifest.get('created_utc')} (schéma {manifest.get('manifest_schema')})")
    print()

    check_transport(args.staging, manifest, report)
    check_structure(args.staging, manifest, args.repo_root, report)
    check_non_decreasing(manifest, baseline, report)
    check_canary(args.staging, report)
    check_cross_store(args.staging, manifest, report)
    check_freshness(manifest, args.max_age_hours, report)

    report.render()
    print()

    if report.failed and not (report.needs_ack and args.accept_baseline and len(report.failed) == 1):
        print(f"🔴 ÉCHEC — {len(report.failed)} invariant(s) en défaut")
        if report.needs_ack:
            print()
            print("   Une décroissance de comptage peut être légitime (purge volontaire).")
            print("   Après vérification humaine, l'acquitter avec :")
            print("     go-task backup:verify -- --accept-baseline")
        return 2

    if args.baseline:
        with open(args.baseline, "w") as fh:
            json.dump(manifest, fh, indent=2, ensure_ascii=False)
            fh.write("\n")
        print(f"   référence mise à jour : {args.baseline}")

    print(f"✅ {len(report.rows)} invariants passés")
    return 0


if __name__ == "__main__":
    sys.exit(main())
