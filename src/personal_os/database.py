"""SQLite connection and deterministic schema initialization."""

from __future__ import annotations

import sqlite3
from collections.abc import Callable
from pathlib import Path

from personal_os.errors import PersonalOSError

CURRENT_SCHEMA_VERSION = 1


class DatabaseInitializationError(PersonalOSError):
    """Raised when a database cannot be initialized safely."""


Migration = Callable[[sqlite3.Connection], None]


def _migration_1(connection: sqlite3.Connection) -> None:
    """Establish the infrastructure-only version 1 schema."""

    # Version 1 intentionally has no domain or ownership tables. The version is
    # recorded by PRAGMA user_version in the migration transaction.


MIGRATIONS: dict[int, Migration] = {1: _migration_1}


def _schema_objects(connection: sqlite3.Connection) -> list[str]:
    rows = connection.execute(
        """
        SELECT name
        FROM sqlite_schema
        WHERE name NOT LIKE 'sqlite_%'
          AND type IN ('table', 'index', 'view', 'trigger')
        ORDER BY name
        """
    ).fetchall()
    return [str(row[0]) for row in rows]


def get_schema_version(connection: sqlite3.Connection) -> int:
    """Read the authoritative SQLite schema version."""

    row = connection.execute("PRAGMA user_version").fetchone()
    if row is None:
        raise DatabaseInitializationError("database did not report a schema version")
    return int(row[0])


def initialize_database(database_path: Path) -> int:
    """Initialize or migrate a database and return its resulting schema version."""

    path = Path(database_path).expanduser().resolve(strict=False)
    path.parent.mkdir(parents=True, exist_ok=True)

    try:
        connection = sqlite3.connect(path, isolation_level=None)
    except sqlite3.Error as exc:
        raise DatabaseInitializationError(f"SQLite connection failed: {exc}") from exc

    try:
        version = get_schema_version(connection)

        if version > CURRENT_SCHEMA_VERSION:
            raise DatabaseInitializationError(
                f"database schema version {version} is newer than supported "
                f"version {CURRENT_SCHEMA_VERSION}"
            )

        if version == 0:
            objects = _schema_objects(connection)
            if objects:
                names = ", ".join(objects)
                raise DatabaseInitializationError(
                    "refusing to initialize an unversioned database containing "
                    f"schema objects: {names}"
                )

        if version == CURRENT_SCHEMA_VERSION:
            objects = _schema_objects(connection)
            if objects:
                names = ", ".join(objects)
                raise DatabaseInitializationError(
                    f"schema version {version} contains unexpected objects: {names}"
                )
            return version

        connection.execute("BEGIN IMMEDIATE")
        try:
            for target_version in range(version + 1, CURRENT_SCHEMA_VERSION + 1):
                migration = MIGRATIONS.get(target_version)
                if migration is None:
                    raise DatabaseInitializationError(
                        f"no migration is available for schema version {target_version}"
                    )
                migration(connection)
                connection.execute(f"PRAGMA user_version = {target_version}")
            connection.commit()
        except Exception:
            connection.rollback()
            raise

        return get_schema_version(connection)
    except sqlite3.Error as exc:
        raise DatabaseInitializationError(f"SQLite initialization failed: {exc}") from exc
    finally:
        connection.close()
