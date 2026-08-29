"""SQLite connection, deterministic migrations, and schema validation."""

from __future__ import annotations

import sqlite3
from collections.abc import Callable
from pathlib import Path

from personal_os.errors import PersonalOSError

CURRENT_SCHEMA_VERSION = 2


class DatabaseInitializationError(PersonalOSError):
    """Raised when a database cannot be initialized safely."""


def _utc_check(column: str) -> str:
    return (
        f"CHECK(length({column}) = 27 AND substr({column}, 11, 1) = 'T' "
        f"AND substr({column}, -1) = 'Z')"
    )


def _date_check(column: str) -> str:
    return f"CHECK(length({column}) = 10)"


TABLE_DDL: dict[str, str] = {
    "projects": f"""
        CREATE TABLE projects (
            id INTEGER PRIMARY KEY,
            name TEXT NOT NULL CHECK(length(trim(name)) > 0),
            description TEXT,
            status TEXT NOT NULL DEFAULT 'ACTIVE'
                CHECK(status IN ('ACTIVE', 'COMPLETED')),
            created_at TEXT NOT NULL {_utc_check('created_at')},
            updated_at TEXT NOT NULL {_utc_check('updated_at')}
        )
    """,
    "tasks": f"""
        CREATE TABLE tasks (
            id INTEGER PRIMARY KEY,
            title TEXT NOT NULL CHECK(length(trim(title)) > 0),
            project_id INTEGER REFERENCES projects(id) ON DELETE RESTRICT,
            status TEXT NOT NULL DEFAULT 'OPEN'
                CHECK(status IN ('OPEN', 'BLOCKED', 'COMPLETED')),
            importance TEXT NOT NULL DEFAULT 'UNSPECIFIED'
                CHECK(importance IN ('UNSPECIFIED', 'MUST', 'SHOULD', 'COULD')),
            schedule_mode TEXT NOT NULL DEFAULT 'FLEXIBLE'
                CHECK(schedule_mode IN ('FLEXIBLE', 'DAY', 'WINDOW')),
            day_date TEXT {_date_check('day_date')},
            window_start TEXT {_utc_check('window_start')},
            window_end TEXT {_utc_check('window_end')},
            deadline_date TEXT {_date_check('deadline_date')},
            deadline_at TEXT {_utc_check('deadline_at')},
            estimated_minutes INTEGER CHECK(estimated_minutes > 0),
            created_at TEXT NOT NULL {_utc_check('created_at')},
            updated_at TEXT NOT NULL {_utc_check('updated_at')},
            CHECK(
                (schedule_mode = 'FLEXIBLE' AND day_date IS NULL
                    AND window_start IS NULL AND window_end IS NULL)
                OR (schedule_mode = 'DAY' AND day_date IS NOT NULL
                    AND window_start IS NULL AND window_end IS NULL)
                OR (schedule_mode = 'WINDOW' AND day_date IS NULL
                    AND window_start IS NOT NULL AND window_end IS NOT NULL
                    AND window_start < window_end)
            ),
            CHECK(NOT (deadline_date IS NOT NULL AND deadline_at IS NOT NULL))
        )
    """,
    "fixed_commitments": f"""
        CREATE TABLE fixed_commitments (
            id INTEGER PRIMARY KEY,
            title TEXT NOT NULL CHECK(length(trim(title)) > 0),
            start_at TEXT NOT NULL {_utc_check('start_at')},
            end_at TEXT {_utc_check('end_at')},
            hardness TEXT NOT NULL DEFAULT 'UNKNOWN'
                CHECK(hardness IN ('UNKNOWN', 'HARD', 'SOFT')),
            created_at TEXT NOT NULL {_utc_check('created_at')},
            updated_at TEXT NOT NULL {_utc_check('updated_at')},
            CHECK(end_at IS NULL OR start_at < end_at)
        )
    """,
    "rules": f"""
        CREATE TABLE rules (
            id INTEGER PRIMARY KEY,
            kind TEXT NOT NULL CHECK(length(trim(kind)) > 0),
            parameters_json TEXT NOT NULL DEFAULT '{{}}',
            enabled INTEGER NOT NULL DEFAULT 1 CHECK(enabled IN (0, 1)),
            created_at TEXT NOT NULL {_utc_check('created_at')},
            updated_at TEXT NOT NULL {_utc_check('updated_at')}
        )
    """,
    "inbox_items": f"""
        CREATE TABLE inbox_items (
            id INTEGER PRIMARY KEY,
            raw_text TEXT NOT NULL CHECK(length(trim(raw_text)) > 0),
            unresolved_reason TEXT NOT NULL
                CHECK(length(trim(unresolved_reason)) > 0),
            resolved_at TEXT {_utc_check('resolved_at')},
            created_at TEXT NOT NULL {_utc_check('created_at')},
            updated_at TEXT NOT NULL {_utc_check('updated_at')}
        )
    """,
}

Migration = Callable[[sqlite3.Connection], None]


def _migration_1(connection: sqlite3.Connection) -> None:
    """Establish the infrastructure-only version 1 schema."""

    # Version 1 intentionally has no domain or ownership tables.


def _migration_2(connection: sqlite3.Connection) -> None:
    """Create the first canonical structured-state schema."""

    for ddl in TABLE_DDL.values():
        connection.execute(ddl)


MIGRATIONS: dict[int, Migration] = {1: _migration_1, 2: _migration_2}


def open_database(path: Path, *, require_existing: bool = False) -> sqlite3.Connection:
    """Open SQLite with explicit transactions and verified foreign keys."""

    normalized = Path(path).expanduser().resolve(strict=False)
    target: str | Path = normalized
    if require_existing:
        target = f"{normalized.as_uri()}?mode=rw"
    connection = sqlite3.connect(target, isolation_level=None, uri=require_existing)
    try:
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        row = connection.execute("PRAGMA foreign_keys").fetchone()
        if row is None or int(row[0]) != 1:
            raise sqlite3.OperationalError("SQLite foreign-key enforcement is unavailable")
        return connection
    except Exception:
        connection.close()
        raise


def get_schema_version(connection: sqlite3.Connection) -> int:
    row = connection.execute("PRAGMA user_version").fetchone()
    if row is None:
        raise DatabaseInitializationError("database did not report a schema version")
    return int(row[0])


def _user_objects(connection: sqlite3.Connection) -> dict[str, tuple[str, str]]:
    rows = connection.execute(
        """
        SELECT name, type, sql
        FROM sqlite_schema
        WHERE name NOT LIKE 'sqlite_%'
          AND type IN ('table', 'index', 'view', 'trigger')
        ORDER BY name
        """
    ).fetchall()
    return {str(row["name"]): (str(row["type"]), str(row["sql"])) for row in rows}


def _normalize_ddl(sql: str) -> str:
    return " ".join(sql.split()).rstrip(";")


def validate_schema(connection: sqlite3.Connection, version: int) -> None:
    """Validate the exact schema structure declared by a supported version."""

    objects = _user_objects(connection)
    if version in (0, 1):
        if objects:
            names = ", ".join(objects)
            raise DatabaseInitializationError(
                f"schema version {version} contains unexpected objects: {names}"
            )
        return
    if version != 2:
        raise DatabaseInitializationError(f"unsupported schema version {version}")
    if set(objects) != set(TABLE_DDL):
        expected = ", ".join(sorted(TABLE_DDL))
        actual = ", ".join(sorted(objects)) or "none"
        raise DatabaseInitializationError(
            f"schema version 2 objects differ; expected {expected}; found {actual}"
        )
    for table, expected_ddl in TABLE_DDL.items():
        object_type, actual_ddl = objects[table]
        if object_type != "table" or _normalize_ddl(actual_ddl) != _normalize_ddl(expected_ddl):
            raise DatabaseInitializationError(
                f"schema version 2 table {table} has an incompatible definition"
            )
    foreign_keys = connection.execute("PRAGMA foreign_key_list(tasks)").fetchall()
    expected = [("projects", "project_id", "id", "NO ACTION", "RESTRICT")]
    actual = [
        (row["table"], row["from"], row["to"], row["on_update"], row["on_delete"])
        for row in foreign_keys
    ]
    if actual != expected:
        raise DatabaseInitializationError("tasks has incompatible foreign-key metadata")


def initialize_database(database_path: Path) -> int:
    """Initialize or migrate a database and return its resulting schema version."""

    path = Path(database_path).expanduser().resolve(strict=False)
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        connection = open_database(path)
    except sqlite3.Error as exc:
        raise DatabaseInitializationError(f"SQLite connection failed: {exc}") from exc
    try:
        version = get_schema_version(connection)
        if version > CURRENT_SCHEMA_VERSION:
            raise DatabaseInitializationError(
                f"database schema version {version} is newer than supported "
                f"version {CURRENT_SCHEMA_VERSION}"
            )
        validate_schema(connection, version)
        if version == CURRENT_SCHEMA_VERSION:
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
                validate_schema(connection, target_version)
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        return get_schema_version(connection)
    except sqlite3.Error as exc:
        raise DatabaseInitializationError(f"SQLite initialization failed: {exc}") from exc
    finally:
        connection.close()
