"""La famille de signal — `shared/class_family` (O5).

Ce qui est verrouillé :

1. Les trois exemples de la spec : une émission commune, un portrait courant,
   une commémorative nationale.
2. La maille BANQUE : une émission commune à 3 pays donne 3 classes
   `emission_commune`, pas une — et un membre non-représentant d'une ère a la
   famille de son représentant.
3. Une pièce inconnue lève : un défaut silencieux en `nationale` ferait passer
   une faute de saisie pour une commémorative.
4. Le module n'écrit rien.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

ML_DIR = Path(__file__).parent.parent
if str(ML_DIR) not in sys.path:
    sys.path.insert(0, str(ML_DIR))

import pytest

from shared import class_family as cf
from store import Store


def _coin(conn, eid, country, year, *, commemo, dgid=None, face=2.0):
    conn.execute(
        "INSERT INTO coins (eurio_id, country, year, face_value, is_commemorative,"
        " design_group_id) VALUES (?,?,?,?,?,?)",
        (eid, country, year, face, int(commemo), dgid),
    )


@pytest.fixture()
def conn(tmp_path):
    c = Store(tmp_path / "t.db")._connection()  # noqa: SLF001
    for gid in ("eu-euro-cash-2012", "be-2euro-philippe-t1", "it-2euro-standard-t1"):
        c.execute("INSERT INTO design_groups (id, designation) VALUES (?, ?)", (gid, gid))
    # Émission commune : même dessin, trois pays.
    for cc in ("cy", "fr", "de"):
        _coin(c, f"{cc}-2012-2eur-10-years-of-euro-cash", cc.upper(), 2012,
              commemo=True, dgid="eu-euro-cash-2012")
    # Portrait courant, groupé mono-pays.
    _coin(c, "be-2014-2eur-standard-philippe", "BE", 2014, commemo=False,
          dgid="be-2euro-philippe-t1")
    # Une ère courante à deux millésimes : 2002 porte l'ancre, 2008 non.
    _coin(c, "it-2002-std", "IT", 2002, commemo=False, dgid="it-2euro-standard-t1")
    _coin(c, "it-2008-std", "IT", 2008, commemo=False, dgid="it-2euro-standard-t1")
    # Commémorative nationale, sans groupe.
    _coin(c, "fr-2016-commemo", "FR", 2016, commemo=True)
    # Une courante qui n'est pas un 2 € : pas un portrait au sens de la banque.
    _coin(c, "fr-2010-1eur-std", "FR", 2010, commemo=False, face=1.0)
    c.commit()
    return c


def _bank(conn, *class_ids):
    for cid in class_ids:
        conn.execute(
            "INSERT INTO dino_class_references (anchors_kind, encoder_version, "
            "class_id, eurio_id, method) VALUES ('2eur_all','dinov2-vitl14',?,?,'canonical')",
            (cid, cid),
        )
    conn.commit()


def test_les_trois_exemples_de_la_spec(conn):
    assert cf.class_family(conn, "cy-2012-2eur-10-years-of-euro-cash") == "emission_commune"
    assert cf.class_family(conn, "be-2014-2eur-standard-philippe") == "portrait_standard"
    assert cf.class_family(conn, "fr-2016-commemo") == "nationale"


def test_les_groupes_multi_pays(conn):
    assert cf.emission_commune_group_ids(conn) == {"eu-euro-cash-2012"}


def test_un_groupe_mono_pays_nest_pas_une_emission_commune(conn):
    # `be-2euro-philippe-t1` a un seul pays : le COUNT(DISTINCT country) > 1
    # le laisse de côté. C'est la règle, pas la présence d'un design_group_id.
    assert cf.class_family(conn, "be-2014-2eur-standard-philippe") != "emission_commune"


def test_une_courante_hors_2eur_est_nationale(conn):
    assert cf.class_family(conn, "fr-2010-1eur-std") == "nationale"


def test_le_membre_a_la_famille_de_son_representant(conn):
    assert cf.class_family(conn, "it-2008-std") == cf.class_family(conn, "it-2002-std")
    assert cf.class_family(conn, "it-2002-std") == "portrait_standard"


def test_une_piece_inconnue_leve(conn):
    with pytest.raises(LookupError):
        cf.class_family(conn, "xx-0000-nope")


def test_families_for_bank_compte_au_grain_banque(conn):
    # L'émission commune entre dans la banque sous TROIS classes — jamais sous
    # `eu-euro-cash-2012`.
    _bank(
        conn,
        "cy-2012-2eur-10-years-of-euro-cash",
        "fr-2012-2eur-10-years-of-euro-cash",
        "de-2012-2eur-10-years-of-euro-cash",
        "be-2014-2eur-standard-philippe",
        "it-2002-std",
        "fr-2016-commemo",
    )
    fam = cf.families_for_bank(conn)
    assert len(fam) == 6
    assert sum(1 for v in fam.values() if v == "emission_commune") == 3
    assert fam["it-2002-std"] == "portrait_standard"
    assert fam["fr-2016-commemo"] == "nationale"
    assert set(fam.values()) <= set(cf.FAMILIES)


def test_families_for_bank_ne_melange_pas_les_banques(conn):
    _bank(conn, "fr-2016-commemo")
    assert cf.families_for_bank(conn, anchors_kind="2eur_commemo") == {}


def test_families_for_bank_leve_sur_une_classe_hors_referentiel(conn):
    _bank(conn, "fr-2016-commemo", "zz-9999-fantome")
    with pytest.raises(LookupError, match="fantome"):
        cf.families_for_bank(conn)


def test_le_module_necrit_rien():
    src = Path(cf.__file__).read_text(encoding="utf-8")
    assert not re.search(r"\b(INSERT|UPDATE|DELETE|REPLACE)\b", src, re.IGNORECASE)
