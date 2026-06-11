"""CLI interactif d'annotation ground-truth des sessions bench.

Usage (depuis ml/) :

    .venv/bin/python -m bench.annotate_session --device Pixel9a [--session <id>]

Pour chaque session non annotée : affiche le résumé (frames scorées, fires,
consensus), ouvre les vignettes ``frames/`` dans la visionneuse système si
présentes, puis demande :

  1. la meilleure frame humaine (par ``frame_id``, parmi les frames scorées) ;
  2. l'eurio_id confirmé (préfill : tag ``coin`` du protocole guidé v2,
     sinon le label du dernier ``consensus_reached``) ;
  3. la condition (préfill : tag ``condition`` v2 — sessions du protocole
     guidé déjà taguées, on ne re-demande pas).

Écrit ``ground_truth.json`` dans le dossier de session (relu par
``calibrate_thresholds`` et ``compare_runs``).
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

from bench.session_io import (
    SESSIONS_ROOT,
    GroundTruth,
    Session,
    iter_session_dirs,
    load_ground_truth,
    load_session,
    save_ground_truth,
)

CONDITIONS = (
    "bright_plain",
    "bright_textured",
    "dim",
    "oblique",
    "glare_specular",
)


def _prompt(label: str, default: str | None = None) -> str:
    suffix = f" [{default}]" if default else ""
    raw = input(f"{label}{suffix}: ").strip()
    return raw or (default or "")


def _open_frames(session: Session) -> None:
    if not session.frames_dir.is_dir():
        return
    jpgs = sorted(session.frames_dir.glob("*.jpg"))
    if not jpgs:
        return
    print(f"  {len(jpgs)} frames JPEG — ouverture visionneuse…")
    if sys.platform == "darwin":
        subprocess.run(["open", *map(str, jpgs)], check=False)
    else:
        subprocess.run(["xdg-open", str(session.frames_dir)], check=False)


def _summary(session: Session) -> None:
    scored = [f for f in session.frames if f.score is not None]
    print(f"\n── session {session.session_id} "
          f"(schema v{session.schema_version}, device {session.device or '?'})")
    if session.coin or session.condition:
        print(f"  protocole : coin={session.coin} condition={session.condition}")
    print(f"  {len(session.frames)} frames analysées, {len(scored)} scorées, "
          f"durée {session.duration_ms} ms")
    consensus = session.events_of("consensus_reached")
    if consensus:
        print(f"  consensus : {consensus[-1].get('eurio_id')}")
    fires = session.events_of("trigger_fire")
    for fire in fires:
        print(f"  trigger_fire : {fire.get('reason')}")
    print("  frames scorées (frame_id → aggregate, passes.all) :")
    for f in scored:
        mark = "✓" if f.score.passes.get("all") else "✗"
        print(f"    {f.frame_id}  agg={f.score.aggregate:.3f}  {mark}")


def annotate(session: Session, annotator: str) -> GroundTruth:
    _summary(session)
    _open_frames(session)

    scored_ids = [f.frame_id for f in session.frames if f.score is not None]
    best_raw = _prompt(
        "Meilleure frame humaine (frame_id, vide = aucune exploitable)",
        default=None,
    )
    best_id: int | None = None
    if best_raw:
        best_id = int(best_raw)
        if best_id not in scored_ids:
            print(f"  ⚠ {best_id} n'est pas une frame scorée de cette session")

    consensus = session.events_of("consensus_reached")
    model_label = consensus[-1].get("eurio_id") if consensus else None
    confirmed = _prompt(
        "eurio_id confirmé", default=session.coin or model_label
    ) or None
    top1_correct = (
        None
        if model_label is None or confirmed is None
        else model_label == confirmed
    )

    condition = _prompt(
        f"Condition {CONDITIONS}", default=session.condition
    ) or None
    if condition and condition not in CONDITIONS:
        print(f"  ⚠ condition {condition!r} hors liste canonique (gardée telle quelle)")

    notes = _prompt("Notes", default="")

    return GroundTruth(
        human_best_frame_id=best_id,
        confirmed_eurio_id=confirmed,
        model_top1_correct=top1_correct,
        condition=condition,
        annotator=annotator,
        notes=notes,
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--device", help="ne traiter que ce device")
    parser.add_argument("--session", help="ne traiter que cette session (id)")
    parser.add_argument("--root", default=str(SESSIONS_ROOT))
    parser.add_argument(
        "--redo", action="store_true", help="ré-annoter même si ground_truth.json existe"
    )
    parser.add_argument("--annotator", default="raphael")
    args = parser.parse_args(argv)

    done = 0
    for device, path in iter_session_dirs(Path(args.root), args.device):
        if args.session and path.name != args.session:
            continue
        if not args.redo and load_ground_truth(path) is not None:
            continue
        session = load_session(path, device=device)
        gt = annotate(session, args.annotator)
        out = save_ground_truth(path, gt)
        print(f"  → {out}")
        done += 1

    if done == 0:
        print("Rien à annoter (toutes les sessions ont un ground_truth.json ; "
              "--redo pour ré-annoter).")
    else:
        print(f"\nOK · {done} session(s) annotée(s).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
