from pathlib import Path
import sqlite3

import pytest

from personal_os import database
from personal_os.database import (
    CURRENT_SCHEMA_VERSION,
    TABLE_DDL,
    V4_SESSIONS_DDL,
    V4_TABLE_DDL,
    V5_TABLE_DDL,
    V6_TABLE_DDL,
    V7_TABLE_DDL,
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


def test_fresh_database_migrates_through_version_8(tmp_path: Path) -> None:
    path = tmp_path / "runtime" / "personal_os.db"

    version = initialize_database(path)

    assert version == CURRENT_SCHEMA_VERSION == 8
    assert read_version(path) == 8
    assert user_objects(path) == sorted(TABLE_DDL)


def test_existing_version_1_migrates_to_version_8(tmp_path: Path) -> None:
    path = tmp_path / "version1.db"
    with sqlite3.connect(path) as connection:
        connection.execute("PRAGMA user_version = 1")

    assert initialize_database(path) == 8
    assert user_objects(path) == sorted(TABLE_DDL)


def test_populated_version_2_migrates_to_version_8_without_losing_data(tmp_path: Path) -> None:
    path = tmp_path / "version2.db"
    create_populated_v2(path)
    original = read_v2_data(path)

    assert initialize_database(path) == 8
    with sqlite3.connect(path) as connection:
        for table, expected in original.items():
            columns = ", ".join(expected)
            row = connection.execute(f"SELECT {columns} FROM {table}").fetchone()
            assert row is not None
            assert dict(zip(expected, row, strict=True)) == expected
        assert connection.execute("SELECT id,name,description,status,source_capture_id FROM projects").fetchone() == (11, "College", "Applications", "ACTIVE", None)
        assert connection.execute("SELECT id,title,project_id,status,importance,schedule_mode,day_date,deadline_date,estimated_minutes,execution_mode,source_capture_id FROM tasks").fetchone() == (21, "Draft essay", 11, "OPEN", "MUST", "DAY", "2026-09-05", "2026-09-10", 45, "SPLITTABLE", None)
        assert connection.execute("SELECT id,title,start_at,end_at,hardness,status,source_capture_id FROM fixed_commitments").fetchone() == (31, "Appointment", "2026-09-02T14:00:00.000000Z", None, "HARD", "SCHEDULED", None)
        assert connection.execute("SELECT id,kind,parameters_json,enabled FROM rules").fetchone() == (41, "hours", '{\"start\":9}', 1)
        assert connection.execute("SELECT id,raw_text,unresolved_reason,resolved_at,source_capture_id FROM inbox_items").fetchone() == (51, "Maybe Tuesday", "ambiguous", None, None)
        assert connection.execute("PRAGMA user_version").fetchone()[0] == 8
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


def test_repeated_version_8_initialization_is_idempotent(tmp_path: Path) -> None:
    path = tmp_path / "personal_os.db"
    initialize_database(path)
    first_bytes = path.read_bytes()

    assert initialize_database(path) == 8
    assert path.read_bytes() == first_bytes


def test_newer_schema_version_fails_without_mutation(tmp_path: Path) -> None:
    path = tmp_path / "future.db"
    with sqlite3.connect(path) as connection:
        connection.execute("PRAGMA user_version = 9")
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


def test_altered_version_8_table_is_rejected(tmp_path: Path) -> None:
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


def test_populated_version_3_migrates_to_8_without_changing_existing_rows(tmp_path: Path) -> None:
    path = tmp_path / "version3.db"
    before = create_populated_v3(path)
    assert initialize_database(path) == 8
    with sqlite3.connect(path) as connection:
        for table, rows in before.items():
            columns = [row[1] for row in connection.execute(f"PRAGMA table_info({table})")]
            added_columns = {"execution_mode"}
            if table == "fixed_commitments":
                added_columns.add("status")
            original_columns = [
                column for column in columns if column not in added_columns
            ]
            assert tuple(connection.execute(
                f"SELECT {', '.join(original_columns)} FROM {table}"
            )) == rows
        assert connection.execute(
            "SELECT execution_mode FROM tasks WHERE id = 3"
        ).fetchone()[0] == "SPLITTABLE"
        assert connection.execute(
            "SELECT status FROM fixed_commitments WHERE id = 4"
        ).fetchone()[0] == "SCHEDULED"
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


def create_populated_v4(path: Path) -> None:
    stamp = "2026-09-01T12:00:00.000000Z"
    ended = "2026-09-01T12:10:00.000000Z"
    with sqlite3.connect(path) as connection:
        for ddl in V3_TABLE_DDL.values():
            connection.execute(ddl)
        connection.execute(V4_SESSIONS_DDL)
        connection.execute(
            """INSERT INTO tasks
               (id,title,status,importance,schedule_mode,created_at,updated_at)
               VALUES (7,'Task','OPEN','SHOULD','FLEXIBLE',?,?)""",
            (stamp, stamp),
        )
        connection.execute(
            """INSERT INTO sessions
               (id,task_id,planned_minutes,started_at,ended_at,outcome,
                start_reason,result_note,active_slot)
               VALUES (11,7,10,?,?,'PROGRESS','because','progressed',NULL)""",
            (stamp, ended),
        )
        connection.execute(
            """INSERT INTO sessions
               (id,task_id,planned_minutes,started_at,ended_at,outcome,
                start_reason,result_note,active_slot)
               VALUES (12,7,25,?,NULL,NULL,'active reason',NULL,1)""",
            (ended,),
        )
        connection.execute("PRAGMA user_version = 4")


def test_valid_v4_schema_is_validated_and_migrates_losslessly_to_v8(
    tmp_path: Path,
) -> None:
    path = tmp_path / "version4.db"
    create_populated_v4(path)
    with open_database(path, require_existing=True) as connection:
        database.validate_schema(connection, 4)

    assert initialize_database(path) == 8

    with sqlite3.connect(path) as connection:
        connection.row_factory = sqlite3.Row
        sessions = connection.execute(
            "SELECT * FROM sessions ORDER BY id"
        ).fetchall()
        assert [row["id"] for row in sessions] == [11, 12]
        assert [row["selected_action"] for row in sessions] == [None, None]
        assert sessions[0]["ended_at"] == "2026-09-01T12:10:00.000000Z"
        assert sessions[0]["outcome"] == "PROGRESS"
        assert sessions[0]["start_reason"] == "because"
        assert sessions[0]["result_note"] == "progressed"
        assert sessions[1]["active_slot"] == 1
        assert sessions[1]["ended_at"] is None
        assert tuple(connection.execute(
            "SELECT id,title,execution_mode FROM tasks"
        ).fetchone()) == (7, "Task", "SPLITTABLE")
        assert connection.execute("PRAGMA user_version").fetchone()[0] == 8


def test_failed_migration_5_rolls_back_to_intact_version_4(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    path = tmp_path / "failed-v5.db"
    create_populated_v4(path)

    def fail(connection: sqlite3.Connection) -> None:
        connection.execute("ALTER TABLE sessions ADD COLUMN partial TEXT")
        raise RuntimeError("migration 5 failed")

    monkeypatch.setitem(database.MIGRATIONS, 5, fail)
    with pytest.raises(RuntimeError, match="migration 5 failed"):
        initialize_database(path)

    assert read_version(path) == 4
    assert user_objects(path) == sorted(V4_TABLE_DDL)
    with sqlite3.connect(path) as connection:
        assert "selected_action" not in {
            row[1] for row in connection.execute("PRAGMA table_info(sessions)")
        }
        assert [row[0] for row in connection.execute(
            "SELECT id FROM sessions ORDER BY id"
        )] == [11, 12]


def create_populated_v5(path: Path) -> None:
    stamp = "2026-09-01T12:00:00.000000Z"
    ended = "2026-09-01T12:45:00.000000Z"
    with sqlite3.connect(path) as connection:
        for ddl in V5_TABLE_DDL.values():
            connection.execute(ddl)
        connection.execute(
            """INSERT INTO projects
               (id,name,description,status,created_at,updated_at)
               VALUES (2,'Project','Description','ACTIVE',?,?)""",
            (stamp, stamp),
        )
        connection.execute(
            """INSERT INTO tasks
               (id,title,project_id,status,importance,schedule_mode,day_date,
                deadline_date,estimated_minutes,created_at,updated_at)
               VALUES (7,'Draft essay',2,'OPEN','MUST','DAY','2026-09-05',
                       '2026-09-10',45,?,?)""",
            (stamp, stamp),
        )
        connection.execute(
            """INSERT INTO sessions
               (id,task_id,planned_minutes,started_at,ended_at,outcome,
                start_reason,result_note,active_slot,selected_action)
               VALUES (11,7,45,?,?,'PROGRESS','because','progressed',NULL,
                       'Draft the essay section.')""",
            (stamp, ended),
        )
        connection.execute(
            """INSERT INTO sessions
               (id,task_id,planned_minutes,started_at,ended_at,outcome,
                start_reason,result_note,active_slot,selected_action)
               VALUES (12,7,25,?,NULL,NULL,'active reason',NULL,1,
                       'Keep drafting.')""",
            (ended,),
        )
        connection.execute("PRAGMA user_version = 5")


def create_populated_v6(path: Path) -> None:
    stamp = "2026-09-01T12:00:00.000000Z"
    ended = "2026-09-01T12:45:00.000000Z"
    with sqlite3.connect(path) as connection:
        for ddl in V6_TABLE_DDL.values():
            connection.execute(ddl)
        connection.execute(
            """INSERT INTO projects
               (id,name,description,status,created_at,updated_at)
               VALUES (2,'Project','Description','ACTIVE',?,?)""",
            (stamp, stamp),
        )
        connection.execute(
            """INSERT INTO tasks
               (id,title,project_id,status,importance,schedule_mode,day_date,
                deadline_date,estimated_minutes,created_at,updated_at,
                source_capture_id,execution_mode)
               VALUES (7,'Draft essay',2,'OPEN','MUST','DAY','2026-09-05',
                       '2026-09-10',45,?,?,NULL,'ONE_SITTING')""",
            (stamp, stamp),
        )
        connection.execute(
            """INSERT INTO sessions
               (id,task_id,planned_minutes,started_at,ended_at,outcome,
                start_reason,result_note,active_slot,selected_action)
               VALUES (11,7,45,?,?,'PROGRESS','because','progressed',NULL,
                       'Draft the essay section.')""",
            (stamp, ended),
        )
        connection.execute("PRAGMA user_version = 6")


def test_populated_version_6_migrates_to_8_with_cancelled_status_and_history(
    tmp_path: Path,
) -> None:
    path = tmp_path / "version6.db"
    create_populated_v6(path)

    assert initialize_database(path) == 8

    with open_database(path, require_existing=True) as connection:
        database.validate_schema(connection, 8)
        task = connection.execute(
            """SELECT id,title,project_id,status,importance,schedule_mode,
                      day_date,deadline_date,estimated_minutes,execution_mode
               FROM tasks"""
        ).fetchone()
        assert tuple(task) == (
            7, "Draft essay", 2, "OPEN", "MUST", "DAY",
            "2026-09-05", "2026-09-10", 45, "ONE_SITTING",
        )
        session = connection.execute(
            "SELECT id,task_id,selected_action FROM sessions"
        ).fetchone()
        assert tuple(session) == (11, 7, "Draft the essay section.")
        connection.execute("UPDATE tasks SET status='CANCELLED' WHERE id=7")
        assert connection.execute(
            "SELECT status FROM tasks WHERE id=7"
        ).fetchone()[0] == "CANCELLED"
        assert connection.execute("PRAGMA user_version").fetchone()[0] == 8


def test_v7_migration_fk_violation_rolls_back_to_intact_version_6(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    path = tmp_path / "orphaned-v7.db"
    create_populated_v6(path)

    def orphan_session(connection: sqlite3.Connection) -> None:
        connection.execute("ALTER TABLE tasks RENAME TO tasks_v6")
        connection.execute(TABLE_DDL["tasks"])
        connection.execute("DROP TABLE tasks_v6")

    monkeypatch.setitem(database.MIGRATIONS, 7, orphan_session)
    with pytest.raises(DatabaseInitializationError, match="foreign-key violations"):
        initialize_database(path)

    assert read_version(path) == 6
    assert user_objects(path) == sorted(V6_TABLE_DDL)
    with open_database(path, require_existing=True) as connection:
        database.validate_schema(connection, 6)
        assert connection.execute("PRAGMA foreign_keys").fetchone()[0] == 1
        assert connection.execute("PRAGMA foreign_key_check").fetchall() == []
        assert tuple(connection.execute(
            "SELECT id,title,execution_mode FROM tasks"
        ).fetchone()) == (7, "Draft essay", "ONE_SITTING")
        assert tuple(connection.execute(
            "SELECT id,task_id,selected_action FROM sessions"
        ).fetchone()) == (11, 7, "Draft the essay section.")


def test_failed_migration_7_rolls_back_to_intact_version_6(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    path = tmp_path / "failed-v7.db"
    create_populated_v6(path)

    def fail(connection: sqlite3.Connection) -> None:
        connection.execute("ALTER TABLE tasks ADD COLUMN partial_cancel TEXT")
        raise RuntimeError("migration 7 failed")

    monkeypatch.setitem(database.MIGRATIONS, 7, fail)
    with pytest.raises(RuntimeError, match="migration 7 failed"):
        initialize_database(path)

    assert read_version(path) == 6
    assert user_objects(path) == sorted(V6_TABLE_DDL)
    with open_database(path, require_existing=True) as connection:
        database.validate_schema(connection, 6)
        assert connection.execute("PRAGMA foreign_keys").fetchone()[0] == 1
        columns = {row["name"] for row in connection.execute("PRAGMA table_info(tasks)")}
        assert "partial_cancel" not in columns
        assert tuple(connection.execute(
            "SELECT id,title,execution_mode FROM tasks"
        ).fetchone()) == (7, "Draft essay", "ONE_SITTING")


def create_populated_v7(path: Path) -> None:
    stamp = "2026-09-01T12:00:00.000000Z"
    ended = "2026-09-01T12:45:00.000000Z"
    with sqlite3.connect(path) as connection:
        for ddl in V7_TABLE_DDL.values():
            connection.execute(ddl)
        connection.execute(
            "INSERT INTO captures (id,raw_text,status,reference_time,timezone_name,interpretation_json,interpretation_version,created_at,updated_at) VALUES (1,'Captured','APPLIED',?,'UTC','{}',1,?,?)",
            (stamp, stamp, stamp),
        )
        connection.execute(
            """INSERT INTO projects
               (id,name,description,status,created_at,updated_at,source_capture_id)
               VALUES (2,'Project','Description','ACTIVE',?,?,1)""",
            (stamp, stamp),
        )
        connection.execute(
            """INSERT INTO tasks
               (id,title,project_id,status,importance,schedule_mode,day_date,
                deadline_date,estimated_minutes,created_at,updated_at,
                source_capture_id,execution_mode)
               VALUES (7,'Draft essay',2,'OPEN','MUST','DAY','2026-09-05',
                       '2026-09-10',45,?,?,1,'ONE_SITTING')""",
            (stamp, stamp),
        )
        connection.execute(
            """INSERT INTO fixed_commitments
               (id,title,start_at,end_at,hardness,created_at,updated_at,
                source_capture_id)
               VALUES (8,'Appointment','2026-09-02T14:00:00.000000Z',
                       '2026-09-02T15:00:00.000000Z','HARD',?,?,1)""",
            (stamp, stamp),
        )
        connection.execute(
            """INSERT INTO sessions
               (id,task_id,planned_minutes,started_at,ended_at,outcome,
                start_reason,result_note,active_slot,selected_action)
               VALUES (11,7,45,?,?,'PROGRESS','because','progressed',NULL,
                       'Draft the essay section.')""",
            (stamp, ended),
        )
        connection.execute("PRAGMA user_version = 7")


def test_populated_version_7_migrates_to_8_with_scheduled_commitments(
    tmp_path: Path,
) -> None:
    path = tmp_path / "version7.db"
    create_populated_v7(path)

    assert initialize_database(path) == 8

    with open_database(path, require_existing=True) as connection:
        database.validate_schema(connection, 8)
        assert tuple(connection.execute(
            "SELECT id,title,hardness,status,source_capture_id FROM fixed_commitments"
        ).fetchone()) == (8, "Appointment", "HARD", "SCHEDULED", 1)
        assert tuple(connection.execute(
            "SELECT id,title,status,source_capture_id FROM tasks"
        ).fetchone()) == (7, "Draft essay", "OPEN", 1)
        assert tuple(connection.execute(
            "SELECT id,task_id,selected_action FROM sessions"
        ).fetchone()) == (11, 7, "Draft the essay section.")
        assert connection.execute("PRAGMA foreign_key_check").fetchall() == []


def test_failed_migration_8_rolls_back_to_intact_version_7(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    path = tmp_path / "failed-v8.db"
    create_populated_v7(path)

    def fail(connection: sqlite3.Connection) -> None:
        connection.execute("ALTER TABLE fixed_commitments ADD COLUMN partial TEXT")
        raise RuntimeError("migration 8 failed")

    monkeypatch.setitem(database.MIGRATIONS, 8, fail)
    with pytest.raises(RuntimeError, match="migration 8 failed"):
        initialize_database(path)

    assert read_version(path) == 7
    assert user_objects(path) == sorted(V7_TABLE_DDL)
    with open_database(path, require_existing=True) as connection:
        database.validate_schema(connection, 7)
        assert connection.execute("PRAGMA foreign_keys").fetchone()[0] == 1
        columns = {
            row["name"]
            for row in connection.execute("PRAGMA table_info(fixed_commitments)")
        }
        assert "partial" not in columns
        assert "status" not in columns
        assert tuple(connection.execute(
            "SELECT id,title,hardness,source_capture_id FROM fixed_commitments"
        ).fetchone()) == (8, "Appointment", "HARD", 1)


def test_populated_version_5_migrates_to_8_with_task_execution_mode_and_history(
    tmp_path: Path,
) -> None:
    path = tmp_path / "version5.db"
    create_populated_v5(path)

    assert initialize_database(path) == 8

    with open_database(path, require_existing=True) as connection:
        database.validate_schema(connection, 8)
        task = connection.execute(
            """SELECT id,title,project_id,status,importance,schedule_mode,
                      day_date,deadline_date,estimated_minutes,execution_mode
               FROM tasks"""
        ).fetchone()
        assert tuple(task) == (
            7, "Draft essay", 2, "OPEN", "MUST", "DAY",
            "2026-09-05", "2026-09-10", 45, "SPLITTABLE",
        )
        sessions = connection.execute(
            """SELECT id,task_id,planned_minutes,started_at,ended_at,outcome,
                      start_reason,result_note,active_slot,selected_action
               FROM sessions ORDER BY id"""
        ).fetchall()
        assert [tuple(row) for row in sessions] == [
            (
                11, 7, 45, "2026-09-01T12:00:00.000000Z",
                "2026-09-01T12:45:00.000000Z", "PROGRESS", "because",
                "progressed", None, "Draft the essay section.",
            ),
            (
                12, 7, 25, "2026-09-01T12:45:00.000000Z", None, None,
                "active reason", None, 1, "Keep drafting.",
            ),
        ]
        assert connection.execute("PRAGMA user_version").fetchone()[0] == 8


def test_failed_migration_6_rolls_back_to_intact_version_5(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    path = tmp_path / "failed-v6.db"
    with sqlite3.connect(path) as connection:
        for ddl in V5_TABLE_DDL.values():
            connection.execute(ddl)
        stamp = "2026-09-01T12:00:00.000000Z"
        connection.execute(
            """INSERT INTO tasks
               (id,title,status,importance,schedule_mode,created_at,updated_at)
               VALUES (7,'Task','OPEN','SHOULD','FLEXIBLE',?,?)""",
            (stamp, stamp),
        )
        connection.execute("PRAGMA user_version = 5")

    def fail(connection: sqlite3.Connection) -> None:
        connection.execute("ALTER TABLE tasks ADD COLUMN partial_planning TEXT")
        raise RuntimeError("migration 6 failed")

    monkeypatch.setitem(database.MIGRATIONS, 6, fail)
    with pytest.raises(RuntimeError, match="migration 6 failed"):
        initialize_database(path)

    assert read_version(path) == 5
    assert user_objects(path) == sorted(V5_TABLE_DDL)
    with sqlite3.connect(path) as connection:
        columns = {row[1] for row in connection.execute("PRAGMA table_info(tasks)")}
        assert "execution_mode" not in columns
        assert "partial_planning" not in columns
