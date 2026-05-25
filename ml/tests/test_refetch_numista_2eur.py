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

from scripts.refetch_numista_2eur import (  # noqa: E402
    Fetcher, _extract_issues, main, parse_nids_file,
)


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


# ─── Fetcher / cache tests ────────────────────────────────────────────────


class FakeKM:
    """Stand-in pour KeyManager — appelle simplement fn(<dummy_key>, *args).
    Compte les appels pour permettre l'assertion."""
    def __init__(self, responses: dict[tuple, object]) -> None:
        # key = (fn_name, *args) → payload retourné
        self.responses = responses
        self.calls: list[tuple] = []

    def call(self, fn, *args):
        self.calls.append((fn.__name__, *args))
        return self.responses[(fn.__name__, *args)]


def test_extract_issues_normalizes_shape() -> None:
    assert _extract_issues([{"id": 1}, {"id": 2}]) == [{"id": 1}, {"id": 2}]
    assert _extract_issues({"issues": [{"id": 1}]}) == [{"id": 1}]
    assert _extract_issues({}) == []
    assert _extract_issues(None) == []  # type: ignore[arg-type]


def test_fetcher_writes_cache_on_miss(tmp_path: Path) -> None:
    type_payload = {"id": 999, "title": "Test"}
    issues_payload = [{"id": 1}, {"id": 2}]
    prices_1 = {"prices": [{"grade": "unc", "price": 5}]}
    prices_2 = {"prices": [{"grade": "unc", "price": 6}]}
    km = FakeKM({
        ("api_type_details", 999): type_payload,
        ("api_type_issues", 999): issues_payload,
        ("api_issue_prices", 999, 1): prices_1,
        ("api_issue_prices", 999, 2): prices_2,
    })
    fetcher = Fetcher(km, tmp_path, refresh=False)
    # Patch sleep pour pas attendre
    import scripts.refetch_numista_2eur as mod
    mod.REQUEST_DELAY_S = 0  # type: ignore[attr-defined]

    bundle = fetcher.fetch_nid(999)
    assert bundle is not None
    assert bundle.type_payload == type_payload
    assert bundle.issues_payload == issues_payload
    assert bundle.prices_by_iid == {1: prices_1, 2: prices_2}
    assert fetcher.stats.api_calls == 4  # type + issues + 2 prices
    assert fetcher.stats.cache_misses == 4

    # Cache files exist
    assert (tmp_path / "999" / "type.json").exists()
    assert (tmp_path / "999" / "issues.json").exists()
    assert (tmp_path / "999" / "prices_1.json").exists()
    assert (tmp_path / "999" / "prices_2.json").exists()


def test_fetcher_reads_cache_on_second_call(tmp_path: Path) -> None:
    km = FakeKM({
        ("api_type_details", 999): {"id": 999},
        ("api_type_issues", 999): [{"id": 1}],
        ("api_issue_prices", 999, 1): {"prices": []},
    })
    import scripts.refetch_numista_2eur as mod
    mod.REQUEST_DELAY_S = 0  # type: ignore[attr-defined]

    # First fetch populates cache
    Fetcher(km, tmp_path, refresh=False).fetch_nid(999)

    # Second fetch with empty KM (no responses) → should hit cache only
    fetcher2 = Fetcher(FakeKM({}), tmp_path, refresh=False)
    bundle = fetcher2.fetch_nid(999)
    assert bundle is not None
    assert fetcher2.stats.api_calls == 0
    assert fetcher2.stats.cache_hits == 3


def test_fetcher_refresh_skips_cache(tmp_path: Path) -> None:
    (tmp_path / "999").mkdir()
    (tmp_path / "999" / "type.json").write_text('{"stale": true}')
    (tmp_path / "999" / "issues.json").write_text("[]")
    fresh = {"id": 999, "title": "Fresh"}
    km = FakeKM({
        ("api_type_details", 999): fresh,
        ("api_type_issues", 999): [],
    })
    import scripts.refetch_numista_2eur as mod
    mod.REQUEST_DELAY_S = 0  # type: ignore[attr-defined]

    fetcher = Fetcher(km, tmp_path, refresh=True)
    bundle = fetcher.fetch_nid(999, skip_prices=True)
    assert bundle is not None
    assert bundle.type_payload == fresh  # not the stale one
    assert fetcher.stats.api_calls == 2


def test_fetcher_skip_prices(tmp_path: Path) -> None:
    km = FakeKM({
        ("api_type_details", 999): {"id": 999},
        ("api_type_issues", 999): [{"id": 1}, {"id": 2}],
    })
    import scripts.refetch_numista_2eur as mod
    mod.REQUEST_DELAY_S = 0  # type: ignore[attr-defined]

    bundle = Fetcher(km, tmp_path).fetch_nid(999, skip_prices=True)
    assert bundle is not None
    assert bundle.prices_by_iid == {}


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
    assert "SCAFFOLD" in out
