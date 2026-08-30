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

## 2026-08-29 — Deterministic recommendation boundary

Recommendation is ephemeral and read-only: it takes one coherent snapshot of
projects, tasks, and fixed commitments and mutates none of the six canonical
tables. Missed open DAY tasks remain eligible with days-late metadata; expired
WINDOW tasks remain open but are ineligible. Date-only deadlines use the
trusted local calendar date, while exact deadlines compare UTC instants, and
deadlines affect ranking metadata rather than eligibility.

Only HARD fixed commitments constrain deterministic availability. SOFT and
UNKNOWN commitments neither constrain availability nor enter AI context. The
normal duration ladder is 5, 10, 15, 20, 25, 30, 35, 45, and 60 minutes, with
an exact-duration exception for explicitly estimated 1–4 minute tasks. A
duration-feasible MUST task deterministically excludes lower-importance tasks
before candidate bounding.

The ranker receives at most 50 eligible, duration-feasible task candidates and
only derived availability, schedule, deadline, importance, and duration facts.
It receives no raw reference time, timezone, clock/daypart, rules, or canonical
state access. Its selected task and duration are validated exactly against the
supplied set.

## 2026-08-30 — Durable work-session lifecycle

Schema version 4 adds immutable work-session history without changing the six
existing tables. A nullable unique `active_slot` permits many closed sessions
but enforces at most one active session under concurrency. Start revalidation
and insertion share one immediate SQLite transaction and reuse the current
deterministic eligibility, HARD availability, duration, and feasible-MUST
policies; AI ranking and candidate bounds are not session-start constraints.

Sessions store exact UTC start and end instants, and actual elapsed duration is
derived without rounding or redundant storage. Zero-duration closure is valid.
Optional start reasons and result notes are preserved verbatim as user-provided
history and are not interpreted by AI.

FINISHED completes the Task, PROGRESS leaves it OPEN without touching its
timestamp, and BLOCKED blocks it. Closure and any Task transition are atomic.
An already matching COMPLETED or BLOCKED Task permits the corresponding close;
conflicting newer Task state is never overwritten. Closed sessions cannot be
reopened, edited, or deleted through the POS-005 API.

## 2026-08-30 — Human dogfood CLI boundary

The POS-006 CLI is a human-readable dogfood adapter, not a stable machine API.
It delegates capture, recommendation, start revalidation, and feedback entirely
to existing application services and intentionally offers no JSON contract.
Future Shortcut, NFC, HTTP, or native interfaces must consume typed application
boundaries rather than scrape CLI output.

Database initialization remains explicit: only `init-db` may create or migrate
storage, and product commands do not auto-bootstrap or repair it. Commands that
depend on local calendar meaning require an explicit IANA timezone supplied by
`--timezone` or `PERSONAL_OS_TIMEZONE`; the CLI does not infer machine-local
timezone configuration.
