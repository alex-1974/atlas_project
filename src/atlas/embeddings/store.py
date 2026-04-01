# src/atlas/embeddings/store.py
"""LanceDB vector store for Atlas semantic search.

Stores paragraph-level embeddings for each document.
Each row in the `paragraphs` table represents one semantic unit:
  - A section (section title + first 300 chars of body)
  - An abstract
  - A dense body paragraph (≥ 50 words)

Schema:
    document_id  str      — SHA-256 of the PDF
    chunk_id     str      — "{document_id}_{block_index}"
    text         str      — the embedded text snippet
    vector       float32[384]  — embedding
    page         int      — page_index of the source block
    block_index  int      — du_blocks.block_index

Index path: `.atlas/embeddings/`

Similarity metric: cosine (vectors are normalised at write time).
"""
from __future__ import annotations

import logging
from pathlib import Path

import numpy as np

log = logging.getLogger(__name__)

_TABLE_NAME = "paragraphs"
_VECTOR_DIM = 384


class EmbeddingStore:
    """Thin wrapper around LanceDB for Atlas semantic search."""

    def __init__(self, db) -> None:
        self._db = db
        self._table = None

    # ── Lifecycle ─────────────────────────────────────────────────────────────

    @classmethod
    def open(cls, catalog_root: Path) -> "EmbeddingStore":
        """Open (or create) the embedding store for a catalog."""
        try:
            import lancedb
        except ImportError:
            raise RuntimeError(
                "lancedb is not installed. Run: pip install lancedb"
            )
        path = catalog_root / ".atlas" / "embeddings"
        path.mkdir(parents=True, exist_ok=True)
        db = lancedb.connect(str(path))
        store = cls(db)
        store._ensure_table()
        return store

    def _ensure_table(self) -> None:
        """Open or create the paragraphs table."""
        import pyarrow as pa

        # LanceDB 0.30+ returns a ListTablesResponse object from list_tables()
        # and table_names() — extract the actual list defensively.
        try:
            existing = self._db.table_names()
            if hasattr(existing, 'tables'):
                existing = existing.tables
            elif hasattr(existing, '__iter__') and not isinstance(existing, (str, bytes)):
                existing = list(existing)
            else:
                existing = []
        except Exception:
            existing = []

        if _TABLE_NAME in existing:
            self._table = self._db.open_table(_TABLE_NAME)
            return

        schema = pa.schema([
            pa.field("document_id",  pa.string()),
            pa.field("chunk_id",     pa.string()),
            pa.field("text",         pa.string()),
            pa.field("vector",       pa.list_(pa.float32(), _VECTOR_DIM)),
            pa.field("page",         pa.int32()),
            pa.field("block_index",  pa.int32()),
        ])
        self._table = self._db.create_table(_TABLE_NAME, schema=schema)
        log.debug("Created LanceDB table %r", _TABLE_NAME)

    # ── Write ─────────────────────────────────────────────────────────────────

    def add_document(
        self,
        document_id: str,
        chunks: list[dict],
    ) -> int:
        """Embed and store text chunks for a document.

        Each chunk dict:
            {"text": str, "page": int, "block_index": int}

        Returns the number of chunks stored.
        """
        if not chunks:
            return 0

        from atlas.embeddings.model import embed_texts
        texts  = [c["text"] for c in chunks]
        vecs   = embed_texts(texts)

        rows = []
        for i, (chunk, vec) in enumerate(zip(chunks, vecs)):
            rows.append({
                "document_id": document_id,
                "chunk_id":    f"{document_id}_{chunk['block_index']:06d}",
                "text":        chunk["text"][:1000],  # cap for storage
                "vector":      vec.tolist(),
                "page":        int(chunk.get("page", 0)),
                "block_index": int(chunk["block_index"]),
            })

        self._table.add(rows)
        return len(rows)

    def remove_document(self, document_id: str) -> None:
        """Remove all vectors for a document."""
        self._table.delete(f'document_id = "{document_id}"')

    # ── Search ────────────────────────────────────────────────────────────────

    def search(
        self,
        query: str,
        top_k: int = 10,
        document_id: str | None = None,
    ) -> list[dict]:
        """Semantic search over all documents (or one document).

        Returns list of dicts:
            {"document_id": str, "chunk_id": str, "text": str,
             "score": float, "page": int, "block_index": int}
        """
        from atlas.embeddings.model import embed_text
        vec = embed_text(query).tolist()

        q = self._table.search(vec).limit(top_k)
        if document_id:
            q = q.where(f'document_id = "{document_id}"')

        results = q.to_list()
        return [
            {
                "document_id": r["document_id"],
                "chunk_id":    r["chunk_id"],
                "text":        r["text"],
                "score":       float(r.get("_distance", 0.0)),
                "page":        r["page"],
                "block_index": r["block_index"],
            }
            for r in results
        ]

    def similar_documents(
        self,
        document_id: str,
        top_k: int = 10,
    ) -> list[dict]:
        """Find documents similar to the given document.

        Uses the centroid of the document's chunk embeddings as query vector.

        Returns list of dicts:
            {"document_id": str, "score": float}
        Score range: 0.0 (dissimilar) to 1.0 (identical).
        """
        # Fetch own vectors — try multiple API styles for compatibility
        own_vecs: list = []
        try:
            # LanceDB >= 0.5: full scan with filter
            df = self._table.to_pandas()
            own_df = df[df["document_id"] == document_id]
            if not own_df.empty:
                own_vecs = list(own_df["vector"].values)
        except Exception:
            pass

        if not own_vecs:
            return []

        # Centroid of this document's embeddings
        vecs = np.stack(own_vecs).astype("float32")
        centroid = vecs.mean(axis=0)
        norm = np.linalg.norm(centroid)
        if norm > 0:
            centroid /= norm

        # Search for similar chunks — limit must be large enough to reach
        # past the document's own chunks (which always rank highest).
        own_count = len(own_vecs)
        search_limit = max(own_count + top_k * 5, 100)
        results = (
            self._table
            .search(centroid.tolist())
            .limit(search_limit)
            .to_list()
        )

        # Aggregate by document, exclude self
        # LanceDB cosine distance: 0 = identical, 2 = opposite
        # Convert to similarity: score = 1 - dist/2
        scores: dict[str, float] = {}
        for r in results:
            did = r["document_id"]
            if did == document_id:
                continue
            dist  = float(r.get("_distance", 2.0))
            score = max(0.0, 1.0 - dist / 2.0)
            if did not in scores or score > scores[did]:
                scores[did] = score

        return sorted(
            [{"document_id": k, "score": v} for k, v in scores.items()],
            key=lambda x: -x["score"],
        )[:top_k]
