"""Sentry observability & agent tracing integration for slothd.

Captures performance spans for Gemma 3 classification, directory scanning,
and file organization batches to provide waterfall visualizations for debugging.
"""

from __future__ import annotations

import contextlib
import logging
from typing import Any, Generator

logger = logging.getLogger(__name__)

_SENTRY_INITIALIZED = False


def init_sentry(dsn: str | None = None, environment: str = "production") -> bool:
    """Initialize Sentry SDK with distributed tracing enabled."""
    global _SENTRY_INITIALIZED
    if not dsn:
        logger.debug("No Sentry DSN provided; tracing will run in no-op mode.")
        return False

    try:
        import sentry_sdk

        sentry_sdk.init(
            dsn=dsn,
            traces_sample_rate=1.0,
            environment=environment,
            release="slothd@0.1.0",
        )
        _SENTRY_INITIALIZED = True
        logger.info("Sentry tracing initialized.")
        return True
    except Exception as e:
        logger.warning("Failed to initialize Sentry: %s", e)
        return False


@contextlib.contextmanager
def trace_span(
    op: str,
    description: str,
    data: dict[str, Any] | None = None,
) -> Generator[Any, None, None]:
    """Context manager for tracing operations in Sentry.

    If Sentry is not configured, silently yields a dummy span.
    """
    if _SENTRY_INITIALIZED:
        try:
            import sentry_sdk

            with sentry_sdk.start_span(op=op, description=description) as span:
                if data:
                    for k, v in data.items():
                        span.set_data(k, v)
                yield span
                return
        except Exception as e:
            logger.debug("Sentry span recording failed: %s", e)

    # Fallback dummy span
    class DummySpan:
        def set_data(self, key: str, val: Any) -> None:
            pass

    yield DummySpan()


def capture_exception(exc: Exception) -> None:
    """Capture an exception and send to Sentry if active."""
    if _SENTRY_INITIALIZED:
        try:
            import sentry_sdk

            sentry_sdk.capture_exception(exc)
        except Exception:
            pass
