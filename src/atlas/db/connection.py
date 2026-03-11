from __future__ import annotations

import psycopg

from atlas.settings import load_settings


def get_connection():
    settings = load_settings()

    try:
        url = settings["database"]["url"]
    except KeyError as exc:
        raise KeyError(
            "Missing config key: database.url"
        ) from exc

    if not url:
        raise ValueError("database.url is empty in Atlas config")

    return psycopg.connect(url)
