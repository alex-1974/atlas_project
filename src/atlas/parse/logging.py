"""
Logging utilities for atlas.parse.

atlas.parse konfiguriert Logging nicht selbst, sondern stellt lediglich
einen standardisierten Logger bereit. Die Konfiguration erfolgt durch
Atlas oder durch CLI-Tools.
"""

from __future__ import annotations

import logging

LOGGER_NAME = "atlas.parse"


def get_logger(name: str | None = None) -> logging.Logger:
    """
    Liefert einen Logger innerhalb des atlas.parse-Namespace.

    Beispiel:
        logger = get_logger(__name__)
    """
    if name:
        return logging.getLogger(f"{LOGGER_NAME}.{name}")
    return logging.getLogger(LOGGER_NAME)
