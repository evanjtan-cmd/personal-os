"""SQLite connection, deterministic migrations, and schema validation."""

from __future__ import annotations

import sqlite3
from collections.abc import Callable
from pathlib import Path

from personal_os.errors import PersonalOSError

CURRENT_SCHEMA_VERSION = 4


class DatabaseInitializationError(PersonalOSError):
    """Raised when a database cannot be initialized safely."""


def _utc_check(column: str) -> str:
    return (
        f"CHECK(length({column}) = 27 AND substr({column}, 11, 1) = 'T' "
        f"AND substr({column}, -1) = 'Z')"
    )


def _date_check(column: str) -> str:
    return f"CHECK(length({column}) = 10)"


V2_TABLE_DDL: dict[str, str] = {
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

def _ddl_after_add_source_column(name: str, ddl: str) -> str:
    column = "            source_capture_id INTEGER REFERENCES captures(id) ON DELETE RESTRICT"
    if name == "tasks":
        marker = "            CHECK(\n                (schedule_mode"
        return ddl.replace(marker, f"{column},\n{marker}", 1)
    if name == "fixed_commitments":
        marker = "            CHECK(end_at IS NULL"
        return ddl.replace(marker, f"{column},\n{marker}", 1)
    return ddl.replace("        )\n    ", f"            , {column.strip()}\n        )\n    ", 1)


V3_TABLE_DDL: dict[str, str] = {
    **{
        name: _ddl_after_add_source_column(name, ddl)
        if name in {"projects", "tasks", "fixed_commitments", "inbox_items"}
        else ddl
        for name, ddl in V2_TABLE_DDL.items()
    },
    "captures": f"""
        CREATE TABLE captures (
            id INTEGER PRIMARY KEY,
            raw_text TEXT NOT NULL CHECK(length(trim(raw_text)) > 0),
            status TEXT NOT NULL CHECK(status IN ('RECEIVED', 'APPLIED', 'UNRESOLVED', 'FAILED')),
            reference_time TEXT NOT NULL {_utc_check('reference_time')},
            timezone_name TEXT NOT NULL CHECK(length(trim(timezone_name)) > 0),
            interpretation_json TEXT,
            interpretation_version INTEGER,
            model_provider TEXT,
            model_name TEXT,
            model_response_id TEXT,
            unresolved_reason TEXT,
            failure_kind TEXT CHECK(failure_kind IN ('CONFIGURATION_ERROR', 'PROVIDER_ERROR', 'REFUSAL', 'INVALID_OUTPUT')),
            failure_reason TEXT,
            created_at TEXT NOT NULL {_utc_check('created_at')},
            updated_at TEXT NOT NULL {_utc_check('updated_at')},
            CHECK((interpretation_json IS NULL AND interpretation_version IS NULL)
                OR (interpretation_json IS NOT NULL AND interpretation_version = 1)),
            CHECK((status = 'RECEIVED' AND unresolved_reason IS NULL AND failure_kind IS NULL AND failure_reason IS NULL)
                OR (status = 'APPLIED' AND unresolved_reason IS NULL AND failure_kind IS NULL AND failure_reason IS NULL)
                OR (status = 'UNRESOLVED' AND unresolved_reason IS NOT NULL AND failure_kind IS NULL AND failure_reason IS NULL)
                OR (status = 'FAILED' AND unresolved_reason IS NULL AND failure_kind IS NOT NULL AND failure_reason IS NOT NULL))
        )
    """,
}

SESSIONS_DDL = f"""
    CREATE TABLE sessions (
        id INTEGER PRIMARY KEY,
        task_id INTEGER NOT NULL REFERENCES tasks(id) ON DELETE RESTRICT,
        planned_minutes INTEGER NOT NULL
            CHECK(typeof(planned_minutes) = 'integer' AND planned_minutes > 0),
        started_at TEXT NOT NULL {_utc_check('started_at')},
        ended_at TEXT {_utc_check('ended_at')},
        outcome TEXT CHECK(outcome IN ('FINISHED', 'PROGRESS', 'BLOCKED')),
        start_reason TEXT
            CHECK(start_reason IS NULL OR length(trim(start_reason)) > 0),
        result_note TEXT
            CHECK(result_note IS NULL OR length(trim(result_note)) > 0),
        active_slot INTEGER UNIQUE
            CHECK(active_slot IS NULL OR
                (typeof(active_slot) = 'integer' AND active_slot = 1)),
        CHECK(
            (active_slot IS NOT NULL AND ended_at IS NULL AND outcome IS NULL
                AND result_note IS NULL)
            OR
            (active_slot IS NULL AND ended_at IS NOT NULL
                AND outcome IS NOT NULL
                AND outcome IN ('FINISHED', 'PROGRESS', 'BLOCKED'))
        ),
        CHECK(ended_at IS NULL OR ended_at >= started_at)
    )
"""

TABLE_DDL: dict[str, str] = {**V3_TABLE_DDL, "sessions": SESSIONS_DDL}

Migration = Callable[[sqlite3.Connection], None]


def _migration_1(connection: sqlite3.Connection) -> None:
    """Establish the infrastructure-only version 1 schema."""

    # Version 1 intentionally has no domain or ownership tables.


def _migration_2(connection: sqlite3.Connection) -> None:
    """Create the first canonical structured-state schema."""

    for ddl in V2_TABLE_DDL.values():
        connection.execute(ddl)


def _migration_3(connection: sqlite3.Connection) -> None:
    """Add durable natural-language captures and source traceability."""

    connection.execute(V3_TABLE_DDL["captures"])
    for table in ("projects", "tasks", "fixed_commitments", "inbox_items"):
        connection.execute(
            f"ALTER TABLE {table} ADD COLUMN source_capture_id INTEGER "
            "REFERENCES captures(id) ON DELETE RESTRICT"
        )


def _migration_4(connection: sqlite3.Connection) -> None:
    """Add durable work-session history."""

    connection.execute(SESSIONS_DDL)


MIGRATIONS: dict[int, Migration] = {
    1: _migration_1,
    2: _migration_2,
    3: _migration_3,
    4: _migration_4,
}


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
    normalized = " ".join(sql.split()).rstrip(";")
    while " )" in normalized:
        normalized = normalized.replace(" )", ")")
    return normalized


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
    if version not in (2, 3, 4):
        raise DatabaseInitializationError(f"unsupported schema version {version}")
    expected_tables = {
        2: V2_TABLE_DDL,
        3: V3_TABLE_DDL,
        4: TABLE_DDL,
    }[version]
    if set(objects) != set(expected_tables):
        expected = ", ".join(sorted(expected_tables))
        actual = ", ".join(sorted(objects)) or "none"
        raise DatabaseInitializationError(
            f"schema version {version} objects differ; expected {expected}; found {actual}"
        )
    for table, expected_ddl in expected_tables.items():
        object_type, actual_ddl = objects[table]
        if object_type != "table" or _normalize_ddl(actual_ddl) != _normalize_ddl(expected_ddl):
            raise DatabaseInitializationError(
                f"schema version {version} table {table} has an incompatible definition"
            )
    expected_fks = {
        "projects": [] if version == 2 else [("captures", "source_capture_id", "id", "NO ACTION", "RESTRICT")],
        "tasks": [("projects", "project_id", "id", "NO ACTION", "RESTRICT")]
        + ([] if version == 2 else [("captures", "source_capture_id", "id", "NO ACTION", "RESTRICT")]),
        "fixed_commitments": [] if version == 2 else [("captures", "source_capture_id", "id", "NO ACTION", "RESTRICT")],
        "inbox_items": [] if version == 2 else [("captures", "source_capture_id", "id", "NO ACTION", "RESTRICT")],
    }
    if version == 4:
        expected_fks["sessions"] = [
            ("tasks", "task_id", "id", "NO ACTION", "RESTRICT")
        ]
    for table, expected in expected_fks.items():
        actual = sorted(
            (row["table"], row["from"], row["to"], row["on_update"], row["on_delete"])
            for row in connection.execute(f"PRAGMA foreign_key_list({table})")
        )
        if actual != sorted(expected):
            raise DatabaseInitializationError(f"{table} has incompatible foreign-key metadata")
    if version == 4:
        unique_active_slot = False
        for index in connection.execute("PRAGMA index_list(sessions)"):
            if int(index["unique"]) != 1:
                continue
            columns = [
                row["name"]
                for row in connection.execute(
                    f"PRAGMA index_info({index['name']})"
                )
            ]
            if columns == ["active_slot"]:
                unique_active_slot = True
                break
        if not unique_active_slot:
            raise DatabaseInitializationError(
                "sessions lacks a unique active_slot constraint"
            )


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
