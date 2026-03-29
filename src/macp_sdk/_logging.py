from __future__ import annotations

import logging

logger = logging.getLogger("macp_sdk")


def configure_logging(
    level: int = logging.INFO,
    fmt: str = "%(asctime)s %(name)s %(levelname)s %(message)s",
) -> None:
    """Configure the macp_sdk logger with a stream handler."""
    handler = logging.StreamHandler()
    handler.setFormatter(logging.Formatter(fmt))
    logger.addHandler(handler)
    logger.setLevel(level)
