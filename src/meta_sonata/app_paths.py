from __future__ import annotations

import os
from pathlib import Path

from platformdirs import user_cache_path, user_data_path


APP_IDENTIFIER = "com.sendinge.meta-sonata"
DATA_DIR_ENV = "META_SONATA_DATA_DIR"
CACHE_DIR_ENV = "META_SONATA_CACHE_DIR"


def default_data_dir() -> Path:
    configured = os.environ.get(DATA_DIR_ENV)
    if configured:
        return Path(configured).expanduser()
    return user_data_path(APP_IDENTIFIER, appauthor=False)


def default_cache_dir() -> Path:
    configured = os.environ.get(CACHE_DIR_ENV)
    if configured:
        return Path(configured).expanduser()
    return user_cache_path(APP_IDENTIFIER, appauthor=False)


def default_catalog_path() -> Path:
    return default_data_dir() / "catalog.sqlite3"


def default_api_cache_path() -> Path:
    return default_cache_dir() / "provider-cache.sqlite3"
