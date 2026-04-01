# src/atlas/embeddings/model.py
"""Local embedding model for semantic search.

Uses `all-MiniLM-L6-v2` from sentence-transformers — a compact,
fast model that runs fully offline after the first download.

Model cache: `~/.atlas/models/all-MiniLM-L6-v2/`

The model is loaded once per process and kept in memory.
For the typical Atlas use case (1000 documents, batch ingestion)
this is acceptable.  For very large catalogs the model could be
unloaded after ingestion and reloaded on demand.
"""
from __future__ import annotations

import logging
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import numpy as np

log = logging.getLogger(__name__)

_MODEL_NAME  = "all-MiniLM-L6-v2"
_CACHE_DIR   = Path.home() / ".atlas" / "models"
_VECTOR_DIM  = 384   # all-MiniLM-L6-v2 output dimension

_model = None   # lazy singleton


def get_model():
    """Return the embedding model, loading it on first call."""
    global _model
    if _model is not None:
        return _model

    try:
        from sentence_transformers import SentenceTransformer
    except ImportError:
        raise RuntimeError(
            "sentence-transformers is not installed. "
            "Run: pip install sentence-transformers"
        )

    log.info("Loading embedding model %s …", _MODEL_NAME)
    _CACHE_DIR.mkdir(parents=True, exist_ok=True)
    _model = SentenceTransformer(
        _MODEL_NAME,
        cache_folder=str(_CACHE_DIR),
    )
    log.info("Embedding model loaded (%d dimensions)", _VECTOR_DIM)
    return _model


def embed_texts(texts: list[str]) -> "np.ndarray":
    """Embed a list of texts, return float32 numpy array (N × 384)."""
    import numpy as np
    if not texts:
        return np.zeros((0, _VECTOR_DIM), dtype="float32")
    model = get_model()
    vecs = model.encode(
        texts,
        batch_size=32,
        show_progress_bar=False,
        normalize_embeddings=True,   # cosine similarity via dot product
    )
    return vecs.astype("float32")


def embed_text(text: str) -> "np.ndarray":
    """Embed a single text, return 1-D float32 array (384,)."""
    return embed_texts([text])[0]


def vector_dim() -> int:
    return _VECTOR_DIM
