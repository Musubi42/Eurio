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

Deux règles gouvernent l'écriture des invariants :

  1. **Calculés, jamais lus** (D-10). Contre-exemple vécu : `storage_status`
     vaut 'present' sur 100 % des lignes, y compris celles qui pointent vers un
     objet absent.
  2. **L'absence de preuve n'est pas une preuve.** Une donnée manquante — table
     disparue, fichier hors manifeste, référence absente — est une anomalie, pas
     un contrôle à sauter. C'est par là que passent les pertes silencieuses.

Usage :
  verify_invariants.py <staging_dir> [--baseline FICHIER] [--accept-baseline]
                                     [--max-age-hours N] [--max-source-age-days N]
                                     [--repo-root DIR]

Sortie : 0 si tous les invariants passent (avertissements tolérés), 2 sinon.
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

# Fichiers dont l'absence est une anomalie, quoi qu'en dise le manifeste.
# Le manifeste n'a pas le droit d'être la seule autorité sur son propre
# périmètre : un staging qui « oublie » review.db doit crier, pas passer.
REQUIRED_FILES = ("eurio.db", "review.db")

# Un `mock/` ou un chemin absolu de machine de dev n'a jamais eu d'objet MinIO
# correspondant : les compter en dangling ferait naître l'invariant 4 en rouge.
# Cf. DONNEES.md §4 bug n°2 — 546 chemins `/Users/...` + 10 lignes `mock/`.
EXCLUDED_PREFIXES = ("mock/", "/")

DB_TO_BUCKET = {
    "image_assets": "enrichment-crops",
    "source_images": "enrichment-raws",
}

OK, WARN, FAIL = "ok", "warn", "fail"
GLYPH = {OK: "✅", WARN: "⚠️ ", FAIL: "🔴"}


class Report:
    """Collecte les verdicts pour n'afficher qu'un seul bilan, lisible d'un coup.

    Trois états et pas deux : un contrôle qu'on n'a pas pu faire n'est ni une
    réussite ni un échec, et le confondre avec l'un des deux est exactement le
    défaut qu'on corrige.
    """

    def __init__(self) -> None:
        self.rows: list[tuple[str, str, str]] = []
        self.ack_rows: list[str] = []

    def add(self, name: str, state: str, detail: str = "") -> None:
        self.rows.append((name, state, detail))

    def check(self, name: str, ok: bool, detail: str = "") -> None:
        self.add(name, OK if ok else FAIL, detail)

    @property
    def failures(self) -> list[tuple[str, str, str]]:
        return [r for r in self.rows if r[1] == FAIL]

    @property
    def warnings(self) -> list[tuple[str, str, str]]:
        return [r for r in self.rows if r[1] == WARN]

    def render(self) -> None:
        for name, state, detail in self.rows:
            print(f"  {GLYPH[state]} {name}" + (f" — {detail}" if detail else ""))


def guarded(report: Report, label: str):
    """Un invariant qui explose est un invariant en échec, pas un crash du script.

    Sans ça, une base corrompue au niveau page fait remonter un traceback et
    `rc=1` — et le rapport déjà collecté est perdu, y compris ses lignes rouges.
    """

    class _Guard:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, _tb):
            if exc is None:
                return False
            report.add(f"{label} (exception)", FAIL, f"{exc_type.__name__}: {exc}")
            return True

    return _Guard()


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


# ── Périmètre — avant tout le reste ──────────────────────────────────────────

def check_scope(staging: str, manifest: dict, report: Report) -> None:
    described = set(manifest.get("files", {}))
    for name in REQUIRED_FILES:
        if name not in described:
            report.check(f"[0] {name} décrit par le manifeste", False, "absent du manifeste")
        elif not os.path.exists(os.path.join(staging, name)):
            report.check(f"[0] {name} présent dans le staging", False, "décrit mais absent du disque")
        else:
            report.check(f"[0] {name} présent", True)


# ── Niveau 1 — intégrité du transport ────────────────────────────────────────

def check_transport(staging: str, manifest: dict, report: Report) -> None:
    """sha256 recalculé ≡ manifeste.

    Sert aussi de **contrôle d'atomicité** : le manifeste est écrit en dernier,
    donc un fichier modifié après lui se signale ici.
    """
    for name, info in manifest["files"].items():
        path = os.path.join(staging, name)
        if not os.path.exists(path):
            continue  # déjà signalé par check_scope
        with guarded(report, f"[1] {name} sha256"):
            got = sha256_of(path)
            report.check(
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
        with guarded(report, f"[2] {name} structure"):
            con = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
            try:
                integrity = [r[0] for r in con.execute("pragma integrity_check")]
                fk = con.execute("pragma foreign_key_check").fetchall()
            finally:
                con.close()
            healthy = integrity == ["ok"]
            report.check(
                f"[2] {name} integrity_check",
                healthy,
                "ok" if healthy else f"{len(integrity)} erreur(s) : {integrity[0][:80]}",
            )
            report.check(f"[2] {name} foreign_key_check", not fk, f"{len(fk)} violation(s)")

    with guarded(report, "[2] migrations"):
        check_migrations(manifest, repo_root, report)


def check_migrations(manifest: dict, repo_root: str | None, report: Report) -> None:
    """Le schéma appliqué correspond-il aux migrations du dépôt ?

    Les DEUX directions comptent, et pas pour la même raison :
      * dépôt ⊄ base → base plus ancienne que le code (migration non appliquée) ;
      * base ⊄ dépôt → base plus récente que le code (on restaure du vieux code
        sur une base neuve). Casse l'application tout aussi sûrement.
    """
    applied = manifest["files"].get("eurio.db", {}).get("migrations", [])
    if not repo_root:
        report.add("[2] migrations appliquées ≡ dépôt", WARN, "--repo-root absent, contrôle non effectué")
        return
    migrations_dir = os.path.join(repo_root, "ml", "serving", "migrations")
    if not os.path.isdir(migrations_dir):
        report.add("[2] migrations appliquées ≡ dépôt", WARN, f"{migrations_dir} introuvable")
        return

    on_disk = sorted(f for f in os.listdir(migrations_dir) if f.endswith(".sql"))
    missing = [m for m in on_disk if m not in applied]
    unknown = [m for m in applied if m not in on_disk]
    problems = []
    if missing:
        problems.append(f"non appliquées : {', '.join(missing)}")
    if unknown:
        problems.append(f"inconnues du dépôt : {', '.join(unknown)}")
    report.check("[2] migrations appliquées ≡ dépôt", not problems, " · ".join(problems))


# ── Niveau 3 — plausibilité sémantique ───────────────────────────────────────

def check_non_decreasing(manifest: dict, baseline: dict | None, report: Report) -> None:
    """L'invariant qui attrape une base tronquée mais parfaitement valide.

    Une décroissance peut être légitime (purge volontaire) ; elle ne doit jamais
    passer en silence. On échoue, et un humain tranche avec --accept-baseline.

    ⚠️ Une table DISPARUE compte comme une régression, pas comme un contrôle à
    sauter : un `drop table` supprime plus de lignes que n'importe quel `delete`.
    """
    if baseline is None:
        report.add(
            "[3] non-décroissance des tables surveillées",
            WARN,
            "aucune référence — contrôle INOPÉRANT ; la référence est posée pour la prochaine fois",
        )
        return

    regressions = []
    for name, info in manifest.get("files", {}).items():
        previous = baseline.get("files", {}).get(name)
        if not previous:
            continue
        # La liste surveillée vient de la baseline ET du manifeste courant :
        # un manifeste qui perdrait sa liste `watched` désactiverait sinon
        # l'invariant en silence.
        watched = set(previous.get("watched", [])) | set(info.get("watched", []))
        for table in sorted(watched):
            was = previous.get("row_counts", {}).get(table)
            now = info.get("row_counts", {}).get(table)
            if was is None:
                continue  # table apparue depuis la référence : pas une régression
            if now is None:
                regressions.append(f"{name}:{table} {was} lignes → TABLE ABSENTE")
            elif now < was:
                regressions.append(f"{name}:{table} {was} → {now} ({now - was:+d})")

        was_tables = previous.get("table_count")
        now_tables = info.get("table_count")
        if was_tables is not None and now_tables is not None and now_tables < was_tables:
            regressions.append(f"{name} : {was_tables} → {now_tables} tables")

    if regressions:
        report.add("[3] non-décroissance des tables surveillées", FAIL, " ; ".join(regressions))
        report.ack_rows.append("[3] non-décroissance des tables surveillées")
    else:
        report.check("[3] non-décroissance des tables surveillées", True)


def check_source_liveness(manifest: dict, baseline: dict | None, max_days: float, report: Report) -> None:
    """Les sources vivent-elles encore ? (D-17)

    Distinct de la fraîcheur du staging : le script peut tourner tous les jours
    sur des données figées depuis des mois. Dans ce cas la non-décroissance est
    vraie par construction et **ne prouve rien** — il faut le dire, sinon on lit
    un ✅ qui ne couvre rien.
    """
    now = dt.datetime.now(dt.UTC)
    for name, info in manifest.get("files", {}).items():
        mtime = info.get("source_mtime_utc")
        if not mtime:
            report.add(f"[3] {name} vivacité de la source", WARN, "source_mtime_utc absent du manifeste")
            continue
        age_days = (now - parse_utc(mtime)).total_seconds() / 86400
        if age_days > max_days:
            report.check(
                f"[3] {name} vivacité de la source",
                False,
                f"aucune écriture depuis {age_days:.0f} j (plafond {max_days:.0f} j) — dernière : {mtime}",
            )
            continue
        detail = f"écrite il y a {age_days:.1f} j"
        previous = (baseline or {}).get("files", {}).get(name, {}).get("source_mtime_utc")
        if previous and previous == mtime:
            report.add(
                f"[3] {name} vivacité de la source",
                WARN,
                f"{detail} — inchangée depuis la référence : la non-décroissance ne prouve rien sur cette base",
            )
        else:
            report.check(f"[3] {name} vivacité de la source", True, detail)


def check_canary(staging: str, report: Report) -> None:
    """Des pièces connues se résolvent de bout en bout.

    Ne teste pas que la base est *valide* — que le contenu est **utilisable**.
    Une base vide passe integrity_check ; elle échoue ici.

    On échantillonne plusieurs pièces réparties dans la table : une pièce unique
    laisserait passer une base dont 99 % des traductions ont disparu, si celle
    qu'on interroge fait partie du 1 % survivant.
    """
    path = os.path.join(staging, "eurio.db")
    if not os.path.exists(path):
        return
    with guarded(report, "[3] pièces canari"):
        con = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
        try:
            total = con.execute("select count(*) from coins").fetchone()[0]
            sample = con.execute(
                "select c.eurio_id,"
                " (select count(*) from coin_names_i18n n where n.eurio_id = c.eurio_id),"
                " (select count(*) from coin_canonical_images i where i.eurio_id = c.eurio_id)"
                " from coins c order by c.eurio_id"
                " limit 20 offset max(0, (select count(*) from coins) / 2 - 10)"
            ).fetchall()
            first = con.execute(
                "select c.eurio_id,"
                " (select count(*) from coin_names_i18n n where n.eurio_id = c.eurio_id)"
                " from coins c order by c.eurio_id limit 1"
            ).fetchone()
        finally:
            con.close()

        if not total or not sample:
            report.check("[3] pièces canari résolues", False, "aucune ligne dans `coins`")
            return
        if first:
            sample = list(sample) + [(first[0], first[1], None)]
        without_name = [row[0] for row in sample if not row[1]]
        without_image = [row[0] for row in sample if row[2] == 0]
        problems = []
        if without_name:
            problems.append(f"{len(without_name)}/{len(sample)} sans traduction (ex. {without_name[0]})")
        if without_image:
            problems.append(f"{len(without_image)} sans image canonique (ex. {without_image[0]})")
        report.check(
            "[3] pièces canari résolues",
            not problems,
            " · ".join(problems) if problems else f"{len(sample)} pièces sur {total} vérifiées",
        )


def check_minio_counts(manifest: dict, baseline: dict | None, report: Report) -> None:
    """Nombre d'objets par bucket, non décroissant (invariant 5).

    `rclone sync` propage les suppressions au miroir — c'est voulu (D-05), mais
    ça veut dire qu'un wipe de MinIO se propage aussi. Le miroir seul ne peut
    donc pas s'en apercevoir : c'est la comparaison à la référence qui le voit.
    """
    current = manifest.get("minio")
    if not current:
        return  # déjà signalé par check_cross_store
    previous = (baseline or {}).get("minio")
    if not previous:
        report.add("[5] objets MinIO non décroissants", WARN, "aucune référence — contrôle INOPÉRANT")
        return

    regressions = []
    for bucket, was in previous.items():
        now = current.get(bucket)
        if now is None:
            regressions.append(f"{bucket} : {was['objects']} objets → BUCKET ABSENT")
        elif now["objects"] < was["objects"]:
            delta = now["objects"] - was["objects"]
            regressions.append(f"{bucket} : {was['objects']} → {now['objects']} objets ({delta:+d})")

    if regressions:
        report.add("[5] objets MinIO non décroissants", FAIL, " ; ".join(regressions))
        report.ack_rows.append("[5] objets MinIO non décroissants")
    else:
        total = sum(b["objects"] for b in current.values())
        report.check("[5] objets MinIO non décroissants", True, f"{total} objets sur {len(current)} buckets")


def check_sample_integrity(staging: str, manifest: dict, sample_size: int, report: Report) -> None:
    """Échantillonnage aléatoire : le contenu du miroir est-il conforme (invariant 6) ?

    On tire au hasard des objets dont la base connaît le sha256 et on recalcule
    celui du fichier miroité. Sur un an, l'échantillonnage couvre
    statistiquement les ~34 000 objets sans jamais tout relire — bien plus
    efficace qu'un `rclone check` intégral, et bien meilleur détecteur de
    pourrissement lent.

    ⚠️ `image_assets.sha256` est NULL sur 100 % des lignes (DONNEES.md §4,
    bug n°1) : les crops ne sont donc pas couverts par ce contrôle. La
    couverture réelle est affichée, précisément pour qu'on ne la surestime pas.
    """
    minio_root = os.path.join(staging, "minio")
    db_path = os.path.join(staging, "eurio.db")
    if not manifest.get("minio") or not os.path.isdir(minio_root) or not os.path.exists(db_path):
        return

    import random

    with guarded(report, "[6] échantillonnage"):
        con = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
        try:
            candidates = []
            for table, bucket in DB_TO_BUCKET.items():
                rows = con.execute(
                    f"select storage_path, sha256 from {table} "
                    "where sha256 is not null and sha256 <> '' "
                    "and storage_path is not null and storage_path <> ''"
                ).fetchall()
                candidates += [
                    (bucket, path, sha)
                    for path, sha in rows
                    if not path.startswith(EXCLUDED_PREFIXES)
                ]
        finally:
            con.close()

        if not candidates:
            report.add(
                "[6] échantillon miroir ≡ sha256 de la base",
                WARN,
                "aucun objet ne porte de sha256 en base — contrôle INOPÉRANT",
            )
            return

        sample = random.sample(candidates, min(sample_size, len(candidates)))
        missing, mismatched = [], []
        for bucket, path, expected in sample:
            full = os.path.join(minio_root, bucket, path)
            if not os.path.exists(full):
                missing.append(f"{bucket}/{path}")
            elif sha256_of(full) != expected:
                mismatched.append(f"{bucket}/{path}")

        problems = []
        if missing:
            problems.append(f"{len(missing)} absent(s) du miroir (ex. {missing[0]})")
        if mismatched:
            problems.append(f"{len(mismatched)} sha256 divergent(s) (ex. {mismatched[0]})")
        report.check(
            "[6] échantillon miroir ≡ sha256 de la base",
            not problems,
            " · ".join(problems)
            if problems
            else f"{len(sample)} objets vérifiés sur {len(candidates)} vérifiables",
        )


def check_cross_store(staging: str, manifest: dict, report: Report) -> None:
    """Intégrité référentielle DB ↔ MinIO — l'invariant propre à Eurio.

    Signalé WARN tant que le miroir n'existe pas (lot 3) : un contrôle absent ne
    doit pas se lire comme un contrôle réussi.
    """
    minio_root = os.path.join(staging, "minio")
    if not manifest.get("minio") or not os.path.isdir(minio_root):
        report.add("[3] cohérence DB ↔ MinIO", WARN, "miroir absent — contrôle non applicable (lot 3)")
        return

    with guarded(report, "[3] cohérence DB ↔ MinIO"):
        con = sqlite3.connect(f"file:{os.path.join(staging, 'eurio.db')}?mode=ro", uri=True)
        try:
            for table, bucket in DB_TO_BUCKET.items():
                bucket_dir = os.path.join(minio_root, bucket)
                if not os.path.isdir(bucket_dir):
                    report.check(f"[3] {table} ↔ {bucket}", False, "bucket absent du miroir")
                    continue
                present = set()
                for dirpath, _dirnames, filenames in os.walk(bucket_dir):
                    rel = os.path.relpath(dirpath, bucket_dir)
                    for filename in filenames:
                        present.add(filename if rel == "." else f"{rel}/{filename}")
                referenced = {
                    r[0]
                    for r in con.execute(
                        f"select storage_path from {table} "
                        "where storage_path is not null and storage_path <> ''"
                    )
                    if not r[0].startswith(EXCLUDED_PREFIXES)
                }
                dangling = referenced - present
                report.check(
                    f"[3] {table} ↔ {bucket} : aucun dangling",
                    not dangling,
                    f"{len(dangling)} référence(s) sans objet"
                    if dangling
                    else f"{len(referenced)} référence(s) résolues, {len(present - referenced)} orphelin(s)",
                )
        finally:
            con.close()


def check_freshness(manifest: dict, max_age_hours: float, report: Report) -> None:
    """Le staging a-t-il été régénéré récemment ?

    Complémentaire de la vivacité des sources : celui-ci surveille le SCRIPT,
    celui-là surveille les DONNÉES.
    """
    created = manifest.get("created_utc")
    if not created:
        report.check("[3] fraîcheur du staging", False, "created_utc absent du manifeste")
        return
    age = (dt.datetime.now(dt.UTC) - parse_utc(created)).total_seconds() / 3600
    report.check(
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
    parser.add_argument("--max-source-age-days", type=float, default=90.0)
    parser.add_argument("--sample-size", type=int, default=20,
                        help="Objets MinIO tirés au hasard pour la vérification de contenu")
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

    check_scope(args.staging, manifest, report)
    check_transport(args.staging, manifest, report)
    check_structure(args.staging, manifest, args.repo_root, report)
    check_non_decreasing(manifest, baseline, report)
    check_source_liveness(manifest, baseline, args.max_source_age_days, report)
    check_canary(args.staging, report)
    check_cross_store(args.staging, manifest, report)
    check_minio_counts(manifest, baseline, report)
    check_sample_integrity(args.staging, manifest, args.sample_size, report)
    check_freshness(manifest, args.max_age_hours, report)

    report.render()
    print()

    failures = report.failures
    # L'acquittement porte sur des lignes IDENTIFIÉES, pas sur un nombre
    # d'échecs : `--accept-baseline` ne doit jamais absoudre un invariant qu'un
    # humain n'a pas regardé.
    acknowledged = (
        args.accept_baseline
        and failures
        and all(name in report.ack_rows for name, _state, _detail in failures)
    )

    if failures and not acknowledged:
        print(f"🔴 ÉCHEC — {len(failures)} invariant(s) en défaut, {len(report.warnings)} avertissement(s)")
        if any(name in report.ack_rows for name, _s, _d in failures):
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

    passed = len(report.rows) - len(failures) - len(report.warnings)
    summary = f"✅ {passed}/{len(report.rows)} invariants passés"
    if failures:
        summary += f", {len(failures)} acquitté(s)"
    if report.warnings:
        summary += f", {len(report.warnings)} avertissement(s)"
    print(summary)
    return 0


if __name__ == "__main__":
    sys.exit(main())
