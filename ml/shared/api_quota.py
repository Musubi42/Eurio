"""Generic API quota tracker backed by SQLite.

One table — `api_call_log` — absorbs every (source, key_hash, window, period)
counter. Numista (monthly, multi-key) and eBay (daily, single-key) both write
here. The schema is created on first use and migrates the legacy
`numista_key_usage` table inline (a one-shot, idempotent rewrite — there is
no other migration system in the repo).

The `period` is computed at every call from `datetime.now(UTC)`, so resets
happen naturally at the boundary (1st of the month for `monthly`, midnight
UTC for `daily`).
"""

from __future__ import annotations

import sqlite3
import threading
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal

# Ancien emplacement, codé en dur : `ml/shared/state/eurio.db`. Il n'était ni le
# canonique ni la réplique — un troisième fichier que personne ne lisait à part le
# tracker, d'où le bug B1 (le compteur s'écrivait ici, les lecteurs interrogeaient
# le Store : le widget affichait 5000/5000 pendant qu'on brûlait 4733 appels, et le
# garde-fou `check_ebay_quota` laissait relancer un run sur un quota déjà épuisé).
# Conservé uniquement pour reprendre son contenu une fois — cf. `_import_legacy_rows`.
_LEGACY_DB = Path(__file__).parent / "state" / "eurio.db"


def default_db_path() -> Path:
    """DB du quota : la DB locale **inscriptible**, jamais le canonique.

    Le quota est de l'état d'observabilité par machine — il ne voyage pas vers le
    canonique, et ne le peut pas : sous Direction A, `eurio-api` est le writer
    unique et Mac/PC n'ont qu'une réplique **read-only**. Y écrire un compteur
    échouerait. `resolve_local_state_db()` est le resolver prévu pour exactement
    ce cas (honore `EURIO_LOCAL_STATE_DB`).

    Résolu à l'appel et non à l'import, pour qu'un test puisse pointer un tmpdir.
    """
    from store import resolve_local_state_db

    return resolve_local_state_db()


Window = Literal["monthly", "daily"]

_SCHEMA = """
CREATE TABLE IF NOT EXISTS api_call_log (
    source       TEXT NOT NULL,
    key_hash     TEXT NOT NULL DEFAULT '',
    window       TEXT NOT NULL,
    period       TEXT NOT NULL,
    calls        INTEGER NOT NULL DEFAULT 0,
    exhausted    INTEGER NOT NULL DEFAULT 0,
    last_call_at TEXT,
    PRIMARY KEY (source, key_hash, window, period)
)
"""

_schema_lock = threading.Lock()
_schema_ready: set[Path] = set()


def _import_legacy_rows(conn: sqlite3.Connection, db_path: Path) -> None:
    """Reprend une fois les compteurs de l'ancien fichier codé en dur (B1).

    Sans ça, la bascule perdrait le mois Numista en cours : les 8 clés
    repartiraient à zéro au milieu du mois et le KeyManager les surconsommerait
    jusqu'au 429. `INSERT OR IGNORE` — les lignes déjà présentes gagnent, donc
    rejouer l'import est un no-op. Le fichier legacy n'est **pas** supprimé :
    retirer de la donnée est une décision du PO, pas un effet de bord de schéma.
    """
    if not _LEGACY_DB.exists() or _LEGACY_DB.resolve() == db_path.resolve():
        return
    # Chemin NU, pas un nom de fichier URI (`file:…?mode=ro`) : la connexion
    # principale est ouverte sans `uri=True`, donc SQLITE_OPEN_URI est désactivé
    # et SQLite prendrait la chaîne au pied de la lettre — l'ATTACH échouerait
    # systématiquement, et l'`except` en ferait un no-op silencieux. On ne lit
    # que des SELECT sur cette base ; le read-only ne vaut pas un import mort.
    try:
        conn.execute("ATTACH DATABASE ? AS legacy", (str(_LEGACY_DB),))
    except sqlite3.Error:
        return  # legacy illisible/verrouillé : jamais bloquant pour le tracker
    try:
        has_table = conn.execute(
            "SELECT name FROM legacy.sqlite_master WHERE type='table' AND name='api_call_log'"
        ).fetchone()
        if has_table:
            conn.execute(
                "INSERT OR IGNORE INTO api_call_log "
                "(source, key_hash, window, period, calls, exhausted, last_call_at) "
                "SELECT source, key_hash, window, period, calls, exhausted, last_call_at "
                "FROM legacy.api_call_log"
            )
            # Obligatoire AVANT le DETACH : l'INSERT ouvre la transaction
            # implicite de sqlite3, et un DETACH sous transaction lève
            # « database legacy is locked ».
            conn.commit()
    except sqlite3.Error:
        pass
    finally:
        try:
            conn.execute("DETACH DATABASE legacy")
        except sqlite3.Error:
            # Un DETACH raté laisse une base attachée sur une connexion qu'on
            # referme juste après — sans conséquence. Le laisser remonter, en
            # revanche, ferait échouer `QuotaTracker.__init__`, donc TOUT appel
            # eBay et Numista.
            pass


def ensure_schema(db_path: Path | None = None) -> None:
    """Create api_call_log if missing and migrate numista_key_usage once.

    Safe to call repeatedly. Process-wide guard skips redundant work after the
    first successful call against a given DB path.
    """
    db_path = Path(db_path) if db_path is not None else default_db_path()
    with _schema_lock:
        if db_path in _schema_ready:
            return
        db_path.parent.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(db_path) as conn:
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute(_SCHEMA)
            legacy = conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name='numista_key_usage'"
            ).fetchone()
            if legacy:
                conn.execute(
                    """
                    INSERT OR IGNORE INTO api_call_log
                        (source, key_hash, window, period, calls, exhausted)
                    SELECT 'numista', key_hash, 'monthly', month, calls, exhausted
                    FROM numista_key_usage
                    """
                )
                conn.execute("DROP TABLE numista_key_usage")
            _import_legacy_rows(conn, db_path)
        _schema_ready.add(db_path)


@dataclass(frozen=True)
class QuotaStatus:
    source: str
    window: Window
    period: str
    limit: int
    calls: int
    remaining: int
    exhausted: bool
    last_call_at: str | None
    key_hash: str = ""


class QuotaTracker:
    """Atomic per-(source, window) counter persisted to api_call_log.

    Concurrency: the `INSERT … ON CONFLICT … DO UPDATE SET calls = calls + 1`
    statement is atomic at the SQLite level, so multi-process scrapes work
    without a process-level lock. The thread-lock here only avoids holding two
    transactions open in the same process.
    """

    def __init__(
        self,
        source: str,
        window: Window,
        limit: int,
        db_path: Path | None = None,
    ) -> None:
        if window not in ("monthly", "daily"):
            raise ValueError(f"Invalid window: {window!r}")
        self.source = source
        self.window: Window = window
        self.limit = limit
        self.db_path = Path(db_path) if db_path is not None else default_db_path()
        self._lock = threading.Lock()
        ensure_schema(self.db_path)

    def _period(self) -> str:
        now = datetime.now(timezone.utc)
        return now.strftime("%Y-%m") if self.window == "monthly" else now.strftime("%Y-%m-%d")

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def record(self, key_hash: str = "") -> None:
        period = self._period()
        now = datetime.now(timezone.utc).isoformat()
        with self._lock, self._connect() as conn:
            conn.execute(
                """
                INSERT INTO api_call_log
                    (source, key_hash, window, period, calls, last_call_at)
                VALUES (?, ?, ?, ?, 1, ?)
                ON CONFLICT (source, key_hash, window, period) DO UPDATE SET
                    calls = calls + 1,
                    last_call_at = excluded.last_call_at
                """,
                (self.source, key_hash, self.window, period, now),
            )

    def mark_exhausted(self, key_hash: str = "") -> None:
        period = self._period()
        with self._lock, self._connect() as conn:
            conn.execute(
                """
                INSERT INTO api_call_log
                    (source, key_hash, window, period, calls, exhausted)
                VALUES (?, ?, ?, ?, 0, 1)
                ON CONFLICT (source, key_hash, window, period) DO UPDATE SET
                    exhausted = 1
                """,
                (self.source, key_hash, self.window, period),
            )

    def status(self) -> list[QuotaStatus]:
        """One QuotaStatus per known key_hash for the current period."""
        period = self._period()
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT key_hash, calls, exhausted, last_call_at
                FROM api_call_log
                WHERE source = ? AND window = ? AND period = ?
                """,
                (self.source, self.window, period),
            ).fetchall()
        return [
            QuotaStatus(
                source=self.source,
                window=self.window,
                period=period,
                limit=self.limit,
                calls=int(r["calls"]),
                remaining=max(0, self.limit - int(r["calls"])),
                exhausted=bool(r["exhausted"]),
                last_call_at=r["last_call_at"],
                key_hash=r["key_hash"],
            )
            for r in rows
        ]

    def total(self) -> QuotaStatus:
        """Aggregate calls across keys for the current period.

        `limit` is reported as-is (caller decides whether it's a per-key cap or
        a global cap). For multi-key sources, callers typically present
        `limit × n_keys` as the headline budget.
        """
        rows = self.status()
        total_calls = sum(r.calls for r in rows)
        any_exhausted = any(r.exhausted for r in rows)
        last = max((r.last_call_at for r in rows if r.last_call_at), default=None)
        return QuotaStatus(
            source=self.source,
            window=self.window,
            period=self._period(),
            limit=self.limit,
            calls=total_calls,
            remaining=max(0, self.limit - total_calls),
            exhausted=any_exhausted,
            last_call_at=last,
            key_hash="",
        )
