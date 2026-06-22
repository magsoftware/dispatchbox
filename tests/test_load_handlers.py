"""Tests for synthetic load-test handlers."""

from unittest.mock import patch

import pytest

from load_tests.handlers import SyntheticHandler


@pytest.mark.parametrize(
    ("kwargs", "message"),
    [
        ({"delay_ms": -1}, "delay_ms"),
        ({"jitter_ms": -1}, "jitter_ms"),
        ({"failure_rate": -0.1}, "failure_rate"),
        ({"failure_rate": 1.1}, "failure_rate"),
    ],
)
def test_synthetic_handler_validates_configuration(kwargs, message):
    with pytest.raises(ValueError, match=message):
        SyntheticHandler(**kwargs)


def test_synthetic_handler_noop_does_not_sleep():
    handler = SyntheticHandler()

    with patch("load_tests.handlers.time.sleep") as sleep:
        handler({"loadId": 1})

    sleep.assert_not_called()


def test_synthetic_handler_applies_delay_and_jitter():
    handler = SyntheticHandler(delay_ms=10, jitter_ms=5)

    with patch("load_tests.handlers.random.uniform", return_value=5):
        with patch("load_tests.handlers.time.sleep") as sleep:
            handler({"loadId": 1})

    sleep.assert_called_once_with(0.015)


def test_synthetic_handler_can_fail():
    handler = SyntheticHandler(failure_rate=0.5)

    with patch("load_tests.handlers.random.random", return_value=0.1):
        with pytest.raises(RuntimeError, match="Synthetic load-test failure"):
            handler({"loadId": 1})
