"""Centralised logging — one factory, no scattered basicConfig calls."""

from __future__ import annotations

import logging
import sys


def configure_logging(*, json_output: bool = False, level: int = logging.INFO) -> None:
    """Call once at startup (in create_app). Sets root logger format."""
    root = logging.getLogger()
    root.setLevel(level)

    if root.handlers:
        return  # already configured (e.g. tests calling create_app twice)

    handler = logging.StreamHandler(sys.stdout)

    if json_output:
        # Minimal JSON lines — swap for python-json-logger if needed later
        fmt = '{"time":"%(asctime)s","level":"%(levelname)s","logger":"%(name)s","message":"%(message)s"}'
    else:
        fmt = "%(asctime)s | %(levelname)-8s | %(name)s — %(message)s"

    handler.setFormatter(logging.Formatter(fmt))
    root.addHandler(handler)


def get_logger(name: str) -> logging.Logger:
    """Import this everywhere instead of logging.getLogger directly."""
    return logging.getLogger(name)
