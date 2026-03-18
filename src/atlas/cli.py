# src/atlas/cli.py
from __future__ import annotations

import multiprocessing as mp
import time
from typing import Any

import typer

from atlas.db.connection import get_connection
from atlas.db.migrate import run_migrations

from atlas.document_understanding.inference.document_type import compute_document_type
from atlas.document_understanding.inference.zone_memberships import compute_zone_memberships
from atlas.document_understanding.inference.roles import compute_roles
from atlas.document_understanding.inference.section_tree import compute_section_tree
from atlas.document_understanding.inference.semantic_zones import compute_semantic_zones
from atlas.document_understanding.inference.signals import compute_signals
from atlas.document_understanding.inference.zone_hypotheses import compute_zone_hypotheses
from atlas.document_understanding.layers.context import compute_context
from atlas.document_understanding.layers.geometry import compute_geometry
from atlas.document_understanding.layers.semantic_micro import compute_semantic_micro
from atlas.document_understanding.layers.surface import compute_surface
from atlas.document_understanding.layers.typography import compute_typography
from atlas.document_understanding.layout.layout_clusters import compute_layout_clusters
from atlas.document_understanding.layout.layout_graph import compute_layout_graph
from atlas.document_understanding.inference.page_furniture import compute_page_furniture
from atlas.document_understanding.persistence.repository import Repository
from atlas.document_understanding.segmentation.blocks import build_document

from atlas.enrich.ocr_candidates import mark_ocr_candidates
from atlas.enrich.pdf_metadata_titles import enrich_titles_from_pdf_metadata
from atlas.enrich.quality import enrich_text_quality
from atlas.enrich.title_from_filename import enrich_titles_from_filename
from atlas.enrich.title_from_text import enrich_title_from_text

from atlas.extract.authors import extract_authors
from atlas.extract.identifiers import extract_identifiers
from atlas.extract.pdf_metadata import extract_pdf_metadata
from atlas.extract.text_fallback import run_pdftotext_fallback
from atlas.extract.text_pymupdf import extract_text_pymupdf

from atlas.ingest.discovery import discover_pdfs
from atlas.ingest.registration import register_document

from atlas.inspect.authors import inspect_authors
from atlas.inspect.identifiers import (
    get_identifier_examples,
    get_identifier_sources,
    get_identifier_summary,
)
from atlas.inspect.ocr import get_ocr_candidates
from atlas.inspect.overview import get_overview
from atlas.inspect.problems import get_empty_or_poor
from atlas.inspect.states import get_state_summary
from atlas.inspect.title_candidates import inspect_title_candidates
from atlas.inspect.titles import inspect_titles

from atlas.normalize.identifiers import dedupe_identifiers, normalize_identifiers

from atlas.search.document_search import search_documents
from atlas.search.lexical import search_segments

from atlas.segment.paragraphs import segment_documents


app = typer.Typer(
    help="Atlas CLI",
    no_args_is_help=True,
)

ingest_app = typer.Typer(
    help="Ingest and registration commands.",
    no_args_is_help=True,
)
extract_app = typer.Typer(
    help="Text and metadata extraction commands.",
    no_args_is_help=True,
)
enrich_app = typer.Typer(
    help="Metadata enrichment commands.",
    no_args_is_help=True,
)
normalize_app = typer.Typer(
    help="Normalization commands.",
    no_args_is_help=True,
)
dedupe_app = typer.Typer(
    help="Deduplication commands.",
    no_args_is_help=True,
)
identifiers_app = typer.Typer(
    help="Identifier summary and source inspection.",
    no_args_is_help=True,
)
inspect_app = typer.Typer(
    help="Corpus inspection commands.",
    no_args_is_help=True,
)
search_app = typer.Typer(
    help="Search commands.",
    no_args_is_help=True,
)
segment_app = typer.Typer(
    help="Segmentation commands.",
    no_args_is_help=True,
)
du_app = typer.Typer(
    help="Document Understanding commands.",
    no_args_is_help=True,
)

app.add_typer(ingest_app, name="ingest")
app.add_typer(extract_app, name="extract")
app.add_typer(enrich_app, name="enrich")
app.add_typer(normalize_app, name="normalize")
app.add_typer(dedupe_app, name="dedupe")
app.add_typer(identifiers_app, name="identifiers")
app.add_typer(inspect_app, name="inspect")
app.add_typer(search_app, name="search")
app.add_typer(segment_app, name="segment")
app.add_typer(du_app, name="du")


def _echo_rows(rows: list[object], limit: int | None = None) -> None:
    if limit is not None:
        rows = rows[:limit]
    for row in rows:
        typer.echo(str(row))


def _du_process_document(doc_id: str) -> None:
    started = time.time()

    with get_connection() as conn:
        repo = Repository(conn)

        # idempotent / deterministic rerun
        repo.delete_du_document(doc_id)

        build_document(repo, doc_id)
        compute_geometry(repo, doc_id)
        compute_layout_graph(repo, doc_id)
        compute_page_furniture(repo, doc_id)
        compute_layout_clusters(repo, doc_id)
        compute_typography(repo, doc_id)
        compute_surface(repo, doc_id)
        compute_context(repo, doc_id)
        compute_semantic_micro(repo, doc_id)
        compute_signals(repo, doc_id)
        compute_roles(repo, doc_id)
        compute_zone_hypotheses(repo, doc_id)
        compute_zone_memberships(repo, doc_id)
        compute_semantic_zones(repo, doc_id)
        compute_section_tree(repo, doc_id)
        compute_document_type(repo, doc_id)

    elapsed = time.time() - started
    typer.echo(f"DU processed {doc_id} in {elapsed:.2f}s")

def _format_search_hit(hit: Any, index: int) -> str:
    score = getattr(hit, "score", None)
    doc_id = getattr(hit, "document_id", None)
    relative_path = getattr(hit, "relative_path", None)
    snippet = getattr(hit, "snippet", None)
    text = getattr(hit, "text", None)

    score_text = f"{score:.4f}" if isinstance(score, (int, float)) else "?"
    snippet_text = snippet or text or ""

    return (
        f"[{index}] score={score_text} "
        f"doc_id={doc_id or '?'} "
        f"path={relative_path or '?'}\n"
        f"{snippet_text}"
    )


@app.command()
def version() -> None:
    typer.echo("atlas")


@app.command()
def migrate() -> None:
    run_migrations()
    typer.echo("Migrations complete.")


@ingest_app.command("register")
def ingest_register() -> None:
    discovered = 0
    registered = 0

    for pdf_path in discover_pdfs():
        discovered += 1
        register_document(pdf_path)
        registered += 1

    typer.echo(f"Discovered {discovered} PDFs.")
    typer.echo(f"Registered {registered} documents.")


@extract_app.command("text")
def extract_text(force: bool = False) -> None:
    count = extract_text_pymupdf(force=force)
    typer.echo(f"Extracted text for {count} documents.")


@extract_app.command("fallback-text")
def fallback_text() -> None:
    count = run_pdftotext_fallback()
    typer.echo(f"Fallback text extraction completed for {count} documents.")


@extract_app.command("metadata")
def extract_metadata() -> None:
    count = extract_pdf_metadata()
    typer.echo(f"Extracted PDF metadata for {count} documents.")


@extract_app.command("authors")
def extract_authors_command() -> None:
    count = extract_authors()
    typer.echo(f"Extracted authors for {count} documents.")


@extract_app.command("identifiers")
def extract_identifiers_command() -> None:
    count = extract_identifiers()
    typer.echo(f"Extracted identifiers for {count} documents.")


@enrich_app.command("metadata-titles")
def enrich_metadata_titles() -> None:
    count = enrich_titles_from_pdf_metadata()
    typer.echo(f"Enriched titles from PDF metadata for {count} documents.")


@enrich_app.command("title-text")
def enrich_title_text() -> None:
    count = enrich_title_from_text()
    typer.echo(f"Enriched titles from text for {count} documents.")


@enrich_app.command("title-filename")
def enrich_title_filename() -> None:
    count = enrich_titles_from_filename()
    typer.echo(f"Enriched titles from filename for {count} documents.")


@enrich_app.command("quality")
def enrich_quality() -> None:
    count = enrich_text_quality()
    typer.echo(f"Computed text quality for {count} documents.")


@enrich_app.command("mark-ocr-candidates")
def mark_ocr_candidates_command() -> None:
    count = mark_ocr_candidates()
    typer.echo(f"Marked {count} OCR candidates.")


@normalize_app.command("identifiers")
def normalize_identifiers_command() -> None:
    count = normalize_identifiers()
    typer.echo(f"Normalized identifiers for {count} rows.")


@dedupe_app.command("identifiers")
def dedupe_identifiers_command() -> None:
    count = dedupe_identifiers()
    typer.echo(f"Deduplicated {count} identifier rows.")


@identifiers_app.command("summary")
def identifier_summary() -> None:
    typer.echo(str(get_identifier_summary()))


@identifiers_app.command("sources")
def identifier_sources() -> None:
    typer.echo(str(get_identifier_sources()))


@inspect_app.command("overview")
def inspect_overview(limit: int = 50) -> None:
    _echo_rows(get_overview(limit=limit), limit=limit)


@inspect_app.command("problems")
def inspect_problems(limit: int = 100) -> None:
    _echo_rows(get_empty_or_poor(limit=limit), limit=limit)


@inspect_app.command("ocr-candidates")
def inspect_ocr_candidates(limit: int = 100) -> None:
    _echo_rows(get_ocr_candidates(limit=limit), limit=limit)


@inspect_app.command("titles")
def inspect_titles_command(limit: int = 80, review_only: bool = False) -> None:
    _echo_rows(inspect_titles(limit=limit, review_only=review_only), limit=limit)


@inspect_app.command("title-candidates")
def inspect_title_candidates_command(
    limit: int = 20,
    review_only: bool = True,
    top_k: int = 3,
) -> None:
    _echo_rows(
        inspect_title_candidates(limit=limit, review_only=review_only, top_k=top_k),
        limit=limit,
    )


@inspect_app.command("authors")
def inspect_authors_command(limit: int = 120) -> None:
    _echo_rows(inspect_authors(limit=limit), limit=limit)


@inspect_app.command("identifiers")
def inspect_identifiers(limit: int = 50) -> None:
    _echo_rows(get_identifier_examples(limit=limit), limit=limit)


@inspect_app.command("state-summary")
def state_summary() -> None:
    typer.echo(str(get_state_summary()))


@search_app.command("segments")
def search_segments_command(query: str, top_k: int = 10) -> None:
    hits = search_segments(query=query, top_k=top_k)
    for i, hit in enumerate(hits, start=1):
        typer.echo(_format_search_hit(hit, i))
        typer.echo("")


@search_app.command("docs")
def search_docs_command(
    query: str,
    top_k: int = 10,
    segment_pool: int = 100,
) -> None:
    _echo_rows(
        search_documents(query=query, top_k=top_k, segment_pool=segment_pool),
        limit=top_k,
    )


@segment_app.command("paragraphs")
def segment_paragraphs(force: bool = False) -> None:
    count = segment_documents(force=force)
    typer.echo(f"Segmented paragraphs for {count} documents.")


@du_app.command("process")
def du_process(doc_id: str) -> None:
    _du_process_document(doc_id)


@du_app.command("process-all")
def du_process_all(workers: int = 4) -> None:
    started = time.perf_counter()

    with get_connection() as conn:
        repo = Repository(conn)
        documents = repo.fetch_documents()

    doc_ids = [str(doc.document_id) for doc in documents]
    total = len(doc_ids)

    typer.echo(f"Processing DU for {total} documents with {workers} workers...")

    if workers <= 1:
        for index, doc_id in enumerate(doc_ids, start=1):
            _du_process_document(doc_id)
            typer.echo(f"[{index}/{total}] done {doc_id}")
    else:
        with mp.Pool(processes=workers) as pool:
            for index, _ in enumerate(pool.imap_unordered(_du_process_document, doc_ids), start=1):
                typer.echo(f"[{index}/{total}] done")

    elapsed = time.perf_counter() - started
    typer.echo(f"DU process-all complete in {elapsed:.2f}s.")


@du_app.command("inspect")
def du_inspect(doc_id: str, limit: int = 50) -> None:
    """
    Inspect DU output:
    - blocks + roles
    - zone hypotheses
    - semantic zones
    - section tree
    - document type
    """
    with get_connection() as conn:
        repo = Repository(conn)

        typer.echo(f"\n=== DU INSPECT: {doc_id} ===\n")

        # ---------------------------------------------------------------------
        # DOCUMENT TYPE
        # ---------------------------------------------------------------------
        doc_type = repo.fetch_document_type(doc_id)
        typer.echo("== Document Type ==")
        typer.echo(str(doc_type))
        typer.echo("")

        # ---------------------------------------------------------------------
        # BLOCKS + ROLES
        # ---------------------------------------------------------------------
        typer.echo("== Blocks + Roles ==")

        blocks = repo.fetch_blocks(doc_id)
        roles = repo.fetch_roles(doc_id)

        role_map = {r["block_id"]: r for r in roles}

        for block in blocks[:limit]:
            role = role_map.get(block["block_id"])

            text_preview = (block.get("text") or "")[:80].replace("\n", " ")

            typer.echo(
                f'[{block["block_index"]:03d}] '
                f'{(role["role"] if role else "?"):12} '
                f'p{block["page_index"]:<2} '
                f"{text_preview}"
            )

        if len(blocks) > limit:
            typer.echo(f"... ({len(blocks) - limit} more blocks)")
        typer.echo("")

        # ---------------------------------------------------------------------
        # ZONE HYPOTHESES
        # ---------------------------------------------------------------------
        typer.echo("== Zone Hypotheses ==")

        hypotheses = repo.fetch_zone_hypotheses(doc_id)

        for z in hypotheses:
            confidence = z.get("confidence")
            conf_text = f"{confidence:.2f}" if confidence is not None else "?"

            typer.echo(
                f'{z["zone_type"]:15} '
                f'[{z["start_block_index"]:03d}-{z["end_block_index"]:03d}] '
                f"conf={conf_text}"
            )

        if not hypotheses:
            typer.echo("(none)")
        typer.echo("")

        # ---------------------------------------------------------------------
        # SEMANTIC ZONES (FINAL)
        # ---------------------------------------------------------------------
        typer.echo("== Semantic Zones ==")

        zones = repo.fetch_semantic_zones(doc_id)

        for z in zones:
            typer.echo(
                f'{z["zone_type"]:15} '
                f'[{z["start_block_index"]:03d}-{z["end_block_index"]:03d}]'
            )

        if not zones:
            typer.echo("(none)")
        typer.echo("")

        # ---------------------------------------------------------------------
        # SECTION TREE
        # ---------------------------------------------------------------------
        typer.echo("== Section Tree ==")

        sections = repo.fetch_section_tree(doc_id)

        for s in sections:
            level = s.get("level") or 0
            indent = "  " * level

            typer.echo(
                f"{indent}- "
                f"L{level} "
                f'[{s["start_block_index"]:03d}-{s["end_block_index"]:03d}] '
                f'{s.get("title") or "(no title)"}'
            )

        if not sections:
            typer.echo("(none)")
            
        scores = repo.fetch_document_type_scores(doc_id)

        print("\n== Document Type (Top-k) ==")
        for s in scores[:5]:
            print(f"{s['rank']:>2} {s['doc_type']:<20} score={s['score']:.2f} weight={s['weight']:.2f}")
            
        typer.echo("")
        
@du_app.command("eval-csv")
def du_eval_csv(csv_path: str) -> None:
    from atlas.db.connection import get_connection
    from atlas.document_understanding.persistence.repository import Repository
    from atlas.eval.du_eval_csv import run_du_eval_csv

    with get_connection() as conn:
        repo = Repository(conn)
        run_du_eval_csv(csv_path, repo)

def main() -> None:
    app()


if __name__ == "__main__":
    main()
