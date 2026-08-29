from pathlib import Path
import sqlite3

import pytest

from personal_os import database
from personal_os.database import (
    CURRENT_SCHEMA_VERSION,
    DatabaseInitializationError,
    initialize_database,
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


def test_clean_database_initialization(tmp_path: Path) -> None:
    path = tmp_path / "runtime" / "personal_os.db"

    version = initialize_database(path)

    assert path.exists()
    assert version == CURRENT_SCHEMA_VERSION
    assert read_version(path) == CURRENT_SCHEMA_VERSION
    assert user_objects(path) == []


def test_repeated_initialization_is_idempotent(tmp_path: Path) -> None:
    path = tmp_path / "personal_os.db"

    first_version = initialize_database(path)
    first_bytes = path.read_bytes()
    second_version = initialize_database(path)

    assert first_version == second_version == CURRENT_SCHEMA_VERSION
    assert path.read_bytes() == first_bytes


def test_newer_schema_version_fails_without_mutation(tmp_path: Path) -> None:
    path = tmp_path / "future.db"
    with sqlite3.connect(path) as connection:
        connection.execute(f"PRAGMA user_version = {CURRENT_SCHEMA_VERSION + 1}")
    original = path.read_bytes()

    with pytest.raises(DatabaseInitializationError, match="newer than supported"):
        initialize_database(path)

    assert path.read_bytes() == original
    assert read_version(path) == CURRENT_SCHEMA_VERSION + 1


def test_unversioned_nonempty_database_is_rejected(tmp_path: Path) -> None:
    path = tmp_path / "unversioned.db"
    with sqlite3.connect(path) as connection:
        connection.execute("CREATE TABLE existing_data (value TEXT)")
    original_objects = user_objects(path)

    with pytest.raises(DatabaseInitializationError, match="unversioned database"):
        initialize_database(path)

    assert read_version(path) == 0
    assert user_objects(path) == original_objects


def test_current_version_with_unexpected_objects_is_rejected(tmp_path: Path) -> None:
    path = tmp_path / "incompatible.db"
    with sqlite3.connect(path) as connection:
        connection.execute("CREATE TABLE unexpected (value TEXT)")
        connection.execute(f"PRAGMA user_version = {CURRENT_SCHEMA_VERSION}")

    with pytest.raises(DatabaseInitializationError, match="unexpected objects"):
        initialize_database(path)

    assert read_version(path) == CURRENT_SCHEMA_VERSION
    assert user_objects(path) == ["unexpected"]


def test_failed_migration_rolls_back(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    path = tmp_path / "failed.db"

    def failing_migration(connection: sqlite3.Connection) -> None:
        connection.execute("CREATE TABLE partial_change (value TEXT)")
        raise RuntimeError("migration failed")

    monkeypatch.setitem(database.MIGRATIONS, 1, failing_migration)

    with pytest.raises(RuntimeError, match="migration failed"):
        initialize_database(path)

    assert read_version(path) == 0
    assert user_objects(path) == []
