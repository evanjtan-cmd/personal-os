# Build State

Last updated: 2026-10-06 for POS-023 Clock Capture Robustness.

## Implemented

- Python 3.12+ package with side-effect-free imports and a thin human-facing
  dogfood CLI over the completed application services.
- External runtime data at `~/.personal-os/personal_os.db`, overrideable through
  `PERSONAL_OS_DATA_DIR`.
- Standard-library SQLite schema version 6 with explicit ordered migrations,
  strict version-specific schema validation, transactional rollback, and
  verified foreign-key enforcement.
- Fresh 0 → 1 → 2 → 3 → 4 → 5 → 6 initialization, existing
  version-1/version-2/version-3/version-4/version-5 migration, and idempotent
  current-version initialization.
- Typed, validated application records and SQLite create/get/list/update
  operations for:
  - projects;
  - tasks;
  - fixed commitments;
  - structured rules;
  - inbox/unresolved items.
- Task OPEN/BLOCKED/COMPLETED status, UNSPECIFIED/MUST/SHOULD/COULD importance,
  FLEXIBLE/DAY/WINDOW scheduling, SPLITTABLE/ONE_SITTING execution mode,
  mutually exclusive date-only or exact-time deadlines, and positive estimated
  durations.
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
- POS-022 gives the capture provider schema a fixed temporal wire contract:
  tagged date objects with explicit weekday/date/text fields, weekday-name to
  ISO-weekday normalization at the adapter boundary, and fixed deadline objects
  with `kind`, `date`, and nullable `clock`. Canonical date/deadline semantics
  and fail-closed validation remain unchanged.
- POS-023 simplifies provider clock capture to a literal clock-text wire field.
  The provider copies explicit clock wording instead of selecting canonical
  `CLOCK_12`, `CLOCK_24`, or `BARE_HOUR`; the adapter deterministically parses
  supported forms before canonical validation. Bare `3`/`3:45` remain
  unresolved clock uncertainty downstream, AM/PM text becomes canonical
  12-hour time, `15:45` becomes canonical 24-hour time, and zero-padded
  `03:45` is treated as explicit 24-hour notation.
- Schedule-less actionable captures use canonical FLEXIBLE task semantics.
  Missing optional schedule, deadline, importance, duration, or project facts
  do not cause UNRESOLVED; genuine ambiguity in explicitly supplied meaning
  remains unresolved without invented facts or reason-string post-processing.
- Read-only deterministic eligibility and availability evaluation, including
  missed-DAY metadata, half-open WINDOW handling, deadline classification, and
  HARD-only fixed-commitment bounds.
- Duration-feasible recommendation candidates with the normal SPLITTABLE
  5–60 minute ladder, explicit short-task support, ONE_SITTING full-duration
  feasibility, deterministic feasible-MUST gating, stable 50-candidate
  bounding, and strict selected-task/duration validation.
- POS-021 task workability policy: SPLITTABLE tasks keep bounded partial-session
  recommendations, with unknown availability capped at 30 minutes; ONE_SITTING
  tasks require a known positive estimate and known sufficient availability,
  and their only allowed duration is the full estimate, even above 60 minutes.
  Recommendation and session start share this deterministic policy.
- A separate lazy OpenAI Responses API recommendation ranker that receives only
  derived facts and returns an ephemeral recommendation with a concise concrete
  execution action, or a valid no-work result. The action is validated
  separately from its ranking explanation and is not persisted.
- POS-013 tightens the recommendation provider contract: NO_WORK needs an
  affirmative reason no supplied candidate should be recommended now, not just
  absence of a MUST gate; actions may use generic execution framing but must
  not invent unsupported topical substeps. The response schema and
  deterministic policy are unchanged.
- Durable work-session history with a database-enforced single active session,
  exact start/end timestamps, derived elapsed duration, planned-duration and
  current-state revalidation, optional verbatim selected action, and distinct
  optional start/result context. Recommendation actions become durable only
  when accepted at session start and never affect deterministic policy.
- Atomic FINISHED, PROGRESS, and BLOCKED feedback that respectively completes,
  preserves, or blocks the selected Task while retaining immutable session
  history. The internal Python APIs now demonstrate the complete minimal loop.
- Explicit-initialization CLI commands for capture, recommendation, session
  start, FINISHED/PROGRESS/BLOCKED feedback, and active-session display. The
  adapter uses explicit IANA timezone configuration, fresh trusted instants,
  human-readable output, and no implicit database bootstrap or duplicated
  domain policy.
- A separate one-shot `personal-os-bridge` machine adapter with strict,
  versioned JSON stdin/stdout requests for capture, recommendation, activation,
  session lifecycle, active-session inspection, and current-state overview. It
  uses shared runtime construction and the same typed services as the human
  CLI, trusts only its own fresh UTC clock where needed, performs no
  initialization or migration, and has no network listener or authentication
  layer.
- A canonical read-only work-activation service for availability-now triggers.
  It returns an existing active session without invoking recommendation, or
  delegates to the existing recommendation service and preserves RECOMMEND or
  NO_WORK. Recommendation-only timezone configuration is resolved only after
  confirming no session is active. Its optional caller time cap is distinct
  from HARD availability and selected duration, is not defaulted or persisted,
  and activation never starts a session.
- Machine Interface v1 additionally exposes `activate` with strict request
  validation and ACTIVE_SESSION/RECOMMEND/NO_WORK result kinds while retaining
  all existing version-1 operations unchanged.
- A separate `personal-os-http` local server binds to `127.0.0.1` with a
  configurable port and returns Machine Interface v1 response envelopes.
  Version and operation are transport-owned and rejected in request bodies.
  It reuses bridge validation/serialization and canonical application services,
  performs no database initialization or migration, and adds no runtime
  dependency.
- POS-015 adds `POST /v1/start` and `POST /v1/feedback` to the same loopback
  adapter using bridge validation, serialization, and canonical session
  services. A same-origin, framework-free Work page at `/` displays activation
  states and errors, starts the exact recommended action and duration, and
  records all three feedback outcomes. It does not auto-request another
  recommendation after start or feedback. The server validates loopback Host
  and POST Origin headers, rejects cross-site browser requests, and serves only
  fixed packaged assets with restrictive content security headers.
- POS-018 removes timezone collection from the browser Work page. Browser
  activation and recommendation start requests omit `timezone`, relying on the
  HTTP process' configured `PERSONAL_OS_TIMEZONE`; the optional browser time
  cap still flows from activation to session start as `available_minutes`.
  Explicit timezone fields remain accepted by the existing HTTP and bridge
  contracts for non-browser clients.
- POS-019 adds natural-language capture to Machine Interface v1 and
  `POST /v1/capture`. Both use a trusted local clock, existing explicit
  timezone configuration, shared bridge validation/serialization, and the
  canonical `CaptureService`; APPLIED, UNRESOLVED, and durable FAILED outcomes
  retain their existing semantics. The Work page sends only `raw_text`, shows
  created names or unresolved reasons, clears successful input, and
  leaves recommendation and session state untouched.
- POS-020 adds the read-only Machine Interface v1 `overview` operation and
  `GET /v1/overview`. The purpose-built contract derives active projects,
  OPEN/BLOCKED tasks, unresolved Inbox items, and the active session from one
  coherent `read_state_snapshot()` result without clock, timezone, provider,
  AI, or mutation. A dedicated compact State page at `/state` loads and
  refreshes that overview, uses safe DOM text insertion, and shares clear Work
  and State navigation without changing the POS-019 Work flow.
- POS-021 extends overview tasks with execution mode and estimated minutes,
  adds Machine Interface v1 `update_task_planning` plus loopback
  `POST /v1/task-planning` for updating only those two planning facts, and adds
  a compact State-page planning editor for OPEN/BLOCKED tasks. Capture now
  interprets execution mode without inventing durations, and Work/CLI capture
  confirmations show title, splittable vs one-sitting, supplied duration, and
  the warning when a one-sitting task still needs a duration.
- POS-022 keeps detailed capture failure information durable and available to
  internal/API consumers, while the normal browser Work capture surface displays
  a concise retry message for FAILED captures instead of raw provider exception
  bodies. UNRESOLVED results still show their human-readable reason.
- Read-only full-state CLI inspection over one validated SQLite connection and
  explicit read transaction. All seven canonical entity groups are shown in
  deterministic ID order without initialization, migration, mutation,
  timezone/provider configuration, or disclosure of interpretation/provider
  internals.
- Explicit per-boundary OpenAI/Groq provider selection for capture and
  recommendation. Both hosts use lazy OpenAI SDK Responses clients, the
  existing strict JSON schemas, provider-specific API keys, accurate provider
  metadata, and unchanged fail-closed typed validation. Groq uses its official
  OpenAI-compatible base URL by default and supports an explicit base-URL
  override.
- An explicitly gated manual live smoke script for capture or recommendation;
  it is not collected or invoked by pytest and performs no request without
  `PERSONAL_OS_LIVE_AI_SMOKE=1`.

## Not implemented

- Ollama/local inference, additional AI providers, or feedback/session AI behavior
- Calendar or Google Sheets integration
- Product CRUD commands, additional HTTP endpoints, Shortcuts, NFC, voice, or
  other UI
- Notifications, background work, deletion, import/export, or duration learning
- Routines, goals, waiting-for items, decisions, open questions, dependencies,
  preferences, or temporary context

## Validation

After POS-008, the configured real provider passed the full dogfood loop for a
schedule-less FLEXIBLE `Study for ACT` task: capture, structured state,
recommendation, session start, PROGRESS feedback, and updated durable state.
That manual run motivated POS-009's concrete action output. POS-009 validation
itself uses fake providers and makes no live request.

After POS-010, the real runtime database migrated to schema version 5 without
losing historical sessions. A real provider recommendation returned a concrete
action, its generated start command was accepted, and the exact selected action
survived the active session and PROGRESS closure. The Task remained OPEN and no
stale active session remained. POS-011 did not access that runtime database or
make a live provider request.

Run on 2026-09-16 with Python 3.12.4 and pytest 8.4.2:

- `python -m pytest` — passed: 416 passed, 0 failed.
- `python -m compileall -q src tests` — passed with exit code 0.
- `python -m personal_os --help` — passed with exit code 0.
- `personal-os --help` — passed with exit code 0.
- `python -m personal_os init-db`, using an isolated temporary
  `PERSONAL_OS_DATA_DIR` and run twice — passed at schema version 5.
- Isolated schema inspection confirmed `PRAGMA user_version = 5`, the seven
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
- POS-013 mocked adapter tests assert the NO_WORK justification and action
  grounding instructions, exercise a generic "Study for ACT" action and a valid
  NO_WORK shape, and retain fail-closed malformed-output coverage. They do not
  claim deterministic semantic verification of provider prose or make a live
  provider request.
- Session tests confirm strict v4 history, lossless v4-to-v5 migration, current
  v5 storage constraints, one-active concurrency, deterministic start rejection
  precedence, atomic feedback
  rollback, and the complete capture-to-updated-state loop without network use.
- CLI tests confirm all nine command/help paths, explicit timezone resolution,
  no product-command auto-bootstrap, advisory recommendation hints,
  service-authoritative start and feedback behavior, exact elapsed display, and
  a complete dogfood loop using real services with fake AI boundaries. No live
  OpenAI request was made.
- Bridge tests confirm strict request envelopes and per-operation fields,
  bool-as-integer rejection, trusted time and timezone handling, stable JSON
  success/error responses, typed semantic error kinds, read-only recommendation,
  service-authoritative start/feedback behavior, exact elapsed microseconds,
  no implicit database initialization, import safety, and the complete
  recommend-to-PROGRESS loop across independent invocations using canonical
  persistence. No live provider request was made.
- Activation tests confirm active-session precedence without AI or mutation,
  unchanged recommendation delegation, deterministic and ranker-generated
  NO_WORK, omitted/zero/positive caller caps, existing HARD bounds, selected
  durations distinct from caps, no cap persistence, strict bridge validation,
  trusted time, and all three activation response kinds.
- Provider tests confirm OpenAI and Groq configuration, provider-specific key
  requirements, official and overridden Groq base URLs, lazy client
  construction, structured parsing, refusals, malformed output, provider
  failures, CLI runtime wiring, durable Groq provider/model metadata, and a
  capture schema with no `anyOf` constructs. The fixed temporal provider wire
  shape preserves TODAY/TOMORROW, weekdays, next weekdays, explicit dates,
  missing-year dates, DATE deadlines, INSTANT deadlines, and strict clock
  behavior by normalizing only at the adapter boundary; malformed date/deadline
  combinations remain fail-closed invalid output. POS-023 provider tests
  confirm clocks use a literal text wire field, the schema no longer exposes
  canonical clock-kind choices, and malformed clock text fails closed while
  canonical typed parsing continues to reject invalid kind/hour/period
  combinations. The capture
  adapter narrowly maps only an APPLY wire response with
  `unresolved_reason=""` to canonical null; UNRESOLVED and all other empty text
  remain fail-closed. The project-reference wire field uses a simple
  integer/string/null type list; canonical parsing still admits only a positive
  integer, exact `NEW`, or null, and deterministic application still requires
  `NEW` to correspond to a supplied new project. Browser asset tests confirm
  FAILED captures display a concise retry message without raw failure reasons.
  No live provider request was made by automated validation.
- `git diff --check` — passed with exit code 0.

Run for POS-023 on 2026-10-06 with Python 3.13.0 and pytest 8.4.2:

- `.venv/bin/python -m pytest tests/test_openai_capture.py tests/test_capture.py -q`
  — passed: 105 passed in 1.88s.
- `.venv/bin/python -m pytest tests/test_http_api.py -q` — passed: 54 passed
  in 28.15s.
- `.venv/bin/python -m pytest` — passed: 534 passed in 46.50s.
- `.venv/bin/python -m compileall -q src tests` — passed.
- `node --check src/personal_os/static/work.js` — passed.
- `git diff --check` — passed.
- No real user data, live AI provider, calendar integration, commit, push,
  merge, or deploy was used.

Run for POS-022 on 2026-10-06 with Python 3.13.0 and pytest 8.4.2:

- `.venv/bin/python -m pytest tests/test_openai_capture.py tests/test_capture.py -q`
  — passed: 75 passed.
- `.venv/bin/python -m pytest tests/test_http_api.py::test_work_page_assets_include_capture_without_client_time_context -q`
  — passed: 1 passed.
- `.venv/bin/python -m pytest tests/test_http_api.py -q` — passed: 54 passed
  in 27.89s.
- `.venv/bin/python -m pytest` — passed: 504 passed in 46.59s.
- `.venv/bin/python -m compileall -q src tests` — passed.
- `node --check src/personal_os/static/work.js` and
  `node --check src/personal_os/static/state.js` — passed.
- `git diff --check` — passed.
- No real user data, live AI provider, calendar integration, commit, push,
  merge, or deploy was used.

Run for POS-021 on 2026-10-05 with Python 3.13.0 and pytest 8.4.2:

- `.venv/bin/python -m pytest` — passed: 493 passed, 0 failed, using isolated
  temporary databases and fake AI providers. HTTP tests required loopback bind
  permission for disposable `127.0.0.1` servers.
- `.venv/bin/python -m compileall -q src tests` — passed.
- `node --check src/personal_os/static/work.js` and
  `node --check src/personal_os/static/state.js` — passed.
- `.venv/bin/python -m personal_os --help` and `.venv/bin/personal-os --help`
  — passed.
- `git diff --check` — passed.

Run on 2026-09-21 with Python 3.13.0 and pytest 8.4.2:

- `python -m pytest` — passed: 432 passed, 0 failed, using the project virtualenv.
- `python -m compileall -q src tests` — passed with exit code 0.
- `python -m personal_os --help` and `personal-os --help` — passed.
- Editable package install and `personal-os-http --help` — passed.
- HTTP endpoint tests use a server bound to `127.0.0.1`, isolated temporary
  SQLite databases, and a fake ranker. They cover all three activation result
  kinds, read-only behavior, structured request/runtime errors, and loopback
  binding. HTTP body tests also reject transport-owned version and operation
  fields. No real user data or live AI request was used.
- `git diff --check` — passed with exit code 0.

Run for POS-015 on 2026-09-21 with Python 3.13.0 and pytest 8.4.2:

- `python -m pytest` — passed: 450 passed, 0 failed, using isolated temporary
  databases and fake AI providers.
- `python -m compileall -q src tests`, `node --check` for the browser script,
  CLI help, and `git diff --check` — passed.
- HTTP tests cover recommendation, active session, no-work, durable start with
  exact action and duration, all feedback outcomes, stale-start rejection,
  request validation, same-origin/Host protections, packaged assets, and
  loopback binding. A built wheel included all three browser assets. Browser
  smoke checks used only disposable databases and fake rankers; HTML-like task
  text remained literal with no inserted image or script elements. No real user
  data or live AI requests were used.

Run for POS-018 on 2026-09-23 with Python 3.13.0 and pytest 8.4.2:

- `.venv/bin/python -m pytest` — passed: 452 passed, 0 failed, using isolated
  temporary databases and fake AI providers.
- `.venv/bin/python -m pytest tests/test_http_api.py` — passed: 36 passed,
  0 failed. The first sandboxed attempt could not bind the loopback test
  server (`PermissionError: [Errno 1] Operation not permitted`); rerunning with
  local loopback bind permission passed.
- `.venv/bin/python -m compileall -q src tests` — passed with exit code 0.
- `node --check src/personal_os/static/work.js` — passed with exit code 0.
- HTTP/browser tests confirm packaged Work assets have no timezone input or
  timezone-sending JavaScript, activation and start requests can omit timezone
  when `PERSONAL_OS_TIMEZONE` is configured, and the time cap still propagates
  to session start as `available_minutes`. No real user data or live AI
  requests were used.

Run for POS-019 on 2026-09-28 with Python 3.13.0 and pytest 8.4.2:

- `.venv/bin/python -m pytest` — passed: 467 passed, 0 failed, using isolated
  temporary databases and fake AI providers.
- `.venv/bin/python -m pytest tests/test_http_api.py -q` — passed: 43 passed,
  0 failed with local loopback bind permission. The initial sandboxed run was
  blocked from binding `127.0.0.1` with `PermissionError: [Errno 1] Operation
  not permitted`.
- `.venv/bin/python -m compileall -q src tests` — passed with exit code 0.
- `node --check src/personal_os/static/work.js` — passed with exit code 0.
- `git diff --check` — passed with exit code 0.
- Capture tests cover strict pre-runtime request validation, trusted clock and
  configured-timezone use, APPLIED/UNRESOLVED/FAILED response shapes, linked
  inbox persistence, loopback HTTP protections, and browser omission of
  timezone/reference timestamps. Existing activation, start, active-session,
  and all feedback outcomes remain covered. No real user data or live AI
  requests were used.

Run for POS-020 on 2026-10-01 with Python 3.13.0 and pytest 8.4.2:

- `.venv/bin/python -m pytest` — passed: 476 passed, 0 failed, using isolated
  temporary databases and fake AI boundaries.
- `.venv/bin/python -m pytest tests/test_bridge.py tests/test_http_api.py -q`
  — passed: 142 passed, 0 failed with local loopback bind permission.
- `.venv/bin/python -m compileall -q src tests` — passed with exit code 0.
- `node --check src/personal_os/static/work.js` and
  `node --check src/personal_os/static/state.js` — passed with exit code 0.
- `git diff --check` — passed with exit code 0.
- Overview tests confirm strict pre-runtime validation, one coherent snapshot
  read, current-state filtering and joins, active-session/null serialization,
  no clock/timezone/provider/AI requirement, normal GET response envelopes,
  Host and method protections, packaged State assets, and safe DOM text
  rendering. Existing capture and Work-loop coverage remains green. No real
  user data or live AI requests were used.
