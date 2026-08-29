"""Runtime path configuration with no import-time side effects."""

from __future__ import annotations

import os
from collections.abc import Mapping
from pathlib import Path

from personal_os.errors import PersonalOSError

DATA_DIR_ENV_VAR = "PERSONAL_OS_DATA_DIR"
DEFAULT_DATA_DIR = Path("~/.personal-os")
DEFAULT_DATABASE_FILENAME = "personal_os.db"


class ConfigurationError(PersonalOSError):
    """Raised when runtime configuration is invalid."""


def get_data_dir(environ: Mapping[str, str] | None = None) -> Path:
    """Return the normalized runtime data directory without creating it."""

    environment = os.environ if environ is None else environ
    configured = environment.get(DATA_DIR_ENV_VAR)
    if configured is not None and not configured.strip():
        raise ConfigurationError(f"{DATA_DIR_ENV_VAR} must not be empty")

    raw_path = Path(configured) if configured is not None else DEFAULT_DATA_DIR
    return raw_path.expanduser().resolve(strict=False)


def get_database_path(
    environ: Mapping[str, str] | None = None,
) -> Path:
    """Return the configured SQLite database path without creating it."""

    return get_data_dir(environ) / DEFAULT_DATABASE_FILENAME
