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
  notes                TEXT
);
CREATE INDEX IF NOT EXISTS idx_scan_corpus_cohort
  ON scan_corpus(cohort_id, condition);
CREATE INDEX IF NOT EXISTS idx_scan_corpus_captured_at
  ON scan_corpus(captured_at);
"""


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

    @staticmethod
    def from_row(row: sqlite3.Row) -> "ScanCapture":
        return ScanCapture(**{k: row[k] for k in row.keys()})


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
            self.connection().executescript(_SCHEMA)

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
                  device_model, quality_json, captured_at, notes
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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
                  notes               = excluded.notes
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
                ),
            )
            return existed is None

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
    ) -> list[ScanCapture]:
        """Filtre du corpus (§5) — l'ensemble retourné, trié par capture_id,
        définit un snapshot : ``corpus_version([c.capture_id for c in ...])``."""
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
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        rows = self.connection().execute(
            f"SELECT * FROM scan_corpus {where} ORDER BY capture_id", params
        ).fetchall()
        return [ScanCapture.from_row(r) for r in rows]

    def count(self) -> int:
        return int(
            self.connection().execute("SELECT COUNT(*) FROM scan_corpus").fetchone()[0]
        )
