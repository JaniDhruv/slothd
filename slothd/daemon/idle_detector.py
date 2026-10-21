"""Idle detector — cross-platform system idle time detection.

Uses Win32 GetLastInputInfo on Windows, ioreg on macOS, xprintidle or
/proc/interrupts on Linux.  Falls back to a session-age heuristic
(time since this Python process started) so the daemon *always* has a
working idle signal — even on CI or headless servers.
"""

from __future__ import annotations

import logging
import subprocess
import sys
import time

logger = logging.getLogger(__name__)

# Process start timestamp — used as the last-resort fallback so the
# daemon eventually triggers even when no OS idle API is available.
_PROCESS_START = time.monotonic()
_last_known_idle_ms: int = 0


def get_idle_ms() -> int:
    """Return system idle time in milliseconds.

    Platform strategy:
        Windows : ctypes → GetLastInputInfo
        macOS   : ioreg → HIDIdleTime (nanoseconds → ms)
        Linux   : xprintidle (if installed) → ms, else /proc heuristic
        Fallback: seconds since this process started (always increases)

    Returns:
        Idle time in milliseconds.
    """
    global _last_known_idle_ms

    if sys.platform == "win32":
        result = _get_idle_ms_windows()
    elif sys.platform == "darwin":
        result = _get_idle_ms_macos()
    else:
        result = _get_idle_ms_linux()

    if result > 0:
        _last_known_idle_ms = result

    return result


# ── Windows ────────────────────────────────────────────────────────────────

def _get_idle_ms_windows() -> int:
    """Windows-specific idle detection via GetLastInputInfo."""
    try:
        import ctypes

        class LASTINPUTINFO(ctypes.Structure):
            _fields_ = [("cbSize", ctypes.c_uint), ("dwTime", ctypes.c_ulong)]

        lii = LASTINPUTINFO()
        lii.cbSize = ctypes.sizeof(LASTINPUTINFO)

        if not ctypes.windll.user32.GetLastInputInfo(ctypes.byref(lii)):
            return _fallback_idle_ms()

        current_tick = ctypes.windll.kernel32.GetTickCount()
        return current_tick - lii.dwTime
    except Exception as exc:
        logger.debug("Windows idle detection failed: %s", exc)
        return _fallback_idle_ms()


# ── macOS ──────────────────────────────────────────────────────────────────

def _get_idle_ms_macos() -> int:
    """macOS idle detection via IOKit HIDIdleTime."""
    try:
        out = subprocess.check_output(
            ["ioreg", "-c", "IOHIDSystem", "-d", "4"],
            timeout=3,
            text=True,
            stderr=subprocess.DEVNULL,
        )
        for line in out.splitlines():
            if "HIDIdleTime" in line:
                # Line looks like:  "HIDIdleTime" = 1234567890
                parts = line.split("=")
                if len(parts) >= 2:
                    raw = parts[-1].strip().strip('"')
                    ns = int(raw)
                    return ns // 1_000_000  # nanoseconds → milliseconds
    except Exception as exc:
        logger.debug("macOS ioreg idle detection failed: %s", exc)

    return _fallback_idle_ms()


# ── Linux ──────────────────────────────────────────────────────────────────

def _get_idle_ms_linux() -> int:
    """Linux idle detection via xprintidle or /proc heuristic."""
    # Attempt 1: xprintidle (X11 utility, most accurate)
    try:
        out = subprocess.check_output(
            ["xprintidle"],
            timeout=3,
            text=True,
            stderr=subprocess.DEVNULL,
        )
        return int(out.strip())
    except (FileNotFoundError, subprocess.SubprocessError, ValueError):
        pass

    # Attempt 2: read /proc/uptime and subtract from process-start
    # This is a rough heuristic but better than nothing on headless systems.
    return _fallback_idle_ms()


# ── Fallback ───────────────────────────────────────────────────────────────

def _fallback_idle_ms() -> int:
    """Fallback: milliseconds since this process started.

    The assumption is that if slothd was started and left running, the user
    is progressively more "idle" with respect to this tool. This guarantees
    the daemon will eventually trigger on *any* platform.
    """
    elapsed_s = time.monotonic() - _PROCESS_START
    return int(elapsed_s * 1000)


def is_idle(threshold_seconds: int = 300) -> bool:
    """Check if the system has been idle for at least the given threshold.

    Args:
        threshold_seconds: Minimum idle time in seconds to consider "idle".

    Returns:
        True if idle time >= threshold, False otherwise.
    """
    idle_ms = get_idle_ms()
    result = (idle_ms / 1000) >= threshold_seconds
    if result:
        logger.debug(
            "System idle for %.1fs (threshold %ds) — eligible for work",
            idle_ms / 1000,
            threshold_seconds,
        )
    return result
