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
- The initial recommendation-duration policy is deliberately unresolved and
  must be decided before POS-004.

## Session semantics

The MVP permits at most one active work session.

- **Finished:** the session and work item complete.
- **Progress:** the session completes while the work item remains open.
- **Blocked:** the session completes and the item becomes ineligible until it is
  unblocked.

## Interfaces and reference data

NFC, Shortcuts, voice, CLI, and future HTTP interfaces must remain thin adapters
over centralized application logic.

The existing Google Sheet is prototype and reference data. It is not the
architectural source of truth and does not define the persistence model.

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
already initialized schema-version-2 database and do not migrate implicitly.
Returned records expose typed dates and timezone-aware UTC datetimes rather than
raw SQLite rows.
