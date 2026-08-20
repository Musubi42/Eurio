"""D3/D10/D11/D13 — la banque SERVIE ne peut plus être écrasée ni périmer en silence.

Trois défauts de la revue adversariale du 2026-08-19, tous du même genre : le
scoping par encodeur (P6-1) a fait de `state/foundation_anchors_<kind>.npz` un
sous-produit déduit, alors que c'est **le** fichier que la review sert.

- **D3** — `_get_bank(kind)` lisait l'artefact scopé ; `load_anchors(kind, enc)`
  avalait le mismatch d'encodeur et rendait `None` sans un mot. Le jour d'une
  bascule d'encodeur, la review devenait aveugle et les logs muets.
- **D10** — `dinov2-vitl14` est à la fois l'encodeur servi et le bras baseline
  du banc : le double-écrit « auto si encodeur de production » laissait un
  rebuild de baseline écraser la banque servie.
- **D13** — le CLI imprimait toujours le chemin de la banque servie, même quand
  le run ne l'avait pas écrite.

Aucun test n'écrit dans `ml/state/` : `STATE_DIR` est redirigé sur `tmp_path`.
Le dernier test, lui, LIT `ml/state/` et vérifie que rien n'y a bougé.
"""

from __future__ import annotations

import logging
import sys
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from training.foundation import anchors as anchors_mod  # noqa: E402
from training.foundation.anchors import (  # noqa: E402
    SUGGESTIONS_ANCHORS_KIND,
    AnchorBank,
    anchor_path,
    encoder_version_for_kind,
    legacy_anchor_path,
    load_anchors,
    save_anchors,
    served_anchor_path,
)

KIND = SUGGESTIONS_ANCHORS_KIND
PROD = encoder_version_for_kind(KIND)          # dinov2-vitl14
OTHER = "dinov2-vits14"


@pytest.fixture(autouse=True)
def _state_dir(tmp_path, monkeypatch):
    monkeypatch.setattr(anchors_mod, "STATE_DIR", tmp_path)
    return tmp_path


@pytest.fixture()
def av():
    from sources._base.steps import auto_validate as _av

    _av._bank_cache.clear()
    yield _av
    _av._bank_cache.clear()


def _bank(kind: str, encoder_version: str, *, dim: int = 8, n: int = 3) -> AnchorBank:
    rng = np.random.default_rng(n * 1000 + dim)
    raw = rng.standard_normal((n, dim)).astype(np.float32)
    raw /= np.linalg.norm(raw, axis=1, keepdims=True)
    return AnchorBank(
        eurio_ids=[f"e{i}" for i in range(n)],
        matrix=raw,
        encoder_version=encoder_version,
        anchors_kind=kind,
        built_at=datetime.now(timezone.utc).isoformat(timespec="seconds"),
        source_paths=[f"p{i}" for i in range(n)],
    )


# ---------------------------------------------------------------------------
# D3 — le garde « banque périmée » redevient bruyant
# ---------------------------------------------------------------------------


def test_d3_get_bank_journalise_quand_la_banque_servie_est_perimee(av, caplog):
    """Le scénario exact de la repro : une banque servie en vits14 seule sur
    disque, la review demande sa banque de production (vitl14). Elle doit
    obtenir `None` ET un ERROR nommant les deux encodeurs."""
    anchors_mod._write_bank_npz(_bank(KIND, OTHER), served_anchor_path(KIND))
    with caplog.at_level(logging.ERROR):
        assert av._get_bank(KIND) is None
    errors = [r.getMessage() for r in caplog.records if r.levelno >= logging.ERROR]
    assert errors, "banque servie périmée = panne MUETTE (D3)"
    assert any(OTHER in m and PROD in m for m in errors), errors


def test_d3_load_anchors_journalise_le_refus_inter_encodeurs(caplog):
    """Même silence côté `load_anchors` : le refus de servir un autre espace
    d'embedding est légitime, le faire sans un mot ne l'est pas."""
    anchors_mod._write_bank_npz(_bank(KIND, OTHER), served_anchor_path(KIND))
    with caplog.at_level(logging.ERROR):
        assert load_anchors(KIND, PROD) is None
    errors = [r.getMessage() for r in caplog.records if r.levelno >= logging.ERROR]
    assert errors, "refus inter-encodeurs muet (D3)"
    assert any(OTHER in m for m in errors), errors


def test_d3_pas_de_bruit_quand_tout_va_bien(av, caplog):
    """Contre-épreuve : le garde ne doit pas crier sur le cas nominal."""
    save_anchors(_bank(KIND, PROD, n=5), write_legacy=True)
    with caplog.at_level(logging.ERROR):
        assert av._get_bank(KIND).count == 5
    assert [r.getMessage() for r in caplog.records
            if r.levelno >= logging.ERROR] == []


# ---------------------------------------------------------------------------
# D10 — la banque servie ne s'écrit que sur intention explicite
# ---------------------------------------------------------------------------


def test_d10_save_anchors_n_ecrit_pas_la_banque_servie_par_defaut():
    scoped = save_anchors(_bank(KIND, PROD))
    assert scoped == anchor_path(KIND, PROD) and scoped.exists()
    assert not served_anchor_path(KIND).exists(), (
        "l'encodeur de production ne suffit pas à distinguer un rebuild de "
        "production d'un bras baseline de banc (D10)"
    )


def test_d10_rebuild_baseline_n_ecrase_pas_la_banque_servie(av):
    """LE test de D10, dans l'ordre de la repro : la banque servie à 9 ancres,
    puis un run de banc sur le MÊME encodeur avec 3 ancres."""
    save_anchors(_bank(KIND, PROD, n=9), write_legacy=True)
    save_anchors(_bank(KIND, PROD, n=3))          # bras baseline du banc

    served = load_anchors(KIND)
    assert served is not None and served.count == 9
    assert av._get_bank(KIND).count == 9, "la review sert le run de banc (D10)"
    assert anchor_path(KIND, PROD).exists()


def test_d10_un_run_de_banc_sur_l_encodeur_servi_le_dit(caplog):
    """Et il le dit : bâtir la banque de l'encodeur de production sans la
    servir est légitime, mais jamais silencieux."""
    with caplog.at_level(logging.WARNING):
        save_anchors(_bank(KIND, PROD, n=3))
    msgs = [r.getMessage() for r in caplog.records if r.levelno >= logging.WARNING]
    assert any("write_legacy=False" in m for m in msgs), msgs


def test_d10_remplacer_la_banque_servie_est_journalise(caplog):
    save_anchors(_bank(KIND, PROD, n=9), write_legacy=True)
    with caplog.at_level(logging.WARNING):
        save_anchors(_bank(KIND, PROD, n=3), write_legacy=True)
    msgs = [r.getMessage() for r in caplog.records if r.levelno >= logging.WARNING]
    assert any("SERVIE" in m and "9" in m and "3" in m for m in msgs), msgs
    assert load_anchors(KIND).count == 3   # remplacement demandé, remplacement fait


def test_d10_servir_un_encodeur_hors_production_reste_possible_mais_crie(caplog):
    with caplog.at_level(logging.WARNING):
        save_anchors(_bank(KIND, OTHER), write_legacy=True)
    assert served_anchor_path(KIND).exists()
    msgs = [r.getMessage() for r in caplog.records if r.levelno >= logging.WARNING]
    assert any(OTHER in m and PROD in m for m in msgs), msgs


def test_d10_les_builders_exposent_l_intention(monkeypatch):
    """Le drapeau doit traverser les builders, sinon aucun appelant ne peut le
    passer — c'était le constat de D10 (« write_legacy existe, personne ne le
    passe »)."""
    import inspect

    from training.foundation import anchors as A

    for fn in (A.build_anchors_2eur_all, A.build_anchors_2eur_commemo,
               A.build_anchors_2eur_standard, A.build_anchors_reverse_2eur):
        assert "write_legacy" in inspect.signature(fn).parameters, fn.__name__


# ---------------------------------------------------------------------------
# D11 — écriture atomique, et les deux fichiers d'un même save sont identiques
# ---------------------------------------------------------------------------


def test_d11_les_deux_fichiers_d_un_meme_save_partagent_leur_bank_id():
    save_anchors(_bank(KIND, PROD, n=6), write_legacy=True)
    a = load_anchors(KIND)
    b = load_anchors(KIND, PROD)
    assert a.bank_id and a.bank_id == b.bank_id
    np.testing.assert_array_equal(a.matrix, b.matrix)


def test_d11_ecriture_interrompue_laisse_la_banque_servie_intacte(_state_dir):
    """`np.savez` qui explose (disque plein, Ctrl-C) ne doit pas laisser un
    .npz tronqué à la place de la banque servie — et l'erreur doit REMONTER."""
    save_anchors(_bank(KIND, PROD, n=9), write_legacy=True)
    served = served_anchor_path(KIND)
    before = served.read_bytes()

    boom = _bank(KIND, PROD, n=2)
    real_savez = anchors_mod.np.savez

    def _explode(path, **kw):
        # On fait échouer la SECONDE écriture (celle de la banque servie ; son
        # nom ne porte pas le slug d'encodeur), pas la première. Ce que fait un
        # disque plein : le fichier cible existe déjà, tronqué, au moment où
        # l'exception part — et `np.load` refuse un zip tronqué, donc la review
        # ne redémarre plus.
        if "__" in Path(str(path)).name:
            return real_savez(path, **kw)
        Path(str(path)).write_bytes(b"PK\x03\x04tronque")
        raise OSError("no space left on device")

    anchors_mod.np.savez = _explode
    try:
        with pytest.raises(OSError):
            save_anchors(boom, write_legacy=True)
    finally:
        anchors_mod.np.savez = real_savez

    assert served.read_bytes() == before
    assert load_anchors(KIND).count == 9
    assert not list(_state_dir.glob(".*tmp.npz")), "temporaire non nettoyé"


# ---------------------------------------------------------------------------
# D13 — le CLI imprime les chemins réellement écrits
# ---------------------------------------------------------------------------


def test_d13_written_paths_annonce_la_banque_servie_inchangee():
    import scripts.build_dino_anchors as bda

    bank = _bank(KIND, PROD, n=3)
    save_anchors(bank)                       # --no-serve
    rows = dict(bda.written_paths(bank, serve=False))
    assert rows["Path"] == str(anchor_path(KIND, PROD))
    assert "NE CONTIENT PAS" in rows["Servie"]
    assert "--no-serve" in rows["Servie"]


def test_d13_written_paths_annonce_la_banque_servie_quand_elle_l_est():
    import scripts.build_dino_anchors as bda

    bank = _bank(KIND, PROD, n=3)
    save_anchors(bank, write_legacy=True)
    rows = dict(bda.written_paths(bank, serve=True))
    assert rows["Path"] == str(anchor_path(KIND, PROD))
    assert rows["Servie"] == str(served_anchor_path(KIND))
    assert "NE CONTIENT PAS" not in rows["Servie"]


def test_d13_written_paths_ne_ment_pas_sur_un_cache_hit():
    """Cache hit : le run n'a RIEN écrit. La ligne « Path: » ne doit pas
    désigner un artefact absent du disque — c'est le même mensonge que D13,
    une case plus loin (observé sur le vrai point d'entrée)."""
    import scripts.build_dino_anchors as bda

    bank = _bank(KIND, PROD, n=4)
    anchors_mod._write_bank_npz(bank, served_anchor_path(KIND))
    reread = load_anchors(KIND)
    rows = dict(bda.written_paths(reread, serve=True))
    assert not anchor_path(KIND, PROD).exists()
    assert "NE CONTIENT PAS" in rows["Path"] and "cache hit" in rows["Path"]
    assert rows["Servie"] == str(served_anchor_path(KIND))


def test_d13_plus_aucun_chemin_de_banque_code_en_dur_dans_le_cli():
    src = (Path(__file__).resolve().parents[1]
           / "scripts" / "build_dino_anchors.py").read_text()
    body = src.split('"""', 2)[-1]     # hors docstring de module
    assert "f'foundation_anchors_{" not in body
    assert 'f"foundation_anchors_{' not in body


def test_d13_l_aide_db_ne_promet_plus_eurio_db():
    """L'aide annonçait « default: ml/state/eurio.db » — un défaut corrigé en
    `resolve_db_path` le même jour. Un opérateur qui lit l'aide doit apprendre
    quelle base sera réellement lue."""
    import scripts.build_dino_anchors as bda

    action = [a for a in bda.build_parser()._actions
              if "--db" in a.option_strings][0]
    assert "resolve_db_path" in action.help
    assert "EURIO_DB_PATH" in action.help
    assert "default: ml/state/eurio.db" not in action.help


def test_d13_le_cli_expose_no_serve():
    import scripts.build_dino_anchors as bda

    assert bda.build_parser().parse_args([]).serve is True
    assert bda.build_parser().parse_args(["--no-serve"]).serve is False


# ---------------------------------------------------------------------------
# Garde-fou : la review qui tourne EN CE MOMENT n'est pas touchée
# ---------------------------------------------------------------------------


def test_les_banques_servies_reelles_restent_lisibles_et_intactes(monkeypatch):
    """Aucun correctif de ce lot ne doit rendre la review aveugle ni modifier
    `ml/state/foundation_anchors_*.npz`. On relit les vraies banques (STATE_DIR
    remis à sa valeur réelle) et on compare les mtimes avant/après."""
    from sources._base.steps import auto_validate as _av

    real_state = Path(anchors_mod.ML_DIR) / "state"
    monkeypatch.setattr(anchors_mod, "STATE_DIR", real_state)
    banks = sorted(real_state.glob("foundation_anchors_*.npz"))
    if not banks:
        pytest.skip("aucune banque servie sur cette machine")
    before = {p: p.stat().st_mtime_ns for p in banks}

    _av._bank_cache.clear()
    try:
        for p in banks:
            if "__" in p.name:
                continue                       # artefact de banc, pas la servie
            kind = p.name[len("foundation_anchors_"):-len(".npz")]
            bank = load_anchors(kind)
            assert bank is not None and bank.count > 0, kind
            assert _av._get_bank(kind) is not None, (
                f"la review deviendrait aveugle sur {kind}"
            )
    finally:
        _av._bank_cache.clear()

    assert {p: p.stat().st_mtime_ns for p in banks} == before
