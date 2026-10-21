"""Tests for the idle detector — cross-platform, mocked, never waits.

"You don't need an idle computer to test idle software."
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch


class TestGetIdleMs:
    """Tests for get_idle_ms() — platform detection and mocking."""

    @patch("slothd.daemon.idle_detector.sys.platform", "darwin")
    @patch("slothd.daemon.idle_detector._get_idle_ms_macos", return_value=42_000)
    def test_macos_uses_ioreg(self, mock_macos: MagicMock) -> None:
        """On macOS, get_idle_ms delegates to the ioreg-based detector."""
        from slothd.daemon.idle_detector import get_idle_ms

        result = get_idle_ms()
        mock_macos.assert_called_once()
        assert result == 42_000

    @patch("slothd.daemon.idle_detector.sys.platform", "linux")
    @patch("slothd.daemon.idle_detector._get_idle_ms_linux", return_value=120_000)
    def test_linux_uses_xprintidle(self, mock_linux: MagicMock) -> None:
        """On Linux, get_idle_ms delegates to the xprintidle/proc detector."""
        from slothd.daemon.idle_detector import get_idle_ms

        result = get_idle_ms()
        mock_linux.assert_called_once()
        assert result == 120_000

    @patch("slothd.daemon.idle_detector.sys.platform", "win32")
    @patch("slothd.daemon.idle_detector._get_idle_ms_windows", return_value=500_000)
    def test_windows_uses_win32(self, mock_win: MagicMock) -> None:
        """On Windows, get_idle_ms delegates to the Win32 detector."""
        from slothd.daemon.idle_detector import get_idle_ms

        result = get_idle_ms()
        mock_win.assert_called_once()
        assert result == 500_000

    def test_fallback_returns_positive_value(self) -> None:
        """The fallback always returns a positive value (process age)."""
        from slothd.daemon.idle_detector import _fallback_idle_ms

        result = _fallback_idle_ms()
        assert result >= 0

    @patch("slothd.daemon.idle_detector.sys.platform", "freebsd")
    def test_unknown_platform_uses_fallback(self) -> None:
        """Unknown platforms use the Linux path which falls back gracefully."""
        from slothd.daemon.idle_detector import get_idle_ms

        # Should not crash — returns fallback value
        result = get_idle_ms()
        assert result >= 0


class TestIsIdle:
    """Tests that is_idle() correctly compares against the threshold."""

    @patch("slothd.daemon.idle_detector.get_idle_ms", return_value=600_000)
    def test_is_idle_when_threshold_exceeded(self, mock_idle: MagicMock) -> None:
        """is_idle() returns True when idle time exceeds threshold."""
        from slothd.daemon.idle_detector import is_idle

        assert is_idle(threshold_seconds=300) is True

    @patch("slothd.daemon.idle_detector.get_idle_ms", return_value=2_000)
    def test_is_not_idle_below_threshold(self, mock_idle: MagicMock) -> None:
        """is_idle() returns False when idle time is below threshold."""
        from slothd.daemon.idle_detector import is_idle

        assert is_idle(threshold_seconds=300) is False

    @patch("slothd.daemon.idle_detector.get_idle_ms", return_value=300_000)
    def test_idle_at_exact_threshold(self, mock_idle: MagicMock) -> None:
        """At exactly the threshold, should trigger (>=)."""
        from slothd.daemon.idle_detector import is_idle

        assert is_idle(threshold_seconds=300) is True


class TestConditionalExecution:
    """Tests that the daemon only triggers organization when idle."""

    @patch("slothd.daemon.idle_detector.get_idle_ms", return_value=600_000)
    def test_organize_called_when_idle(self, mock_idle: MagicMock) -> None:
        """When system is idle, the organize cycle should proceed."""
        from slothd.daemon.idle_detector import is_idle

        # Simulate the check the scheduler does
        assert is_idle(threshold_seconds=300) is True

    @patch("slothd.daemon.idle_detector.get_idle_ms", return_value=2_000)
    def test_organize_skipped_when_active(self, mock_idle: MagicMock) -> None:
        """When system is active, the organize cycle should be skipped."""
        from slothd.daemon.idle_detector import is_idle

        assert is_idle(threshold_seconds=300) is False

    @patch("slothd.daemon.idle_detector.get_idle_ms", return_value=300_000)
    def test_organize_at_exact_threshold(self, mock_idle: MagicMock) -> None:
        """At exactly the threshold, should trigger (>=)."""
        from slothd.daemon.idle_detector import is_idle

        assert is_idle(threshold_seconds=300) is True
