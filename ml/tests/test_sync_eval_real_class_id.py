"""Le corpus d'évaluation doit être rangé par CLASSE, et ne rien écraser.

Chaque test ici garde un défaut SILENCIEUX déjà payé, mesuré le 2026-08-25 :

- ``sync()`` — le chemin appelé par ``POST /lab/cohorts/{id}/captures/sync`` —
  écrivait ``output / eurio_id`` sans jamais consulter de table de classes,
  alors que ``main()`` résolvait bien la classe. Deux boucles, chacune la
  moitié du contrat. Résultat : **7 dossiers sur 19** du corpus nommés par
  membre au lieu de leur groupe de dessin, et toute lecture naïve comptant des
  classes fantômes. Rien n'a jamais levé.
- Le ``class_manifest.json`` par défaut date du 5 mai et ne couvre que **5 des
  17 classes** du pull de juin — dont **aucun** des 5 membres qui ont
  justement besoin d'être traduits. Réparer le câblage sans changer la source
  aurait laissé le prédicat faux : c'est le motif « le garde qui ne garde
  pas », huitième instance.
- Les pulls d'avril et de juin partagent deux noms d'étape (``bright_plain``,
  ``bright_textured``). Cumuler sans préfixe de protocole écrase les photos
  d'avril **en silence** — une perte de données irréversible sur un corpus qui
  n'a aucune réplique.
"""

from __future__ import annotations

import numpy as np
import pytest

from training.eval.real_photo_meta import parse_filename
from vision import sync_eval_real


def _ecrire_pull(racine, arbre: dict[str, list[str]]):
    """Fabrique <racine>/eval_real/<eurio_id>/<step>_raw.jpg."""
    import cv2

    for eurio_id, steps in arbre.items():
        d = racine / "eval_real" / eurio_id
        d.mkdir(parents=True, exist_ok=True)
        for step in steps:
            img = np.full((480, 480, 3), 200, dtype=np.uint8)
            cv2.circle(img, (240, 240), 150, (90, 90, 90), -1)
            cv2.imwrite(str(d / f"{step}_raw.jpg"), img)
    return racine


@pytest.fixture
def _normalisation_triviale(monkeypatch):
    """Neutralise la normalisation Hough : ces tests portent sur le RANGEMENT."""
    class _Res:
        image = np.zeros((224, 224, 3), dtype=np.uint8)

    monkeypatch.setattr(sync_eval_real, "normalize_device_path", lambda _p: _Res())


def test_sync_range_par_classe_pas_par_membre(tmp_path, monkeypatch, _normalisation_triviale):
    """Un MEMBRE d'un groupe de dessin atterrit dans le dossier du GROUPE.

    Mutation qui doit faire rougir : rétablir ``out_dir = output / eurio_id``
    dans ``sync()``.
    """
    monkeypatch.setattr(
        sync_eval_real,
        "_catalogue_eurio_to_class",
        lambda: {"fr-1999-2eur-standard-1st-map": "fr-2euro-standard-t1"},
    )
    pull = _ecrire_pull(tmp_path / "pull", {"fr-1999-2eur-standard-1st-map": ["bright_plain"]})
    out = tmp_path / "out"

    rapport = sync_eval_real.sync(pull, output=out, manifest=tmp_path / "absent.json")

    assert rapport.normalized == 1
    assert (out / "fr-2euro-standard-t1").is_dir()
    assert not (out / "fr-1999-2eur-standard-1st-map").exists()


def test_sync_utilise_le_catalogue_quand_le_manifeste_ignore_la_piece(
    tmp_path, monkeypatch, _normalisation_triviale
):
    """Le manifeste périmé ne doit pas dicter le rangement.

    C'est le cœur du défaut : brancher ``sync()`` sur le manifeste seul aurait
    laissé les 12 classes qu'il ignore rangées par membre.
    """
    monkeypatch.setattr(
        sync_eval_real,
        "_catalogue_eurio_to_class",
        lambda: {"ad-2014-2eur-standard-1st-type": "ad-2euro-standard-t1"},
    )
    manifeste = tmp_path / "class_manifest.json"
    manifeste.write_text('{"classes": [{"class_id": "autre", "eurio_ids": ["sans-rapport"]}]}')
    pull = _ecrire_pull(tmp_path / "pull", {"ad-2014-2eur-standard-1st-type": ["dim"]})
    out = tmp_path / "out"

    rapport = sync_eval_real.sync(pull, output=out, manifest=manifeste)

    assert (out / "ad-2euro-standard-t1" / "dim.jpg").exists()
    assert rapport.unmapped_to_class == []


def test_le_protocole_evite_l_ecrasement_entre_deux_pulls(
    tmp_path, monkeypatch, _normalisation_triviale
):
    """Deux pulls partageant un nom d'étape coexistent — et sans protocole, non.

    ``bright_plain`` existe dans le pull d'avril ET dans celui de juin. C'est
    la collision réelle, pas un cas d'école.
    """
    monkeypatch.setattr(sync_eval_real, "_catalogue_eurio_to_class", lambda: {})
    out = tmp_path / "out"
    avril = _ecrire_pull(tmp_path / "avril", {"fr-2018-2eur-simone-veil": ["bright_plain"]})
    juin = _ecrire_pull(tmp_path / "juin", {"fr-2018-2eur-simone-veil": ["bright_plain"]})
    absent = tmp_path / "absent.json"

    r1 = sync_eval_real.sync(avril, output=out, manifest=absent, protocol="proto-2026-04")
    r2 = sync_eval_real.sync(juin, output=out, manifest=absent, protocol="proto-2026-06")

    d = out / "fr-2018-2eur-simone-veil"
    assert (d / "proto-2026-04_bright_plain.jpg").exists()
    assert (d / "proto-2026-06_bright_plain.jpg").exists()
    assert r1.overwritten == [] and r2.overwritten == []

    # …et la preuve par l'absurde : sans protocole, le second écrase le premier
    # et le rapport le DIT au lieu de le taire.
    r3 = sync_eval_real.sync(avril, output=out, manifest=absent)
    r4 = sync_eval_real.sync(juin, output=out, manifest=absent)
    assert r3.overwritten == []
    assert r4.overwritten == ["fr-2018-2eur-simone-veil/bright_plain.jpg"]


def test_les_eurio_id_inconnus_du_catalogue_sont_comptes(
    tmp_path, monkeypatch, _normalisation_triviale
):
    """Le repli sur l'eurio_id brut reste permis, mais il se COMPTE.

    C'est ce repli, muet jusqu'ici, qui fabriquait les classes fantômes.
    """
    monkeypatch.setattr(sync_eval_real, "_catalogue_eurio_to_class", lambda: {})
    pull = _ecrire_pull(tmp_path / "pull", {"piece-inconnue": ["dim"]})

    rapport = sync_eval_real.sync(
        pull, output=tmp_path / "out", manifest=tmp_path / "absent.json"
    )

    assert rapport.unmapped_to_class == ["piece-inconnue"]
    assert "unmapped_to_class" in rapport.to_dict()


@pytest.mark.parametrize(
    "stem, attendu",
    [
        # Convention device — AUCUN de ces axes n'était lisible avant le
        # 2026-08-25 : parse_filename rendait None partout pour 9 des 11 noms
        # d'étape réels, donc la ventilation per_condition du benchmark était
        # vide. On photographiait sous trois éclairages sans pouvoir noter par
        # éclairage.
        ("proto-2026-04_bright_plain", {"lighting": "bright", "background": "plain",
                                        "protocol": "proto-2026-04"}),
        ("proto-2026-06_oblique_p2", {"angle": "oblique", "position": "p2",
                                      "protocol": "proto-2026-06"}),
        ("proto-2026-06_glare_specular_p3", {"lighting": "glare", "state": "specular",
                                             "position": "p3",
                                             "protocol": "proto-2026-06"}),
        ("proto-2026-04_tilt_plain", {"angle": "tilt", "background": "plain",
                                      "protocol": "proto-2026-04"}),
        # Convention legacy real-photos — NON RÉGRESSION, elle doit parser
        # exactement comme avant l'ajout du vocabulaire device.
        ("natural-direct_wood_15deg_close_clean",
         {"lighting": "natural-direct", "background": "wood", "angle": "15deg",
          "distance": "close", "state": "clean"}),
    ],
)
def test_le_vocabulaire_device_est_lisible(stem, attendu):
    obtenu = {k: v for k, v in parse_filename(stem).to_dict().items() if v}
    assert obtenu == attendu
