"""Cohérence de ``ml/tasks.yml`` et des messages d'aide qu'il ou le code citent.

Ces tests attrapent une famille précise de défauts : **une commande qui ment**.
Une tâche qui pointe un fichier inexistant, une tâche qui embarque un drapeau
destructeur en dur, un message d'aide qui nomme un package qui n'existe pas.
Aucun de ces défauts ne lève d'erreur là où on le lit — ils ne se manifestent
qu'au moment où on les exécute, souvent trop tard (cf. skill ``eurio-verify``).
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest
import yaml

ML_DIR = Path(__file__).resolve().parent.parent
TASKS_YML = ML_DIR / "tasks.yml"


def _tasks() -> dict:
    doc = yaml.safe_load(TASKS_YML.read_text())
    return doc.get("tasks", {})


def _cmd_strings(task: dict) -> list[str]:
    out: list[str] = []
    for cmd in task.get("cmds", []) or []:
        if isinstance(cmd, str):
            out.append(cmd)
    return out


# --------------------------------------------------------------------------
# A1 — `--clear` ne doit pas être embarqué en dur dans eval-real:sync
# --------------------------------------------------------------------------

def test_eval_real_sync_does_not_hardcode_clear():
    """``ml:eval-real:sync`` efface tout ``datasets/eval_real_norm/``.

    Avec ``--clear`` en dur, la relancer sur UN dossier de ``debug_pull/``
    détruit les captures normalisées de tous les autres. La destruction doit
    être un choix explicite de l'appelant, pas un effet de bord de la tâche.
    """
    task = _tasks()["eval-real:sync"]
    for cmd in _cmd_strings(task):
        assert "--clear" not in cmd, (
            "eval-real:sync embarque --clear en dur : relancer la tâche sur un "
            "seul debug_pull détruirait tout eval_real_norm/. Utiliser la tâche "
            "dédiée eval-real:sync:clear."
        )


def test_eval_real_sync_clear_variant_exists_and_is_labelled():
    """L'usage légitime (repartir propre) reste accessible, mais nommé."""
    tasks = _tasks()
    assert "eval-real:sync:clear" in tasks, (
        "la variante destructrice doit exister explicitement"
    )
    task = tasks["eval-real:sync:clear"]
    assert any("--clear" in c for c in _cmd_strings(task))
    desc = task.get("desc", "")
    assert "DESTRUCTIF" in desc.upper(), (
        "la desc doit dire que la tâche détruit — c'est ce que lit go-task -l"
    )


def _fake_pull(tmp_path):
    """Un debug_pull minimal — un seul _raw.jpg, jamais décodé (voir plus bas)."""
    src = tmp_path / "pull" / "eurio_debug" / "eval_real" / "fr-2007-2eur"
    src.mkdir(parents=True)
    (src / "step0_raw.jpg").write_bytes(b"not-a-real-jpeg")
    return tmp_path / "pull"


def test_sync_default_preserves_other_classes(tmp_path):
    """Le défaut de la FONCTION est additif : c'est le contrat sur lequel
    ``ml:eval-real:sync`` s'appuie désormais."""
    from vision.sync_eval_real import sync

    out = tmp_path / "eval_real_norm"
    stale = out / "es-2011-2eur"
    stale.mkdir(parents=True)
    (stale / "step9.jpg").write_bytes(b"precieux")

    sync(_fake_pull(tmp_path), output=out)
    assert (stale / "step9.jpg").exists(), (
        "sync() sans --clear ne doit RIEN effacer des classes déjà normalisées"
    )


def test_sync_clear_is_the_only_destructive_path(tmp_path):
    from vision.sync_eval_real import sync

    out = tmp_path / "eval_real_norm"
    stale = out / "es-2011-2eur"
    stale.mkdir(parents=True)
    (stale / "step9.jpg").write_bytes(b"precieux")

    sync(_fake_pull(tmp_path), output=out, clear=True)
    assert not stale.exists(), "clear=True doit bien effacer (usage légitime préservé)"


# --------------------------------------------------------------------------
# A2 — aucune tâche ne doit pointer un fichier / module inexistant
# --------------------------------------------------------------------------

_PY_FILE_RE = re.compile(r"\{\{\.VENV\}\}/python\s+([A-Za-z0-9_./-]+\.py)")
_PY_MODULE_RE = re.compile(r"\{\{\.VENV\}\}/python\s+-m\s+([A-Za-z0-9_.]+)")


def _module_exists(mod: str) -> bool:
    base = ML_DIR / Path(*mod.split("."))
    if base.with_suffix(".py").exists() or (base / "__init__.py").exists():
        return True
    try:  # module tiers installé dans le venv (uvicorn, pytest…)
        import importlib.util

        return importlib.util.find_spec(mod) is not None
    except (ImportError, ValueError, ModuleNotFoundError):
        return False


# Dette PRÉEXISTANTE, hors périmètre du correctif A2. Deux familles :
#   - les scripts one-shot de la migration référentiel v2 / chunks 3a-3f,
#     supprimés une fois joués, dont les tâches sont restées ;
#   - tout le répertoire `ml/eval/`, qui n'existe plus (6 tâches orphelines).
# Elles sont mortes de la même façon que scrape-ebay. `benchmark` et
# `confusion-map` sont, elles, des noms plausibles qu'on peut chercher à
# tâtons : elles mériteront le même panneau indicateur que scrape-ebay.
# Cette liste est un CLIQUET : elle ne doit que rétrécir. N'y ajoute rien.
_KNOWN_DEAD_TASKS = {
    "evaluate", "visualize", "confusion-map", "confusion-map-dry",
    "augment-preview", "benchmark", "benchmark:photos:check",
    "migrate-v2", "migrate-v2-dry",
    "apply-3a", "apply-3a-dry", "apply-3b", "apply-3b-dry",
    "apply-3c", "apply-3c-dry", "apply-3d", "apply-3d-dry",
    "apply-3f", "apply-3f-dry",
    "apply-3e-flag", "apply-3e-flag-dry",
    "apply-3e-enrich", "apply-3e-enrich-dry",
}


def _missing_targets() -> list[str]:
    missing: list[str] = []
    for name, task in _tasks().items():
        if not isinstance(task, dict) or name in _KNOWN_DEAD_TASKS:
            continue
        for cmd in _cmd_strings(task):
            for rel in _PY_FILE_RE.findall(cmd):
                if not (ML_DIR / rel).exists():
                    missing.append(f"{name}: fichier absent {rel}")
            for mod in _PY_MODULE_RE.findall(cmd):
                if not _module_exists(mod):
                    missing.append(f"{name}: module absent {mod}")
    return missing


def test_known_dead_task_list_only_shrinks():
    """Le cliquet lui-même : une entrée réparée doit sortir de la liste."""
    still_dead = set()
    for name in _KNOWN_DEAD_TASKS:
        task = _tasks().get(name)
        if not isinstance(task, dict):
            continue
        for cmd in _cmd_strings(task):
            for rel in _PY_FILE_RE.findall(cmd):
                if not (ML_DIR / rel).exists():
                    still_dead.add(name)
    stale = _KNOWN_DEAD_TASKS - still_dead
    assert not stale, (
        f"ces tâches ne sont plus mortes — retire-les de _KNOWN_DEAD_TASKS : {sorted(stale)}"
    )


def test_no_task_points_at_a_missing_script():
    """Une tâche morte est pire qu'une tâche absente : elle est *trouvable*.

    ``go-task ml:scrape-ebay`` était le nom le plus évident pour qui cherche à
    scraper eBay, et pointait un fichier supprimé. Le piège se refermait sur
    quiconque lisait ``go-task -l``.
    """
    missing = _missing_targets()
    assert not missing, "tâches pointant du code inexistant :\n  " + "\n  ".join(missing)


def test_scrape_ebay_signpost_names_the_right_door():
    """Si le nom mort est conservé, il doit échouer en nommant la bonne porte."""
    tasks = _tasks()
    if "scrape-ebay" not in tasks:
        pytest.skip("tâche supprimée — pas de panneau à vérifier")
    task = tasks["scrape-ebay"]
    blob = " ".join(_cmd_strings(task)) + " " + str(task.get("desc", ""))
    assert "ml:src:ebay:run" in blob, (
        "le panneau doit nommer ml:src:ebay:run (qui pose EURIO_CENSUS_RECOVER=1)"
    )
    assert any("exit 1" in c or "exit 2" in c for c in _cmd_strings(task)), (
        "le panneau doit ÉCHOUER, pas se contenter d'afficher un texte"
    )


# --------------------------------------------------------------------------
# A3 — plus aucune référence au package inexistant `scan.sync_eval_real`
# --------------------------------------------------------------------------

def test_no_reference_to_nonexistent_scan_package():
    """Il n'y a pas de ``ml/scan/`` — le module est ``vision.sync_eval_real``.

    Des messages d'aide (train_embedder, prepare_dataset) dictaient une
    commande qui ne peut qu'échouer en ``No module named scan``.
    """
    assert not (ML_DIR / "scan" / "__init__.py").exists(), (
        "si un package ml/scan/ existe désormais, ce test est à revoir"
    )
    offenders: list[str] = []
    for py in ML_DIR.rglob("*.py"):
        parts = set(py.parts)
        if {".venv", "__pycache__", "node_modules"} & parts:
            continue
        if py.name == Path(__file__).name:
            continue
        for i, line in enumerate(py.read_text(errors="ignore").splitlines(), 1):
            if "scan.sync_eval_real" in line:
                offenders.append(f"{py.relative_to(ML_DIR)}:{i}")
    assert not offenders, (
        "références au package inexistant `scan` :\n  " + "\n  ".join(offenders)
    )
