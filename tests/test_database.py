from pathlib import Path
import sqlite3

import pytest

from personal_os import database
from personal_os.database import (
    CURRENT_SCHEMA_VERSION,
    TABLE_DDL,
    V2_TABLE_DDL,
    V3_TABLE_DDL,
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


def create_populated_v2(path: Path) -> None:
    stamp = "2026-09-01T12:00:00.000000Z"
    with sqlite3.connect(path) as connection:
        for ddl in V2_TABLE_DDL.values():
            connection.execute(ddl)
        connection.execute("INSERT INTO projects (id, name, description, status, created_at, updated_at) VALUES (11, 'College', 'Applications', 'ACTIVE', ?, ?)", (stamp, stamp))
        connection.execute("INSERT INTO tasks (id, title, project_id, status, importance, schedule_mode, day_date, deadline_date, estimated_minutes, created_at, updated_at) VALUES (21, 'Draft essay', 11, 'OPEN', 'MUST', 'DAY', '2026-09-05', '2026-09-10', 45, ?, ?)", (stamp, stamp))
        connection.execute("INSERT INTO fixed_commitments (id, title, start_at, end_at, hardness, created_at, updated_at) VALUES (31, 'Appointment', '2026-09-02T14:00:00.000000Z', NULL, 'HARD', ?, ?)", (stamp, stamp))
        connection.execute("INSERT INTO rules (id, kind, parameters_json, enabled, created_at, updated_at) VALUES (41, 'hours', '{\"start\":9}', 1, ?, ?)", (stamp, stamp))
        connection.execute("INSERT INTO inbox_items (id, raw_text, unresolved_reason, resolved_at, created_at, updated_at) VALUES (51, 'Maybe Tuesday', 'ambiguous', NULL, ?, ?)", (stamp, stamp))
        connection.execute("PRAGMA user_version = 2")


def read_v2_data(path: Path) -> dict[str, dict[str, object]]:
    result = {}
    with sqlite3.connect(path) as connection:
        connection.row_factory = sqlite3.Row
        for table in V2_TABLE_DDL:
            row = connection.execute(f"SELECT * FROM {table}").fetchone()
            assert row is not None
            result[table] = dict(row)
    return result


def test_fresh_database_migrates_through_version_4(tmp_path: Path) -> None:
    path = tmp_path / "runtime" / "personal_os.db"

    version = initialize_database(path)

    assert version == CURRENT_SCHEMA_VERSION == 4
    assert read_version(path) == 4
    assert user_objects(path) == sorted(TABLE_DDL)


def test_existing_version_1_migrates_to_version_4(tmp_path: Path) -> None:
    path = tmp_path / "version1.db"
    with sqlite3.connect(path) as connection:
        connection.execute("PRAGMA user_version = 1")

    assert initialize_database(path) == 4
    assert user_objects(path) == sorted(TABLE_DDL)


def test_populated_version_2_migrates_to_version_4_without_rebuilding(tmp_path: Path) -> None:
    path = tmp_path / "version2.db"
    create_populated_v2(path)
    original = read_v2_data(path)

    assert initialize_database(path) == 4
    with sqlite3.connect(path) as connection:
        for table, expected in original.items():
            columns = ", ".join(expected)
            row = connection.execute(f"SELECT {columns} FROM {table}").fetchone()
            assert row is not None
            assert dict(zip(expected, row, strict=True)) == expected
        assert connection.execute("SELECT id,name,description,status,source_capture_id FROM projects").fetchone() == (11, "College", "Applications", "ACTIVE", None)
        assert connection.execute("SELECT id,title,project_id,status,importance,schedule_mode,day_date,deadline_date,estimated_minutes,source_capture_id FROM tasks").fetchone() == (21, "Draft essay", 11, "OPEN", "MUST", "DAY", "2026-09-05", "2026-09-10", 45, None)
        assert connection.execute("SELECT id,title,start_at,end_at,hardness,source_capture_id FROM fixed_commitments").fetchone() == (31, "Appointment", "2026-09-02T14:00:00.000000Z", None, "HARD", None)
        assert connection.execute("SELECT id,kind,parameters_json,enabled FROM rules").fetchone() == (41, "hours", '{\"start\":9}', 1)
        assert connection.execute("SELECT id,raw_text,unresolved_reason,resolved_at,source_capture_id FROM inbox_items").fetchone() == (51, "Maybe Tuesday", "ambiguous", None, None)
        assert connection.execute("PRAGMA user_version").fetchone()[0] == 4
        task_fks = {(row[2], row[3], row[4], row[6]) for row in connection.execute("PRAGMA foreign_key_list(tasks)")}
        assert task_fks == {("projects", "project_id", "id", "RESTRICT"), ("captures", "source_capture_id", "id", "RESTRICT")}


def test_failed_migration_3_rolls_back_schema_and_preserves_all_v2_data(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    path = tmp_path / "failed-v3.db"
    create_populated_v2(path)
    original = read_v2_data(path)

    def failing_migration(connection: sqlite3.Connection) -> None:
        connection.execute("CREATE TABLE partial_v3 (value TEXT)")
        connection.execute("ALTER TABLE projects ADD COLUMN partial_column TEXT")
        raise RuntimeError("migration 3 failed")

    monkeypatch.setitem(database.MIGRATIONS, 3, failing_migration)
    with pytest.raises(RuntimeError, match="migration 3 failed"):
        initialize_database(path)

    assert read_version(path) == 2
    assert user_objects(path) == sorted(V2_TABLE_DDL)
    assert read_v2_data(path) == original
    with sqlite3.connect(path) as connection:
        assert [row[1] for row in connection.execute("PRAGMA table_info(projects)")] == ["id", "name", "description", "status", "created_at", "updated_at"]
        assert connection.execute("SELECT id,name,description,status FROM projects").fetchone() == (11, "College", "Applications", "ACTIVE")
        assert connection.execute("SELECT id,title,project_id FROM tasks").fetchone() == (21, "Draft essay", 11)
        assert connection.execute("SELECT id,title FROM fixed_commitments").fetchone() == (31, "Appointment")
        assert connection.execute("SELECT id,kind FROM rules").fetchone() == (41, "hours")
        assert connection.execute("SELECT id,raw_text FROM inbox_items").fetchone() == (51, "Maybe Tuesday")


def test_repeated_version_4_initialization_is_idempotent(tmp_path: Path) -> None:
    path = tmp_path / "personal_os.db"
    initialize_database(path)
    first_bytes = path.read_bytes()

    assert initialize_database(path) == 4
    assert path.read_bytes() == first_bytes


def test_newer_schema_version_fails_without_mutation(tmp_path: Path) -> None:
    path = tmp_path / "future.db"
    with sqlite3.connect(path) as connection:
        connection.execute("PRAGMA user_version = 5")
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


def test_altered_version_4_table_is_rejected(tmp_path: Path) -> None:
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


def create_populated_v3(path: Path) -> dict[str, tuple]:
    stamp = "2026-09-01T12:00:00.000000Z"
    with sqlite3.connect(path) as connection:
        for ddl in V3_TABLE_DDL.values():
            connection.execute(ddl)
        connection.execute(
            "INSERT INTO captures (id,raw_text,status,reference_time,timezone_name,interpretation_json,interpretation_version,created_at,updated_at) VALUES (1,'Captured','APPLIED',?,'UTC','{}',1,?,?)",
            (stamp, stamp, stamp),
        )
        connection.execute("INSERT INTO projects VALUES (2,'Project',NULL,'ACTIVE',?,?,1)", (stamp, stamp))
        connection.execute("INSERT INTO tasks VALUES (3,'Task',2,'OPEN','MUST','FLEXIBLE',NULL,NULL,NULL,NULL,NULL,25,?,?,1)", (stamp, stamp))
        connection.execute("INSERT INTO fixed_commitments VALUES (4,'Meeting',?,NULL,'UNKNOWN',?,?,1)", (stamp, stamp, stamp))
        connection.execute("INSERT INTO rules VALUES (5,'rule','{}',1,?,?)", (stamp, stamp))
        connection.execute("INSERT INTO inbox_items VALUES (6,'Text','Reason',NULL,?,?,1)", (stamp, stamp))
        connection.execute("PRAGMA user_version = 3")
        before = {
            table: tuple(connection.execute(f"SELECT * FROM {table}"))
            for table in V3_TABLE_DDL
        }
    return before


def test_populated_version_3_migrates_to_4_without_changing_existing_rows(tmp_path: Path) -> None:
    path = tmp_path / "version3.db"
    before = create_populated_v3(path)
    assert initialize_database(path) == 4
    with sqlite3.connect(path) as connection:
        assert {
            table: tuple(connection.execute(f"SELECT * FROM {table}"))
            for table in V3_TABLE_DDL
        } == before
        assert connection.execute("SELECT * FROM sessions").fetchall() == []
        fk = connection.execute("PRAGMA foreign_key_list(sessions)").fetchone()
        assert (fk[2], fk[3], fk[4], fk[6]) == ("tasks", "task_id", "id", "RESTRICT")
        indexes = connection.execute("PRAGMA index_list(sessions)").fetchall()
        assert any(
            row[2] == 1 and [item[2] for item in connection.execute(f"PRAGMA index_info({row[1]})")] == ["active_slot"]
            for row in indexes
        )


def test_failed_migration_4_rolls_back_to_intact_version_3(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    path = tmp_path / "failed-v4.db"
    before = create_populated_v3(path)

    def fail(connection: sqlite3.Connection) -> None:
        connection.execute("CREATE TABLE partial_sessions (id INTEGER)")
        raise RuntimeError("migration 4 failed")

    monkeypatch.setitem(database.MIGRATIONS, 4, fail)
    with pytest.raises(RuntimeError, match="migration 4 failed"):
        initialize_database(path)
    assert read_version(path) == 3
    assert user_objects(path) == sorted(V3_TABLE_DDL)
    with sqlite3.connect(path) as connection:
        assert {table: tuple(connection.execute(f"SELECT * FROM {table}")) for table in V3_TABLE_DDL} == before
