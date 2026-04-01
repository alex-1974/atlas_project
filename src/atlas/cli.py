# src/atlas/cli.py
"""Atlas CLI — lokales Werkzeug zur Erschließung wissenschaftlicher PDF-Sammlungen.

Öffentliche Kommandos:
    atlas init
    atlas add <pdf|ordner> [--resume]
    atlas status
    atlas inspect <id>
    atlas search "<query>" [--top-k N] [--json]
    atlas find [--author] [--year] [--doi] [--type] [--json]
    atlas doctor

Entwicklungsbereich (atlas dev):
    atlas dev db migrate
    atlas dev db reset --confirm
    atlas dev schema
    atlas dev du process <id>
    atlas dev du inspect <id> [--verbose] [--limit N]
    atlas dev du process-all [--workers N]
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import typer
from rich.console import Console
from rich.table import Table
from rich import print as rprint

from atlas.catalog.init import init_catalog
from atlas.catalog.add import add_document, add_directory
from atlas.catalog.update import update_catalog
from atlas.catalog.remove import remove_document
from atlas.db.connection import connect
from atlas.db.migrate import run_migrations, assert_schema_current, list_applied

console = Console()
app     = typer.Typer(help="Atlas — lokales Werkzeug für PDF-Sammlungen",
                      no_args_is_help=True)
dev_app = typer.Typer(help="Entwicklungs- und Debug-Kommandos", hidden=True)
dev_db  = typer.Typer(help="Datenbankoperationen")
dev_du  = typer.Typer(help="Document Understanding")
app.add_typer(dev_app, name="dev")
dev_app.add_typer(dev_db, name="db")
dev_app.add_typer(dev_du, name="du")


# ── Helpers ───────────────────────────────────────────────────────────────────

def _catalog_root(cwd: Path | None = None) -> Path:
    return (cwd or Path.cwd()).resolve()


def _db_path(root: Path) -> Path:
    return root / ".atlas" / "catalog.db"


def _require_catalog(root: Path) -> None:
    if not _db_path(root).exists():
        console.print("[red]Kein Katalog gefunden.[/red] "
                      "Führe zuerst [bold]atlas init[/bold] aus.")
        raise typer.Exit(1)


def _open(root: Path):
    conn = connect(_db_path(root))
    assert_schema_current(conn)
    return conn


# ── Öffentliche Kommandos ─────────────────────────────────────────────────────

@app.command()
def init(path: str = typer.Argument(".", help="Wurzelordner der Sammlung")) -> None:
    """Katalog initialisieren."""
    init_catalog(Path(path))


@app.command()
def add(
    target: str = typer.Argument(..., help="PDF-Datei oder Ordner"),
    resume: bool = typer.Option(False, "--resume",
                                help="Unterbrochenen Lauf fortsetzen"),
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
            console.print(f"[green]✓[/green] {p.name}  [dim]{result['document_id'][:12]}[/dim]")

    elif p.is_dir():
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
        console.print(f"\n[bold]{ok} indexiert, {skipped} übersprungen, {failed} Fehler[/bold]")
    else:
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
    yes: bool = typer.Option(False, "--yes", "-y",
                             help="Ohne Rückfrage löschen"),
) -> None:
    """Dokument aus allen Indexschichten entfernen."""
    root = _catalog_root()
    _require_catalog(root)
    conn = _open(root)
    row  = conn.execute(
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
    else:
        console.print("[red]Fehler beim Entfernen.[/red]")
        raise typer.Exit(1)


@app.command()
def status(
    as_json: bool = typer.Option(False, "--json")) -> None:
    """Kataloggröße und Verarbeitungsstatus anzeigen."""
    root = _catalog_root()
    _require_catalog(root)
    conn = _open(root)

    total = conn.execute("SELECT COUNT(*) FROM documents").fetchone()[0]
    by_status = {r[0]: r[1] for r in conn.execute(
        "SELECT pipeline_status, COUNT(*) FROM documents GROUP BY pipeline_status"
    ).fetchall()}
    conn.close()

    if as_json:
        typer.echo(json.dumps({"total": total, "by_status": by_status}))
        return

    console.print(f"\n[bold]Atlas Katalog[/bold]  {root}")
    console.print(f"  Dokumente gesamt:  {total}")
    for s, n in sorted(by_status.items()):
        color = "green" if s == "indexed" else "red" if s == "failed" else "yellow"
        console.print(f"  [{color}]{s:<16}[/{color}]  {n}")

    # Wissensgraph-Statistiken (optional — schweigt wenn nicht vorhanden)
    try:
        from atlas.knowledge.store import KnowledgeStore
        from atlas.knowledge.sparql import graph_stats
        ks     = KnowledgeStore.open(root)
        gstats = graph_stats(ks)
        if gstats.get("citations", 0) or gstats.get("wikidata", 0):
            console.print()
            console.print(f"  Wissensgraph:      "
                          f"{gstats.get('authors', 0)} Autoren  "
                          f"{gstats.get('citations', 0)} Zitationen")
            if gstats.get("wikidata", 0):
                console.print(f"  Wikidata:          {gstats['wikidata']} Verknüpfungen")
            if gstats.get("orcids", 0):
                console.print(f"  ORCIDs:            {gstats['orcids']} Autoren-IDs")
    except Exception:
        pass  # Wissensgraph noch nicht befüllt — kein Fehler
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

    console.print(f"\n[bold]{doc.get('title') or doc.get('file_name') or doc['document_id']}[/bold]")
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

    # Keywords (aus SQLite)
    if doc.get("keywords"):
        try:
            kws = json.loads(doc["keywords"])
            console.print(f"  Keywords: {', '.join(kws[:8])}")
        except Exception:
            pass

    # Themen/Subjects (aus SQLite)
    if doc.get("subjects"):
        try:
            subjects = json.loads(doc["subjects"])
            console.print(f"  Themen:   {', '.join(subjects[:5])}")
        except Exception:
            pass

    # Externe Identitäten aus Wissensgraph
    try:
        from atlas.knowledge.store import KnowledgeStore
        from atlas.knowledge.sparql import wikidata_qid_for_document, orcids_for_document
        ks  = KnowledgeStore.open(root)
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
            console.print(f"{indent}{'—' if node['level']>1 else '•'} {node['title']}")
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
    author:   str  = typer.Option(None, "--author",  help="Autorenname (Teilstring)"),
    year:     str  = typer.Option(None, "--year",    help="Jahr oder Bereich 2017-2023"),
    doi:      str  = typer.Option(None, "--doi",     help="DOI"),
    doc_type: str  = typer.Option(None, "--type",    help="Dokumenttyp"),
    as_json:  bool = typer.Option(False, "--json"),
) -> None:
    """Strukturierte Suche mit Filtern."""
    root = _catalog_root()
    _require_catalog(root)
    conn = _open(root)

    conditions: list[str] = []
    params:     list      = []

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
    rows  = conn.execute(
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
    table.add_column("Typ",   width=10)
    table.add_column("Jahr",  justify="right", width=6)
    table.add_column("ID",    style="dim", width=12)
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
    doc_id:  str  = typer.Argument(..., help="Dokument-ID (auch Präfix)"),
    top_k:   int  = typer.Option(5, "--top-k", "-k"),
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
        console.print("[red]LanceDB nicht installiert.[/red] "
                      "Führe: pip install lancedb sentence-transformers")
        conn.close()
        raise typer.Exit(1)

    store   = EmbeddingStore.open(root)
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
        enriched.append({
            "document_id": r["document_id"],
            "score":       round(r["score"], 3),
            "title":       meta["title"] if meta else None,
            "file_name":   meta["file_name"] if meta else None,
            "year":        meta["year"] if meta else None,
        })
    conn.close()

    if as_json:
        typer.echo(json.dumps(enriched, default=str))
        return

    table = Table(show_header=True, header_style="bold")
    table.add_column("Score", width=7)
    table.add_column("Titel", max_width=55)
    table.add_column("Jahr",  justify="right", width=6)
    table.add_column("ID",    style="dim", width=12)
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
    doc_id:  str  = typer.Argument(..., help="Dokument-ID (auch Präfix)"),
    depth:   int  = typer.Option(1, "--depth", "-d", help="1=direkt, 2=transitiv"),
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

    from atlas.knowledge.store import KnowledgeStore
    from atlas.knowledge.sparql import references_for_document
    store   = KnowledgeStore.open(root)
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
    author:  str  = typer.Option(..., "--author", help="Autorenname"),
    as_dot:  bool = typer.Option(False, "--dot",  help="Graphviz DOT-Format ausgeben"),
    as_json: bool = typer.Option(False, "--json"),
) -> None:
    """Co-Autoren-Graph für einen Autor."""
    root = _catalog_root()
    _require_catalog(root)

    from atlas.knowledge.store import KnowledgeStore
    from atlas.knowledge.sparql import coauthors_of
    store   = KnowledgeStore.open(root)
    results = coauthors_of(store, author)

    if as_json:
        typer.echo(json.dumps(results, default=str))
        return

    if as_dot:
        lines = ['digraph coauthors {', f'  rankdir=LR;']
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
    table.add_column("Co-Autor",              max_width=45)
    table.add_column("Gemeinsame Dokumente",  justify="right", width=22)
    for r in results:
        table.add_row(r["name"], str(r["shared_papers"]))
    console.print(table)


@app.command()
def concept(
    term:    str  = typer.Argument(..., help="Konzept oder Schlagwort"),
    as_json: bool = typer.Option(False, "--json"),
) -> None:
    """Dokumente zu einem Konzept oder Schlagwort finden."""
    root = _catalog_root()
    _require_catalog(root)
    conn = _open(root)

    from atlas.knowledge.store import KnowledgeStore
    from atlas.knowledge.sparql import documents_about_concept
    store   = KnowledgeStore.open(root)
    results = documents_about_concept(store, term)

    # Ergänze: SQLite-Keywords-Suche
    kw_rows = conn.execute(
        "SELECT document_id, title FROM documents WHERE keywords LIKE ?",
        (f"%{term}%",),
    ).fetchall()
    existing_ids = {r.get("document_id") for r in results if r.get("document_id")}
    for r in kw_rows:
        if r["document_id"] not in existing_ids:
            results.append({
                "document_id": r["document_id"],
                "title":       r["title"],
                "relation":    "keyword",
            })

    # Titel aus SQLite nachfüllen wenn im Graph-Ergebnis leer
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
    table.add_column("Titel",    max_width=55)
    table.add_column("ID",       style="dim", width=12)
    for r in results:
        table.add_row(
            r.get("relation") or "—",
            str(r.get("title") or "—")[:55],
            (r.get("document_id") or "")[:12],
        )
    console.print(table)


@app.command()
def enrich(
    doc_id:       str  = typer.Argument(None,  help="Dokument-ID (leer = alle)"),
    all_docs:     bool = typer.Option(False, "--all",               help="Alle Dokumente"),
    do_keywords:  bool = typer.Option(False, "--keywords",          help="Keywords via YAKE (lokal, schnell)"),
    do_kw_sem:    bool = typer.Option(False, "--keywords-semantic",  help="Keywords via KeyBERT (semantisch, langsamer)"),
    do_themes:    bool = typer.Option(False, "--themes",             help="Themen via RVK + Wikidata"),
    do_crossref:  bool = typer.Option(False, "--crossref",          help="CrossRef (braucht Netz)"),
    do_wikidata:  bool = typer.Option(False, "--wikidata",          help="Wikidata (braucht Netz)"),
    do_rvk:       bool = typer.Option(False, "--rvk",               help="RVK (lokal + Netz)"),
    as_json:      bool = typer.Option(False, "--json"),
) -> None:
    """Dokument(e) mit externen Quellen anreichern."""
    root = _catalog_root()
    _require_catalog(root)
    conn = _open(root)

    if all_docs or doc_id is None:
        doc_ids = [r["document_id"] for r in conn.execute(
            "SELECT document_id FROM documents WHERE pipeline_status = 'indexed'"
        ).fetchall()]
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

    # Ohne explizite Flags: YAKE-Keywords lokal
    run_keywords     = do_keywords or not any([do_crossref, do_wikidata, do_rvk, do_kw_sem, do_themes])
    run_kw_semantic  = do_kw_sem
    run_themes       = do_themes

    summary: list[dict] = []

    for did in doc_ids:
        meta = conn.execute(
            "SELECT title, file_name FROM documents WHERE document_id = ?", (did,)
        ).fetchone()
        name = (meta["title"] or meta["file_name"] or did[:12])[:55] if meta else did[:12]
        entry: dict = {"document_id": did, "name": name}

        if not as_json:
            console.print(f"  [dim]{name}[/dim]")

        if run_keywords:
            from atlas.enrich.keywords import extract_keywords
            kws = extract_keywords(conn, did, use_yake=True)
            entry["keywords"] = kws
            if kws and not as_json:
                console.print(f"    Keywords (YAKE): {', '.join(kws[:5])}")

        if run_kw_semantic:
            from atlas.enrich.keywords import extract_keywords_semantic
            with console.status("KeyBERT…"):
                kws = extract_keywords_semantic(conn, did)
            entry["keywords_semantic"] = kws
            if kws and not as_json:
                console.print(f"    Keywords (KeyBERT): {', '.join(kws[:5])}")

        if run_themes:
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

        if do_crossref:
            try:
                from atlas.enrich.crossref import enrich_document as _cr
                cr_meta = _cr(conn, did)
                entry["crossref"] = bool(cr_meta)
                if cr_meta and not as_json:
                    console.print(f"    [green]CrossRef ✓[/green]  "
                                  f"{(cr_meta.get('title') or '')[:45]}")
                elif not cr_meta and not as_json:
                    console.print("    CrossRef: kein Ergebnis")
            except Exception as exc:
                entry["crossref_error"] = str(exc)
                if not as_json:
                    console.print(f"    [yellow]CrossRef: {exc}[/yellow]")

        if do_wikidata:
            try:
                from atlas.knowledge.store import KnowledgeStore
                from atlas.enrich.wikidata import enrich_document as _wd
                ks     = KnowledgeStore.open(root)
                result = _wd(conn, ks, did)
                entry["wikidata"] = result.get("qid")
                if result.get("qid") and not as_json:
                    console.print(f"    [green]Wikidata ✓[/green]  "
                                  f"{result['qid']}  (via {result.get('source','?')})")
                    for aname, orcid in result.get("orcids", {}).items():
                        console.print(f"      ORCID: {aname} → {orcid}")
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
        console.print(f"\n[green]✓ Anreicherung abgeschlossen[/green]  "
                      f"({len(doc_ids)} Dokument(e))")


@app.command()
def doctor() -> None:
    """Katalog-Konsistenz prüfen."""
    root = _catalog_root()
    _require_catalog(root)
    conn = _open(root)

    issues: list[str] = []

    # 1. Fehlende PDF-Dateien
    missing = [r["file_path"] for r in conn.execute(
        "SELECT file_path FROM documents WHERE pipeline_status != 'failed'"
    ).fetchall() if not Path(r["file_path"]).exists()]
    if missing:
        issues.append(f"{len(missing)} PDF(s) nicht mehr auf der Festplatte")

    # 2. Fehlgeschlagene Dokumente
    failed = conn.execute(
        "SELECT COUNT(*) FROM documents WHERE pipeline_status='failed'"
    ).fetchone()[0]
    if failed:
        issues.append(f"{failed} Dokument(e) mit Status 'failed'")

    # 3. Hängende Verarbeitung
    stuck = conn.execute(
        "SELECT COUNT(*) FROM documents WHERE pipeline_status IN "
        "('extracting','du_processing','indexing')"
    ).fetchone()[0]
    if stuck:
        issues.append(f"{stuck} Dokument(e) in unfertigem Verarbeitungsstatus")

    conn.close()

    if not issues:
        console.print("[green]✓ Kein Problem gefunden.[/green]")
    else:
        for issue in issues:
            console.print(f"[yellow]⚠[/yellow]  {issue}")
        console.print(
            "\nTipp: [bold]atlas dev du process <id>[/bold] "
            "um ein fehlgeschlagenes Dokument neu zu verarbeiten."
        )


# ── atlas dev db ──────────────────────────────────────────────────────────────

@dev_db.command("migrate")
def dev_db_migrate() -> None:
    """Ausstehende Schema-Migrationen anwenden."""
    root = _catalog_root()
    _require_catalog(root)
    conn = connect(_db_path(root))
    run_migrations(conn)
    rows = list_applied(conn)
    conn.close()
    console.print("[green]✓ Migrationen aktuell[/green]")
    for r in rows:
        console.print(f"  {r['version']}  {r['applied_at']}")


@dev_db.command("reset")
def dev_db_reset(
    confirm: bool = typer.Option(False, "--confirm",
                                 help="Sicherheitsbestätigung erforderlich"),
) -> None:
    """Datenbank zurücksetzen (nur für Tests)."""
    if not confirm:
        console.print("[red]Abgebrochen.[/red] Nutze --confirm um wirklich zurückzusetzen.")
        raise typer.Exit(1)
    db = _db_path(_catalog_root())
    if db.exists():
        db.unlink()
        console.print(f"[green]✓ Gelöscht:[/green] {db}")
    else:
        console.print("[dim]Keine Datenbank vorhanden.[/dim]")


@dev_db.command("schema")
def dev_db_schema() -> None:
    """Aktuelles Datenbankschema und Version anzeigen."""
    root = _catalog_root()
    _require_catalog(root)
    conn = connect(_db_path(root))
    rows = list_applied(conn)
    tables = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
    ).fetchall()
    conn.close()

    console.print(f"\n[bold]Angewandte Migrationen:[/bold]")
    for r in rows:
        console.print(f"  {r['version']}  {r['applied_at']}")
    console.print(f"\n[bold]Tabellen ({len(tables)}):[/bold]")
    for t in tables:
        console.print(f"  {t[0]}")
    console.print()


# ── atlas dev du ──────────────────────────────────────────────────────────────

@dev_du.command("process")
def dev_du_process(
    doc_id: str = typer.Argument(..., help="Dokument-ID"),
    recompute: bool = typer.Option(False, "--recompute", "-r",
                                   help="Signale und Layer 3 neu berechnen"),
) -> None:
    """DU-Pipeline für ein Dokument neu berechnen."""
    from atlas.understanding.pipeline import run_du_pipeline
    root = _catalog_root()
    _require_catalog(root)
    conn = _open(root)

    row = conn.execute(
        "SELECT document_id, file_path FROM documents WHERE document_id LIKE ?",
        (f"{doc_id}%",),
    ).fetchone()
    if not row:
        console.print(f"[red]Nicht gefunden:[/red] {doc_id}")
        conn.close()
        raise typer.Exit(1)

    if recompute:
        # Recompute Layer 2+3 with two-pass approach
        from atlas.understanding.aggregate.signals import compute_signals
        from atlas.understanding.interpret.roles import compute_roles
        from atlas.understanding.interpret.consensus import compute_consensus
        from atlas.understanding.interpret.zones import compute_zones
        from atlas.understanding.interpret.headings import compute_headings
        from atlas.understanding.interpret.section_tree import compute_section_tree
        from atlas.understanding.interpret.document_type import compute_document_type

        def _layer3(msg: str) -> None:
            with console.status(msg):
                compute_signals(conn, row["document_id"])
                compute_roles(conn, row["document_id"])
                compute_consensus(conn, row["document_id"])
                compute_zones(conn, row["document_id"])
                compute_headings(conn, row["document_id"])
                compute_section_tree(conn, row["document_id"])

        _layer3("Pass 1 — Signale und Rollen…")
        with console.status("Dokumenttyp erkennen…"):
            compute_document_type(conn, row["document_id"])
        _layer3("Pass 2 — Rollen mit Typ-Anpassungen…")
        conn.close()
        console.print(f"[green]✓ Neu berechnet[/green]  {row['document_id'][:12]}")
        return

    with console.status("DU-Pipeline läuft…"):
        ok = run_du_pipeline(conn, row["document_id"])
    conn.close()

    if ok:
        console.print(f"[green]✓ DU abgeschlossen[/green]  {row['document_id'][:12]}")
    else:
        console.print(f"[yellow]Keine Layout-Daten vorhanden.[/yellow] "
                      "Führe zuerst 'atlas add' aus.")


@dev_du.command("inspect")
def dev_du_inspect(
    doc_id: str = typer.Argument(..., help="Dokument-ID"),
    verbose: bool = typer.Option(False, "--verbose", "-v"),
    limit: int = typer.Option(50, "--limit", "-n"),
) -> None:
    """DU-Ergebnisse eines Dokuments anzeigen."""
    root = _catalog_root()
    _require_catalog(root)
    conn = _open(root)

    doc = conn.execute(
        "SELECT document_id, file_name FROM documents WHERE document_id LIKE ?",
        (f"{doc_id}%",),
    ).fetchone()
    if not doc:
        console.print(f"[red]Nicht gefunden:[/red] {doc_id}")
        conn.close()
        raise typer.Exit(1)

    did = doc["document_id"]

    blocks = conn.execute(
        """SELECT b.block_index, b.page_index, b.text,
                  r.role, s.heading_like, s.body_like, s.noise_like,
                  t.font_size, t.bold, z.zone
           FROM du_blocks b
           LEFT JOIN du_block_roles r ON r.block_id = b.block_id
           LEFT JOIN du_block_signals s ON s.block_id = b.block_id
           LEFT JOIN du_block_typography t ON t.block_id = b.block_id
           LEFT JOIN du_block_zones z ON z.block_id = b.block_id
           WHERE b.document_id = ?
           ORDER BY b.block_index
           LIMIT ?""",
        (did, limit),
    ).fetchall()

    tree = conn.execute(
        "SELECT level, title FROM du_section_tree WHERE document_id=? ORDER BY start_block_index",
        (did,),
    ).fetchall()

    zones_summary = conn.execute(
        "SELECT z.zone, COUNT(*) n FROM du_block_zones z "
        "JOIN du_blocks b ON b.block_id=z.block_id "
        "WHERE b.document_id=? GROUP BY z.zone ORDER BY MIN(b.block_index)",
        (did,),
    ).fetchall()
    conn.close()

    console.print(f"\n[bold]{doc['file_name']}[/bold]  {did[:12]}")

    if zones_summary:
        console.print("\n[bold]Zonen:[/bold]")
        for z in zones_summary:
            console.print(f"  {z['zone']:<16} {z['n']} Blöcke")

    if tree:
        console.print("\n[bold]Section Tree:[/bold]")
        for node in tree:
            indent = "  " + "  " * (node["level"] - 1)
            console.print(f"{indent}L{node['level']} {node['title']}")

    if blocks:
        console.print(f"\n[bold]Blöcke (erste {limit}):[/bold]")
        for b in blocks:
            role   = b["role"] or "?"
            text   = (b["text"] or "")[:60].replace("\n", " ")
            fs     = f"{b['font_size']:.0f}pt" if b["font_size"] else ""
            bold   = " bold" if b["bold"] else ""
            signal = ""
            if verbose and b["heading_like"] is not None:
                signal = (f"  h={b['heading_like']:.2f} "
                          f"b={b['body_like']:.2f} "
                          f"n={b['noise_like']:.2f}")
            color = {
                "heading": "cyan", "title": "bold cyan",
                "body": "white", "reference": "blue",
                "caption": "magenta", "noise": "dim",
                "page_furniture": "dim", "author": "green",
            }.get(role, "white")
            console.print(
                f"  [{b['block_index']:03d}] [{color}]{role:<14}[/{color}] "
                f"p{b['page_index']} {fs}{bold}  {text!r}{signal}"
            )
    console.print()


@dev_du.command("process-all")
def dev_du_process_all(
    workers: int = typer.Option(1, "--workers", "-w"),
    recompute: bool = typer.Option(False, "--recompute", "-r",
                                    help="Nur Layer 2+3 neu berechnen (schneller)"),
) -> None:
    """DU für alle Dokumente neu berechnen."""
    from atlas.understanding.pipeline import run_du_pipeline
    root = _catalog_root()
    _require_catalog(root)
    conn = _open(root)

    docs = conn.execute(
        "SELECT document_id FROM documents WHERE pipeline_status != 'failed'"
    ).fetchall()
    conn.close()

    console.print(f"Verarbeite {len(docs)} Dokument(e)…")
    ok = failed = 0

    if recompute:
        from atlas.understanding.aggregate.signals import compute_signals
        from atlas.understanding.interpret.roles import compute_roles
        from atlas.understanding.interpret.consensus import compute_consensus
        from atlas.understanding.interpret.zones import compute_zones
        from atlas.understanding.interpret.headings import compute_headings
        from atlas.understanding.interpret.section_tree import compute_section_tree
        from atlas.understanding.interpret.document_type import compute_document_type

        for row in docs:
            conn = _open(root)
            try:
                did = row["document_id"]
                compute_signals(conn, did)
                compute_roles(conn, did)
                compute_consensus(conn, did)
                compute_zones(conn, did)
                compute_headings(conn, did)
                compute_section_tree(conn, did)
                compute_document_type(conn, did)
                # Pass 2: rollen mit Typ-Anpassungen
                compute_signals(conn, did)
                compute_roles(conn, did)
                compute_consensus(conn, did)
                compute_zones(conn, did)
                compute_headings(conn, did)
                compute_section_tree(conn, did)
                ok += 1
                console.print(f"  [green]✓[/green] {did[:12]}")
            except Exception as exc:
                console.print(f"  [red]✗[/red] {row['document_id'][:12]}: {exc}")
                failed += 1
            finally:
                conn.close()
    else:
        for row in docs:
            conn = _open(root)
            try:
                run_du_pipeline(conn, row["document_id"])
                ok += 1
            except Exception as exc:
                console.print(f"[red]✗[/red] {row['document_id'][:12]}: {exc}")
                failed += 1
            finally:
                conn.close()

    console.print(f"[bold]{ok} OK, {failed} Fehler[/bold]")


@dev_du.command("embed-all")
def dev_du_embed_all(
    workers: int = typer.Option(1, "--workers", "-w"),
) -> None:
    """LanceDB-Embeddings für alle Dokumente (neu) berechnen."""
    root = _catalog_root()
    _require_catalog(root)

    try:
        from atlas.embeddings.store import EmbeddingStore
        from atlas.embeddings.index import reindex_document
    except ImportError:
        console.print("[red]lancedb / sentence-transformers nicht installiert.[/red]")
        console.print("Führe aus: pip install lancedb sentence-transformers")
        raise typer.Exit(1)

    conn  = _open(root)
    store = EmbeddingStore.open(root)
    docs  = conn.execute(
        "SELECT document_id, title, file_name FROM documents "
        "WHERE pipeline_status = 'indexed'"
    ).fetchall()

    if not docs:
        console.print("[dim]Keine indexierten Dokumente.[/dim]")
        conn.close()
        return

    console.print(f"Erstelle Embeddings für {len(docs)} Dokument(e)…")
    ok = failed = 0

    for doc in docs:
        did  = doc["document_id"]
        name = (doc["title"] or doc["file_name"] or did[:12])[:50]
        try:
            with console.status(f"{name}…"):
                n = reindex_document(conn, store, did)
            console.print(f"  [green]✓[/green] {name}  [dim]{n} chunks[/dim]")
            ok += 1
        except Exception as exc:
            console.print(f"  [red]✗[/red] {name}: {exc}")
            failed += 1

    conn.close()
    console.print(f"\n[bold]{ok} OK, {failed} Fehler[/bold]")


@dev_du.command("graph-all")
def dev_du_graph_all() -> None:
    """Wissensgraph-Tripel für alle Dokumente (neu) schreiben."""
    root = _catalog_root()
    _require_catalog(root)

    from atlas.knowledge.store import KnowledgeStore
    from atlas.knowledge.triples import write_document_to_store

    conn  = _open(root)
    store = KnowledgeStore.open(root)
    docs  = conn.execute(
        "SELECT document_id, title, file_name FROM documents "
        "WHERE pipeline_status = 'indexed'"
    ).fetchall()

    if not docs:
        console.print("[dim]Keine indexierten Dokumente.[/dim]")
        conn.close()
        return

    console.print(f"Schreibe Wissensgraph für {len(docs)} Dokument(e)…")
    ok = failed = total_triples = 0

    for doc in docs:
        did  = doc["document_id"]
        name = (doc["title"] or doc["file_name"] or did[:12])[:50]
        try:
            store.remove_document(did)
            n = write_document_to_store(conn, store, did)
            total_triples += n
            console.print(f"  [green]✓[/green] {name}  [dim]{n} Tripel[/dim]")
            ok += 1
        except Exception as exc:
            console.print(f"  [red]✗[/red] {name}: {exc}")
            failed += 1

    conn.close()
    console.print(
        f"\n[bold]{ok} OK, {failed} Fehler, {total_triples} Tripel gesamt[/bold]"
    )


@dev_du.command("eval")
def dev_du_eval(
    gt_dir: str = typer.Argument(
        ..., help="Ordner mit ground_truth_documents.csv und/oder ground_truth_sections.csv"
    ),
    verbose: bool = typer.Option(False, "--verbose", "-v",
                                  help="Zeigt alle Kapitel einzeln"),
    as_json: bool = typer.Option(False, "--json",
                                  help="Maschinenlesbarer JSON-Output"),
) -> None:
    """DU-Qualität gegen Ground-Truth-CSVs evaluieren."""
    from atlas.understanding.eval import (
        load_document_gt, load_section_gt, run_eval,
        format_report, format_report_json,
    )

    root = _catalog_root()
    _require_catalog(root)

    gt_path = Path(gt_dir).resolve()
    if not gt_path.is_dir():
        console.print(f"[red]Kein Ordner:[/red] {gt_path}")
        raise typer.Exit(1)

    doc_csv     = gt_path / "ground_truth_documents.csv"
    section_csv = gt_path / "ground_truth_sections.csv"

    if not doc_csv.exists() and not section_csv.exists():
        console.print(
            f"[red]Keine Ground-Truth-Dateien gefunden.[/red]\n"
            f"Erwartet: ground_truth_documents.csv und/oder ground_truth_sections.csv\n"
            f"In: {gt_path}"
        )
        raise typer.Exit(1)

    doc_gt     = load_document_gt(doc_csv)     if doc_csv.exists()     else {}
    section_gt = load_section_gt(section_csv)  if section_csv.exists() else {}

    conn = _open(root)
    report = run_eval(conn, doc_gt, section_gt)
    conn.close()

    if not report.results:
        console.print("[yellow]Keine übereinstimmenden Dokumente gefunden.[/yellow] "
                      "Sind die document_ids in den CSVs korrekt?")
        raise typer.Exit(1)

    if as_json:
        typer.echo(format_report_json(report))
    else:
        console.print(format_report(report, verbose=verbose))


# ── Entry point ───────────────────────────────────────────────────────────────

if __name__ == "__main__":
    app()
