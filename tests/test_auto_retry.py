"""Auto-retry budget logic (up to 3 rounds per batch)."""
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))

from BatchSimLab import _should_auto_retry, _MAX_AUTO_RETRIES


class TestShouldAutoRetry:
    def test_no_errors_no_retry(self):
        assert _should_auto_retry(0, True, 0) is False

    def test_disabled_no_retry(self):
        assert _should_auto_retry(5, False, 0) is False

    def test_first_round_fires(self):
        assert _should_auto_retry(2, True, 0) is True

    def test_within_budget_fires(self):
        # rounds 0,1,2 already counted still leave budget while < max
        assert _should_auto_retry(1, True, 1) is True
        assert _should_auto_retry(1, True, 2) is True

    def test_budget_exhausted_stops(self):
        assert _should_auto_retry(1, True, _MAX_AUTO_RETRIES) is False
        assert _should_auto_retry(1, True, _MAX_AUTO_RETRIES + 1) is False

    def test_default_budget_is_three(self):
        assert _MAX_AUTO_RETRIES == 3

    def test_custom_max(self):
        assert _should_auto_retry(1, True, 1, max_retries=1) is False
        assert _should_auto_retry(1, True, 0, max_retries=1) is True
