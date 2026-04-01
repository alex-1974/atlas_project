# src/atlas/catalog/init.py
from __future__ import annotations

import sys
from datetime import datetime, timezone
from pathlib import Path

import tomllib

from atlas.db.connection import connect
from atlas.db.migrate import run_migrations


# ── Pfade ────────────────────────────────────────────────────────────────────

def _catalog_dir(root: Path) -> Path:
    return root / ".atlas"

def _db_path(root: Path) -> Path:
    return _catalog_dir(root) / "catalog.db"

def _global_atlas_dir() -> Path:
    return Path.home() / ".atlas"

def _global_registry_path() -> Path:
    return _global_atlas_dir() / "registry.toml"

def _global_config_path() -> Path:
    return _global_atlas_dir() / "config.toml"

def _local_config_path(root: Path) -> Path:
    return _catalog_dir(root) / "config.toml"


# ── Hilfsfunktionen ───────────────────────────────────────────────────────────

def _write_local_config(root: Path) -> None:
    """Leere lokale Konfiguration mit Kommentaren anlegen."""
    path = _local_config_path(root)
    if path.exists():
        return
    path.write_text(
        "# Atlas catalog configuration\n"
        "# These settings override ~/.atlas/config.toml for this catalog.\n"
        "#\n"
        "# [catalog]\n"
        "# name = \"\"\n",
        encoding="utf-8",
    )


def _write_global_config() -> None:
    """Globale Konfiguration mit Kommentaren anlegen, falls noch nicht vorhanden."""
    path = _global_config_path()
    if path.exists():
        return
    path.write_text(
        "# Atlas global configuration\n"
        "# Settings here apply to all catalogs unless overridden locally.\n"
        "#\n"
        "# [search]\n"
        "# default_top_k = 10\n",
        encoding="utf-8",
    )


def _register_catalog(root: Path) -> None:
    """Katalog in der globalen Registry eintragen oder aktualisieren."""
    registry_path = _global_registry_path()

    if registry_path.exists():
        registry = tomllib.loads(registry_path.read_text(encoding="utf-8"))
    else:
        registry = {"catalogs": []}

    catalogs: list[dict] = registry.setdefault("catalogs", [])
    abs_root = str(root.resolve())

    # Bereits eingetragen? → updated_at aktualisieren.
    for entry in catalogs:
        if entry.get("path") == abs_root:
            entry["updated_at"] = _now()
            break
    else:
        catalogs.append({
            "path": abs_root,
            "name": root.resolve().name,
            "added_at": _now(),
            "updated_at": _now(),
        })

    registry_path.write_text(_dumps_registry(registry), encoding="utf-8")


def _now() -> str:
    return datetime.now(tz=timezone.utc).isoformat()


def _dumps_registry(registry: dict) -> str:
    """Minimale TOML-Serialisierung für die Registry-Datei."""
    lines = []
    for entry in registry.get("catalogs", []):
        lines.append("[[catalogs]]")
        for k, v in entry.items():
            lines.append(f'{k} = "{v}"')
        lines.append("")
    return "\n".join(lines)


# ── Öffentliche API ───────────────────────────────────────────────────────────

def init_catalog(root: Path) -> None:
    """Initialisiert einen Atlas-Katalog im angegebenen Verzeichnis.

    Legt die .atlas/-Struktur an, schreibt das vollständige SQLite-Schema,
    erstellt Verzeichnisse für LanceDB und Oxigraph und registriert den
    Katalog in der globalen Registry.

    Ist der Katalog bereits initialisiert, wird nur die Registry
    aktualisiert — bestehende Daten bleiben unberührt.
    """
    catalog_dir = _catalog_dir(root)
    already_exists = catalog_dir.exists()

    # 1. Verzeichnisstruktur
    (catalog_dir / "embeddings").mkdir(parents=True, exist_ok=True)
    (catalog_dir / "knowledge").mkdir(parents=True, exist_ok=True)

    # 2. SQLite-Schema
    conn = connect(_db_path(root))
    try:
        run_migrations(conn)
    finally:
        conn.close()

    # 3. Lokale Konfiguration
    _write_local_config(root)

    # 4. Globale Registry + Config
    _global_atlas_dir().mkdir(parents=True, exist_ok=True)
    _write_global_config()
    _register_catalog(root)

    if already_exists:
        print(f"Catalog already exists at {root.resolve()} — schema verified.")
    else:
        print(f"Initialized Atlas catalog at {root.resolve()}")
        _print_tree(root)


def _print_tree(root: Path) -> None:
    lines = [
        f"  {root.name}/",
        f"  └── .atlas/",
        f"      ├── catalog.db",
        f"      ├── embeddings/",
        f"      ├── knowledge/",
        f"      └── config.toml",
    ]
    print("\n".join(lines))
