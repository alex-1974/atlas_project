from __future__ import annotations

import json
from pathlib import Path

import typer
from rich.console import Console
from rich.table import Table
import logging
import os

from atlas.catalog.add import add_document
from atlas.catalog.init import init_catalog
from atlas.catalog.remove import remove_document
from atlas.catalog.update import update_catalog
from atlas.db.connection import connect
from atlas.db.migrate import assert_schema_current
from atlas.parse import analyze_document
from atlas.parse.config import ParseConfig
from atlas.eval.geometry_eval import evaluate_geometry_against_ground_truth

logging.basicConfig(
    level=getattr(logging, os.getenv("PYTHONLOGLEVEL", "INFO").upper(), logging.INFO),
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
    
console = Console()
app = typer.Typer(
    help="Atlas — lokales Werkzeug für PDF-Sammlungen",
    no_args_is_help=True,
)


# ── Helpers ───────────────────────────────────────────────────────────────────

def _catalog_root(cwd: Path | None = None) -> Path:
    return (cwd or Path.cwd()).resolve()


def _db_path(root: Path) -> Path:
    return root / ".atlas" / "catalog.db"


def _require_catalog(root: Path) -> None:
    if not _db_path(root).exists():
        console.print(
            "[red]Kein Katalog gefunden.[/red] "
            "Führe zuerst [bold]atlas init[/bold] aus."
        )
        raise typer.Exit(1)


def _open(root: Path):
    conn = connect(_db_path(root))
    assert_schema_current(conn)
    return conn


# ── Öffentliche Kommandos ─────────────────────────────────────────────────────

@app.command()
def init(
    path: str = typer.Argument(".", help="Wurzelordner der Sammlung"),
) -> None:
    """Katalog initialisieren."""
    init_catalog(Path(path))


@app.command()
def add(
    target: str = typer.Argument(..., help="PDF-Datei oder Ordner"),
    resume: bool = typer.Option(
        False,
        "--resume",
        help="Unterbrochenen Lauf fortsetzen",
    ),
) -> None:
    """Ein Dokument oder einen Ordner indexieren."""
    root = _catalog_root()
    _require_catalog(root)
    p = Path(target).resolve()

    if not p.exists():
        console.print(f"[red]Nicht gefunden:[/red] {p}")
        raise typer.Exit(1)

    if p.is_file():
        if p.suffix.lower() != ".pdf":
            console.print(f"[red]Kein PDF:[/red] {p}")
            raise typer.Exit(1)
        with console.status(f"Verarbeite {p.name}…"):
            result = add_document(root, p)
        if result["skipped"]:
            console.print(f"[dim]Übersprungen (bereits indexiert):[/dim] {p.name}")
        else:
            console.print(
                f"[green]✓[/green] {p.name}  [dim]{result['document_id'][:12]}[/dim]"
            )
        return

    if p.is_dir():
        pdfs = sorted(p.rglob("*.pdf"))
        if not pdfs:
            console.print(f"[yellow]Keine PDFs gefunden in:[/yellow] {p}")
            raise typer.Exit(0)

        console.print(f"Gefunden: {len(pdfs)} PDF(s)")
        ok = skipped = failed = 0

        for pdf in pdfs:
            with console.status(f"{pdf.name}…"):
                try:
                    r = add_document(root, pdf)
                    if r["skipped"]:
                        skipped += 1
                    else:
                        ok += 1
                        console.print(f"  [green]✓[/green] {pdf.name}")
                except Exception as exc:
                    failed += 1
                    console.print(f"  [red]✗[/red] {pdf.name}: {exc}")

        console.print(
            f"\n[bold]{ok} indexiert, {skipped} übersprungen, {failed} Fehler[/bold]"
        )
        return

    console.print(f"[red]Unbekannter Pfadtyp:[/red] {p}")
    raise typer.Exit(1)


@app.command()
def update() -> None:
    """Neue PDFs im Katalogordner erkennen und indexieren."""
    root = _catalog_root()
    _require_catalog(root)
    with console.status("Suche neue PDFs…"):
        result = update_catalog(root)

    console.print(
        f"[green]{result['new']} neu indexiert[/green]  "
        f"{result['skipped']} bereits bekannt  "
        f"{'[red]' + str(result['failed']) + ' Fehler[/red]' if result['failed'] else ''}"
    )
    for name, err in result["errors"]:
        console.print(f"  [red]✗[/red] {name}: {err}")


@app.command()
def remove(
    doc_id: str = typer.Argument(..., help="Dokument-ID (auch Präfix)"),
    yes: bool = typer.Option(
        False,
        "--yes",
        "-y",
        help="Ohne Rückfrage löschen",
    ),
) -> None:
    """Dokument aus allen Indexschichten entfernen."""
    root = _catalog_root()
    _require_catalog(root)
    conn = _open(root)
    row = conn.execute(
        "SELECT document_id, file_name FROM documents WHERE document_id LIKE ?",
        (f"{doc_id}%",),
    ).fetchone()
    conn.close()

    if not row:
        console.print(f"[red]Nicht gefunden:[/red] {doc_id}")
        raise typer.Exit(1)

    if not yes:
        typer.confirm(
            f"Dokument '{row['file_name']}' ({row['document_id'][:12]}) entfernen?",
            abort=True,
        )

    ok = remove_document(root, row["document_id"])
    if ok:
        console.print(f"[green]✓ Entfernt:[/green] {row['file_name']}")
        return

    console.print("[red]Fehler beim Entfernen.[/red]")
    raise typer.Exit(1)


@app.command()
def status(
    as_json: bool = typer.Option(False, "--json"),
) -> None:
    """Kataloggröße und Verarbeitungsstatus anzeigen."""
    root = _catalog_root()
    _require_catalog(root)
    conn = _open(root)

    total = conn.execute("SELECT COUNT(*) FROM documents").fetchone()[0]
    by_status = {
        r[0]: r[1]
        for r in conn.execute(
            "SELECT pipeline_status, COUNT(*) FROM documents GROUP BY pipeline_status"
        ).fetchall()
    }
    conn.close()

    if as_json:
        typer.echo(json.dumps({"total": total, "by_status": by_status}))
        return

    console.print(f"\n[bold]Atlas Katalog[/bold]  {root}")
    console.print(f"  Dokumente gesamt:  {total}")
    for s, n in sorted(by_status.items()):
        color = "green" if s == "indexed" else "red" if s == "failed" else "yellow"
        console.print(f"  [{color}]{s:<16}[/{color}]  {n}")

    try:
        from atlas.knowledge.sparql import graph_stats
        from atlas.knowledge.store import KnowledgeStore

        ks = KnowledgeStore.open(root)
        gstats = graph_stats(ks)
        if gstats.get("citations", 0) or gstats.get("wikidata", 0):
            console.print()
            console.print(
                f"  Wissensgraph:      "
                f"{gstats.get('authors', 0)} Autoren  "
                f"{gstats.get('citations', 0)} Zitationen"
            )
            if gstats.get("wikidata", 0):
                console.print(f"  Wikidata:          {gstats['wikidata']} Verknüpfungen")
            if gstats.get("orcids", 0):
                console.print(f"  ORCIDs:            {gstats['orcids']} Autoren-IDs")
    except Exception:
        pass

    console.print()


@app.command()
def inspect(
    doc_id: str = typer.Argument(..., help="Dokument-ID (SHA-256, auch Präfix)"),
    as_json: bool = typer.Option(False, "--json"),
) -> None:
    """Einzeldokument im Detail anzeigen."""
    root = _catalog_root()
    _require_catalog(root)
    conn = _open(root)

    row = conn.execute(
        "SELECT * FROM documents WHERE document_id LIKE ?",
        (f"{doc_id}%",),
    ).fetchone()
    if not row:
        console.print(f"[red]Nicht gefunden:[/red] {doc_id}")
        conn.close()
        raise typer.Exit(1)

    doc = dict(row)
    tree = conn.execute(
        "SELECT level, title FROM du_section_tree WHERE document_id=? ORDER BY start_block_index",
        (doc["document_id"],),
    ).fetchall()
    conn.close()

    if as_json:
        doc["section_tree"] = [dict(n) for n in tree]
        typer.echo(json.dumps(doc, default=str))
        return

    console.print(
        f"\n[bold]{doc.get('title') or doc.get('file_name') or doc['document_id']}[/bold]"
    )
    console.print(f"  ID:      {doc['document_id']}")
    console.print(f"  Status:  {doc['pipeline_status']}")
    console.print(f"  Typ:     {doc.get('du_document_type') or '—'}")
    if doc.get("authors"):
        console.print(f"  Autoren: {doc['authors']}")
    if doc.get("year"):
        console.print(f"  Jahr:    {doc['year']}")
    if doc.get("doi"):
        console.print(f"  DOI:     {doc['doi']}")
    if doc.get("pipeline_error"):
        console.print(f"  [red]Fehler:[/red]  {doc['pipeline_error'][:200]}")

    if doc.get("topic"):
        console.print(f"  Topic:    {doc['topic'][:120]}")

    if doc.get("keywords"):
        try:
            kws = json.loads(doc["keywords"])
            console.print(f"  Keywords: {', '.join(kws[:8])}")
        except Exception:
            pass

    if doc.get("subjects"):
        try:
            subjects = json.loads(doc["subjects"])
            console.print(f"  Themen:   {', '.join(subjects[:5])}")
        except Exception:
            pass

    try:
        from atlas.knowledge.sparql import (
            orcids_for_document,
            wikidata_qid_for_document,
        )
        from atlas.knowledge.store import KnowledgeStore

        ks = KnowledgeStore.open(root)
        qid = wikidata_qid_for_document(ks, doc["document_id"])
        if qid:
            console.print(f"  Wikidata: {qid}")
        for o in orcids_for_document(ks, doc["document_id"]):
            if o.get("orcid"):
                console.print(f"  ORCID:    {o['name']} → {o['orcid']}")
    except Exception:
        pass

    if tree:
        console.print("\n  [bold]Struktur:[/bold]")
        for node in tree:
            indent = "    " + "  " * (node["level"] - 1)
            console.print(f"{indent}{'—' if node['level'] > 1 else '•'} {node['title']}")
    console.print()


@app.command()
def search(
    query: str = typer.Argument(..., help="Suchanfrage"),
    top_k: int = typer.Option(10, "--top-k", "-k"),
    as_json: bool = typer.Option(False, "--json"),
) -> None:
    """Volltextsuche via FTS5."""
    root = _catalog_root()
    _require_catalog(root)
    conn = _open(root)

    rows = conn.execute(
        """SELECT d.document_id, d.title, d.file_name, d.year, f.rank
           FROM documents_fts f
           JOIN documents d ON d.document_id = f.document_id
           WHERE documents_fts MATCH ?
           ORDER BY rank LIMIT ?""",
        (query, top_k),
    ).fetchall()
    conn.close()

    if as_json:
        typer.echo(json.dumps([dict(r) for r in rows], default=str))
        return

    if not rows:
        console.print("[dim]Keine Treffer.[/dim]")
        return

    table = Table(show_header=True, header_style="bold")
    table.add_column("Titel", max_width=60)
    table.add_column("Jahr", justify="right")
    table.add_column("ID", style="dim")
    for r in rows:
        table.add_row(
            r["title"] or r["file_name"] or "—",
            str(r["year"] or ""),
            r["document_id"][:12],
        )
    console.print(table)


@app.command()
def find(
    author: str | None = typer.Option(None, "--author", help="Autorenname (Teilstring)"),
    year: str | None = typer.Option(None, "--year", help="Jahr oder Bereich 2017-2023"),
    doi: str | None = typer.Option(None, "--doi", help="DOI"),
    doc_type: str | None = typer.Option(None, "--type", help="Dokumenttyp"),
    as_json: bool = typer.Option(False, "--json"),
) -> None:
    """Strukturierte Suche mit Filtern."""
    root = _catalog_root()
    _require_catalog(root)
    conn = _open(root)

    conditions: list[str] = []
    params: list[object] = []

    if author:
        conditions.append("authors LIKE ?")
        params.append(f"%{author}%")
    if doi:
        conditions.append("doi = ?")
        params.append(doi)
    if doc_type:
        conditions.append("du_document_type = ?")
        params.append(doc_type)
    if year:
        if "-" in year:
            y1, y2 = year.split("-", 1)
            conditions.append("year BETWEEN ? AND ?")
            params.extend([int(y1), int(y2)])
        else:
            conditions.append("year = ?")
            params.append(int(year))

    where = ("WHERE " + " AND ".join(conditions)) if conditions else ""
    rows = conn.execute(
        f"SELECT document_id, title, file_name, authors, year, du_document_type "
        f"FROM documents {where}",
        params,
    ).fetchall()
    conn.close()

    if as_json:
        typer.echo(json.dumps([dict(r) for r in rows], default=str))
        return

    if not rows:
        console.print("[dim]Keine Treffer.[/dim]")
        return

    table = Table(show_header=True, header_style="bold")
    table.add_column("Titel", max_width=55)
    table.add_column("Typ", width=10)
    table.add_column("Jahr", justify="right", width=6)
    table.add_column("ID", style="dim", width=12)
    for r in rows:
        table.add_row(
            r["title"] or r["file_name"] or "—",
            r["du_document_type"] or "—",
            str(r["year"] or ""),
            r["document_id"][:12],
        )
    console.print(table)


@app.command()
def similar(
    doc_id: str = typer.Argument(..., help="Dokument-ID (auch Präfix)"),
    top_k: int = typer.Option(5, "--top-k", "-k"),
    as_json: bool = typer.Option(False, "--json"),
) -> None:
    """Ähnliche Dokumente via semantische Suche finden."""
    root = _catalog_root()
    _require_catalog(root)
    conn = _open(root)

    row = conn.execute(
        "SELECT document_id, title, file_name FROM documents WHERE document_id LIKE ?",
        (f"{doc_id}%",),
    ).fetchone()
    if not row:
        console.print(f"[red]Nicht gefunden:[/red] {doc_id}")
        conn.close()
        raise typer.Exit(1)
    full_id = row["document_id"]

    try:
        from atlas.embeddings.store import EmbeddingStore
    except ImportError:
        console.print(
            "[red]LanceDB nicht installiert.[/red] "
            "Führe: pip install lancedb sentence-transformers"
        )
        conn.close()
        raise typer.Exit(1)

    store = EmbeddingStore.open(root)
    results = store.similar_documents(full_id, top_k=top_k)

    if not results:
        console.print("[dim]Keine ähnlichen Dokumente gefunden.[/dim]")
        conn.close()
        return

    enriched = []
    for r in results:
        meta = conn.execute(
            "SELECT title, file_name, year FROM documents WHERE document_id = ?",
            (r["document_id"],),
        ).fetchone()
        enriched.append(
            {
                "document_id": r["document_id"],
                "score": round(r["score"], 3),
                "title": meta["title"] if meta else None,
                "file_name": meta["file_name"] if meta else None,
                "year": meta["year"] if meta else None,
            }
        )
    conn.close()

    if as_json:
        typer.echo(json.dumps(enriched, default=str))
        return

    table = Table(show_header=True, header_style="bold")
    table.add_column("Score", width=7)
    table.add_column("Titel", max_width=55)
    table.add_column("Jahr", justify="right", width=6)
    table.add_column("ID", style="dim", width=12)
    for r in enriched:
        table.add_row(
            str(r["score"]),
            r["title"] or r["file_name"] or "—",
            str(r["year"] or ""),
            r["document_id"][:12],
        )
    console.print(table)


@app.command()
def refs(
    doc_id: str = typer.Argument(..., help="Dokument-ID (auch Präfix)"),
    depth: int = typer.Option(1, "--depth", "-d", help="1=direkt, 2=transitiv"),
    as_json: bool = typer.Option(False, "--json"),
) -> None:
    """Referenznetzwerk eines Dokuments anzeigen."""
    root = _catalog_root()
    _require_catalog(root)
    conn = _open(root)

    row = conn.execute(
        "SELECT document_id, title, file_name FROM documents WHERE document_id LIKE ?",
        (f"{doc_id}%",),
    ).fetchone()
    if not row:
        console.print(f"[red]Nicht gefunden:[/red] {doc_id}")
        conn.close()
        raise typer.Exit(1)
    full_id = row["document_id"]
    conn.close()

    from atlas.knowledge.sparql import references_for_document
    from atlas.knowledge.store import KnowledgeStore

    store = KnowledgeStore.open(root)
    results = references_for_document(store, full_id, depth=depth)

    if as_json:
        typer.echo(json.dumps(results, default=str))
        return

    title = row["title"] or row["file_name"] or full_id[:12]
    console.print(f"\n[bold]Referenzen:[/bold] {title}\n")

    if not results:
        console.print("[dim]Keine Referenzen gefunden.[/dim]")
        return

    table = Table(show_header=True, header_style="bold")
    table.add_column("T", width=3, justify="right")
    table.add_column("DOI / Titel", max_width=60)
    table.add_column("Lokal", width=5)
    for r in results:
        label = r.get("doi") or r.get("title") or r.get("uri", "")[:50]
        local = "✓" if r.get("document_id") else "—"
        table.add_row(str(r["depth"]), str(label)[:60], local)
    console.print(table)


@app.command()
def graph(
    author: str = typer.Option(..., "--author", help="Autorenname"),
    as_dot: bool = typer.Option(False, "--dot", help="Graphviz DOT-Format ausgeben"),
    as_json: bool = typer.Option(False, "--json"),
) -> None:
    """Co-Autoren-Graph für einen Autor."""
    root = _catalog_root()
    _require_catalog(root)

    from atlas.knowledge.sparql import coauthors_of
    from atlas.knowledge.store import KnowledgeStore

    store = KnowledgeStore.open(root)
    results = coauthors_of(store, author)

    if as_json:
        typer.echo(json.dumps(results, default=str))
        return

    if as_dot:
        lines = ["digraph coauthors {", "  rankdir=LR;"]
        for r in results:
            label = r["shared_papers"]
            lines.append(f'  "{author}" -> "{r["name"]}" [label="{label}"];')
        lines.append("}")
        typer.echo("\n".join(lines))
        return

    if not results:
        console.print(f"[dim]Keine Co-Autoren für »{author}« gefunden.[/dim]")
        return

    table = Table(show_header=True, header_style="bold")
    table.add_column("Co-Autor", max_width=45)
    table.add_column("Gemeinsame Dokumente", justify="right", width=22)
    for r in results:
        table.add_row(r["name"], str(r["shared_papers"]))
    console.print(table)


@app.command()
def concept(
    term: str = typer.Argument(..., help="Konzept oder Schlagwort"),
    as_json: bool = typer.Option(False, "--json"),
) -> None:
    """Dokumente zu einem Konzept oder Schlagwort finden."""
    root = _catalog_root()
    _require_catalog(root)
    conn = _open(root)

    from atlas.knowledge.sparql import documents_about_concept
    from atlas.knowledge.store import KnowledgeStore

    store = KnowledgeStore.open(root)
    results = documents_about_concept(store, term)

    kw_rows = conn.execute(
        "SELECT document_id, title FROM documents WHERE keywords LIKE ?",
        (f"%{term}%",),
    ).fetchall()

    existing_ids = {r.get("document_id") for r in results if r.get("document_id")}
    for r in kw_rows:
        if r["document_id"] not in existing_ids:
            results.append(
                {
                    "document_id": r["document_id"],
                    "title": r["title"],
                    "relation": "keyword",
                }
            )

    for r in results:
        if not r.get("title") and r.get("document_id"):
            meta = conn.execute(
                "SELECT title, file_name FROM documents WHERE document_id = ?",
                (r["document_id"],),
            ).fetchone()
            if meta:
                r["title"] = meta["title"] or meta["file_name"]
    conn.close()

    if as_json:
        typer.echo(json.dumps(results, default=str))
        return

    if not results:
        console.print(f"[dim]Keine Dokumente für »{term}« gefunden.[/dim]")
        return

    table = Table(show_header=True, header_style="bold")
    table.add_column("Relation", width=14)
    table.add_column("Titel", max_width=55)
    table.add_column("ID", style="dim", width=12)
    for r in results:
        table.add_row(
            r.get("relation") or "—",
            str(r.get("title") or "—")[:55],
            (r.get("document_id") or "")[:12],
        )
    console.print(table)


@app.command()
def enrich(
    doc_id: str | None = typer.Argument(None, help="Dokument-ID (leer = alle)"),
    all_docs: bool = typer.Option(False, "--all", help="Alle Dokumente"),
    do_keywords: bool = typer.Option(False, "--keywords", help="Keywords via YAKE"),
    do_kw_sem: bool = typer.Option(
        False,
        "--keywords-semantic",
        help="Keywords via KeyBERT",
    ),
    do_topic: bool = typer.Option(False, "--topic", help="Topic-Satz extrahieren"),
    do_sec_kw: bool = typer.Option(
        False,
        "--section-keywords",
        help="Keywords pro Kapitel",
    ),
    do_themes: bool = typer.Option(False, "--themes", help="Themen via RVK + Wikidata"),
    do_gnd: bool = typer.Option(False, "--gnd", help="GND-Entitäten via lobid.org"),
    do_crossref: bool = typer.Option(False, "--crossref", help="CrossRef"),
    do_wikidata: bool = typer.Option(False, "--wikidata", help="Wikidata"),
    do_rvk: bool = typer.Option(False, "--rvk", help="RVK"),
    as_json: bool = typer.Option(False, "--json"),
) -> None:
    """Dokument(e) mit externen Quellen anreichern."""
    root = _catalog_root()
    _require_catalog(root)
    conn = _open(root)

    if all_docs or doc_id is None:
        doc_ids = [
            r["document_id"]
            for r in conn.execute(
                "SELECT document_id FROM documents WHERE pipeline_status = 'indexed'"
            ).fetchall()
        ]
    else:
        row = conn.execute(
            "SELECT document_id FROM documents WHERE document_id LIKE ?",
            (f"{doc_id}%",),
        ).fetchone()
        if not row:
            console.print(f"[red]Nicht gefunden:[/red] {doc_id}")
            conn.close()
            raise typer.Exit(1)
        doc_ids = [row["document_id"]]

    if not doc_ids:
        console.print("[dim]Keine indexierten Dokumente.[/dim]")
        conn.close()
        return

    run_keywords = do_keywords or not any(
        [
            do_crossref,
            do_wikidata,
            do_rvk,
            do_kw_sem,
            do_themes,
            do_gnd,
            do_topic,
            do_sec_kw,
        ]
    )

    summary: list[dict] = []

    for did in doc_ids:
        meta = conn.execute(
            "SELECT title, file_name FROM documents WHERE document_id = ?",
            (did,),
        ).fetchone()
        name = (meta["title"] or meta["file_name"] or did[:12])[:55] if meta else did[:12]
        entry: dict = {"document_id": did, "name": name}

        if not as_json:
            console.print(f"  [dim]{name}[/dim]")

        if do_topic:
            try:
                from atlas.enrich.topic import extract_topic

                topic = extract_topic(conn, did, force=True)
                entry["topic"] = topic
                if topic and not as_json:
                    console.print(f"    Topic: {topic[:80]}")
                elif not topic and not as_json:
                    console.print("    Topic: nicht gefunden")
            except Exception as exc:
                entry["topic_error"] = str(exc)
                if not as_json:
                    console.print(f"    [yellow]Topic: {exc}[/yellow]")

        if do_sec_kw:
            try:
                from atlas.semantic.section_text import extract_section_texts
                from atlas.semantic.keywords import extract_keywords
                from atlas.semantic.persist import (
                    save_section_keywords, aggregate_document_keywords,
                    save_document_keywords,
                )
                from atlas.parse.geometry import build_document_geometry_profile

                doc_row = conn.execute(
                    "SELECT file_path, language FROM documents WHERE document_id=?",
                    (did,)
                ).fetchone()
                pdf_path = Path(doc_row["file_path"])
                doc_lang = doc_row["language"] or "en"

                profile, _ = build_document_geometry_profile(pdf_path)
                texts    = extract_section_texts(pdf_path, conn, did, profile=profile)
                sec_kws  = extract_keywords(texts, document_language=doc_lang)
                n_saved  = save_section_keywords(conn, did, sec_kws, force=True)
                doc_kws  = aggregate_document_keywords(sec_kws)
                save_document_keywords(conn, did, doc_kws, force=True)

                entry["section_keywords"] = n_saved
                if sec_kws and not as_json:
                    console.print(f"    Kapitel-Keywords: {n_saved} Sektionen, "
                                  f"{len(doc_kws)} Dokument-Keywords")
            except Exception as exc:
                entry["section_keywords_error"] = str(exc)
                if not as_json:
                    console.print(f"    [yellow]Kapitel-Keywords: {exc}[/yellow]")

        if run_keywords:
            from atlas.enrich.keywords import extract_keywords

            kws = extract_keywords(conn, did, use_yake=True)
            entry["keywords"] = kws
            if kws and not as_json:
                console.print(f"    Keywords (YAKE): {', '.join(kws[:5])}")

        if do_kw_sem:
            from atlas.enrich.keywords import extract_keywords_semantic

            with console.status("KeyBERT…"):
                kws = extract_keywords_semantic(conn, did)
            entry["keywords_semantic"] = kws
            if kws and not as_json:
                console.print(f"    Keywords (KeyBERT): {', '.join(kws[:5])}")

        if do_themes:
            try:
                from atlas.enrich.themes import extract_themes

                ks = None
                try:
                    from atlas.knowledge.store import KnowledgeStore

                    ks = KnowledgeStore.open(root)
                except Exception:
                    pass

                themes_list = extract_themes(conn, did, store=ks)
                entry["themes"] = themes_list
                if themes_list and not as_json:
                    console.print(f"    Themen: {', '.join(themes_list[:4])}")
                elif not themes_list and not as_json:
                    console.print("    Themen: keine gefunden")
            except Exception as exc:
                entry["themes_error"] = str(exc)
                if not as_json:
                    console.print(f"    [yellow]Themen: {exc}[/yellow]")

        if do_gnd:
            try:
                from atlas.enrich.gnd import enrich_document as _gnd

                ks = None
                try:
                    from atlas.knowledge.store import KnowledgeStore

                    ks = KnowledgeStore.open(root)
                except Exception:
                    pass

                gnd_ids = _gnd(conn, did, store=ks)
                entry["gnd"] = gnd_ids
                if gnd_ids and not as_json:
                    console.print(f"    GND: {', '.join(gnd_ids[:3])}")
                elif not gnd_ids and not as_json:
                    console.print("    GND: keine Entitäten gefunden")
            except Exception as exc:
                entry["gnd_error"] = str(exc)
                if not as_json:
                    console.print(f"    [yellow]GND: {exc}[/yellow]")

        if do_crossref:
            try:
                from atlas.enrich.crossref import enrich_document as _cr

                cr_meta = _cr(conn, did)
                entry["crossref"] = bool(cr_meta)
                if cr_meta and not as_json:
                    console.print(
                        f"    [green]CrossRef ✓[/green]  "
                        f"{(cr_meta.get('title') or '')[:45]}"
                    )
                elif not cr_meta and not as_json:
                    console.print("    CrossRef: kein Ergebnis")
            except Exception as exc:
                entry["crossref_error"] = str(exc)
                if not as_json:
                    console.print(f"    [yellow]CrossRef: {exc}[/yellow]")

        if do_wikidata:
            try:
                from atlas.enrich.wikidata import enrich_document as _wd
                from atlas.knowledge.store import KnowledgeStore

                ks = KnowledgeStore.open(root)
                result = _wd(conn, ks, did)
                entry["wikidata"] = result.get("qid")
                if result.get("qid") and not as_json:
                    console.print(
                        f"    [green]Wikidata ✓[/green]  "
                        f"{result['qid']}  (via {result.get('source', '?')})"
                    )
                elif not result.get("qid") and not as_json:
                    console.print("    Wikidata: kein Treffer")
            except Exception as exc:
                entry["wikidata_error"] = str(exc)
                if not as_json:
                    console.print(f"    [yellow]Wikidata: {exc}[/yellow]")

        if do_rvk:
            try:
                from atlas.enrich.rvk import enrich_document as _rvk

                notations = _rvk(conn, did)
                entry["rvk"] = notations
                if notations and not as_json:
                    console.print(f"    [green]RVK ✓[/green]  {', '.join(notations)}")
                elif not notations and not as_json:
                    console.print("    RVK: keine Notation gefunden")
            except Exception as exc:
                entry["rvk_error"] = str(exc)
                if not as_json:
                    console.print(f"    [yellow]RVK: {exc}[/yellow]")

        summary.append(entry)

    conn.close()

    if as_json:
        typer.echo(json.dumps(summary, default=str))
    else:
        console.print(
            f"\n[green]✓ Anreicherung abgeschlossen[/green]  "
            f"({len(doc_ids)} Dokument(e))"
        )


@app.command()
def doctor() -> None:
    """Katalog-Konsistenz prüfen."""
    root = _catalog_root()
    _require_catalog(root)
    conn = _open(root)

    issues: list[str] = []

    missing = [
        r["file_path"]
        for r in conn.execute(
            "SELECT file_path FROM documents WHERE pipeline_status != 'failed'"
        ).fetchall()
        if not Path(r["file_path"]).exists()
    ]
    if missing:
        issues.append(f"{len(missing)} PDF(s) nicht mehr auf der Festplatte")

    failed = conn.execute(
        "SELECT COUNT(*) FROM documents WHERE pipeline_status='failed'"
    ).fetchone()[0]
    if failed:
        issues.append(f"{failed} Dokument(e) mit Status 'failed'")

    stuck = conn.execute(
        "SELECT COUNT(*) FROM documents WHERE pipeline_status IN "
        "('extracting','du_processing','indexing')"
    ).fetchone()[0]
    if stuck:
        issues.append(f"{stuck} Dokument(e) in unfertigem Verarbeitungsstatus")

    conn.close()

    if not issues:
        console.print("[green]✓ Kein Problem gefunden.[/green]")
        return

    for issue in issues:
        console.print(f"[yellow]⚠[/yellow]  {issue}")


@app.command("parse")
def parse_document(
    path: Path = typer.Argument(..., help="Pfad zu einem PDF-Dokument"),
    as_json: bool = typer.Option(False, "--json", help="Komplettes Parse-Ergebnis als JSON"),
) -> None:
    """Ein einzelnes PDF mit atlas.parse analysieren."""
    pdf_path = path.resolve()

    if not pdf_path.exists():
        console.print(f"[red]Nicht gefunden:[/red] {pdf_path}")
        raise typer.Exit(1)

    if not pdf_path.is_file():
        console.print(f"[red]Kein Datei-Pfad:[/red] {pdf_path}")
        raise typer.Exit(1)

    if pdf_path.suffix.lower() != ".pdf":
        console.print(f"[red]Kein PDF:[/red] {pdf_path}")
        raise typer.Exit(1)

    config = ParseConfig()
    result = analyze_document(pdf_path, config=config)

    if as_json:
        typer.echo(json.dumps(result.to_dict(), ensure_ascii=False, indent=2, default=str))
        return

    console.print(f"\n[bold]{pdf_path.name}[/bold]")
    console.print(f"  Quelle:        {result.source_path}")
    console.print(f"  Titel:         {result.metadata.title or '—'}")
    console.print(
        f"  Autoren:       {', '.join(result.metadata.authors) if result.metadata.authors else '—'}"
    )
    console.print(f"  Jahr:          {result.metadata.year or '—'}")
    console.print(f"  Dokumenttyp:   {result.metadata.document_type or '—'}")
    console.print(f"  Textsegmente:  {len(result.text_segments)}")
    console.print(f"  Sektionen:     {len(result.sections)}")
    console.print(f"  Identifikator: {len(result.identifiers)}")
    console.print(f"  Referenzen:    {len(result.references)}")

    if result.diagnostics:
        console.print("\n[bold]Diagnostik:[/bold]")
        for key, value in result.diagnostics.items():
            console.print(f"  {key}: {value}")


@app.command("eval-geometry")
def eval_geometry(
    pdf_root: Path = typer.Option(..., "--pdf-root", help="Wurzelordner mit den PDFs"),
    documents_csv: Path = typer.Option(
        Path("evaluation/geometry_ground_truth/documents.csv"),
        "--documents",
        help="CSV mit document_id und filename",
    ),
    ground_truth_csv: Path = typer.Option(
        Path("evaluation/geometry_ground_truth/layout_ground_truth.csv"),
        "--ground-truth",
        help="CSV mit seitenweiser Ground Truth",
    ),
    output_dir: Path = typer.Option(
        Path("evaluation/geometry_results"),
        "--output-dir",
        help="Zielordner für predictions/errors/metrics",
    ),
    as_json: bool = typer.Option(False, "--json"),
) -> None:
    """Geometrieerkennung gegen eine Ground Truth evaluieren."""
    documents_csv = documents_csv.resolve()
    ground_truth_csv = ground_truth_csv.resolve()
    pdf_root = pdf_root.resolve()
    output_dir = output_dir.resolve()

    if not pdf_root.exists() or not pdf_root.is_dir():
        console.print(f"[red]Ungültiger PDF-Root:[/red] {pdf_root}")
        raise typer.Exit(1)

    if not documents_csv.exists():
        console.print(f"[red]Nicht gefunden:[/red] {documents_csv}")
        raise typer.Exit(1)

    if not ground_truth_csv.exists():
        console.print(f"[red]Nicht gefunden:[/red] {ground_truth_csv}")
        raise typer.Exit(1)

    with console.status("Evaluiere Geometrie…"):
        metrics = evaluate_geometry_against_ground_truth(
            pdf_root=pdf_root,
            documents_csv=documents_csv,
            layout_ground_truth_csv=ground_truth_csv,
            output_dir=output_dir,
        )

    if as_json:
        typer.echo(json.dumps(metrics, ensure_ascii=False, indent=2, default=str))
        return

    console.print("\n[bold]Geometry Evaluation[/bold]")
    console.print(f"  Dokumente GT:        {metrics['documents_total_in_ground_truth']}")
    console.print(f"  Dokumente evaluiert: {metrics['documents_evaluated']}")
    console.print(f"  Seiten evaluiert:    {metrics['pages_evaluated']}")
    console.print(f"  Column Accuracy:     {metrics['column_accuracy']:.3f}")

    hm = metrics["header_metrics"]
    fm = metrics["footer_metrics"]

    console.print(
        f"  Header P/R/F1:       {hm['precision']:.3f} / {hm['recall']:.3f} / {hm['f1']:.3f}"
    )
    console.print(
        f"  Footer P/R/F1:       {fm['precision']:.3f} / {fm['recall']:.3f} / {fm['f1']:.3f}"
    )

    console.print("\n[bold]Artefakte[/bold]")
    console.print(f"  predictions:         {metrics['artifacts']['predictions_csv']}")
    console.print(f"  errors:              {metrics['artifacts']['errors_csv']}")
    console.print(f"  metrics:             {metrics['artifacts']['metrics_json']}")

if __name__ == "__main__":
    app()
