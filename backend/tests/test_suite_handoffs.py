"""The 25 COAST test jobs (see suite_scenarios.py), one pytest case each."""

import pytest

from tests.suite_scenarios import SCENARIOS, Suite


@pytest.mark.parametrize("sc", SCENARIOS, ids=[f"{s.n:02d}-{s.job}" for s in SCENARIOS])
def test_scenario(client, db, sc):
    sc.run(Suite(client, db))
