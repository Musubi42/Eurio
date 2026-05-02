"""Per-step implementations of the 6-step pipeline (D-13).

Each module owns one step and is callable from `orchestrator.py`.
Steps are deliberately thin and idempotent — they delegate persistence
to `dedup.py` and only carry the loop / counter logic.
"""
