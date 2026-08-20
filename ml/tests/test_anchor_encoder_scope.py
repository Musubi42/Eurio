"""P6-1/P6-2 — la banque d'ancres est scopée par encodeur.

Avant ce chantier, `anchor_path(kind)` ne portait que le kind : bencher un
second encodeur sur `2eur_all` écrasait la banque que la review sert en
production, sans le moindre message. Ces tests verrouillent les trois
propriétés qui lèvent le piège :

1. deux encodeurs COEXISTENT sur le même kind (fichiers distincts) ;
2. les appelants historiques (`load_anchors(kind)`) lisent le même fichier
   qu'avant — le legacy est encore écrit pour l'encodeur de production ;
3. `_get_bank` cache par COUPLE (kind, encodeur) et la review, elle, voit
   toujours sa banque.

⚠️ Depuis D10 (2026-08-19), `save_anchors` n'écrit PLUS la banque servie par
déduction : `dinov2-vitl14` est à la fois l'encodeur servi et le bras baseline
du banc, donc « c'est l'encodeur de production » ne dit pas « c'est le rebuild
de production ». L'intention passe par `write_legacy=True`, que seul
`scripts/build_dino_anchors.py` passe. Cf. `tests/test_anchor_bank_serving.py`.

Aucun test n'écrit dans `ml/state/` : `STATE_DIR` est redirigé sur `tmp_path`.
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
    adopt_legacy_bank,
    anchor_path,
    encoder_slug,
    encoder_version_for_kind,
    legacy_anchor_path,
    load_anchors,
    save_anchors,
)

DINOV3_SPEC = "timm:vit_small_patch16_dinov3.lvd1689m"


@pytest.fixture(autouse=True)
def _state_dir(tmp_path, monkeypatch):
    """Personne n'écrit dans ml/state/ pendant les tests."""
    monkeypatch.setattr(anchors_mod, "STATE_DIR", tmp_path)
    return tmp_path


def _bank(kind: str, encoder_version: str, *, dim: int = 8, n: int = 3) -> AnchorBank:
    rng = np.random.default_rng(abs(hash(encoder_version)) % (2**32))
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
# 1. encoder_slug
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("spec", "expected"),
    [
        ("dinov2-vits14", "dinov2-vits14"),
        ("dinov2-vitl14", "dinov2-vitl14"),
        (DINOV3_SPEC, "timm-vit_small_patch16_dinov3.lvd1689m"),
        ("timm:convnext_tiny.dinov3_lvd1689m", "timm-convnext_tiny.dinov3_lvd1689m"),
        ("DINOv2-ViTL14", "dinov2-vitl14"),
        ("  spaced name  ", "spaced-name"),
    ],
)
def test_encoder_slug_table(spec, expected):
    assert encoder_slug(spec) == expected


def test_encoder_slug_is_filename_safe():
    for spec in ("timm:a/b\\c", "x y:z"):
        slug = encoder_slug(spec)
        assert "/" not in slug and "\\" not in slug and ":" not in slug
        assert slug == Path(slug).name


def test_encoder_slug_injectif_sur_les_specs_manipulees():
    specs = [
        "dinov2-vits14",
        "dinov2-vitl14",
        DINOV3_SPEC,
        "timm:convnext_tiny.dinov3_lvd1689m",
    ]
    slugs = [encoder_slug(s) for s in specs]
    assert len(set(slugs)) == len(specs)


# ---------------------------------------------------------------------------
# 2. anchor_path / save_anchors
# ---------------------------------------------------------------------------


def test_anchor_path_sans_encodeur_reste_le_chemin_legacy(_state_dir):
    assert anchor_path("2eur_all") == _state_dir / "foundation_anchors_2eur_all.npz"
    assert anchor_path("2eur_all") == legacy_anchor_path("2eur_all")


def test_anchor_path_scope_porte_le_slug(_state_dir):
    assert anchor_path("2eur_all", DINOV3_SPEC) == (
        _state_dir
        / "foundation_anchors_2eur_all__timm-vit_small_patch16_dinov3.lvd1689m.npz"
    )


def test_save_encodeur_de_production_ecrit_scope_ET_legacy(_state_dir):
    """Le rebuild de production (write_legacy=True) écrit les DEUX fichiers.
    Sans le drapeau, seul l'artefact de banc est écrit — cf. D10."""
    prod = encoder_version_for_kind(SUGGESTIONS_ANCHORS_KIND)
    scoped = save_anchors(_bank(SUGGESTIONS_ANCHORS_KIND, prod), write_legacy=True)
    assert scoped == anchor_path(SUGGESTIONS_ANCHORS_KIND, prod)
    assert scoped.exists()
    assert legacy_anchor_path(SUGGESTIONS_ANCHORS_KIND).exists()


def test_save_autre_encodeur_n_ecrit_que_le_scope(_state_dir):
    scoped = save_anchors(_bank(SUGGESTIONS_ANCHORS_KIND, DINOV3_SPEC))
    assert scoped.exists()
    assert not legacy_anchor_path(SUGGESTIONS_ANCHORS_KIND).exists()


def test_save_write_legacy_force(_state_dir):
    save_anchors(_bank(SUGGESTIONS_ANCHORS_KIND, DINOV3_SPEC), write_legacy=True)
    assert legacy_anchor_path(SUGGESTIONS_ANCHORS_KIND).exists()


def test_save_write_legacy_false_sur_encodeur_de_prod(_state_dir):
    prod = encoder_version_for_kind(SUGGESTIONS_ANCHORS_KIND)
    save_anchors(_bank(SUGGESTIONS_ANCHORS_KIND, prod), write_legacy=False)
    assert not legacy_anchor_path(SUGGESTIONS_ANCHORS_KIND).exists()


# ---------------------------------------------------------------------------
# 3. LE test P6-1 : deux encodeurs coexistent sur le même kind
# ---------------------------------------------------------------------------


def test_deux_encodeurs_coexistent_sur_le_meme_kind(_state_dir):
    """Sauver l'un puis l'autre : aucun n'écrase l'autre, dim et encodeur
    restent distincts à la relecture. C'est la levée de P6-1."""
    kind = SUGGESTIONS_ANCHORS_KIND
    prod = encoder_version_for_kind(kind)
    p_prod = save_anchors(_bank(kind, prod, dim=1024, n=4), write_legacy=True)
    p_v3 = save_anchors(_bank(kind, DINOV3_SPEC, dim=384, n=3))
    assert p_prod != p_v3
    assert p_prod.exists() and p_v3.exists()

    a = load_anchors(kind, prod)
    b = load_anchors(kind, DINOV3_SPEC)
    assert a is not None and b is not None
    assert (a.dim, a.count, a.encoder_version) == (1024, 4, prod)
    assert (b.dim, b.count, b.encoder_version) == (384, 3, DINOV3_SPEC)

    # ... et la banque servie (lecture legacy sans encodeur) est bien celle de
    # production, pas celle du benchmark : la review ne devient pas aveugle.
    served = load_anchors(kind)
    assert served is not None
    assert served.encoder_version == prod
    assert served.dim == 1024


# ---------------------------------------------------------------------------
# 4. load_anchors — compat et refus inter-encodeurs
# ---------------------------------------------------------------------------


def test_load_sans_encodeur_lit_le_legacy_seul(_state_dir):
    """Un tmpdir ne contenant QUE le legacy : comportement d'avant, inchangé."""
    bank = _bank("2eur_commemo", "dinov2-vits14")
    anchors_mod._write_bank_npz(bank, legacy_anchor_path("2eur_commemo"))
    loaded = load_anchors("2eur_commemo")
    assert loaded is not None
    assert loaded.eurio_ids == bank.eurio_ids
    np.testing.assert_array_almost_equal(loaded.matrix, bank.matrix)


def test_load_avec_encodeur_retombe_sur_le_legacy_si_meme_encodeur(_state_dir):
    bank = _bank("2eur_commemo", "dinov2-vits14")
    anchors_mod._write_bank_npz(bank, legacy_anchor_path("2eur_commemo"))
    assert not anchor_path("2eur_commemo", "dinov2-vits14").exists()
    loaded = load_anchors("2eur_commemo", "dinov2-vits14")
    assert loaded is not None and loaded.encoder_version == "dinov2-vits14"


def test_load_avec_autre_encodeur_ne_rend_pas_le_legacy(_state_dir):
    """Un legacy vits14 ne doit JAMAIS être servi à qui demande du DINOv3 :
    ce serait comparer des cosinus entre deux espaces différents."""
    anchors_mod._write_bank_npz(
        _bank("2eur_commemo", "dinov2-vits14"), legacy_anchor_path("2eur_commemo")
    )
    assert load_anchors("2eur_commemo", DINOV3_SPEC) is None


def test_load_absent_rend_none(_state_dir):
    assert load_anchors("inexistant") is None
    assert load_anchors("inexistant", DINOV3_SPEC) is None


# ---------------------------------------------------------------------------
# 5. adopt_legacy_bank
# ---------------------------------------------------------------------------


def test_adopt_legacy_bank_copie_sans_supprimer(_state_dir):
    legacy = legacy_anchor_path("2eur_all")
    anchors_mod._write_bank_npz(_bank("2eur_all", "dinov2-vitl14"), legacy)
    scoped = adopt_legacy_bank("2eur_all")
    assert scoped == anchor_path("2eur_all", "dinov2-vitl14")
    assert scoped.exists()
    assert legacy.exists()  # jamais supprimé
    adopted = load_anchors("2eur_all", "dinov2-vitl14")
    assert adopted is not None and adopted.encoder_version == "dinov2-vitl14"


def test_adopt_legacy_bank_idempotente(_state_dir):
    legacy = legacy_anchor_path("2eur_all")
    anchors_mod._write_bank_npz(_bank("2eur_all", "dinov2-vitl14"), legacy)
    first = adopt_legacy_bank("2eur_all")
    mtime = first.stat().st_mtime_ns
    second = adopt_legacy_bank("2eur_all")
    assert second == first
    assert first.stat().st_mtime_ns == mtime  # pas de réécriture


def test_adopt_legacy_bank_dry_run_n_ecrit_rien(_state_dir):
    anchors_mod._write_bank_npz(
        _bank("2eur_all", "dinov2-vitl14"), legacy_anchor_path("2eur_all")
    )
    target = adopt_legacy_bank("2eur_all", dry_run=True)
    assert target == anchor_path("2eur_all", "dinov2-vitl14")
    assert not target.exists()


def test_adopt_legacy_bank_sans_legacy_rend_none(_state_dir):
    assert adopt_legacy_bank("2eur_all") is None


# ---------------------------------------------------------------------------
# 6. _get_bank — cache par couple, review non aveugle, garde-fou stale
# ---------------------------------------------------------------------------


@pytest.fixture()
def _clean_bank_cache():
    from sources._base.steps import auto_validate as av

    av._bank_cache.clear()
    yield av
    av._bank_cache.clear()


def test_get_bank_defaut_sert_la_banque_de_production(_state_dir, _clean_bank_cache):
    """La review appelle `_get_bank(kind)` sans encodeur : elle doit continuer
    de voir sa banque, même quand une banque de benchmark est sur disque."""
    av = _clean_bank_cache
    kind = SUGGESTIONS_ANCHORS_KIND
    prod = encoder_version_for_kind(kind)
    save_anchors(_bank(kind, prod, dim=1024, n=5), write_legacy=True)
    save_anchors(_bank(kind, DINOV3_SPEC, dim=384, n=2))

    served = av._get_bank(kind)
    assert served is not None
    assert served.encoder_version == prod
    assert (served.dim, served.count) == (1024, 5)


def test_get_bank_cache_par_couple(_state_dir, _clean_bank_cache):
    av = _clean_bank_cache
    kind = SUGGESTIONS_ANCHORS_KIND
    prod = encoder_version_for_kind(kind)
    save_anchors(_bank(kind, prod, dim=1024, n=5), write_legacy=True)
    save_anchors(_bank(kind, DINOV3_SPEC, dim=384, n=2))

    a1 = av._get_bank(kind, prod)
    b1 = av._get_bank(kind, DINOV3_SPEC)
    assert a1 is not b1                       # pas le même objet
    assert a1.dim == 1024 and b1.dim == 384   # pas la même banque
    assert av._get_bank(kind, prod) is a1     # cache effectif
    assert av._get_bank(kind, DINOV3_SPEC) is b1
    assert set(av._bank_cache) == {(kind, prod), (kind, DINOV3_SPEC)}


def test_get_bank_banque_qui_ment_sur_son_meta_est_traitee_absente(
    _state_dir, _clean_bank_cache, caplog
):
    """Garde-fou stale : une banque SERVIE qui n'est pas celle de l'encodeur de
    production est traitée comme absente, et ça se voit dans les logs (D3).
    Depuis D10, `_get_bank(kind)` lit la banque servie — c'est donc elle qu'on
    empoisonne ici (avant, il fallait mentir dans le meta du fichier scopé)."""
    av = _clean_bank_cache
    kind = SUGGESTIONS_ANCHORS_KIND
    anchors_mod._write_bank_npz(_bank(kind, "dinov2-vits14"), legacy_anchor_path(kind))
    with caplog.at_level(logging.ERROR):
        assert av._get_bank(kind) is None
    assert any(r.levelno == logging.ERROR for r in caplog.records)
    assert av._bank_cache == {}
