"""Écritures des dimensions lab — routées vers le writer unique (Direction A, C5).

**Le problème que ce module résout.** Le devShell Mac/PC pose
``EURIO_DB_READONLY=1`` et pointe ``EURIO_DB_PATH`` sur la réplique
(``flake.nix``) : le SQLite local est un **cache read-only** du canonique. Les
routes du lab, elles, écrivaient encore en local puis poussaient au canonique en
best-effort (F09). Sous le flip, la première écriture lève
``attempt to write a readonly database`` → 503 « Route non encore reroutée ».
Créer une cohorte était donc impossible dans le shell standard.

``migration-direction-a.md`` §C5 prévoyait ce rerouting
(``serving/lab_routes.py → write API VPS``) ; c'est ce fichier.

**L'inversion.** Sous le flip, le canonique n'est plus une destination
*best-effort* après coup : c'est **la** destination. On y écrit d'abord, et son
échec est l'échec de la requête — une écriture lab qui n'atteint pas le VPS ne
doit jamais avoir l'air d'avoir réussi.

**Read-your-writes.** Le canonique écrit, la réplique locale ne le sait pas
encore ; or la route relit juste après pour répondre. On rafraîchit donc la
réplique dans la foulée. C'est peu coûteux : ``sqlite3_rsync`` est incrémental
(**~1 s** mesuré, il ne transporte que les pages modifiées) et il est fourni par
le devShell. Le repli HTTP (``GET /db/replica``, snapshot complet ~156 Mo, ~20 s)
n'est pris que si ``sqlite3_rsync`` manque — auquel cas on préfère répondre avec
la donnée poussée plutôt que d'imposer 20 s à chaque clic.

**Hors flip** (dev Model A, aucune réplique) : comportement d'origine inchangé —
écriture locale, puis push F09 best-effort.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from fastapi import HTTPException

if TYPE_CHECKING:  # pragma: no cover
    from store import ExperimentCohortRow, Store
    from store.iterations import ExperimentIterationRow

logger = logging.getLogger(__name__)

# Au-delà, on ne rafraîchit pas la réplique en ligne : voir §Read-your-writes.
_CHEAP_REFRESH_TRANSPORT = "rsync"


def local_is_replica() -> bool:
    """Vrai si le SQLite local est une réplique read-only (flip C5)."""
    from store import resolve_db_readonly  # noqa: PLC0415 — évite un cycle d'import

    return resolve_db_readonly()


def _remote_configured() -> bool:
    from client.http import remote_sync_enabled  # noqa: PLC0415

    return remote_sync_enabled()


def _require_remote() -> None:
    """Sous le flip, l'absence de canonique n'est pas récupérable.

    Sans cette garde, ``push_cohort`` renverrait ``None`` (no-op documenté quand
    aucun canonique n'est configuré) et la route répondrait 200 sans que rien
    n'ait été écrit nulle part — le pire des deux mondes.
    """
    if not _remote_configured():
        raise HTTPException(
            status_code=503,
            detail=(
                "SQLite local en lecture seule (EURIO_DB_READONLY) et aucun "
                "canonique configuré (EURIO_API_URL) : cette écriture n'a nulle "
                "part où aller. Configure EURIO_API_URL, ou retire le flip pour "
                "travailler en local."
            ),
        )


def _canonical_failed(op: str, exc: Exception) -> HTTPException:
    return HTTPException(
        status_code=502,
        detail=f"écriture canonique refusée ({op}) : {exc}",
    )


def refresh_replica() -> None:
    """Rapatrie les pages modifiées pour que la relecture voie l'écriture.

    Best-effort **délibérément** : à ce stade le canonique a déjà accepté
    l'écriture, elle n'est pas perdue. Échouer ici ne doit pas transformer un
    succès en erreur — les routes retombent sur la donnée qu'elles viennent de
    pousser, et le prochain pull rattrapera.
    """
    try:
        from client import replica  # noqa: PLC0415

        if not replica.rsync_available():
            logger.info(
                "réplique non rafraîchie : sqlite3_rsync absent, le repli HTTP "
                "(snapshot complet) coûterait ~20 s. La lecture suivante peut "
                "être en retard d'un pull."
            )
            return
        replica.pull_replica_auto()
    except Exception as exc:  # noqa: BLE001
        logger.warning("rafraîchissement de la réplique échoué : %s", exc)


# ─── Cohortes ──────────────────────────────────────────────────────────────


def write_cohort(store: "Store", row: "ExperimentCohortRow") -> None:
    """Upsert d'une cohorte, vers le writer qui fait autorité sur cette machine."""
    if not local_is_replica():
        store.upsert_cohort(row)
        _push_cohort_best_effort(row.id, store)
        return

    _require_remote()
    from client import ingest as _ingest  # noqa: PLC0415

    try:
        _ingest.push_cohort(row.to_dict())
    except Exception as exc:  # noqa: BLE001
        raise _canonical_failed(f"cohorte {row.id}", exc) from exc
    refresh_replica()


def delete_cohort(store: "Store", cohort_id: str) -> bool:
    """Supprime une cohorte. Retourne False si elle n'existait pas."""
    if not local_is_replica():
        deleted = store.delete_cohort(cohort_id)
        if deleted:
            _push_cohort_best_effort(cohort_id, store)
        return deleted

    _require_remote()
    if store.get_cohort(cohort_id) is None:
        return False
    from client import ingest as _ingest  # noqa: PLC0415

    try:
        _ingest.push_cohort_delete(cohort_id)
    except Exception as exc:  # noqa: BLE001
        raise _canonical_failed(f"suppression cohorte {cohort_id}", exc) from exc
    refresh_replica()
    return True


def _push_cohort_best_effort(cohort_id: str, store: "Store") -> None:
    """Chemin hors flip : le local fait foi, le canonique suit (F09)."""
    try:
        from client import ingest as _ingest  # noqa: PLC0415

        row = store.get_cohort(cohort_id)
        if row is None:
            _ingest.push_cohort_delete(cohort_id)
        else:
            _ingest.push_cohort(row.to_dict())
    except Exception as exc:  # noqa: BLE001
        logger.warning(
            "F09 cohort push failed for %s: %s (best-effort, ignoré)", cohort_id, exc
        )


# ─── Itérations ────────────────────────────────────────────────────────────


def _push_parent_cohort(store: "Store", cohort_id: str) -> None:
    """Le canonique refuse (409) une itération dont la cohorte lui est inconnue
    — FK ``cohort_id``, jamais nullable. On pousse donc le parent d'abord, comme
    ``iteration_runner._sync_canonical``."""
    from client import ingest as _ingest  # noqa: PLC0415

    cohort = store.get_cohort(cohort_id)
    if cohort is not None:
        _ingest.push_cohort(cohort.to_dict())


def write_iteration(store: "Store", row: "ExperimentIterationRow") -> None:
    """Upsert d'une itération, vers le writer qui fait autorité."""
    if not local_is_replica():
        store.upsert_iteration(row)
        _push_iteration_best_effort(store, row)
        return

    _require_remote()
    from client import http as _http  # noqa: PLC0415
    from serving.iteration_summary import build_iteration_push_payload  # noqa: PLC0415

    try:
        _push_parent_cohort(store, row.cohort_id)
        payload = build_iteration_push_payload(store, row)
        _http.put_json(f"/iterations/{row.id}", payload, timeout=15)
    except Exception as exc:  # noqa: BLE001
        raise _canonical_failed(f"itération {row.id}", exc) from exc
    refresh_replica()


def delete_iteration(store: "Store", iteration_id: str) -> bool:
    """Supprime une itération. Retourne False si elle n'existait pas."""
    if not local_is_replica():
        deleted = store.delete_iteration(iteration_id)
        if deleted:
            _push_iteration_delete_best_effort(iteration_id)
        return deleted

    _require_remote()
    if store.get_iteration(iteration_id) is None:
        return False
    from client import ingest as _ingest  # noqa: PLC0415

    try:
        _ingest.push_iteration_delete(iteration_id)
    except Exception as exc:  # noqa: BLE001
        raise _canonical_failed(f"suppression itération {iteration_id}", exc) from exc
    refresh_replica()
    return True


def _push_iteration_best_effort(store: "Store", row: "ExperimentIterationRow") -> None:
    try:
        from client import http as _http  # noqa: PLC0415
        from client.http import remote_sync_enabled  # noqa: PLC0415
        from serving.iteration_summary import build_iteration_push_payload  # noqa: PLC0415

        if not remote_sync_enabled():
            return
        _push_parent_cohort(store, row.cohort_id)   # ordre FK parent → enfant
        _http.put_json(f"/iterations/{row.id}", build_iteration_push_payload(store, row), timeout=15)
    except Exception as exc:  # noqa: BLE001
        logger.warning("F09 iteration push failed for %s: %s (best-effort)", row.id, exc)


def _push_iteration_delete_best_effort(iteration_id: str) -> None:
    try:
        from client import ingest as _ingest  # noqa: PLC0415

        _ingest.push_iteration_delete(iteration_id)
    except Exception as exc:  # noqa: BLE001
        logger.warning(
            "F09 iteration delete push failed for %s: %s (best-effort)", iteration_id, exc
        )
