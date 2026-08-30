"""Runtime path configuration with no import-time side effects."""

from __future__ import annotations

import os
from collections.abc import Mapping
from pathlib import Path
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from personal_os.errors import PersonalOSError

DATA_DIR_ENV_VAR = "PERSONAL_OS_DATA_DIR"
TIMEZONE_ENV_VAR = "PERSONAL_OS_TIMEZONE"
DEFAULT_DATA_DIR = Path("~/.personal-os")
DEFAULT_DATABASE_FILENAME = "personal_os.db"


class ConfigurationError(PersonalOSError):
    """Raised when runtime configuration is invalid."""


def get_timezone_name(
    explicit: str | None = None,
    environ: Mapping[str, str] | None = None,
) -> str:
    """Return an explicitly configured, validated IANA timezone key."""

    environment = os.environ if environ is None else environ
    supplied = explicit if explicit is not None else environment.get(TIMEZONE_ENV_VAR)
    if supplied is None or not supplied.strip():
        raise ConfigurationError(
            f"timezone must be supplied with --timezone or {TIMEZONE_ENV_VAR}"
        )
    try:
        ZoneInfo(supplied)
    except (ZoneInfoNotFoundError, ValueError, KeyError) as exc:
        raise ConfigurationError(f"invalid IANA timezone: {supplied}") from exc
    return supplied


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
