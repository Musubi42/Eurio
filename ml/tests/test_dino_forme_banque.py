"""La FORME d'une banque d'ancres, et le fait qu'un rebuild la dise.

Ces tests existent à cause d'un silence réel : le 2026-08-20 le plancher
``min_exemplars=2`` a été retiré du code alors que la banque servie le portait
encore. Le rebuild du 2026-08-24 a rendu son exemplaire à 55 classes, et rien
ne l'a signalé — le garde P1 compte les classes à ``>= 2`` exemplaires, un
compte que ce retour laisse exactement invariant.
"""

from __future__ import annotations

import sqlite3

import pytest

from store.dino_references import (
    DinoRefRow,
    delta_de_forme,
    forme_servie,
    histogramme_exemplaires,
)


def _row(class_id: str, method: str, asset_id: str | None = None) -> DinoRefRow:
    return DinoRefRow(class_id, f"{class_id}-eid", asset_id, method)


class TestHistogramme:
    def test_une_classe_au_canonique_seul_compte_zero(self) -> None:
        assert histogramme_exemplaires([_row("a", "canonical")]) == {0: 1}

    def test_les_manual_ne_sont_pas_des_exemplaires_fps(self) -> None:
        rows = [_row("a", "canonical"), _row("a", "manual_pin", "x")]
        assert histogramme_exemplaires(rows) == {0: 1}

    def test_paliers(self) -> None:
        rows = [
            _row("a", "canonical"),
            _row("b", "canonical"), _row("b", "fps", "1"),
            _row("c", "canonical"), _row("c", "fps", "2"), _row("c", "fps", "3"),
            _row("d", "canonical"), _row("d", "fps", "4"), _row("d", "fps", "5"),
        ]
        assert histogramme_exemplaires(rows) == {0: 1, 1: 1, 2: 2}


class TestDelta:
    def test_premiere_banque_ne_compare_rien(self) -> None:
        assert delta_de_forme({}, {0: 10}) is None

    def test_forme_identique_ne_dit_rien(self) -> None:
        assert delta_de_forme({0: 5, 2: 3}, {0: 5, 2: 3}) is None

    def test_le_cas_reel_du_plancher_retire(self) -> None:
        """55 classes passent de 0 à 1 exemplaire. P1 (>= 2) ne bouge pas."""
        avant = {0: 402 + 55, 2: 38, 10: 73}
        apres = {0: 402, 1: 55, 2: 38, 10: 73}
        msg = delta_de_forme(avant, apres)
        assert msg is not None, "le retour du plancher doit être DIT"
        assert "1 exemplaire: 0→55" in msg
        assert "0 exemplaires: 457→402" in msg
        # Le compte P1 (classes à >= 2) est identique de part et d'autre :
        # c'est bien pour ça qu'il ne peut pas servir de garde ici.
        p1 = lambda h: sum(v for k, v in h.items() if k >= 2)  # noqa: E731
        assert p1(avant) == p1(apres)

    def test_un_palier_qui_disparait_est_dit(self) -> None:
        msg = delta_de_forme({3: 7}, {})
        assert msg is not None and "3 exemplaires: 7→0" in msg

    def test_singulier_et_pluriel(self) -> None:
        msg = delta_de_forme({1: 1}, {1: 2})
        assert "1 exemplaire:" in msg and "1 exemplaires:" not in msg


class TestFormeServie:
    @pytest.fixture()
    def conn(self) -> sqlite3.Connection:
        c = sqlite3.connect(":memory:")
        c.execute(
            "CREATE TABLE dino_class_references ("
            " anchors_kind TEXT, encoder_version TEXT, class_id TEXT,"
            " eurio_id TEXT, asset_id TEXT, method TEXT)"
        )
        return c

    def _ins(self, c, kind, enc, cid, method, aid=None):
        c.execute(
            "INSERT INTO dino_class_references VALUES (?,?,?,?,?,?)",
            (kind, enc, cid, f"{cid}-eid", aid, method),
        )

    def test_lit_la_banque_en_base(self, conn) -> None:
        self._ins(conn, "2eur_all", "v1", "a", "canonical")
        self._ins(conn, "2eur_all", "v1", "b", "canonical")
        self._ins(conn, "2eur_all", "v1", "b", "fps", "1")
        assert forme_servie(conn, "2eur_all", "v1") == {0: 1, 1: 1}

    def test_ignore_l_autre_encodeur(self, conn) -> None:
        """Sans ce scope, bencher un candidat ferait croire à un changement."""
        self._ins(conn, "2eur_all", "v1", "a", "canonical")
        self._ins(conn, "2eur_all", "AUTRE", "z", "fps", "9")
        self._ins(conn, "2eur_all", "AUTRE", "z", "fps", "8")
        assert forme_servie(conn, "2eur_all", "v1") == {0: 1}

    def test_inclut_les_manual_a_encodeur_vide(self, conn) -> None:
        """Un pin humain porte ``encoder_version = ''`` — il fait partie de la
        banque servie et ne doit pas passer pour une classe absente."""
        self._ins(conn, "2eur_all", "", "a", "manual_pin", "1")
        assert forme_servie(conn, "2eur_all", "v1") == {0: 1}

    def test_ignore_l_autre_kind(self, conn) -> None:
        self._ins(conn, "reverse_2eur", "v1", "r", "fps", "1")
        assert forme_servie(conn, "2eur_all", "v1") == {}


class TestOrdreDeLecture:
    """L'ORDRE est le piège, pas le prédicat.

    ``forme_servie`` doit être lue AVANT ``replace_auto_references``. Lue
    après, elle rend la forme NEUVE : le delta est alors vide, le garde se tait,
    et on retombe exactement dans le silence qu'il devait rompre. Ce test fixe
    l'ordre comme un fait exécutable plutôt que comme un commentaire.
    """

    def test_lue_apres_la_reecriture_la_forme_est_la_neuve(self) -> None:
        from store.dino_references import replace_auto_references

        conn = sqlite3.connect(":memory:")
        conn.execute(
            "CREATE TABLE dino_class_references ("
            " anchors_kind TEXT, encoder_version TEXT NOT NULL, class_id TEXT,"
            " eurio_id TEXT, asset_id TEXT, method TEXT, rank INTEGER,"
            " selected_sim REAL, source_path TEXT, build_id TEXT,"
            " PRIMARY KEY (anchors_kind, encoder_version, class_id, eurio_id, asset_id))"
        )
        # Banque servie : « a » a deux exemplaires.
        for aid in ("1", "2"):
            conn.execute(
                "INSERT INTO dino_class_references"
                " (anchors_kind, encoder_version, class_id, eurio_id, asset_id, method)"
                " VALUES ('2eur_all', 'v1', 'a', 'a-eid', ?, 'fps')",
                (aid,),
            )
        avant = forme_servie(conn, "2eur_all", "v1")
        assert avant == {2: 1}

        # Le rebuild n'en garde qu'un : un vrai changement de forme.
        neuves = [_row("a", "canonical"), _row("a", "fps", "1")]
        replace_auto_references(conn, "2eur_all", neuves, encoder_version="v1")

        apres_lecture_tardive = forme_servie(conn, "2eur_all", "v1")
        assert apres_lecture_tardive == {1: 1}

        # Lu au bon moment, le garde parle. Lu trop tard, il se tait.
        assert delta_de_forme(avant, histogramme_exemplaires(neuves)) is not None
        assert delta_de_forme(
            apres_lecture_tardive, histogramme_exemplaires(neuves)
        ) is None
