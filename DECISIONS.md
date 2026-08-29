# Architectural Decisions

## 2026-08-28 — Python package foundation

Personal OS requires Python 3.12 or newer and uses a `src` package layout. The
package supports both `python -m personal_os` and a `personal-os` console entry
point. Imports perform no filesystem or database work.

## 2026-08-28 — SQLite and schema evolution

Local persistence uses Python's standard-library `sqlite3` module with no ORM.
SQLite `PRAGMA user_version` is the authoritative schema version, advanced by an
explicit ordered migration mechanism. Migrations and version changes are
transactional. Infrastructure schema version 1 intentionally contains no
product-domain tables.

## 2026-08-28 — External runtime state

Runtime state defaults to `~/.personal-os`, with `personal_os.db` as the database
filename. `PERSONAL_OS_DATA_DIR` is the single directory override. Runtime data
and secrets do not belong in Git.

## 2026-08-28 — Timestamp representation

Persisted Personal OS timestamps will be timezone-aware UTC values in one
normalized representation. Naive timestamps and invented local timezone data
are not valid persistence values. POS-001 has no timestamp-bearing domain
tables.

## 2026-08-28 — Thin interfaces

CLI, HTTP, Shortcut, NFC, voice, and other interfaces remain thin adapters over
centralized application and domain logic. POS-001's CLI exposes only database
initialization.

## 2026-08-29 — Canonical structured state

Projects, tasks, fixed commitments, rules, and unresolved inbox items are the
first canonical domain records. Application-facing state uses frozen
dataclasses, string enums, typed `date` and timezone-aware `datetime` values,
and a concrete SQLite state store. Local integer primary keys are sufficient
for the personal-use MVP; future external-source identifiers remain separate.

Task scheduling and deadlines are independent. Scheduling uses FLEXIBLE, DAY,
or half-open WINDOW semantics. Deadlines preserve either a date-only fact or an
exact UTC instant without converting one into the other.

## 2026-08-29 — Schema version 2 and persistence integrity

Schema version 2 contains exactly five domain tables and is validated against
canonical table definitions. Each state operation requires an explicitly
initialized current-version database, enables and verifies SQLite foreign-key
enforcement, and owns its connection and transaction. State operations never
run migrations implicitly.

Persisted instants use fixed-width `YYYY-MM-DDTHH:MM:SS.ffffffZ` UTC text.
Rules use canonically serialized JSON-object text validated by the application,
without depending on optional SQLite JSON functions. Inbox resolution is
represented nonredundantly by nullable `resolved_at` and is one-way.

## 2026-08-29 — Durable constrained capture

Schema version 3 adds durable captures and nullable `source_capture_id` foreign
keys on projects, tasks, fixed commitments, and inbox items. Raw text and its
trusted reference instant/timezone are committed before interpretation.
Finalization is one-way and atomically creates either validated derived state or
one unresolved inbox item. Configuration/provider/refusal/invalid-output
failures preserve the capture without creating an inbox item.

Capture interpretation has one versioned semantic JSON contract and one OpenAI
3.x Responses API adapter using strict structured output and `store=False`.
Model configuration is explicit through `PERSONAL_OS_CAPTURE_MODEL`; SDK client
construction remains lazy. Deterministic application code owns relative-date,
weekend, timezone, and daylight-saving resolution. Bare clock hours and dates
without years are preserved as semantic uncertainty and remain unresolved.
The interpreter receives neither the trusted reference instant nor timezone;
decoded JSON is validated into frozen typed intents before deterministic
resolution. Active project context is deterministic and bounded, and a single
multi-date task intent expands atomically into independent canonical task rows.
