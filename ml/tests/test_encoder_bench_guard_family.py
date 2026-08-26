"""M2 — la FAMILLE « un garde qui ne garde pas », fermée par un invariant.

En deux jours, quatre instances du même défaut ont été trouvées sur le même
garde (``store.encoder_bench.calibration_blockers``) :

* **D1 volet P3** — le garde se taisait pour un encodeur candidat (aucune ligne
  de build ⇒ tout le bloc sauté) ;
* **D1 volet P1** — le même garde comptait les références sans prédicat
  d'encodeur ;
* **M1** — le correctif du volet P1 s'appuie sur une contrainte d'unicité
  inexistante (autre lot) ;
* **M2** — ``POST /ingest/encoder-bench`` n'appelait **aucun** garde et
  recopiait ``provisional`` depuis le corps HTTP.

Ce n'est pas quatre bugs, c'est **une faiblesse de conception** : le garde
était branché sur *le chemin qu'on avait en tête* (le CLI du banc), jamais sur
*le chemin réellement emprunté*. Corriger l'instance suivante ne suffira pas —
il en apparaîtra une cinquième.

Ce fichier ferme la famille en deux temps, et il faut les deux :

1. **L'invariant** — ``record_run`` refuse d'écrire ``provisional=0`` dans une
   base qui mesure des bloqueurs. Le garde n'est plus une politesse
   d'appelant : c'est une propriété de la porte. Un cinquième chemin écrit
   demain hérite du garde sans que son auteur y pense.
2. **L'inventaire** — ``record_run`` est prouvé être la SEULE porte. Un
   `INSERT` direct dans ``encoder_bench_runs`` contournerait l'invariant ; le
   test énumère par AST tous les appelants et tous les SQL d'écriture de la
   table, et échoue sur tout nouvel entrant non déclaré ici.

L'un sans l'autre est un demi-garde : l'invariant seul se contourne par un
`INSERT`, l'inventaire seul se contente de compter les portes sans les fermer.
"""

from __future__ import annotations

import ast
import re
import sqlite3
import sys
from pathlib import Path

ML_DIR = Path(__file__).parent.parent
if str(ML_DIR) not in sys.path:
    sys.path.insert(0, str(ML_DIR))

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from serving.auth_principal import Principal, require_principal
from store import Store
from store.encoder_bench import (
    SCHEMA_SQL,
    ensure_schema,
    CalibrationNotVerified,
    EncoderBenchPrediction,
    EncoderBenchRun,
    measured_blockers,
    record_predictions,
    record_run,
)

# ─── Le run de la sonde M2, tel qu'il a été soumis à la vraie route ──────────
#
# Sonde du 2026-08-20, base ``mkdtemp``, vraie route FastAPI. AVANT correctif :
#   HTTP 200 · en base {'provisional': 0, 'provisional_reason': None,
#                       'gold_sample_n': 99999, 'n_paired': 1, 'recall1': 0.99}
# Le même triplet soumis à ``calibration_blockers`` rendait QUATRE bloqueurs —
# P3 (aucun build tracé), P1 (0 classe à exemplaires), « echantillon: run sur
# 99999 crops sur les 1958 du gold », « apparie: seulement 1 crops communs … ».
# Le garde avait la bonne réponse, personne ne le consultait.
_RUN_FORGE = {
    "run_id": "forge-1",
    "created_at": "2026-08-20T10:00:00Z",
    "gold_version": "0ecbb1d70e3c",
    "gold_n_crops": 1958,
    "gold_sample_n": 99999,
    "anchors_kind": "2eur_all",
    "encoder_spec": "timm:vit_small_patch16_dinov3.lvd1689m",
    "encoder_version": "dinov3-vits16",
    "n_in_scope": 1900,
    "baseline_run_id": "une-baseline",
    "n_paired": 1,
    "recall1": 0.99,
    "provisional": 0,
}


@pytest.fixture()
def conn(tmp_path) -> sqlite3.Connection:
    """Une base nue : aucun build d'ancres, aucune référence — donc bloquée.

    C'est l'état d'une base de test, et c'est aussi celui d'un encodeur
    CANDIDAT au canonique. Les deux doivent bloquer, pour la même raison :
    ce qui n'est pas mesurable n'est pas promouvable.
    """
    c = sqlite3.connect(tmp_path / "t.db")
    # `ensure_schema` : depuis 0015 le DDL de la table n'est plus dans une
    # seule migration (deux ALTER), et `SCHEMA_SQL` n'en porte que la 0009.
    ensure_schema(c)
    return c


def _principal(scopes):
    return Principal(
        user_id="t", email="t@test.local", roles=["owner"],
        scopes=set(scopes), auth_method="api_token",
    )


@pytest.fixture()
def http(tmp_path):
    from serving import ingest_routes

    store = Store(tmp_path / "api.db")
    c = store._connection()  # noqa: SLF001
    ensure_schema(c)
    ingest_routes.bind(store)
    app = FastAPI()
    app.include_router(ingest_routes.router)
    app.dependency_overrides[require_principal] = lambda: _principal({"ingest:write"})
    return c, TestClient(app)


# ─── 1. L'invariant, sur chacun des chemins d'écriture connus ────────────────


def test_le_store_refuse_un_run_promouvable_que_la_base_contredit(conn):
    """Chemin « appel direct au store » — celui qu'aucun garde ne couvrait.

    C'est le chemin le plus court et le moins surveillé : un script d'analyse,
    un notebook, un futur import de runs archivés. Avant M2, il écrivait
    ``provisional=0`` sans que rien ne le mesure.
    """
    with pytest.raises(CalibrationNotVerified) as exc:
        record_run(conn, EncoderBenchRun(**_RUN_FORGE))
    assert exc.value.run_id == "forge-1"
    assert any(b.startswith("P3:") for b in exc.value.blockers), exc.value.blockers
    assert any("echantillon" in b for b in exc.value.blockers), exc.value.blockers
    # Et surtout : RIEN n'a été écrit. Un garde qui lève après l'INSERT ne
    # garde rien.
    assert conn.execute("SELECT COUNT(*) FROM encoder_bench_runs").fetchone()[0] == 0


def test_un_run_provisoire_passe_sans_mesure(conn):
    """Contre-épreuve : l'invariant ne bloque pas tout, il bloque le mensonge.

    Sans ce test, « ça lève toujours » passerait pour un garde.
    """
    record_run(conn, EncoderBenchRun(**dict(_RUN_FORGE, provisional=1)))
    assert conn.execute(
        "SELECT provisional FROM encoder_bench_runs WHERE run_id='forge-1'"
    ).fetchone()[0] == 1


def test_la_route_http_ne_peut_plus_declarer_un_run_promouvable(http):
    """Chemin HTTP — la sonde M2, rejouée contre la vraie route.

    Le geste attendu n'est PAS un 4xx (cf. le docstring de la route : sous
    Direction A l'appelant mesure sur une réplique en retard, refuser ferait
    perdre des heures de GPU pour un champ que le serveur recalcule seul).
    C'est une correction, dans le sens sûr (0 → 1), rendue visible dans la
    réponse ET dans les logs.
    """
    c, client = http
    r = client.post(
        "/ingest/encoder-bench", json={"run": _RUN_FORGE, "predictions": []}
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["provisional"] == 1, body
    assert any("provisional: declare 0" in x for x in body["corrections"]), body
    assert body["blockers"], body

    row = c.execute(
        "SELECT provisional, provisional_reason, recall1 "
        "  FROM encoder_bench_runs WHERE run_id='forge-1'"
    ).fetchone()
    assert row["provisional"] == 1
    assert row["provisional_reason"], "corrige sans dire pourquoi = panne muette"
    # Le reste du run — ce que le serveur ne sait pas recalculer — est gardé.
    assert row["recall1"] == 0.99


def test_la_correction_est_journalisee(http, caplog):
    """Une correction que personne ne voit passer est la même maladie, d'un cran.

    La réponse sert l'appelant ; le log sert l'exploitant qui relit un ingest
    d'il y a trois jours. Les deux, ou rien.
    """
    _c, client = http
    with caplog.at_level("WARNING"):
        client.post(
            "/ingest/encoder-bench", json={"run": _RUN_FORGE, "predictions": []}
        )
    assert any(
        "forge-1" in r.getMessage() and "provisional" in r.getMessage()
        for r in caplog.records
    ), [r.getMessage() for r in caplog.records]


def test_le_serveur_recompte_n_paired_au_lieu_de_le_croire(http):
    """``paired_overlap`` enfin appelée — c'était exactement son usage.

    Écrite pour « vérifier un run déjà poussé, y compris un run dont le
    ``n_paired`` déclaré serait faux », elle n'avait aucun appelant :
    ``grep -rn paired_overlap ml/scripts ml/serving ml/store ml/client`` ne
    rendait que sa définition et sa docstring.
    """
    c, client = http
    preds = [
        {"asset_id": f"a{i}", "truth_class_id": "fr-2eur", "correct": 1, "in_top5": 1}
        for i in range(4)
    ]
    client.post(
        "/ingest/encoder-bench",
        json={
            "run": dict(
                _RUN_FORGE, run_id="base-1", baseline_run_id=None, n_paired=None,
                provisional=1,
            ),
            "predictions": preds,
        },
    )
    r = client.post(
        "/ingest/encoder-bench",
        json={
            "run": dict(_RUN_FORGE, baseline_run_id="base-1", n_paired=1),
            "predictions": preds[:3],
        },
    )
    assert r.status_code == 200, r.text
    assert any("n_paired: declare 1, mesure 3" in x for x in r.json()["corrections"]), (
        r.json()
    )
    assert c.execute(
        "SELECT n_paired FROM encoder_bench_runs WHERE run_id='forge-1'"
    ).fetchone()[0] == 3


def test_overlap_non_mesurable_ne_se_fait_pas_passer_pour_zero(conn):
    """Le piège symétrique : ``paired_overlap`` rend 0 pour « disjoints » ET
    pour « pas de prédictions en base ».

    La route accepte ``predictions: []`` (D9). Prendre ce 0 pour une mesure
    déclarerait « recouvrement nul » un run parfaitement apparié dont on n'a
    simplement pas repoussé les prédictions — la panne muette de D16, à
    l'envers. D'où ``measured_overlap`` → ``None`` = non mesurable.
    """
    from store.encoder_bench import measured_overlap

    assert measured_overlap(conn, "forge-1", "base-1") is None
    record_predictions(conn, "forge-1", [
        EncoderBenchPrediction("a1", "fr-2eur", 1, 1),
    ])
    assert measured_overlap(conn, "forge-1", "base-1") is None  # baseline vide
    record_predictions(conn, "base-1", [
        EncoderBenchPrediction("a1", "fr-2eur", 1, 1),
        EncoderBenchPrediction("a2", "fr-2eur", 1, 1),
    ])
    assert measured_overlap(conn, "forge-1", "base-1") == 1


def test_le_cli_derive_provisional_de_la_mesure_pas_de_l_option(conn):
    """Chemin CLI — ``build_run`` n'invente pas son verdict, il le reçoit.

    Le CLI reste correct depuis D4 ; ce test le tient DANS l'inventaire, pour
    que sa régression tombe ici avec les autres et pas seule dans un fichier
    voisin.
    """
    import scripts.bench_encoder_dino as bench

    result = {
        "model": "timm:vit_small_patch16_dinov3.lvd1689m",
        "encoder_version": "dinov3-vits16", "n_in_scope": 2, "anchors": 1533,
        "n_bank_classes": 671, "dim": 384, "params_m": 21.0, "input_px": 224,
        "device": "cpu", "ms_per_img": 1.0, "g1": 1, "g5": 2, "c1": 1, "c5": 2,
        "c_total": 2,
    }
    commun = dict(
        run_id="cli-1", created_at="2026-08-20T10:00:00Z",
        gold_version="0ecbb1d70e3c", gold_n_crops=1958, gold_sample_n=None,
        proposal_dict=None, sweep_json=None, bank_build_id=None,
    )
    bloque = bench.build_run(result, blockers=["P3: rien de trace"], **commun)
    assert bloque.provisional == 1 and bloque.provisional_reason
    libre = bench.build_run(result, blockers=[], **commun)
    assert libre.provisional == 0
    # …et ce ``provisional=0`` ne franchit toujours pas la porte si la base de
    # DESTINATION, elle, mesure des bloqueurs. C'est tout l'intérêt d'un
    # invariant côté store : le CLI mesure sur la réplique, le canonique
    # tranche.
    with pytest.raises(CalibrationNotVerified):
        record_run(conn, libre)


# ─── 2. L'inventaire : prouver que ``record_run`` est la SEULE porte ─────────

#: Les chemins d'écriture de ``encoder_bench_runs`` connus au 2026-08-20, avec
#: la raison pour laquelle chacun est acceptable. Toute entrée nouvelle fait
#: échouer le test : c'est le point. Ajouter une ligne ici est un geste
#: délibéré qui oblige à répondre « ce chemin passe-t-il par l'invariant ? ».
INVENTAIRE_ATTENDU: dict[str, set[str]] = {
    # LA porte. Le seul SQL d'écriture de la table, et le lieu de l'invariant.
    "store/encoder_bench.py": {"sql"},
    # La route HTTP : construit un run depuis le corps, le fait mesurer par
    # ``measured_blockers``, corrige, puis passe par ``record_run``.
    "serving/ingest_routes.py": {"EncoderBenchRun", "record_run"},
    # Le CLI du banc : construit le run et le POSTe. N'écrit jamais en local
    # (Direction A — la réplique est en lecture seule).
    "scripts/bench_encoder_dino.py": {"EncoderBenchRun"},
}

_SQL_ECRITURE = re.compile(
    r"\b(insert|update|replace|delete)\b[\s\S]*\bencoder_bench_runs\b", re.I
)


def _sources_du_produit() -> list[Path]:
    """Tout le Python de ``ml/``, sauf les tests et le venv.

    Les tests sont exclus À DESSEIN : ils ont le droit de fabriquer des runs.
    C'est le code de production qui doit n'avoir qu'une porte.
    """
    out = []
    for f in sorted(ML_DIR.rglob("*.py")):
        rel = f.relative_to(ML_DIR).as_posix()
        if rel.startswith((".venv/", "tests/", "build/")) or "/.venv/" in rel:
            continue
        out.append(f)
    return out


def _importe_du_store(tree: ast.AST) -> tuple[set[str], set[str]]:
    """``(noms importés depuis store.encoder_bench, alias du module)``.

    Sans cette résolution, l'inventaire confondrait
    ``store.encoder_bench.record_run`` avec ``state.sources_runs.record_run``
    — homonyme appelé par onze scrapers, qui n'a rien à voir avec le banc.
    """
    noms: set[str] = set()
    alias: set[str] = set()
    for n in ast.walk(tree):
        if isinstance(n, ast.ImportFrom):
            module = n.module or ""
            vise_le_module = module.endswith("store.encoder_bench") or (
                module == "encoder_bench" and (n.level or 0) > 0
            )
            if vise_le_module:
                noms |= {a.asname or a.name for a in n.names}
            elif module in ("store", ""):
                for a in n.names:
                    if a.name == "encoder_bench":
                        alias.add(a.asname or a.name)
        elif isinstance(n, ast.Import):
            for a in n.names:
                if a.name.endswith("store.encoder_bench"):
                    alias.add(a.asname or a.name.split(".")[-1])
    return noms, alias


def _inventaire_reel() -> dict[str, set[str]]:
    trouve: dict[str, set[str]] = {}
    for f in _sources_du_produit():
        rel = f.relative_to(ML_DIR).as_posix()
        try:
            tree = ast.parse(f.read_text(encoding="utf-8"))
        except SyntaxError:  # pragma: no cover — un fichier cassé se voit ailleurs
            continue
        noms, alias = _importe_du_store(tree)
        kinds: set[str] = set()
        for n in ast.walk(tree):
            if isinstance(n, ast.Call):
                fn = n.func
                if isinstance(fn, ast.Name) and fn.id in noms:
                    if fn.id in ("record_run", "EncoderBenchRun"):
                        kinds.add(fn.id)
                elif (
                    isinstance(fn, ast.Attribute)
                    and isinstance(fn.value, ast.Name)
                    and fn.value.id in alias
                    and fn.attr in ("record_run", "EncoderBenchRun")
                ):
                    kinds.add(fn.attr)
            elif isinstance(n, ast.Constant) and isinstance(n.value, str):
                if _SQL_ECRITURE.search(n.value):
                    kinds.add("sql")
        if kinds:
            trouve[rel] = kinds
    return trouve


def test_inventaire_des_chemins_d_ecriture_d_un_run():
    """Le test qui fait échouer le CINQUIÈME chemin, celui de demain.

    Il ne cherche pas à deviner si un nouveau chemin est correct — c'est
    impossible à automatiser. Il rend impossible de l'ajouter **sans le
    remarquer** : le message dit quoi vérifier, et l'invariant de
    ``record_run`` fait le reste.
    """
    reel = _inventaire_reel()
    assert reel == INVENTAIRE_ATTENDU, (
        "l'inventaire des chemins d'ecriture de encoder_bench_runs a bouge.\n"
        f"  attendu : {INVENTAIRE_ATTENDU}\n"
        f"  trouve  : {reel}\n"
        "Si c'est un nouveau chemin legitime : verifie qu'il passe par "
        "store.encoder_bench.record_run (jamais un INSERT direct — ce serait "
        "le seul moyen de contourner l'invariant de calibration), puis "
        "declare-le dans INVENTAIRE_ATTENDU avec sa raison. Cf. FINDINGS §M2."
    )


def test_le_seul_sql_d_ecriture_vit_dans_le_store():
    """Corollaire, dit séparément parce que c'est LUI qui tient l'invariant.

    Un ``INSERT INTO encoder_bench_runs`` ailleurs contournerait ``record_run``
    et donc le garde, sans rien casser d'autre : exactement la forme qu'ont
    prises les quatre instances précédentes.
    """
    porteurs = {rel for rel, k in _inventaire_reel().items() if "sql" in k}
    assert porteurs == {"store/encoder_bench.py"}, porteurs


def test_l_invariant_est_dans_record_run_pas_chez_les_appelants(conn):
    """Le test le plus important du fichier : la propriété, formulée une fois.

    « Aucun chemin ne peut produire une ligne ``provisional=0`` sans être passé
    par ``calibration_blockers`` » se démontre ainsi : (a) toute écriture passe
    par ``record_run`` — les deux tests d'inventaire ci-dessus ; (b)
    ``record_run`` mesure lui-même dès que ``provisional=0``. Ici, (b), sans
    passer par aucun appelant.
    """
    from store import encoder_bench as eb

    appels: list[dict] = []
    vrai = eb.calibration_blockers

    def espion(c, **kw):
        appels.append(kw)
        return vrai(c, **kw)

    eb.calibration_blockers = espion
    try:
        with pytest.raises(CalibrationNotVerified):
            eb.record_run(conn, EncoderBenchRun(**_RUN_FORGE))
    finally:
        eb.calibration_blockers = vrai

    assert len(appels) == 1, appels
    # Et il mesure sur le COUPLE du run, pas sur un couple par défaut : c'est
    # le volet P1/P3 de D1 qui se rejouerait sinon.
    assert appels[0]["anchors_kind"] == "2eur_all"
    assert appels[0]["encoder_version"] == "dinov3-vits16"


def test_measured_blockers_ignore_le_declaratif_du_payload(conn):
    """Le payload ne fait foi sur AUCUN champ que la base sait mesurer.

    ``provisional`` / ``provisional_reason`` sont des affirmations d'appelant :
    les lire pour décider s'il faut vérifier serait un garde qui demande la
    permission au suspect.
    """
    menteur = EncoderBenchRun(
        **dict(_RUN_FORGE, provisional=0, provisional_reason="rien a signaler")
    )
    blockers = measured_blockers(conn, menteur)
    assert blockers and all("rien a signaler" not in b for b in blockers)


def test_le_banc_rapporte_la_correction_faite_par_le_canonique(monkeypatch):
    """La boucle refermée côté appelant : deux vérités, une seule visible.

    Le banc imprime sa bannière à partir des bloqueurs mesurés sur LA
    RÉPLIQUE. Le canonique, lui, mesure sur une base fraîche et peut démoter
    le run. Sans remontée, l'opérateur lit « ✔ CALIBRATION PROMOUVABLE » dans
    son terminal pendant que la table dit ``provisional=1`` — et rien nulle
    part ne dit qu'ils se contredisent. C'est la forme exacte du motif que ce
    fichier ferme, déplacée d'un cran vers l'appelant.
    """
    import scripts.bench_encoder_dino as bench
    from client import ingest as client_ingest

    monkeypatch.setattr(
        client_ingest, "push_encoder_bench",
        lambda run, preds: {
            "run_id": run["run_id"], "provisional": 1,
            "corrections": ["provisional: declare 0, corrige a 1 — 4 bloqueur(s)"],
        },
    )
    pousse, dump, message = bench.push_run(
        EncoderBenchRun(**dict(_RUN_FORGE, provisional=0)), []
    )
    assert pousse and dump is None
    assert "CORRIGÉ PAR LE CANONIQUE" in message, message
    assert "corrige a 1" in message, message


def test_le_banc_reste_silencieux_quand_le_canonique_ne_corrige_rien(monkeypatch):
    """Contre-épreuve : l'avertissement ne s'imprime pas à tous les runs."""
    import scripts.bench_encoder_dino as bench
    from client import ingest as client_ingest

    monkeypatch.setattr(
        client_ingest, "push_encoder_bench",
        lambda run, preds: {"run_id": run["run_id"], "provisional": 1, "corrections": []},
    )
    _pousse, _dump, message = bench.push_run(EncoderBenchRun(**_RUN_FORGE), [])
    assert "CORRIGÉ" not in message, message
