"""Parsers for recorded bench sessions (events.jsonl + ground_truth.json).

Schema contract — mirror of ``app-android .../ml/bench/BenchEvent.kt`` :

  - **v1** (sessions enregistrées ≤ 2026-05) : le champ de la frame s'appelle
    ``seq`` (il porte en réalité un timestamp millis, monotone par session) et
    les entrées ArcFace utilisent la clé ``eurio_id`` — qui contient en fait le
    label brut du modèle (ID Numista numérique), pas un eurio_id canonique.
  - **v2** (BenchRecorder.SCHEMA_VERSION actuel) : ``frame_ts_ms`` remplace
    ``seq`` ; la clé ArcFace devient ``class_name`` (sémantique clarifiée) ;
    ``session_start`` porte ``coin`` / ``condition`` quand la session vient du
    protocole guidé (BenchProtocol).

Le parseur normalise les deux vers les mêmes dataclasses : ``frame_id`` est
l'identifiant d'ordre (ex-``seq`` / ``frame_ts_ms``), ArcFace expose
``class_name``. On refuse les schémas > 2 plutôt que de mal interpréter un
champ (même doctrine que ``BundleMeta.kt`` côté Android).
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterator

ML_DIR = Path(__file__).resolve().parent.parent
SESSIONS_ROOT = ML_DIR / "bench" / "sessions"

SUPPORTED_SCHEMAS = (1, 2)
GROUND_TRUTH_FILENAME = "ground_truth.json"
REPLAYS_DIRNAME = "replays"


class SessionParseError(ValueError):
    """events.jsonl illisible ou schéma non supporté — jamais ignoré en silence."""


@dataclass(frozen=True)
class ArcfaceEntry:
    class_name: str  # label brut du modèle (ID Numista), PAS un eurio_id résolu
    cos: float


@dataclass(frozen=True)
class Detection:
    method: str  # "YOLO" | "HOUGH"
    bbox: tuple[float, float, float, float] | None  # left, top, right, bottom
    yolo_conf: float | None


@dataclass(frozen=True)
class RecordedScore:
    """ScorePayload tel qu'enregistré — mesures brutes + dérivés Kotlin."""

    sharpness: float
    sharpness_raw: float
    exposure: float
    mean_luminance: float
    clipping_ratio: float
    completeness: float
    motion: float | None
    aggregate: float
    passes: dict[str, bool | None]  # sharpness/exposure/completeness/motion/all


@dataclass(frozen=True)
class FrameEvent:
    t: float
    frame_id: int  # v1 `seq` / v2 `frame_ts_ms` — monotone, clé d'ordre
    detection: Detection | None
    score: RecordedScore | None
    arcface_top3: tuple[ArcfaceEntry, ...]
    timings_ms: dict[str, int]


@dataclass(frozen=True)
class BenchConfig:
    """ConfigPayload — le snapshot DebugScanConfig au start de session."""

    trigger_mode: str
    stability_iou_min: float
    stability_n_frames: int
    yolo_conf_min: float
    burst_size: int
    rolling_buffer_enabled: bool
    ae_lock_enabled: bool
    af_lock_enabled: bool
    awb_lock_enabled: bool
    sharpness_min: float
    exposure_band_half_width: float
    completeness_min: float
    motion_enabled: bool
    capture_mode: str

    def with_overrides(self, overrides: dict[str, Any]) -> "BenchConfig":
        unknown = set(overrides) - set(self.__dataclass_fields__)
        if unknown:
            raise SessionParseError(
                f"override(s) inconnu(s) : {sorted(unknown)} — clés valides : "
                f"{sorted(self.__dataclass_fields__)}"
            )
        merged = {**self.__dict__, **overrides}
        return BenchConfig(**merged)


@dataclass
class Session:
    session_id: str
    device: str | None
    path: Path
    schema_version: int
    coin: str | None
    condition: str | None
    config: BenchConfig | None
    device_info: dict[str, Any]
    events: list[dict[str, Any]]  # tous les events bruts, ordre fichier
    frames: list[FrameEvent]  # frame_analyzed normalisés, ordre fichier
    duration_ms: int | None
    dropped_lines: int | None

    @property
    def ground_truth_path(self) -> Path:
        return self.path / GROUND_TRUTH_FILENAME

    @property
    def frames_dir(self) -> Path:
        return self.path / "frames"

    @property
    def replays_dir(self) -> Path:
        return self.path / REPLAYS_DIRNAME

    def state_transitions(self) -> list[dict[str, Any]]:
        return [e for e in self.events if e.get("evt") == "state_transition"]

    def events_of(self, evt: str) -> list[dict[str, Any]]:
        return [e for e in self.events if e.get("evt") == evt]


def _parse_frame(raw: dict[str, Any]) -> FrameEvent:
    det = raw.get("detection")
    detection = None
    if det is not None:
        bbox = det.get("bbox")
        detection = Detection(
            method=det.get("method", "?"),
            bbox=tuple(bbox) if bbox else None,
            yolo_conf=det.get("yolo_conf"),
        )

    sc = raw.get("score")
    score = None
    if sc is not None:
        score = RecordedScore(
            sharpness=sc["sharpness"],
            sharpness_raw=sc["sharpness_raw"],
            exposure=sc["exposure"],
            mean_luminance=sc["mean_luminance"],
            clipping_ratio=sc["clipping_ratio"],
            completeness=sc["completeness"],
            motion=sc.get("motion"),
            aggregate=sc["aggregate"],
            passes=dict(sc["passes"]),
        )

    arcface = tuple(
        ArcfaceEntry(
            # v2 = class_name ; v1 = eurio_id (label modèle malgré le nom)
            class_name=entry.get("class_name") or entry["eurio_id"],
            cos=entry["cos"],
        )
        for entry in raw.get("arcface_top3", [])
    )

    frame_id = raw.get("frame_ts_ms")
    if frame_id is None:
        frame_id = raw["seq"]

    return FrameEvent(
        t=raw["t"],
        frame_id=int(frame_id),
        detection=detection,
        score=score,
        arcface_top3=arcface,
        timings_ms=dict(raw.get("timings_ms", {})),
    )


def load_session(path: Path | str, device: str | None = None) -> Session:
    """Parse ``<path>/events.jsonl`` en :class:`Session`.

    Lève :class:`SessionParseError` sur fichier absent, ligne JSON cassée ou
    ``schema_version`` non supporté. Un ``session_end`` manquant (crash
    mi-session) est toléré : le streaming flush côté Android garantit un
    préfixe lisible, c'est un cas de premier ordre pour le bench.
    """
    path = Path(path)
    events_file = path / "events.jsonl"
    if not events_file.exists():
        raise SessionParseError(f"{events_file} absent — pas une session bench")

    events: list[dict[str, Any]] = []
    for lineno, line in enumerate(
        events_file.read_text().splitlines(), start=1
    ):
        if not line.strip():
            continue
        try:
            events.append(json.loads(line))
        except json.JSONDecodeError as exc:
            # Dernière ligne tronquée = crash mi-écriture, on garde le préfixe.
            if lineno == len(events_file.read_text().splitlines()):
                break
            raise SessionParseError(
                f"{events_file}:{lineno} JSON invalide : {exc}"
            ) from exc

    if not events or events[0].get("evt") != "session_start":
        raise SessionParseError(
            f"{events_file} ne commence pas par session_start"
        )
    start = events[0]
    schema = int(start.get("schema_version", 0))
    if schema not in SUPPORTED_SCHEMAS:
        raise SessionParseError(
            f"schema_version {schema} non supporté (connus : {SUPPORTED_SCHEMAS})"
            " — mettre à jour bench/session_io.py en conscience, pas de parse"
            " best-effort"
        )

    config = None
    device_info: dict[str, Any] = {}
    for e in events:
        if e.get("evt") == "config_snapshot" and config is None:
            config = BenchConfig(**e["config"])
        elif e.get("evt") == "device_info" and not device_info:
            device_info = {k: v for k, v in e.items() if k not in ("evt", "t")}

    frames = [
        _parse_frame(e) for e in events if e.get("evt") == "frame_analyzed"
    ]

    end = next(
        (e for e in events if e.get("evt") == "session_end"), None
    )

    return Session(
        session_id=start.get("session_id", path.name),
        device=device,
        path=path,
        schema_version=schema,
        coin=start.get("coin"),
        condition=start.get("condition"),
        config=config,
        device_info=device_info,
        events=events,
        frames=frames,
        duration_ms=end.get("duration_ms") if end else None,
        dropped_lines=end.get("dropped_lines") if end else None,
    )


def iter_session_dirs(
    root: Path | str = SESSIONS_ROOT, device: str | None = None
) -> Iterator[tuple[str, Path]]:
    """Yield ``(device, session_dir)`` pour chaque session sous *root*.

    Layout produit par ``go-task android:bench:pull`` :
    ``<root>/<device>/sessions/<session_id>/events.jsonl``.
    """
    root = Path(root)
    if not root.exists():
        return
    devices = (
        [root / device] if device else sorted(p for p in root.iterdir() if p.is_dir())
    )
    for device_dir in devices:
        sessions_dir = device_dir / "sessions"
        if not sessions_dir.is_dir():
            continue
        for session_dir in sorted(sessions_dir.iterdir()):
            if (session_dir / "events.jsonl").exists():
                yield device_dir.name, session_dir


def load_sessions(
    root: Path | str = SESSIONS_ROOT, device: str | None = None
) -> list[Session]:
    return [
        load_session(path, device=dev)
        for dev, path in iter_session_dirs(root, device)
    ]


# ── Ground truth (annotate_session.py) ───────────────────────────────────────


@dataclass
class GroundTruth:
    human_best_frame_id: int | None
    confirmed_eurio_id: str | None
    model_top1_correct: bool | None
    condition: str | None
    annotator: str = "raphael"
    notes: str = ""
    extras: dict[str, Any] = field(default_factory=dict)

    def to_json(self) -> dict[str, Any]:
        return {
            "human_best_frame_id": self.human_best_frame_id,
            "confirmed_eurio_id": self.confirmed_eurio_id,
            "model_top1_correct": self.model_top1_correct,
            "condition": self.condition,
            "annotator": self.annotator,
            "notes": self.notes,
            **self.extras,
        }


def load_ground_truth(session_path: Path | str) -> GroundTruth | None:
    gt_file = Path(session_path) / GROUND_TRUTH_FILENAME
    if not gt_file.exists():
        return None
    raw = json.loads(gt_file.read_text())
    known = {
        "human_best_frame_id",
        "confirmed_eurio_id",
        "model_top1_correct",
        "condition",
        "annotator",
        "notes",
    }
    return GroundTruth(
        human_best_frame_id=raw.get("human_best_frame_id"),
        confirmed_eurio_id=raw.get("confirmed_eurio_id"),
        model_top1_correct=raw.get("model_top1_correct"),
        condition=raw.get("condition"),
        annotator=raw.get("annotator", "raphael"),
        notes=raw.get("notes", ""),
        extras={k: v for k, v in raw.items() if k not in known},
    )


def save_ground_truth(session_path: Path | str, gt: GroundTruth) -> Path:
    gt_file = Path(session_path) / GROUND_TRUTH_FILENAME
    gt_file.write_text(json.dumps(gt.to_json(), ensure_ascii=False, indent=2) + "\n")
    return gt_file
