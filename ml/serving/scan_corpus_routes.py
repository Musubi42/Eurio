"""Routes du corpus d'évaluation — voir les photos qui jugent une classe, et agir.

Ce que ce router sert (juge-et-banc, livrable 5)
-----------------------------------------------
La fiche pièce de ``studio-local`` montre déjà les images canoniques et les
crops d'enrichissement. Il lui manquait **ce qui juge la classe** : les 451
captures device de ``ml/state/scan_corpus.db``. Les montrer ne suffit pas — le
PO veut se faire un avis **par photo** :

* **remap** — cette photo montre une autre pièce (le geste s'écrivait jusqu'ici
  dans un dictionnaire Python, ``scripts/import_device_pull.EXTRA_MAPPING``) ;
* **garder / écarter** — cette photo n'est pas exploitable comme juge (cadrage
  raté, pièce illisible, doublon).

Les deux gestes sont journalisés (``scan_corpus_decisions``) : qui, quand,
ancien état → nouvel état. Un avis sans trace ne se re-discute pas.

⚠️ Un seul pool, pas deux protocoles
------------------------------------
Décision PO du 2026-08-25 : *« une photo de val pour une classe, c'est une
photo »*. Les 451 captures forment **un seul pool** mélangé. ``bundle_source``
reste rendu comme **provenance** (d'où vient la photo), jamais comme axe de
lecture. Le découpage avril/juin était un instrument médico-légal, utilisé une
fois dans ``LOT4-RESULTATS.md`` pour mesurer la fuite de centroïdes ; la fuite
fermée, il ne décrit plus rien d'utile.

⚠️ La maille : une photo juge une CLASSE, pas toujours une pièce
----------------------------------------------------------------
Le label ArcFace est ``COALESCE(design_group_id, eurio_id)``. Pour une pièce
**courante**, les photos appartiennent au groupe de dessin : celles d'une autre
année du même groupe jugent la même classe. La réponse le **dit** (``scope``,
``class_kind``, ``is_exact_match`` par capture) au lieu de laisser l'écran
mentir sur ce qu'il montre.

⛔ Ce router ne joint JAMAIS ``eurio.db`` en écriture. Sa seule lecture du
référentiel est le garde-fou ``eurio_id`` (même garde qu'à l'import) : on
refuse de poser une vérité terrain qui ne désigne aucune pièce.
"""
from __future__ import annotations

import json
import logging
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import FileResponse
from pydantic import BaseModel

from store.scan_corpus import EVAL_DECISIONS, ScanCapture, ScanCorpusStore

from . import auth as api_auth
from .thumbnails import ThumbnailCache, safe_child

logger = logging.getLogger(__name__)

ML_DIR = Path(__file__).resolve().parent.parent
THUMBNAIL_ROOT = ML_DIR / "output" / "scan_corpus_thumbnails"

router = APIRouter(prefix="/scan-corpus", tags=["scan-corpus"])

#: Même brique que ``benchmark_routes`` (``serving/thumbnails.py``) — même TTL,
#: même garde de traversée, un seul nettoyage à maintenir.
_thumbs = ThumbnailCache(THUMBNAIL_ROOT)

_store: ScanCorpusStore | None = None


def get_store() -> ScanCorpusStore:
    """Store paresseux — la base est créée au premier appel, pas au boot."""
    global _store
    if _store is None:
        _store = ScanCorpusStore()
    return _store


def cleanup_expired_thumbnails() -> int:
    """Éviction TTL, appelée au démarrage du serveur (cf. ``server.py``)."""
    return _thumbs.cleanup_expired()


# ─── Référentiel : lecture seule, et jamais fatale ──────────────────────────


class _Referential:
    """Cache du résolveur de classes. Rechargé si la lecture avait échoué.

    Lit ``eurio.db`` en **lecture seule** via ``store.class_resolver``, qui
    honore ``EURIO_DB_PATH`` (donc la réplique sur Mac/PC). Injoignable n'est
    pas une panne du corpus : la lecture dégrade proprement (``available``
    faux), l'**écriture** refuse (503) — on n'écrit pas un label qu'on ne sait
    pas confronter.
    """

    def __init__(self) -> None:
        self._resolver = None

    def resolver(self):
        if self._resolver is None:
            try:
                from store.class_resolver import Resolver, coin_refs_from_sqlite

                self._resolver = Resolver(coin_refs_from_sqlite())
            except Exception as exc:  # noqa: BLE001
                logger.warning("scan-corpus: référentiel injoignable (%s)", exc)
                return None
        return self._resolver

    def reset(self) -> None:
        self._resolver = None


_referential = _Referential()


# ─── Payloads ───────────────────────────────────────────────────────────────


class RemapPayload(BaseModel):
    eurio_id: str
    #: ``None`` = on garde le drapeau existant. ``True`` = « juste à la classe,
    #: faux à la pièce » (le référentiel n'a pas la pièce montrée).
    class_level_only: bool | None = None
    reason: str | None = None
    decided_by: str | None = None


class EvalDecisionPayload(BaseModel):
    #: ``'keep'`` · ``'exclude'`` · ``None`` (ré-ouvre l'avis).
    decision: str | None = None
    reason: str | None = None
    decided_by: str | None = None


# ─── Helpers ────────────────────────────────────────────────────────────────


def _sanitize_capture_id(capture_id: str) -> str:
    """Refuse tout ce qui n'est pas un identifiant nu (motif ``_sanitize_run_id``).

    C'est ce garde qui rend ``/scan-corpus/thumbnail/..%2F..%2Fetc%2Fpasswd``
    un **400** et non un fichier servi : Starlette décode ``%2F`` dans un
    paramètre de chemin, donc le ``..`` arrive bien jusqu'ici.
    """
    if (
        not capture_id
        or "/" in capture_id
        or "\\" in capture_id
        or ".." in capture_id
        or len(capture_id) > 128
    ):
        raise HTTPException(status_code=400, detail="capture_id invalide")
    return capture_id


def _decisions_by_capture(
    store: ScanCorpusStore, capture_ids: list[str]
) -> dict[str, list[dict]]:
    if not capture_ids:
        return {}
    placeholders = ", ".join("?" for _ in capture_ids)
    rows = store.connection().execute(
        f"SELECT * FROM scan_corpus_decisions WHERE capture_id IN ({placeholders}) "
        "ORDER BY id",
        capture_ids,
    ).fetchall()
    out: dict[str, list[dict]] = {}
    for r in rows:
        out.setdefault(r["capture_id"], []).append(dict(r))
    return out


def _normalize_method(capture: ScanCapture) -> str | None:
    """``quality_json.normalize.method`` — QUATRE normaliseurs cohabitent dans
    les crops stockés (mesuré : ``hough_tight`` 113, ``hough_relaxed`` 1,
    ``hough_strict`` 280, ``hough_loose`` 57). Le dire sur la vignette évite de
    prendre une différence de code pour une différence de prise de vue."""
    if not capture.quality_json:
        return None
    try:
        q = json.loads(capture.quality_json)
    except (json.JSONDecodeError, TypeError):
        return None
    norm = q.get("normalize")
    return norm.get("method") if isinstance(norm, dict) else None


def _capture_dict(capture: ScanCapture, requested_eurio_id: str, decisions) -> dict:
    return {
        "capture_id": capture.capture_id,
        "eurio_id": capture.eurio_id,
        "is_exact_match": capture.eurio_id == requested_eurio_id,
        "condition": capture.condition,
        # Provenance, pas axe d'analyse (cf. docstring du module).
        "bundle_source": capture.bundle_source,
        "captured_at": capture.captured_at,
        "device_model": capture.device_model,
        "raw_w": capture.raw_w,
        "raw_h": capture.raw_h,
        "crop_w": capture.crop_w,
        "crop_h": capture.crop_h,
        "normalize_method": _normalize_method(capture),
        "class_level_only": capture.class_level_only,
        "eval_decision": capture.eval_decision,
        "eval_decision_by": capture.eval_decision_by,
        "eval_decision_at": capture.eval_decision_at,
        "eval_decision_reason": capture.eval_decision_reason,
        "notes": capture.notes,
        "crop_url": f"/scan-corpus/thumbnail/{capture.capture_id}",
        "raw_url": f"/scan-corpus/thumbnail/{capture.capture_id}?kind=raw",
        "decisions": decisions,
    }


# ─── Routes ─────────────────────────────────────────────────────────────────


@router.get("/captures/{eurio_id}")
def list_captures_for_coin(
    eurio_id: str,
    include_excluded: bool = Query(
        True,
        description=(
            "Inclure les captures écartées par un humain (eval_decision="
            "'exclude'). Vrai par défaut : l'écran doit pouvoir les revoir "
            "pour revenir sur l'avis."
        ),
    ),
) -> dict:
    """Photos d'évaluation d'une pièce — **ou de son groupe de dessin**.

    La maille est dite dans la réponse, jamais devinée par l'appelant :

    * ``class_id`` / ``class_kind`` — la classe que ces photos jugent ;
    * ``scope`` — ``coin`` si toutes les captures rendues portent l'``eurio_id``
      demandé, ``design_group`` dès qu'au moins une vient d'une autre pièce du
      même groupe ;
    * ``is_exact_match`` par capture.

    404 si l'``eurio_id`` est inconnu du référentiel (et sans capture) : une
    section vide sur un slug mort ferait croire à une pièce sans photos.
    """
    store = get_store()
    resolver = _referential.resolver()

    class_id = eurio_id
    class_kind = "eurio_id"
    class_eurio_ids = [eurio_id]
    if resolver is not None:
        descriptor = resolver.for_eurio(eurio_id)
        if descriptor is None:
            raise HTTPException(
                status_code=404,
                detail=f"eurio_id inconnu du référentiel: {eurio_id}",
            )
        class_id = descriptor.class_id
        class_kind = descriptor.class_kind
        class_eurio_ids = list(descriptor.eurio_ids)

    captures = store.list_captures(
        eurio_ids=class_eurio_ids, exclude_rejected=not include_excluded
    )
    if resolver is None and not captures:
        raise HTTPException(
            status_code=404,
            detail=(
                f"aucune capture pour {eurio_id} et référentiel injoignable — "
                "impossible de dire si la pièce existe"
            ),
        )

    decisions = _decisions_by_capture(store, [c.capture_id for c in captures])
    rows = [
        _capture_dict(c, eurio_id, decisions.get(c.capture_id, [])) for c in captures
    ]
    n_exact = sum(1 for r in rows if r["is_exact_match"])
    scope = "coin" if n_exact == len(rows) else "design_group"
    return {
        "eurio_id": eurio_id,
        "class_id": class_id,
        "class_kind": class_kind,
        "class_eurio_ids": class_eurio_ids,
        "scope": scope,
        "scope_note": (
            "Les photos rendues sont celles de cette pièce."
            if scope == "coin"
            else (
                "Ces photos jugent le GROUPE DE DESSIN "
                f"« {class_id} » : certaines montrent une autre pièce du groupe. "
                "C'est la maille de la classe, pas une erreur de label."
            )
        ),
        "referential_available": resolver is not None,
        "n_captures": len(rows),
        "n_exact_match": n_exact,
        "n_class_level_only": sum(1 for r in rows if r["class_level_only"]),
        "n_excluded": sum(1 for r in rows if r["eval_decision"] == "exclude"),
        "n_kept": sum(1 for r in rows if r["eval_decision"] == "keep"),
        "n_undecided": sum(1 for r in rows if r["eval_decision"] is None),
        "captures": rows,
    }


@router.get("/thumbnail/{capture_id}")
def capture_thumbnail(
    capture_id: str,
    kind: str = Query("crop", pattern="^(crop|raw)$"),
) -> FileResponse:
    """Vignette 256 px d'une capture. ``kind=raw`` sert la photo d'origine.

    Deux gardes, indépendants : ``_sanitize_capture_id`` sur l'identifiant
    (400), et ``safe_child`` sur le chemin **stocké en base** (400 aussi) — le
    second couvre le cas où une ligne du corpus porterait un chemin sortant de
    ``frames_root``, que le premier ne voit pas.
    """
    _sanitize_capture_id(capture_id)
    store = get_store()
    capture = store.get_capture(capture_id)
    if capture is None:
        raise HTTPException(status_code=404, detail="capture inconnue")
    rel = capture.raw_path if kind == "raw" else capture.crop_path
    src = safe_child(store.frames_root, rel)
    dst = _thumbs.ensure(f"{capture_id}:{kind}", src)
    return FileResponse(dst, media_type="image/jpeg")


@router.post("/captures/{capture_id}/remap")
def remap_capture(
    capture_id: str,
    payload: RemapPayload,
    token_name: str | None = Depends(api_auth.require_token),
) -> dict:
    """Réattribue une capture à une autre pièce. Journalisé, jamais silencieux.

    Garde-fou identique à celui de l'import : un ``eurio_id`` absent du
    référentiel est **refusé** (400), pas écrit. Référentiel injoignable →
    **503** : on ne pose pas une vérité terrain qu'on ne sait pas confronter.
    """
    _sanitize_capture_id(capture_id)
    store = get_store()
    new_id = payload.eurio_id.strip()
    if not new_id:
        raise HTTPException(status_code=400, detail="eurio_id vide")

    resolver = _referential.resolver()
    if resolver is None:
        raise HTTPException(
            status_code=503,
            detail=(
                "référentiel injoignable — remap refusé (le garde-fou eurio_id "
                "ne peut pas être exercé)"
            ),
        )
    if resolver.for_eurio(new_id) is None:
        raise HTTPException(
            status_code=400,
            detail=f"eurio_id absent du référentiel: {new_id}",
        )

    try:
        capture = store.relabel_capture(
            capture_id,
            new_id,
            class_level_only=payload.class_level_only,
            reason=payload.reason,
            decided_by=payload.decided_by or token_name or "local",
        )
    except KeyError:
        raise HTTPException(status_code=404, detail="capture inconnue") from None

    decisions = store.list_decisions(capture_id)
    return {
        "capture": _capture_dict(capture, capture.eurio_id, decisions),
        "decisions": decisions,
    }


@router.post("/captures/{capture_id}/eval-decision")
def set_eval_decision(
    capture_id: str,
    payload: EvalDecisionPayload,
    token_name: str | None = Depends(api_auth.require_token),
) -> dict:
    """Garde ou écarte une photo **pour l'évaluation**. Journalisé.

    ⚠️ Poser l'avis ne suffit pas encore : le juge
    (``scripts/replay_corpus.py``) **ne filtre pas** sur ``eval_decision``. Le
    store sait le faire (``list_captures(exclude_rejected=True)``), le câblage
    reste à faire — c'est un reste-à-faire assumé, pas un oubli.
    """
    _sanitize_capture_id(capture_id)
    if payload.decision is not None and payload.decision not in EVAL_DECISIONS:
        raise HTTPException(
            status_code=400,
            detail=(
                f"decision invalide: {payload.decision!r} "
                f"(attendu {' | '.join(EVAL_DECISIONS)} ou null)"
            ),
        )
    store = get_store()
    try:
        capture = store.set_eval_decision(
            capture_id,
            payload.decision,
            reason=payload.reason,
            decided_by=payload.decided_by or token_name or "local",
        )
    except KeyError:
        raise HTTPException(status_code=404, detail="capture inconnue") from None

    decisions = store.list_decisions(capture_id)
    return {
        "capture": _capture_dict(capture, capture.eurio_id, decisions),
        "decisions": decisions,
    }
