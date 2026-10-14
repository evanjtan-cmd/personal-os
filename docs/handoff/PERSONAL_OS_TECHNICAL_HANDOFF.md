# Personal OS Technical Handoff

Audit date: 2026-10-13 (America/New_York)

Repository: `personal-os`

Audited checkout: `main` at `11707a13cd5e642c715ab464353d1c4cfbf79e0f`

## 1. Purpose and audit boundary

This document is an evidence-based reference for the implementation present in
the audited local checkout, plus clearly labeled historical operational evidence
needed to resume the project. It is not a product narrative or a substitute for
the architectural decision log.

The audit inspected:

- `AGENTS.md`, `PROJECT_CONTEXT.md`, `docs/MVP_SPEC.md`, `BUILD_STATE.md`,
  `DECISIONS.md`, `README.md`, and `pyproject.toml`;
- every tracked source, browser asset, test, and script;
- the current Git branch, local remote-tracking refs, named branches, recent
  history, and working-tree state;
- the SQLite DDL and migrations, typed models, state store, application
  services, adapters, browser flows, and test coverage;
- documented setup and validation procedures;
- accessible Personal OS build, Shortcut, deployment, and migration
  conversations, including the dated POS-026 live-acceptance transcript.

No personal runtime directory, live database, API secret, provider account,
deployed process, current iPhone Shortcut definition, NFC tag, calendar, Google
Sheet, or remote host was directly inspected by this technical audit. No
`git fetch` was performed. Therefore references to `origin/main` below mean the
locally stored remote-tracking ref, not an independent assertion about GitHub at
audit time.

Accessible conversations nevertheless contain dated, user-provided command
output from the Home Mac and phone acceptance work. Those records are included
as **historical operational evidence**, not presented as a fresh inspection or
a guarantee that the external systems remained unchanged. “Not tracked in this
repository,” “not directly inspected now,” and “never implemented” are distinct
claims throughout this handoff.

## 2. Evidence classes and source-of-truth boundaries

Do not use one hierarchy for every kind of claim.

For **implemented behavior in this checkout**:

1. Current code, migrations, and tests define what is implemented.
2. `docs/MVP_SPEC.md` defines constraints implementation tickets must preserve,
   including requirements that are not yet implemented.
3. `BUILD_STATE.md` is the intended implementation ledger and dated validation
   record. It has one known post-POS-026 live-acceptance omission described
   below.
4. `DECISIONS.md` records enduring architectural rationale.
5. `PROJECT_CONTEXT.md` defines product direction and success criteria.
6. `README.md` is operator convenience. It is currently incomplete for the
   full bridge/HTTP surface and stale about browser timezone behavior.
7. `AGENTS.md` is mandatory repository-working guidance.

For **roadmap and continuation**, use the latest explicitly approved product
ticket or explicit stop decision. POS-026 is complete; no POS-027 is approved.
The current direction is normal dogfooding until real use supplies evidence for
the next bounded ticket. Audit recommendations are not roadmap approval.

For **deployed state**, use dated direct host/runtime evidence. A checkout
cannot prove deployment. The last accessible evidence is the 2026-10-13
POS-026 deployment and acceptance transcript summarized in section 12; it was
not freshly re-executed by this audit.

For **external integrations**, distinguish absence from Git from absence in the
project. The Shortcut, SSH/Tailscale path, laptop Automator launcher, launchd
job, and runtime scripts are external artifacts with their own verification
dates.

The Google Sheet named in `PROJECT_CONTEXT.md` is prototype/reference data, not
the persistence or architectural source of truth.

## 3. Audited Git and package state

### Git snapshot

- Branch: `main`.
- HEAD: `11707a1`, merge of POS-026, “Capture Reliability & Project Intake.”
- Upstream as locally recorded: `origin/main` at the same commit (`+0/-0`).
- Working tree at audit start: clean.
- Diff from locally recorded `origin/main`: none.
- Named local or remote-tracking branches not merged into `main`: none reported
  by `git branch --no-merged main` or `git branch -r --no-merged main`.
- Tags: none.
- Several old local feature branches remain; several display a gone upstream.
  They point to work already merged into `main`, not verified unmerged work.
- The only intended working-tree changes produced by the handoff and its
  adversarial review are four uncommitted Markdown files under `docs/handoff/`.
  No application code, configuration, or tests were changed.

Recent mainline work, newest first:

- POS-026: project deadlines, standalone-project capture, missing-year dates,
  and one structured-output retry.
- POS-025: state history, commitment lifecycle/protection, and Task reopen.
- POS-024: state triage, narrow Task corrections, and Inbox maintenance.
- POS-023/POS-022: clock and temporal capture hardening.
- POS-021: SPLITTABLE/ONE_SITTING workability semantics.
- POS-020/POS-019/POS-015/POS-014: State UI, browser capture, browser Work UI,
  and loopback HTTP transport.

### Exact continuation point

POS-026 is the latest merged engineering phase. There is no approved POS-027.
The explicit project direction after live acceptance was to stop building and
dogfood the existing loop:

```text
Capture -> State -> Recommend -> Start -> Finished / Progress / Blocked
```

Open a new bounded ticket only when meaningful real-use friction supplies its
objective and acceptance criteria. The maintenance findings in the open-issues
document are candidates, not an approved immediate sequence.

### Package and dependency snapshot

- Package: `personal-os`, version `0.1.0`.
- Layout: Python `src/` package.
- Python requirement: 3.12 or newer.
- Runtime dependency: `openai>=3.6,<4`.
- Development dependency: `pytest>=8,<9`.
- Audited virtual environment: Python 3.13.0, OpenAI SDK 3.8.0, pytest 8.4.2.
- Console scripts:
  - `personal-os` -> `personal_os.cli:main`
  - `personal-os-bridge` -> `personal_os.bridge:main`
  - `personal-os-http` -> `personal_os.http_api:main`
- There is no dependency lockfile, CI workflow, formatter/linter/type-checker
  configuration, container definition, or release/deployment manifest in the
  repository.

## 4. Architecture

Personal OS is a local, single-user Python application. The implemented loop is:

```text
human/browser/machine input
        |
        v
thin adapters: CLI | JSON bridge | loopback HTTP + static browser UI
        |
        v
shared application services
  CaptureService
  RecommendationService
  WorkActivationService
  SessionService
        |
        +---- deterministic policy (capture time resolution,
        |     eligibility, availability, durations, transitions)
        |
        +---- constrained AI boundaries (capture interpretation,
        |     recommendation ranking/action wording)
        |
        v
SQLiteStateStore -> explicitly initialized SQLite schema v9
```

`personal_os.runtime.build_runtime()` wires one `SQLiteStateStore` to the
capture, recommendation, session, and activation services. Construction is
side-effect-free: the database and provider clients are opened lazily. Adapters
delegate to these services and must not duplicate policy.

### Responsibility boundaries

| Component | Responsibility | Must not own |
| --- | --- | --- |
| Models/types | Frozen typed records, enums, validation, serialization | I/O or provider calls |
| Database module | Exact DDL, ordered migrations, schema validation | Product workflows |
| State store | Typed SQLite reads/writes and transaction boundaries | AI interpretation/ranking |
| Capture service | Persist-first capture orchestration and deterministic resolution/application | Provider-specific protocol details |
| Eligibility/recommendation | Deterministic candidate/availability/duration policy and constrained ranking handoff | State mutation |
| Session service | Authoritative start/close validation and lifecycle | Recommendation acceptance before start |
| Activation service | Return active work or request a recommendation | Starting a session |
| AI adapters | Strict Responses request/response conversion | Inventing or persisting hard facts |
| CLI/bridge/HTTP/UI | Parsing, configuration, serialization, display, transport | Domain policy |

## 5. Repository map and entry points

### Project documents and packaging

| Path | Role |
| --- | --- |
| `AGENTS.md` | Mandatory change discipline and safety boundaries |
| `PROJECT_CONTEXT.md` | Product definition, future state model, MVP success condition |
| `docs/MVP_SPEC.md` | Executable product and architecture constraints |
| `BUILD_STATE.md` | Implemented/not-implemented ledger and historical validation |
| `DECISIONS.md` | Enduring architecture decisions |
| `README.md` | Setup and dogfood quick start; partly stale for newer interfaces |
| `pyproject.toml` | Build metadata, dependencies, package data, entry points, pytest config |
| `.gitignore` | Excludes secrets, runtime DBs/logs, caches, virtualenvs, and build output |

### Application code

| Path | Role |
| --- | --- |
| `src/personal_os/__main__.py` | `python -m personal_os` entry point |
| `config.py` | Runtime data path and explicit IANA timezone resolution |
| `database.py` | Schema version 9, migrations 1-9, exact schema validation |
| `models.py` | Projects, Tasks, commitments, Rules, Inbox, Captures, canonical values |
| `state.py` | SQLite store, snapshots, atomic capture/session/maintenance writes |
| `capture_types.py` | Version-1 provider-independent capture semantic contract |
| `capture.py` | Capture workflow and deterministic date/time resolution |
| `eligibility.py` | Pure Task eligibility, deadline state, and availability |
| `recommendation_types.py` | Recommendation contexts, candidates, results, and errors |
| `recommendation.py` | Duration policy, deterministic filtering/gating/bounding, output validation |
| `session_types.py` | Work-session model and lifecycle error kinds |
| `session.py` | Authoritative start/feedback service |
| `activation_types.py`, `activation.py` | Availability-now operation |
| `ai_provider.py` | Explicit OpenAI/Groq configuration and lazy client construction |
| `openai_capture.py` | Strict Responses capture adapter and narrow retry |
| `openai_recommendation.py` | Strict Responses ranking adapter |
| `runtime.py` | Shared service wiring for adapters |
| `cli.py` | Human dogfood CLI |
| `bridge.py` | Stable one-request-per-process Machine Interface v1 |
| `http_api.py` | Loopback HTTP/static-file adapter |
| `static/work.*` | Capture/recommend/start/feedback browser UI |
| `static/state.*` | Overview, triage, history, and narrow correction UI |
| `scripts/live_ai_smoke.py` | Explicitly opt-in live provider smoke checks; recommend path is currently stale |

### Tests

The 16 `tests/test_*.py` modules cover models, configuration, migrations,
state operations, capture, provider adapters, eligibility, recommendation,
sessions, activation, CLI, bridge, HTTP/browser assets, and import safety.
Tests use temporary SQLite databases and fake provider clients/rankers. HTTP
tests bind disposable loopback ports. Pytest does not run the live AI smoke
script.

## 6. Persistence and canonical data model

### Database boundary

- Backend: standard-library `sqlite3`; no ORM.
- Default path: `~/.personal-os/personal_os.db`.
- Override: `PERSONAL_OS_DATA_DIR`; the filename remains `personal_os.db`.
- Initialization/migration is explicit via `personal-os init-db` only.
- Product operations require an existing database at exactly schema version 9.
- Every connection enables and verifies foreign-key enforcement.
- Every state operation validates exact table DDL and expected foreign keys.
- Writes use `BEGIN IMMEDIATE`; multi-record workflows roll back atomically.
- Coherent state and recommendation reads use one connection and explicit read
  transaction.
- Instants are fixed-width UTC strings: `YYYY-MM-DDTHH:MM:SS.ffffffZ`.
- Date-only facts are ISO `YYYY-MM-DD` and are not converted to instants.
- Rule parameters are canonical JSON-object text with sorted keys.
- There are no physical-delete application operations.

### Schema evolution

| Version | Change |
| --- | --- |
| 1 | Infrastructure-only; no domain tables |
| 2 | Projects, Tasks, fixed commitments, Rules, Inbox |
| 3 | Captures and `source_capture_id` traceability |
| 4 | Sessions and DB-enforced single-active-session slot |
| 5 | Durable accepted `selected_action` on Sessions |
| 6 | Task `execution_mode` |
| 7 | Task `CANCELLED` status |
| 8 | Fixed-commitment `SCHEDULED`/`CANCELLED` status |
| 9 | Project date-only/exact deadlines |

Migrations are ordered, transactional, and validated at each step. Versions 7
and 9 rebuild referenced tables and surround that work with foreign-key checks.
Existing Task behavior migrates to SPLITTABLE, existing commitments to
SCHEDULED, and existing Projects to no deadline.

### Canonical records and invariants

#### Project

- Fields: integer ID, name, optional description, ACTIVE/COMPLETED status,
  timestamps, optional source capture, optional date-only or exact deadline.
- Deadline representations are mutually exclusive.
- A Project is a planning container, never an executable recommendation.
- Project deadlines are not inherited by Tasks and do not make a Project
  eligible or cause automatic decomposition.

#### Task

- Status: OPEN, BLOCKED, COMPLETED, or CANCELLED.
- Importance: UNSPECIFIED, MUST, SHOULD, or COULD. Missing importance is not
  silently promoted to SHOULD.
- Schedule:
  - FLEXIBLE: no day/window fields;
  - DAY: one calendar date, no clock;
  - WINDOW: timezone-resolved half-open UTC interval `[start, end)`.
- Deadline: either a date or exact UTC instant, independent of schedule.
- Execution: SPLITTABLE or ONE_SITTING.
- Estimate: optional positive integer minutes.
- Optional Project and source-Capture foreign keys use `ON DELETE RESTRICT`.
- CANCELLED is historical removal, not completion or deletion, and is never
  recommendation-eligible.

#### Fixed commitment

- Required title/start; optional end; start must precede a known end.
- Hardness: UNKNOWN (default), HARD, or SOFT.
- Lifecycle: SCHEDULED or CANCELLED. There is no stored COMPLETED state.
- FUTURE/ACTIVE/PAST display is derived from trusted current time.
- Only SCHEDULED HARD commitments affect availability. A cancelled commitment
  never constrains work.

#### Rule

- Non-empty kind, canonical JSON-object parameters, enabled boolean.
- Rules are persisted and displayed but no rule-kind taxonomy or evaluation
  engine is implemented.

#### Inbox item

- Preserves raw unresolved text, reason, timestamps, and optional source
  Capture.
- `resolved_at = NULL` is the sole unresolved marker.
- Resolution is one-way and idempotent through the general store operation.
- Replacement capture resolves the old Inbox row only when the replacement
  finalizes APPLIED or UNRESOLVED; FAILED preserves the original unresolved row.

#### Capture

- Status: RECEIVED, APPLIED, UNRESOLVED, or FAILED.
- Raw input, trusted reference time, and timezone are committed before provider
  inference.
- Final Captures may retain versioned interpretation JSON, actual provider,
  model, response ID, unresolved reason, or classified failure details.
- Failure kinds: CONFIGURATION_ERROR, PROVIDER_ERROR, REFUSAL, INVALID_OUTPUT.
- APPLIED/UNRESOLVED/FAILED finalization is one-way.
- Derived Projects, Tasks, commitments, and Inbox items retain immutable source
  traceability.

#### Session

- References one Task and stores planned minutes, exact start/end instants,
  outcome, optional accepted action, optional start reason, and result note.
- Outcome: FINISHED, PROGRESS, or BLOCKED.
- A nullable unique `active_slot` permits any number of closed Sessions but at
  most one active Session, including under concurrent starts.
- Actual duration is derived exactly as `ended_at - started_at`; it is not
  rounded or redundantly stored, and zero duration is valid.
- Closed Sessions are immutable through the implemented API.

## 7. Capture workflow

1. Validate non-empty raw text, a timezone-aware reference instant, and an
   explicit IANA timezone.
2. Persist one RECEIVED Capture before provider configuration or inference.
3. Read all Projects and supply at most 50 ACTIVE Projects to the interpreter,
   newest `updated_at`/ID first, as ID/name pairs only.
4. Ask the configured provider for strict schema output.
5. Normalize the provider wire form to the provider-independent typed semantic
   contract.
6. Resolve temporal meaning deterministically using the stored reference time
   and timezone.
7. Atomically finalize the Capture and create either:
   - a Project, Tasks, and/or fixed commitments (APPLIED); or
   - exactly one Inbox item (UNRESOLVED).
8. Classified provider/configuration/refusal/output failures finalize FAILED
   without creating Inbox or derived state.

Important semantics:

- Schedule-less actionable input becomes a FLEXIBLE Task.
- Missing optional schedule, deadline, importance, estimate, or Project is not
  uncertainty.
- TODAY, TOMORROW, weekday, next weekday, full ISO date, supported English
  month/day without year, and THIS_WEEKEND are implemented.
- A month/day without a year resolves to the first valid occurrence on or after
  the trusted local date.
- Multi-date DAY Tasks expand to independently completable, deduplicated rows.
- Exact local times are converted to UTC only if they exist and are unambiguous
  in the supplied zone. DST gaps/folds become UNRESOLVED.
- Bare `3` or `3:45` is unresolved; AM/PM and unambiguous 24-hour forms resolve.
  Zero-padded `03:45` is treated as 24-hour 03:45.
- A fixed commitment resolving into the past is UNRESOLVED; a past deadline is
  a valid stored fact.
- Captured commitments contain a start but no end. The user can later classify
  work protection with an explicit duration or no reservation.
- One capture may create one new Project, zero or more Tasks, and zero or more
  commitments. A standalone Project is valid; a fake Task is not required.
- New Project names collide case-insensitively with any existing Project and
  route to UNRESOLVED. This is capture policy, not a database unique constraint.

Provider retry is narrow: capture performs one retry only for a provider
`json_validate_failed` or a typed structured-output contract violation. It does
not retry configuration/authentication, generic provider failure, refusal,
deterministic application errors, or persistence errors. A persistence error
propagates; an unexpected internal error can leave the already durable Capture
in RECEIVED for diagnosis.

## 8. Eligibility, availability, recommendation, and activation

### Eligibility

- Only OPEN Tasks can be eligible.
- Tasks under COMPLETED Projects are ineligible.
- FLEXIBLE Tasks are eligible.
- Future DAY Tasks are ineligible; today's and missed DAY Tasks are eligible,
  with missed days supplied as ranking metadata.
- WINDOW Tasks are eligible only while `start <= now < end`.
- Deadlines affect ranking state (NONE/FUTURE/DUE_TODAY/OVERDUE), not
  eligibility or calendar occupancy.

### Availability

- Only SCHEDULED HARD commitments constrain work.
- An active bounded HARD commitment returns deterministic no-work.
- An active open-ended HARD commitment returns a distinct deterministic
  no-work reason.
- The earliest future HARD start and optional caller availability/time cap form
  the finite bound. Availability is floored to whole minutes.
- SOFT, UNKNOWN, past, and CANCELLED commitments do not constrain work and are
  not sent to the ranker.
- Missing caller availability means unknown, not unlimited.

### Duration and candidate policy

- SPLITTABLE ladder: 5, 10, 15, 20, 25, 30, 35, 45, 60 minutes.
- Explicit 1-4 minute estimates are allowed exactly when they fit.
- An estimate bounds a SPLITTABLE session; non-ladder estimates of at least five
  minutes can also be included exactly.
- With no known hard bound, SPLITTABLE recommendations cap at 30 minutes.
- ONE_SITTING requires a known estimate and known sufficient availability. Its
  sole valid duration is the entire estimate, even above 60 minutes.
- Duration-feasible MUST Tasks gate out all lower importance candidates.
- Candidates are deterministically urgency-sorted and bounded to 50 before AI.
- The AI can select only a supplied Task and one of its allowed durations.
- AI NO_WORK is invalid while MUST gating is active. Otherwise it is allowed,
  subject to prompt instructions; the prose rationale is not semantically
  proved by deterministic code.

Recommendation is read-only and ephemeral. It does not mark acceptance or
persist generated action text. A chosen action becomes durable only when the
caller starts a Session and supplies that exact text.

Activation is the canonical “I am available now” operation. It first returns
the active Session and Task without requiring timezone or invoking AI. If no
Session is active, it delegates to recommendation. It never starts work.

## 9. Session workflow

Starting a Session uses a fresh trusted time and revalidates inside the same
immediate transaction that inserts the active row. Rejection order is:

1. selected Task is not OPEN;
2. parent Project is COMPLETED;
3. Task schedule is ineligible;
4. a HARD commitment is active;
5. requested duration is not currently allowed;
6. a feasible MUST Task requires selection.

Ranking order and the 50-candidate bound do not restrict a manual start. A start
does not create a timer, background worker, Focus mode, or notification.

Feedback always targets the one active Session:

- FINISHED closes the Session and sets the Task COMPLETED.
- PROGRESS closes the Session and leaves the Task OPEN without touching the
  Task update timestamp.
- BLOCKED closes the Session and sets the Task BLOCKED.

Session close and Task transition are atomic. An already matching final Task
state is accepted for FINISHED/BLOCKED; a conflicting intervening Task state is
not overwritten. Result notes are uninterpreted history. There is no feedback
AI, automatic next-action generation, Project mutation, or duration learning.

## 10. User-facing and machine interfaces

### Human CLI

The CLI is a dogfood interface, not a machine contract:

```text
personal-os init-db
personal-os capture TEXT [--timezone ZONE]
personal-os recommend [--available-minutes N] [--timezone ZONE]
personal-os start TASK_ID MINUTES [--available-minutes N] [--action TEXT] [--reason TEXT] [--timezone ZONE]
personal-os finish [--note TEXT]
personal-os progress [--note TEXT]
personal-os block [--note TEXT]
personal-os active
personal-os state
```

Only `init-db` initializes or migrates. Capture, recommendation, and start need
an explicit command timezone or `PERSONAL_OS_TIMEZONE`. `active`, feedback, and
`state` do not need provider configuration. `state` reads all seven tables in
one coherent snapshot and intentionally omits interpretation JSON/provider
internals. Its output is human-readable and must not be scraped.

### Machine Interface v1

`personal-os-bridge` reads exactly one JSON value from stdin, requires a strict
object with integer `version: 1`, writes exactly one compact JSON envelope, and
exits. Requests cannot supply current/reference time.

Implemented operations:

| Operation | Request-specific fields | Notes |
| --- | --- | --- |
| `capture` | required `raw_text`; optional `timezone` | Durable APPLIED/UNRESOLVED/FAILED result |
| `resolve_inbox` | required `inbox_item_id`, `raw_text`; optional `timezone` | New canonical capture; atomic supersession on APPLIED/UNRESOLVED |
| `dismiss_inbox` | required `inbox_item_id` | Resolves only; no AI |
| `recommend` | optional `available_minutes`, `timezone` | Read-only |
| `activate` | optional `time_cap_minutes`, `timezone` | Active Session wins; otherwise recommend |
| `start` | required `task_id`, `planned_minutes`; optional `available_minutes`, `timezone`, `selected_action`, `start_reason` | Fresh authoritative validation |
| `feedback` | required `outcome`; optional `result_note` | Targets active Session |
| `active` | no extra fields | Active Session inspection |
| `overview` | no extra fields | Purpose-built current state/history read model |
| `update_task_planning` | required `task_id`, `execution_mode`, nullable `estimated_minutes` | Narrow planning correction |
| `correct_task_status` | required `task_id`, target `status` | Target OPEN/COMPLETED/CANCELLED; store enforces valid transition |
| `configure_commitment_protection` | required `commitment_id`, nullable `duration_minutes` | Positive duration -> HARD bounded end; null -> SOFT |
| `cancel_commitment` | required `commitment_id` | Historical cancellation |

Success envelope:

```json
{"version":1,"ok":true,"operation":"...","result":{}}
```

Error envelope:

```json
{"version":1,"ok":false,"operation":"...","error":{"code":"...","message":"...","kind":null}}
```

Exit status 2 means protocol validation failure; status 1 means an expected
operational error; status 0 includes durable capture FAILED outcomes because
the request itself completed successfully. Unexpected programming errors are
not flattened into expected protocol errors.

`overview` is deliberately not a full dump. It returns ACTIVE Projects,
OPEN/BLOCKED Tasks, unresolved Inbox, future/active SCHEDULED commitments,
active Session, and at most 20 recent closed Tasks and 20 past/cancelled
commitments. Commitment temporal labels use the bridge/server clock. It excludes
Rules, capture history/metadata, closed Sessions, and secrets.

### Loopback HTTP API

`personal-os-http` uses `ThreadingHTTPServer`, binds only to `127.0.0.1`, and
defaults to port 8765. It injects bridge version/operation fields and reuses
bridge validation, result shapes, and application services.

| Method/path | Purpose |
| --- | --- |
| `POST /v1/capture` | Capture text |
| `POST /v1/resolve-inbox` | Replace unresolved text |
| `POST /v1/dismiss-inbox` | Dismiss Inbox item |
| `POST /v1/activate` | Active work or recommendation |
| `POST /v1/start` | Start Session |
| `POST /v1/feedback` | Close active Session |
| `POST /v1/task-planning` | Correct execution mode/estimate |
| `POST /v1/task-status` | Narrow lifecycle correction |
| `POST /v1/commitment-protection` | Set bounded HARD or SOFT protection |
| `POST /v1/cancel-commitment` | Cancel commitment |
| `GET /v1/overview` | Current overview/history |
| `GET /`, `/state`, `/work.js`, `/state.js`, `/work.css` | Fixed packaged UI assets |

There is no HTTP `recommend` or `active` route; browser work uses `activate`.
Bodies may not supply transport-owned `version` or `operation`. JSON POST bodies
must be 1-65,536 bytes with `application/json`. The exact loopback Host header
is required. Cross-origin browser POSTs are rejected using Origin and
`Sec-Fetch-Site`. Static and JSON responses use `no-store`, nosniff, and a
restrictive Content Security Policy. There is no CORS or authentication;
loopback and same-origin constraints are the intended boundary. Protocol errors
map to HTTP 400, expected runtime errors to HTTP 500.

### Browser UI

The framework-free Work page supports:

- natural-language capture;
- concise APPLIED/UNRESOLVED/FAILED results;
- inline correction or dismissal of unresolved Inbox items;
- setting a missing ONE_SITTING duration;
- optional time cap, activation, recommendation display, and exact accepted
  action/duration start;
- FINISHED/PROGRESS/BLOCKED feedback;
- explicit “Find next work” after closure.

It deliberately sends no browser-derived timezone; the HTTP process must have
`PERSONAL_OS_TIMEZONE` unless a non-browser API caller supplies one.

The State page loads `overview` and renders Needs input, active Session,
upcoming commitments, active Tasks, active Projects, and bounded history. It
also invokes the narrow Inbox, planning, Task-status, commitment-protection,
commitment-cancellation, and reopen operations. The overview GET is read-only;
the current State page as a whole is not read-only. Both scripts construct DOM
nodes with `textContent` rather than interpreting stored text as HTML.

### iPhone Shortcut and other external interfaces

No Shortcut file, NFC action, voice adapter, Google Calendar adapter, or Google
Sheets adapter is tracked in the repository. That does not mean every external
interface was never built.

Accessible POS-012/POS-013 acceptance history records an external iPhone Work
Shortcut using SSH to invoke `personal-os-bridge`. It was verified across:

- `activate` returning `RECOMMEND`, `ACTIVE_SESSION`, and `NO_WORK`;
- `start` preserving the selected action and planned duration;
- `feedback` with `PROGRESS` closing the Session while leaving the Task OPEN;
- active-session precedence on the next activation.

The Shortcut was deliberately changed to call canonical `activate`, not to ask
for minutes and not to manually chain `active` followed by `recommend`.
Shortcuts parsing was a separate source of failures: the response path is
`result.kind`, and `RECOMMEND` and `ACTIVE_SESSION` use different result field
names. Those UI problems were isolated from the working backend rather than
patched in application code.

The current Shortcut definition/export was not available to this audit, and
the phone flow was not revalidated after POS-026. Its status is therefore:

- repository artifact: absent;
- historical functional acceptance: present;
- current exported definition and freshness: unverified.

No verified NFC, Action Button, or voice trigger artifact was recovered.
Calendar entries do not automatically populate fixed commitments; current
commitments must come from capture/internal APIs. The Google Sheet remains
prototype/reference data only.

## 11. AI integration and configuration boundaries

Capture and recommendation configure provider/model independently:

| Purpose | Provider variable | Model variable |
| --- | --- | --- |
| Capture | `PERSONAL_OS_CAPTURE_PROVIDER` | `PERSONAL_OS_CAPTURE_MODEL` |
| Recommendation | `PERSONAL_OS_RECOMMEND_PROVIDER` | `PERSONAL_OS_RECOMMEND_MODEL` |

Supported providers are `openai` and `groq`. OpenAI uses `OPENAI_API_KEY`.
Groq uses `GROQ_API_KEY` and defaults to
`https://api.groq.com/openai/v1`, overrideable by
`PERSONAL_OS_GROQ_BASE_URL`. There is no provider/model default or cross-boundary
fallback. No `.env` loader is implemented. Client construction and network
access are lazy.

Both adapters use the OpenAI Python SDK Responses API, strict JSON-schema
output, and `store=False`.

- Capture AI receives raw text plus bounded ACTIVE Project ID/name context. It
  does not receive reference time/timezone and cannot authoritatively resolve
  dates or local instants.
- Recommendation AI receives derived availability plus bounded candidate facts
  and allowed durations. It does not receive the raw clock, timezone,
  commitments, Rules, or mutation access.
- Application code fail-closes malformed/refused/provider output and validates
  selected Task/duration exactly.
- Action grounding and non-MUST NO_WORK coherence rely partly on provider
  instructions; they are not fully semantically machine-verified.

Automated tests use fake clients and do not certify current provider
availability, quota, model support, latency, or hosted behavior. Live checks are
billable and require `PERSONAL_OS_LIVE_AI_SMOKE=1`; the recommendation live-smoke
path currently has a verified constructor mismatch and should not be treated as
working until corrected and covered.

## 12. Development, validation, and runtime procedures

### Local setup

```bash
python -m venv .venv
source .venv/bin/activate
python -m pip install -e ".[dev]"
```

Configure only the provider boundary being exercised. Keep secrets and runtime
data outside Git. The repository's `.gitignore` covers common DB, log, secret,
environment, virtualenv, cache, and build artifacts, but this is not a reason to
place them in the repository.

### Isolated database initialization

Never validate against the user's default runtime. Use an explicit disposable
directory:

```bash
audit_data_dir="$(mktemp -d)"
PERSONAL_OS_DATA_DIR="$audit_data_dir" .venv/bin/personal-os init-db
```

Product commands do not auto-create, migrate, or repair the database.

### Verified validation commands

On 2026-10-13 the audit ran:

```bash
.venv/bin/python -m pytest
.venv/bin/python -m compileall -q src tests
node --check src/personal_os/static/work.js
node --check src/personal_os/static/state.js
.venv/bin/python -m personal_os --help
.venv/bin/personal-os --help
.venv/bin/personal-os-http --help
git diff --check
```

Result: 635 tests passed in 57.46 seconds with Python 3.13.0 and pytest 8.4.2;
the remaining commands passed. The first restricted-sandbox pytest run could
not bind disposable loopback ports and ended with 562 passes plus HTTP bind
errors. The same complete suite passed when loopback binding was allowed. No
live AI request or personal runtime database was used.

`BUILD_STATE.md` records the same 635-test count on 2026-10-12 and additional
historical validation. The current audit independently confirmed it.

### Repository-documented runtime operation

The repository itself documents only the manual path:

```bash
personal-os init-db
personal-os-http --port 8765
```

Then open `http://127.0.0.1:8765/`. No process supervisor, auto-start
definition, environment-secret loader, reverse proxy, remote-access
configuration, backup/restore runbook, or rollback procedure is tracked in Git.

### External deployed topology

Accessible project history records a more complete deployment outside the
repository:

```text
iPhone Work Shortcut
    -> SSH to Home Mac
    -> external runtime environment
    -> personal-os-bridge

Laptop /Applications/personal-os.app
    -> establish or reuse SSH/Tailscale local forwarding
    -> open http://127.0.0.1:8765/
    -> Home-Mac loopback personal-os-http

Home Mac
    -> ~/Documents/GitHub/personal-os
    -> launchd label com.evan.personal-os.http
    -> ~/.personal-os/bin/start-http.sh
    -> ~/.personal-os/personal_os.db
    -> ~/.personal-os/backups/
    -> ~/.personal-os/logs/http.out.log and http.err.log
```

The maintenance SSH alias is `personal-os-home`. Tailscale reachability is a
prerequisite. The HTTP process remains bound to loopback; the trusted tunnel is
the remote-access boundary. Do not bind the unauthenticated HTTP server to a
LAN or public address to simplify access.

Earlier Shortcut acceptance used a separate installed bridge runtime under
`~/.personal-os/runtime/venv` and sourced `~/.personal-os/runtime/env`. Those
paths are historical evidence, not a freshly verified current install.

### Last known live state

The `Remote project work` conversation contains user-provided command output
from 2026-10-13 showing:

- the Home-Mac checkout fast-forwarded from POS-025 to `11707a1`;
- the live database migrated from schema 8 to schema 9;
- `PRAGMA foreign_key_check` reported no rows;
- a timestamped pre-POS-026 database backup was created;
- launchd returned the HTTP service to running state;
- `GET /state` returned HTTP 200;
- the exact motivating capture,
  `project: chinese culture presentation - due oct 22`, returned `APPLIED`,
  created one Project with deadline `2026-10-22`, and created no fake Task.

This is strong dated operational evidence, not a fresh inspection performed by
this audit. Before any runtime-affecting work, repeat a read-only preflight.
Do not copy live database contents, environment values, logs, keys, or secrets
into Git or the handoff.

### Practiced deployment and migration procedure

Successful schema-changing releases used the following sequence:

1. verify the merge and sync the laptop;
2. SSH to the Home Mac with forwarding disabled for the maintenance shell;
3. inspect Git status/commit, schema version, FK integrity, service state, and
   database presence;
4. stop the launchd service;
5. create a timestamped database backup;
6. fast-forward the Home-Mac checkout from `origin/main`;
7. run explicit `personal-os init-db` migration;
8. verify the new schema and `PRAGMA foreign_key_check`;
9. restart/bootstrap launchd and verify HTTP 200;
10. run the exact live acceptance case that motivated the ticket.

The corresponding historical command shape was:

```bash
ssh -o ClearAllForwardings=yes personal-os-home
cd ~/Documents/GitHub/personal-os
git status --short --branch
git log -1 --oneline
sqlite3 ~/.personal-os/personal_os.db "PRAGMA user_version;"
sqlite3 ~/.personal-os/personal_os.db "PRAGMA foreign_key_check;"
launchctl print gui/$(id -u)/com.evan.personal-os.http \
  | grep -E 'state =|pid =|last exit code|program =|path ='

stamp=$(date +%Y%m%d-%H%M%S)
mkdir -p ~/.personal-os/backups
launchctl bootout gui/$(id -u)/com.evan.personal-os.http
cp -p ~/.personal-os/personal_os.db \
  ~/.personal-os/backups/personal_os-pre-upgrade-$stamp.db
git pull --ff-only origin main
.venv/bin/personal-os init-db
sqlite3 ~/.personal-os/personal_os.db "PRAGMA user_version;"
sqlite3 ~/.personal-os/personal_os.db "PRAGMA foreign_key_check;"
launchctl bootstrap gui/$(id -u) \
  ~/Library/LaunchAgents/com.evan.personal-os.http.plist
sleep 3
curl -sS -o /dev/null -w '%{http_code}\n' \
  http://127.0.0.1:8765/state
```

Confirm current paths and obtain explicit authorization before using that
procedure. Stop on unexpected output. Backup creation is evidenced; successful
restore, downgrade, and rollback are not.

The principal observed infrastructure failure was the Home Mac falling offline
from Tailscale, which made SSH, browser, and Shortcut access unavailable. The
explicit rule was not to start using a separate laptop database as a workaround,
because that would create conflicting authoritative states.

## 13. Implemented versus partial or absent

### Implemented

- Complete minimal internal loop: capture -> canonical state -> recommend ->
  start -> feedback -> updated state.
- Schema v9 migrations and exact integrity validation.
- Projects, Tasks, commitments, Rules, Inbox, Captures, and Sessions.
- Deterministic temporal capture resolution for the supported grammar.
- Deterministic eligibility, hard-availability, duration, MUST gating, and
  session revalidation.
- OpenAI/Groq Responses adapters for capture and recommendation.
- Human CLI, Machine Interface v1, loopback HTTP, Work UI, and State/triage UI.
- Narrow planning/lifecycle/inbox/commitment corrections and bounded history.
- Extensive isolated automated tests.

### Partial by design

- Rules are stored but never evaluated.
- Project deadlines are stored/displayed but do not drive Task eligibility,
  inheritance, risk analysis, or decomposition.
- Fixed commitments are locally captured records, not calendar-synchronized.
- AI action grounding and ordinary NO_WORK quality use prompts plus structural
  validation, not deterministic semantic proof.
- Overview is intentionally bounded and not an export/full-state API.
- The CLI exposes the core work loop and debug state, but not all browser
  maintenance operations.
- Capture supports selected temporal forms but not recurrence or general
  natural-language calendaring.
- Remote operation depends on external, locally configured SSH/Tailscale,
  launchd, Automator, and Shortcut artifacts that are not version-controlled or
  reproducible from this repository alone.

### Not implemented

- Calendar or Google Sheets integration.
- Repository-managed Shortcut, NFC, Action Button, voice, or remote transport
  artifacts. A historically accepted iPhone SSH Shortcut exists outside Git;
  its current definition and health are unverified.
- Authentication, accounts, multi-user tenancy, or non-loopback HTTP.
- Background scheduler, timer, Focus mode, notifications, or proactive work.
- Generic CRUD, physical deletion, import/export, backup/restore, or sync.
- Feedback AI, automatic next actions, Project mutation after Sessions, or
  learned duration estimates.
- Routines, Goals, waiting-for items, dependencies, decisions, open questions,
  preferences, temporary context, or change detection.
- Ollama/local inference or providers other than OpenAI/Groq.

## 14. Constraints that should not be casually reversed

- Hard facts and eligibility are deterministic; AI interprets or ranks but does
  not invent dates, conflicts, availability, dependencies, or completion.
- A Project is not an executable action.
- Schedule and deadline are independent; date-only facts remain dates.
- Unknown availability is not unlimited, and availability is not recommended
  duration.
- UNKNOWN/SOFT commitments are not silently HARD.
- Recommendations are advisory and ephemeral; start revalidates authoritative
  current state.
- Accepted action text belongs to Session history, not Task truth.
- At most one Session is active, enforced in SQLite and application logic.
- Interfaces stay thin; do not move policy into JavaScript, CLI, HTTP, or a
  Shortcut.
- Storage initialization/migration is explicit; ordinary operations fail on
  missing/stale schema.
- Runtime/personal data and secrets stay outside the repository.
- The Home-Mac database is the authoritative deployed state. Do not create a
  competing laptop database during connectivity outages.
- Browser remote access preserves the loopback/no-auth boundary through a
  trusted tunnel; do not expose the HTTP listener directly.
- Avoid speculative abstractions for hypothetical commercial scale.

## 15. Resolved mistakes and approaches not to repeat

The final architecture alone does not reveal why several boundaries are strict.
Preserve this correction history:

- The first POS-012 implementation resolved timezone and constructed
  recommendation context before active-session inspection. That made an active
  Session depend on recommendation-only configuration. Commit `2fc5aeb`
  corrected the order: active Session first, deferred timezone only when idle.
- Availability-now adapters must call `activate`; the Shortcut must not
  independently orchestrate `active` and `recommend`.
- Activation accepts an optional time cap, not a required duration, and never
  auto-starts the recommendation.
- Browser timezone collection was removed in POS-018. The browser sends none;
  the configured HTTP runtime supplies it.
- Ordinary natural language is the capture interface. Do not require tags,
  rigid syntax, or rephrasing to work around provider/schema defects.
- POS-022 replaced complex temporal provider unions with fixed wire shapes and
  deterministic normalization after ordinary weekday capture failed.
- A Project may be captured without a fake Task. Projects remain planning
  containers and are never recommendation candidates.
- Project deadlines must not be copied to child Tasks.
- Supported explicit month/day text without a year resolves to the next valid
  occurrence on or after the trusted local date. Unsupported or ambiguous
  incomplete forms remain unresolved.
- Capture retry is internal, capped at one retry, and limited to structured
  output instability. Configuration/authentication, generic provider errors,
  refusals, deterministic application errors, and persistence failures are not
  retried. One user capture remains one durable Capture row.
- Do not add brittle natural-language word-difference validation for generated
  actions. Grounding is a provider contract plus structural validation.
- When evidence isolates a Shortcut magic-variable problem, do not change the
  backend. When it isolates provider/application behavior, do not patch it in
  the Shortcut.

## 16. Verified limitations and continuation

The detailed issue inventory is in
`docs/handoff/PERSONAL_OS_TECHNICAL_OPEN_ISSUES.md`.

There is no approved engineering ticket after POS-026. The immediate project
activity is ordinary dogfooding of the deployed loop. Do not select calendar,
NFC, local inference, generic CRUD, project decomposition, infrastructure
changes, or another item from the absent-feature list without new evidence and
an explicitly bounded ticket.

Known maintenance candidates are:

- repair and offline-test the stale recommendation live-smoke constructor;
- reconcile `README.md` with the current bridge, HTTP, browser timezone, State
  page, and external-runtime reality;
- decide whether human `state` output should show Project deadlines and
  commitment lifecycle status;
- convert the practiced deployment sequence into a privacy-safe checked-in
  runbook and test restore on an isolated copy;
- decide whether dependency locking is worth the maintenance cost.

These are verified audit findings, not approved roadmap priorities. Before any
future runtime-affecting ticket, repeat the read-only Home-Mac preflight because
the last live evidence is dated.

`BUILD_STATE.md` also needs a future documentation-only clarification: its
POS-026 “No live AI provider was called” line describes automated validation,
but a later manual live-provider acceptance occurred. Do not silently rewrite
that history; add a separately dated manual-acceptance note when documentation
maintenance is approved.

## 17. Collaboration protocol for the next Codex agent

The demonstrated workflow is more specific than the repository rules alone:

1. Use real dogfood evidence to define one bounded POS ticket.
2. ChatGPT/product review defines scope and acceptance criteria; Codex
   implements that scope.
3. Codex reports implementation and exact validation but does not declare
   product acceptance solely from green tests.
4. Material diffs receive independent review before merge; corrections stay on
   the same feature branch when appropriate.
5. Commit, push, merge, and deployment are distinct gates. Do not merge or
   deploy without explicit instruction.
6. Verify the remote branch and merged `main`; do not rely only on a local
   implementation report.
7. For deployment, state which machine each command runs on and proceed one
   stage at a time: preflight, backup, stop, pull, migrate, verify, restart,
   exact live acceptance.
8. Prefer one precise next action with expected output over a broad menu.
9. Do not train the user to work around valid natural-language failures.
   Isolate and fix the responsible layer.

## 18. Source bundle and remaining evidence gaps

Transfer the repository with Git history, all files under `docs/handoff/`, and
the separate narrative-package documents:

- `PERSONAL_OS_START_HERE.md`
- `PERSONAL_OS_HISTORY_AND_DECISIONS.md`
- `PERSONAL_OS_COLLABORATION_PROTOCOL.md`
- `PERSONAL_OS_CURRENT_STATE.md`
- `PERSONAL_OS_PROJECT_INSTRUCTIONS.md`
- `PERSONAL_OS_SOURCE_INDEX.md`

Key accessible conversations are:

- `Remote project work`, ID `6ab138bf-68fc-83ea-887e-677ac4ff7ad5` — later
  implementation review, deployment, outages, dogfooding, and POS-026 live
  acceptance;
- `main`, ID `6a91bfb9-b054-83ea-bfdf-b52b814c6ccd` — earlier build management
  through POS-013 and the POS-012 correction;
- `Design work now flow`, ID `6a9ece7c-3bc4-83ea-b90e-bbd9efd39fd3` — activation
  product rationale;
- `Build Activate Shortcut`, ID `6aa6cb43-eb70-83e9-85f8-b830f3cc2dd4` — phone
  acceptance and recommendation-coherence discovery;
- `Rebuild JSON Parsing`, ID `6aab4f2b-8d10-83e9-9cfc-02ab5c69f709` — Shortcut
  parsing/start/active-session corrections;
- `Migration Package Creation`, ID `6acecb06-c290-83ea-a239-41128248b9e4` —
  narrative-package production and its coverage disclaimer;
- Codex task `Implement POS-024 state triage`, ID
  `01a10f23-7603-7f13-94c9-210c004cd8b7` — despite its title, also contains
  later POS-025/POS-026 implementation turns.

Inventory or export external artifacts separately, without secrets or personal
data: the current iPhone Work Shortcut, `/Applications/personal-os.app`, the
launchd plist, `~/.personal-os/bin/start-http.sh`, and a redacted description
of SSH/Tailscale/runtime configuration key names. Do not transfer the live
database, backups, logs, environment values, private keys, Keychain contents,
provider credentials, or personal Calendar/Sheet data as Markdown handoff
material.

Still unrecovered: complete historical chat coverage, unavailable image/file
attachments and uploaded diffs, the actual current external artifact contents,
current Home-Mac state after the last 2026-10-13 evidence, a tested restore or
downgrade, current hosted-provider behavior, and any future POS-027 objective.
