"""Concrete SQLite-backed operations for canonical structured state."""

from __future__ import annotations

import sqlite3
import json
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

from personal_os.database import (
    CURRENT_SCHEMA_VERSION,
    DatabaseInitializationError,
    get_schema_version,
    open_database,
    validate_schema,
)
from personal_os.errors import DomainValidationError, EntityNotFoundError, PersistenceError
from personal_os.models import (
    CommitmentHardness,
    Capture,
    CaptureFailureKind,
    CaptureStatus,
    FixedCommitment,
    InboxItem,
    Project,
    ProjectStatus,
    Rule,
    Task,
    TaskImportance,
    TaskScheduleMode,
    TaskStatus,
    canonicalize_parameters,
    normalize_instant,
    optional_instant,
    optional_text,
    parse_date,
    parse_instant,
    parse_parameters,
    require_enum,
    require_identifier,
    require_text,
    serialize_date,
    serialize_instant,
    serialize_parameters,
    validate_task_fields,
)

_OMITTED = object()


class SQLiteStateStore:
    """Persist typed Personal OS state in an explicitly initialized database."""

    def __init__(
        self, database_path: Path, *, clock: Callable[[], datetime] | None = None
    ) -> None:
        self.database_path = Path(database_path).expanduser().resolve(strict=False)
        self._clock = clock or (lambda: datetime.now(UTC))

    def _now(self) -> datetime:
        return normalize_instant(self._clock(), "clock result")

    @contextmanager
    def _connection(self) -> Iterator[sqlite3.Connection]:
        try:
            connection = open_database(self.database_path, require_existing=True)
        except sqlite3.Error as exc:
            raise PersistenceError(f"cannot open initialized state database: {exc}") from exc
        try:
            version = get_schema_version(connection)
            if version != CURRENT_SCHEMA_VERSION:
                raise PersistenceError(
                    f"state database schema version {version} is not current version "
                    f"{CURRENT_SCHEMA_VERSION}; run explicit database initialization"
                )
            try:
                validate_schema(connection, version)
            except DatabaseInitializationError as exc:
                raise PersistenceError(f"state database schema is incompatible: {exc}") from exc
            yield connection
        except sqlite3.Error as exc:
            raise PersistenceError(f"SQLite state operation failed: {exc}") from exc
        finally:
            connection.close()

    @contextmanager
    def _transaction(self) -> Iterator[sqlite3.Connection]:
        with self._connection() as connection:
            connection.execute("BEGIN IMMEDIATE")
            try:
                yield connection
                connection.commit()
            except Exception:
                connection.rollback()
                raise

    @staticmethod
    def _row_or_missing(
        connection: sqlite3.Connection, table: str, entity_id: int, label: str
    ) -> sqlite3.Row:
        row = connection.execute(
            f"SELECT * FROM {table} WHERE id = ?", (require_identifier(entity_id),)
        ).fetchone()
        if row is None:
            raise EntityNotFoundError(f"{label} {entity_id} does not exist")
        return row

    @staticmethod
    def _decode(factory: Callable[[], Any], label: str) -> Any:
        try:
            return factory()
        except (DomainValidationError, ValueError, TypeError) as exc:
            raise PersistenceError(f"stored {label} is malformed: {exc}") from exc

    def _project_from_row(self, row: sqlite3.Row) -> Project:
        return self._decode(
            lambda: Project(
                id=row["id"], name=row["name"], description=row["description"],
                status=ProjectStatus(row["status"]),
                created_at=parse_instant(row["created_at"], "created_at"),
                updated_at=parse_instant(row["updated_at"], "updated_at"),
                source_capture_id=row["source_capture_id"],
            ),
            "project",
        )

    def _task_from_row(self, row: sqlite3.Row) -> Task:
        return self._decode(
            lambda: Task(
                id=row["id"], title=row["title"], project_id=row["project_id"],
                status=TaskStatus(row["status"]), importance=TaskImportance(row["importance"]),
                schedule_mode=TaskScheduleMode(row["schedule_mode"]),
                day_date=None if row["day_date"] is None else parse_date(row["day_date"], "day_date"),
                window_start=None if row["window_start"] is None else parse_instant(row["window_start"], "window_start"),
                window_end=None if row["window_end"] is None else parse_instant(row["window_end"], "window_end"),
                deadline_date=None if row["deadline_date"] is None else parse_date(row["deadline_date"], "deadline_date"),
                deadline_at=None if row["deadline_at"] is None else parse_instant(row["deadline_at"], "deadline_at"),
                estimated_minutes=row["estimated_minutes"],
                created_at=parse_instant(row["created_at"], "created_at"),
                updated_at=parse_instant(row["updated_at"], "updated_at"),
                source_capture_id=row["source_capture_id"],
            ),
            "task",
        )

    def _commitment_from_row(self, row: sqlite3.Row) -> FixedCommitment:
        return self._decode(
            lambda: FixedCommitment(
                id=row["id"], title=row["title"],
                start_at=parse_instant(row["start_at"], "start_at"),
                end_at=None if row["end_at"] is None else parse_instant(row["end_at"], "end_at"),
                hardness=CommitmentHardness(row["hardness"]),
                created_at=parse_instant(row["created_at"], "created_at"),
                updated_at=parse_instant(row["updated_at"], "updated_at"),
                source_capture_id=row["source_capture_id"],
            ),
            "fixed commitment",
        )

    @staticmethod
    def _decode_rule_enabled(value: object) -> bool:
        if type(value) is not int or value not in (0, 1):
            raise DomainValidationError("stored rule enabled must be integer 0 or 1")
        return value == 1

    def _rule_from_row(self, row: sqlite3.Row) -> Rule:
        return self._decode(
            lambda: Rule(
                id=row["id"], kind=row["kind"],
                parameters=parse_parameters(row["parameters_json"]),
                enabled=self._decode_rule_enabled(row["enabled"]),
                created_at=parse_instant(row["created_at"], "created_at"),
                updated_at=parse_instant(row["updated_at"], "updated_at"),
            ),
            "rule",
        )

    def _inbox_from_row(self, row: sqlite3.Row) -> InboxItem:
        return self._decode(
            lambda: InboxItem(
                id=row["id"], raw_text=row["raw_text"],
                unresolved_reason=row["unresolved_reason"],
                resolved_at=None if row["resolved_at"] is None else parse_instant(row["resolved_at"], "resolved_at"),
                created_at=parse_instant(row["created_at"], "created_at"),
                updated_at=parse_instant(row["updated_at"], "updated_at"),
                source_capture_id=row["source_capture_id"],
            ),
            "inbox item",
        )

    def _insert_project(
        self, connection: sqlite3.Connection, *, name: str,
        description: str | None, status: ProjectStatus,
        source_capture_id: int | None = None,
    ) -> Project:
        now = serialize_instant(self._now())
        cursor = connection.execute(
            "INSERT INTO projects (name, description, status, created_at, updated_at, source_capture_id) VALUES (?, ?, ?, ?, ?, ?)",
            (name, description, status.value, now, now, source_capture_id),
        )
        return self._project_from_row(self._row_or_missing(connection, "projects", cursor.lastrowid, "project"))

    def _insert_task(
        self, connection: sqlite3.Connection, *, values: dict[str, object],
        source_capture_id: int | None = None,
    ) -> Task:
        self._require_project(connection, values["project_id"])
        now = serialize_instant(self._now())
        cursor = connection.execute(
            """INSERT INTO tasks (
                title, project_id, status, importance, schedule_mode, day_date,
                window_start, window_end, deadline_date, deadline_at,
                estimated_minutes, created_at, updated_at, source_capture_id
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            self._task_sql_values(values) + (now, now, source_capture_id),
        )
        return self._task_from_row(self._row_or_missing(connection, "tasks", cursor.lastrowid, "task"))

    def _insert_fixed_commitment(
        self, connection: sqlite3.Connection, *, title: str, start_at: datetime,
        end_at: datetime | None, hardness: CommitmentHardness,
        source_capture_id: int | None = None,
    ) -> FixedCommitment:
        now = serialize_instant(self._now())
        cursor = connection.execute(
            "INSERT INTO fixed_commitments (title, start_at, end_at, hardness, created_at, updated_at, source_capture_id) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (title, serialize_instant(start_at), None if end_at is None else serialize_instant(end_at), hardness.value, now, now, source_capture_id),
        )
        return self._commitment_from_row(self._row_or_missing(connection, "fixed_commitments", cursor.lastrowid, "fixed commitment"))

    def _insert_inbox_item(
        self, connection: sqlite3.Connection, *, raw_text: str,
        unresolved_reason: str, source_capture_id: int | None = None,
    ) -> InboxItem:
        now = serialize_instant(self._now())
        cursor = connection.execute(
            "INSERT INTO inbox_items (raw_text, unresolved_reason, resolved_at, created_at, updated_at, source_capture_id) VALUES (?, ?, NULL, ?, ?, ?)",
            (raw_text, unresolved_reason, now, now, source_capture_id),
        )
        return self._inbox_from_row(self._row_or_missing(connection, "inbox_items", cursor.lastrowid, "inbox item"))

    def create_project(
        self, name: str, description: str | None = None,
        status: ProjectStatus = ProjectStatus.ACTIVE,
    ) -> Project:
        name = require_text(name, "name")
        description = optional_text(description, "description")
        status = require_enum(status, ProjectStatus, "status")  # type: ignore[assignment]
        with self._transaction() as connection:
            return self._insert_project(connection, name=name, description=description, status=status)

    def get_project(self, project_id: int) -> Project:
        with self._connection() as connection:
            return self._project_from_row(self._row_or_missing(connection, "projects", project_id, "project"))

    def list_projects(self) -> list[Project]:
        with self._connection() as connection:
            return [self._project_from_row(row) for row in connection.execute("SELECT * FROM projects ORDER BY id")]

    def update_project(
        self, project_id: int, *, name: object = _OMITTED,
        description: object = _OMITTED, status: object = _OMITTED,
    ) -> Project:
        with self._transaction() as connection:
            current = self._project_from_row(self._row_or_missing(connection, "projects", project_id, "project"))
            new_name = current.name if name is _OMITTED else require_text(name, "name")
            new_description = current.description if description is _OMITTED else optional_text(description, "description")
            new_status = current.status if status is _OMITTED else require_enum(status, ProjectStatus, "status")
            connection.execute(
                "UPDATE projects SET name = ?, description = ?, status = ?, updated_at = ? WHERE id = ?",
                (new_name, new_description, new_status.value, serialize_instant(self._now()), project_id),
            )
            return self._project_from_row(self._row_or_missing(connection, "projects", project_id, "project"))

    @staticmethod
    def _task_sql_values(values: dict[str, object]) -> tuple[object, ...]:
        return (
            values["title"], values["project_id"], values["status"].value,
            values["importance"].value, values["schedule_mode"].value,
            None if values["day_date"] is None else serialize_date(values["day_date"]),
            None if values["window_start"] is None else serialize_instant(values["window_start"]),
            None if values["window_end"] is None else serialize_instant(values["window_end"]),
            None if values["deadline_date"] is None else serialize_date(values["deadline_date"]),
            None if values["deadline_at"] is None else serialize_instant(values["deadline_at"]),
            values["estimated_minutes"],
        )

    @staticmethod
    def _require_project(connection: sqlite3.Connection, project_id: int | None) -> None:
        if project_id is not None and connection.execute(
            "SELECT 1 FROM projects WHERE id = ?", (project_id,)
        ).fetchone() is None:
            raise EntityNotFoundError(f"project {project_id} does not exist")

    def create_task(
        self, title: str, *, project_id: int | None = None,
        status: TaskStatus = TaskStatus.OPEN,
        importance: TaskImportance = TaskImportance.UNSPECIFIED,
        schedule_mode: TaskScheduleMode = TaskScheduleMode.FLEXIBLE,
        day_date: date | None = None, window_start: datetime | None = None,
        window_end: datetime | None = None, deadline_date: date | None = None,
        deadline_at: datetime | None = None, estimated_minutes: int | None = None,
    ) -> Task:
        values = validate_task_fields(
            title=title, project_id=project_id, status=status, importance=importance,
            schedule_mode=schedule_mode, day_date=day_date, window_start=window_start,
            window_end=window_end, deadline_date=deadline_date, deadline_at=deadline_at,
            estimated_minutes=estimated_minutes,
        )
        with self._transaction() as connection:
            return self._insert_task(connection, values=values)

    def get_task(self, task_id: int) -> Task:
        with self._connection() as connection:
            return self._task_from_row(self._row_or_missing(connection, "tasks", task_id, "task"))

    def list_tasks(self) -> list[Task]:
        with self._connection() as connection:
            return [self._task_from_row(row) for row in connection.execute("SELECT * FROM tasks ORDER BY id")]

    def update_task(
        self, task_id: int, *, title: object = _OMITTED,
        project_id: object = _OMITTED, status: object = _OMITTED,
        importance: object = _OMITTED, schedule_mode: object = _OMITTED,
        day_date: object = _OMITTED, window_start: object = _OMITTED,
        window_end: object = _OMITTED, deadline_date: object = _OMITTED,
        deadline_at: object = _OMITTED, estimated_minutes: object = _OMITTED,
    ) -> Task:
        with self._transaction() as connection:
            current = self._task_from_row(self._row_or_missing(connection, "tasks", task_id, "task"))
            proposed = {
                field: current_value if supplied is _OMITTED else supplied
                for field, current_value, supplied in (
                    ("title", current.title, title), ("project_id", current.project_id, project_id),
                    ("status", current.status, status), ("importance", current.importance, importance),
                    ("schedule_mode", current.schedule_mode, schedule_mode),
                    ("day_date", current.day_date, day_date),
                    ("window_start", current.window_start, window_start),
                    ("window_end", current.window_end, window_end),
                    ("deadline_date", current.deadline_date, deadline_date),
                    ("deadline_at", current.deadline_at, deadline_at),
                    ("estimated_minutes", current.estimated_minutes, estimated_minutes),
                )
            }
            values = validate_task_fields(**proposed)
            self._require_project(connection, values["project_id"])
            connection.execute(
                """UPDATE tasks SET title = ?, project_id = ?, status = ?, importance = ?,
                    schedule_mode = ?, day_date = ?, window_start = ?, window_end = ?,
                    deadline_date = ?, deadline_at = ?, estimated_minutes = ?, updated_at = ?
                    WHERE id = ?""",
                self._task_sql_values(values) + (serialize_instant(self._now()), task_id),
            )
            return self._task_from_row(self._row_or_missing(connection, "tasks", task_id, "task"))

    def create_fixed_commitment(
        self, title: str, start_at: datetime, *, end_at: datetime | None = None,
        hardness: CommitmentHardness = CommitmentHardness.UNKNOWN,
    ) -> FixedCommitment:
        title = require_text(title, "title")
        start = normalize_instant(start_at, "start_at")
        end = optional_instant(end_at, "end_at")
        hardness = require_enum(hardness, CommitmentHardness, "hardness")  # type: ignore[assignment]
        if end is not None and start >= end:
            raise DomainValidationError("start_at must be before end_at")
        with self._transaction() as connection:
            return self._insert_fixed_commitment(connection, title=title, start_at=start, end_at=end, hardness=hardness)

    def get_fixed_commitment(self, commitment_id: int) -> FixedCommitment:
        with self._connection() as connection:
            return self._commitment_from_row(self._row_or_missing(connection, "fixed_commitments", commitment_id, "fixed commitment"))

    def list_fixed_commitments(self) -> list[FixedCommitment]:
        with self._connection() as connection:
            return [self._commitment_from_row(row) for row in connection.execute("SELECT * FROM fixed_commitments ORDER BY id")]

    def update_fixed_commitment(
        self, commitment_id: int, *, title: object = _OMITTED,
        start_at: object = _OMITTED, end_at: object = _OMITTED,
        hardness: object = _OMITTED,
    ) -> FixedCommitment:
        with self._transaction() as connection:
            current = self._commitment_from_row(self._row_or_missing(connection, "fixed_commitments", commitment_id, "fixed commitment"))
            new_title = current.title if title is _OMITTED else require_text(title, "title")
            new_start = current.start_at if start_at is _OMITTED else normalize_instant(start_at, "start_at")
            new_end = current.end_at if end_at is _OMITTED else optional_instant(end_at, "end_at")
            new_hardness = current.hardness if hardness is _OMITTED else require_enum(hardness, CommitmentHardness, "hardness")
            if new_end is not None and new_start >= new_end:
                raise DomainValidationError("start_at must be before end_at")
            connection.execute(
                "UPDATE fixed_commitments SET title = ?, start_at = ?, end_at = ?, hardness = ?, updated_at = ? WHERE id = ?",
                (new_title, serialize_instant(new_start), None if new_end is None else serialize_instant(new_end), new_hardness.value, serialize_instant(self._now()), commitment_id),
            )
            return self._commitment_from_row(self._row_or_missing(connection, "fixed_commitments", commitment_id, "fixed commitment"))

    def create_rule(self, kind: str, parameters: dict[str, Any] | None = None, *, enabled: bool = True) -> Rule:
        kind = require_text(kind, "kind")
        parameters = canonicalize_parameters({} if parameters is None else parameters)
        if not isinstance(enabled, bool):
            raise DomainValidationError("enabled must be a boolean")
        with self._transaction() as connection:
            now = serialize_instant(self._now())
            cursor = connection.execute(
                "INSERT INTO rules (kind, parameters_json, enabled, created_at, updated_at) VALUES (?, ?, ?, ?, ?)",
                (kind, serialize_parameters(parameters), int(enabled), now, now),
            )
            return self._rule_from_row(self._row_or_missing(connection, "rules", cursor.lastrowid, "rule"))

    def get_rule(self, rule_id: int) -> Rule:
        with self._connection() as connection:
            return self._rule_from_row(self._row_or_missing(connection, "rules", rule_id, "rule"))

    def list_rules(self) -> list[Rule]:
        with self._connection() as connection:
            return [self._rule_from_row(row) for row in connection.execute("SELECT * FROM rules ORDER BY id")]

    def update_rule(
        self, rule_id: int, *, kind: object = _OMITTED,
        parameters: object = _OMITTED, enabled: object = _OMITTED,
    ) -> Rule:
        with self._transaction() as connection:
            current = self._rule_from_row(self._row_or_missing(connection, "rules", rule_id, "rule"))
            new_kind = current.kind if kind is _OMITTED else require_text(kind, "kind")
            new_parameters = current.parameters if parameters is _OMITTED else canonicalize_parameters(parameters)
            new_enabled = current.enabled if enabled is _OMITTED else enabled
            if not isinstance(new_enabled, bool):
                raise DomainValidationError("enabled must be a boolean")
            connection.execute(
                "UPDATE rules SET kind = ?, parameters_json = ?, enabled = ?, updated_at = ? WHERE id = ?",
                (new_kind, serialize_parameters(new_parameters), int(new_enabled), serialize_instant(self._now()), rule_id),
            )
            return self._rule_from_row(self._row_or_missing(connection, "rules", rule_id, "rule"))

    def create_inbox_item(self, raw_text: str, unresolved_reason: str) -> InboxItem:
        raw_text = require_text(raw_text, "raw_text", preserve=True)
        unresolved_reason = require_text(unresolved_reason, "unresolved_reason")
        with self._transaction() as connection:
            return self._insert_inbox_item(connection, raw_text=raw_text, unresolved_reason=unresolved_reason)

    def get_inbox_item(self, item_id: int) -> InboxItem:
        with self._connection() as connection:
            return self._inbox_from_row(self._row_or_missing(connection, "inbox_items", item_id, "inbox item"))

    def list_inbox_items(self) -> list[InboxItem]:
        with self._connection() as connection:
            return [self._inbox_from_row(row) for row in connection.execute("SELECT * FROM inbox_items ORDER BY id")]

    def update_inbox_item(self, item_id: int, *, unresolved_reason: str) -> InboxItem:
        reason = require_text(unresolved_reason, "unresolved_reason")
        with self._transaction() as connection:
            self._row_or_missing(connection, "inbox_items", item_id, "inbox item")
            connection.execute(
                "UPDATE inbox_items SET unresolved_reason = ?, updated_at = ? WHERE id = ?",
                (reason, serialize_instant(self._now()), item_id),
            )
            return self._inbox_from_row(self._row_or_missing(connection, "inbox_items", item_id, "inbox item"))

    def resolve_inbox_item(self, item_id: int) -> InboxItem:
        with self._transaction() as connection:
            current = self._inbox_from_row(self._row_or_missing(connection, "inbox_items", item_id, "inbox item"))
            if current.is_resolved:
                return current
            now = serialize_instant(self._now())
            connection.execute(
                "UPDATE inbox_items SET resolved_at = ?, updated_at = ? WHERE id = ?",
                (now, now, item_id),
            )
            return self._inbox_from_row(self._row_or_missing(connection, "inbox_items", item_id, "inbox item"))

    def _capture_from_row(self, row: sqlite3.Row) -> Capture:
        def decode() -> Capture:
            interpretation = None
            if row["interpretation_json"] is not None:
                interpretation = json.loads(row["interpretation_json"])
                if not isinstance(interpretation, dict):
                    raise DomainValidationError("stored interpretation must be a JSON object")
            return Capture(
                id=row["id"], raw_text=row["raw_text"], status=CaptureStatus(row["status"]),
                reference_time=parse_instant(row["reference_time"], "reference_time"),
                timezone_name=row["timezone_name"], interpretation=interpretation,
                interpretation_version=row["interpretation_version"],
                model_provider=row["model_provider"], model_name=row["model_name"],
                model_response_id=row["model_response_id"],
                unresolved_reason=row["unresolved_reason"],
                failure_kind=None if row["failure_kind"] is None else CaptureFailureKind(row["failure_kind"]),
                failure_reason=row["failure_reason"],
                created_at=parse_instant(row["created_at"], "created_at"),
                updated_at=parse_instant(row["updated_at"], "updated_at"),
            )
        return self._decode(decode, "capture")

    def create_capture(self, raw_text: str, reference_time: datetime, timezone_name: str) -> Capture:
        raw = require_text(raw_text, "raw_text", preserve=True)
        reference = normalize_instant(reference_time, "reference_time")
        zone = require_text(timezone_name, "timezone_name")
        with self._transaction() as connection:
            now = serialize_instant(self._now())
            cursor = connection.execute(
                "INSERT INTO captures (raw_text, status, reference_time, timezone_name, created_at, updated_at) VALUES (?, 'RECEIVED', ?, ?, ?, ?)",
                (raw, serialize_instant(reference), zone, now, now),
            )
            return self._capture_from_row(self._row_or_missing(connection, "captures", cursor.lastrowid, "capture"))

    def get_capture(self, capture_id: int) -> Capture:
        with self._connection() as connection:
            return self._capture_from_row(self._row_or_missing(connection, "captures", capture_id, "capture"))

    def list_captures(self) -> list[Capture]:
        with self._connection() as connection:
            return [self._capture_from_row(row) for row in connection.execute("SELECT * FROM captures ORDER BY id")]

    @staticmethod
    def _ensure_received(connection: sqlite3.Connection, capture_id: int) -> None:
        row = SQLiteStateStore._row_or_missing(connection, "captures", capture_id, "capture")
        if row["status"] != CaptureStatus.RECEIVED.value:
            raise PersistenceError(f"capture {capture_id} has already been finalized")

    @staticmethod
    def _interpretation_json(interpretation: dict[str, Any] | None) -> str | None:
        if interpretation is None:
            return None
        return json.dumps(interpretation, allow_nan=False, separators=(",", ":"), sort_keys=True)

    def mark_capture_failed(
        self, capture_id: int, kind: CaptureFailureKind, reason: str, *,
        interpretation: dict[str, Any] | None = None, model_provider: str | None = None,
        model_name: str | None = None, model_response_id: str | None = None,
    ) -> Capture:
        kind = require_enum(kind, CaptureFailureKind, "failure_kind")  # type: ignore[assignment]
        reason = require_text(reason, "failure_reason")
        with self._transaction() as connection:
            self._ensure_received(connection, capture_id)
            connection.execute(
                """UPDATE captures SET status='FAILED', interpretation_json=?, interpretation_version=?,
                    model_provider=?, model_name=?, model_response_id=?, failure_kind=?, failure_reason=?, updated_at=? WHERE id=?""",
                (self._interpretation_json(interpretation), 1 if interpretation is not None else None,
                 model_provider, model_name, model_response_id, kind.value, reason,
                 serialize_instant(self._now()), capture_id),
            )
            return self._capture_from_row(self._row_or_missing(connection, "captures", capture_id, "capture"))

    def apply_unresolved_capture(
        self, capture_id: int, reason: str, *, interpretation: dict[str, Any],
        model_provider: str, model_name: str, model_response_id: str | None,
    ) -> tuple[Capture, InboxItem]:
        reason = require_text(reason, "unresolved_reason")
        with self._transaction() as connection:
            row = self._row_or_missing(connection, "captures", capture_id, "capture")
            self._ensure_received(connection, capture_id)
            now = serialize_instant(self._now())
            inbox = self._insert_inbox_item(
                connection, raw_text=row["raw_text"], unresolved_reason=reason,
                source_capture_id=capture_id,
            )
            connection.execute(
                """UPDATE captures SET status='UNRESOLVED', interpretation_json=?, interpretation_version=1,
                    model_provider=?, model_name=?, model_response_id=?, unresolved_reason=?, updated_at=? WHERE id=?""",
                (self._interpretation_json(interpretation), model_provider, model_name,
                 model_response_id, reason, now, capture_id),
            )
            capture = self._capture_from_row(self._row_or_missing(connection, "captures", capture_id, "capture"))
            return capture, inbox

    def apply_resolved_capture(
        self, capture_id: int, *, interpretation: dict[str, Any], model_provider: str,
        model_name: str, model_response_id: str | None, project: dict[str, Any] | None,
        tasks: list[dict[str, Any]], commitments: list[dict[str, Any]],
    ) -> tuple[Capture, Project | None, list[Task], list[FixedCommitment]]:
        with self._transaction() as connection:
            self._ensure_received(connection, capture_id)
            now = serialize_instant(self._now())
            created_project = None
            if project is not None:
                created_project = self._insert_project(
                    connection, name=project["name"], description=project.get("description"),
                    status=ProjectStatus.ACTIVE, source_capture_id=capture_id,
                )
            created_tasks = []
            for item in tasks:
                project_id = created_project.id if item.get("project_id") == "NEW" else item.get("project_id")
                values = validate_task_fields(**{**item, "project_id": project_id})
                created_tasks.append(self._insert_task(connection, values=values, source_capture_id=capture_id))
            created_commitments = []
            for item in commitments:
                created_commitments.append(self._insert_fixed_commitment(
                    connection, title=item["title"], start_at=item["start_at"],
                    end_at=item.get("end_at"), hardness=item.get("hardness", CommitmentHardness.UNKNOWN),
                    source_capture_id=capture_id,
                ))
            connection.execute(
                """UPDATE captures SET status='APPLIED', interpretation_json=?, interpretation_version=1,
                    model_provider=?, model_name=?, model_response_id=?, updated_at=? WHERE id=?""",
                (self._interpretation_json(interpretation), model_provider, model_name,
                 model_response_id, now, capture_id),
            )
            capture = self._capture_from_row(self._row_or_missing(connection, "captures", capture_id, "capture"))
            return capture, created_project, created_tasks, created_commitments
