# Build State

Last updated: 2026-08-30 for POS-005.

## Implemented

- Python 3.12+ package with side-effect-free imports and an infrastructure-only
  `init-db` CLI.
- External runtime data at `~/.personal-os/personal_os.db`, overrideable through
  `PERSONAL_OS_DATA_DIR`.
- Standard-library SQLite schema version 4 with explicit ordered migrations,
  strict version-specific schema validation, transactional rollback, and
  verified foreign-key enforcement.
- Fresh 0 → 1 → 2 → 3 → 4 initialization, existing version-1/version-2/version-3 migration, and idempotent
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
- Read-only deterministic eligibility and availability evaluation, including
  missed-DAY metadata, half-open WINDOW handling, deadline classification, and
  HARD-only fixed-commitment bounds.
- Duration-feasible recommendation candidates with the fixed 5–60 minute
  ladder, explicit short-task support, deterministic feasible-MUST gating,
  stable 50-candidate bounding, and strict selected-task/duration validation.
- A separate lazy OpenAI Responses API recommendation ranker that receives only
  derived facts and returns an ephemeral recommendation or valid no-work result.
- Durable work-session history with a database-enforced single active session,
  exact start/end timestamps, derived elapsed duration, planned-duration and
  current-state revalidation, and optional verbatim start/result context.
- Atomic FINISHED, PROGRESS, and BLOCKED feedback that respectively completes,
  preserves, or blocks the selected Task while retaining immutable session
  history. The internal Python APIs now demonstrate the complete minimal loop.

## Not implemented

- Additional AI providers or feedback/session AI behavior
- Calendar or Google Sheets integration
- Product CRUD CLI commands, HTTP endpoints, Shortcuts, NFC, voice, or UI
- Notifications, background work, deletion, import/export, or duration learning
- Routines, goals, waiting-for items, decisions, open questions, dependencies,
  preferences, or temporary context

## Validation

Run on 2026-08-30 with Python 3.12.4 and pytest 8.4.2:

- `python -m pytest` — passed: 216 passed, 0 failed.
- `python -m compileall -q src tests` — passed with exit code 0.
- `python -m personal_os --help` — passed with exit code 0.
- `personal-os --help` — passed with exit code 0.
- `python -m personal_os init-db`, using an isolated temporary
  `PERSONAL_OS_DATA_DIR` and run twice — passed at schema version 4.
- Isolated schema inspection confirmed `PRAGMA user_version = 4`, the seven
  expected tables, all project/capture traceability `ON DELETE RESTRICT`
  foreign keys, and canonical table definitions. A populated version-2 fixture
  migrated without losing data.
- Capture tests use fake interpreters/clients and confirmed raw persistence
  precedes configuration, authentication, provider, or output processing. No
  live OpenAI request was made.
- Recommendation tests use fake rankers/clients and confirm coherent read-only
  snapshots, unchanged schema and table contents, HARD-only availability,
  feasible-MUST gating before bounding, short-task feasibility, derived-only AI
  input, and no live OpenAI request.
- Session tests confirm strict v4 migration and storage constraints, one-active
  concurrency, deterministic start rejection precedence, atomic feedback
  rollback, and the complete capture-to-updated-state loop without network use.
- `git diff --check` — passed with exit code 0.
