"""Skip de reprise du crop (B6) et son opt-out.

`run_detect_crop` n'exécute plus la détection sur une image déjà tentée sans
crop : le détecteur est déterministe, et re-broyer le backlog `zero_crops` à
chaque reprise faisait croire à l'opérateur que « ça ne fait que des 0 crops ».

Mais les scripts `recrop_*` ciblent EXACTEMENT ces images. Sans opt-out ils
rapporteraient 0 récupéré sur N, sans lever la moindre erreur — d'où ces tests.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

ML_DIR = Path(__file__).parent.parent
if str(ML_DIR) not in sys.path:
    sys.path.insert(0, str(ML_DIR))

from store import Store  # noqa: E402


class _FakeRun:
    """RunHandle minimal — le chemin testé ne fait que compter."""

    run_id = "test-run"

    def bump(self, **_kw) -> None:
        pass

    def set_step(self, _step: str) -> None:
        pass


@pytest.fixture()
def conn(tmp_path):
    return Store(tmp_path / "t.db")._connection()


def _seed_image(conn, sid: str, crop_status: str | None) -> None:
    conn.execute(
        "INSERT INTO source_images (id, source, source_ref, storage_path, fetched_at,"
        " license, crop_status) VALUES (?,?,?,?,?,?,?)",
        (sid, "ebay", f"ref-{sid}", f"raws/{sid}.jpg", "2026-08-16 00:00:00",
         "fair_use_research", crop_status),
    )
    conn.commit()


def _run(conn, monkeypatch, *, retry: bool):
    """Lance le step avec `local_path` qui échoue : une image qui FRANCHIT le
    skip part alors en `n_errors`, une image skippée en `n_skipped`. Le
    compteur suffit donc à distinguer les deux sans faire tourner la détection."""
    import sources._base.steps.detect_crop as dc

    def _boom(*_a, **_kw):
        raise FileNotFoundError("raw absent (stub de test)")

    monkeypatch.setattr(dc, "local_path", _boom)
    return dc.run_detect_crop(
        conn=conn, run=_FakeRun(), source_id="ebay",
        source_image_ids={"ref-si1": "si1"},
        retry_zero_crops=retry,
    )


def test_zero_crops_is_skipped_on_resume(conn, monkeypatch):
    _seed_image(conn, "si1", "zero_crops")
    res = _run(conn, monkeypatch, retry=False)
    assert res.n_skipped == 1
    assert res.n_errors == 0


def test_retry_flag_bypasses_the_skip(conn, monkeypatch):
    """L'opt-out que les scripts `recrop_*` passent — sans lui ils ne font rien."""
    _seed_image(conn, "si1", "zero_crops")
    res = _run(conn, monkeypatch, retry=True)
    assert res.n_skipped == 0
    assert res.n_errors == 1, "l'image doit avoir franchi le skip"


def test_error_status_is_never_skipped(conn, monkeypatch):
    """`crop_status='error'` n'est écrit que par le chemin « raw absent de
    MinIO » — une panne réseau, pas un verdict du détecteur. Le skipper à vie
    ferait qu'un hoquet MinIO exclut ces images définitivement."""
    _seed_image(conn, "si1", "error")
    res = _run(conn, monkeypatch, retry=False)
    assert res.n_skipped == 0
    assert res.n_errors == 1


def test_never_attempted_is_processed(conn, monkeypatch):
    _seed_image(conn, "si1", None)
    res = _run(conn, monkeypatch, retry=False)
    assert res.n_skipped == 0
    assert res.n_errors == 1


def test_recrop_scripts_pass_the_optout():
    """Garde de contrat : ces deux scripts ciblent les `zero_crops`. S'ils
    cessent de passer l'opt-out, ils redeviennent silencieusement inopérants —
    aucun test fonctionnel ne le dirait, ils rapporteraient juste 0 sur N."""
    for name in ("recrop_zero_score_guided", "recrop_ebay_orphans"):
        src = (ML_DIR / "scripts" / f"{name}.py").read_text(encoding="utf-8")
        assert "retry_zero_crops=True" in src, f"{name} ne passe plus l'opt-out"
