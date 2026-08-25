"""ScanCorpusStore — store SQLite dédié du corpus de scan rejouable.

Spec : ``docs/work-in-progress/scan-quality/corpus-spec.md`` (§3 layout, §4 table,
§5 versioning). Store lab **PC-only, totalement isolé** : DB dédiée
``ml/state/scan_corpus.db`` (gitignored), jamais référencée par le pipeline
canonique/replica — il ne référence ni ``eurio.db``, ni ``eurio.replica.db``,
ni ``local_state_store()``. Le corpus est model-agnostic : images + labels,
aucune prédiction ni embedding.

Path par défaut : ``ml/state/scan_corpus.db``. Override via ``EURIO_SCAN_CORPUS_DB``.
Les frames vivent à côté, sous ``ml/state/scan_corpus/frames/`` (content-addressed,
``<capture_id>.raw.jpg`` + ``<capture_id>.crop.png``) ; les chemins stockés en
table sont relatifs à ``ml/state/scan_corpus/``.
"""
from __future__ import annotations

import hashlib
import os
import sqlite3
import threading
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Iterator, Sequence

_ML_DIR = Path(__file__).resolve().parent.parent
_DEFAULT_DB_PATH = _ML_DIR / "state" / "scan_corpus.db"
_DEFAULT_FRAMES_ROOT = _ML_DIR / "state" / "scan_corpus"

#: Vocabulaire ouvert (§Q2) — set validé, extensible sans migration.
KNOWN_CONDITIONS = {"bright", "dim", "tilt", "glare", "inhand", "worn", "dirty"}

_SCHEMA = """
CREATE TABLE IF NOT EXISTS scan_corpus (
  capture_id           TEXT PRIMARY KEY,          -- sha256(raw_bytes)[:16]
  eurio_id             TEXT NOT NULL,             -- label vérité (pièce attendue)
  condition            TEXT NOT NULL,             -- vocabulaire ouvert (§Q2)
  cohort_id            TEXT,
  source_iteration_id  TEXT,                      -- provenance uniquement, jamais scoré
  bundle_source        TEXT,
  raw_path             TEXT NOT NULL,             -- relatif à scan_corpus/
  crop_path            TEXT NOT NULL,
  raw_w                INTEGER,
  raw_h                INTEGER,
  crop_w               INTEGER,
  crop_h               INTEGER,
  device_model         TEXT,
  quality_json         TEXT,
  captured_at          TEXT NOT NULL,             -- ISO 8601
  notes                TEXT,
  -- FAIT sur le label, posé à l'import : la capture est juste à la CLASSE et
  -- fausse à la PIÈCE (le référentiel n'a pas la pièce montrée). Miroir de
  -- `remap_bench_golden_set.Mapping.class_level_only`. Ce n'est pas un avis.
  class_level_only     INTEGER NOT NULL DEFAULT 0,
  -- AVIS humain : cette photo est-elle exploitable comme juge ?
  -- NULL = pas encore jugée · 'keep' = gardée · 'exclude' = écartée.
  eval_decision        TEXT,
  eval_decision_by     TEXT,
  eval_decision_at     TEXT,
  eval_decision_reason TEXT
);
CREATE INDEX IF NOT EXISTS idx_scan_corpus_cohort
  ON scan_corpus(cohort_id, condition);
CREATE INDEX IF NOT EXISTS idx_scan_corpus_captured_at
  ON scan_corpus(captured_at);
CREATE INDEX IF NOT EXISTS idx_scan_corpus_eurio_id
  ON scan_corpus(eurio_id);

-- Journal des décisions humaines (remap ET garder/écarter). Une décision sans
-- trace ne se re-discute pas : qui, quand, ancien état → nouvel état.
CREATE TABLE IF NOT EXISTS scan_corpus_decisions (
  id          INTEGER PRIMARY KEY AUTOINCREMENT,
  capture_id  TEXT NOT NULL,
  kind        TEXT NOT NULL,            -- 'remap' | 'eval_decision'
  old_value   TEXT,
  new_value   TEXT,
  reason      TEXT,
  decided_by  TEXT,
  decided_at  TEXT NOT NULL             -- ISO 8601 UTC
);
CREATE INDEX IF NOT EXISTS idx_scan_corpus_decisions_capture
  ON scan_corpus_decisions(capture_id, id);
"""

#: Colonnes ajoutées après coup — migration idempotente pour les bases déjà
#: peuplées (les 451 captures du pull device existaient avant ces colonnes).
_ADDED_COLUMNS: tuple[tuple[str, str], ...] = (
    ("class_level_only", "INTEGER NOT NULL DEFAULT 0"),
    ("eval_decision", "TEXT"),
    ("eval_decision_by", "TEXT"),
    ("eval_decision_at", "TEXT"),
    ("eval_decision_reason", "TEXT"),
)

#: Valeurs admises pour ``eval_decision`` (``None`` = pas encore jugée).
EVAL_DECISIONS = ("keep", "exclude")


def _utc_now() -> str:
    from datetime import datetime, timezone

    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def capture_id_for(raw_bytes: bytes) -> str:
    """capture_id canonique = sha256 des bytes raw, tronqué à 16 hex (§3)."""
    return hashlib.sha256(raw_bytes).hexdigest()[:16]


def corpus_version(capture_ids: Sequence[str]) -> str:
    """Version de corpus = hash du manifeste trié (§5) : sha256(sorted ids)[:12]."""
    manifest = "\n".join(sorted(capture_ids))
    return hashlib.sha256(manifest.encode("utf-8")).hexdigest()[:12]


@dataclass
class ScanCapture:
    capture_id: str
    eurio_id: str
    condition: str
    captured_at: str
    raw_path: str
    crop_path: str
    cohort_id: str | None = None
    source_iteration_id: str | None = None
    bundle_source: str | None = None
    raw_w: int | None = None
    raw_h: int | None = None
    crop_w: int | None = None
    crop_h: int | None = None
    device_model: str | None = None
    quality_json: str | None = None
    notes: str | None = None
    #: FAIT posé à l'import (label juste à la classe, faux à la pièce).
    class_level_only: bool = False
    #: AVIS humain — ``None`` tant que personne n'a regardé la photo.
    eval_decision: str | None = None
    eval_decision_by: str | None = None
    eval_decision_at: str | None = None
    eval_decision_reason: str | None = None

    @staticmethod
    def from_row(row: sqlite3.Row) -> "ScanCapture":
        data = {k: row[k] for k in row.keys()}
        data["class_level_only"] = bool(data.get("class_level_only") or 0)
        return ScanCapture(**data)


class ScanCorpusStore:
    """Wrapper minimal (connexion par thread + write lock), pattern ReviewDB."""

    def __init__(
        self,
        db_path: Path | str | None = None,
        frames_root: Path | str | None = None,
    ) -> None:
        if db_path is None:
            db_path = os.environ.get("EURIO_SCAN_CORPUS_DB", str(_DEFAULT_DB_PATH))
        self._db_path = Path(db_path)
        if frames_root is None:
            env_root = os.environ.get("EURIO_SCAN_CORPUS_ROOT")
            frames_root = Path(env_root) if env_root else self._default_frames_root()
        self._frames_root = Path(frames_root)
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        self._write_lock = threading.Lock()
        self._local = threading.local()
        self._bootstrap()

    def _default_frames_root(self) -> Path:
        # DB custom (tests) → frames à côté de la DB ; DB par défaut → layout §3.
        if self._db_path == _DEFAULT_DB_PATH:
            return _DEFAULT_FRAMES_ROOT
        return self._db_path.parent / "scan_corpus"

    @property
    def db_path(self) -> Path:
        return self._db_path

    @property
    def frames_root(self) -> Path:
        """Racine ``scan_corpus/`` — les ``raw_path``/``crop_path`` y sont relatifs."""
        return self._frames_root

    @property
    def frames_dir(self) -> Path:
        return self._frames_root / "frames"

    def connection(self) -> sqlite3.Connection:
        conn = getattr(self._local, "conn", None)
        if conn is None:
            conn = sqlite3.connect(
                self._db_path,
                check_same_thread=False,
                isolation_level=None,
            )
            conn.row_factory = sqlite3.Row
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute("PRAGMA synchronous=NORMAL")
            conn.execute("PRAGMA busy_timeout=5000")
            self._local.conn = conn
        return conn

    def _bootstrap(self) -> None:
        with self._write_lock:
            conn = self.connection()
            conn.executescript(_SCHEMA)
            self._migrate(conn)

    @staticmethod
    def _migrate(conn: sqlite3.Connection) -> None:
        """ALTER TABLE idempotents — les bases déjà peuplées n'ont pas ces colonnes.

        SQLite n'a pas d'``ADD COLUMN IF NOT EXISTS`` ; on lit ``table_info``
        plutôt que d'avaler une exception, pour qu'une vraie erreur de schéma
        reste visible au lieu d'être absorbée.
        """
        present = {
            r["name"] for r in conn.execute("PRAGMA table_info(scan_corpus)")
        }
        for name, ddl in _ADDED_COLUMNS:
            if name not in present:
                conn.execute(f"ALTER TABLE scan_corpus ADD COLUMN {name} {ddl}")

    @contextmanager
    def writing(self) -> Iterator[sqlite3.Connection]:
        with self._write_lock:
            conn = self.connection()
            conn.execute("BEGIN IMMEDIATE")
            try:
                yield conn
                conn.execute("COMMIT")
            except Exception:
                conn.execute("ROLLBACK")
                raise

    # ------------------------------------------------------------------ writes

    def upsert_capture(self, capture: ScanCapture) -> bool:
        """Upsert idempotent par ``capture_id``. Retourne True si insert neuf.

        Append-only côté images (on ne réécrit jamais un fichier) ; les
        métadonnées (label, condition, notes…) sont re-labellisables via
        ce même upsert (§3 : re-labelliser = un UPDATE SQL).
        """
        with self.writing() as conn:
            existed = conn.execute(
                "SELECT 1 FROM scan_corpus WHERE capture_id = ?",
                (capture.capture_id,),
            ).fetchone()
            conn.execute(
                """
                INSERT INTO scan_corpus (
                  capture_id, eurio_id, condition, cohort_id, source_iteration_id,
                  bundle_source, raw_path, crop_path, raw_w, raw_h, crop_w, crop_h,
                  device_model, quality_json, captured_at, notes, class_level_only
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(capture_id) DO UPDATE SET
                  eurio_id            = excluded.eurio_id,
                  condition           = excluded.condition,
                  cohort_id           = excluded.cohort_id,
                  source_iteration_id = excluded.source_iteration_id,
                  bundle_source       = excluded.bundle_source,
                  raw_path            = excluded.raw_path,
                  crop_path           = excluded.crop_path,
                  raw_w               = excluded.raw_w,
                  raw_h               = excluded.raw_h,
                  crop_w              = excluded.crop_w,
                  crop_h              = excluded.crop_h,
                  device_model        = excluded.device_model,
                  quality_json        = excluded.quality_json,
                  captured_at         = excluded.captured_at,
                  notes               = excluded.notes,
                  class_level_only    = excluded.class_level_only
                  -- ⛔ eval_decision* n'est PAS touché : c'est un AVIS humain, et
                  -- un ré-import (idempotent par construction) ne doit pas
                  -- l'effacer en silence. Il ne bouge que par
                  -- ``set_eval_decision``.
                """,
                (
                    capture.capture_id,
                    capture.eurio_id,
                    capture.condition,
                    capture.cohort_id,
                    capture.source_iteration_id,
                    capture.bundle_source,
                    capture.raw_path,
                    capture.crop_path,
                    capture.raw_w,
                    capture.raw_h,
                    capture.crop_w,
                    capture.crop_h,
                    capture.device_model,
                    capture.quality_json,
                    capture.captured_at,
                    capture.notes,
                    1 if capture.class_level_only else 0,
                ),
            )
            return existed is None

    # ------------------------------------------------- décisions humaines

    def _journal(
        self,
        conn: sqlite3.Connection,
        capture_id: str,
        kind: str,
        old_value: str | None,
        new_value: str | None,
        reason: str | None,
        decided_by: str | None,
        decided_at: str,
    ) -> None:
        conn.execute(
            """INSERT INTO scan_corpus_decisions
                 (capture_id, kind, old_value, new_value, reason, decided_by, decided_at)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (capture_id, kind, old_value, new_value, reason, decided_by, decided_at),
        )

    def relabel_capture(
        self,
        capture_id: str,
        new_eurio_id: str,
        *,
        class_level_only: bool | None = None,
        reason: str | None = None,
        decided_by: str | None = None,
    ) -> ScanCapture:
        """Réattribue une capture à une autre pièce, et le **journalise**.

        Un remap qui n'écrirait que la nouvelle valeur serait irrattrapable : on
        ne saurait plus ce qui a été corrigé, ni par qui. L'ancien ``eurio_id``
        part dans ``scan_corpus_decisions`` (kind ``remap``).

        ⛔ Le garde-fou référentiel n'est PAS ici : ce store ne lit jamais
        ``eurio.db``. C'est l'appelant (route / script d'import) qui confronte
        l'``eurio_id`` au référentiel avant d'écrire.
        """
        at = _utc_now()
        with self.writing() as conn:
            row = conn.execute(
                "SELECT eurio_id, class_level_only FROM scan_corpus WHERE capture_id = ?",
                (capture_id,),
            ).fetchone()
            if row is None:
                raise KeyError(capture_id)
            old_eurio_id = row["eurio_id"]
            old_flag = bool(row["class_level_only"] or 0)
            flag = old_flag if class_level_only is None else bool(class_level_only)
            conn.execute(
                "UPDATE scan_corpus SET eurio_id = ?, class_level_only = ? "
                "WHERE capture_id = ?",
                (new_eurio_id, 1 if flag else 0, capture_id),
            )
            self._journal(
                conn, capture_id, "remap",
                f"{old_eurio_id} (class_level_only={old_flag})",
                f"{new_eurio_id} (class_level_only={flag})",
                reason, decided_by, at,
            )
            return ScanCapture.from_row(
                conn.execute(
                    "SELECT * FROM scan_corpus WHERE capture_id = ?", (capture_id,)
                ).fetchone()
            )

    def set_eval_decision(
        self,
        capture_id: str,
        decision: str | None,
        *,
        reason: str | None = None,
        decided_by: str | None = None,
    ) -> ScanCapture:
        """Garde / écarte une capture pour l'évaluation. ``None`` = re-ouvre l'avis.

        C'est un **avis**, distinct de ``class_level_only`` qui est un fait sur
        le label. Journalisé (kind ``eval_decision``).
        """
        if decision is not None and decision not in EVAL_DECISIONS:
            raise ValueError(
                f"eval_decision invalide: {decision!r} "
                f"(attendu {' | '.join(EVAL_DECISIONS)} ou None)"
            )
        at = _utc_now()
        with self.writing() as conn:
            row = conn.execute(
                "SELECT eval_decision FROM scan_corpus WHERE capture_id = ?",
                (capture_id,),
            ).fetchone()
            if row is None:
                raise KeyError(capture_id)
            conn.execute(
                """UPDATE scan_corpus
                     SET eval_decision = ?, eval_decision_by = ?,
                         eval_decision_at = ?, eval_decision_reason = ?
                   WHERE capture_id = ?""",
                (
                    decision,
                    decided_by if decision is not None else None,
                    at if decision is not None else None,
                    reason if decision is not None else None,
                    capture_id,
                ),
            )
            self._journal(
                conn, capture_id, "eval_decision",
                row["eval_decision"], decision, reason, decided_by, at,
            )
            return ScanCapture.from_row(
                conn.execute(
                    "SELECT * FROM scan_corpus WHERE capture_id = ?", (capture_id,)
                ).fetchone()
            )

    def list_decisions(self, capture_id: str) -> list[dict]:
        """Journal d'une capture, du plus ancien au plus récent."""
        rows = self.connection().execute(
            "SELECT * FROM scan_corpus_decisions WHERE capture_id = ? ORDER BY id",
            (capture_id,),
        ).fetchall()
        return [dict(r) for r in rows]

    # ------------------------------------------------------------------- reads

    def get_capture(self, capture_id: str) -> ScanCapture | None:
        row = self.connection().execute(
            "SELECT * FROM scan_corpus WHERE capture_id = ?", (capture_id,)
        ).fetchone()
        return ScanCapture.from_row(row) if row else None

    def list_captures(
        self,
        cohort_id: str | None = None,
        conditions: Sequence[str] | None = None,
        source_iteration_id: str | None = None,
        captured_before: str | None = None,
        bundle_sources: Sequence[str] | None = None,
        eurio_ids: Sequence[str] | None = None,
        exclude_rejected: bool = False,
    ) -> list[ScanCapture]:
        """Filtre du corpus (§5) — l'ensemble retourné, trié par capture_id,
        définit un snapshot : ``corpus_version([c.capture_id for c in ...])``.

        ``bundle_sources`` porte le **protocole de prise de vue** (ex.
        ``device_pull_20260429`` vs ``device_pull_20260601``). Sans lui, « noter
        les deux protocoles séparément » n'est pas exprimable : deux protocoles
        partagent des noms d'étape (``bright_plain``, ``bright_textured``), donc
        ``conditions`` ne les sépare pas. ⛔ Ne pas détourner
        ``source_iteration_id`` pour ça — cette colonne est de la provenance,
        elle n'est jamais scorée.

        ⚠️ ``bundle_source`` est de la **provenance**, plus un axe d'analyse : les
        451 captures device forment un seul pool d'évaluation (décision PO du
        2026-08-25 — « une photo de val pour une classe, c'est une photo »). Le
        découpage par protocole a servi une fois, dans ``LOT4-RESULTATS.md``,
        pour mesurer la fuite de centroïdes ; la fuite fermée, il ne décrit plus
        rien d'utile. Le filtre reste disponible, il n'est plus le cadre.

        ``exclude_rejected`` retire les captures qu'un humain a écartées
        (``eval_decision='exclude'``). Le juge (``scripts/replay_corpus.py``)
        s'en sert **par défaut** depuis le 2026-08-25.

        🔴 Ce prédicat vit ICI et nulle part ailleurs. Un appelant qui a besoin
        des deux ensembles (le juge : pour dire combien il a écarté) fait DEUX
        appels — un filtré, un non — et dérive la différence. Le ré-implémenter
        en Python côté appelant le ferait diverger le jour où
        ``eval_decision`` gagne une troisième valeur.

        ⚠️ Conséquence à ne jamais perdre de vue : l'ensemble noté devient
        dépendant d'une décision humaine **mutable**. C'est pourquoi
        ``corpus_version`` doit être calculée sur l'ensemble RÉELLEMENT noté,
        après exclusion — sinon deux runs noteraient des jeux différents sous
        la même version, et rien ne le signalerait.
        """
        clauses: list[str] = []
        params: list[object] = []
        if cohort_id is not None:
            clauses.append("cohort_id = ?")
            params.append(cohort_id)
        if conditions:
            placeholders = ", ".join("?" for _ in conditions)
            clauses.append(f"condition IN ({placeholders})")
            params.extend(conditions)
        if source_iteration_id is not None:
            clauses.append("source_iteration_id = ?")
            params.append(source_iteration_id)
        if captured_before is not None:
            clauses.append("captured_at < ?")
            params.append(captured_before)
        if bundle_sources:
            placeholders = ", ".join("?" for _ in bundle_sources)
            clauses.append(f"bundle_source IN ({placeholders})")
            params.extend(bundle_sources)
        if eurio_ids:
            placeholders = ", ".join("?" for _ in eurio_ids)
            clauses.append(f"eurio_id IN ({placeholders})")
            params.extend(eurio_ids)
        if exclude_rejected:
            clauses.append("(eval_decision IS NULL OR eval_decision <> 'exclude')")
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        rows = self.connection().execute(
            f"SELECT * FROM scan_corpus {where} ORDER BY capture_id", params
        ).fetchall()
        return [ScanCapture.from_row(r) for r in rows]

    def count(self) -> int:
        return int(
            self.connection().execute("SELECT COUNT(*) FROM scan_corpus").fetchone()[0]
        )
