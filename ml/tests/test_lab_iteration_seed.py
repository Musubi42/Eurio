"""La graine du bake se pose explicitement — ou deux runs jumeaux n'en sont pas.

`POST /lab/cohorts/{id}/iterations` ne savait pas transporter
`augmentations_seed` : le runner en tirait une au hasard
(`iteration_runner._generate_seed`). Deux itérations censées ne différer
que d'un paramètre recevaient alors des augmentations différentes, et
tout écart mesuré entre elles mélangeait le facteur étudié et le tirage.
Cf. docs/work-in-progress/juge-et-banc/LOT4-PREPARATION.md.
"""
from tests.test_lab_api import client, _post_cohort  # noqa: F401


def test_route_transmet_le_seed_au_runner(client):
    c, store, stub = client
    seen = {}
    orig = stub.create_iteration

    def spy(**kw):
        seen.update(kw)
        return orig(**kw)

    stub.create_iteration = spy
    cohort = _post_cohort(client).json()
    r = c.post(f"/lab/cohorts/{cohort['id']}/iterations",
               json={"name": "run-a", "augmentations_seed": 20260825})
    assert r.status_code == 200, r.text
    assert seen["augmentations_seed"] == 20260825


def test_route_sans_seed_transmet_none(client):
    c, store, stub = client
    seen = {}
    orig = stub.create_iteration

    def spy(**kw):
        seen.update(kw)
        return orig(**kw)

    stub.create_iteration = spy
    cohort = _post_cohort(client, name="green-v2").json()
    r = c.post(f"/lab/cohorts/{cohort['id']}/iterations", json={"name": "run-x"})
    assert r.status_code == 200, r.text
    assert seen["augmentations_seed"] is None


def test_runner_reel_honore_le_seed(tmp_path):
    """Le vrai IterationRunner, pas le stub : le seed atterrit dans la row."""
    from store import Store, ExperimentCohortRow
    from serving.iteration_runner import IterationRunner
    from serving.training_runner import TrainingRunner
    store = Store(tmp_path / "t.db")
    store.create_cohort(ExperimentCohortRow(
        id="c1", name="c-one", description=None, zone=None,
        eurio_ids=["fr-2007"], status="draft", frozen_at=None))
    runner = IterationRunner(store, TrainingRunner(store))
    row = runner.create_iteration(
        cohort_id="c1", name="run-a", hypothesis=None,
        parent_iteration_id=None, recipe_id=None, variant_count=100,
        training_config={"epochs": 9}, augmentations_seed=20260825)
    assert store.get_iteration(row.id).augmentations_seed == 20260825
    row2 = runner.create_iteration(
        cohort_id="c1", name="run-b", hypothesis=None,
        parent_iteration_id=None, recipe_id=None, variant_count=100,
        training_config={"epochs": 9})
    assert store.get_iteration(row2.id).augmentations_seed != 20260825
