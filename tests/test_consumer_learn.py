"""House-delta outlier handling (four samples max, drop-one triple)."""

from __future__ import annotations

from energy_manager.const import CONSUMER_LEARN_SPREAD_MAX
from energy_manager.engine.house_delta_sample_math import best_triple_from_four


def test_best_triple_drops_single_outlier() -> None:
    """Classic case: one bad sample among four; remaining triple is tight."""
    four = [2.739, 2.832, 0.664, 2.73]
    out = best_triple_from_four(four, CONSUMER_LEARN_SPREAD_MAX)
    assert out is not None
    mean_kw, sp = out
    assert sp <= CONSUMER_LEARN_SPREAD_MAX
    assert 2.65 < mean_kw < 2.8


def test_best_triple_none_when_no_single_outlier() -> None:
    """No single drop leaves a triple within spread (e.g. ramp, not one bad point)."""
    four = [0.0, 1.0, 2.0, 3.0]
    assert best_triple_from_four(four, CONSUMER_LEARN_SPREAD_MAX) is None
