"""Le `--db` codé en dur — la régression du 2026-08-19, et ses frères.

`build_dino_anchors.py` bâtissait la banque sur `ml/state/eurio.db`, base de
travail **périmée**, au lieu de la base pointée par `EURIO_DB_PATH` (la
réplique sous Direction A). Mesuré ce jour-là :

    sqlite3 ml/state/eurio.db          "SELECT COUNT(*) FROM image_assets"  → 6205
    sqlite3 ml/state/eurio.replica.db  "SELECT COUNT(*) FROM image_assets"  → 12454

Conséquence : 125 classes avec exemplaires au lieu de 182. Le motif existait
encore dans dix scripts, dont `backfill_dino_predictions` (le backfill P3).

Ce fichier tient la ligne à deux niveaux :

1. **statique** (AST) — le défaut de `--db` de chaque script passe par
   `store.resolve_db_path`, jamais par un chemin littéral. Un AST plutôt qu'un
   `import` : plusieurs de ces scripts tirent torch/DINO à l'import.
2. **dynamique** — pour le script du backfill P3, on recharge réellement le
   module avec `EURIO_DB_PATH` posé et on vérifie la valeur résolue, plus le
   câblage argparse (`--db` explicite, `--db` ignoré sous `--push`).
"""

from __future__ import annotations

import ast
import importlib
import os
from pathlib import Path

import pytest

ML_DIR = Path(__file__).resolve().parent.parent
SCRIPTS = ML_DIR / "scripts"

# Le script du backfill P3 + les neuf frères audités le 2026-08-19.
CORRIGES = [
    "backfill_dino_predictions",
    "backfill_coin_source_status",
    "backfill_denom",
    "backfill_face",
    "backfill_text_signals",
    "bench_theme_match",
    "enrich_bench_images",
    "llm_coin_aliases",
    "mine_coin_aliases",
    "sweep_bce_empty_upstream",
]


def _db_path_assignment(module_name: str) -> ast.AST:
    """L'expression affectée à la constante `DB_PATH` du script, au niveau module."""
    tree = ast.parse((SCRIPTS / f"{module_name}.py").read_text(encoding="utf-8"))
    for node in tree.body:
        if isinstance(node, ast.Assign) and any(
            isinstance(t, ast.Name) and t.id == "DB_PATH" for t in node.targets
        ):
            return node.value
    raise AssertionError(f"{module_name}: pas de constante DB_PATH au niveau module")


@pytest.mark.parametrize("module_name", CORRIGES)
def test_le_defaut_de_db_passe_par_resolve_db_path(module_name):
    """Le défaut doit être `resolve_db_path(...)`, pas un chemin littéral.

    Rouge avant le correctif : `DB_PATH = ML_DIR / "state" / "eurio.db"` est un
    `ast.BinOp`, pas un `ast.Call` à `resolve_db_path`.
    """
    value = _db_path_assignment(module_name)
    assert isinstance(value, ast.Call), (
        f"{module_name}: DB_PATH est un chemin littéral "
        f"({ast.unparse(value)}) — il ignore EURIO_DB_PATH et pointe donc la "
        "base de travail périmée sous le devShell."
    )
    assert isinstance(value.func, ast.Name) and value.func.id == "resolve_db_path", (
        f"{module_name}: DB_PATH doit passer par store.resolve_db_path, "
        f"trouvé {ast.unparse(value.func)}"
    )


@pytest.mark.parametrize("module_name", CORRIGES)
def test_un_db_explicite_nest_jamais_repasse_par_le_resolver(module_name):
    """`Store(resolve_db_path(args.db))` fait de `--db` un leurre.

    `resolve_db_path` renvoie `EURIO_DB_PATH` **quel que soit** son argument :
    ré-appliquer le resolver à une valeur déjà choisie par l'opérateur écrase
    ce choix en silence. Le resolver n'a sa place que sur le DÉFAUT.
    """
    src = (SCRIPTS / f"{module_name}.py").read_text(encoding="utf-8")
    for node in ast.walk(ast.parse(src)):
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id == "resolve_db_path"
            and "args." in ast.unparse(node)
        ):
            raise AssertionError(
                f"{module_name}: {ast.unparse(node)} — le resolver écrase la "
                "valeur passée en --db dès que EURIO_DB_PATH est posé."
            )


# ── Niveau dynamique : le script du backfill P3 ──────────────────────────────


def test_backfill_p3_db_path_suit_eurio_db_path(monkeypatch, tmp_path):
    """Le vrai câblage, pas seulement le prédicat : on recharge le module."""
    import scripts.backfill_dino_predictions as bdp

    replique = tmp_path / "eurio.replica.db"
    monkeypatch.setenv("EURIO_DB_PATH", str(replique))
    module = importlib.reload(bdp)
    try:
        assert module.DB_PATH == replique
    finally:
        monkeypatch.delenv("EURIO_DB_PATH", raising=False)
        importlib.reload(bdp)


def test_backfill_p3_repli_sur_la_replique_sans_variable(monkeypatch):
    """Hors devShell (pas de variable), le repli est `ml/state/eurio.replica.db`.

    Arbitrage du 2026-08-19, argumenté dans la docstring de
    `store.resolve_db_path` : entre les deux replis possibles, celui-ci est le
    seul dont les DEUX issues sont bruyantes — un lecteur lit le vrai corpus
    (12454 assets, pas 6205), un écrivain se fait refuser par nom de fichier au
    constructeur de `Store`. Le repli `state/eurio.db` fait taire les deux.
    """
    import scripts.backfill_dino_predictions as bdp

    monkeypatch.delenv("EURIO_DB_PATH", raising=False)
    module = importlib.reload(bdp)
    assert module.DB_PATH == ML_DIR / "state" / "eurio.replica.db"


def test_tous_les_scripts_corriges_replient_sur_la_replique():
    """La convention est UNIQUE : aucun des dix ne peut diverger en douce.

    Test statique (AST) — `backfill_denom` / `backfill_face` tirent torch à
    l'import. On lit l'argument littéral passé à `resolve_db_path`.
    """
    fautifs = []
    for name in CORRIGES:
        tree = ast.parse((SCRIPTS / f"{name}.py").read_text(encoding="utf-8"))
        trouve = False
        for node in ast.walk(tree):
            if (isinstance(node, ast.Assign)
                    and any(getattr(t, "id", "") == "DB_PATH" for t in node.targets)
                    and isinstance(node.value, ast.Call)
                    and getattr(node.value.func, "id", "") == "resolve_db_path"):
                trouve = True
                if "eurio.replica.db" not in ast.unparse(node.value):
                    fautifs.append(f"{name}: {ast.unparse(node.value)}")
        if not trouve:
            fautifs.append(f"{name}: pas de DB_PATH = resolve_db_path(...)")
    assert fautifs == [], fautifs


def test_backfill_p3_aide_nomme_la_variable_et_la_valeur_resolue(monkeypatch, tmp_path):
    """L'aide de `--db` doit dire la valeur RÉELLEMENT résolue et nommer
    EURIO_DB_PATH — sinon l'opérateur croit lire `ml/state/eurio.db`."""
    import contextlib
    import io
    import sys

    import scripts.backfill_dino_predictions as bdp

    replique = tmp_path / "eurio.replica.db"
    monkeypatch.setenv("EURIO_DB_PATH", str(replique))
    module = importlib.reload(bdp)
    try:
        monkeypatch.setattr(sys, "argv", ["backfill_dino_predictions", "--help"])
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf), pytest.raises(SystemExit):
            module.main()
        # argparse enroule l'aide : on recolle avant de chercher le chemin.
        aide = "".join(buf.getvalue().split())
        assert "".join(str(replique).split()) in aide, (
            "l'aide doit annoncer la valeur résolue")
        assert "EURIO_DB_PATH" in aide, "l'aide doit nommer la variable"
    finally:
        monkeypatch.delenv("EURIO_DB_PATH", raising=False)
        importlib.reload(bdp)


def test_backfill_p3_ignore_db_sous_push_et_le_dit(monkeypatch, caplog):
    """Sous `--push`, `--db` n'est jamais ouvert : le script doit le DIRE.

    Sans ce message, un opérateur qui passe `--db /chemin/precis.db` croit
    avoir choisi la base alors que le backfill pull une réplique scratch —
    panne muette de la même famille que celle du jour.
    """
    import logging
    import sys

    import scripts.backfill_dino_predictions as bdp

    monkeypatch.setattr("client.http.sync_enabled", lambda: True)

    def _boom(**kwargs):
        raise _StopHere()

    monkeypatch.setattr("client.replica.pull_replica", _boom)
    monkeypatch.setattr(sys, "argv",
                        ["backfill_dino_predictions", "--db", "/tmp/choisie.db"])
    with caplog.at_level(logging.WARNING):
        with pytest.raises(_StopHere):
            bdp.main()
    messages = "\n".join(r.getMessage() for r in caplog.records)
    assert "/tmp/choisie.db" in messages
    assert "IGNOR" in messages.upper()


class _StopHere(Exception):
    """Sentinelle : on s'arrête avant le pull réseau."""


def test_aucun_script_corrige_ne_reste_sur_le_chemin_en_dur():
    """Filet global : le littéral ne doit plus servir de DÉFAUT dans ces dix."""
    coupables = []
    for name in CORRIGES:
        src = (SCRIPTS / f"{name}.py").read_text(encoding="utf-8")
        tree = ast.parse(src)
        for node in ast.walk(tree):
            if isinstance(node, ast.Call) and "Store(" in ast.unparse(node)[:6]:
                arg = ast.unparse(node)
                if 'state" / "eurio.db"' in arg or "state/eurio.db" in arg:
                    coupables.append(f"{name}: {arg}")
    assert coupables == [], coupables


def test_environnement_du_devshell_est_bien_celui_quon_croit():
    """Documente ce que le test suppose ; ne casse rien s'il tourne ailleurs."""
    env = os.environ.get("EURIO_DB_PATH", "")
    if env:
        assert env.endswith(".db"), env
