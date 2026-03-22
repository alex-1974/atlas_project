from __future__ import annotations

import multiprocessing as mp
import time
from typing import Any

from pathlib import Path
import typer

from atlas.db.connection import get_connection
from atlas.db.migrate import run_migrations

from atlas.document_understanding.inference.consensus import compute_consensus
from atlas.document_understanding.inference.headings import compute_headings
from atlas.document_understanding.inference.document_type import compute_document_type
from atlas.document_understanding.inference.roles import compute_roles
from atlas.document_understanding.inference.semantic_zones import compute_semantic_zones
from atlas.document_understanding.inference.signals import compute_signals
from atlas.document_understanding.inference.zone_hypotheses import compute_zone_hypotheses
from atlas.document_understanding.inference.zone_memberships import compute_zone_memberships
from atlas.document_understanding.layers.context import compute_context
from atlas.document_understanding.layers.document_phase import compute_document_phase
from atlas.document_understanding.layers.geometry import compute_geometry
from atlas.document_understanding.layers.page_furniture import compute_page_furniture
from atlas.document_understanding.layers.semantic_micro import compute_semantic_micro
from atlas.document_understanding.layers.spacing_rhythm import compute_spacing_rhythm
from atlas.document_understanding.layers.surface import compute_surface
from atlas.document_understanding.layers.topology import compute_topology
from atlas.document_understanding.layers.typography import compute_typography
from atlas.document_understanding.layers.section_tree import compute_section_tree
from atlas.document_understanding.layers.zones import compute_zones
from atlas.document_understanding.layout.layout_clusters import compute_layout_clusters
from atlas.document_understanding.layout.layout_graph import compute_layout_graph
from atlas.document_understanding.persistence.repository import Repository
from atlas.document_understanding.segmentation.blocks import build_document

from atlas.enrich.ocr_candidates import mark_ocr_candidates
from atlas.enrich.pdf_metadata_titles import enrich_titles_from_pdf_metadata
from atlas.enrich.quality import enrich_text_quality
from atlas.enrich.title_from_filename import enrich_titles_from_filename
from atlas.enrich.title_from_text import enrich_title_from_text

from atlas.eval.du_eval_csv import run_du_eval_csv

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

        repo.delete_du_document(doc_id)

        build_document(repo, doc_id)

        compute_geometry(repo, doc_id)
        compute_layout_graph(repo, doc_id)
        compute_layout_clusters(repo, doc_id)

        compute_typography(repo, doc_id)
        compute_surface(repo, doc_id)
        compute_context(repo, doc_id)
        compute_semantic_micro(repo, doc_id)
        compute_spacing_rhythm(repo, doc_id)
        compute_topology(repo, doc_id)
        compute_page_furniture(repo, doc_id)

        compute_signals(repo, doc_id)
        compute_roles(repo, doc_id)
        compute_consensus(repo, doc_id)
        compute_headings(repo, doc_id)
        compute_document_phase(repo, doc_id)
        compute_zone_hypotheses(repo, doc_id)
        compute_zone_memberships(repo, doc_id)
        compute_semantic_zones(repo, doc_id)
        compute_zones(repo, doc_id)
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
    processed = 0

    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                select document_id, file_path
                from documents
                order by document_id
                """
            )
            rows = cur.fetchall()

    for document_id, file_path in rows:
        if not file_path:
            continue

        path = Path(file_path)
        if not path.exists():
            typer.echo(f"[skip] missing file: {file_path}")
            continue

        result = extract_text_pymupdf(
            path=path,
            document_id=str(document_id),
            force=force,
        )

        status = result.get("status")
        if status == "ok":
            typer.echo(
                f"[ok] {document_id} "
                f"(lines={result.get('layout_lines')}, spans={result.get('layout_spans')})"
            )
        elif status == "skipped":
            typer.echo(f"[skip] {document_id}")
        else:
            typer.echo(f"[error] {document_id}: {result.get('error')}")

        processed += 1

    typer.echo(f"\nProcessed {processed} documents.")


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
            for index, _ in enumerate(
                pool.imap_unordered(_du_process_document, doc_ids),
                start=1,
            ):
                typer.echo(f"[{index}/{total}] done")

    elapsed = time.perf_counter() - started
    typer.echo(f"DU process-all complete in {elapsed:.2f}s.")


@du_app.command("inspect")
def du_inspect(doc_id: str, limit: int = 50, verbose: bool = True) -> None:
    def _fetch_map(cur, sql: str, params: tuple) -> dict:
        cur.execute(sql, params)
        cols = [d[0] for d in cur.description]
        out = {}
        for row in cur.fetchall():
            rec = dict(zip(cols, row))
            out[rec["block_id"]] = rec
            out[str(rec["block_id"])] = rec
        return out

    def _fmt_float(value, ndigits: int = 3) -> str:
        if value is None:
            return "-"
        try:
            return f"{float(value):.{ndigits}f}"
        except Exception:
            return str(value)

    def _fmt_bool(value) -> str:
        return "T" if bool(value) else "-"

    def _get(mapping: dict, block_id):
        if block_id in mapping:
            return mapping[block_id]
        sid = str(block_id)
        if sid in mapping:
            return mapping[sid]
        return {}

    with get_connection() as conn:
        repo = Repository(conn)

        typer.echo(f"\n=== DU INSPECT: {doc_id} ===\n")

        doc_type = repo.fetch_document_type(doc_id)
        typer.echo("== Document Type ==")
        typer.echo(str(doc_type))
        typer.echo("")

        blocks = repo.fetch_blocks(doc_id)
        roles = repo.fetch_roles(doc_id)

        role_map = {r["block_id"]: r for r in roles}
        role_map.update({str(r["block_id"]): r for r in roles})

        with conn.cursor() as cur:
            phase_map = _fetch_map(
                cur,
                """
                select block_id, phase
                from du_block_phase
                where block_id in (
                    select block_id from du_blocks where document_id = %s
                )
                """,
                (doc_id,),
            )

            topology_hint_map = _fetch_map(
                cur,
                """
                select block_id, repeated_header_footer_hint
                from du_block_topology
                where block_id in (
                    select block_id from du_blocks where document_id = %s
                )
                """,
                (doc_id,),
            )

            geometry_map = _fetch_map(
                cur,
                """
                select *
                from du_block_geometry
                where block_id in (
                    select block_id from du_blocks where document_id = %s
                )
                """,
                (doc_id,),
            )

            typography_map = _fetch_map(
                cur,
                """
                select *
                from du_block_typography
                where block_id in (
                    select block_id from du_blocks where document_id = %s
                )
                """,
                (doc_id,),
            )

            spacing_map = _fetch_map(
                cur,
                """
                select *
                from du_block_spacing_rhythm
                where block_id in (
                    select block_id from du_blocks where document_id = %s
                )
                """,
                (doc_id,),
            )

            topology_signal_map = _fetch_map(
                cur,
                """
                select *
                from du_block_topology_signals
                where block_id in (
                    select block_id from du_blocks where document_id = %s
                )
                """,
                (doc_id,),
            )

            surface_map = _fetch_map(
                cur,
                """
                select *
                from du_block_surface_features
                where block_id in (
                    select block_id from du_blocks where document_id = %s
                )
                """,
                (doc_id,),
            )

            context_map = _fetch_map(
                cur,
                """
                select *
                from du_block_context
                where block_id in (
                    select block_id from du_blocks where document_id = %s
                )
                """,
                (doc_id,),
            )

            semantic_map = _fetch_map(
                cur,
                """
                select *
                from du_block_semantic_micro
                where block_id in (
                    select block_id from du_blocks where document_id = %s
                )
                """,
                (doc_id,),
            )

            furniture_signal_map = _fetch_map(
                cur,
                """
                select *
                from du_block_page_furniture_signals
                where block_id in (
                    select block_id from du_blocks where document_id = %s
                )
                """,
                (doc_id,),
            )

        typer.echo("== Blocks (role | phase | furniture) ==")

        for block in blocks[:limit]:
            bid = block["block_id"]

            role = _get(role_map, bid)
            phase = _get(phase_map, bid).get("phase", "?")
            furn = bool(_get(topology_hint_map, bid).get("repeated_header_footer_hint", False))

            text_preview = (block.get("text") or "")[:100].replace("\n", " ")

            typer.echo(
                f'[{block["block_index"]:03d}] '
                f'{role.get("role", "?"):10} '
                f'{phase:14} '
                f'{"F" if furn else "-"} '
                f'p{block["page_index"]:<2} '
                f"{text_preview}"
            )

            if not verbose:
                continue

            geom = _get(geometry_map, bid)
            typo = _get(typography_map, bid)
            spacing = _get(spacing_map, bid)
            topo_sig = _get(topology_signal_map, bid)
            surf = _get(surface_map, bid)
            ctx = _get(context_map, bid)
            sem = _get(semantic_map, bid)
            furn_sig = _get(furniture_signal_map, bid)

            typer.echo(
                "    geometry: "
                f"x0={_fmt_float(block.get('x0'))} "
                f"y0={_fmt_float(block.get('y0'))} "
                f"x1={_fmt_float(block.get('x1'))} "
                f"y1={_fmt_float(block.get('y1'))} "
                f"w_ratio={_fmt_float(geom.get('width_ratio'))} "
                f"h_ratio={_fmt_float(geom.get('height_ratio'))} "
                f"page_y={_fmt_float(geom.get('page_y_ratio'))} "
                f"doc_y={_fmt_float(geom.get('doc_y_ratio'))} "
                f"full={_fmt_bool(geom.get('full_width_like'))} "
                f"narrow={_fmt_bool(geom.get('narrow_width_like'))} "
                f"col={geom.get('column_hint', '-')}"
            )

            typer.echo(
                "    typography: "
                f"font={typo.get('font_family_normalized') or typo.get('font_family') or typo.get('font_name') or '-'} "
                f"size={_fmt_float(typo.get('font_size'), 2)} "
                f"ratio={_fmt_float(typo.get('font_ratio'))} "
                f"bold={_fmt_bool(typo.get('bold'))} "
                f"italic={_fmt_bool(typo.get('italic'))} "
                f"scaps={_fmt_bool(typo.get('small_caps'))} "
                f"caps={_fmt_bool(typo.get('all_caps'))} "
                f"largest={_fmt_bool(typo.get('largest_on_page'))} "
                f"dom_share={_fmt_float(typo.get('dominant_font_share'))} "
                f"d_prev={_fmt_float(typo.get('font_size_delta_prev'), 2)} "
                f"d_next={_fmt_float(typo.get('font_size_delta_next'), 2)}"
            )

            typer.echo(
                "    spacing: "
                f"gap_b={_fmt_float(spacing.get('line_gap_before'), 2)} "
                f"gap_a={_fmt_float(spacing.get('line_gap_after'), 2)} "
                f"para_b={_fmt_float(spacing.get('paragraph_gap_before'), 2)} "
                f"para_a={_fmt_float(spacing.get('paragraph_gap_after'), 2)} "
                f"indent_l={_fmt_float(spacing.get('indent_left'), 2)} "
                f"indent_r={_fmt_float(spacing.get('indent_right'), 2)} "
                f"align_l={_fmt_float(spacing.get('alignment_left'), 2)} "
                f"align_c={_fmt_float(spacing.get('alignment_center'), 2)} "
                f"cont={_fmt_float(spacing.get('same_column_continuation_like'), 2)} "
                f"break={_fmt_float(spacing.get('new_region_break_like'), 2)}"
            )

            typer.echo(
                "    topology: "
                f"same_prev={_fmt_bool(topo_sig.get('same_page_prev'))} "
                f"same_next={_fmt_bool(topo_sig.get('same_page_next'))} "
                f"trans_b={_fmt_bool(topo_sig.get('page_transition_before'))} "
                f"trans_a={_fmt_bool(topo_sig.get('page_transition_after'))} "
                f"col_prev={_fmt_float(topo_sig.get('same_column_prev_like'), 2)} "
                f"col_next={_fmt_float(topo_sig.get('same_column_next_like'), 2)} "
                f"col_cand={topo_sig.get('column_index_candidate', '-')} "
                f"parity={topo_sig.get('odd_even_page', '-') or '-'} "
                f"early={_fmt_float(topo_sig.get('early_on_page_score'), 2)} "
                f"late={_fmt_float(topo_sig.get('late_on_page_score'), 2)}"
            )

            typer.echo(
                "    surface: "
                f"chars={surf.get('char_count', '-')} "
                f"words={surf.get('word_count', '-')} "
                f"lines={surf.get('line_count', '-')} "
                f"digits={_fmt_float(surf.get('digit_density'), 3)} "
                f"punct={_fmt_float(surf.get('punctuation_density'), 3)} "
                f"starts_num={_fmt_bool(surf.get('starts_with_number'))} "
                f"ends_colon={_fmt_bool(surf.get('ends_with_colon'))} "
                f"doi={_fmt_bool(surf.get('contains_doi'))} "
                f"year={_fmt_bool(surf.get('contains_year'))} "
                f"all_caps={_fmt_bool(surf.get('is_all_caps'))}"
            )

            typer.echo(
                "    context: "
                f"page_y={_fmt_float(ctx.get('page_y_ratio'))} "
                f"doc_y={_fmt_float(ctx.get('doc_y_ratio'))} "
                f"front={_fmt_float(ctx.get('front_matter_score'), 2)} "
                f"body={_fmt_float(ctx.get('body_score'), 2)} "
                f"back={_fmt_float(ctx.get('back_matter_score'), 2)}"
            )

            typer.echo(
                "    semantic_micro: "
                f"abstract={_fmt_bool(sem.get('is_abstract_marker'))} "
                f"keywords={_fmt_bool(sem.get('is_keywords_marker'))} "
                f"refs={_fmt_bool(sem.get('is_references_marker'))} "
                f"figure={_fmt_bool(sem.get('is_figure_marker'))} "
                f"table={_fmt_bool(sem.get('is_table_marker'))} "
                f"appendix={_fmt_bool(sem.get('is_appendix_marker'))} "
                f"doi={_fmt_bool(sem.get('contains_doi'))} "
                f"year={_fmt_bool(sem.get('contains_year'))} "
                f"cit_b={_fmt_bool(sem.get('contains_citation_bracket'))} "
                f"cit_ay={_fmt_bool(sem.get('contains_citation_author_year'))}"
            )

            typer.echo(
                "    page_furniture: "
                f"top={_fmt_bool(furn_sig.get('is_top_band'))} "
                f"bottom={_fmt_bool(furn_sig.get('is_bottom_band'))} "
                f"pnum={_fmt_bool(furn_sig.get('page_number_like'))} "
                f"run_h={_fmt_bool(furn_sig.get('running_header_like'))} "
                f"run_f={_fmt_bool(furn_sig.get('running_footer_like'))} "
                f"rep_pages={_fmt_bool(furn_sig.get('repeated_across_pages'))} "
                f"rep_parity={_fmt_bool(furn_sig.get('repeated_same_parity'))} "
                f"first_meta={_fmt_bool(furn_sig.get('first_page_meta_like'))}"
            )

            typer.echo("")

        if len(blocks) > limit:
            typer.echo(f"... ({len(blocks) - limit} more blocks)")
        typer.echo("")

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
            print(
                f"{s['rank']:>2} {s['doc_type']:<20} "
                f"score={s['score']:.2f} weight={s['weight']:.2f}"
            )

        typer.echo("")


@du_app.command("eval-csv")
def du_eval_csv(csv_path: str) -> None:
    with get_connection() as conn:
        repo = Repository(conn)
        run_du_eval_csv(csv_path, repo)


def main() -> None:
    app()


if __name__ == "__main__":
    main()
