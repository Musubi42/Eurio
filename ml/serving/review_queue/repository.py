"""Accès SQL pur pour le domaine `review_queue`.

Cf. ARCHITECTURE.md §2.2.
"""
from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timedelta

from serving._coin_helpers import canonical_obverse_url
from shared.bank_classes import bank_class_ids, bank_class_ids_for_many
from shared.dino_scope import build_dino_scope, suggestions_join_sql
from shared.verdict_scope import (
    SUGGESTIONS_ANCHORS_KIND,
    SUGGESTIONS_ENCODER_VERSION,
    VERDICT_ANCHORS_KIND,
    VERDICT_ENCODER_VERSION,
)

from .models import (
    LotListItem,
    RejectedCrop,
    ReviewBbox,
    ReviewCandidate,
    ReviewItem,
    ReviewStats,
    TextSignalsResponse,
)


# ─── Constantes ─────────────────────────────────────────────────────────────

_RESTORED_NOTE = "restored"
NOT_RESTORED_SQL = (
    f"(rq.decision_notes IS NULL OR rq.decision_notes != '{_RESTORED_NOTE}')"
)
VALID_KINDS = ("single", "lot", "all")
VALID_LANES = ("manual", "auto_accept")

# listing_key extraction — eBay : `ebay_<itemId>` via raw_payload_json.
# Pour les autres sources, fallback à `source_ref`.
LISTING_KEY_SQL = """
CASE
  WHEN si.source = 'ebay'
   AND json_extract(si.raw_payload_json, '$.ebay_item_id') IS NOT NULL
    THEN 'ebay_' || json_extract(si.raw_payload_json, '$.ebay_item_id')
  ELSE si.source_ref
END
"""


# ─── Exceptions ─────────────────────────────────────────────────────────────


class ReviewItemNotFound(Exception):
    pass


class LotNotFound(Exception):
    pass


class TextSignalsNotFound(Exception):
    pass


class CohortNotFound(Exception):
    pass


# ─── Helpers candidates / row → item ────────────────────────────────────────


def _build_target_candidate(
    row: sqlite3.Row,
    target_eurio_id: str | None,
    conn: sqlite3.Connection | None = None,
) -> ReviewCandidate | None:
    if not target_eurio_id or "t_eurio_id" not in row.keys() or not row["t_eurio_id"]:
        return None
    label_bits = [
        row["t_country_name"],
        str(row["t_year"]) if row["t_year"] else None,
        row["t_theme"],
    ]
    denom = (
        f"{float(row['t_face_value']):.2f} EUR"
        if row["t_face_value"] is not None else ""
    )
    # Vignette : l'URL du référentiel (`coin_canonical_images`) D'ABORD.
    #
    # `/images/<numista_id>/source` est un endpoint LEGACY qui sert le layout
    # `ml/datasets/<nid>/`, absent des machines migrées — et surtout absent du
    # VPS, qui est justement celui qui sert cette file au front (la queue est
    # lue via `eurioApi`, pas via l'API locale). Le front préfixe l'URL relative
    # avec l'adresse du ML local, et on obtient une image cassée pour une pièce
    # dont la photo existe pourtant en base : mesuré le 2026-08-19 sur cy-2008
    # et cy-2026, et c'est ce qui a fait croire à des « pièces sans photo
    # canonique ». 100 % des lignes `role='obverse'` portent une `url`.
    thumb = (
        (canonical_obverse_url(conn, row["t_eurio_id"]) if conn is not None else None)
        or (f"/images/{int(row['t_numista_id'])}/source" if row["t_numista_id"] else "")
    )
    return ReviewCandidate(
        eurio_id=row["t_eurio_id"],
        score=1.0,
        label=" · ".join([b for b in label_bits if b]) or row["t_eurio_id"],
        country=row["t_country"] or "",
        denomination=denom,
        year=row["t_year"],
        canonical_thumb_url=thumb,
    )


def _build_dino_top1_candidate(
    conn: sqlite3.Connection, eurio_id: str | None, sim: float | None,
) -> ReviewCandidate | None:
    if not eurio_id or sim is None:
        return None
    row = conn.execute(
        """
        SELECT eurio_id, country, country_name, year, theme,
               face_value, numista_id
          FROM coins WHERE eurio_id = ?
        """,
        (eurio_id,),
    ).fetchone()
    if row is None:
        return None
    label_bits = [
        row["country_name"],
        str(row["year"]) if row["year"] else None,
        row["theme"],
    ]
    denom = (
        f"{float(row['face_value']):.2f} EUR"
        if row["face_value"] is not None else ""
    )
    # Même raison que dans `_build_target_candidate` : le référentiel d'abord,
    # l'endpoint legacy en dernier recours.
    thumb = (
        canonical_obverse_url(conn, row["eurio_id"])
        or (f"/images/{int(row['numista_id'])}/source" if row["numista_id"] else "")
    )
    return ReviewCandidate(
        eurio_id=row["eurio_id"],
        score=float(sim),
        label=" · ".join([b for b in label_bits if b]) or row["eurio_id"],
        country=row["country"] or "",
        denomination=denom,
        year=row["year"],
        canonical_thumb_url=thumb,
    )


def _fetch_group_candidates(
    conn: sqlite3.Connection, pairs: set[tuple[str, int]],
) -> dict[tuple[str, int], list[ReviewCandidate]]:
    out: dict[tuple[str, int], list[ReviewCandidate]] = {}
    for country, year in pairs:
        rows = conn.execute(
            """
            SELECT eurio_id, country, country_name, year, theme,
                   face_value, numista_id
              FROM coins
             WHERE country = ? AND year = ?
               AND face_value = 2.0 AND is_commemorative = 1
             ORDER BY theme
            """,
            (country, year),
        ).fetchall()
        cands: list[ReviewCandidate] = []
        for r in rows:
            label_bits = [
                r["country_name"],
                str(r["year"]) if r["year"] else None,
                r["theme"],
            ]
            cands.append(ReviewCandidate(
                eurio_id=r["eurio_id"], score=0.0,
                label=" · ".join([b for b in label_bits if b]) or r["eurio_id"],
                country=r["country"] or "",
                denomination=(
                    f"{float(r['face_value']):.2f} EUR"
                    if r["face_value"] is not None else ""
                ),
                year=r["year"],
                canonical_thumb_url=(
                    f"/images/{int(r['numista_id'])}/source"
                    if r["numista_id"] else ""
                ),
            ))
        out[(country, year)] = cands
    return out


def _fetch_standard_candidates(
    conn: sqlite3.Connection, countries: set[str], denom: float = 2.0,
) -> dict[str, list[ReviewCandidate]]:
    out: dict[str, list[ReviewCandidate]] = {}
    for country in countries:
        rows = conn.execute(
            """
            SELECT c.eurio_id, c.country, c.country_name, c.year, c.theme,
                   c.face_value, c.numista_id,
                   COALESCE(c.design_group_id, c.eurio_id) AS class_id,
                   dg.designation AS dg_designation
              FROM coins c
              LEFT JOIN design_groups dg ON dg.id = c.design_group_id
             WHERE c.face_value = ? AND c.country = ?
               AND c.is_commemorative = 0 AND c.canonical_eurio_id IS NULL
             ORDER BY c.year, c.eurio_id
            """,
            (denom, country),
        ).fetchall()
        groups: dict[str, sqlite3.Row] = {}
        for r in rows:
            groups.setdefault(r["class_id"], r)
        cands: list[ReviewCandidate] = []
        for r in groups.values():
            label = r["dg_designation"] or " · ".join(
                b for b in [
                    r["country_name"],
                    str(r["year"]) if r["year"] else None,
                    r["theme"],
                ] if b
            ) or r["eurio_id"]
            cands.append(ReviewCandidate(
                eurio_id=r["eurio_id"], score=0.0, label=label,
                country=r["country"] or "",
                denomination=(
                    f"{float(r['face_value']):.2f} EUR"
                    if r["face_value"] is not None else ""
                ),
                year=r["year"],
                canonical_thumb_url=canonical_obverse_url(conn, r["eurio_id"]) or (
                    f"/images/{int(r['numista_id'])}/source"
                    if r["numista_id"] else ""
                ),
            ))
        cands.sort(key=lambda c: (c.year or 0))
        out[country] = cands
    return out


def _row_to_item(
    row: sqlite3.Row,
    group_map: dict[tuple[str, int], list[ReviewCandidate]] | None,
    conn: sqlite3.Connection,
    std_map: dict[str, list[ReviewCandidate]] | None,
) -> ReviewItem:
    bbox: ReviewBbox | None = None
    if row["bbox_json"]:
        try:
            d = json.loads(row["bbox_json"])
            bbox = ReviewBbox(x=d.get("x", 0), y=d.get("y", 0),
                              w=d.get("w", 0), h=d.get("h", 0))
        except (json.JSONDecodeError, TypeError):
            bbox = None

    candidates: list[ReviewCandidate] = []
    if row["candidate_eurio_ids_json"]:
        try:
            raw = json.loads(row["candidate_eurio_ids_json"])
            for c in raw if isinstance(raw, list) else []:
                if not isinstance(c, dict) or "eurio_id" not in c:
                    continue
                thumb = c.get("canonical_thumb_url") or ""
                if not thumb:
                    thumb = canonical_obverse_url(conn, c["eurio_id"]) or ""
                candidates.append(ReviewCandidate(
                    eurio_id=c["eurio_id"],
                    score=float(c.get("score", 0)),
                    label=c.get("label", c["eurio_id"]),
                    country=c.get("country", ""),
                    denomination=c.get("denomination", ""),
                    year=c.get("year"),
                    canonical_thumb_url=thumb,
                ))
        except json.JSONDecodeError:
            pass

    target_eurio_id: str | None = (
        row["target_eurio_id"] if "target_eurio_id" in row.keys() else None
    )
    target_candidate = _build_target_candidate(row, target_eurio_id, conn)

    cols = row.keys()

    def _opt(name: str):
        return row[name] if name in cols else None

    group_candidates: list[ReviewCandidate] = []
    if target_candidate is None and group_map is not None:
        gc_country = _opt("listing_country")
        gc_year = _opt("listing_year")
        if gc_country and gc_year is not None:
            group_candidates = group_map.get((gc_country, gc_year), [])

    standard_candidates: list[ReviewCandidate] = []
    if std_map is not None:
        sc_country = _opt("listing_country")
        if sc_country and _opt("listing_year") is None:
            standard_candidates = std_map.get(sc_country, [])

    dino_eurio_id = _opt("dino_top1_country_eurio_id") or _opt("dino_top1_eurio_id")
    dino_sim = (
        _opt("dino_top1_country_sim") if _opt("dino_top1_country_eurio_id")
        else _opt("dino_top1_sim")
    )
    dino_top1 = _build_dino_top1_candidate(conn, dino_eurio_id, dino_sim)

    return ReviewItem(
        id=row["id"],
        crop_url=f"/sources/{row['source']}/assets/{row['image_asset_id']}/file",
        bbox=bbox,
        source=row["source"],
        source_ref=row["source_ref"],
        listing_title=row["listing_title"],
        listing_url=row["source_url"],
        listing_price=row["listing_price"],
        listing_kind=_opt("listing_kind"),
        listing_kind_confidence=_opt("listing_kind_confidence"),
        condition=_opt("condition_normalized"),
        condition_confidence=_opt("condition_confidence"),
        listing_origin_date=_opt("listing_origin_date"),
        sold_qty=_opt("sold_qty"),
        candidates=candidates,
        face_detected=row["face"],
        priority=row["priority"],
        is_multi_coin_lot=False,
        quality_score=row["quality_score"] or 0.0,
        enqueued_at=row["enqueued_at"],
        target_eurio_id=target_eurio_id,
        target_candidate=target_candidate,
        group_candidates=group_candidates,
        standard_candidates=standard_candidates,
        dino_top1=dino_top1,
        sugg_top1_eurio_id=_opt("sugg_top1_eurio_id"),
        sugg_top1_sim=_opt("sugg_top1_sim"),
        sugg_spread=_opt("sugg_spread"),
    )


# ─── Cohort helper ──────────────────────────────────────────────────────────


def _cohort_eurio_ids(
    conn: sqlite3.Connection, cohort_id: str | None,
) -> tuple[list[str], bool]:
    """Renvoie (eurio_ids, is_empty_or_missing).

    is_empty_or_missing=True signifie qu'on doit court-circuiter vers une
    réponse vide (cohort introuvable OU cohort sans coin).

    La table source est `experiment_cohorts.eurio_ids_json` (CSV JSON).
    `cohort_jobs` est une autre table (jobs de scrape par cohorte).
    """
    if not cohort_id:
        return [], False
    row = conn.execute(
        "SELECT eurio_ids_json FROM experiment_cohorts WHERE id = ?",
        (cohort_id,),
    ).fetchone()
    if row is None:
        return [], True
    try:
        eids = json.loads(row["eurio_ids_json"] or "[]")
    except (TypeError, json.JSONDecodeError):
        eids = []
    return list(eids), len(eids) == 0


# ─── /review-queue (list) ───────────────────────────────────────────────────


_LIST_SELECT_SQL = f"""
SELECT rq.id, rq.image_asset_id, rq.priority, rq.enqueued_at,
       rq.candidate_eurio_ids_json AS rq_candidates,
       a.bbox_json, a.candidate_eurio_ids_json, a.face, a.quality_score,
       s.source, s.source_ref, s.listing_title, s.source_url,
       s.listing_price, s.target_eurio_id,
       s.listing_country, s.listing_year,
       s.listing_origin_date, s.sold_qty,
       lts.listing_kind, lts.listing_kind_confidence,
       lts.condition_normalized, lts.condition_confidence,
       t.eurio_id     AS t_eurio_id,
       t.country      AS t_country,
       t.country_name AS t_country_name,
       t.year         AS t_year,
       t.theme        AS t_theme,
       t.face_value   AS t_face_value,
       t.numista_id   AS t_numista_id,
       p.top1_country_eurio_id AS dino_top1_country_eurio_id,
       p.top1_country_sim      AS dino_top1_country_sim,
       p.top1_eurio_id         AS dino_top1_eurio_id,
       p.top1_sim              AS dino_top1_sim,
       ps.top1_eurio_id        AS sugg_top1_eurio_id,
       ps.top1_sim             AS sugg_top1_sim,
       ps.spread               AS sugg_spread
  FROM review_queue rq
  JOIN image_assets a ON a.id = rq.image_asset_id
  JOIN source_images s ON s.id = a.source_image_id
  LEFT JOIN listing_text_signals lts ON lts.source_image_id = s.id
  LEFT JOIN coins t   ON t.eurio_id = s.target_eurio_id
  LEFT JOIN image_asset_dino_predictions p
         ON p.asset_id = a.id
        AND p.encoder_version = '{VERDICT_ENCODER_VERSION}'
        AND p.anchors_kind = '{VERDICT_ANCHORS_KIND}'
  -- Seconde jointure, dédiée au TRI et au FILTRE — jamais au verdict.
  -- La banque du verdict ne contient aucune pièce courante : trier dessus ne
  -- trierait sur rien dès qu'on travaille un standard. `ps` lit la banque des
  -- suggestions, la seule qui les couvre. Les deux jointures pointeront sur la
  -- même ligne le jour où le verdict basculera — sans fan-out, la PK
  -- (asset_id, encoder_version, anchors_kind) garantit une ligne au plus.
  LEFT JOIN image_asset_dino_predictions ps
         ON ps.asset_id = a.id
        AND ps.encoder_version = '{SUGGESTIONS_ENCODER_VERSION}'
        AND ps.anchors_kind = '{SUGGESTIONS_ANCHORS_KIND}'
"""


def list_queue(
    conn: sqlite3.Connection,
    *,
    status: str,
    limit: int,
    order: str,
    kind: str,
    lane: str | None,
    cohort_id: str | None,
    eurio_id: str | None,
    review_ids: list[str] | None,
    dino_min_spread: float | None = None,
    dino_top1_only: bool = False,
    dino_class: str | None = None,
    dino_rank: int = 1,
) -> list[ReviewItem]:
    # `dino` : d'abord ce que le modèle rattache à LA CLASSE TRAVAILLÉE, puis
    # du plus net au plus flou.
    #
    # Les deux critères comptent, et dans cet ordre. Trier par le seul spread
    # remonterait ce dont le modèle est le plus sûr — y compris quand il est
    # sûr que ce n'est PAS la classe : mesuré, la file « Philippe » ouvrait sur
    # un Spa-Francorchamps 2025 à 0,28 de spread. Utile à savoir, mais ce n'est
    # pas ce qu'on est venu trancher.
    #
    # COALESCE(-1) plutôt que de laisser NULL : un crop jamais scoré finit en
    # queue, et l'écrire évite de dépendre de la place des NULL dans le tri
    # SQLite (qui change entre ASC et DESC).
    # ⚠️ La banque n'indexe PAS une pièce courante sous son propre identifiant
    # mais sous celui du plus ancien millésime de son ère. Traduire est
    # obligatoire : sans ça, tri comme filtre porteraient sur un identifiant
    # que la banque ne connaît pas, et renverraient un résultat vide ou non
    # trié — parfaitement plausible, donc invisible. Cf. shared/bank_classes.
    #
    # `dino_class` renverse la définition du périmètre : la file n'est plus
    # « ce que le scrape visait » mais « ce que la banque reconnaît ». Il PREND
    # LA PLACE du scope par cible (eurio_id / cohort_id) au lieu de s'y ajouter
    # — les combiner rendrait les lots inatteignables, qui sont précisément le
    # gisement qu'on vient chercher. Cf. shared/dino_scope.
    scope = build_dino_scope(
        conn, dino_class=dino_class, rank=dino_rank,
        min_spread=dino_min_spread,
    )

    wanted_classes: list[str] = []
    if order == "dino" or dino_top1_only:
        if dino_class:
            wanted_classes = list(scope.class_ids)
        elif eurio_id:
            wanted_classes = bank_class_ids(conn, eurio_id)
        elif cohort_id:
            _eids, _ = _cohort_eurio_ids(conn, cohort_id)
            wanted_classes = bank_class_ids_for_many(conn, _eids)

    order_args: list[object] = []
    if order == "dino":
        bits = []
        if wanted_classes:
            ph = ",".join("?" * len(wanted_classes))
            bits.append(f"(ps.top1_eurio_id IN ({ph})) DESC")
            order_args.extend(wanted_classes)
        bits.append("COALESCE(ps.spread, -1.0) DESC")
        bits.append("rq.priority ASC, rq.enqueued_at ASC")
        order_clause = ", ".join(bits)
    else:
        order_clause = (
            "rq.priority ASC, rq.enqueued_at ASC" if order == "priority"
            else "rq.enqueued_at ASC"
        )
    where = "rq.status = ?"
    args: list[object] = [status]
    if kind != "all":
        where += " AND rq.kind = ?"
        args.append(kind)
    if lane is not None:
        if lane == "manual":
            where += " AND (rq.lane = 'manual' OR rq.lane IS NULL)"
        else:
            where += " AND rq.lane = ?"
            args.append(lane)

    if review_ids:
        where += f" AND rq.id IN ({','.join('?' * len(review_ids))})"
        args.extend(review_ids)
    elif dino_class:
        pass  # le périmètre est la prédiction (appliqué plus bas), pas la cible
    elif eurio_id:
        std_coin = conn.execute(
            "SELECT country, face_value FROM coins "
            "WHERE eurio_id = ? AND is_commemorative = 0",
            (eurio_id,),
        ).fetchone()
        if std_coin and std_coin["country"]:
            where += (
                " AND s.source = 'ebay' AND s.listing_country = ? "
                "AND s.listing_year IS NULL "
                "AND rq.kind = 'single' "
                "AND (rq.lane = 'manual' OR rq.lane IS NULL)"
            )
            args.append(std_coin["country"])
        else:
            where += " AND s.target_eurio_id = ?"
            args.append(eurio_id)
    elif cohort_id:
        eids, empty = _cohort_eurio_ids(conn, cohort_id)
        if not eids:
            if cohort_id and empty:
                raise CohortNotFound(cohort_id)
            return []
        where += f" AND s.target_eurio_id IN ({','.join('?' * len(eids))})"
        args.extend(eids)

    # ── Filtres DINO (banque des suggestions, jamais celle du verdict) ──────
    # La marge et l'appartenance à la classe viennent toutes deux du scope
    # partagé : `dino_min_spread` y est lu en COALESCE(country_spread, spread),
    # la grandeur que le verdict utilise réellement — un filtre sur la seule
    # colonne country écarte en silence des crops que le verdict évalue.
    if not scope.is_empty:
        where += f" AND {scope.sql}"
        args.extend(scope.args)
    if dino_top1_only and wanted_classes and not dino_class:
        ph = ",".join("?" * len(wanted_classes))
        where += f" AND ps.top1_eurio_id IN ({ph})"
        args.extend(wanted_classes)

    args.extend(order_args)
    args.append(limit)

    rows = conn.execute(
        f"{_LIST_SELECT_SQL} WHERE {where} ORDER BY {order_clause} LIMIT ?",
        args,
    ).fetchall()

    pairs: set[tuple[str, int]] = set()
    std_countries: set[str] = set()
    for r in rows:
        c, y = r["listing_country"], r["listing_year"]
        if c and y is None:
            std_countries.add(c)
        if r["target_eurio_id"]:
            continue
        if c and y is not None:
            pairs.add((c, y))
    group_map = _fetch_group_candidates(conn, pairs)
    std_map = _fetch_standard_candidates(conn, std_countries)

    return [_row_to_item(r, group_map, conn, std_map) for r in rows]


def get_review_item(conn: sqlite3.Connection, review_id: str) -> ReviewItem:
    rows = conn.execute(
        f"{_LIST_SELECT_SQL} WHERE rq.id = ?",
        (review_id,),
    ).fetchall()
    if not rows:
        raise ReviewItemNotFound(review_id)
    r = rows[0]
    pairs: set[tuple[str, int]] = set()
    std_countries: set[str] = set()
    c, y = r["listing_country"], r["listing_year"]
    if c and y is None:
        std_countries.add(c)
    if not r["target_eurio_id"] and c and y is not None:
        pairs.add((c, y))
    group_map = _fetch_group_candidates(conn, pairs)
    std_map = _fetch_standard_candidates(conn, std_countries)
    return _row_to_item(r, group_map, conn, std_map)


# ─── /review-queue/stats ────────────────────────────────────────────────────


def queue_stats(conn: sqlite3.Connection) -> ReviewStats:
    today = datetime.utcnow().strftime("%Y-%m-%d")
    week_start = (datetime.utcnow() - timedelta(days=7)).strftime("%Y-%m-%d")

    n_pending = conn.execute(
        "SELECT COUNT(*) AS c FROM review_queue WHERE status = 'open'"
    ).fetchone()["c"]
    n_done_today = conn.execute(
        "SELECT COUNT(*) AS c FROM review_queue WHERE status = 'done' AND decided_at >= ?",
        (today,),
    ).fetchone()["c"]
    n_done_week = conn.execute(
        "SELECT COUNT(*) AS c FROM review_queue WHERE status = 'done' AND decided_at >= ?",
        (week_start,),
    ).fetchone()["c"]

    deltas: list[float] = []
    for r in conn.execute(
        """
        SELECT enqueued_at, decided_at FROM review_queue
         WHERE status = 'done' AND decided_at IS NOT NULL
         ORDER BY decided_at DESC LIMIT 100
        """
    ).fetchall():
        try:
            t0 = datetime.fromisoformat(r["enqueued_at"].replace(" ", "T"))
            t1 = datetime.fromisoformat(r["decided_at"].replace(" ", "T"))
            deltas.append((t1 - t0).total_seconds())
        except Exception:  # noqa: BLE001
            continue
    deltas.sort()
    median = deltas[len(deltas) // 2] if deltas else 0.0

    return ReviewStats(
        n_pending=n_pending,
        n_done_today=n_done_today,
        n_done_this_week=n_done_week,
        median_seconds_per_decision=round(median, 1),
    )


# ─── /review-queue/rejected ─────────────────────────────────────────────────


def list_rejected(
    conn: sqlite3.Connection, *, cohort_id: str | None, limit: int,
) -> list[RejectedCrop]:
    eids, empty = _cohort_eurio_ids(conn, cohort_id)
    if cohort_id and empty:
        return []
    cohort_clause = ""
    cohort_args: list[object] = []
    if eids:
        cohort_clause = f" AND s.target_eurio_id IN ({','.join('?' * len(eids))})"
        cohort_args = list(eids)

    rows = conn.execute(
        f"""
        SELECT rq.id AS review_id, rq.image_asset_id, rq.decided_at,
               a.quality_reason,
               s.source, s.listing_title, s.target_eurio_id,
               t.country_name AS t_country_name, t.year AS t_year,
               t.theme AS t_theme
          FROM review_queue rq
          JOIN image_assets a ON a.id = rq.image_asset_id
          JOIN source_images s ON s.id = a.source_image_id
          LEFT JOIN coins t ON t.eurio_id = s.target_eurio_id
         WHERE a.resolution_status = 'rejected'{cohort_clause}
         ORDER BY rq.decided_at DESC
         LIMIT ?
        """,
        [*cohort_args, limit],
    ).fetchall()

    return [
        RejectedCrop(
            review_id=r["review_id"],
            image_asset_id=r["image_asset_id"],
            crop_url=f"/sources/{r['source']}/assets/{r['image_asset_id']}/file",
            listing_title=r["listing_title"],
            quality_reason=r["quality_reason"],
            decided_at=r["decided_at"],
            target_eurio_id=r["target_eurio_id"],
            target_label=_format_target_label(
                r["t_country_name"], r["t_year"], r["t_theme"],
            ),
        )
        for r in rows
    ]


def _format_target_label(country: str | None, year: int | None, theme: str | None) -> str | None:
    parts = [country, str(year) if year else None, theme]
    return " · ".join(b for b in parts if b) or None


# ─── /review-queue/lots ─────────────────────────────────────────────────────


def _lot_scope(
    conn: sqlite3.Connection,
    *,
    cohort_id: str | None,
    target_eurio_id: str | None,
    design_group: str | None,
    dino_class: str | None = None,
    dino_rank: int = 1,
    dino_min_spread: float | None = None,
) -> tuple[str, str, str, list[object]]:
    """Le périmètre d'une file de lots, en un seul endroit.

    Renvoie ``(join_sql, where_clause, match_expr, args)`` :

    - ``join_sql`` — la jointure vers la banque des suggestions, vide hors pêche
    - ``where_clause`` — le filtre par CIBLE de découverte (cohorte / classe /
      ère), vide en mode pêche
    - ``match_expr`` — l'expression 0/1 « ce crop est de la classe pêchée »,
      vide hors pêche
    - ``args`` — les paramètres, dans l'ordre ``where`` puis ``match``

    ⚠️ En mode pêche, le périmètre par prédiction **remplace** celui par cible
    et ne filtre PAS les crops : il sélectionne les LISTINGS qui en contiennent
    au moins un. On ouvre ensuite le lot entier — un coffret ne se tranche pas
    en regardant une pièce sur trente.

    Lève ``ValueError`` si ``design_group`` est inconnu (même contrat
    qu'auparavant : l'appelant renvoie une liste vide).
    """
    if dino_class:
        scope = build_dino_scope(
            conn, dino_class=dino_class, rank=dino_rank,
            min_spread=dino_min_spread,
        )
        if scope.is_empty:  # classe absente ET marge absente : rien à pêcher
            return "", "", "", []
        return (
            suggestions_join_sql("ps"),
            "",
            f"CASE WHEN {scope.sql} THEN 1 ELSE 0 END",
            list(scope.args),
        )

    if design_group:
        clause, args = _design_group_lot_scope(conn, design_group)  # peut lever
        return "", clause, "", args
    if target_eurio_id:
        return "", " AND si.target_eurio_id = ?", "", [target_eurio_id]

    eids, empty = _cohort_eurio_ids(conn, cohort_id)
    if cohort_id and empty:
        raise ValueError(f"cohort {cohort_id!r} sans pièce")
    if eids:
        ph = ",".join("?" * len(eids))
        return "", f" AND si.target_eurio_id IN ({ph})", "", list(eids)
    return "", "", "", []


def lot_order_sql(peche: bool) -> str:
    """L'ordre d'une file de lots — le MÊME pour la liste et pour la nav.

    Hors pêche : le plus vieux d'abord, l'ordre historique de la file.

    En pêche : **le plus fourni d'abord**. La règle « plus ancien d'abord »
    ouvrait la file italienne sur un coffret français de 36 crops dont UN seul
    appartenait à la classe — 35 vignettes à écarter à l'œil avant la première
    utile. Quand on pêche, on commence là où sont les poissons.
    """
    if peche:
        return "n_matching_crops DESC, oldest_enqueued_at ASC, listing_key ASC"
    return "oldest_enqueued_at ASC, listing_key ASC"


def _lot_keys_in_scope(
    conn: sqlite3.Connection,
    *,
    join_sql: str,
    where_clause: str,
    match_expr: str,
    args: list[object],
) -> list[str]:
    """Les listing_key du périmètre, dans son ordre — la même liste que sert
    ``list_lots``, sans pagination.

    C'est elle qui fait exister « lot suivant » : la nav prev/next DOIT lire
    exactement l'ordre que l'écran a annoncé, sinon « suivant » emmène ailleurs.
    D'où l'ordre partagé, cf. ``LOT_ORDER_SQL``.
    """
    # ⚠️ `match_expr` porte des `?` : il ne doit apparaître QU'UNE fois dans la
    # requête, sinon les paramètres ne correspondent plus. D'où l'alias réutilisé
    # dans HAVING (SQLite l'accepte) plutôt qu'une seconde copie de l'expression.
    having = " HAVING n_matching_crops > 0" if match_expr else ""
    rows = conn.execute(
        f"""
        SELECT {LISTING_KEY_SQL} AS listing_key,
               MIN(rq.enqueued_at) AS oldest_enqueued_at,
               SUM({match_expr or '0'}) AS n_matching_crops
          FROM review_queue rq
          JOIN image_assets a ON a.id = rq.image_asset_id
          JOIN source_images si ON si.id = a.source_image_id
          {join_sql}
         WHERE rq.kind = 'lot' AND rq.status = 'open'{where_clause}
         GROUP BY listing_key{having}
         ORDER BY {lot_order_sql(bool(match_expr))}
        """,
        args,
    ).fetchall()
    return [r["listing_key"] for r in rows]


def list_lots(
    conn: sqlite3.Connection,
    *,
    limit: int,
    offset: int,
    cohort_id: str | None,
    target_eurio_id: str | None,
    design_group: str | None,
    dino_class: str | None = None,
    dino_rank: int = 1,
    dino_min_spread: float | None = None,
) -> tuple[list[LotListItem], int]:
    """Liste les listings ayant ≥ 1 row review_queue.kind='lot' status='open'.

    Scope (priorité décroissante) :
    - `dino_class` → les listings qui contiennent ≥ 1 crop que la banque
      rattache à cette classe, quelle que soit la cible du scrape (pêche)
    - `design_group` → membres + pool ambigu du pays (cf. _design_group_lot_scope)
    - `target_eurio_id` → une classe précise
    - `cohort_id` → tous les lots des coins de la cohort
    """
    try:
        join_sql, where_clause, match_expr, scope_args = _lot_scope(
            conn, cohort_id=cohort_id, target_eurio_id=target_eurio_id,
            design_group=design_group, dino_class=dino_class,
            dino_rank=dino_rank, dino_min_spread=dino_min_spread,
        )
    except ValueError:
        return [], 0

    # `n_matching` sert deux fois : à filtrer les listings (HAVING) et à dire à
    # l'écran combien de pièces y sont à trouver. SQLite accepte l'alias d'un
    # agrégat dans HAVING — on ne duplique donc ni l'expression ni ses args.
    having = " HAVING n_matching_crops > 0" if match_expr else ""

    total = conn.execute(
        f"""
        SELECT COUNT(*) AS n FROM (
          SELECT {LISTING_KEY_SQL} AS listing_key,
                 SUM({match_expr or '0'}) AS n_matching_crops
            FROM review_queue rq
            JOIN image_assets a ON a.id = rq.image_asset_id
            JOIN source_images si ON si.id = a.source_image_id
            {join_sql}
           WHERE rq.kind = 'lot' AND rq.status = 'open'{where_clause}
           GROUP BY listing_key{having}
        )
        """,
        scope_args,
    ).fetchone()["n"]

    rows = conn.execute(
        f"""
        WITH grouped AS (
          SELECT {LISTING_KEY_SQL} AS listing_key,
                 si.source             AS source,
                 si.target_eurio_id    AS target_eurio_id,
                 MAX(si.listing_title) AS listing_title,
                 MAX(si.listing_price) AS listing_price,
                 MAX(si.listing_currency) AS listing_currency,
                 MAX(si.is_lot_suspected) AS is_lot_suspected,
                 COUNT(DISTINCT si.id)    AS n_images,
                 COUNT(DISTINCT a.id)     AS n_crops_in_review,
                 SUM({match_expr or '0'}) AS n_matching_crops,
                 MIN(rq.enqueued_at)      AS oldest_enqueued_at,
                 (SELECT si2.id FROM source_images si2
                   WHERE si2.source = si.source
                     AND {LISTING_KEY_SQL.replace('si.', 'si2.')} = {LISTING_KEY_SQL}
                   ORDER BY si2.fetched_at ASC LIMIT 1) AS thumb_si_id
            FROM review_queue rq
            JOIN image_assets a ON a.id = rq.image_asset_id
            JOIN source_images si ON si.id = a.source_image_id
            {join_sql}
           WHERE rq.kind = 'lot' AND rq.status = 'open'{where_clause}
           GROUP BY listing_key{having}
        )
        SELECT * FROM grouped
         ORDER BY {lot_order_sql(bool(match_expr))}
         LIMIT ? OFFSET ?
        """,
        (*scope_args, limit, offset),
    ).fetchall()

    items = [
        LotListItem(
            listing_key=r["listing_key"],
            source=r["source"],
            target_eurio_id=r["target_eurio_id"],
            listing_title=r["listing_title"],
            listing_price=r["listing_price"],
            listing_currency=r["listing_currency"] or "EUR",
            is_lot_suspected=bool(r["is_lot_suspected"]),
            n_images=r["n_images"],
            n_crops_in_review=r["n_crops_in_review"],
            oldest_enqueued_at=r["oldest_enqueued_at"],
            thumb_url=(
                f"/sources/{r['source']}/raws/{r['thumb_si_id']}/file"
                if r["thumb_si_id"] else None
            ),
            n_matching_crops=(
                int(r["n_matching_crops"]) if match_expr else None
            ),
        )
        for r in rows
    ]
    return items, int(total or 0)


ORPHAN_IDS_CAP = 500


def dino_candidates_summary(
    conn: sqlite3.Connection,
    *,
    dino_class: str,
    dino_rank: int = 1,
    dino_min_spread: float | None = None,
):
    """Combien de crops la banque rattache à cette classe, et où ils sont.

    Lecture pure. Les orphelins sont COMPTÉS, jamais enfilés : enfiler est une
    écriture, et une écriture qui se déclencherait au fil d'une lecture serait
    invisible à celui qui la provoque. Le front propose un bouton explicite qui
    appelle `POST /coins/assets/reflag-needs-review`.
    """
    from .models import DinoCandidatesSummary

    scope = build_dino_scope(
        conn, dino_class=dino_class, rank=dino_rank,
        min_spread=dino_min_spread,
    )
    if scope.is_empty:
        raise ValueError("dino_class requis")

    join_sql = suggestions_join_sql("ps")

    # La MEILLEURE MARGE par mode, à côté du compte. Un compte seul ment par
    # omission : la file ES « 4 à l'unité » était faite de quatre annonces
    # FRANÇAISES à 0,023 de marge au mieux — quatre skips pour rien, et
    # l'impression que l'écran est cassé. Le compte dit combien il y a à voir,
    # la marge dit si ça vaut le coup de regarder.
    # ⚠️ `status = 'open'` EXACTEMENT, comme `list_queue` : ce compteur annonce
    # ce que la file va servir, et deux populations légèrement différentes pour
    # un même fait, c'est un badge qui dit 4 au-dessus d'une file qui en sert 3.
    # (`in_progress` n'est écrit nulle part dans ce système — l'inclure était
    # une largeur morte qui ne pouvait que diverger. Il reste dans le test
    # d'orphelinat ci-dessous, où la largeur protège au lieu de nuire.)
    rows = conn.execute(
        f"""
        SELECT rq.kind AS kind, COUNT(*) AS n,
               MAX(COALESCE(ps.country_spread, ps.spread)) AS best
          FROM review_queue rq
          JOIN image_assets a ON a.id = rq.image_asset_id
          {join_sql}
         WHERE rq.status = 'open' AND {scope.sql}
         GROUP BY rq.kind
        """,
        scope.args,
    ).fetchall()
    by_kind = {r["kind"]: int(r["n"]) for r in rows}
    best_by_kind = {r["kind"]: r["best"] for r in rows}

    # Orphelin = needs_review, aucune ligne de review OUVERTE. Une ligne `done`
    # ne suffit pas à disqualifier : un crop peut avoir été tranché puis
    # re-flaggé. C'est bien l'absence de file OUVERTE qui le rend invisible.
    orphans = conn.execute(
        f"""
        SELECT a.id AS asset_id
          FROM image_assets a
          {join_sql}
         WHERE a.resolution_status = 'needs_review'
           AND a.training_eligible IS NOT 1
           AND NOT EXISTS (
                 SELECT 1 FROM review_queue rq2
                  WHERE rq2.image_asset_id = a.id
                    AND rq2.status IN ('open', 'in_progress')
               )
           AND {scope.sql}
         ORDER BY a.id
         LIMIT ?
        """,
        (*scope.args, ORPHAN_IDS_CAP + 1),
    ).fetchall()
    orphan_ids = [r["asset_id"] for r in orphans]
    n_orphans = len(orphan_ids)
    if n_orphans > ORPHAN_IDS_CAP:
        # On dit le vrai compte même quand on ne rend pas tous les ids : un
        # plafond silencieux se lit « on a tout couvert » alors qu'il tronque.
        n_orphans = conn.execute(
            f"""
            SELECT COUNT(*) AS n
              FROM image_assets a
              {join_sql}
             WHERE a.resolution_status = 'needs_review'
               AND a.training_eligible IS NOT 1
               AND NOT EXISTS (
                     SELECT 1 FROM review_queue rq2
                      WHERE rq2.image_asset_id = a.id
                        AND rq2.status IN ('open', 'in_progress')
                   )
               AND {scope.sql}
            """,
            scope.args,
        ).fetchone()["n"]
        orphan_ids = orphan_ids[:ORPHAN_IDS_CAP]

    # Déjà au train. Compté EXACTEMENT comme le préflight compte `n_ebay`
    # (`training/iteration_augmentations._ebay_training_sources`) : source eBay,
    # training_eligible, fichier présent, revers exclu — et sur le LABEL tranché
    # (`image_assets.eurio_id`), pas sur la cible de découverte, car un crop
    # réattribué suit son nouveau label.
    #
    # ⚠️ Reproduire ces quatre conditions n'est pas du zèle : un compteur qui
    # dirait 8 là où l'écran de cohorte dit 6 ferait douter des deux. La règle
    # du projet est qu'un même fait porte partout le même nombre.
    n_eligible = conn.execute(
        """
        SELECT COUNT(*) AS n
          FROM image_assets a
          JOIN source_images si ON si.id = a.source_image_id
          JOIN coins c ON c.eurio_id = a.eurio_id
         WHERE si.source = 'ebay'
           AND a.training_eligible = 1
           AND a.storage_status = 'present'
           AND (a.face IS NULL OR a.face != 'reverse')
           AND COALESCE(c.design_group_id, c.eurio_id) = ?
        """,
        (dino_class,),
    ).fetchone()["n"]

    return DinoCandidatesSummary(
        class_id=dino_class,
        bank_class_ids=list(scope.class_ids),
        rank=dino_rank,
        min_spread=dino_min_spread,
        n_open_single=by_kind.get("single", 0),
        n_open_lot=by_kind.get("lot", 0),
        best_spread_single=best_by_kind.get("single"),
        best_spread_lot=best_by_kind.get("lot"),
        n_orphans=int(n_orphans),
        orphan_asset_ids=orphan_ids,
        n_training_eligible=int(n_eligible),
    )


def _design_group_lot_scope(
    conn: sqlite3.Connection, design_group_id: str,
) -> tuple[str, list[object]]:
    """Port de `sources.ebay.standards.design_group_lot_scope`.

    Une ère regroupe :
    1. les listings assignés au prior ou aux membres (target_eurio_id IN …)
    2. le pool standard ambigu du pays (target NULL + listing_year NULL).
    """
    members = conn.execute(
        "SELECT eurio_id, country FROM coins "
        "WHERE COALESCE(design_group_id, eurio_id) = ?",
        (design_group_id,),
    ).fetchall()
    if not members:
        raise ValueError(f"design_group {design_group_id!r} introuvable")
    eurio_ids = [m["eurio_id"] for m in members]
    country = members[0]["country"]
    placeholders = ",".join("?" * len(eurio_ids))
    clause = (
        f" AND (si.target_eurio_id IN ({placeholders})"
        f" OR (si.target_eurio_id IS NULL AND si.source='ebay'"
        f" AND si.listing_country=? AND si.listing_year IS NULL))"
    )
    args: list[object] = [*eurio_ids, country]
    return clause, args


# ─── /review-queue/lots/{listing_key} ───────────────────────────────────────


def lot_siblings(
    conn: sqlite3.Connection,
    listing_key: str,
    *,
    cohort_id: str | None = None,
    target_eurio_id: str | None = None,
    design_group: str | None = None,
    dino_class: str | None = None,
    dino_rank: int = 1,
    dino_min_spread: float | None = None,
) -> tuple[str | None, str | None]:
    """Le lot précédent et le suivant **dans le périmètre courant**.

    Le listing courant peut être hors périmètre (on l'a ouvert par son URL, ou
    on vient d'en trancher tous les crops et il a quitté la file) : dans ce cas
    on ne devine pas — `(None, None)`, et l'écran le dit plutôt que de sauter
    quelque part au hasard.
    """
    try:
        join_sql, where_clause, match_expr, args = _lot_scope(
            conn, cohort_id=cohort_id, target_eurio_id=target_eurio_id,
            design_group=design_group, dino_class=dino_class,
            dino_rank=dino_rank, dino_min_spread=dino_min_spread,
        )
    except ValueError:
        return None, None
    keys = _lot_keys_in_scope(
        conn, join_sql=join_sql, where_clause=where_clause,
        match_expr=match_expr, args=args,
    )
    if listing_key not in keys:
        return None, None
    i = keys.index(listing_key)
    return (
        keys[i - 1] if i > 0 else None,
        keys[i + 1] if i + 1 < len(keys) else None,
    )


def get_lot_detail(
    conn: sqlite3.Connection, listing_key: str,
    *,
    cohort_id: str | None = None,
    target_eurio_id: str | None = None,
    design_group: str | None = None,
    dino_class: str | None = None,
    dino_rank: int = 1,
    dino_min_spread: float | None = None,
):
    """Lot detail — version sans re-détection live (image lean).

    Lit les détections persistées dans source_images.detections_json. NE PAS
    appeler `_compute_detections` (cv2 requis).

    Les paramètres de périmètre sont ceux de `list_lots`, et ils ne servent
    qu'à une chose : calculer `prev/next_listing_key` **dans la file qu'on est
    en train de dérouler**. Sans eux, « lot suivant » sortirait de la classe au
    premier clic ; sans eux du tout — c'était le cas ici jusqu'au 2026-08-20,
    les deux clés étant renvoyées `None` en dur — le chaînage n'existe pas et
    les flèches restent grises pour toujours.
    """
    from .models import LotCrop, LotDetail, LotDetection, LotImage

    si_rows = conn.execute(
        f"""
        SELECT si.id AS source_image_id,
               si.source, si.source_ref, si.listing_title, si.listing_price,
               si.listing_currency, si.is_lot_suspected, si.target_eurio_id,
               si.storage_path AS raw_storage_path,
               si.width AS raw_width, si.height AS raw_height,
               si.detections_json,
               si.fetched_at,
               {LISTING_KEY_SQL} AS computed_key
          FROM source_images si
         WHERE {LISTING_KEY_SQL} = ?
         ORDER BY si.fetched_at ASC
        """,
        (listing_key,),
    ).fetchall()
    if not si_rows:
        raise LotNotFound(listing_key)

    # PÊCHE — quels crops de CE listing la banque rattache-t-elle à la classe ?
    # Une seule requête pour tout le listing : sans ce marquage, un coffret de
    # 36 vignettes dont une seule appartient à la classe se trie entièrement à
    # l'œil, alors que la réponse est en base.
    # La marge de chaque crop, lue une fois pour tout le listing. Elle est
    # servie même hors pêche : c'est un signal d'affichage, pas un filtre.
    spread_by_asset: dict[str, float] = {
        r["asset_id"]: r["m"]
        for r in conn.execute(
            f"""
            SELECT a.id AS asset_id,
                   COALESCE(ps.country_spread, ps.spread) AS m
              FROM image_assets a
              JOIN source_images si ON si.id = a.source_image_id
              {suggestions_join_sql("ps")}
             WHERE {LISTING_KEY_SQL} = ?
            """,
            (listing_key,),
        ).fetchall()
        if r["m"] is not None
    }

    matching_assets: set[str] | None = None
    if dino_class:
        _scope = build_dino_scope(
            conn, dino_class=dino_class, rank=dino_rank,
            min_spread=dino_min_spread,
        )
        if not _scope.is_empty:
            _rows = conn.execute(
                f"""
                SELECT a.id AS asset_id
                  FROM image_assets a
                  JOIN source_images si ON si.id = a.source_image_id
                  {suggestions_join_sql("ps")}
                 WHERE {LISTING_KEY_SQL} = ? AND {_scope.sql}
                """,
                (listing_key, *_scope.args),
            ).fetchall()
            matching_assets = {r["asset_id"] for r in _rows}

    head = si_rows[0]
    source = head["source"]
    target_eurio_id = head["target_eurio_id"]
    listing_title = head["listing_title"]
    listing_price = head["listing_price"]
    listing_currency = head["listing_currency"] or "EUR"
    is_lot_suspected = bool(head["is_lot_suspected"])

    # target_candidate enrichi.
    target_candidate: ReviewCandidate | None = None
    if target_eurio_id:
        target_candidate = _build_dino_top1_candidate(conn, target_eurio_id, 1.0)

    # Pour chaque source_image, image_assets + reviews.
    images: list[LotImage] = []
    is_multi_crop_single = False
    for idx, si in enumerate(si_rows):
        si_id = si["source_image_id"]
        asset_rows = conn.execute(
            """
            SELECT a.id AS asset_id, a.crop_index, a.bbox_json, a.phash,
                   a.eurio_id, a.candidate_eurio_ids_json,
                   rq.id AS review_id
              FROM image_assets a
              LEFT JOIN review_queue rq ON rq.image_asset_id = a.id
             WHERE a.source_image_id = ?
             ORDER BY a.crop_index ASC
            """,
            (si_id,),
        ).fetchall()
        if len(asset_rows) > 1:
            is_multi_crop_single = is_multi_crop_single or (not is_lot_suspected)
        crops: list[LotCrop] = []
        for a in asset_rows:
            cands: list[ReviewCandidate] = []
            if a["candidate_eurio_ids_json"]:
                try:
                    raw = json.loads(a["candidate_eurio_ids_json"])
                    for c in raw if isinstance(raw, list) else []:
                        if not isinstance(c, dict) or "eurio_id" not in c:
                            continue
                        cands.append(ReviewCandidate(
                            eurio_id=c["eurio_id"],
                            score=float(c.get("score", 0)),
                            label=c.get("label", c["eurio_id"]),
                            country=c.get("country", ""),
                            denomination=c.get("denomination", ""),
                            year=c.get("year"),
                            canonical_thumb_url=(
                                c.get("canonical_thumb_url")
                                or canonical_obverse_url(conn, c["eurio_id"])
                                or ""
                            ),
                        ))
                except (json.JSONDecodeError, TypeError):
                    pass
            bbox = None
            if a["bbox_json"]:
                try:
                    bj = json.loads(a["bbox_json"])
                    bbox = ReviewBbox(
                        x=bj.get("x", 0), y=bj.get("y", 0),
                        w=bj.get("w", 0), h=bj.get("h", 0),
                    )
                except (json.JSONDecodeError, TypeError):
                    pass
            crops.append(LotCrop(
                dino_spread=spread_by_asset.get(a["asset_id"]),
                matches_dino_class=(
                    a["asset_id"] in matching_assets
                    if matching_assets is not None else None
                ),
                asset_id=a["asset_id"],
                review_id=a["review_id"] or "",
                crop_url=f"/sources/{source}/assets/{a['asset_id']}/file",
                crop_index=a["crop_index"],
                phash=a["phash"],
                current_eurio_id=a["eurio_id"],
                candidate_eurio_ids=cands,
                bbox=bbox,
            ))
        detections = _lot_detections_from_json(
            si["detections_json"],
            [c.crop_index for c in crops],
        )
        images.append(LotImage(
            source_image_id=si_id,
            image_index=idx,
            raw_url=f"/sources/{source}/raws/{si_id}/file",
            raw_width=si["raw_width"],
            raw_height=si["raw_height"],
            detections=detections,
            crops=crops,
        ))

    prev_key, next_key = lot_siblings(
        conn, listing_key,
        cohort_id=cohort_id, target_eurio_id=target_eurio_id,
        design_group=design_group, dino_class=dino_class,
        dino_rank=dino_rank, dino_min_spread=dino_min_spread,
    )

    return LotDetail(
        listing_key=listing_key,
        source=source,
        target_eurio_id=target_eurio_id,
        target_candidate=target_candidate,
        listing_title=listing_title,
        listing_price=listing_price,
        listing_currency=listing_currency,
        is_lot_suspected=is_lot_suspected,
        is_multi_crop_single=is_multi_crop_single,
        images=images,
        prev_listing_key=prev_key,
        next_listing_key=next_key,
    )


def _lot_detections_from_json(
    detections_json: str | None,
    crop_indices_in_db: list[int],
):
    from .models import LotDetection
    if not detections_json:
        return []
    try:
        raw = json.loads(detections_json)
    except (json.JSONDecodeError, TypeError):
        return []
    out: list[LotDetection] = []
    accepted_idx = 0
    for det in raw:
        crop_index: int | None = None
        if det.get("accepted"):
            if accepted_idx < len(crop_indices_in_db):
                crop_index = crop_indices_in_db[accepted_idx]
            accepted_idx += 1
        out.append(LotDetection(
            cx=det.get("cx", 0), cy=det.get("cy", 0), r=det.get("r", 0),
            accepted=bool(det.get("accepted")),
            reject_reason=det.get("reject_reason"),
            method=det.get("method", ""),
            crop_index=crop_index,
        ))
    return out


# ─── /review-queue/{id}/text-signals + /asset/{id}/text-signals ─────────────


def text_signals_by_source_image(
    conn: sqlite3.Connection, source_image_id: str,
) -> TextSignalsResponse:
    row = conn.execute(
        """
        SELECT lts.*, si.listing_title, si.target_eurio_id
          FROM listing_text_signals lts
          JOIN source_images si ON si.id = lts.source_image_id
         WHERE lts.source_image_id = ?
        """,
        (source_image_id,),
    ).fetchone()
    if row is None:
        raise TextSignalsNotFound(source_image_id)
    cols = row.keys()

    def _col(name: str) -> object:
        return row[name] if name in cols else None

    return TextSignalsResponse(
        source_image_id=row["source_image_id"],
        extractor_version=row["extractor_version"],
        listing_title=row["listing_title"],
        target_eurio_id=row["target_eurio_id"],
        countries=json.loads(row["countries_json"] or "[]"),
        years=json.loads(row["years_json"] or "[]"),
        denominations=json.loads(row["denominations_json"] or "[]"),
        theme_tokens=json.loads(row["theme_tokens_json"] or "[]"),
        rejected_markers=json.loads(row["rejected_markers_json"] or "[]"),
        is_lot=bool(row["is_lot"]),
        coverage=row["coverage"],
        matched=json.loads(row["matched_json"] or "{}"),
        vs_target_verdict=_col("vs_target_verdict"),  # type: ignore[arg-type]
        contradictions=json.loads(_col("contradictions_json") or "[]"),  # type: ignore[arg-type]
        convergences=json.loads(_col("convergences_json") or "[]"),  # type: ignore[arg-type]
        computed_at=row["computed_at"],
    )


def source_image_id_for_asset(conn: sqlite3.Connection, asset_id: str) -> str:
    row = conn.execute(
        "SELECT source_image_id FROM image_assets WHERE id = ?", (asset_id,),
    ).fetchone()
    if row is None:
        raise ReviewItemNotFound(asset_id)
    return row["source_image_id"]


def source_image_id_for_review(conn: sqlite3.Connection, review_id: str) -> str:
    row = conn.execute(
        """
        SELECT a.source_image_id
          FROM review_queue rq
          JOIN image_assets a ON a.id = rq.image_asset_id
         WHERE rq.id = ?
        """,
        (review_id,),
    ).fetchone()
    if row is None:
        raise ReviewItemNotFound(review_id)
    return row["source_image_id"]


# ─── Helpers pour /review-queue/triage-stats (SQL extraite du service) ─────


def count_with_filter(
    conn: sqlite3.Connection,
    *,
    status_clause: str,
    status_args: list[object],
    kind: str,
    kind_clause: bool,
    cohort_clause: str,
    cohort_args: list[object],
) -> int:
    """Compteur générique sur `review_queue` avec scope cohort optionnel.

    `status_clause` : ex. "rq.status = 'open'" ou "rq.decided_by = ?".
    `kind_clause` : si True, applique aussi le filtre kind (sauf si kind='all').
    `cohort_clause` / `cohort_args` : précomputés par `cohort_filter_clause()`.
    """
    kc = " AND rq.kind = ?" if (kind_clause and kind != "all") else ""
    ka = [kind] if (kind_clause and kind != "all") else []
    if cohort_clause:
        sql = (
            "SELECT COUNT(*) AS c FROM review_queue rq "
            "JOIN image_assets a ON a.id = rq.image_asset_id "
            "JOIN source_images si ON si.id = a.source_image_id "
            f"WHERE {status_clause}{kc}{cohort_clause}"
        )
        return conn.execute(sql, [*status_args, *ka, *cohort_args]).fetchone()["c"]
    sql = f"SELECT COUNT(*) AS c FROM review_queue rq WHERE {status_clause}{kc}"
    return conn.execute(sql, [*status_args, *ka]).fetchone()["c"]


def count_lot_open_in_lane(
    conn: sqlite3.Connection,
    *,
    lane_clause: str,
    lane_args: list[object],
    cohort_clause: str,
    cohort_args: list[object],
) -> int:
    """Lots open par lane — variante de count_with_filter spécialisée."""
    if cohort_clause:
        sql = (
            "SELECT COUNT(*) AS c FROM review_queue rq "
            "JOIN image_assets a ON a.id = rq.image_asset_id "
            "JOIN source_images si ON si.id = a.source_image_id "
            f"WHERE rq.status='open' AND rq.kind='lot' AND {lane_clause}{cohort_clause}"
        )
        return conn.execute(sql, [*lane_args, *cohort_args]).fetchone()["c"]
    sql = (
        "SELECT COUNT(*) AS c FROM review_queue rq "
        f"WHERE rq.status='open' AND rq.kind='lot' AND {lane_clause}"
    )
    return conn.execute(sql, lane_args).fetchone()["c"]


def count_lot_open_open(
    conn: sqlite3.Connection, *,
    cohort_clause: str, cohort_args: list[object],
) -> int:
    """`COUNT(*) WHERE rq.status='open' AND rq.kind='lot'` (scopable cohort)."""
    if cohort_clause:
        sql = (
            "SELECT COUNT(*) AS c FROM review_queue rq "
            "JOIN image_assets a ON a.id = rq.image_asset_id "
            "JOIN source_images si ON si.id = a.source_image_id "
            f"WHERE rq.status = 'open' AND rq.kind = 'lot'{cohort_clause}"
        )
        return conn.execute(sql, cohort_args).fetchone()["c"]
    return conn.execute(
        "SELECT COUNT(*) AS c FROM review_queue rq "
        "WHERE rq.status = 'open' AND rq.kind = 'lot'"
    ).fetchone()["c"]


def count_rejected(
    conn: sqlite3.Connection, *,
    cohort_clause: str, cohort_args: list[object],
) -> int:
    if cohort_clause:
        sql = (
            "SELECT COUNT(*) AS c FROM review_queue rq "
            "JOIN image_assets a ON a.id = rq.image_asset_id "
            "JOIN source_images si ON si.id = a.source_image_id "
            f"WHERE a.resolution_status = 'rejected'{cohort_clause}"
        )
        return conn.execute(sql, cohort_args).fetchone()["c"]
    return conn.execute(
        "SELECT COUNT(*) AS c FROM review_queue rq "
        "JOIN image_assets a ON a.id = rq.image_asset_id "
        "WHERE a.resolution_status = 'rejected'"
    ).fetchone()["c"]


def count_skipped(
    conn: sqlite3.Connection, *,
    cohort_clause: str, cohort_args: list[object],
) -> int:
    if cohort_clause:
        sql = (
            "SELECT COUNT(*) AS c FROM review_queue rq "
            "JOIN image_assets a ON a.id = rq.image_asset_id "
            "JOIN source_images si ON si.id = a.source_image_id "
            f"WHERE rq.status = 'open' AND rq.decision_notes = 'skipped'{cohort_clause}"
        )
        return conn.execute(sql, cohort_args).fetchone()["c"]
    return conn.execute(
        "SELECT COUNT(*) AS c FROM review_queue rq "
        "WHERE rq.status = 'open' AND rq.decision_notes = 'skipped'"
    ).fetchone()["c"]


def fetch_verdict_signal_rows(
    conn: sqlite3.Connection,
    *,
    kind: str,
    cohort_clause: str,
    cohort_args: list[object],
) -> list[sqlite3.Row]:
    """Scan complet de la queue open pour compute_auto_validate_verdict.

    Une seule requête puis pure-Python dans service.compute_auto_validate_verdict.
    """
    where = f"rq.status = 'open' AND {NOT_RESTORED_SQL}"
    args: list[object] = []
    if kind != "all":
        where += " AND rq.kind = ?"
        args.append(kind)
    return conn.execute(
        f"""
        SELECT a.face,
               si.target_eurio_id,
               p.top1_country_eurio_id, p.top1_country_sim, p.country_spread,
               p.top1_eurio_id, p.top1_sim, p.spread,
               lts.vs_target_verdict
          FROM review_queue rq
          JOIN image_assets a ON a.id = rq.image_asset_id
          JOIN source_images si ON si.id = a.source_image_id
          LEFT JOIN image_asset_dino_predictions p
                 ON p.asset_id = a.id
                AND p.encoder_version = '{VERDICT_ENCODER_VERSION}'
                AND p.anchors_kind = '{VERDICT_ANCHORS_KIND}'
          LEFT JOIN listing_text_signals lts
                 ON lts.source_image_id = si.id
         WHERE {where}{cohort_clause}
        """,
        [*args, *cohort_args],
    ).fetchall()


def cohort_filter_clause(
    conn: sqlite3.Connection, cohort_id: str | None,
) -> tuple[str, list[object], bool]:
    """Renvoie (clause SQL `AND si.target_eurio_id IN …`, args, is_empty).

    `is_empty=True` signifie cohort introuvable ou vide → caller court-circuite.
    """
    eids, empty = _cohort_eurio_ids(conn, cohort_id)
    if cohort_id and empty:
        return "", [], True
    if not eids:
        return "", [], False
    clause = f" AND si.target_eurio_id IN ({','.join('?' * len(eids))})"
    return clause, list(eids), False
