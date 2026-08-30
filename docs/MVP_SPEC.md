# Personal OS MVP Specification

## Purpose

This document is the executable specification for the Personal OS MVP. It
defines constraints that future implementation tickets must preserve. The
complete MVP described here is not yet implemented; the current implementation
state is recorded in `BUILD_STATE.md`.

## Complete MVP loop

The complete MVP must support:

```text
CAPTURE
→ STRUCTURED STATE
→ RECOMMEND
→ START SESSION
→ FINISH / PROGRESS / BLOCKED
→ UPDATED STATE
```

The loop must maintain a small set of tasks, projects, and rules; return one
sensible context-aware action and duration; track the resulting work session;
and update the underlying state correctly.

## Deterministic and AI responsibilities

Hard facts and eligibility are deterministic whenever possible.

AI may:

- interpret natural language;
- rank alternatives already determined to be eligible;
- decompose work;
- generate concrete next actions;
- explain recommendations.

AI must not invent dates, deadlines, calendar conflicts, availability,
dependencies, or completion state. Ambiguous required hard facts remain unknown
or unresolved until they are supplied or deterministically established.

## Scheduling and work semantics

- Projects are planning containers, not executable recommendations. A project
  must expose a concrete next action before it can be recommended.
- Task scheduling semantics and deadlines are separate dimensions.
- A day task must not acquire an invented clock time.
- A deadline does not itself occupy calendar time.
- A fixed or timed commitment may have a known start and unknown end; the system
  must not invent a duration.
- A multi-date obligation must eventually use independently completable
  occurrences so that completing one date does not erase the others.
- MUST, SHOULD, and COULD remain distinguishable. Unspecified importance must
  not silently become SHOULD.
- A valid recommendation may be "no additional work." The system must not
  fabricate activity.
- Availability and recommended work duration are distinct concepts.
- Recommendation durations use the POS-004 fixed ladder and explicit short-task
  exception described below.

## Session semantics

The MVP permits at most one active work session.

- **Finished:** the session and work item complete.
- **Progress:** the session completes while the work item remains open.
- **Blocked:** the session completes and the item becomes ineligible until it is
  unblocked.

POS-005 persists session history with exact UTC start/end facts and derives
actual elapsed duration without rounding. At most one session may be active,
enforced by SQLite as well as application checks. A session start revalidates
current Task/project eligibility, HARD availability, exact allowed duration,
and feasible-MUST protection atomically with insertion. Recommendation ranking,
urgency sorting, and the 50-candidate AI bound do not constrain session start.

FINISHED atomically closes the session and completes its Task. PROGRESS closes
the session while leaving the Task OPEN and does not touch its update timestamp.
BLOCKED closes the session and blocks the Task. Matching preexisting COMPLETED
or BLOCKED state is accepted for its corresponding outcome, while conflicting
state is not overwritten. Result text remains uninterpreted session history;
POS-005 adds no feedback AI, automatic next action, or project mutation.

## Interfaces and reference data

NFC, Shortcuts, voice, CLI, and future HTTP interfaces must remain thin adapters
over centralized application logic.

The existing Google Sheet is prototype and reference data. It is not the
architectural source of truth and does not define the persistence model.

## POS-006 thin dogfood interface

POS-006 exposes explicit database initialization, capture, recommendation,
session start, FINISHED/PROGRESS/BLOCKED feedback, and active-session display
through a human-readable CLI. It performs parsing, runtime configuration,
trusted-clock acquisition, service construction, typed display reads, output
formatting, and expected-error translation only. Domain eligibility,
availability, duration, MUST gating, capture interpretation, and session state
transitions remain centralized behind application services.

Capture, recommendation, and start require an explicitly supplied IANA
timezone, resolved from a command option before `PERSONAL_OS_TIMEZONE` without
machine-local inference. Recommendations are advisory and ephemeral; start uses
a fresh context and authoritative current-state revalidation. Starting a
session does not imply a timer or background process. The CLI has no JSON
contract and is not the integration boundary for future interfaces. Only
`init-db` may initialize or migrate storage; other commands fail cleanly when
storage is missing or stale.

## POS-001 executable boundary

POS-001 implements only the repository and persistence foundation:

- an installable Python package;
- a thin database-initialization CLI;
- configurable external runtime storage;
- deterministic, versioned SQLite initialization;
- automated tests and repository safety protections.

POS-001 does not implement capture, structured task or project state,
recommendation, sessions, calendar behavior, AI behavior, Google integrations,
HTTP endpoints, Shortcuts, NFC, user interfaces, or notifications.

## Canonical structured state

POS-002 implements deterministic persistence and Python operations for five
canonical record types. It does not implement capture, eligibility,
recommendation, sessions, or product-facing interfaces.

### Projects and tasks

Projects are ACTIVE or COMPLETED planning containers and are never executable
recommendations. Tasks are executable work items with OPEN, BLOCKED, or
COMPLETED status and distinct UNSPECIFIED, MUST, SHOULD, and COULD importance.
UNSPECIFIED is the default and must not silently become SHOULD.

Task scheduling uses one of:

- FLEXIBLE, with no day or window fields;
- DAY, with a calendar date and no invented clock time;
- WINDOW, with a timezone-aware half-open interval `[start, end)` whose start is
  strictly before its end.

Scheduling and deadlines are independent. A task may have either a date-only
deadline or an exact-time deadline, but never both. A date-only deadline remains
a calendar date; an exact-time deadline is a normalized UTC instant. Neither
form is a calendar commitment or directly occupies calendar time. Later
eligibility policy must decide how a date-only deadline affects urgency or when
it becomes overdue during its calendar day.

### Fixed commitments

Fixed commitments remain distinct from tasks. They have a required known start
and may have an unknown end. An end is never invented and, when present, must be
after the start. HARD, SOFT, and UNKNOWN classifications are explicit; UNKNOWN
is the default because a timed event is not automatically hard.

### Rules and unresolved inbox items

Rules have a non-empty kind, structured JSON-object parameters, and an enabled
state. POS-002 stores but does not evaluate them and defines no rule-kind
taxonomy.

Inbox items preserve original unresolved text and a reason. A null
`resolved_at` means unresolved; first resolution sets it, and later resolution
calls are no-ops. POS-002 does not interpret or resolve natural language.

### Persistence boundary

Schema initialization is explicit. Structured-state operations require an
already initialized current-version database and do not migrate implicitly.
Returned records expose typed dates and timezone-aware UTC datetimes rather than
raw SQLite rows.

## Natural-language capture

POS-003 adds a Python application service for durable natural-language capture.
Each non-empty capture is stored as RECEIVED before external interpretation.
It then becomes APPLIED, UNRESOLVED with one linked inbox item, or FAILED with a
classified configuration, provider, refusal, or invalid-output failure. Derived
projects, tasks, fixed commitments, and inbox items retain their immutable
source-capture relationship, and resolved output is applied atomically.

AI interpretation is constrained to a versioned semantic JSON contract that is
validated into frozen typed intents before application logic consumes it. It may
extract explicit facts, including a bare clock hour, but it may not resolve a
bare `at 4` to AM or PM, infer a missing year, invent importance or duration,
silently choose a project, or express recurrence. A bare clock and an explicit
date without a year remain UNRESOLVED rather than becoming failed captures.

Relative dates are resolved deterministically from the capture's trusted,
timezone-aware reference instant and IANA timezone. TODAY, TOMORROW, weekday,
next-weekday, explicit full dates, and this-weekend windows are supported. Day
facts remain dates. Exact local times become UTC only when the local time is
unambiguous and exists; daylight-saving gaps and folds remain unresolved. A
fixed commitment that resolves into the past is unresolved, while a past
deadline remains a valid fact.

The interpreter receives only raw text and a bounded deterministic list of
active project IDs and names. It never receives the trusted reference instant
or timezone; only deterministic application code uses that context. One DAY
task intent may contain multiple date expressions, which resolve, deduplicate,
and expand into independently completable task rows. POS-003 commitment intents
contain a start but no end, so captured commitments retain an unknown end.

The production interpreter uses the OpenAI 3.x Responses API with an explicitly
configured `PERSONAL_OS_CAPTURE_MODEL`, strict JSON Schema structured output,
and `store=False`. `OPENAI_API_KEY` is read by the standard SDK. Client creation
and all network activity are lazy, and no live request is part of automated
validation. POS-003 adds no capture CLI, recurrence, rule capture, calendar
integration, recommendation, eligibility, session, or HTTP behavior.

## Deterministic recommendation

POS-004 adds a read-only Python recommendation service over one coherent state
snapshot. OPEN standalone tasks and tasks under ACTIVE projects can qualify;
BLOCKED or COMPLETED tasks and tasks under COMPLETED projects cannot. FLEXIBLE
tasks qualify, future DAY tasks do not, missed DAY tasks remain eligible with
days-late metadata, and WINDOW eligibility is half-open at
`start <= now < end`. Date deadlines are classified against the trusted local
date and exact deadlines against their UTC instant, but neither removes a task.

Only HARD commitments constrain availability. An active HARD commitment yields
deterministic no-work; the earliest future HARD start and an optional trusted
caller cap form the finite bound. SOFT and UNKNOWN commitments are ignored and
omitted from ranking. Candidate durations use the fixed 5–60 minute ladder,
bounded by availability and task estimate, while an explicit 1–4 minute
estimate remains usable exactly when it fits.

After eligibility and duration feasibility, any feasible MUST task excludes all
lower importance candidates. Stable urgency preselection bounds the ranker to
50 tasks. The OpenAI ranker sees only derived availability and supplied
candidate facts—never raw time, timezone, clock/daypart, rules, commitments, or
mutation access—and strict validation rejects unknown tasks, unsupplied
durations, contradictory fields, and NO_WORK during MUST gating. POS-004 adds no
schema, mutation, CLI, session, history, rule evaluation, calendar, or UI.
