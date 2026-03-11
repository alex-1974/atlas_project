from __future__ import annotations

import typer
from atlas.db.migrate import run_migrations
from atlas.ingest.discovery import discover_pdfs
from atlas.ingest.registration import register_document
from atlas.extract.text_fallback import run_pdftotext_fallback
from atlas.extract.text_pymupdf import extract_text_pymupdf
from atlas.db.migrate import run_migrations
from atlas.extract.pdf_metadata import extract_pdf_metadata
from atlas.enrich.document_state import classify_documents
from atlas.enrich.pdf_metadata_titles import enrich_titles_from_pdf_metadata
from atlas.enrich.quality import enrich_text_quality
from atlas.ingest.discovery import discover_pdfs
from atlas.ingest.registration import register_document
from atlas.extract.text_fallback import run_pdftotext_fallback
from atlas.extract.text_pymupdf import extract_text_pymupdf
from atlas.segment.paragraphs import segment_documents
from atlas.inspect.ocr import get_ocr_candidates
from atlas.inspect.overview import get_overview
from atlas.inspect.problems import get_empty_or_poor
from atlas.inspect.states import get_state_summary
from atlas.search.document_search import search_documents
from atlas.search.lexical import search_segments
from atlas.extract.identifiers import extract_identifiers
from atlas.inspect.identifiers import (
    get_identifier_examples,
    get_identifier_sources,
    get_identifier_summary,
)
from atlas.normalize.identifiers import dedupe_identifiers, normalize_identifiers

app = typer.Typer(help="Atlas literature catalog CLI.")


@app.command()
def version() -> None:
    """Show Atlas version."""
    typer.echo("atlas 0.1.0")

@app.command()
def migrate():
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

    from atlas.ingest.discovery import discover_pdfs
    from atlas.ingest.registration import register_document

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
    inserted = extract_pdf_metadata()
    typer.echo(f"metadata extracted: {inserted}")


@app.command("enrich-metadata-titles")
def enrich_metadata_titles() -> None:
    updated = enrich_titles_from_pdf_metadata()
    typer.echo(f"titles updated from pdf metadata: {updated}")


@app.command("enrich-quality")
def enrich_quality() -> None:
    updated = enrich_text_quality()
    typer.echo(f"text quality updated: {updated}")


@app.command("classify")
def classify() -> None:
    updated = classify_documents()
    typer.echo(f"classified documents: {updated}")

@app.command()
def segment(force: bool = False) -> None:
    """Create paragraph text segments from extracted texts."""
    created = segment_documents(force=force)
    typer.echo(f"segments created: {created}")
    
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
        
def main() -> None:
    app()


if __name__ == "__main__":
    main()
