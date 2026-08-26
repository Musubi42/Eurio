"""Les deux axes de la matrice — `quantization` et `eval_corpus` (migration 0015).

Chantier `juge-et-banc`, lot 5. La matrice d'encodeurs doit rester lisible
pendant que le corpus grossit. `encoder_bench_runs` savait déjà dire QUEL
encodeur sur QUELLE banque contre QUEL gold ; elle ne savait pas dire **à
quelle précision** ni **sur quel corpus d'évaluation**. Deux runs qui ne
mesurent pas la même chose se lisaient pareil.

Ce que ces tests verrouillent, et pourquoi chacun existe :

1. **la colonne naît des deux côtés du contrat de miroir** — base neuve
   (`schema.sql`) ET base antérieure (`_ensure_column` pre-bootstrap). L'index
   partiel `idx_encoder_bench_runs_corpus` rend la branche « base antérieure »
   obligatoire : sans elle `executescript` plante en `no such column` avant
   que quoi que ce soit d'autre tourne (piège payé en 0014) ;
2. **la valeur fait l'aller-retour**, y compris par la route d'ingest —
   pydantic ignore silencieusement un champ non déclaré, et le run monterait
   au canonique amputé de ses deux axes sans qu'aucun code d'erreur ne le
   dise ;
3. **le vocabulaire de `quantization` est gardé à la PORTE** (`record_run`),
   pas par un CHECK SQL absent des bases antérieures ;
4. **la précision est RELEVÉE sur le modèle, pas déclarée** — un champ
   déclaratif dirait « int8 » d'un modèle resté en fp32 ;
5. **`eval_corpus` vient du SIDECAR du gold**, donc du manifeste figé, jamais
   d'une requête d'ici : un gold se relit quand la base a bougé.

Run: `.venv/bin/python -m pytest ml/tests/test_encoder_bench_matrice_axes.py -q`
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
from store.encoder_bench import (  # noqa: E402
    QUANTIZATIONS,
    EncoderBenchRun,
    ensure_schema,
    get_run,
    record_run,
)

_MIGRATION_0009 = ML_DIR / "serving" / "migrations" / "0009_encoder_bench.sql"
_MIGRATION_0015 = (
    ML_DIR / "serving" / "migrations"
    / "0015_encoder_bench_quantization_eval_corpus.sql"
)


def _run(**over) -> EncoderBenchRun:
    base = dict(
        run_id="r1",
        created_at="2026-08-26T10:00:00Z",
        gold_version="9bc08e19b83c",
        gold_n_crops=260,
        anchors_kind="matrice60",
        encoder_spec="dinov2_vitl14",
        encoder_version="dinov2-vitl14",
        n_in_scope=260,
        recall1=0.981,
    )
    base.update(over)
    return EncoderBenchRun(**base)


# ─── 1. La colonne naît partout ──────────────────────────────────────────────


def test_une_base_neuve_nait_avec_les_deux_colonnes_et_lindex(tmp_path):
    """`schema.sql` (rejoué à chaque ouverture d'un Store) fait autorité pour
    les bases locales : elles ne rejouent jamais les migrations."""
    conn = Store(tmp_path / "neuve.db")._connection()  # noqa: SLF001
    cols = {r[1] for r in conn.execute("PRAGMA table_info(encoder_bench_runs)")}
    assert {"quantization", "eval_corpus"} <= cols
    idx = {r[0] for r in conn.execute(
        "SELECT name FROM sqlite_master WHERE type='index'")}
    assert "idx_encoder_bench_runs_corpus" in idx


def test_une_base_anterieure_a_0015_rattrape_les_colonnes(tmp_path):
    """LE test du pre-bootstrap.

    Une base qui porte déjà `encoder_bench_runs` (celle de 0009) doit gagner
    les deux colonnes AVANT `executescript`, parce que `schema.sql` y crée un
    index PARTIEL sur `eval_corpus`. Posé après, il échouerait en « no such
    column: eval_corpus » — et la panne n'a rien à voir avec sa cause.
    """
    db = tmp_path / "ancienne.db"
    brut = sqlite3.connect(db)
    # Une VRAIE base d'avant 0015 : le schéma courant amputé des deux colonnes
    # et de leur index. Fabriquer un `encoder_bench_runs` de fantaisie ne
    # prouverait rien — ce qu'on exerce, c'est l'ordre pre-bootstrap →
    # executescript sur la table telle que 0009 l'a laissée.
    brut.executescript(_MIGRATION_0009.read_text(encoding="utf-8"))
    brut.commit()
    brut.close()
    assert "eval_corpus" not in {
        r[1] for r in sqlite3.connect(db).execute(
            "PRAGMA table_info(encoder_bench_runs)")
    }

    conn = Store(db)._connection()  # noqa: SLF001
    cols = {r[1] for r in conn.execute("PRAGMA table_info(encoder_bench_runs)")}
    assert {"quantization", "eval_corpus"} <= cols, (
        "une base antérieure à 0015 doit gagner les colonnes par _ensure_column")
    # Et le défaut de la colonne NOT NULL est bien posé sur les lignes d'avant.
    conn.execute(
        "INSERT INTO encoder_bench_runs (run_id, created_at, gold_version, "
        "gold_n_crops, anchors_kind, encoder_spec, encoder_version, n_in_scope) "
        "VALUES ('vieux', 'x', 'g', 1, 'k', 's', 'v', 1)")
    assert conn.execute(
        "SELECT quantization FROM encoder_bench_runs WHERE run_id='vieux'"
    ).fetchone()[0] == "fp32"


def test_ensure_schema_applique_0015_et_reste_rejouable():
    """`ensure_schema` est la porte documentée « pour les tests et les bases
    locales ». Depuis 0015 le DDL n'est plus dans un seul fichier, et
    `ALTER TABLE ADD COLUMN` n'a pas de `IF NOT EXISTS` : un deuxième appel
    doit passer, pas lever « duplicate column name »."""
    c = sqlite3.connect(":memory:")
    ensure_schema(c)
    ensure_schema(c)
    cols = {r[1] for r in c.execute("PRAGMA table_info(encoder_bench_runs)")}
    assert {"quantization", "eval_corpus"} <= cols
    c.close()


# ─── 2. La valeur fait l'aller-retour, jusqu'au canonique ────────────────────


def test_les_deux_axes_font_laller_retour_en_base(tmp_path):
    c = sqlite3.connect(":memory:")
    c.row_factory = sqlite3.Row
    ensure_schema(c)
    record_run(c, _run(quantization="int8_dynamic",
                       eval_corpus="matrice-encodeurs-2026-08"))
    ligne = get_run(c, "r1")
    assert ligne["quantization"] == "int8_dynamic"
    assert ligne["eval_corpus"] == "matrice-encodeurs-2026-08"
    c.close()


def test_deux_precisions_du_meme_encodeur_ne_secrasent_plus():
    """La raison d'être de `quantization`, dite en une assertion.

    Sans elle, ces deux runs partagent `encoder_spec`, `encoder_version`,
    `anchors_kind` et `gold_version` : dans l'index `..._couple` comme dans la
    lecture d'un humain, ils sont le même run mesuré deux fois — alors qu'ils
    ne mesurent pas la même chose.
    """
    c = sqlite3.connect(":memory:")
    c.row_factory = sqlite3.Row
    ensure_schema(c)
    record_run(c, _run(run_id="fp32", quantization="fp32", recall1=0.981))
    record_run(c, _run(run_id="i8", quantization="int8_dynamic", recall1=0.940))
    lignes = {r["run_id"]: r["quantization"] for r in c.execute(
        "SELECT run_id, quantization FROM encoder_bench_runs")}
    assert lignes == {"fp32": "fp32", "i8": "int8_dynamic"}
    c.close()


def test_la_route_ingest_transporte_les_deux_axes():
    """Le champ doit exister sur le MODÈLE de la route, pas seulement dans le
    dataclass : pydantic ignore silencieusement un champ non déclaré, et le run
    monterait au canonique amputé — 200 OK, valeur perdue."""
    from serving.ingest_routes import EncoderBenchRunPayload

    assert "quantization" in EncoderBenchRunPayload.model_fields
    assert "eval_corpus" in EncoderBenchRunPayload.model_fields
    p = EncoderBenchRunPayload(
        run_id="r", created_at="t", gold_version="g", gold_n_crops=1,
        anchors_kind="k", encoder_spec="s", encoder_version="v", n_in_scope=1,
        quantization="fp16", eval_corpus="matrice-encodeurs-2026-08",
    )
    d = p.model_dump()
    assert d["quantization"] == "fp16"
    assert d["eval_corpus"] == "matrice-encodeurs-2026-08"
    # Et le défaut, qui est la vérité de tous les runs d'avant 0015.
    defaut = EncoderBenchRunPayload(
        run_id="r", created_at="t", gold_version="g", gold_n_crops=1,
        anchors_kind="k", encoder_spec="s", encoder_version="v", n_in_scope=1)
    assert defaut.quantization == "fp32" and defaut.eval_corpus is None


# ─── 3. Le vocabulaire est gardé à la porte ──────────────────────────────────


@pytest.mark.parametrize("q", QUANTIZATIONS)
def test_les_precisions_du_vocabulaire_passent(q):
    c = sqlite3.connect(":memory:")
    ensure_schema(c)
    record_run(c, _run(quantization=q))
    c.close()


def test_une_precision_inventee_est_refusee_a_lecriture():
    """Gardé ici et pas par un CHECK SQL : un CHECK imposerait une
    reconstruction de table pour admettre une précision de plus, et resterait
    absent des bases antérieures à 0015 — donc muet là où il compte."""
    c = sqlite3.connect(":memory:")
    ensure_schema(c)
    with pytest.raises(ValueError, match="quantization"):
        record_run(c, _run(quantization="int4"))
    assert c.execute("SELECT COUNT(*) FROM encoder_bench_runs").fetchone()[0] == 0
    c.close()


# ─── 4. La précision est RELEVÉE, pas déclarée ───────────────────────────────


def test_la_precision_est_lue_sur_le_modele():
    """Un champ déclaré par l'appelant dirait « int8 » d'un modèle resté en
    fp32 sans que rien ne rougisse. `_quantization_of` lit les paramètres."""
    torch = pytest.importorskip("torch")
    from scripts.bench_encoder_dino import _quantization_of

    m = torch.nn.Linear(4, 4)
    assert _quantization_of(m) == "fp32"
    assert _quantization_of(m.half()) == "fp16"
    # Un modèle sans paramètre ne fait pas planter le banc en fin de course.
    assert _quantization_of(torch.nn.ReLU()) == "fp32"


def test_build_run_porte_la_precision_du_resultat_et_le_corpus_du_sidecar():
    """`eval_corpus` vient du sidecar du gold (`meta['eval_corpus']`), donc du
    manifeste FIGÉ — jamais d'une requête d'ici. Le gold doit rester relisible
    quand la base a bougé."""
    import scripts.bench_encoder_dino as bench

    result = {
        "model": "arcface:lab/iterations/392205b7f725/checkpoints/best_model.pth",
        "encoder_version": "arcface-392205b7f725", "n_in_scope": 260,
        "anchors": 1813, "n_bank_classes": 52, "dim": 256, "params_m": 2.2,
        "input_px": 224, "device": "mps", "ms_per_img": 1.0,
        "g1": 258, "g5": 260, "c1": 258, "c5": 260, "c_total": 260,
        "quantization": "fp16",
    }
    run = bench.build_run(
        result, run_id="m-1", created_at="2026-08-26T10:00:00Z",
        gold_version="9bc08e19b83c", gold_n_crops=260, gold_sample_n=None,
        blockers=["P1"], proposal_dict=None, sweep_json=None, bank_build_id=None,
        anchors_kind="matrice60", eval_corpus="matrice-encodeurs-2026-08",
    )
    assert run.quantization == "fp16"
    assert run.eval_corpus == "matrice-encodeurs-2026-08"

    # Sans corpus nommé (gold de review), la colonne reste NULL — et c'est une
    # information, pas un trou : « noté sur le gold de review ».
    revue = bench.build_run(
        result, run_id="m-2", created_at="2026-08-26T10:00:00Z",
        gold_version="0ecbb1d70e3c", gold_n_crops=1958, gold_sample_n=None,
        blockers=["P1"], proposal_dict=None, sweep_json=None, bank_build_id=None,
    )
    assert revue.eval_corpus is None


def test_le_sidecar_du_gold_deval_nomme_bien_le_corpus():
    """La source de `eval_corpus` côté banc. Si `eval_gold_extra` cessait de
    poser la clé, `meta.get('eval_corpus')` rendrait None sans un mot et tous
    les runs de la matrice redeviendraient indiscernables d'un run de review.
    """
    from review.eval_corpus_gold import eval_gold_extra

    extra = eval_gold_extra([], "matrice-encodeurs-2026-08")
    assert extra["eval_corpus"] == "matrice-encodeurs-2026-08"
