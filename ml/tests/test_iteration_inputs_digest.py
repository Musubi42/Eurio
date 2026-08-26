"""`inputs_digest` quitte le disque — migration 0016.

Chantier `juge-et-banc`, lot 5. L'empreinte des entrées d'un bake existait
déjà (configuration de recette + graine par pièce + cible + liste ORDONNÉE des
sources) mais vivait dans le `_manifest.json` de chaque pièce, sur la machine
qui a baké. Le canonique ne savait donc pas AVEC QUOI un modèle avait été
entraîné — pendant que le pool grossissait sous la même cohorte : **5 051
samples le 2026-08-16, 6 594 le 2026-08-25 (+30,5 %)**.

Ce que ces tests verrouillent, et pourquoi chacun existe :

1. **la colonne naît des deux côtés du contrat de miroir** — base neuve
   (`schema.sql`) et base antérieure (`_ensure_column`) ;
2. **le rollup change quand les entrées changent, et SEULEMENT alors.** Un
   digest qui ne bouge pas quand une classe entre dans le bake est pire
   qu'aucun digest : il affirme une identité fausse ;
3. **il ne dépend pas de l'ordre des rapports** — sinon deux bakes identiques
   rendraient deux empreintes différentes, et la colonne ne servirait à rien ;
4. **la valeur fait l'aller-retour, jusqu'au canonique** — la route de sync
   est du pydantic, qui laisse tomber un champ non déclaré sans un mot ;
5. **un bake réutilisé (snapshot conforme) porte quand même son digest** — ne
   le poser que sur la branche « régénéré » ferait dire « entrées inconnues »
   d'un bake parfaitement à jour.

Run: `.venv/bin/python -m pytest ml/tests/test_iteration_inputs_digest.py -q`
"""

from __future__ import annotations

import sqlite3
import sys
from pathlib import Path

ML_DIR = Path(__file__).resolve().parent.parent
if str(ML_DIR) not in sys.path:
    sys.path.insert(0, str(ML_DIR))

import pytest  # noqa: E402

from store import Store  # noqa: E402
from store.iterations import ExperimentIterationRow  # noqa: E402
from training.iteration_augmentations import (  # noqa: E402
    CoinAugReport,
    rollup_inputs_digest,
)

_MIGRATION = ML_DIR / "serving" / "migrations" / "0016_iteration_inputs_digest.sql"


def _rapport(eurio_id, digest=None, *, skipped=None) -> CoinAugReport:
    return CoinAugReport(
        eurio_id=eurio_id, numista_id=1, written=100, sources_used=3,
        inputs_digest=digest, skipped_reason=skipped,
    )


# ─── 1. La colonne naît partout ──────────────────────────────────────────────


def test_la_migration_0016_est_bien_un_alter_et_son_miroir_existe():
    sql = _MIGRATION.read_text(encoding="utf-8")
    assert "ALTER TABLE experiment_iterations ADD COLUMN inputs_digest TEXT" in sql
    schema = (ML_DIR / "state" / "schema.sql").read_text(encoding="utf-8")
    assert "inputs_digest" in schema


def test_une_base_neuve_nait_avec_inputs_digest(tmp_path):
    conn = Store(tmp_path / "neuve.db")._connection()  # noqa: SLF001
    cols = {r[1] for r in conn.execute("PRAGMA table_info(experiment_iterations)")}
    assert "inputs_digest" in cols


def test_une_base_anterieure_rattrape_inputs_digest(tmp_path):
    """`_ensure_column` : une base créée AVANT 0016 gagne la colonne à
    l'ouverture. Sans ça, `upsert_iteration` — qui NOMME la colonne dans son
    INSERT — exploserait en « no such column » sur chaque push."""
    schema = (ML_DIR / "state" / "schema.sql").read_text(encoding="utf-8")
    ampute = "\n".join(
        ligne for ligne in schema.splitlines() if "inputs_digest" not in ligne
    ).replace("  summary_json              TEXT,\n", "  summary_json              TEXT\n")
    db = tmp_path / "ancienne.db"
    brut = sqlite3.connect(db)
    brut.executescript(ampute)
    brut.commit()
    brut.close()
    assert "inputs_digest" not in {
        r[1] for r in sqlite3.connect(db).execute(
            "PRAGMA table_info(experiment_iterations)")
    }

    conn = Store(db)._connection()  # noqa: SLF001
    assert "inputs_digest" in {
        r[1] for r in conn.execute("PRAGMA table_info(experiment_iterations)")
    }


# ─── 2. Le rollup dit la vérité sur les entrées ──────────────────────────────


def test_le_rollup_est_stable_et_independant_de_lordre():
    """Deux bakes des mêmes entrées doivent rendre la MÊME empreinte, quel que
    soit l'ordre où `bake_member_ids` a rendu les pièces (il dépend d'une
    expansion `design_group`, pas d'un tri)."""
    a = [_rapport("be-1999", "d1"), _rapport("fr-2007", "d2")]
    b = [_rapport("fr-2007", "d2"), _rapport("be-1999", "d1")]
    assert rollup_inputs_digest(a) == rollup_inputs_digest(b)
    assert rollup_inputs_digest(a) == rollup_inputs_digest(list(a))


def test_le_rollup_change_quand_une_source_change():
    avant = [_rapport("be-1999", "d1"), _rapport("fr-2007", "d2")]
    apres = [_rapport("be-1999", "d1"), _rapport("fr-2007", "d2-BIS")]
    assert rollup_inputs_digest(avant) != rollup_inputs_digest(apres)


def test_le_rollup_change_quand_une_PIECE_entre_ou_sort():
    """LE cas qui a motivé 0016 : le pool grossit sous la MÊME cohorte
    (5 051 → 6 594 samples, +30,5 % entre le 2026-08-16 et le 2026-08-25). Une
    empreinte qui ne bouge pas quand une pièce entre dans le bake affirmerait
    une identité fausse — pire qu'une colonne vide."""
    petit = [_rapport("be-1999", "d1")]
    grand = [_rapport("be-1999", "d1"), _rapport("fr-2007", "d2")]
    assert rollup_inputs_digest(petit) != rollup_inputs_digest(grand)


def test_une_piece_SAUTEE_compte_dans_le_rollup():
    """L'autre moitié du même cas : une classe sans source aujourd'hui en a une
    demain. Si les sautées étaient omises, le rollup dirait « mêmes entrées »
    d'un bake qui vient de gagner une classe entière.

    Et le MOTIF compte : « pas de numista_id » et « pas de source » ne sont pas
    le même état du monde.
    """
    sautee = [_rapport("be-1999", "d1"),
              _rapport("fr-2007", None, skipped="no training source")]
    entree = [_rapport("be-1999", "d1"), _rapport("fr-2007", "d2")]
    absente = [_rapport("be-1999", "d1")]
    assert len({rollup_inputs_digest(x)
                for x in (sautee, entree, absente)}) == 3

    autre_motif = [_rapport("be-1999", "d1"),
                   _rapport("fr-2007", None, skipped="no numista_id mapping")]
    assert rollup_inputs_digest(sautee) != rollup_inputs_digest(autre_motif)


# ─── 3. La valeur fait l'aller-retour, jusqu'au canonique ────────────────────


def _cohorte_et_iteration(store: Store, *, digest=None) -> ExperimentIterationRow:
    from store.cohorts import ExperimentCohortRow

    store.create_cohort(ExperimentCohortRow(
        id="co1", name="c", eurio_ids=["be-1999"]))
    it = ExperimentIterationRow(
        id="it1", cohort_id="co1", name="i1", inputs_digest=digest)
    store.create_iteration(it)
    return it


def test_update_iteration_persiste_le_digest_et_get_le_relit(tmp_path):
    store = Store(tmp_path / "t.db")
    _cohorte_et_iteration(store)
    assert store.get_iteration("it1").inputs_digest is None

    store.update_iteration("it1", inputs_digest="ab" * 32)
    assert store.get_iteration("it1").inputs_digest == "ab" * 32


def test_upsert_iteration_transporte_le_digest(tmp_path):
    """C'est `upsert_iteration` qui sert le PUT canonique : si elle ne nommait
    pas la colonne, chaque push écraserait la provenance par NULL."""
    store = Store(tmp_path / "t.db")
    it = _cohorte_et_iteration(store)
    it.inputs_digest = "cd" * 32
    store.upsert_iteration(it)
    assert store.get_iteration("it1").inputs_digest == "cd" * 32

    # Et le snapshot poussé le porte : `to_dict` est le corps du PUT.
    assert store.get_iteration("it1").to_dict()["inputs_digest"] == "cd" * 32


def test_la_route_de_sync_transporte_le_digest():
    """Pydantic ignore silencieusement un champ non déclaré : sans lui sur le
    modèle, l'itération monterait au canonique amputée de sa provenance
    pendant que le PUT répond 200."""
    from serving.iteration_sync_routes import IterationSnapshot

    assert "inputs_digest" in IterationSnapshot.model_fields
    snap = IterationSnapshot(
        cohort_id="co1", name="i1", status="pending", inputs_digest="ef" * 32)
    assert snap.model_dump()["inputs_digest"] == "ef" * 32
    # …et le dataclass accepte le dict tel quel (`ExperimentIterationRow(id=…,
    # **data)` dans la route : une clé de trop y serait un TypeError).
    row = ExperimentIterationRow(id="it1", **snap.model_dump())
    assert row.inputs_digest == "ef" * 32


# ─── 4. Le bake remonte le digest, régénéré OU réutilisé ─────────────────────


def test_le_bake_remonte_le_digest_meme_quand_il_reutilise_le_snapshot(
    tmp_path, monkeypatch,
):
    """Le second bake ne régénère rien (`_reusable_snapshot` a prouvé que les
    entrées n'ont pas bougé) — il doit quand même rendre l'empreinte, et la
    MÊME. Ne la poser que sur la branche « régénéré » ferait dire au rollup
    « entrées inconnues » d'un bake parfaitement à jour.
    """
    from tests.test_iteration_augmentations import _bake_env  # type: ignore

    ia, store, sources, out_dir, _mk = _bake_env(tmp_path, monkeypatch)

    r1 = ia.generate_for_iteration(iteration_id="it1", store=store)
    assert r1[0].inputs_digest, "le bake qui GÉNÈRE doit rendre son empreinte"
    # Le manifeste sur disque et le rapport disent la MÊME chose : sinon la
    # colonne 0016 et la preuve de provenance divergeraient en silence.
    import json

    manifest = json.loads((out_dir / "_manifest.json").read_text())
    assert manifest["inputs_digest"] == r1[0].inputs_digest

    r2 = ia.generate_for_iteration(iteration_id="it1", store=store)
    assert r2[0].inputs_digest == r1[0].inputs_digest
    assert rollup_inputs_digest(r1) == rollup_inputs_digest(r2)

    # …et il change dès qu'une source entre.
    sources.append(_mk("s2.jpg", (30, 200, 30)))
    r3 = ia.generate_for_iteration(iteration_id="it1", store=store)
    assert rollup_inputs_digest(r3) != rollup_inputs_digest(r1)


@pytest.mark.parametrize("champ", ["inputs_digest"])
def test_le_rapport_de_bake_porte_le_champ(champ):
    """Garde nommée : sans le champ sur `CoinAugReport`, le runner n'aurait
    aucun moyen de connaître les digests sans relire les manifestes — qui
    n'existent que sur la machine qui a baké."""
    assert champ in CoinAugReport.__dataclass_fields__
