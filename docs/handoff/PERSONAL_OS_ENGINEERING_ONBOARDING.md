# Personal OS Engineering Onboarding

This is the operational guide for a new coding agent. Read the full technical
handoff for system detail and the open-issues report before selecting work.

Current continuation point: POS-026 is merged at `11707a1`, was recorded as
deployed and live-accepted on 2026-10-13, and has no approved POS-027. Resume by
dogfooding the existing loop; do not turn an audit finding or absent feature
into a ticket without explicit product approval.

## 1. First orientation

Run these read-only checks before proposing or implementing a ticket:

```bash
pwd
git status --short --branch
git branch -vv
git log --oneline --decorate -n 20
rg --files
```

Do not assume the checkout, locally cached `origin/main`, deployed Home-Mac
checkout, and live database are identical. Do not inspect the user's real
runtime database unless the user explicitly puts it in scope.

The last accessible operational evidence says the Home Mac was at `11707a1`,
schema 9, with clean FK checks, a running launchd HTTP service, HTTP 200 from
`/state`, and a successful exact POS-026 capture. Treat that as dated last-known
state, not a substitute for a fresh preflight.

Read these files, in order:

1. `AGENTS.md` — mandatory repository rules.
2. `PROJECT_CONTEXT.md` — product identity and intended loop.
3. `docs/MVP_SPEC.md` — executable constraints, including unimplemented scope.
4. `BUILD_STATE.md` — implementation ledger and historical validation.
5. `DECISIONS.md` — enduring architecture decisions.
6. `docs/handoff/PERSONAL_OS_TECHNICAL_HANDOFF.md` — audited system reference.
7. `docs/handoff/PERSONAL_OS_TECHNICAL_OPEN_ISSUES.md` — verified gaps and
   external uncertainties.
8. `docs/handoff/PERSONAL_OS_ADVERSARIAL_COMPLETENESS_AUDIT.md` — provenance for
   the second-round corrections and unrecovered evidence.
9. `README.md` — setup and dogfood usage, checked against source because some
   newer interface details are currently stale.

If available in the destination workspace, also read the narrative package's
`PERSONAL_OS_START_HERE.md`, `PERSONAL_OS_HISTORY_AND_DECISIONS.md`,
`PERSONAL_OS_COLLABORATION_PROTOCOL.md`, and
`PERSONAL_OS_CURRENT_STATE.md`. They supply product and collaboration history;
they do not override current code for implementation facts.

## 2. Authority and conflict resolution

For implementation facts, use this hierarchy:

1. Current code plus tests: what is implemented.
2. `docs/MVP_SPEC.md`: constraints the implementation must preserve.
3. `BUILD_STATE.md`: intended current feature inventory.
4. `DECISIONS.md`: architectural rationale and boundaries.
5. `PROJECT_CONTEXT.md`: product direction.
6. `README.md`: operator convenience, not a complete protocol definition.

For roadmap priority, use the latest explicitly approved ticket or stop
decision. There is currently no POS-027. For deployment claims, use dated host
evidence rather than the checkout. For external integrations, distinguish
“not tracked in Git” from “not built.”

The canonical persistence model is SQLite schema v9 in
`src/personal_os/database.py`, decoded and mutated through
`src/personal_os/state.py`. The stable machine boundary is Machine Interface v1
in `src/personal_os/bridge.py`. Do not treat the human CLI, browser DOM, or old
Google Sheet as a machine/domain source of truth.

## 3. Repository navigation

### Persistence and domain records

- `src/personal_os/database.py`: DDL, `CURRENT_SCHEMA_VERSION`, migrations, and
  strict schema validation.
- `src/personal_os/models.py`: Project, Task, fixed commitment, Rule, Inbox, and
  Capture invariants.
- `src/personal_os/session_types.py`: Session record and lifecycle errors.
- `src/personal_os/state.py`: concrete store, coherent snapshots, atomic
  capture/session/maintenance transactions.

### Application policy

- `capture_types.py` and `capture.py`: provider-independent capture contract,
  deterministic temporal resolution, persist-first/finalize-once workflow.
- `eligibility.py`: pure eligibility, deadline, and HARD-availability logic.
- `recommendation_types.py` and `recommendation.py`: candidate construction,
  duration feasibility, MUST gating, 50-item bound, and AI-choice validation.
- `session.py`: fresh authoritative start validation and feedback transitions.
- `activation_types.py` and `activation.py`: active Session first, otherwise
  recommendation.

### External inference

- `ai_provider.py`: explicit provider/model/key configuration.
- `openai_capture.py`: strict Responses capture schema and one narrow repair
  retry.
- `openai_recommendation.py`: strict ranking/action contract.

### Interfaces

- `cli.py`: human dogfood adapter.
- `bridge.py`: strict one-shot JSON protocol v1 and overview serialization.
- `http_api.py`: loopback transport that delegates to bridge/application code.
- `static/work.*`: capture and work-session UI.
- `static/state.*`: overview, triage, history, and narrow correction UI.
- `runtime.py`: shared service construction.

External but historically verified project artifacts are not in this tree:

- iPhone Work Shortcut -> SSH -> `personal-os-bridge`;
- laptop `/Applications/personal-os.app` -> SSH/Tailscale tunnel -> browser UI;
- Home-Mac launchd label `com.evan.personal-os.http`;
- `~/.personal-os/bin/start-http.sh`;
- `~/.personal-os/personal_os.db`, backups, and logs.

The phone flow was accepted around POS-012/POS-013 but was not exported or
revalidated after POS-026. The deployed paths are dated evidence, not a
repository-managed deployment definition.

### Tests

Test modules mirror each boundary. Start with the test matching the changed
module, then run the full suite. HTTP tests require permission to bind a
disposable `127.0.0.1` port.

## 4. Design principles to preserve

- Handle hard facts, eligibility, availability, allowed durations, and state
  transitions deterministically.
- AI may interpret, rank, create grounded action wording, or explain. It must
  not invent dates, deadlines, conflicts, availability, dependencies,
  completion state, importance, or duration.
- Projects are planning containers; only Tasks are executable.
- Task schedule and deadline are independent. Date-only facts must not acquire
  an invented time.
- Missing optional facts use canonical defaults/nulls. Genuine ambiguity routes
  to Inbox rather than becoming a guess.
- Unknown caller availability is not unlimited. Availability is distinct from
  selected duration.
- Only SCHEDULED HARD commitments constrain recommendation/start.
- SPLITTABLE and ONE_SITTING policy is shared by recommendation and session
  start; do not fork it in an adapter.
- Recommendation is read-only and ephemeral. Acceptance occurs only at Session
  start, which revalidates current state.
- Preserve the database-level single-active-Session invariant.
- Keep CLI, bridge, HTTP, browser, Shortcut, NFC, and voice integrations thin.
- Availability-now interfaces call canonical `activate`. Active Session is
  checked before recommendation-only timezone/provider configuration; do not
  reintroduce the pre-`2fc5aeb` ordering bug.
- Activation has an optional caller cap, not a required duration, and does not
  auto-start work.
- The browser sends no timezone. Runtime configuration supplies browser context;
  retain explicit timezone support for non-browser machine clients.
- Provider temporal wire shapes are fixed and normalized deterministically. Do
  not restore complex temporal unions.
- Standalone Projects are valid without fake Tasks. Project deadlines never
  flow onto child Tasks.
- Supported explicit month/day missing-year dates use deterministic
  next-occurrence resolution; other ambiguous/incomplete forms go to Inbox.
- Capture's provider retry is narrow and occurs at most once. Never retry
  configuration/authentication, refusal, generic provider, deterministic
  application, or persistence failures.
- Use ordinary natural-language capture. Do not teach rigid phrasing to hide a
  product/provider bug.
- Do not add generic CRUD when a narrow domain correction is the established
  boundary.
- Do not add speculative abstractions for future commercial scale.
- Keep the Home-Mac database authoritative. Do not create a laptop database as
  an outage workaround, and do not expose the loopback HTTP server directly to
  the network.

## 5. Before changing code

1. Confirm the approved ticket and list its in-scope behavior. At this handoff
   there is no POS-027; dogfooding alone does not authorize a code change.
2. Inspect `git status`; preserve unrelated user changes.
3. Find the existing service and tests that own the behavior.
4. Check `docs/MVP_SPEC.md` and `DECISIONS.md` for constraints.
5. Inspect the relevant migration and model invariants if persistence is
   involved.
6. Identify whether the change affects an existing stable contract:
   - SQLite schema/data migration;
   - Machine Interface v1 request/result shape;
   - HTTP mapping;
   - provider schema;
   - session or recommendation policy.
7. Decide validation before implementation.
8. Isolate the faulty layer. A Shortcut magic-variable failure is not evidence
   for a backend change; a provider/application defect should not be hidden in
   the Shortcut or by user rephrasing.

Prefer extending the current service boundary. Do not rewrite modules, add a
framework/ORM, introduce a provider plugin system, or redesign the storage
model unless the approved ticket and an enduring decision require it.

## 6. Safe development setup

```bash
python -m venv .venv
source .venv/bin/activate
python -m pip install -e ".[dev]"
```

Default runtime data is `~/.personal-os/personal_os.db`. Never use it for tests
or migration experiments. Use an isolated directory:

```bash
test_data_dir="$(mktemp -d)"
PERSONAL_OS_DATA_DIR="$test_data_dir" .venv/bin/personal-os init-db
```

Do not commit databases, WAL/journal files, logs, `.env` files, credentials,
API keys, or populated runtime exports. Tests must use `tmp_path` or another
explicit temporary location.

Provider configuration is explicit and lazy. Capture and recommendation use
separate provider/model variables. Do not run `scripts/live_ai_smoke.py` unless
the ticket requires a billable live check and the user authorizes/configures it.
The recommendation smoke path is currently a verified open issue.

## 7. Implementation workflow

For a normal ticket:

1. Add or update focused tests that express the intended behavior and
   invariants.
2. Implement behind the existing typed service boundary.
3. Keep transport parsing/serialization separate from application policy.
4. If schema changes:
   - increment `CURRENT_SCHEMA_VERSION`;
   - add one ordered transactional migration;
   - add exact DDL and foreign-key validation;
   - test fresh initialization, populated prior-version migration, rollback,
     idempotence, and data preservation;
   - never let product commands migrate implicitly.
5. If bridge changes, preserve strict fields, integer-vs-boolean validation,
   trusted server time, stable envelopes, and error/exit semantics.
6. If HTTP changes, route through bridge/application boundaries and retain
   loopback Host/origin/body/header protections.
7. If browser changes, use safe DOM text insertion and retain the browser's
   no-timezone-inference rule.
8. Update `BUILD_STATE.md` whenever implemented behavior changes.
9. Update `DECISIONS.md` only if an enduring architectural decision changes.
10. Do not edit `PROJECT_CONTEXT.md` without explicit product-level approval.

Record unrelated findings as follow-ups. Do not opportunistically repair them.

## 8. Collaboration and review workflow

The established division of work is:

1. Real dogfood evidence motivates a bounded phase.
2. ChatGPT/product review defines the objective, exclusions, acceptance tests,
   and Codex task.
3. Codex inspects the actual tree, implements only that task, and reports exact
   files and validation.
4. Green tests do not by themselves declare product acceptance. Material
   changes receive an independent diff/review pass, and corrections stay
   bounded.
5. Commit, push, merge, and deployment are separate gates. Do not cross one
   merely because the prior gate passed.
6. The user normally performs or confirms the merge; verify the remote branch
   and merged `main` before deployment.
7. During operational work, identify the machine for every command and proceed
   one stage at a time, waiting for actual output before the next state change.

Communication should lead with the result or next precise action. Include the
expected output and stop condition. Do not offer speculative redesigns when a
narrow correction is supported by evidence.

## 9. Validation

Run focused tests during development, then the relevant full checks:

```bash
.venv/bin/python -m pytest tests/test_<area>.py -q
.venv/bin/python -m pytest
.venv/bin/python -m compileall -q src tests
node --check src/personal_os/static/work.js
node --check src/personal_os/static/state.js
git diff --check
git status --short --branch
```

Run CLI/help checks when adapters or packaging change:

```bash
.venv/bin/python -m personal_os --help
.venv/bin/personal-os --help
.venv/bin/personal-os-http --help
```

The audit baseline on 2026-10-13 was 635 passing tests on Python 3.13.0 and
pytest 8.4.2. A sandbox that forbids local socket binding will make HTTP tests
fail with `PermissionError`; rerun with disposable loopback binding permission
before treating that as a product failure.

Never run validation that points at the user's real data directory. Automated
tests must not call a live provider. Live provider checks require the explicit
`PERSONAL_OS_LIVE_AI_SMOKE=1` opt-in and can be billable.

## 10. Git and deployment discipline

- Inspect status and diff before and after work.
- Do not commit, push, merge, deploy, or migrate the live database unless the
  user explicitly requests it.
- Do not assume local `origin/main` is current without a fetch, or that a
  deployed checkout follows it.
- Repository history uses scoped POS tickets and feature branches. Keep new
  work within the approved ticket.
- There is no repository-defined deployment/service/backup runbook, but a
  successful external procedure is historically recorded: read-only preflight
  -> stop launchd -> timestamped DB backup -> fast-forward `main` -> explicit
  `init-db` migration -> schema/FK checks -> restart -> HTTP 200 -> exact live
  acceptance. Confirm current paths and obtain authorization before using it.
- Backup creation is evidenced; restore, downgrade, and rollback are not.
- Treat deployed state as a separate system. The 2026-10-13 schema-9 state is
  the last known evidence, not a perpetual guarantee.
- Do not create a laptop state store when the Home Mac/Tailscale path is down.
  Preserve one authoritative database.
- Never commit or paste external runtime files if they contain environment
  values, logs, personal data, SSH material, or credentials.

## 11. Reporting a completed implementation

Report the outcome first, then include:

- behavior changed and behavior deliberately left unchanged;
- important files/boundaries touched;
- schema/protocol/runtime compatibility impact;
- validation commands and exact results;
- whether live AI, external integrations, or real runtime data were used;
- remaining limitations, unverified assumptions, and follow-ups;
- current branch/working-tree status and whether anything was committed.

Use precise phrases such as “verified in the local checkout,” “covered with a
fake provider,” or “not inspected on the deployed runtime.” Do not report a
deployment, provider behavior, or data migration as successful without direct
evidence.

## 12. Current resume decision

Do not begin implementation when first opening this repository. The current
approved activity is dogfooding. If new evidence produces a candidate ticket,
first reconcile it with the architecture and ask for explicit scope.

Known unapproved maintenance candidates are the stale recommendation
live-smoke constructor, README/interface drift, incomplete human `state` fields,
a checked-in operations/restore runbook, and dependency reproducibility. Also
remember the documentation discrepancy: `BUILD_STATE.md` correctly says the
automated POS-026 validation made no live provider call, but it omits the later
manual live-provider acceptance.
