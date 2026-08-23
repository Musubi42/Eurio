"""Le besoin par classe — `shared/class_need` (O1), les invariants en miniature.

Ce qui est verrouillé, et pourquoi chaque point a coûté quelque chose :

1. **La maille banque.** Un membre non-représentant d'une ère courante et son
   représentant rendent le MÊME `ClassNeed` — la traduction passe par
   `bank_classes`. Mutation attendue : remplacer `bank_class_ids` par
   l'identifiant brut doit faire rougir `test_le_membre_et_le_representant…`.
2. **L'émission commune reste 3 classes**, pas une, chacune avec la cible 5 (D4).
3. **Le verdict**, dans l'ordre : `pleine` (have ≥ target, D2) → `review`
   (pending_scoped > 0) → `scrape`.
4. **`pending` lit `status = 'open'` exactement**, et le couple
   `(anchors_kind, encoder_version)` : une prédiction d'une autre banque ne
   compte pas.
5. **La voie A est affichée, jamais dans le verdict** : ses quatre conditions
   sont celles du bake.
6. `cap` vaut `DEFAULT_EXEMPLARS_PER_CLASS` — la constante est recopiée (torch),
   l'égalité est verrouillée ici.
7. Le module n'écrit rien.
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

ML_DIR = Path(__file__).parent.parent
if str(ML_DIR) not in sys.path:
    sys.path.insert(0, str(ML_DIR))

import pytest

from shared import class_need as cn
from shared.class_need import ClassNeed, all_needs, bottleneck_for, need_for
from store import Store

KIND = "2eur_all"
ENC = "dinov2-vitl14"
EC = ("cy", "fr", "de")


def _coin(conn, eid, country, year, *, commemo, dgid=None, face=2.0):
    conn.execute(
        "INSERT INTO coins (eurio_id, country, country_name, year, face_value,"
        " is_commemorative, design_group_id, theme) VALUES (?,?,?,?,?,?,?,?)",
        (eid, country, country, year, face, int(commemo), dgid, "thème"),
    )


@pytest.fixture()
def conn(tmp_path):
    c = Store(tmp_path / "t.db")._connection()  # noqa: SLF001
    for gid, des in (
        ("eu-euro-cash-2012", "Joint issue — 10 ans"),
        ("it-2euro-standard-t1", "IT 2€ standard (1er type)"),
    ):
        c.execute("INSERT INTO design_groups (id, designation) VALUES (?, ?)", (gid, des))
    for cc in EC:
        _coin(c, f"{cc}-2012-ec", cc.upper(), 2012, commemo=True, dgid="eu-euro-cash-2012")
    _coin(c, "it-2002-std", "IT", 2002, commemo=False, dgid="it-2euro-standard-t1")
    _coin(c, "it-2008-std", "IT", 2008, commemo=False, dgid="it-2euro-standard-t1")
    _coin(c, "fr-2016-commemo", "FR", 2016, commemo=True)
    _coin(c, "lu-2019-commemo", "LU", 2019, commemo=True)
    c.commit()
    return c


def _bank(conn, class_id, n_fps, *, eurio_id=None, kind=KIND, enc=ENC, canonical=True):
    """Une classe de banque avec son canonique et `n_fps` exemplaires.

    `canonical=False` pour AJOUTER des exemplaires à une classe déjà posée :
    le canonique est unique par classe (index `idx_dino_class_refs_canonical`).
    """
    if canonical:
        conn.execute(
            "INSERT INTO dino_class_references (anchors_kind, encoder_version, class_id,"
            " eurio_id, method) VALUES (?,?,?,?,'canonical')",
            (kind, enc, class_id, eurio_id or class_id),
        )
    for i in range(n_fps):
        aid = _asset(conn, f"ref-{eurio_id or class_id}-{i}")
        conn.execute(
            "INSERT INTO dino_class_references (anchors_kind, encoder_version, class_id,"
            " eurio_id, asset_id, method, rank) VALUES (?,?,?,?,?,'fps',?)",
            (kind, enc, class_id, eurio_id or class_id, aid, i),
        )
    conn.commit()


def _asset(conn, ref, *, source="ebay", eurio_id=None, eligible=0, storage="present", face=None):
    conn.execute(
        "INSERT OR IGNORE INTO source_images (id, source, source_ref, storage_path) "
        "VALUES (?,?,?,'x.jpg')",
        (f"si-{ref}", source, f"r-{ref}"),
    )
    conn.execute(
        "INSERT INTO image_assets (id, source_image_id, storage_path, storage_status,"
        " eurio_id, training_eligible, face) VALUES (?,?,?,?,?,?,?)",
        (f"a-{ref}", f"si-{ref}", "c.jpg", storage, eurio_id, eligible, face),
    )
    return f"a-{ref}"


def _open(conn, ref, top1, *, status="open", spread=0.08, country_spread=None,
          kind=KIND, enc=ENC):
    """Un crop en file, avec sa prédiction pointant `top1`."""
    aid = _asset(conn, ref)
    conn.execute(
        "INSERT INTO review_queue (id, image_asset_id, status) VALUES (?,?,?)",
        (f"rq-{ref}", aid, status),
    )
    conn.execute(
        "INSERT INTO image_asset_dino_predictions (asset_id, encoder_version, anchors_kind,"
        " anchors_count, top_k_json, top1_eurio_id, top1_sim, spread, country_spread)"
        " VALUES (?,?,?,?,?,?,?,?,?)",
        (aid, enc, kind, 10, json.dumps([{"eurio_id": top1, "sim": 0.8}]), top1, 0.8,
         spread, country_spread),
    )
    conn.commit()


def _by_id(needs) -> dict[str, ClassNeed]:
    return {n.class_id: n for n in needs}


# ── La maille ────────────────────────────────────────────────────────────────


def test_le_membre_et_le_representant_rendent_le_meme_besoin(conn):
    # La banque indexe l'ère sous 2002 ; 2008 n'y a pas de ligne. Demander le
    # besoin par 2008 doit tomber sur la classe de 2002, pas sur rien.
    _bank(conn, "it-2002-std", 3)
    _open(conn, "p1", "it-2002-std")
    a = need_for(conn, "it-2008-std", anchors_kind=KIND, encoder_version=ENC)
    b = need_for(conn, "it-2002-std", anchors_kind=KIND, encoder_version=ENC)
    assert a is not None
    assert a == b
    assert a.class_id == "it-2002-std"
    assert (a.have, a.pending, a.bottleneck) == (3, 1, "review")


def test_une_piece_hors_banque_rend_none(conn):
    _bank(conn, "fr-2016-commemo", 2)
    assert need_for(conn, "lu-2019-commemo", anchors_kind=KIND, encoder_version=ENC) is None


def test_une_emission_commune_donne_une_classe_par_pays_avec_la_cible_5(conn):
    for cc in EC:
        _bank(conn, f"{cc}-2012-ec", 2)
    needs = all_needs(conn, anchors_kind=KIND, encoder_version=ENC)
    assert len(needs) == 3
    assert {n.class_id for n in needs} == {f"{cc}-2012-ec" for cc in EC}
    assert all(n.family == "emission_commune" for n in needs)
    assert all(n.target == 5 for n in needs)
    assert all(n.need == 3 for n in needs)
    # Jamais sous le design_group_id.
    assert "eu-euro-cash-2012" not in {n.class_id for n in needs}


def test_la_cible_depend_de_la_famille(conn):
    assert cn.target_for_family("emission_commune") == cn.TARGET_EMISSION_COMMUNE == 5
    assert cn.target_for_family("nationale") == cn.DEFAULT_TARGET == 8
    assert cn.target_for_family("portrait_standard") == 8
    _bank(conn, "fr-2016-commemo", 1)
    _bank(conn, "it-2002-std", 1)
    by = _by_id(all_needs(conn, anchors_kind=KIND, encoder_version=ENC))
    assert (by["fr-2016-commemo"].family, by["fr-2016-commemo"].target) == ("nationale", 8)
    assert (by["it-2002-std"].family, by["it-2002-std"].target) == ("portrait_standard", 8)
    assert by["fr-2016-commemo"].need == 7


# ── Le verdict ───────────────────────────────────────────────────────────────


def test_le_verdict_dans_lordre():
    # D2 : « pleine » dès la CIBLE (8, ou 5 pour une émission commune), pas le
    # plafond 10 — la liste de travail s'arrête là où le besoin tombe à 0.
    assert bottleneck_for(have=8, target=8, pending_scoped=5) == "pleine"
    assert bottleneck_for(have=11, target=8, pending_scoped=0) == "pleine"
    assert bottleneck_for(have=5, target=5, pending_scoped=3) == "pleine"
    assert bottleneck_for(have=7, target=8, pending_scoped=1) == "review"
    assert bottleneck_for(have=0, target=8, pending_scoped=0) == "scrape"
    assert cn.BOTTLENECKS == ("pleine", "review", "scrape")


def test_pleine_a_have_au_plafond_meme_avec_des_candidats(conn):
    _bank(conn, "fr-2016-commemo", 10)
    _open(conn, "p1", "fr-2016-commemo")
    n = _by_id(all_needs(conn, anchors_kind=KIND, encoder_version=ENC))["fr-2016-commemo"]
    assert (n.have, n.cap, n.need, n.bottleneck, n.pending) == (10, 10, 0, "pleine", 1)


def test_pleine_a_la_cible_pas_au_plafond(conn):
    # Mutation : remettre `have >= cap` dans bottleneck_for doit faire rougir ce test.
    _bank(conn, "fr-2016-commemo", 8)
    _open(conn, "p1", "fr-2016-commemo")
    n = _by_id(all_needs(conn, anchors_kind=KIND, encoder_version=ENC))["fr-2016-commemo"]
    assert (n.have, n.cap, n.target, n.need, n.bottleneck) == (8, 10, 8, 0, "pleine")


def test_scrape_a_pending_zero(conn):
    _bank(conn, "fr-2016-commemo", 4)
    n = _by_id(all_needs(conn, anchors_kind=KIND, encoder_version=ENC))["fr-2016-commemo"]
    assert (n.have, n.need, n.pending, n.pending_scoped, n.bottleneck) == (4, 4, 0, 0, "scrape")
    assert n.best_margin is None


def test_review_sinon_et_la_meilleure_marge(conn):
    _bank(conn, "fr-2016-commemo", 4)
    _open(conn, "p1", "fr-2016-commemo", spread=0.03)
    _open(conn, "p2", "fr-2016-commemo", spread=0.20, country_spread=0.12)
    _open(conn, "p3", "fr-2016-commemo", spread=0.07)
    n = _by_id(all_needs(conn, anchors_kind=KIND, encoder_version=ENC))["fr-2016-commemo"]
    assert (n.pending, n.pending_scoped, n.bottleneck) == (3, 3, "review")
    # COALESCE(country_spread, spread) : la marge du verdict, pas la colonne brute.
    assert n.best_margin == pytest.approx(0.12)


def test_une_classe_pleine_nest_pas_masquee(conn):
    _bank(conn, "fr-2016-commemo", 10)
    _bank(conn, "lu-2019-commemo", 0)
    ids = {n.class_id for n in all_needs(conn, anchors_kind=KIND, encoder_version=ENC)}
    assert ids == {"fr-2016-commemo", "lu-2019-commemo"}


# ── `pending` : la population exacte ─────────────────────────────────────────


def test_pending_ne_compte_que_le_statut_open(conn):
    _bank(conn, "fr-2016-commemo", 4)
    _open(conn, "p1", "fr-2016-commemo", status="open")
    _open(conn, "p2", "fr-2016-commemo", status="in_progress")
    _open(conn, "p3", "fr-2016-commemo", status="done")
    n = _by_id(all_needs(conn, anchors_kind=KIND, encoder_version=ENC))["fr-2016-commemo"]
    assert n.pending == 1


def test_pending_ne_melange_pas_les_banques(conn):
    _bank(conn, "fr-2016-commemo", 4)
    _open(conn, "p1", "fr-2016-commemo", kind="2eur_commemo", enc="dinov2-vits14")
    n = _by_id(all_needs(conn, anchors_kind=KIND, encoder_version=ENC))["fr-2016-commemo"]
    assert (n.pending, n.bottleneck) == (0, "scrape")


def test_le_couple_est_obligatoire(conn):
    with pytest.raises(TypeError):
        all_needs(conn)  # type: ignore[call-arg]
    with pytest.raises(TypeError):
        all_needs(conn, anchors_kind=KIND)  # type: ignore[call-arg]


def test_une_banque_vide_rend_une_liste_vide(conn):
    assert all_needs(conn, anchors_kind=KIND, encoder_version=ENC) == []


# ── `have` : grain banque, fps seulement ─────────────────────────────────────


def test_have_ne_compte_que_les_fps(conn):
    _bank(conn, "fr-2016-commemo", 2)
    _asset(conn, "pin")
    conn.execute(
        "INSERT INTO dino_class_references (anchors_kind, encoder_version, class_id,"
        " eurio_id, asset_id, method) VALUES (?,?,?,?,?,'manual_pin')",
        (KIND, ENC, "fr-2016-commemo", "fr-2016-commemo", "a-pin"),
    )
    conn.commit()
    n = _by_id(all_needs(conn, anchors_kind=KIND, encoder_version=ENC))["fr-2016-commemo"]
    assert n.have == 2


def test_have_compte_les_fps_des_membres_sous_le_representant(conn):
    # Deux exemplaires de 2008 rangés sous la classe 2002 : c'est le grain
    # banque, et c'est 2002 qui les porte.
    _bank(conn, "it-2002-std", 1)
    _bank(conn, "it-2002-std", 2, eurio_id="it-2008-std", canonical=False)
    needs = all_needs(conn, anchors_kind=KIND, encoder_version=ENC)
    assert [(n.class_id, n.have) for n in needs] == [("it-2002-std", 3)]


# ── Voie A : affichée, jamais dans le verdict ────────────────────────────────


def test_n_train_eligible_avec_les_quatre_conditions(conn):
    _bank(conn, "it-2002-std", 0)
    # Compte : eBay, éligible, présent, pas un revers — sur toute l'ère.
    _asset(conn, "ok1", eurio_id="it-2002-std", eligible=1)
    _asset(conn, "ok2", eurio_id="it-2008-std", eligible=1, face="obverse")
    # Ne compte pas : chacune casse UNE condition.
    _asset(conn, "ko-src", source="numista", eurio_id="it-2002-std", eligible=1)
    _asset(conn, "ko-elig", eurio_id="it-2002-std", eligible=0)
    _asset(conn, "ko-store", eurio_id="it-2002-std", eligible=1, storage="missing_in_storage")
    _asset(conn, "ko-face", eurio_id="it-2002-std", eligible=1, face="reverse")
    conn.commit()
    n = _by_id(all_needs(conn, anchors_kind=KIND, encoder_version=ENC))["it-2002-std"]
    assert n.n_train_eligible == 2
    # Et ça ne change rien au verdict : la voie A n'y entre pas.
    assert n.bottleneck == "scrape"


def test_une_commemorative_demission_commune_compte_seule_en_voie_a(conn):
    # Le bake entraîne une commémorative sous son propre label, même quand elle
    # porte un design_group_id multi-pays.
    for cc in EC:
        _bank(conn, f"{cc}-2012-ec", 0)
    _asset(conn, "cy1", eurio_id="cy-2012-ec", eligible=1)
    _asset(conn, "cy2", eurio_id="cy-2012-ec", eligible=1)
    _asset(conn, "fr1", eurio_id="fr-2012-ec", eligible=1)
    conn.commit()
    by = _by_id(all_needs(conn, anchors_kind=KIND, encoder_version=ENC))
    assert [by[f"{cc}-2012-ec"].n_train_eligible for cc in EC] == [2, 1, 0]


# ── Le contrat du module ─────────────────────────────────────────────────────


def test_le_module_necrit_rien():
    src = Path(cn.__file__).read_text(encoding="utf-8")
    assert not re.search(r"\b(INSERT|UPDATE|DELETE|REPLACE)\b", src, re.IGNORECASE)


def test_le_dataclass_est_gele(conn):
    _bank(conn, "fr-2016-commemo", 1)
    n = all_needs(conn, anchors_kind=KIND, encoder_version=ENC)[0]
    with pytest.raises(Exception):
        n.have = 99  # type: ignore[misc]


def test_le_plafond_est_celui_du_builder():
    """`DEFAULT_CAP` recopie `anchors.DEFAULT_EXEMPLARS_PER_CLASS` (torch)."""
    anchors = pytest.importorskip("training.foundation.anchors")
    assert cn.DEFAULT_CAP == anchors.DEFAULT_EXEMPLARS_PER_CLASS


def test_le_label_est_lisible(conn):
    _bank(conn, "it-2002-std", 0)
    _bank(conn, "fr-2016-commemo", 0)
    by = _by_id(all_needs(conn, anchors_kind=KIND, encoder_version=ENC))
    assert by["it-2002-std"].label == "IT 2€ standard (1er type)"
    assert by["fr-2016-commemo"].label == "FR 2016 — thème"
    assert by["it-2002-std"].country == "IT"


# ── D8 · les ACQUIS : validés, pas encore en banque ──────────────────────────
#
# Pourquoi ce bloc existe : `have` ne bouge qu'au `build_dino_anchors` suivant.
# Sans ce compte, `bottleneck` est FIGÉ pendant toute une session de review et
# la file ressert une classe qu'on vient de remplir. Mesuré le 2026-08-22
# (banque a55e6594) : 1 451 crops acceptés hors banque, dont 76 seulement
# poseraient un exemplaire — le reste tombe dans des classes déjà à leur cible.


def _accepte(conn, ref, top1, *, storage="present", face=None):
    """Un crop VALIDÉ par un humain, avec sa prédiction — pas encore en banque."""
    aid = _asset(conn, ref, eligible=1, storage=storage, face=face)
    conn.execute(
        "INSERT INTO image_asset_dino_predictions (asset_id, encoder_version, anchors_kind,"
        " anchors_count, top_k_json, top1_eurio_id, top1_sim, spread)"
        " VALUES (?,?,?,?,?,?,?,0.2)",
        (aid, ENC, KIND, 10, json.dumps([{"eurio_id": top1, "sim": 0.8}]), top1, 0.8),
    )
    conn.commit()
    return aid


def test_un_crop_accepte_compte_dans_les_acquis(conn):
    _coin(conn, "fr-2016-c", "FR", 2016, commemo=True)
    _bank(conn, "fr-2016-c", 3)
    _accepte(conn, "acq1", "fr-2016-c")
    _accepte(conn, "acq2", "fr-2016-c")

    n = _by_id(all_needs(conn, anchors_kind=KIND, encoder_version=ENC))["fr-2016-c"]
    assert n.have == 3, "la banque n'a pas bougé — elle ne bouge qu'au rebuild"
    assert n.accepted_pending == 2


def test_le_verdict_compte_les_acquis_sinon_la_file_ressert_une_classe_pleine(conn):
    """LE test du lot. C'est lui qui rend l'exigence du PO réalisable.

    7 en banque + 1 acquis = la cible 8 est atteinte. `have` vaut toujours 7 et
    vaudra 7 jusqu'au rebuild : un verdict calculé sur lui seul dirait `review`
    et renverrait l'opérateur trancher une classe déjà remplie.
    """
    _coin(conn, "fr-2016-c", "FR", 2016, commemo=True)
    _bank(conn, "fr-2016-c", 7)
    _open(conn, "encore", "fr-2016-c")        # il reste des candidats en file
    _accepte(conn, "acq1", "fr-2016-c")

    n = _by_id(all_needs(conn, anchors_kind=KIND, encoder_version=ENC))["fr-2016-c"]
    assert n.have == 7 and n.accepted_pending == 1
    assert n.pending == 1, "la file a bien encore de quoi servir"
    assert n.bottleneck == "pleine", "et pourtant on ne sert plus : 7 + 1 ≥ 8"


def test_need_reste_sur_la_banque_meme_quand_le_verdict_est_pleine(conn):
    """`need` et `bottleneck` ne comptent pas la même chose, et c'est voulu.

    `need` alimente le BUDGET (ce qui manque à la banque, et qui manquera
    jusqu'au rebuild). `bottleneck` décide s'il faut SERVIR. Les aligner ferait
    mentir l'un des deux : soit le budget oublierait des exemplaires à bâtir,
    soit la file resservirait une classe remplie.
    """
    _coin(conn, "fr-2016-c", "FR", 2016, commemo=True)
    _bank(conn, "fr-2016-c", 7)
    _accepte(conn, "acq1", "fr-2016-c")

    n = _by_id(all_needs(conn, anchors_kind=KIND, encoder_version=ENC))["fr-2016-c"]
    assert n.need == 1, "il manque toujours un exemplaire À LA BANQUE"
    assert n.bottleneck == "pleine", "mais il est déjà acquis"


def test_un_crop_deja_en_banque_n_est_pas_compte_deux_fois(conn):
    """Sans la clause `NOT IN (banque)`, une classe pleine paraîtrait doublement
    pleine et le bandeau « un rebuild poserait N » serait faux."""
    _coin(conn, "fr-2016-c", "FR", 2016, commemo=True)
    _bank(conn, "fr-2016-c", 2)
    # L'asset qui porte déjà l'exemplaire fps n°0, marqué validé et prédit.
    aid = conn.execute(
        "SELECT asset_id FROM dino_class_references "
        " WHERE method='fps' AND rank=0 AND class_id='fr-2016-c'",
    ).fetchone()[0]
    conn.execute("UPDATE image_assets SET training_eligible=1 WHERE id=?", (aid,))
    conn.execute(
        "INSERT INTO image_asset_dino_predictions (asset_id, encoder_version, anchors_kind,"
        " anchors_count, top_k_json, top1_eurio_id, top1_sim, spread)"
        " VALUES (?,?,?,?,?,?,0.8,0.2)",
        (aid, ENC, KIND, 10, json.dumps([{"eurio_id": "fr-2016-c", "sim": 0.8}]), "fr-2016-c"),
    )
    conn.commit()

    n = _by_id(all_needs(conn, anchors_kind=KIND, encoder_version=ENC))["fr-2016-c"]
    assert n.have == 2
    assert n.accepted_pending == 0, "il est DÉJÀ bâti : ce n'est pas un acquis"


def test_les_acquis_appliquent_les_memes_portes_que_le_builder(conn):
    """Un revers ou un fichier absent ne deviendra JAMAIS un exemplaire.

    Les compter promettrait un exemplaire qui n'arrivera pas, et le bandeau
    « un rebuild poserait N » annoncerait plus que ce qu'il pose.
    """
    _coin(conn, "fr-2016-c", "FR", 2016, commemo=True)
    _bank(conn, "fr-2016-c", 1)
    _accepte(conn, "bon", "fr-2016-c")
    _accepte(conn, "revers", "fr-2016-c", face="reverse")
    _accepte(conn, "absent", "fr-2016-c", storage="missing_in_storage")

    n = _by_id(all_needs(conn, anchors_kind=KIND, encoder_version=ENC))["fr-2016-c"]
    assert n.accepted_pending == 1, "seul le crop exploitable compte"


def test_les_acquis_ne_melangent_pas_les_banques(conn):
    """Même exigence que `pending` : le couple (kind, encoder) est obligatoire."""
    _coin(conn, "fr-2016-c", "FR", 2016, commemo=True)
    _bank(conn, "fr-2016-c", 1)
    aid = _asset(conn, "autre", eligible=1)
    conn.execute(
        "INSERT INTO image_asset_dino_predictions (asset_id, encoder_version, anchors_kind,"
        " anchors_count, top_k_json, top1_eurio_id, top1_sim, spread)"
        " VALUES (?,?,?,?,?,?,0.8,0.2)",
        (aid, ENC, "2eur_commemo", 10,
         json.dumps([{"eurio_id": "fr-2016-c", "sim": 0.8}]), "fr-2016-c"),
    )
    conn.commit()

    n = _by_id(all_needs(conn, anchors_kind=KIND, encoder_version=ENC))["fr-2016-c"]
    assert n.accepted_pending == 0


def test_bottleneck_for_accepte_les_acquis_en_argument():
    """Le verdict reste testable seul, sans base."""
    from shared.class_need import bottleneck_for
    assert bottleneck_for(have=7, target=8, pending_scoped=5) == "review"
    assert bottleneck_for(
        have=7, target=8, pending_scoped=5, accepted_pending=1) == "pleine"
    # Les acquis ne fabriquent pas de candidats : sans file, c'est du scrape.
    assert bottleneck_for(
        have=0, target=8, pending_scoped=0, accepted_pending=3) == "scrape"


# ── O4 · `pending_scoped` porte enfin ce que la file SERT (lot 6) ────────────
#
# La dette que ces tests ferment : jusqu'au 2026-08-23, `pending_scoped` était
# une copie de `pending`. La page `/besoin` comptait donc le pool BRUT là où la
# pêche sert le pool FILTRÉ, et l'écart n'était réconciliable qu'à la
# soustraction. Mesuré sur la réplique une fois le champ réel : Σ pending
# 6 409 → Σ pending_scoped 3 176, et 50 classes basculent `review` → `scrape`.


def _annonce(conn, ref: str, *, country: str | None = None, years=None) -> None:
    """Le pays et les années de l'ANNONCE d'un crop déjà enfilé par `_open`."""
    if country is not None:
        conn.execute(
            "UPDATE source_images SET listing_country = ? WHERE id = ?",
            (country, f"si-{ref}"),
        )
    if years is not None:
        conn.execute(
            "INSERT INTO listing_text_signals (source_image_id, years_json, coverage)"
            " VALUES (?,?,'rich')",
            (f"si-{ref}", json.dumps(years)),
        )
    conn.commit()


def test_une_classe_dont_l_ere_ecarte_tout_bascule_en_scrape(conn):
    """⛔ C'est un CHANGEMENT DE SENS du verdict, et il est voulu.

    Cas réel : `lu-2016-…charlotte-bridge` portait 20 candidats, tous issus
    d'annonces belges de 2026 (« 100 Jahre NMBS ») que la banque marquait à
    tort. Les envoyer en review, c'est envoyer un humain devant une file vide.
    La classe relève du SCRAPE, et l'écran doit le dire.
    """
    _bank(conn, "fr-2016-commemo", 2)
    for ref in ("faux1", "faux2"):
        _open(conn, ref, "fr-2016-commemo")
        _annonce(conn, ref, country="BE", years=[2026])

    n = _by_id(all_needs(conn, anchors_kind=KIND, encoder_version=ENC))["fr-2016-commemo"]
    assert n.pending == 2, "le pool brut ne bouge pas — il n'est pas censé mentir"
    assert n.pending_scoped == 0
    assert n.n_hidden_by_era == 2
    assert n.bottleneck == "scrape"


def test_les_effets_des_filtres_sont_emboites_et_somment(conn):
    """`pending − era − country − denom = pending_scoped`, exactement.

    Trois effets qu'on lirait comme indépendants donneraient « 1 + 1 masqués »
    au-dessus d'une file qui en a perdu 2 : le badge et la file diraient deux
    choses différentes, ce que ce dépôt paie cher à chaque fois.
    """
    _bank(conn, "fr-2016-commemo", 2)
    _open(conn, "bon", "fr-2016-commemo")
    _annonce(conn, "bon", country="FR", years=[2016])
    _open(conn, "hors-ere", "fr-2016-commemo")
    _annonce(conn, "hors-ere", country="FR", years=[2020])
    _open(conn, "hors-pays", "fr-2016-commemo")
    _annonce(conn, "hors-pays", country="DE", years=[2016])

    n = _by_id(all_needs(conn, anchors_kind=KIND, encoder_version=ENC))["fr-2016-commemo"]
    assert (n.pending, n.n_hidden_by_era, n.n_hidden_by_country) == (3, 1, 1)
    assert n.pending_scoped == 1
    assert n.pending - n.n_hidden_by_era - n.n_hidden_by_country \
           - n.n_hidden_by_denom == n.pending_scoped
    assert n.bottleneck == "review"
    assert n.country_disarmed is False


def test_le_pays_desarme_remonte_jusqu_a_la_ligne(conn):
    """Sans ce drapeau, le geste proposé par `/besoin` ouvre une file vide.

    La ligne annonce N candidats ; le lien doit alors porter `pays=tous`, sinon
    la pêche réapplique son filtre par défaut et sert zéro. C'est le « badge qui
    annonce 4 au-dessus d'une file qui en sert 3 », en pire.
    """
    _bank(conn, "fr-2016-commemo", 2)
    for ref in ("de1", "de2"):
        _open(conn, ref, "fr-2016-commemo")
        _annonce(conn, ref, country="DE", years=[2016])

    n = _by_id(all_needs(conn, anchors_kind=KIND, encoder_version=ENC))["fr-2016-commemo"]
    assert n.country_disarmed is True
    assert n.n_hidden_by_country == 0, "un filtre retiré ne masque rien"
    assert (n.pending, n.pending_scoped, n.bottleneck) == (2, 2, "review")


def test_la_porte_denomination_ne_se_ferme_que_si_on_l_arme(conn):
    """Inactive par défaut : elle coûte ~5 % de vrais positifs (choix, pas règle)."""
    _bank(conn, "fr-2016-commemo", 2)
    _open(conn, "piecette", "fr-2016-commemo")
    _annonce(conn, "piecette", country="FR", years=[2016])
    conn.execute(
        "UPDATE image_asset_dino_predictions SET denom_2eur_score = 0.05 "
        "WHERE asset_id = 'a-piecette'",
    )
    conn.commit()

    ouverte = _by_id(all_needs(conn, anchors_kind=KIND, encoder_version=ENC))
    assert ouverte["fr-2016-commemo"].pending_scoped == 1
    assert ouverte["fr-2016-commemo"].n_hidden_by_denom == 0

    armee = _by_id(all_needs(
        conn, anchors_kind=KIND, encoder_version=ENC, min_denom=0.4,
    ))
    assert armee["fr-2016-commemo"].pending_scoped == 0
    assert armee["fr-2016-commemo"].n_hidden_by_denom == 1
    assert armee["fr-2016-commemo"].bottleneck == "scrape"


def test_une_autre_banque_ne_pretend_pas_filtrer(conn):
    """Les filtres lisent les prédictions de la banque des SUGGESTIONS.

    Sur une autre banque ils porteraient sur une population qui n'est pas celle
    qu'on compte : `pending_scoped` retombe sur `pending` plutôt que de rendre
    un nombre bâti sur la mauvaise population — et il le fait sans rien
    prétendre filtrer.
    """
    _bank(conn, "fr-2016-commemo", 2, kind="2eur_commemo", enc="dinov2-vitb14")
    _open(conn, "x", "fr-2016-commemo", kind="2eur_commemo", enc="dinov2-vitb14")
    _annonce(conn, "x", country="BE", years=[2026])   # contredirait l'ère 2016

    n = _by_id(all_needs(
        conn, anchors_kind="2eur_commemo", encoder_version="dinov2-vitb14",
    ))["fr-2016-commemo"]
    assert (n.pending, n.pending_scoped, n.n_hidden_by_era) == (1, 1, 0)
