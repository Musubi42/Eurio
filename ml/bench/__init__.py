"""Bench tooling for the best-frame-capture scan pipeline (chunk 7).

Android records scan sessions as JSONL (``BenchRecorder.kt``) ; this package
parses them (``session_io``), replays them offline under alternative configs
(``replay``, ``replay_session``), collects human ground truth
(``annotate_session``), grid-searches quality thresholds
(``calibrate_thresholds``) and renders comparative reports (``compare_runs``).

Sessions live under ``ml/bench/sessions/<device>/sessions/<id>/`` — the layout
``go-task android:bench:pull`` produces.
"""
