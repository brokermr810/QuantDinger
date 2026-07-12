from __future__ import annotations

import pytest

from tests.helpers.backtest_stress_cases import default_stress_scenarios, run_scenario


@pytest.mark.parametrize("scenario", default_stress_scenarios(), ids=lambda s: s.name)
def test_complex_backtest_scenarios_complete_with_valid_results(scenario):
    summary = run_scenario(scenario)

    assert summary["fills"] >= scenario.min_fills
    assert summary["orders"] >= summary["fills"]
    assert summary["seconds"] <= scenario.max_seconds
