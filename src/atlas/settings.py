from __future__ import annotations

import os
from pathlib import Path

import yaml


def get_project_root() -> Path:
    return Path(__file__).resolve().parents[2]


def get_config_dir() -> Path:
    return get_project_root() / "config"


def get_selected_config_name() -> str:
    return os.getenv("ATLAS_CONFIG", "atlas.yaml")


def get_selected_config_path() -> Path:
    return get_config_dir() / get_selected_config_name()


def load_settings() -> dict:
    path = get_selected_config_path()

    if not path.exists():
        raise FileNotFoundError(f"Config file not found: {path}")

    with open(path, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f)

    if data is None:
        raise ValueError(f"Config file is empty: {path}")

    if not isinstance(data, dict):
        raise TypeError(f"Config must be a YAML mapping: {path}")

    return data
