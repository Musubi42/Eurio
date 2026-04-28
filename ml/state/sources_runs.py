"""Per-source run markers — `ml/state/sources_runs.json`.

Each scraper / enrich script calls `record_run(source_id, kind, ...)` once at
the end of its main(). The aggregator endpoint reads `read_all()` to expose
"days since last run" and basic delta counts in the `/sources` admin page.

The marker is intentionally lightweight: a single JSON file rewritten
atomically (tempfile + os.replace) on every run. Concurrency is rare
(scrapes run serially in practice) but the rename is atomic on every POSIX
filesystem we care about.
"""

from __future__ import annotations

import json
import os
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

DEFAULT_PATH = Path(__file__).parent / "sources_runs.json"
_lock = threading.Lock()


def record_run(
    source_id: str,
    kind: str,
    *,
    calls: int = 0,
    added_coins: int = 0,
    path: Path = DEFAULT_PATH,
) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with _lock:
        data: dict[str, Any] = {}
        if path.exists():
            try:
                data = json.loads(path.read_text())
            except json.JSONDecodeError:
                data = {}
        data[source_id] = {
            "last_run_at": datetime.now(timezone.utc).isoformat(),
            "last_run_kind": kind,
            "last_run_calls": int(calls),
            "last_run_added_coins": int(added_coins),
        }
        tmp = path.with_suffix(path.suffix + ".tmp")
        tmp.write_text(json.dumps(data, indent=2, ensure_ascii=False))
        os.replace(tmp, path)


def read_all(path: Path = DEFAULT_PATH) -> dict[str, dict]:
    path = Path(path)
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text())
    except json.JSONDecodeError:
        return {}
