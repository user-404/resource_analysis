import pytest

from app.recommendations import recommend


def test_peak_recommendation_rounds_cpu_and_memory_up():
    assert recommend(0.101, 0.8, 1.2, 0.001) == (0.127, 0.127)
    assert recommend(10.5 * 1024**2, 0.8, 1.2, 1024**2) == (14 * 1024**2, 14 * 1024**2)


def test_missing_usage_does_not_produce_recommendations():
    assert recommend(None, 0.8, 1.2, 0.001) == (None, None)


@pytest.mark.parametrize("bad_target", [0, -0.1, 1.1])
def test_recommendation_formula_requires_valid_target(bad_target):
    with pytest.raises(ValueError):
        recommend(1.0, bad_target, 1.2, 0.001)
