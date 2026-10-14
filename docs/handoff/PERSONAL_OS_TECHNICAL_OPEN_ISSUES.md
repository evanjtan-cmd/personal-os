# Personal OS Technical Open Issues

Audit date: 2026-10-13

Audited commit: `11707a13cd5e642c715ab464353d1c4cfbf79e0f` on `main`

This report separates verified defects/documentation drift, known unimplemented
scope, and external uncertainties. “Recommended” work below is an audit
recommendation, not an approved roadmap or architectural decision.

## 1. Working tree, branches, and unmerged work

### Verified local Git state

- At audit start, `main` was clean and matched the locally stored
  `origin/main` ref (`+0/-0`) at `11707a1`.
- `git diff --stat origin/main...HEAD` was empty.
- No named local or remote-tracking branch was reported as unmerged into
  `main`.
- No tags exist.
- Old feature branches remain locally. Some have live remote-tracking refs and
  some report a gone upstream, but all named feature tips are ancestors of
  `main`.
- The four files under `docs/handoff/` are intentionally uncommitted handoff
  and review deliverables. No code, configuration, or tests were changed.

### What this does not prove

- No `git fetch` was performed, so the GitHub remote could have changed after
  the locally recorded `origin/main` ref.
- GitHub issues, pull requests, project boards, and a separately maintained
  backlog were not inspected.
- Unreachable/dangling Git objects are not treated as active work because no
  named branch or worktree points to them.
- A deployed Home-Mac checkout may have changed after the last dated evidence.
  Accessible history recorded parity at `11707a1` on 2026-10-13, but this audit
  did not freshly inspect the host.

## 2. Verified defects and documentation drift

### ISSUE-1 — Recommendation live-smoke script is stale

Priority: Medium maintenance; required before relying on that script, but not
on the normal application runtime path and not the approved next project phase.

Evidence:

- `EligibleTaskCandidate` currently requires both `execution_mode` and
  `allowed_durations` after `estimated_minutes`.
- `scripts/live_ai_smoke.py:70-74` passes only `10, (5, 10)` in those positions.
  It therefore omits `execution_mode` and has no argument for
  `allowed_durations`.
- Pytest does not collect this script, so the 635-test suite cannot catch the
  mismatch.
- `BUILD_STATE.md` and `README.md` present the recommendation smoke command as
  available.

Impact:

- With the required live opt-in, the recommendation smoke path will fail while
  constructing the candidate before it can validate the provider boundary.
- The capture smoke path imports and is not affected by this constructor
  mismatch, but no live provider request was made during the audit.

Recommended bounded maintenance ticket, if approved:

- Supply `TaskExecutionMode.SPLITTABLE` and the duration tuple in the correct
  positions, preferably using keyword arguments.
- Add a non-network test that executes both smoke control paths with fake
  adapters so signature drift is detected without billable calls.
- Only then run a separately authorized live provider check.

### ISSUE-2 — `README.md` understates the current machine and HTTP surfaces

Priority: High for handoff/operator accuracy.

Evidence:

- `README.md:178-181` lists only `activate`, `recommend`, `start`, `feedback`,
  and `active` for Machine Interface v1.
- `bridge.py` also implements `capture`, `overview`, `resolve_inbox`,
  `dismiss_inbox`, `update_task_planning`, `correct_task_status`,
  `configure_commitment_protection`, and `cancel_commitment`.
- `README.md:220-224` lists only activate/start/feedback HTTP JSON endpoints.
- `http_api.py` also exposes capture, Inbox resolution/dismissal, overview,
  Task planning/status, commitment protection, and commitment cancellation.
- `README.md:217-218` says timezone can be configured “in the page,” while
  POS-018 removed the browser timezone control and browser JavaScript sends no
  timezone.
- The README describes the browser mainly as a Work interface and does not
  explain the current State/triage/history surface or its narrow mutations.

Impact:

- A new maintainer could rebuild an existing interface, call the wrong
  boundary, or assume browser timezone behavior that does not exist.

Recommended next ticket:

- Reconcile the README with `bridge.py`, `http_api.py`, and the current Work and
  State assets. Keep the full protocol detail in the technical handoff rather
  than overloading the quick start.

### ISSUE-3 — Human `state` output does not display all newly canonical fields

Priority: Medium; requires a product/interface decision before changing
behavior.

Evidence:

- Schema v9 and `Project` include `deadline_date`/`deadline_at`, and browser
  overview serializes Project deadlines.
- `cli.py::_print_state()` prints Project name, status, description, and source
  capture, but not Project deadline.
- Fixed commitments have canonical SCHEDULED/CANCELLED lifecycle status.
- The CLI prints commitment hardness, title, start, end, and source capture,
  but not lifecycle status.
- The command describes itself as showing all canonical persisted state, though
  it intentionally omits other internal/provider details.

Impact:

- CLI inspection cannot distinguish a cancelled commitment from a scheduled
  one or see a Project deadline, while the browser overview can.

Open decision:

- Decide whether the human debug view should expose these fields. If yes, add
  focused CLI tests and update the documented example. Do not turn the CLI into
  a stable machine/export contract.

### ISSUE-4 — No automated check covers standalone scripts or documentation/API drift

Priority: Medium.

Evidence:

- The full suite passed while the recommendation smoke constructor remained
  stale.
- There is no test that compares README operation/endpoint lists to registered
  bridge/HTTP routes.
- There is no CI configuration in the repository.

Impact:

- Non-pytest operational tooling and user-facing protocol summaries can drift
  without breaking the standard validation command.

Recommended approach:

- Add narrow offline tests for scripts and route/operation registration where
  stable, and/or simplify docs so they link to one authoritative contract list.
- CI, linting, or type checking would be new tooling and should be introduced
  only through an approved ticket, not as incidental cleanup.

### ISSUE-5 — `BUILD_STATE.md` omits the later POS-026 live acceptance

Priority: Medium documentation accuracy.

Evidence:

- The POS-026 automated validation block says “No live AI provider was called.”
  That is accurate for the isolated test run.
- A later 2026-10-13 Home-Mac acceptance transcript records a live configured
  provider call for the exact motivating capture.
- The resulting Capture was APPLIED, with one Project deadline of `2026-10-22`
  and no fake Task.
- The project conversation explicitly identified the missing manual-acceptance
  note as documentation housekeeping.

Impact:

- A reader can incorrectly interpret the automated-test qualifier as a claim
  that POS-026 never received live provider/runtime acceptance.

Recommended documentation correction:

- Preserve the automated-validation statement but qualify its scope.
- Add a separately dated manual acceptance note. Do not merge automated and
  live evidence into one undifferentiated “passed” claim.

## 3. Deployment and runtime gaps

### ISSUE-6 — Last-known runtime parity is verified, but freshness is not

Priority: High before a production/runtime-affecting ticket.

Repository boundary:

- No deployment manifest, service-manager definition, launch script, host
  inventory, SSH/Tailscale configuration, or Automator/Shortcut artifact is
  tracked in Git.
- The repository documents only manual `personal-os-http --port 8765` startup.

Dated operational evidence from 2026-10-13:

- Home-Mac checkout fast-forwarded to `11707a1` on `main`.
- Live database at `~/.personal-os/personal_os.db` migrated from schema 8 to 9.
- `PRAGMA foreign_key_check` reported no rows.
- launchd label `com.evan.personal-os.http` returned to running state through
  external `~/.personal-os/bin/start-http.sh`.
- `GET /state` returned HTTP 200.
- The exact POS-026 motivating capture was accepted live.

Current unknowns requiring external inspection:

- whether the deployed checkout, database, service, dependencies, environment,
  logs, and backups changed after that evidence;
- whether the iPhone Shortcut still works after POS-026;
- current Tailscale/sleep/reachability behavior;
- current provider availability and configuration, excluding secret values.

Required action before a runtime-affecting ticket:

- Perform a separately authorized, read-only preflight. Record only non-secret
  operational facts. Do not copy personal database contents, environment
  values, logs, keys, or provider credentials into Git or the handoff.

### ISSUE-7 — Upgrade/backup procedure exists, but restore and rollback are unverified

Priority: High before migrating a valuable live database.

Evidence:

- The database initializer performs explicit forward migrations with rollback
  on failure.
- Successful deployments repeatedly used read-only preflight, service stop,
  timestamped database backup, fast-forward pull, explicit migration, schema/FK
  verification, service restart, HTTP check, and an exact live acceptance case.
- POS-026 visibly created a pre-migration backup under
  `~/.personal-os/backups/`.
- The repository has no checked-in version of that procedure, restore test,
  downgrade path, release pin, or rollback procedure.
- There is no import/export interface.

Impact:

- Backup creation and forward migration have operational evidence. Backup
  integrity, restore, downgrade, and live rollback remain unspecified.

Recommended next step:

- Convert the practiced sequence into a privacy-safe runbook and verify restore
  on a copy in an isolated directory before claiming rollback capability. This
  is operations work, not a request to add generic product export.

### ISSUE-8 — Dependency and release reproducibility is limited

Priority: Medium.

Evidence:

- `pyproject.toml` uses ranges (`openai>=3.6,<4`, `pytest>=8,<9`).
- There is no lockfile, release tag, build artifact manifest, or deployed
  dependency snapshot in Git.
- The audited environment used OpenAI SDK 3.8.0, but a fresh install may select
  another compatible 3.x release.

Impact:

- Provider SDK behavior can change within the accepted range, and recreating a
  deployment exactly is not guaranteed.

Open decision:

- Decide whether this personal deployment needs a committed lock/constraints
  strategy. Do not add one incidentally without considering update workflow.

### ISSUE-9 — Home-Mac/Tailscale availability is a single operational dependency

Priority: Evidence-dependent; open a reliability ticket only if outages recur.

Evidence:

- One recorded outage showed the Home Mac offline from Tailscale. SSH, browser,
  and Shortcut access all failed together even though application code was not
  the cause.
- The Home-Mac database is the authoritative deployed state.
- The explicit response was not to use a separate laptop database, which would
  create conflicting Personal OS states.

Current boundary:

- Wake/sleep policy, Tailscale persistence, monitoring, and recovery were not
  inspected in this audit.
- Do not redesign hosting speculatively. If the failure repeats, first isolate
  Mac sleep, Tailscale, SSH, and network causes, then define a bounded
  reliability phase.

## 4. Known product/architecture limitations (not regressions)

These are verified absent or deliberately narrow in the current checkout.

### External integrations

- No Google Calendar or Google Sheets adapter.
- No repository-managed iPhone Shortcut, NFC action, Action Button flow, voice
  adapter, SSH/Tailscale transport, Automator launcher, or launchd definition.
- An external iPhone SSH Shortcut was historically accepted for
  activate/start/feedback, and a laptop Automator SSH-tunnel launcher was
  tested. Their current definitions are unavailable and their post-POS-026
  health is unverified.
- Fixed commitments are local records; they do not synchronize with a calendar.

### Scheduling and capture

- No recurrence model. Explicit multiple DAY dates expand to separate Tasks,
  but general recurring obligations are unsupported.
- Captured fixed commitments store a start and unknown end. End/duration is set
  later only through the narrow protection operation.
- Supported temporal grammar is intentionally bounded; unsupported or
  ambiguous facts route to Inbox.
- A capture can create at most one new Project; provider Project context is
  limited to the 50 most recently updated ACTIVE Projects.
- There is no automatic deduplication for Tasks/commitments. New Project name
  collision is capture policy, not a DB uniqueness invariant.

### Recommendation and AI

- Rules are persisted but not evaluated.
- Project deadlines do not affect Task eligibility/ranking or create next
  actions.
- No project health, stale-item detection, deadline-risk analysis, dependency
  logic, waiting-for follow-up, plan repair, batching, energy matching, or
  learned duration model.
- The ranker sees at most 50 feasible candidates.
- Action grounding and ordinary non-MUST NO_WORK quality are instructed and
  structurally validated, but not semantically proven by deterministic code.
- Only OpenAI-hosted and Groq-hosted Responses inference is supported. No
  Ollama/local provider.
- Automated tests do not certify live provider availability, quota, strict
  schema support, latency, or model quality.

### Sessions and automation

- One active Session maximum; no parallel work sessions.
- No countdown, timer, background process, Focus integration, notification, or
  proactive scheduling.
- Feedback notes are not interpreted. No automatic next Task, Project update,
  or duration learning follows a Session.

### State and lifecycle

- No generic product CRUD and no physical delete.
- No generic import/export/sync.
- Overview history is intentionally capped at 20 Tasks and 20 commitments and
  excludes closed Sessions, Rules, and Captures.
- The CLI has no stable JSON contract; only the bridge is a machine boundary.
- Routines, Goals, waiting-for items, dependencies, decisions, open questions,
  preferences, and temporary context are absent as canonical records.

### HTTP/security boundary

- HTTP is unauthenticated and loopback-only. It is not suitable for binding to
  a LAN/public interface without a new transport/security design.
- There is no TLS, account model, rate limiting, or authorization.
- Expected application errors map to HTTP 500 even when they are user-actionable
  domain conflicts; clients must inspect the structured envelope.
- The bridge itself has no authentication or transport. External project
  history records SSH as the implemented trusted wrapper for the iPhone flow,
  while the laptop reaches the loopback HTTP service through SSH/Tailscale
  forwarding. Those transport artifacts are not version-controlled.

## 5. Unresolved architectural and product questions

No question below is an approved ticket. The current direction is to dogfood
POS-026 and let real use define the next bounded phase.

1. Which future dogfood failure, if any, justifies POS-027?
2. Do recurring Home-Mac/Tailscale outages justify a bounded reliability phase,
   and what is their actual cause?
3. Which stored Rule kinds, if any, should become deterministic eligibility or
   ranking inputs?
4. How should Project deadlines influence planning without making Projects
   executable or copying deadlines to Tasks?
5. Should commitment capture represent explicit end times/durations, and how
   should ambiguity and calendar semantics be preserved?
6. Should current-state history remain bounded in the interface, and what
   separate export/backup boundary is appropriate if needed?
7. Is provider-independent local inference desired, and can it satisfy strict
   Responses/JSON-schema behavior without weakening validation?
8. Should external Shortcut, Automator, launchd, and operations artifacts gain
   a safe versioned/exported representation, and how should secrets stay out?
9. Is dependency locking worth its maintenance cost for this personal
   deployment?
10. What data and conversation material may be transferred to the separate
    ChatGPT Business workspace under the owner's privacy policy?

## 6. Validation status and limitations

Verified on the audited checkout:

```text
Python: 3.13.0
pytest: 8.4.2
Tests: 635 passed in 57.46s
compileall: passed
work.js syntax: passed
state.js syntax: passed
module/CLI/HTTP help: passed
git diff --check: passed before adding these documents
```

The first sandboxed test run could not bind loopback ports and ended with 562
passes, 3 failures, and 70 errors, all in HTTP tests at server construction with
`PermissionError: [Errno 1] Operation not permitted`. The complete suite passed
when disposable loopback binding was permitted. This is an audit-environment
constraint, not a verified product defect.

Not validated:

- current OpenAI/Groq availability, quota, configuration, or model
  compatibility after the dated live acceptance;
- Home-Mac repository/database/service state after the 2026-10-13 evidence;
- current phone Shortcut definition or post-POS-026 behavior;
- NFC, Action Button, voice, calendar, or Sheets behavior;
- remote Git state beyond locally stored refs;
- backup integrity, restore, downgrade, or deployment rollback.

Historically validated but not freshly rechecked:

- schema-9 migration and FK check on the live Home-Mac database;
- launchd service recovery and HTTP 200;
- exact POS-026 live provider acceptance;
- iPhone activate/start/feedback behavior around POS-012/POS-013;
- creation of timestamped pre-migration database backups.

## 7. Current continuation and maintenance backlog

There is no approved immediate engineering sequence. The approved continuation
is normal dogfooding of Capture -> State -> Recommend -> Start -> Feedback.
Only real evidence should open POS-027.

Before any future runtime-affecting ticket, repeat the read-only deployment
preflight because the last known state is dated.

Unapproved maintenance candidates are:

1. Fix and offline-test the recommendation live-smoke path before relying on it.
2. Update README interface/runtime documentation to match current code and
   clearly distinguish external deployment artifacts.
3. Add the dated POS-026 manual live-acceptance note to `BUILD_STATE.md`.
4. Convert the practiced deployment sequence into a privacy-safe runbook and
   test restore on an isolated copy.
5. Decide whether to expose Project deadlines and commitment lifecycle in the
   human `state` output.
6. Decide whether dependency locking is warranted.

Do not bundle these with calendar, mobile transport, generic CRUD, provider
framework, hosting, or other product changes. Each requires an explicit bounded
ticket.

## 8. Remaining evidence gaps for migration

The following could not be recovered or freshly verified and should not be
filled by inference:

- complete coverage of every historical Personal OS conversation;
- inaccessible screenshots, uploaded diffs, and file/Library attachments;
- the actual contents of the six narrative-package Markdown downloads from the
  separate migration conversation;
- the current iPhone Shortcut export and any NFC/Action Button configuration;
- the current Automator app, launchd plist, start script, SSH config, Tailscale
  settings, and runtime environment contents;
- live host/database/provider state after the last 2026-10-13 evidence;
- a tested database restore, downgrade, or rollback;
- current GitHub issues, PRs, boards, or refs beyond the locally cached refs;
- the prototype Google Sheet and Calendar contents or their transfer policy;
- any POS-027 objective.

External artifacts may be inventoried or exported separately only with explicit
scope. Do not place databases, backups, logs, populated environment files,
private keys, Keychain contents, credentials, or personal Calendar/Sheet data in
the repository or Markdown handoff.
