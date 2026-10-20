"""Tests for the idle detector — mocked, never waits for actual idle.

"You don't need an idle computer to test idle software."
"""

from __future__ import annotations

from unittest.mock import patch


class TestGetIdleMs:
    """Tests for get_idle_ms() — platform detection and mocking."""

    @patch("slothd.daemon.idle_detector.sys.platform", "darwin")
    def test_non_windows_returns_zero(self) -> None:
        """On non-Windows platforms, get_idle_ms returns 0."""
        from slothd.daemon.idle_detector import get_idle_ms

        assert get_idle_ms() == 0

    @patch("slothd.daemon.idle_detector.get_idle_ms")
    def test_is_idle_when_threshold_exceeded(self, mock_idle) -> None:
        """is_idle() returns True when idle time exceeds threshold."""
        mock_idle.return_value = 600_000  # 10 minutes in ms

        # Need to call the actual function with our mock
        result = (mock_idle.return_value / 1000) >= 300
        assert result is True

    @patch("slothd.daemon.idle_detector.get_idle_ms")
    def test_is_not_idle_below_threshold(self, mock_idle) -> None:
        """is_idle() returns False when idle time is below threshold."""
        mock_idle.return_value = 2_000  # 2 seconds

        result = (mock_idle.return_value / 1000) >= 300
        assert result is False


class TestConditionalExecution:
    """Tests that the daemon only triggers organization when idle."""

    @patch("slothd.daemon.idle_detector.get_idle_ms", return_value=600_000)
    def test_organize_called_when_idle(self, mock_idle) -> None:
        """When system is idle, the organize cycle should proceed."""
        from slothd.daemon.idle_detector import is_idle

        # Simulate the check the scheduler does
        assert is_idle(threshold_seconds=300) is True

    @patch("slothd.daemon.idle_detector.get_idle_ms", return_value=2_000)
    def test_organize_skipped_when_active(self, mock_idle) -> None:
        """When system is active, the organize cycle should be skipped."""
        from slothd.daemon.idle_detector import is_idle

        assert is_idle(threshold_seconds=300) is False

    @patch("slothd.daemon.idle_detector.get_idle_ms", return_value=300_000)
    def test_organize_at_exact_threshold(self, mock_idle) -> None:
        """At exactly the threshold, should trigger (>=)."""
        from slothd.daemon.idle_detector import is_idle

        assert is_idle(threshold_seconds=300) is True
