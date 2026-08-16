"""Fraîcheur : qu'est-ce que j'ai sous la main, et de quand ça date.

Le besoin n'est pas d'aller plus vite entre les machines — rien dans la boucle
d'Eurio n'exige du temps réel. Le besoin est de **savoir** si la réplique sous
la main date de ce matin ou du mois dernier, sans avoir à le déduire.

Deux niveaux, exprès :

* sans argument — **local seulement, instantané, aucun réseau**. Utilisable
  hors ligne et sans secrets. C'est le mode par défaut parce qu'un diagnostic
  qui exige le réseau est inutilisable précisément quand le réseau est le
  problème.
* ``--probe`` — ajoute les questions qui exigent de parler au canonique et à la
  prod : le canonique a-t-il bougé depuis mon dernier pull, la projection
  est-elle en phase.

Chaque ligne dit **l'âge**, un **verdict**, et **la commande** qui rafraîchit.
Un verdict qu'on ne sait pas rendre s'affiche « ? » — jamais « à jour ».

Codes de sortie : 0 tout est frais · 2 au moins un élément est en retard
(``--probe`` inclus) · 1 erreur. Le 2 est distinct pour qu'un script puisse
s'en servir sans parser la sortie.
"""

from __future__ import annotations

import argparse
import json
import os
import sqlite3
import sys
import time
from pathlib import Path

_ML_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = _ML_ROOT.parent
STATE = _ML_ROOT / "state"
REPLICA = Path(os.environ.get("EURIO_REPLICA_PATH", STATE / "eurio.replica.db"))
RECEIPT = REPLICA.with_suffix(REPLICA.suffix + ".sync.json")

_OK, _STALE, _UNKNOWN = "à jour", "EN RETARD", "?"


def _age(seconds: float) -> str:
    """Durée lisible. Les âges se lisent en un coup d'œil ou ne se lisent pas."""
    if seconds < 90:
        return f"{int(seconds)} s"
    if seconds < 5400:
        return f"{seconds/60:.0f} min"
    if seconds < 172800:
        return f"{seconds/3600:.1f} h"
    return f"{seconds/86400:.1f} j"


def _mtime_age(path: Path) -> float | None:
    return None if not path.exists() else time.time() - path.stat().st_mtime


class Report:
    def __init__(self) -> None:
        self.rows: list[tuple[str, str, str, str]] = []
        self.stale = 0

    def add(self, what: str, age: str, verdict: str, fix: str = "") -> None:
        self.rows.append((what, age, verdict, fix))
        if verdict.startswith(_STALE):
            self.stale += 1

    def render(self) -> None:
        w = max(len(r[0]) for r in self.rows)
        a = max(len(r[1]) for r in self.rows)
        v = max(len(r[2]) for r in self.rows)
        print()
        print(f"  {'ÉLÉMENT'.ljust(w)}  {'ÂGE'.ljust(a)}  {'ÉTAT'.ljust(v)}  RAFRAÎCHIR")
        print(f"  {'─'*w}  {'─'*a}  {'─'*v}  {'─'*34}")
        for what, age, verdict, fix in self.rows:
            print(f"  {what.ljust(w)}  {age.ljust(a)}  {verdict.ljust(v)}  {fix}")
        print()


# ─── local ───────────────────────────────────────────────────────────────────

def _read_receipt() -> dict:
    if not RECEIPT.exists():
        return {}
    try:
        return json.loads(RECEIPT.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return {}


def local_checks(rep: Report) -> dict:
    receipt = _read_receipt()

    # Réplique — l'âge est celui du dernier pull réussi, pas du mtime du
    # fichier : un pull rsync qui n'a rien à transférer ne touche pas le mtime,
    # et on croirait la réplique vieille alors qu'elle est à jour.
    if not REPLICA.exists():
        rep.add("réplique du canonique", "absente", _STALE, "go-task ml:db:pull-replica")
    else:
        pulled_at = receipt.get("pulled_at")
        if pulled_at:
            age = time.time() - pulled_at
            verdict = _OK if age < 86400 else f"{_STALE} (> 24 h)"
            rep.add(
                "réplique du canonique",
                _age(age),
                verdict,
                "go-task ml:db:pull-replica",
            )
        else:
            # Repli sur le mtime, en le disant : sans reçu on ne connaît que la
            # date du fichier, qui sous-estime la fraîcheur.
            rep.add(
                "réplique du canonique",
                f"~{_age(_mtime_age(REPLICA))} (mtime)",
                _UNKNOWN + " sans reçu de synchro",
                "go-task ml:db:pull-replica",
            )

    # Artefacts épinglés — comparaison de contenu, purement locale.
    for label, module, fix in (
        ("artefacts d'entraînement", "scripts.training_assets", "go-task ml:training-assets:fetch"),
        ("modèles de l'APK", "scripts.model_assets", "go-task ml:assets:fetch"),
    ):
        try:
            import importlib
            import io
            import contextlib

            mod = importlib.import_module(module)
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf):
                code = mod.cmd_status(None)
            rep.add(label, "—", _OK if code == 0 else f"{_STALE} (dérive)", fix)
        except Exception as exc:  # noqa: BLE001
            rep.add(label, "—", f"{_UNKNOWN} ({exc.__class__.__name__})", fix)

    # Cache local — pas une question de fraîcheur mais de place : un cache au
    # plafond évince, et une éviction se manifeste par un FileNotFoundError
    # loin de sa cause.
    try:
        from shared.storage import local_cache

        cs = local_cache.cache_stats()
        cap = local_cache._max_gb()
        gb = cs["size_bytes"] / 1e9
        pct = f"{gb/cap*100:.0f} %" if cap else "sans plafond"
        near = cap and gb / cap > 0.9
        rep.add(
            "cache d'images",
            f"{gb:.1f} Go",
            f"{_STALE} (plafond {pct})" if near else f"{_OK} ({pct})",
            "go-task ml:cache-stats",
        )
    except Exception as exc:  # noqa: BLE001
        rep.add("cache d'images", "—", f"{_UNKNOWN} ({exc.__class__.__name__})", "")

    # Catalogue packagé — sa fraîcheur se mesure contre le canonique, localement.
    core = REPO_ROOT / "app-android" / "src" / "main" / "assets" / "app_core.db"
    if not core.exists():
        rep.add("catalogue de l'APK", "absent", _STALE, "go-task ml:build-app-core")
    else:
        rep.add(
            "catalogue de l'APK",
            _age(_mtime_age(core)),
            _catalogue_verdict(core),
            "go-task ml:build-app-core",
        )
    return receipt


def _catalogue_verdict(core: Path) -> str:
    """Le catalogue packagé reflète-t-il encore le canonique ?

    Comparaison de volume sur la table la plus structurante. Pas un contrôle
    exhaustif — c'est `build-app-core:verify` qui l'est — mais assez pour dire
    « ça a bougé depuis », qui est la question posée ici.
    """
    if not REPLICA.exists():
        return _UNKNOWN + " (pas de réplique)"
    try:
        a = sqlite3.connect(f"file:{core}?mode=ro", uri=True)
        n_core = a.execute("select count(*) from coin").fetchone()[0]
        a.close()
        b = sqlite3.connect(f"file:{REPLICA}?mode=ro", uri=True)
        n_can = b.execute("select count(*) from coins").fetchone()[0]
        b.close()
    except Exception as exc:  # noqa: BLE001
        return f"{_UNKNOWN} ({exc.__class__.__name__})"
    if n_core == n_can:
        return f"{_OK} ({n_core} pièces)"
    return f"{_STALE} ({n_core} pièces vs {n_can} au canonique)"


# ─── réseau ──────────────────────────────────────────────────────────────────

# Doit rester le miroir exact de `serving.coin_assets_routes.enrichment_counts`
# (défaut `include_unresolved=False`). Si l'un des deux change, la comparaison
# devient un faux positif permanent — c'est le risque assumé de cette approche,
# et il est préférable à un marqueur auto-invalidant.
_RESOLVED = ("resolved", "auto_resolved", "manual_resolved")


def _local_enrichment_counts() -> dict[str, int] | None:
    if not REPLICA.exists():
        return None
    try:
        con = sqlite3.connect(f"file:{REPLICA}?mode=ro", uri=True)
        try:
            from serving.coin_assets_routes import _RESOLVED_STATUSES

            statuses = list(_RESOLVED_STATUSES)
        except Exception:  # noqa: BLE001
            statuses = list(_RESOLVED)
        ph = ",".join("?" for _ in statuses)
        rows = con.execute(
            f"SELECT eurio_id, COUNT(*) FROM image_assets "
            f"WHERE eurio_id IS NOT NULL AND resolution_status IN ({ph}) "
            f"GROUP BY eurio_id",
            statuses,
        ).fetchall()
        con.close()
        return {r[0]: int(r[1]) for r in rows}
    except Exception:  # noqa: BLE001
        return None

def probe_checks(rep: Report, receipt: dict) -> None:
    # Ma réplique est-elle en retard sur le canonique ?
    #
    # On compare un AGRÉGAT MÉTIER, pas une empreinte de fichier. Le sha du
    # snapshot distant (`/db/replica/sha`) paraissait le marqueur évident : il
    # est inutilisable. Mesuré le 2026-08-16 : il change en moins de 75 s sans
    # aucune écriture métier, parce que `pat_tokens.last_used_at` est mis à
    # jour à chaque requête authentifiée — dont celle qui va chercher le sha.
    # Un marqueur auto-invalidant : le mesurer change ce qu'il mesure, et le
    # verdict serait « en retard » en permanence.
    #
    # `/coins/enrichment-counts` est un simple GROUP BY sur `image_assets`, la
    # table métier la plus mouvante. Le même agrégat se recalcule à l'identique
    # sur la réplique, donc l'écart mesuré est un vrai retard de données.
    try:
        from client import http as _http

        remote = _http.get_json("/coins/enrichment-counts")
    except Exception as exc:  # noqa: BLE001
        rep.add(
            "réplique vs canonique", "—",
            f"{_UNKNOWN} canonique injoignable ({exc.__class__.__name__})", "",
        )
        remote = None

    if remote is not None:
        local = _local_enrichment_counts()
        if local is None:
            rep.add("réplique vs canonique", "—", f"{_UNKNOWN} (pas de réplique)", "")
        else:
            n_remote, n_local = sum(remote.values()), sum(local.values())
            delta = n_remote - n_local
            differing = sum(1 for k in set(remote) | set(local) if remote.get(k) != local.get(k))
            if not differing:
                rep.add(
                    "réplique vs canonique", "—",
                    f"{_OK} ({n_local} crops, identiques)", "",
                )
            else:
                rep.add(
                    "réplique vs canonique", "—",
                    f"{_STALE} ({delta:+d} crops, {differing} pièce(s))",
                    "go-task ml:db:pull-replica",
                )

    # La projection de prod est-elle en phase avec le canonique ?
    try:
        import io
        import contextlib

        from export.app_export.io import get_pg_client, get_sqlite_con
        from export.build_app_core import (
            fetch_core,
            fetch_core_from_canonical,
            verify_subset,
        )

        con = get_sqlite_con()
        try:
            local = fetch_core_from_canonical(con)
        finally:
            con.close()
        cl = get_pg_client()
        try:
            remote = fetch_core(cl)
        finally:
            cl.close()
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            problems = verify_subset(local, remote)
        rep.add(
            "projection (Supabase)", "—",
            _OK if not problems else f"{_STALE} ({len(problems)} table(s) en retard)",
            "python -m export.app_export.run --apply",
        )
    except Exception as exc:  # noqa: BLE001
        rep.add(
            "projection (Supabase)", "—",
            f"{_UNKNOWN} injoignable ({exc.__class__.__name__})", "",
        )


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="freshness", description=__doc__)
    ap.add_argument(
        "--probe", action="store_true",
        help="Interroge aussi le canonique et la prod (réseau + secrets requis).",
    )
    args = ap.parse_args(argv)

    rep = Report()
    receipt = local_checks(rep)
    if args.probe:
        probe_checks(rep, receipt)
    rep.render()

    if rep.stale:
        print(f"  {rep.stale} élément(s) en retard.")
        if not args.probe:
            print("  (`--probe` ajoute le canonique et la projection)")
        return 2
    if not args.probe:
        print("  Tout est frais côté local. `--probe` pour interroger le canonique.")
    else:
        print("  Tout est frais.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
