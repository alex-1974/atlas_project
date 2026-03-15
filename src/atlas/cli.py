from __future__ import annotations

import multiprocessing as mp
import time

import typer

from atlas.db.migrate import run_migrations
from atlas.ingest.discovery import discover_pdfs
from atlas.ingest.registration import register_document
from atlas.extract.text_fallback import run_pdftotext_fallback
from atlas.extract.text_pymupdf import extract_text_pymupdf
from atlas.extract.pdf_metadata import extract_pdf_metadata
from atlas.enrich.document_state import classify_documents
from atlas.enrich.pdf_metadata_titles import enrich_titles_from_pdf_metadata
from atlas.enrich.quality import enrich_text_quality
from atlas.segment.paragraphs import segment_documents
from atlas.inspect.ocr import get_ocr_candidates
from atlas.inspect.overview import get_overview
from atlas.inspect.problems import get_empty_or_poor
from atlas.inspect.states import get_state_summary
from atlas.inspect.titles import inspect_titles
from atlas.inspect.authors import inspect_authors
from atlas.inspect.title_candidates import inspect_title_candidates
from atlas.search.document_search import search_documents
from atlas.search.lexical import search_segments
from atlas.extract.identifiers import extract_identifiers
from atlas.inspect.identifiers import (
    get_identifier_examples,
    get_identifier_sources,
    get_identifier_summary,
)
from atlas.normalize.identifiers import dedupe_identifiers, normalize_identifiers
from atlas.enrich.title_from_text import enrich_title_from_text
from atlas.enrich.title_from_filename import enrich_titles_from_filename
from atlas.enrich.ocr_candidates import mark_ocr_candidates
from atlas.extract.authors import extract_authors
from atlas.segment.document_regions import segment_document_regions
from atlas.inspect.regions import inspect_regions
from atlas.inspect.header import inspect_header
from atlas.inspect.document_map import inspect_document_map

from atlas.inspect.du_roles import inspect_du_roles
from atlas.inspect.du_document_type import inspect_du_document_type
from atlas.inspect.du_columns import inspect_du_columns
from atlas.inspect.du_sections import inspect_du_sections
from atlas.document_understanding.structure.section_tree import compute_section_tree

app = typer.Typer(help="Atlas literature catalog CLI.")


def du_build_process_document(args):
    from atlas.db.connection import get_connection
    from atlas.document_understanding.persistence.repository import DURepository
    from atlas.document_understanding.blocks.blocks import build_document
    from atlas.document_understanding.topology.topology_features import compute_topology
    from atlas.document_understanding.geometry.geometry_features import compute_geometry
    from atlas.document_understanding.signals.signal_detectors import compute_signals
    from atlas.document_understanding.zones.zone_hypotheses import compute_zone_hypotheses
    from atlas.document_understanding.zones.memberships import compute_memberships
    from atlas.document_understanding.zones.semantic_zones import compute_semantic_zones

    document_id, path = args

    t0 = time.perf_counter()

    with get_connection() as conn:
        repo = DURepository(conn)

        t_build_0 = time.perf_counter()
        build_document(repo, document_id)
        t_build_1 = time.perf_counter()

        compute_topology(repo, document_id)
        t_topology_1 = time.perf_counter()

        compute_geometry(repo, document_id)
        t_geometry_1 = time.perf_counter()

        compute_signals(repo, document_id)
        t_signals_1 = time.perf_counter()

        compute_section_tree(repo, document_id)
        t_sections_1 = time.perf_counter()

        compute_zone_hypotheses(repo, document_id)
        t_hypotheses_1 = time.perf_counter()

        compute_memberships(repo, document_id)
        t_memberships_1 = time.perf_counter()

        compute_semantic_zones(repo, document_id)
        t_semantic_1 = time.perf_counter()

    return {
        "path": path,
        "build": t_build_1 - t_build_0,
        "topology": t_topology_1 - t_build_1,
        "geometry": t_geometry_1 - t_topology_1,
        "signals": t_signals_1 - t_geometry_1,
        "hypotheses": t_hypotheses_1 - t_signals_1,
        "memberships": t_memberships_1 - t_hypotheses_1,
        "semantic": t_semantic_1 - t_memberships_1,
        "total": t_semantic_1 - t0,
    }


@app.command()
def version() -> None:
    """Show Atlas version."""
    typer.echo("atlas 0.1.0")


@app.command()
def migrate() -> None:
    """Run database migrations."""
    run_migrations()


@app.command()
def ingest() -> None:
    """Discover and register PDFs."""
    count = 0

    for discovered in discover_pdfs():
        register_document(discovered)
        typer.echo(f"registered {discovered.relative_path}")
        count += 1

    typer.echo(f"ingest complete: {count} files")


@app.command()
def extract(force: bool = False) -> None:
    """Extract text from registered PDFs using PyMuPDF."""
    ok = 0
    skipped = 0
    errors = 0

    for discovered in discover_pdfs():
        document_id = register_document(discovered)
        result = extract_text_pymupdf(
            discovered.absolute_path,
            document_id,
            force=force,
        )

        if result["status"] == "ok":
            msg = f"extracted {discovered.relative_path}"
            if result["nul_bytes_removed"]:
                msg += f" (removed {result['nul_bytes_removed']} NUL bytes)"
            typer.echo(msg)
            ok += 1
        elif result["status"] == "skipped":
            typer.echo(f"skipped {discovered.relative_path} (already extracted)")
            skipped += 1
        else:
            typer.echo(f"error {discovered.relative_path}: {result['error']}")
            errors += 1

    typer.echo(f"extract complete: ok={ok} skipped={skipped} errors={errors}")


@app.command("fallback-text")
def fallback_text() -> None:
    """Run pdftotext fallback for documents whose latest extraction has text_length = 0."""
    processed = run_pdftotext_fallback()
    typer.echo(f"pdftotext fallback processed: {processed}")


@app.command("extract-metadata")
def extract_metadata() -> None:
    """Extract PDF metadata."""
    inserted = extract_pdf_metadata()
    typer.echo(f"metadata extracted: {inserted}")


@app.command("enrich-metadata-titles")
def enrich_metadata_titles() -> None:
    """Fill titles from PDF metadata."""
    updated = enrich_titles_from_pdf_metadata()
    typer.echo(f"titles updated from pdf metadata: {updated}")


@app.command("enrich-quality")
def enrich_quality() -> None:
    """Enrich text quality indicators."""
    updated = enrich_text_quality()
    typer.echo(f"text quality updated: {updated}")


@app.command("classify")
def classify() -> None:
    """Classify documents."""
    updated = classify_documents()
    typer.echo(f"classified documents: {updated}")


@app.command()
def segment(force: bool = False) -> None:
    """Create paragraph text segments from extracted texts."""
    created = segment_documents(force=force)
    typer.echo(f"segments created: {created}")


@app.command("segment-regions")
def segment_regions(force: bool = False) -> None:
    """Detect and persist document regions."""
    processed = segment_document_regions(force=force)
    typer.echo(f"region documents processed: {processed}")


@app.command()
def inspect(limit: int = 50) -> None:
    """Show a compact document overview."""
    rows = get_overview(limit)

    header = f"{'CATEGORY':15} {'PAGES':5} {'QUALITY':10} {'PATH':45} TITLE"
    typer.echo(header)
    typer.echo("-" * len(header))

    for category, path, title, quality, pages in rows:
        path_short = str(path)[:45]
        title_short = title[:80]
        typer.echo(
            f"{category:15} {str(pages or '-'):5} {quality:10} {path_short:45} {title_short}"
        )


@app.command("inspect-problems")
def inspect_problems(limit: int = 100) -> None:
    """Show documents with poor or empty extracted text."""
    rows = get_empty_or_poor(limit)

    header = f"{'CATEGORY':15} {'PAGES':5} {'QLTY':10} {'TEXTLEN':7} {'PATH':45} TITLE"
    typer.echo(header)
    typer.echo("-" * len(header))

    for category, path, title, quality, pages, text_length in rows:
        path_short = str(path)[:45]
        title_short = title[:80]
        typer.echo(
            f"{category:15} {str(pages or '-'):5} {quality:10} {str(text_length or 0):7} {path_short:45} {title_short}"
        )


@app.command("inspect-ocr-candidates")
def inspect_ocr_candidates(limit: int = 100) -> None:
    """Show OCR candidate documents."""
    rows = get_ocr_candidates(limit)

    header = f"{'CATEGORY':15} {'PAGES':5} {'PATH':45} TITLE"
    typer.echo(header)
    typer.echo("-" * len(header))

    for category, path, title, pages in rows:
        path_short = str(path)[:45]
        title_short = title[:80]
        typer.echo(
            f"{category:15} {str(pages or '-'):5} {path_short:45} {title_short}"
        )


@app.command("inspect-regions")
def inspect_regions_command(limit: int = 100) -> None:
    """Show detected document regions."""
    inspect_regions(limit=limit)


@app.command("state-summary")
def state_summary() -> None:
    """Show counts by document state."""
    rows = get_state_summary()

    typer.echo("DOCUMENT STATES")
    typer.echo("----------------")
    for state, count in rows:
        typer.echo(f"{state:20} {count}")


@app.command("search")
def search(query: str, top_k: int = 10) -> None:
    """Search matching text segments."""
    hits = search_segments(query, top_k=top_k)

    if not hits:
        typer.echo("no results")
        return

    for i, hit in enumerate(hits, start=1):
        typer.echo(f"[{i}] score={hit.score:.4f}")
        typer.echo(f"    path : {hit.relative_path}")
        typer.echo(f"    title: {hit.title}")
        snippet = " ".join(hit.segment_text.split())
        typer.echo(f"    text : {snippet[:300]}")
        typer.echo("")


@app.command("search-docs")
def search_docs(query: str, top_k: int = 10, segment_pool: int = 100) -> None:
    """Search and aggregate hits by document."""
    hits = search_documents(query, top_k=top_k, segment_pool=segment_pool)

    if not hits:
        typer.echo("no results")
        return

    for i, hit in enumerate(hits, start=1):
        typer.echo(f"[{i}] score={hit.score:.4f}")
        typer.echo(f"    path : {hit.relative_path}")
        typer.echo(f"    title: {hit.title}")
        typer.echo(f"    text : {hit.best_snippet}")
        typer.echo("")


@app.command("extract-identifiers")
def extract_identifiers_command() -> None:
    """Extract DOI/ISBN/ISSN/URN/Handle from text, PDF metadata, and filenames."""
    result = extract_identifiers()
    typer.echo(
        "identifiers found: "
        f"text={result['text']} "
        f"pdf_metadata={result['pdf_metadata']} "
        f"filename={result['filename']} "
        f"total={result['total']}"
    )


@app.command("normalize-identifiers")
def normalize_identifiers_command() -> None:
    """Normalize extracted identifiers."""
    updated = normalize_identifiers()
    typer.echo(f"identifiers normalized: {updated}")


@app.command("dedupe-identifiers")
def dedupe_identifiers_command() -> None:
    """Remove duplicate identifiers per document."""
    removed = dedupe_identifiers()
    typer.echo(f"duplicate identifiers removed: {removed}")


@app.command("identifier-summary")
def identifier_summary() -> None:
    """Show identifier counts by type."""
    rows = get_identifier_summary()
    typer.echo("IDENTIFIERS")
    typer.echo("-----------")
    for identifier_type, count in rows:
        typer.echo(f"{identifier_type:12} {count}")


@app.command("identifier-sources")
def identifier_sources() -> None:
    """Show identifier counts by source and type."""
    rows = get_identifier_sources()
    typer.echo("IDENTIFIER SOURCES")
    typer.echo("------------------")
    for source, identifier_type, count in rows:
        typer.echo(f"{source:14} {identifier_type:12} {count}")


@app.command("inspect-identifiers")
def inspect_identifiers(limit: int = 50) -> None:
    """Show sample identifiers with path and source."""
    rows = get_identifier_examples(limit=limit)

    header = f"{'TYPE':10} {'SOURCE':14} {'PATH':45} VALUE"
    typer.echo(header)
    typer.echo("-" * len(header))

    for relative_path, identifier_type, identifier_value, source in rows:
        path_short = str(relative_path)[:45]
        typer.echo(
            f"{identifier_type:10} {source:14} {path_short:45} {identifier_value}"
        )


@app.command("enrich-title-text")
def enrich_title_text() -> None:
    """Infer titles from document text."""
    updated = enrich_title_from_text()
    typer.echo(f"titles updated from text heuristic: {updated}")


@app.command("enrich-title-filename")
def enrich_title_filename() -> None:
    """Fill missing titles from filenames."""
    updated = enrich_titles_from_filename()
    typer.echo(f"titles updated from filename fallback: {updated}")


@app.command("mark-ocr-candidates")
def mark_ocr_candidates_command() -> None:
    """Mark documents with no extracted text as OCR candidates."""
    updated = mark_ocr_candidates()
    typer.echo(f"ocr candidates marked: {updated}")


@app.command("extract-authors")
def extract_authors_command() -> None:
    """Extract author names from PDF metadata and extracted text."""
    result = extract_authors()
    typer.echo(
        "authors found: "
        f"pdf_metadata={result['pdf_metadata']} "
        f"text_heuristic={result['text_heuristic']} "
        f"total={result['total']}"
    )


@app.command("inspect-titles")
def inspect_titles_command(
    limit: int = 80,
    review_only: bool = False,
) -> None:
    """Inspect stored document titles."""
    inspect_titles(limit=limit, review_only=review_only)


@app.command("inspect-title-candidates")
def inspect_title_candidates_command(
    limit: int = 20,
    review_only: bool = True,
    top_k: int = 3,
) -> None:
    """Inspect top scored title candidates per document."""
    inspect_title_candidates(limit=limit, review_only=review_only, top_k=top_k)


@app.command("inspect-authors")
def inspect_authors_command(limit: int = 120) -> None:
    """Inspect extracted authors."""
    inspect_authors(limit)


@app.command("inspect-header")
def inspect_header_command(limit: int = 20) -> None:
    """Inspect parsed document headers."""
    inspect_header(limit)


@app.command("inspect-du-map")
def inspect_du_map(
    limit: int = 10,
    path_filter: str | None = None,
) -> None:
    """Inspect DU block / signal / zone map."""
    inspect_document_map(limit=limit, document_path_filter=path_filter)


@app.command("inspect-du-roles")
def inspect_du_roles_command(
    limit: int = 5,
    path_filter: str | None = None,
) -> None:
    """Inspect inferred DU block roles."""
    inspect_du_roles(limit=limit, path_filter=path_filter)


@app.command("inspect-du-document-type")
def inspect_du_document_type_command(
    limit: int = 20,
    path_filter: str | None = None,
) -> None:
    """Inspect inferred DU document types."""
    inspect_du_document_type(limit=limit, path_filter=path_filter)


@app.command("inspect-du-columns")
def inspect_du_columns_command(limit: int = 5) -> None:
    """Inspect inferred DU columns."""
    inspect_du_columns(limit)


@app.command("inspect-du-sections")
def inspect_du_sections_command(limit: int = 5) -> None:
    """Inspect inferred DU section tree."""
    inspect_du_sections(limit)


@app.command("du-build-map")
def du_build_map(workers: int = 4) -> None:
    from atlas.db.connection import get_connection
    from atlas.document_understanding.persistence.repository import DURepository

    with get_connection() as conn:
        repo = DURepository(conn)
        docs = repo.fetch_documents()

    print(f"DU build: processing {len(docs)} documents with {workers} workers")

    totals = {
        "build": 0.0,
        "topology": 0.0,
        "geometry": 0.0,
        "signals": 0.0,
        "hypotheses": 0.0,
        "memberships": 0.0,
        "semantic": 0.0,
        "total": 0.0,
    }

    t0 = time.perf_counter()

    with mp.Pool(workers) as pool:
        for i, result in enumerate(pool.imap_unordered(du_build_process_document, docs), 1):
            print(f"[{i}/{len(docs)}] {result['path']}")

            totals["build"] += result["build"]
            totals["topology"] += result["topology"]
            totals["geometry"] += result["geometry"]
            totals["signals"] += result["signals"]
            totals["hypotheses"] += result["hypotheses"]
            totals["memberships"] += result["memberships"]
            totals["semantic"] += result["semantic"]
            totals["total"] += result["total"]

    t1 = time.perf_counter()

    print("DU build: stage totals")
    print(f"    build       {totals['build']:.3f}s")
    print(f"    topology    {totals['topology']:.3f}s")
    print(f"    geometry    {totals['geometry']:.3f}s")
    print(f"    signals     {totals['signals']:.3f}s")
    print(f"    hypotheses  {totals['hypotheses']:.3f}s")
    print(f"    memberships {totals['memberships']:.3f}s")
    print(f"    semantic    {totals['semantic']:.3f}s")
    print(f"    total       {totals['total']:.3f}s")
    print(f"DU build: wall time {t1 - t0:.3f}s")
    print("DU build: done")


def main() -> None:
    app()


if __name__ == "__main__":
    main()
