"""
Logging utilities for atlas.parse.
"""
from __future__ import annotations
import logging

LOGGER_NAME = "atlas.parse"


def get_logger(name: str | None = None) -> logging.Logger:
    """
    Liefert einen Logger innerhalb des atlas.parse-Namespace.

    Wenn name bereits mit 'atlas.' beginnt (z.B. __name__ eines Moduls),
    wird er direkt genutzt — kein doppelter Prefix.

        logger = get_logger(__name__)  # atlas.parse.pipeline → korrekt
    """
    if not name:
        return logging.getLogger(LOGGER_NAME)
    if name.startswith("atlas."):
        return logging.getLogger(name)
    return logging.getLogger(f"{LOGGER_NAME}.{name}")
