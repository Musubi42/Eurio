"""Remapping du golden set de bench — application de la table tranchée à l'œil.

Pourquoi ce script existe
-------------------------
`ml/datasets/eval_real_norm/` porte 30 dossiers / 180 photos, nommés d'après
l'`eurio_id` que l'APK Android portait **au moment de la capture**
(`ml/vision/sync_eval_real.py`). Ce nom est un instantané d'un catalogue
périmé, pas une vérité de référentiel : 14 dossiers sur 30 pointent un slug
mort, et **deux d'entre eux mentent sur le millésime de la pièce photographiée**.
Le bench ne portait donc que sur 96 photos utiles sur 180, et une évaluation
à la pièce (par opposition à la classe) aurait été fausse sans le dire.

La table de correspondance a été établie le 2026-08-17 **en regardant chaque
photo**, jamais par ressemblance de chaînes — c'est documenté dans
`docs/work-in-progress/bench-golden-set-remap.md`. Ce script ne rejuge rien :
il applique. Il fait deux choses, séparables (`--scope`) :

1. **Journal** — consigne les renommages dans `eurio_id_migrations`
   (`ml/state/schema.sql:1177`), la table prévue exactement pour ça, déjà
   porteuse du split belge 2017 et classée « patrimoine » par
   `wipe_referential.py`. ⛔ Surtout pas `coin_aliases`, qui est du vocabulaire
   de marché eBay.
2. **Fichiers** — réconcilie les dossiers : renomme quand la cible est absente,
   **fusionne** quand elle est déjà là et que les captures sont octet-pour-octet
   identiques, **refuse tout le run** dès qu'un sha256 diverge.

⛔ Ne jamais « rafraîchir » avec `go-task ml:eval-real:sync` : la tâche embarque
`--clear` en dur et effacerait les 96 photos saines.

14 lignes, 11 cibles
--------------------
Le doc parle de « 11 renommages » : ce sont les **11 pièces cibles distinctes**.
Le journal, lui, écrit **14 lignes** — une par slug mort. Trois paires de
dossiers sont la même capture sous deux orthographes ; n'en journaliser qu'une
laisserait les trois autres slugs morts irrésolubles pour quiconque les
rencontre plus tard (gold de bench, exports, historique d'APK). Les
correspondances, elles, sont inchangées : 14 → 11.

Le cas belge
------------
`be-2008-2eur-standard` porte une pièce **datée 2011**, 2ᵉ portrait. Le
référentiel n'a **aucune pièce belge entre 2010 et 2013** dans ce groupe :
`be-2euro-albert-ii-t2` s'arrête à ses membres 2008 et 2009. La capture est
rattachable à la **classe**, à aucune **pièce**. Choix fait ici : rattachement
au représentant 2ᵉ portrait du groupe (le membre 2008), mais avec
`resolution='needs_rematch'` et un drapeau `class_level_only` — pour qu'un
benchmark **à la pièce** puisse l'exclure au lieu de compter une fausse
réussite. Marquer cette ligne `deterministic` serait le silence qu'on veut
éviter. Le vrai correctif reste de créer la pièce 2011 manquante.

Où part l'écriture
------------------
`eurio_id_migrations` vit au **canonique (VPS)**. Sous le flip Direction A
(`EURIO_DB_READONLY=1` posé par le devShell) la réplique locale est en lecture
seule, et **aucune route `/ingest/*` n'expose cette table** (vérifié sur
l'OpenAPI du canonique le 2026-08-17). Le script **refuse** donc d'écrire le
journal depuis une machine cliente plutôt que de le déposer dans une base
locale qui divergerait en silence — cf. skill `eurio-data-writes`. Il émet à la
place un SQL rejouable (`--emit-sql`) à appliquer au canonique.

Usage::

    python -m scripts.remap_bench_golden_set                     # dry-run (défaut)
    python -m scripts.remap_bench_golden_set --emit-sql /tmp/j.sql
    python -m scripts.remap_bench_golden_set --scope fs --apply  # renomme les dossiers
    python -m scripts.remap_bench_golden_set --scope journal --apply   # VPS uniquement
"""

from __future__ import annotations

import argparse
import hashlib
import shutil
import sqlite3
import sys
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

DEFAULT_ROOT = ROOT / "datasets" / "eval_real_norm"

BATCH_ID = "bench-golden-remap-2026-08-17"
DECIDED_BY = "preuve-visuelle-2026-08-17"

# Représentant 2ᵉ portrait du groupe be-2euro-albert-ii-t2 (cf. §Le cas belge).
BE_T2_REPRESENTATIVE = "be-2008-2eur-standard-albert-ii-2nd-map-2nd-type-2nd-portrait"


class RemapRefused(RuntimeError):
    """Le plan ne peut pas être établi sans risque — rien n'est appliqué."""


class CanonicalUnreachable(RuntimeError):
    """Le journal doit aller au canonique, et cette machine ne peut pas l'atteindre."""


@dataclass(frozen=True)
class Mapping:
    old_eurio_id: str
    new_eurio_id: str
    design_group: str | None
    reason: str
    resolution: str = "deterministic"
    class_level_only: bool = False


_R_DUP = "Capture identique (sha256) à son jumeau orthographique ; slug d'APK périmé."
_R_STD = "Slug d'APK périmé ; identification confirmée sur la photo (2026-08-17)."

MAPPING: tuple[Mapping, ...] = (
    # ── les trois paires de doublons (même capture, deux orthographes) ──
    Mapping("at-2002-2eur-standard", "at-2002-2eur-standard-1st-map",
            "at-2euro-standard-t1", f"Bertha von Suttner. {_R_STD}"),
    Mapping("at-2eur-standard-2002", "at-2002-2eur-standard-1st-map",
            "at-2euro-standard-t1", f"Bertha von Suttner. {_R_DUP}"),
    Mapping("be-2007-2eur-standard",
            "be-2007-2eur-standard-albert-ii-2nd-map-1st-type-1st-portrait",
            "be-2euro-albert-ii-t1", f"Albert II, 1er portrait, 2007. {_R_STD}"),
    Mapping("be-2eur-standard-2007",
            "be-2007-2eur-standard-albert-ii-2nd-map-1st-type-1st-portrait",
            "be-2euro-albert-ii-t1", f"Albert II, 1er portrait, 2007. {_R_DUP}"),
    Mapping("es-1999-2eur-standard",
            "es-1999-2eur-standard-juan-carlos-i-1st-type-1st-map",
            "es-2euro-juan-carlos-i-t1", f"Juan Carlos I, ESPAÑA, 2002. {_R_STD}"),
    Mapping("es-2eur-standard-1999",
            "es-1999-2eur-standard-juan-carlos-i-1st-type-1st-map",
            "es-2euro-juan-carlos-i-t1", f"Juan Carlos I, ESPAÑA, 2002. {_R_DUP}"),
    # ── renommages purs (même pièce, libellé de slug rafraîchi) ──
    Mapping("be-2011-2eur-1st-centenary-of-the-international-womens-day",
            "be-2011-2eur-100th-international-womens-day", None,
            f"Deux visages, BE 2011. {_R_STD}"),
    Mapping("es-2016-2eur-old-city-of-segovia-and-its-aqueduct",
            "es-2016-2eur-old-town-of-segovia-and-its-aqueduct", None,
            f"Aqueduc, ESPAÑA 2016 (city→town). {_R_STD}"),
    Mapping("fr-2016-2eur-100-years-since-the-birth-of-francois-mitterrand",
            "fr-2016-2eur-100th-anniversary-of-the-birth-of-francois-mitterrand", None,
            f"Portrait Mitterrand. {_R_STD}"),
    Mapping("it-2016-2eur-2200-years-since-the-death-of-plautus",
            "it-2016-2eur-2200th-anniversary-of-the-death-of-plautus", None,
            f"Masques, PLAUTO. {_R_STD}"),
    Mapping("it-2016-2eur-550-years-since-the-death-of-donatello",
            "it-2016-2eur-550th-anniversary-of-the-death-of-donatello", None,
            f"DONATELLO. {_R_STD}"),
    Mapping("mt-2008-2eur-standard", "mt-2008-2eur-standard-2nd-map",
            "mt-2euro-standard-t1", f"Croix de Malte. {_R_STD}"),
    # ── 🔴 les deux lignes où le nom de dossier ment sur le millésime ──
    Mapping("fr-2eur-standard-2007", "fr-1999-2eur-standard-1st-map",
            "fr-2euro-standard-t1",
            "Le nom appelait fr-2007-…-2nd-map ; la photo (close_plain, "
            "daylight_plain) montre l'arbre de vie daté 2000 → 1re carte. "
            "Même design_group, donc l'erreur restait invisible à l'évaluation "
            "par classe et fausse à l'évaluation à la pièce."),
    Mapping("be-2008-2eur-standard", BE_T2_REPRESENTATIVE,
            "be-2euro-albert-ii-t2",
            "Le nom appelait une standard 2008 ; la photo montre le 2e portrait "
            "daté 2011 (close_plain). Le référentiel n'a AUCUNE pièce belge "
            "entre 2010 et 2013 : le groupe be-2euro-albert-ii-t2 s'arrête à ses "
            "membres 2008 et 2009. Rattachement au représentant 2e portrait du "
            "groupe (membre 2008) : valide à la CLASSE, faux à la PIÈCE. "
            "needs_rematch jusqu'à création de la pièce 2011 manquante.",
            resolution="needs_rematch", class_level_only=True),
)


def by_old(old_eurio_id: str) -> Mapping:
    for m in MAPPING:
        if m.old_eurio_id == old_eurio_id:
            return m
    raise KeyError(old_eurio_id)


# ── réconciliation des dossiers ───────────────────────────────────────────


@dataclass(frozen=True)
class FsAction:
    kind: str  # rename | merge | done | absent
    old: str
    new: str
    detail: str = ""


def _dir_digest(d: Path) -> dict[str, str]:
    """sha256 par fichier — la comparaison de noms ne suffit pas."""
    out = {}
    for p in sorted(d.iterdir()):
        if p.is_file():
            out[p.name] = hashlib.sha256(p.read_bytes()).hexdigest()
    return out


def plan_filesystem(root: Path) -> list[FsAction]:
    """Établit le plan complet AVANT d'écrire quoi que ce soit.

    Lève ``RemapRefused`` au premier écart : on ne renomme pas la moitié d'un
    lot pour découvrir ensuite qu'une fusion était impossible.
    """
    actions: list[FsAction] = []
    # Deux slugs morts peuvent viser la MÊME cible absente (les paires de
    # doublons) : le premier la crée, le second doit donc être une fusion —
    # sinon `rename` échoue sur un dossier non vide. On simule l'état futur.
    planned: dict[str, Path] = {}
    for m in MAPPING:
        src, dst = root / m.old_eurio_id, root / m.new_eurio_id
        if not src.exists():
            exists = dst.exists() or m.new_eurio_id in planned
            actions.append(
                FsAction("done" if exists else "absent", m.old_eurio_id,
                         m.new_eurio_id,
                         "cible déjà en place" if exists else "ni source ni cible")
            )
            continue
        if not dst.exists() and m.new_eurio_id not in planned:
            planned[m.new_eurio_id] = src
            actions.append(FsAction("rename", m.old_eurio_id, m.new_eurio_id,
                                    f"{len(_dir_digest(src))} photos"))
            continue
        ref = dst if dst.exists() else planned[m.new_eurio_id]
        a, b = _dir_digest(src), _dir_digest(ref)
        if set(a) != set(b):
            raise RemapRefused(
                f"{m.old_eurio_id} → {m.new_eurio_id} : la cible existe mais les "
                f"jeux de fichiers diffèrent ({sorted(set(a) ^ set(b))}). "
                "Fusion refusée — vérifier à la main."
            )
        diverging = [k for k in a if a[k] != b[k]]
        if diverging:
            raise RemapRefused(
                f"{m.old_eurio_id} → {m.new_eurio_id} : la cible existe mais les "
                f"sha256 divergent sur {diverging}. Ce ne sont PAS les mêmes "
                "captures — fusion refusée, rien n'a été modifié."
            )
        actions.append(FsAction("merge", m.old_eurio_id, m.new_eurio_id,
                                f"{len(a)} photos identiques (sha256)"))
    return actions


def apply_filesystem(root: Path, actions: list[FsAction]) -> None:
    for a in actions:
        src, dst = root / a.old, root / a.new
        if a.kind == "rename":
            src.rename(dst)
        elif a.kind == "merge":
            shutil.rmtree(src)


# ── journal `eurio_id_migrations` ─────────────────────────────────────────


def plan_journal(conn: sqlite3.Connection) -> list[Mapping]:
    """Lignes restant à écrire — les couples (old, new) déjà journalisés sous
    ce batch sont ignorés (idempotence)."""
    seen = {
        (r[0], r[1])
        for r in conn.execute(
            "SELECT old_eurio_id, new_eurio_id FROM eurio_id_migrations "
            "WHERE batch_id = ?",
            (BATCH_ID,),
        )
    }
    return [m for m in MAPPING if (m.old_eurio_id, m.new_eurio_id) not in seen]


def _row(m: Mapping) -> tuple:
    return (BATCH_ID, "rename", m.old_eurio_id, m.new_eurio_id, m.resolution,
            "pending", m.reason, DECIDED_BY)


_INSERT = (
    "INSERT INTO eurio_id_migrations "
    "(batch_id, kind, old_eurio_id, new_eurio_id, resolution, status, reason, decided_by) "
    "VALUES (?, ?, ?, ?, ?, ?, ?, ?)"
)


def apply_journal(conn: sqlite3.Connection, pending: list[Mapping]) -> int:
    if not pending:
        return 0
    conn.executemany(_INSERT, [_row(m) for m in pending])
    conn.commit()
    return len(pending)


def emit_sql(pending: list[Mapping]) -> str:
    """SQL rejouable à appliquer au canonique (VPS) — idempotent par batch."""
    def q(v):
        return "NULL" if v is None else "'" + str(v).replace("'", "''") + "'"

    lines = [
        f"-- eurio_id_migrations · batch {BATCH_ID}",
        "-- Généré par ml/scripts/remap_bench_golden_set.py (ne pas éditer à la main).",
        "-- À appliquer sur le canonique (VPS) : aucune route /ingest ne l'expose.",
        "BEGIN;",
    ]
    for m in pending:
        vals = ", ".join(q(v) for v in _row(m))
        lines.append(
            f"INSERT INTO eurio_id_migrations (batch_id, kind, old_eurio_id, "
            f"new_eurio_id, resolution, status, reason, decided_by)\n"
            f"  SELECT {vals}\n"
            f"  WHERE NOT EXISTS (SELECT 1 FROM eurio_id_migrations "
            f"WHERE batch_id={q(BATCH_ID)} AND old_eurio_id={q(m.old_eurio_id)} "
            f"AND new_eurio_id={q(m.new_eurio_id)});"
        )
    lines.append("COMMIT;")
    return "\n".join(lines) + "\n"


def _require_canonical_write() -> None:
    """Refuse l'écriture du journal depuis une machine cliente Direction A.

    Le devShell pose ``EURIO_DB_READONLY=1`` et pointe ``EURIO_DB_PATH`` sur la
    réplique : écrire ici serait soit un `readonly database`, soit — pire — une
    divergence silencieuse dans une base locale que rien ne resynchronise.
    """
    from store import resolve_db_readonly  # noqa: PLC0415

    client = resolve_db_readonly()
    if not client:
        try:
            from client.http import sync_enabled  # noqa: PLC0415

            client = sync_enabled()
        except ImportError:
            client = False
    if client:
        raise CanonicalUnreachable(
            "eurio_id_migrations vit au canonique (VPS) et AUCUNE route /ingest/* "
            "ne l'expose (OpenAPI vérifié le 2026-08-17). Cette machine est une "
            "cliente Direction A (EURIO_DB_READONLY / EURIO_API_URL) : écrire le "
            "journal ici le déposerait dans une réplique que rien ne resynchronise. "
            "Chemin propre : (a) --emit-sql puis appliquer le fichier sur le "
            "canonique du VPS, ou (b) ouvrir une route /ingest/eurio-id-migrations "
            "et un client.ingest.push_eurio_id_migrations. Cf. skill eurio-data-writes."
        )


# ── rapport ───────────────────────────────────────────────────────────────


def run(*, root: Path, apply: bool, scope: str = "all",
        journal_conn: sqlite3.Connection | None = None,
        emit_sql_path: Path | None = None) -> int:
    mode = "APPLY" if apply else "DRY-RUN"
    print(f"── remap golden set de bench · {mode} · scope={scope}")
    print(f"   racine : {root}")
    print(f"   batch  : {BATCH_ID}  ·  decided_by : {DECIDED_BY}")
    print(f"   table  : {len(MAPPING)} slugs morts → "
          f"{len({m.new_eurio_id for m in MAPPING})} pièces cibles distinctes")

    if scope in ("all", "fs"):
        print("\n── dossiers (ml/datasets/eval_real_norm/)")
        actions = plan_filesystem(root)  # lève RemapRefused avant tout write
        width = max(len(a.old) for a in actions)
        for a in actions:
            flag = " 🔴" if by_old(a.old).class_level_only else ""
            print(f"   [{a.kind:<6}] {a.old:<{width}} → {a.new}{flag}")
            if a.detail:
                print(f"             {a.detail}")
        counts: dict[str, int] = {}
        for a in actions:
            counts[a.kind] = counts.get(a.kind, 0) + 1
        print(f"   résumé : {counts}")
        if apply:
            apply_filesystem(root, actions)
            print("   → appliqué.")
        else:
            print("   → rien écrit (dry-run ; --apply pour appliquer).")

    if scope in ("all", "journal"):
        print("\n── journal eurio_id_migrations")
        if journal_conn is None and apply:
            _require_canonical_write()
        pending = plan_journal(journal_conn) if journal_conn is not None else list(MAPPING)
        if journal_conn is None:
            print("   (aucune connexion canonique — plan théorique complet)")
        print(f"   {len(pending)} ligne(s) à écrire, kind='rename', status='pending'")
        for m in pending:
            mark = "🔴" if m.class_level_only else "  "
            print(f"   {mark} {m.old_eurio_id}")
            print(f"      → {m.new_eurio_id}  [{m.resolution}]")
        if apply and journal_conn is not None:
            n = apply_journal(journal_conn, pending)
            print(f"   → {n} ligne(s) écrite(s).")
        else:
            print("   → rien écrit.")

    be = by_old("be-2008-2eur-standard")
    print("\n── CAS BELGE — traité explicitement, pas en silence")
    print(f"   {be.old_eurio_id} porte une pièce datée 2011 (2e portrait).")
    print("   Le référentiel n'a aucune pièce belge 2010-2013 dans ce groupe :")
    print("   be-2euro-albert-ii-t2 = {2008 (2e portrait), 2009 (1er portrait)}.")
    print(f"   Décision : rattachement au représentant → {be.new_eurio_id}")
    print(f"   resolution = {be.resolution} · class_level_only = {be.class_level_only}")
    print("   ⇒ valide à la CLASSE, faux à la PIÈCE : un bench par pièce doit")
    print("     exclure cette capture tant que la pièce 2011 n'est pas créée.")

    if emit_sql_path is not None:
        sql = emit_sql(list(MAPPING) if journal_conn is None else plan_journal(journal_conn))
        emit_sql_path.write_text(sql, encoding="utf-8")
        print(f"\n── SQL canonique écrit : {emit_sql_path}")
    return 0


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    ap = argparse.ArgumentParser(description="Remapping du golden set de bench.")
    ap.add_argument("--apply", action="store_true",
                    help="Écrit réellement. Sans ce drapeau : dry-run (défaut).")
    ap.add_argument("--scope", choices=("all", "fs", "journal"), default="all")
    ap.add_argument("--root", type=Path, default=DEFAULT_ROOT)
    ap.add_argument("--emit-sql", type=Path, default=None,
                    help="Écrit le SQL rejouable pour le canonique (VPS).")
    return ap.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        return run(root=args.root, apply=args.apply, scope=args.scope,
                   emit_sql_path=args.emit_sql)
    except (RemapRefused, CanonicalUnreachable) as exc:
        print(f"\nREFUS : {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
