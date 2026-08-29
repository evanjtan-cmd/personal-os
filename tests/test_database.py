from pathlib import Path
import sqlite3

import pytest

from personal_os import database
from personal_os.database import (
    CURRENT_SCHEMA_VERSION,
    TABLE_DDL,
    V2_TABLE_DDL,
    DatabaseInitializationError,
    initialize_database,
    open_database,
)


def read_version(path: Path) -> int:
    with sqlite3.connect(path) as connection:
        row = connection.execute("PRAGMA user_version").fetchone()
    assert row is not None
    return int(row[0])


def user_objects(path: Path) -> list[str]:
    with sqlite3.connect(path) as connection:
        rows = connection.execute(
            "SELECT name FROM sqlite_schema WHERE name NOT LIKE 'sqlite_%' ORDER BY name"
        ).fetchall()
    return [str(row[0]) for row in rows]


def test_fresh_database_migrates_through_version_3(tmp_path: Path) -> None:
    path = tmp_path / "runtime" / "personal_os.db"

    version = initialize_database(path)

    assert version == CURRENT_SCHEMA_VERSION == 3
    assert read_version(path) == 3
    assert user_objects(path) == sorted(TABLE_DDL)


def test_existing_version_1_migrates_to_version_3(tmp_path: Path) -> None:
    path = tmp_path / "version1.db"
    with sqlite3.connect(path) as connection:
        connection.execute("PRAGMA user_version = 1")

    assert initialize_database(path) == 3
    assert user_objects(path) == sorted(TABLE_DDL)


def test_populated_version_2_migrates_to_version_3_without_rebuilding(tmp_path: Path) -> None:
    path = tmp_path / "version2.db"
    with sqlite3.connect(path) as connection:
        for ddl in V2_TABLE_DDL.values():
            connection.execute(ddl)
        stamp = "2026-09-01T12:00:00.000000Z"
        connection.execute(
            "INSERT INTO projects (name, status, created_at, updated_at) VALUES ('College', 'ACTIVE', ?, ?)",
            (stamp, stamp),
        )
        connection.execute("PRAGMA user_version = 2")

    assert initialize_database(path) == 3
    with sqlite3.connect(path) as connection:
        assert connection.execute("SELECT name, source_capture_id FROM projects").fetchone() == ("College", None)
        assert connection.execute("PRAGMA user_version").fetchone()[0] == 3


def test_repeated_version_3_initialization_is_idempotent(tmp_path: Path) -> None:
    path = tmp_path / "personal_os.db"
    initialize_database(path)
    first_bytes = path.read_bytes()

    assert initialize_database(path) == 3
    assert path.read_bytes() == first_bytes


def test_newer_schema_version_fails_without_mutation(tmp_path: Path) -> None:
    path = tmp_path / "future.db"
    with sqlite3.connect(path) as connection:
        connection.execute("PRAGMA user_version = 4")
    original = path.read_bytes()

    with pytest.raises(DatabaseInitializationError, match="newer than supported"):
        initialize_database(path)

    assert path.read_bytes() == original


def test_unversioned_nonempty_database_is_rejected(tmp_path: Path) -> None:
    path = tmp_path / "unversioned.db"
    with sqlite3.connect(path) as connection:
        connection.execute("CREATE TABLE existing_data (value TEXT)")

    with pytest.raises(DatabaseInitializationError, match="version 0"):
        initialize_database(path)

    assert read_version(path) == 0
    assert user_objects(path) == ["existing_data"]


def test_malformed_version_2_schema_is_rejected(tmp_path: Path) -> None:
    path = tmp_path / "malformed.db"
    with sqlite3.connect(path) as connection:
        for name, ddl in TABLE_DDL.items():
            if name != "rules":
                connection.execute(ddl)
        connection.execute("PRAGMA user_version = 2")

    with pytest.raises(DatabaseInitializationError, match="objects differ"):
        initialize_database(path)

    assert read_version(path) == 2


def test_altered_version_2_table_is_rejected(tmp_path: Path) -> None:
    path = tmp_path / "altered.db"
    initialize_database(path)
    with sqlite3.connect(path) as connection:
        connection.execute("ALTER TABLE rules ADD COLUMN unexpected TEXT")

    with pytest.raises(DatabaseInitializationError, match="incompatible definition"):
        initialize_database(path)


def test_failed_migration_2_rolls_back_to_version_1(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = tmp_path / "failed.db"
    with sqlite3.connect(path) as connection:
        connection.execute("PRAGMA user_version = 1")

    def failing_migration(connection: sqlite3.Connection) -> None:
        connection.execute("CREATE TABLE partial_change (value TEXT)")
        raise RuntimeError("migration failed")

    monkeypatch.setitem(database.MIGRATIONS, 2, failing_migration)

    with pytest.raises(RuntimeError, match="migration failed"):
        initialize_database(path)

    assert read_version(path) == 1
    assert user_objects(path) == []


def test_database_connections_enable_foreign_keys(tmp_path: Path) -> None:
    path = tmp_path / "personal_os.db"
    initialize_database(path)

    connection = open_database(path, require_existing=True)
    try:
        assert connection.execute("PRAGMA foreign_keys").fetchone()[0] == 1
        foreign_keys = connection.execute("PRAGMA foreign_key_list(tasks)").fetchall()
        assert {(row["table"], row["from"], row["on_delete"]) for row in foreign_keys} == {
            ("projects", "project_id", "RESTRICT"),
            ("captures", "source_capture_id", "RESTRICT"),
        }
    finally:
        connection.close()
