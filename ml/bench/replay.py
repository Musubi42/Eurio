"""Offline replay engine — re-runs trigger + gates + selection on a session.

Ports exacts des stratégies Kotlin (``app-android .../ml/trigger/``) :

  - :class:`BoxStabilityTrigger`  ↔ ``BoxStabilityTrigger.kt`` (IoU consécutifs)
  - :class:`YoloConfidenceTrigger` ↔ ``YoloConfidenceTrigger.kt`` (silencieux
    sur frames Hough-only, reset compteur)
  - :class:`BestFrameSelector`    ↔ ``BestFrameSelector.kt`` (D8 : plus
    *ancienne* frame qui passe tous les gates, sinon max aggregate)
  - :func:`iou`                   ↔ ``BboxF.kt``

Limites de fidélité, assumées et documentées (chunk-7 spec §replay) :

  - **Détection non rejouable** : on opère sur ce que le détecteur a vu
    (bbox/conf enregistrées), pas sur la détection elle-même.
  - **Composition du buffer approximée** : le ``RollingFrameBuffer`` Android
    n'enregistre pas ses membres ; on le reconstruit en poussant chaque
    frame *scorée* (le ``CoinAnalyzer`` ne pousse qu'après normalize réussi).
  - **arcface_consensus non simulable frame à frame** : le
    ``consensusLockedClass`` n'est pas enregistré par frame. On rejoue ce
    trigger en le faisant tirer aux events ``consensus_reached`` — fidèle au
    *moment* du fire, pas à sa mécanique interne.

Les gates/aggregate sont recalculés depuis les mesures brutes enregistrées
via ``vision.frame_scorer.rescore_from_measures`` — donc exacts sous toute
policy, frames JPEG présentes ou non.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from bench.session_io import BenchConfig, FrameEvent, Session
from vision.frame_scorer import FrameScore, ScoringPolicy, rescore_from_measures

REPLAY_SCHEMA_VERSION = 1


# ── BboxF.kt ─────────────────────────────────────────────────────────────────


def iou(a: tuple[float, float, float, float], b: tuple[float, float, float, float]) -> float:
    """IoU, 0 sur boîtes dégénérées — jamais NaN (mirror ``BboxF.kt``)."""

    def area(box: tuple[float, float, float, float]) -> float:
        return max(box[2] - box[0], 0.0) * max(box[3] - box[1], 0.0)

    inter_w = max(min(a[2], b[2]) - max(a[0], b[0]), 0.0)
    inter_h = max(min(a[3], b[3]) - max(a[1], b[1]), 0.0)
    inter = inter_w * inter_h
    union = area(a) + area(b) - inter
    return inter / union if union > 0 else 0.0


# ── Frames re-scorées (l'unité que triggers/selector consomment) ─────────────


@dataclass(frozen=True)
class ReplayFrame:
    source: FrameEvent
    rescored: FrameScore | None  # None ⟺ frame sans score enregistré

    @property
    def frame_id(self) -> int:
        return self.source.frame_id


def rescore_frame(frame: FrameEvent, policy: ScoringPolicy) -> ReplayFrame:
    if frame.score is None:
        return ReplayFrame(source=frame, rescored=None)
    s = frame.score
    return ReplayFrame(
        source=frame,
        rescored=rescore_from_measures(
            sharpness_raw=s.sharpness_raw,
            mean_luminance=s.mean_luminance,
            clipping_ratio=s.clipping_ratio,
            completeness_score=s.completeness,
            motion_score=s.motion,
            policy=policy,
        ),
    )


# ── TriggerStrategy ports ────────────────────────────────────────────────────


@dataclass(frozen=True)
class TriggerFire:
    reason: str
    buffer_snapshot: tuple[ReplayFrame, ...]


class BoxStabilityTrigger:
    """Port exact de ``BoxStabilityTrigger.kt`` — mêmes resets, même reason."""

    name = "box_stability"

    def __init__(self, iou_min: float, n_frames_required: int) -> None:
        self.iou_min = iou_min
        self.n_frames_required = n_frames_required
        self.reset()

    def reset(self) -> None:
        self._fired_for_run = False
        self._consecutive = 0
        self._last_bbox: tuple[float, float, float, float] | None = None

    def observe(
        self, frame: ReplayFrame, buffer: list[ReplayFrame]
    ) -> TriggerFire | None:
        if self._fired_for_run:
            return None
        det = frame.source.detection
        current = det.bbox if det else None
        if current is None:
            self._consecutive = 0
            self._last_bbox = None
            return None

        if self._last_bbox is not None:
            if iou(self._last_bbox, current) >= self.iou_min:
                self._consecutive += 1
            else:
                self._consecutive = 1
        else:
            self._consecutive = 1
        self._last_bbox = current

        if self._consecutive >= self.n_frames_required:
            self._fired_for_run = True
            return TriggerFire(
                reason=f"stable {self._consecutive}f IoU≥{self.iou_min:.2f}",
                buffer_snapshot=tuple(buffer),
            )
        return None


class YoloConfidenceTrigger:
    """Port exact de ``YoloConfidenceTrigger.kt`` — silencieux hors YOLO."""

    name = "yolo_confidence"

    def __init__(self, conf_min: float, n_frames_required: int) -> None:
        self.conf_min = conf_min
        self.n_frames_required = n_frames_required
        self.reset()

    def reset(self) -> None:
        self._fired_for_run = False
        self._consecutive = 0

    def observe(
        self, frame: ReplayFrame, buffer: list[ReplayFrame]
    ) -> TriggerFire | None:
        if self._fired_for_run:
            return None
        det = frame.source.detection
        conf = det.yolo_conf if det else None
        source = det.method if det else None
        if conf is None or source != "YOLO" or conf < self.conf_min:
            self._consecutive = 0
            return None
        self._consecutive += 1
        if self._consecutive >= self.n_frames_required:
            self._fired_for_run = True
            return TriggerFire(
                reason=f"yolo {self._consecutive}f conf≥{self.conf_min:.2f}",
                buffer_snapshot=tuple(buffer),
            )
        return None


class NoOpTrigger:
    name = "off"

    def reset(self) -> None:  # pragma: no cover - trivial
        pass

    def observe(self, frame: ReplayFrame, buffer: list[ReplayFrame]) -> None:
        return None


def make_trigger(config: BenchConfig):
    mode = config.trigger_mode.lower()
    if mode == "off":
        return NoOpTrigger()
    if mode == "box_stability":
        return BoxStabilityTrigger(
            iou_min=config.stability_iou_min,
            n_frames_required=config.stability_n_frames,
        )
    if mode == "yolo_confidence":
        return YoloConfidenceTrigger(
            conf_min=config.yolo_conf_min,
            n_frames_required=config.stability_n_frames,
        )
    if mode == "arcface_consensus":
        # Pas de port mécanique possible (consensusLockedClass non enregistré
        # par frame) — replay_session gère ce mode via les events
        # consensus_reached. Refus explicite ici plutôt qu'une simulation
        # silencieusement fausse.
        raise ValueError(
            "arcface_consensus n'est pas simulable frame à frame depuis une "
            "session enregistrée — le replay le rejoue aux events "
            "consensus_reached (voir replay_session.py)"
        )
    raise ValueError(f"trigger_mode inconnu : {config.trigger_mode!r}")


# ── BestFrameSelector.kt ─────────────────────────────────────────────────────


@dataclass(frozen=True)
class Selection:
    frame: ReplayFrame
    index_in_snapshot: int
    reason: str  # "PASSED_ALL_GATES" | "BEST_AGGREGATE_FALLBACK"


def select_best_frame(snapshot: list[ReplayFrame] | tuple[ReplayFrame, ...]) -> Selection | None:
    """D8 : plus ancienne frame qui passe tous les gates, sinon max aggregate.

    ``None`` ⟺ snapshot vide (mirror de ``SelectionResult.Empty``).
    """
    scored = [f for f in snapshot if f.rescored is not None]
    if not scored:
        return None
    for idx, frame in enumerate(scored):
        if frame.rescored.passes_all:
            return Selection(frame=frame, index_in_snapshot=idx, reason="PASSED_ALL_GATES")
    best_idx = 0
    best_agg = scored[0].rescored.aggregate
    for i in range(1, len(scored)):
        agg = scored[i].rescored.aggregate
        if agg > best_agg:
            best_agg = agg
            best_idx = i
    return Selection(
        frame=scored[best_idx],
        index_in_snapshot=best_idx,
        reason="BEST_AGGREGATE_FALLBACK",
    )


# ── Replay d'une session entière ─────────────────────────────────────────────


@dataclass
class ReplayResult:
    session_id: str
    config: BenchConfig
    frames: list[ReplayFrame]
    fires: list[dict[str, Any]]  # shadow events trigger_fire + selection
    shadow_events: list[dict[str, Any]]

    @property
    def first_selection_frame_id(self) -> int | None:
        for fire in self.fires:
            sel = fire.get("selection")
            if sel:
                return sel["frame_id"]
        return None

    def gates_pass_rate(self) -> float | None:
        scored = [f for f in self.frames if f.rescored is not None]
        if not scored:
            return None
        return sum(1 for f in scored if f.rescored.passes_all) / len(scored)


def config_hash(config: BenchConfig) -> str:
    payload = json.dumps(config.__dict__, sort_keys=True)
    return hashlib.sha256(payload.encode()).hexdigest()[:8]


def policy_from_config(config: BenchConfig) -> ScoringPolicy:
    """Mirror de ``ScoringPolicy.fromDebugConfig`` — seuls 4 knobs viennent du
    config runtime, le reste reste aux défauts gelés du data class Kotlin."""
    return ScoringPolicy(
        sharpness_min=config.sharpness_min,
        exposure_band_half_width=config.exposure_band_half_width,
        completeness_min=config.completeness_min,
        motion_enabled=config.motion_enabled,
    )


def replay(session: Session, config: BenchConfig | None = None) -> ReplayResult:
    """Rejoue *session* sous *config* (défaut : le config enregistré).

    Boucle fidèle au pipeline Android : pour chaque ``frame_analyzed`` dans
    l'ordre du fichier — (1) re-score sous la policy, (2) push dans le buffer
    simulé si la frame est scorée, (3) ``trigger.observe``, (4) au Fire :
    sélection D8 sur le snapshot. Le trigger n'est PAS reset après fire (même
    sémantique ``firedForRun`` que le device : un seul fire par run, le reset
    vient du retour Idle que le replay ne simule pas — les sessions bench
    couvrent un seul scan).
    """
    cfg = config or session.config
    if cfg is None:
        raise ValueError(
            f"session {session.session_id} sans config_snapshot — replay "
            "impossible sans config explicite"
        )

    policy = policy_from_config(cfg)
    capacity = max(cfg.burst_size, 1)

    if cfg.trigger_mode.lower() == "arcface_consensus":
        return _replay_arcface_consensus(session, cfg, policy, capacity)

    trigger = make_trigger(cfg)
    buffer: list[ReplayFrame] = []
    frames: list[ReplayFrame] = []
    fires: list[dict[str, Any]] = []
    shadow: list[dict[str, Any]] = []

    for raw in session.frames:
        frame = rescore_frame(raw, policy)
        frames.append(frame)
        if frame.rescored is not None:
            buffer.append(frame)
            if len(buffer) > capacity:
                buffer.pop(0)
        fired = trigger.observe(frame, buffer)
        if fired is not None:
            fires.append(_fire_record(raw.t, trigger.name, fired, shadow))

    return ReplayResult(
        session_id=session.session_id,
        config=cfg,
        frames=frames,
        fires=fires,
        shadow_events=shadow,
    )


def _replay_arcface_consensus(
    session: Session,
    cfg: BenchConfig,
    policy: ScoringPolicy,
    capacity: int,
) -> ReplayResult:
    """Rejoue arcface_consensus aux timestamps des ``consensus_reached``."""
    consensus_ts = sorted(e["t"] for e in session.events_of("consensus_reached"))
    buffer: list[ReplayFrame] = []
    frames: list[ReplayFrame] = []
    fires: list[dict[str, Any]] = []
    shadow: list[dict[str, Any]] = []
    pending = list(consensus_ts)

    for raw in session.frames:
        frame = rescore_frame(raw, policy)
        frames.append(frame)
        if frame.rescored is not None:
            buffer.append(frame)
            if len(buffer) > capacity:
                buffer.pop(0)
        while pending and raw.t >= pending[0]:
            pending.pop(0)
            fired = TriggerFire(
                reason="consensus (rejoué sur consensus_reached)",
                buffer_snapshot=tuple(buffer),
            )
            fires.append(_fire_record(raw.t, "arcface_consensus", fired, shadow))

    return ReplayResult(
        session_id=session.session_id,
        config=cfg,
        frames=frames,
        fires=fires,
        shadow_events=shadow,
    )


def _fire_record(
    t: float,
    strategy: str,
    fired: TriggerFire,
    shadow: list[dict[str, Any]],
) -> dict[str, Any]:
    selection = select_best_frame(fired.buffer_snapshot)
    shadow.append(
        {
            "t": t,
            "evt": "trigger_fire",
            "strategy": strategy,
            "reason": fired.reason,
            "buffer_size": len(fired.buffer_snapshot),
            "buffer_frame_ids": [f.frame_id for f in fired.buffer_snapshot],
        }
    )
    sel_payload = None
    if selection is not None:
        sel_payload = {
            "frame_id": selection.frame.frame_id,
            "index_in_snapshot": selection.index_in_snapshot,
            "selection_reason": selection.reason,
            "aggregate": selection.frame.rescored.aggregate,
        }
        shadow.append({"t": t, "evt": "best_frame_selected", **sel_payload})
    else:
        shadow.append(
            {"t": t, "evt": "best_frame_selected", "selection_reason": "EMPTY"}
        )
    return {
        "t": t,
        "strategy": strategy,
        "reason": fired.reason,
        "buffer_size": len(fired.buffer_snapshot),
        "selection": sel_payload,
    }


def write_replay_jsonl(
    session: Session, result: ReplayResult, output: Path | str | None = None
) -> Path:
    """Écrit le JSONL shadow : header replay + gates recalculés + fires."""
    if output is None:
        session.replays_dir.mkdir(exist_ok=True)
        output = session.replays_dir / f"replay_{config_hash(result.config)}.jsonl"
    output = Path(output)
    output.parent.mkdir(parents=True, exist_ok=True)

    lines: list[dict[str, Any]] = [
        {
            "evt": "replay_start",
            "replay_schema_version": REPLAY_SCHEMA_VERSION,
            "session_id": session.session_id,
            "source_schema_version": session.schema_version,
            "config": result.config.__dict__,
            "config_hash": config_hash(result.config),
        }
    ]
    for frame in result.frames:
        if frame.rescored is None:
            continue
        lines.append(
            {
                "t": frame.source.t,
                "evt": "frame_rescored",
                "frame_id": frame.frame_id,
                "score": frame.rescored.as_payload(),
            }
        )
    lines.extend(result.shadow_events)
    summary = {
        "evt": "replay_summary",
        "n_frames": len(result.frames),
        "n_scored": sum(1 for f in result.frames if f.rescored is not None),
        "gates_pass_rate": result.gates_pass_rate(),
        "n_fires": len(result.fires),
        "first_selection_frame_id": result.first_selection_frame_id,
    }
    lines.append(summary)

    output.write_text(
        "\n".join(json.dumps(line, ensure_ascii=False) for line in lines) + "\n"
    )
    return output
