"""Tests pour `ml/scripts/refetch_numista_2eur.py` — P.7a scaffold.

Couvre :
* parse_nids_file : lignes pures, commentaires inline, lignes vides,
  fichiers manquants, NIDs invalides, doublons.
* main() : exit codes (missing file, empty file, OK).
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

ML_DIR = Path(__file__).resolve().parent.parent
if str(ML_DIR) not in sys.path:
    sys.path.insert(0, str(ML_DIR))

from scripts.refetch_numista_2eur import main, parse_nids_file  # noqa: E402


def _write(tmp_path: Path, content: str) -> Path:
    p = tmp_path / "nids.txt"
    p.write_text(content)
    return p


def test_parse_nids_minimal(tmp_path: Path) -> None:
    f = _write(tmp_path, "1\n2\n3\n")
    assert parse_nids_file(f) == [1, 2, 3]


def test_parse_nids_inline_comments(tmp_path: Path) -> None:
    content = """\
# Cohort header
68395    # ad-2014-2eur-standard
64       # at-2002-2eur-standard

# blank line above + section header below
2193     # at-2005-2eur-50th-anniversary
"""
    assert parse_nids_file(_write(tmp_path, content)) == [68395, 64, 2193]


def test_parse_nids_empty_file(tmp_path: Path) -> None:
    assert parse_nids_file(_write(tmp_path, "")) == []


def test_parse_nids_only_comments(tmp_path: Path) -> None:
    assert parse_nids_file(_write(tmp_path, "# foo\n# bar\n\n")) == []


def test_parse_nids_invalid_value(tmp_path: Path) -> None:
    f = _write(tmp_path, "123\nabc\n")
    with pytest.raises(ValueError, match=":2:"):
        parse_nids_file(f)


def test_parse_nids_duplicate(tmp_path: Path) -> None:
    f = _write(tmp_path, "42\n43\n42\n")
    with pytest.raises(ValueError, match="duplicate NID 42"):
        parse_nids_file(f)


def test_parse_nids_missing_file(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError):
        parse_nids_file(tmp_path / "nope.txt")


def test_parse_real_cohort_file() -> None:
    """Le fichier cohorte committé doit être parseable et contenir 19 NIDs."""
    cohort = ML_DIR / "state" / "cohort_validation_19.txt"
    nids = parse_nids_file(cohort)
    assert len(nids) == 19
    # Quelques NIDs canoniques (cf. ROADMAP-DB.md §6) :
    assert 68395 in nids  # Andorre 2014 standard
    assert 10069 in nids  # Bremen cas-fil-rouge
    assert 134283 in nids  # Bleuet coloured
    assert 2162 in nids   # Treaty of Rome 2007 DE


def test_main_missing_file(tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
                           capsys: pytest.CaptureFixture[str]) -> None:
    monkeypatch.setattr(
        "sys.argv",
        ["refetch_numista_2eur", "--nids-file", str(tmp_path / "nope.txt")],
    )
    assert main() == 1
    assert "not found" in capsys.readouterr().err.lower()


def test_main_empty_file(tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
                         capsys: pytest.CaptureFixture[str]) -> None:
    f = _write(tmp_path, "# only comments\n")
    monkeypatch.setattr(
        "sys.argv",
        ["refetch_numista_2eur", "--nids-file", str(f)],
    )
    assert main() == 1
    assert "no nids" in capsys.readouterr().out.lower()


def test_main_dry_run_ok(tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
                        capsys: pytest.CaptureFixture[str]) -> None:
    f = _write(tmp_path, "10069\n134283\n")
    monkeypatch.setattr(
        "sys.argv",
        ["refetch_numista_2eur", "--nids-file", str(f), "--skip-images"],
    )
    assert main() == 0
    out = capsys.readouterr().out
    assert "NIDs to fetch              : 2" in out
    assert "P.7a SCAFFOLD" in out
