"""Replay une session bench enregistrée sous une config alternative.

Usage (depuis ml/) :

    .venv/bin/python -m bench.replay_session \\
        --session bench/sessions/Pixel9a/sessions/20260516_140229_e15a \\
        --override trigger_mode=yolo_confidence --override yolo_conf_min=0.45

Sans ``--override``, rejoue la config enregistrée (utile pour vérifier la
parité gates Python↔Kotlin : le résumé compare aux passes enregistrées).
Sortie : ``<session>/replays/replay_<hash>.jsonl`` (ou ``--output``).
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from bench.replay import config_hash, replay, write_replay_jsonl
from bench.session_io import SessionParseError, load_session


def _parse_override(raw: str) -> tuple[str, object]:
    if "=" not in raw:
        raise argparse.ArgumentTypeError(f"override attendu clé=valeur, reçu {raw!r}")
    key, value = raw.split("=", 1)
    for cast in (int, float):
        try:
            return key, cast(value)
        except ValueError:
            continue
    if value.lower() in ("true", "false"):
        return key, value.lower() == "true"
    return key, value


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--session", required=True, help="dossier de la session")
    parser.add_argument(
        "--override",
        action="append",
        default=[],
        type=_parse_override,
        metavar="CLE=VALEUR",
        help="champ de BenchConfig à surcharger (répétable)",
    )
    parser.add_argument("--output", help="chemin du JSONL shadow (défaut: replays/)")
    args = parser.parse_args(argv)

    try:
        session = load_session(Path(args.session))
    except SessionParseError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    if session.config is None:
        print("error: session sans config_snapshot", file=sys.stderr)
        return 2

    config = session.config.with_overrides(dict(args.override))
    result = replay(session, config)
    output = write_replay_jsonl(
        session, result, Path(args.output) if args.output else None
    )

    # Comparaison à l'original : fires enregistrés + drift des gates.
    recorded_fires = session.events_of("trigger_fire")
    recorded_pass = [
        f.score.passes.get("all")
        for f in session.frames
        if f.score is not None
    ]
    recorded_rate = (
        sum(1 for p in recorded_pass if p) / len(recorded_pass)
        if recorded_pass
        else None
    )

    print(f"OK · replay {session.session_id} config={config_hash(config)}")
    print(f"  frames analysées : {len(result.frames)} "
          f"(scorées : {sum(1 for f in result.frames if f.rescored)})")
    rate = result.gates_pass_rate()
    print(
        "  gates pass rate  : "
        f"{rate:.1%}" if rate is not None else "  gates pass rate  : n/a",
        end="",
    )
    if recorded_rate is not None:
        print(f"  (enregistré : {recorded_rate:.1%})")
    else:
        print()
    print(f"  trigger fires    : {len(result.fires)} "
          f"(enregistrés : {len(recorded_fires)})")
    for fire in result.fires:
        sel = fire["selection"]
        sel_txt = (
            f"frame {sel['frame_id']} [{sel['selection_reason']}] "
            f"agg={sel['aggregate']:.3f}"
            if sel
            else "buffer vide"
        )
        print(f"    - {fire['reason']} → {sel_txt}")
    print(f"  shadow JSONL     : {output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
