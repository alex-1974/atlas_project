# src/atlas/core/logging.py
"""Centralised logging configuration for Atlas.

Usage
-----
In any module::

    from atlas.core.logging import get_logger
    log = get_logger(__name__)

    log.debug("signal %s = %.3f", name, value)   # lazy — no cost if DEBUG off
    log.info("indexed %d chunks for %s", n, doc_id[:12])
    log.warning("no heading candidates for %s", doc_id[:12])

Configuration
-------------
Set the environment variable ATLAS_LOG before running any atlas command::

    # Everything at INFO
    ATLAS_LOG=INFO atlas add paper.pdf

    # Only DU pipeline at DEBUG, rest at WARNING
    ATLAS_LOG=atlas.du=DEBUG atlas dev du process fd2ec5

    # Multiple areas
    ATLAS_LOG=atlas.du=DEBUG,atlas.pipeline=INFO atlas add paper.pdf

    # Everything at DEBUG
    ATLAS_LOG=DEBUG atlas add paper.pdf

Format::

    ATLAS_LOG_FORMAT=short   — "INFO  atlas.du.zones: body_start=4"  (default)
    ATLAS_LOG_FORMAT=long    — timestamp + level + logger + message
    ATLAS_LOG_FORMAT=json    — machine-readable JSON lines

Logger namespace hierarchy
--------------------------
    atlas                     root — covers everything
    atlas.pipeline            run_pipeline, Pass 0 profiling
    atlas.du                  DU root — covers all DU sub-loggers
    atlas.du.segmentation     build_document, source_kind detection
    atlas.du.zones            zone boundary detection
    atlas.du.roles            role assignment
    atlas.du.headings         heading candidate collection
    atlas.du.section_tree     section tree building
    atlas.du.document_type    document type classification
    atlas.du.signals          signal aggregation
    atlas.enrich              enrichment pipeline
    atlas.search              search queries
    atlas.knowledge           knowledge graph operations
    atlas.embeddings          embedding indexing
"""
from __future__ import annotations

import logging
import os
import sys
from typing import Optional


# ── Constants ─────────────────────────────────────────────────────────────────

_ENV_LEVEL  = "ATLAS_LOG"
_ENV_FORMAT = "ATLAS_LOG_FORMAT"

_DEFAULT_LEVEL  = logging.WARNING
_DEFAULT_FORMAT = "short"

_SHORT_FORMAT = "%(levelname)-7s %(name)s: %(message)s"
_LONG_FORMAT  = "%(asctime)s %(levelname)-7s %(name)s: %(message)s"
_DATE_FORMAT  = "%Y-%m-%d %H:%M:%S"

_INITIALIZED = False


# ── Setup ─────────────────────────────────────────────────────────────────────

def setup_logging(
    level: Optional[str] = None,
    fmt: Optional[str] = None,
) -> None:
    """Configure Atlas logging from environment or explicit arguments.

    Safe to call multiple times — subsequent calls are no-ops unless
    force=True is used internally.

    Parameters
    ----------
    level : str, optional
        Override ATLAS_LOG environment variable.
        Examples: "DEBUG", "INFO", "atlas.du=DEBUG",
                  "atlas.du=DEBUG,atlas.pipeline=INFO"
    fmt : str, optional
        Override ATLAS_LOG_FORMAT. One of: "short", "long", "json".
    """
    global _INITIALIZED
    if _INITIALIZED:
        return
    _INITIALIZED = True

    level_spec = level or os.environ.get(_ENV_LEVEL, "")
    fmt_name   = fmt   or os.environ.get(_ENV_FORMAT, _DEFAULT_FORMAT)

    # ── Formatter ─────────────────────────────────────────────────────────────
    if fmt_name == "long":
        formatter = logging.Formatter(_LONG_FORMAT, datefmt=_DATE_FORMAT)
    elif fmt_name == "json":
        formatter = _JsonFormatter()
    else:
        formatter = logging.Formatter(_SHORT_FORMAT)

    # ── Handler ───────────────────────────────────────────────────────────────
    handler = logging.StreamHandler(sys.stderr)
    handler.setFormatter(formatter)

    # ── Root atlas logger ─────────────────────────────────────────────────────
    root = logging.getLogger("atlas")
    root.addHandler(handler)
    root.propagate = False  # don't bubble to Python root logger

    if not level_spec:
        root.setLevel(_DEFAULT_LEVEL)
        return

    # ── Parse level spec ──────────────────────────────────────────────────────
    # Formats:
    #   "DEBUG"                           → set atlas root to DEBUG
    #   "atlas.du=DEBUG"                  → set specific logger
    #   "atlas.du=DEBUG,atlas.pipeline=INFO"  → multiple
    parts = [p.strip() for p in level_spec.split(",") if p.strip()]

    global_level = None
    per_logger: dict[str, int] = {}

    for part in parts:
        if "=" in part:
            name, lvl = part.split("=", 1)
            numeric = _parse_level(lvl.strip())
            per_logger[name.strip()] = numeric
        else:
            global_level = _parse_level(part)

    if global_level is not None:
        root.setLevel(global_level)
    else:
        root.setLevel(_DEFAULT_LEVEL)

    for name, numeric in per_logger.items():
        lg = logging.getLogger(name)
        lg.setLevel(numeric)
        # Ensure the logger propagates to atlas root (which has the handler)
        lg.propagate = True


def _parse_level(s: str) -> int:
    """Convert level string to int. Raises ValueError for unknown levels."""
    numeric = getattr(logging, s.upper(), None)
    if numeric is None:
        raise ValueError(f"Unknown log level: {s!r}")
    return numeric


# ── Public API ────────────────────────────────────────────────────────────────

def get_logger(name: str) -> logging.Logger:
    """Return a logger for *name*.

    Call this at module level::

        log = get_logger(__name__)

    The logger is lazy — no cost when its level is disabled.
    setup_logging() is called automatically on first use.
    """
    setup_logging()
    return logging.getLogger(name)


# ── JSON formatter ────────────────────────────────────────────────────────────

class _JsonFormatter(logging.Formatter):
    """Emit one JSON object per log record."""

    def format(self, record: logging.LogRecord) -> str:
        import json
        import time
        d = {
            "ts":      time.strftime(_DATE_FORMAT, time.localtime(record.created)),
            "level":   record.levelname,
            "logger":  record.name,
            "msg":     record.getMessage(),
        }
        if record.exc_info:
            d["exc"] = self.formatException(record.exc_info)
        return json.dumps(d, ensure_ascii=False)
