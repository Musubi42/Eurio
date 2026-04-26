"""Numista API key manager with monthly quota tracking.

Reads NUMISTA_API_KEY_1, NUMISTA_API_KEY_2, ... from environment (set via .envrc).
Tracks monthly call counts in the training SQLite DB (state/training.db).
Rotates to the next key automatically when one hits 429 or the 1800 soft limit.
"""

from __future__ import annotations

import hashlib
import os
import sqlite3
import threading
from datetime import datetime
from pathlib import Path

_MONTHLY_LIMIT = 1800
_DEFAULT_DB = Path(__file__).parent / "state" / "training.db"


def _key_hash(key: str) -> str:
    return hashlib.sha256(key.encode()).hexdigest()[:12]


def _current_month() -> str:
    return datetime.now().strftime("%Y-%m")


class KeyManager:
    """Pick the best available Numista key and track its quota."""

    def __init__(self, db_path: Path = _DEFAULT_DB) -> None:
        self._db_path = Path(db_path)
        self._lock = threading.Lock()
        self._keys = self._load_keys()
        if not self._keys:
            raise RuntimeError(
                "No Numista API keys found. "
                "Add NUMISTA_API_KEY_MUSUBI00 (and optionally MUSUBI01, ...) to .envrc"
            )
        self._ensure_table()

    # ── Key loading ──────────────────────────────────────────────────────────

    def _load_keys(self) -> list[tuple[str, str]]:
        """Return [(key_hash, key_value), ...] from env, in slot order.

        Scans NUMISTA_API_KEY_MUSUBI00, NUMISTA_API_KEY_MUSUBI01, ...
        Stops at the first missing slot.
        """
        keys = []
        i = 0
        while True:
            val = os.environ.get(f"NUMISTA_API_KEY_MUSUBI{i:02d}")
            if not val:
                break
            keys.append((_key_hash(val), val))
            i += 1
        return keys

    # ── SQLite ───────────────────────────────────────────────────────────────

    def _conn(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self._db_path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        return conn

    def _ensure_table(self) -> None:
        with self._conn() as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS numista_key_usage (
                    key_hash  TEXT NOT NULL,
                    month     TEXT NOT NULL,
                    calls     INTEGER NOT NULL DEFAULT 0,
                    exhausted INTEGER NOT NULL DEFAULT 0,
                    PRIMARY KEY (key_hash, month)
                )
            """)

    # ── Public API ───────────────────────────────────────────────────────────

    def pick(self) -> str:
        """Return the best available key for this month.

        Picks the key with fewest calls this month that is neither
        exhausted nor at the 1800 soft limit.
        Raises RuntimeError if all keys are at capacity.
        """
        month = _current_month()
        conn = self._conn()
        rows = {
            r["key_hash"]: dict(r)
            for r in conn.execute(
                "SELECT key_hash, calls, exhausted FROM numista_key_usage WHERE month = ?",
                (month,),
            ).fetchall()
        }
        conn.close()

        candidates: list[tuple[int, str, str]] = []
        for key_hash, key_value in self._keys:
            row = rows.get(key_hash)
            calls = row["calls"] if row else 0
            exhausted = bool(row["exhausted"]) if row else False
            if not exhausted and calls < _MONTHLY_LIMIT:
                candidates.append((calls, key_hash, key_value))

        if not candidates:
            raise RuntimeError(
                f"All Numista API keys are at or above the {_MONTHLY_LIMIT}/month soft limit "
                "or have received a 429. Add a new key or wait until next month."
            )

        candidates.sort()
        _, _, key_value = candidates[0]
        return key_value

    def record_call(self, key: str) -> None:
        """Increment the call count for the given key in the current month."""
        kh = _key_hash(key)
        month = _current_month()
        with self._lock:
            with self._conn() as conn:
                conn.execute(
                    """
                    INSERT INTO numista_key_usage (key_hash, month, calls)
                    VALUES (?, ?, 1)
                    ON CONFLICT (key_hash, month) DO UPDATE SET calls = calls + 1
                    """,
                    (kh, month),
                )

    def mark_exhausted(self, key: str) -> None:
        """Mark a key as exhausted (received 429) for the current month."""
        kh = _key_hash(key)
        month = _current_month()
        with self._lock:
            with self._conn() as conn:
                conn.execute(
                    """
                    INSERT INTO numista_key_usage (key_hash, month, exhausted)
                    VALUES (?, ?, 1)
                    ON CONFLICT (key_hash, month) DO UPDATE SET exhausted = 1
                    """,
                    (kh, month),
                )

    def call(self, fn, *args, **kwargs):
        """Call fn(key, *args, **kwargs) with quota tracking and 429 rotation.

        On 429 the current key is marked exhausted and the next available key
        is tried automatically. Raises RuntimeError when all keys are spent.
        """
        while True:
            key = self.pick()
            try:
                result = fn(key, *args, **kwargs)
                self.record_call(key)
                return result
            except Exception as e:
                status_code = getattr(getattr(e, "response", None), "status_code", None)
                if status_code == 429 or "429" in str(e):
                    self.mark_exhausted(key)
                    print(f"  [KeyManager] Key ...{key[-4:]} exhausted (429), rotating to next key...")
                    continue
                raise

    def status(self) -> list[dict]:
        """Return quota status for all registered keys (current month)."""
        month = _current_month()
        conn = self._conn()
        rows = {
            r["key_hash"]: dict(r)
            for r in conn.execute(
                "SELECT key_hash, calls, exhausted FROM numista_key_usage WHERE month = ?",
                (month,),
            ).fetchall()
        }
        conn.close()

        result = []
        for i, (key_hash, _) in enumerate(self._keys, 1):
            row = rows.get(key_hash)
            calls = row["calls"] if row else 0
            exhausted = bool(row["exhausted"]) if row else False
            result.append({
                "slot": i,
                "key_hash": key_hash,
                "calls_this_month": calls,
                "remaining": max(0, _MONTHLY_LIMIT - calls),
                "exhausted": exhausted,
                "month": month,
            })
        return result
