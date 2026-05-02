"""Mock source adapter for orchestrator tests.

Returns 5 fixed `DiscoveredItem` rows backed by the obverse.jpg of
real coins (numista_id 64, 80, 88, 96, 104) under `ml/datasets/`.
Used by `ml/tests/test_orchestrator.py` to validate the pipeline
without touching any external API.
"""

from sources._mock.adapter import MockAdapter, MOCK_FIXTURES

__all__ = ["MockAdapter", "MOCK_FIXTURES"]
