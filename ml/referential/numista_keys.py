"""Numista API key manager with monthly quota tracking.

Reads NUMISTA_API_KEY_MUSUBI00, NUMISTA_API_KEY_MUSUBI01, ... from the
environment (set via .envrc). Counting is delegated to QuotaTracker (one
shared `api_call_log` SQLite table for every API source). KeyManager is the
multi-key piece: pick the next-best key, rotate on 429, expose status.
"""

from __future__ import annotations

import hashlib
import os
from pathlib import Path

from api_quota import DEFAULT_DB, QuotaTracker

_SOURCE = "numista"
_WINDOW = "monthly"
_MONTHLY_LIMIT = 1800


def _key_hash(key: str) -> str:
    return hashlib.sha256(key.encode()).hexdigest()[:12]


class KeyManager:
    """Pick the best available Numista key and track its quota."""

    def __init__(self, db_path: Path = DEFAULT_DB) -> None:
        self._tracker = QuotaTracker(_SOURCE, _WINDOW, _MONTHLY_LIMIT, db_path=db_path)
        self._keys = self._load_keys()
        if not self._keys:
            raise RuntimeError(
                "No Numista API keys found. "
                "Add NUMISTA_API_KEY_MUSUBI00 (and optionally MUSUBI01, ...) to .envrc"
            )

    # ── Key loading ──────────────────────────────────────────────────────────

    def _load_keys(self) -> list[tuple[str, str]]:
        """Return [(key_hash, key_value), ...] from env, in slot order.

        Scans NUMISTA_API_KEY_MUSUBI00, NUMISTA_API_KEY_MUSUBI01, ...
        Stops at the first missing slot.
        """
        keys: list[tuple[str, str]] = []
        i = 0
        while True:
            val = os.environ.get(f"NUMISTA_API_KEY_MUSUBI{i:02d}")
            if not val:
                break
            keys.append((_key_hash(val), val))
            i += 1
        return keys

    # ── Public API ───────────────────────────────────────────────────────────

    def pick(self) -> str:
        """Return the best available key for this month.

        Picks the key with fewest calls this month that is neither
        exhausted nor at the 1800 soft limit.
        Raises RuntimeError if all keys are at capacity.
        """
        per_key = {s.key_hash: s for s in self._tracker.status()}
        candidates: list[tuple[int, str]] = []
        for key_hash, key_value in self._keys:
            s = per_key.get(key_hash)
            calls = s.calls if s else 0
            exhausted = s.exhausted if s else False
            if not exhausted and calls < _MONTHLY_LIMIT:
                candidates.append((calls, key_value))

        if not candidates:
            raise RuntimeError(
                f"All Numista API keys are at or above the {_MONTHLY_LIMIT}/month soft limit "
                "or have received a 429. Add a new key or wait until next month."
            )

        candidates.sort(key=lambda x: x[0])
        return candidates[0][1]

    def record_call(self, key: str) -> None:
        self._tracker.record(_key_hash(key))

    def mark_exhausted(self, key: str) -> None:
        self._tracker.mark_exhausted(_key_hash(key))

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
        per_key = {s.key_hash: s for s in self._tracker.status()}
        period = self._tracker._period()
        result = []
        for slot, (key_hash, _) in enumerate(self._keys, 1):
            s = per_key.get(key_hash)
            calls = s.calls if s else 0
            exhausted = s.exhausted if s else False
            result.append({
                "slot": slot,
                "key_hash": key_hash,
                "calls_this_month": calls,
                "remaining": max(0, _MONTHLY_LIMIT - calls),
                "exhausted": exhausted,
                "month": period,
            })
        return result
