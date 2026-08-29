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

