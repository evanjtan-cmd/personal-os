# Build State

Last updated: 2026-08-29 for POS-003.

## Implemented

- Python 3.12+ package with side-effect-free imports and an infrastructure-only
  `init-db` CLI.
- External runtime data at `~/.personal-os/personal_os.db`, overrideable through
  `PERSONAL_OS_DATA_DIR`.
- Standard-library SQLite schema version 3 with explicit ordered migrations,
  strict version-specific schema validation, transactional rollback, and
  verified foreign-key enforcement.
- Fresh 0 → 1 → 2 → 3 initialization, existing version-1/version-2 migration, and idempotent
  current-version initialization.
- Typed, validated application records and SQLite create/get/list/update
  operations for:
  - projects;
  - tasks;
  - fixed commitments;
  - structured rules;
  - inbox/unresolved items.
- Task OPEN/BLOCKED/COMPLETED status, UNSPECIFIED/MUST/SHOULD/COULD importance,
  FLEXIBLE/DAY/WINDOW scheduling, mutually exclusive date-only or exact-time
  deadlines, and positive estimated durations.
- Fixed commitments with explicit UNKNOWN/HARD/SOFT classification and optional
  ends.
- Canonical UTC instant storage, calendar-date storage, canonical JSON-object
  rule parameters, and one-way inbox resolution.
- A concrete state store with explicit bootstrap boundaries, parameterized SQL,
  atomic mutations, typed reads, and explicit validation/not-found/persistence
  errors.
- Durable RECEIVED/APPLIED/UNRESOLVED/FAILED captures with immutable raw input,
  reference instant and IANA timezone, validated interpretation metadata,
  classified failures, and source traceability on capture-created state.
- Natural-language capture application flow with a constrained OpenAI Responses
  API adapter, deterministic relative-date and local-time resolution, atomic
  multi-record application, and unresolved inbox routing.

## Not implemented

- Eligibility, prioritization, or recommendations
- Work sessions or Finished/Progress/Blocked session handling
- Additional AI providers or AI behavior beyond capture interpretation
- Calendar or Google Sheets integration
- Product CRUD CLI commands, HTTP endpoints, Shortcuts, NFC, voice, or UI
- Notifications, background work, deletion, import/export, or duration learning
- Routines, goals, waiting-for items, decisions, open questions, dependencies,
  preferences, temporary context, or historical sessions

## Validation

Run on 2026-08-29 with Python 3.12.4 and pytest 8.4.2:

- `python -m pytest` — passed: 108 passed, 0 failed.
- `python -m compileall -q src tests` — passed with exit code 0.
- `python -m personal_os --help` — passed with exit code 0.
- `personal-os --help` — passed with exit code 0.
- `python -m personal_os init-db`, using an isolated temporary
  `PERSONAL_OS_DATA_DIR` and run twice — passed at schema version 3.
- Isolated schema inspection confirmed `PRAGMA user_version = 3`, the six
  expected tables, all project/capture traceability `ON DELETE RESTRICT`
  foreign keys, and canonical table definitions. A populated version-2 fixture
  migrated without losing data.
- Capture tests use fake interpreters/clients and confirmed raw persistence
  precedes configuration, authentication, provider, or output processing. No
  live OpenAI request was made.
- `git diff --check` — passed with exit code 0.
