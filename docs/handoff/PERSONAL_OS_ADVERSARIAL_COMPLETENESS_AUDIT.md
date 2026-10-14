# Personal OS Migration Package — Adversarial Completeness Audit

Audit date: 2026-10-13 (America/New_York)

Audited technical package:

- `PERSONAL_OS_TECHNICAL_HANDOFF.md`
- `PERSONAL_OS_ENGINEERING_ONBOARDING.md`
- `PERSONAL_OS_TECHNICAL_OPEN_ISSUES.md`

This audit tests that package against the current checkout, Git history, the
governing repository documents, and accessible Personal OS conversation
history. It does not claim exhaustive conversation coverage. In particular,
the downloadable files in the separate narrative migration package were not
available as readable local files in this task; only their titles, the
producing conversation, and its completion summary were accessible.

At this adversarial audit's start, `main` and the locally stored `origin/main`
both pointed to `11707a1`; the only working-tree entries were the three
untracked technical-package documents. Writing this audit adds a fourth
untracked Markdown document. No application code, configuration, tests, commit,
branch, remote, deployment, or runtime state was changed.

## 1. Prioritized findings

### P0 — Continuation-critical

#### 1. The package recommends an engineering sequence that is not the current plan

Impact: Critical. A replacement assistant could immediately open an unapproved
maintenance ticket instead of continuing from the actual stopping point.

The technical package promotes the stale recommendation live-smoke script,
README reconciliation, and runtime inventory as the highest-value immediate
work. Those are legitimate audit findings, but accessible project history is
more specific about continuation:

- POS-026 is merged at `11707a13cd5e642c715ab464353d1c4cfbf79e0f`.
- A dated deployment transcript records the Home Mac moving to that commit and
  the live database moving from schema 8 to schema 9.
- The exact capture that motivated POS-026 then applied successfully.
- No POS-027 was approved.
- The explicit next step was normal dogfooding of
  Capture -> State -> Recommend -> Start -> Feedback, with a new bounded ticket
  only when real use exposes a meaningful limitation.

Correction: Reclassify the smoke script, README drift, CLI field omissions, and
operations documentation as backlog candidates. Do not describe any of them as
the next approved phase.

#### 2. Deployment is treated as wholly unknown, although recent operational evidence exists

Impact: Critical. The replacement assistant could waste time rediscovering the
deployment or incorrectly conclude that POS-026 has never run against the live
database.

The original package correctly says that this Codex audit did not itself inspect
the Home Mac. It goes too far when it turns that audit boundary into the broader
claim that deployment topology, schema parity, backup procedure, and transport
are undefined or unverified.

The `Remote project work` conversation records the following on 2026-10-13:

- Home-Mac repository: clean `main` at `11707a1` after a fast-forward pull.
- Live database: `~/.personal-os/personal_os.db`, migrated from schema 8 to 9.
- `PRAGMA foreign_key_check`: no reported violations.
- Pre-migration backup created under `~/.personal-os/backups/`.
- launchd service `com.evan.personal-os.http` running.
- launch script reported as `~/.personal-os/bin/start-http.sh`.
- `/state` on `127.0.0.1:8765` returned HTTP 200 after restart.
- The exact live capture
  `project: chinese culture presentation - due oct 22` returned `APPLIED`,
  created one Project with deadline `2026-10-22`, and created no fake Task.

This is strong, dated, user-provided operational evidence. It is not a fresh
host inspection during this audit, and it does not prove the host remained
unchanged afterward. The correct status is therefore **last known live state,
conversation-verified on 2026-10-13; current freshness not revalidated**, not
“deployment unverified.”

#### 3. “Not in the repository” is repeatedly allowed to imply “not implemented”

Impact: Critical. This loses the real integration architecture and can lead to
building a second, conflicting transport.

No Shortcut, LaunchAgent, SSH configuration, Automator application, or Tailscale
configuration is tracked in Git. However, accessible history records external
artifacts and tested flows:

- iPhone Shortcut -> SSH -> `personal-os-bridge` was acceptance-tested for
  `RECOMMEND`, `ACTIVE_SESSION`, `NO_WORK`, `start`, and `PROGRESS` around
  POS-012/POS-013.
- The Shortcut was changed to call canonical `activate`, rather than manually
  chaining `active` and `recommend` or requiring minutes.
- A laptop Automator launcher at `/Applications/personal-os.app` was tested to
  establish/re-establish an SSH tunnel and open the browser UI.
- The laptop reaches the Home-Mac loopback HTTP service through the SSH/Tailscale
  path; the Home Mac remains the authoritative database host.
- A launchd job runs the Home-Mac HTTP process.

The current contents and continued health of those external artifacts were not
inspected here. The package should say **implemented outside the repository and
historically acceptance-tested, but not version-controlled or freshly
revalidated**.

#### 4. The package lacks a source model for implementation truth versus continuation truth

Impact: Critical. The current hierarchy is useful for code facts but incomplete
for choosing what to do next or describing a deployment.

Three distinct questions require three distinct authorities:

1. What does this checkout implement? Current code, migrations, and tests.
2. What should be built next? The latest explicitly approved product ticket or,
   currently, the explicit decision to dogfood without POS-027.
3. What is deployed? Dated direct host/runtime evidence, not the checkout and
   not the product narrative.

Repository documents remain authoritative for constraints, but they cannot by
themselves establish current host state or roadmap approval.

### P1 — High impact

#### 5. The final POS-026 live acceptance and its originating failure are omitted

Impact: High. The next assistant loses both the most recent problem context and
the acceptance criterion that proved it fixed.

Live dogfooding exposed two different failures:

- transient Groq structured-output failures that often succeeded only after the
  user clicked Capture again;
- a deterministic application invariant rejecting a standalone new Project
  because no Task referenced it.

POS-026 therefore intentionally combined one bounded provider-boundary retry,
standalone Project capture, Project deadlines, and deterministic resolution of
supported month/day dates without a year. The final correction was necessary
because the first POS-026 implementation still routed every `MISSING_YEAR`
expression to Inbox, meaning the motivating input would still not work.

The accepted deterministic rule is the first valid occurrence of an explicit
month/day on or after the trusted local date, including leap-day handling.
Unsupported or ambiguous incomplete dates remain unresolved. Project deadlines
must not be inherited by child Tasks.

#### 6. `BUILD_STATE.md` is known to be stale about post-test live acceptance

Impact: High. A replacement assistant could cite the validation note as proof
that no live provider was called after POS-026.

`BUILD_STATE.md` says “No live AI provider was called” in the POS-026 validation
block. That statement is accurate for the automated validation run, but the
later live acceptance used the configured provider and live database. The
conversation explicitly identified this as a documentation housekeeping item.

Correction: Qualify the existing line as automated-test scope, and add a dated
manual acceptance note. Do not erase the distinction between isolated tests and
live validation.

#### 7. Resolved architectural mistakes are not preserved as a “do not repeat” ledger

Impact: High. The final architecture is documented, but the reasons for several
non-obvious shapes are easy to lose.

Important resolved patterns include:

- Do not resolve recommendation-only timezone before checking for an active
  Session. The initial POS-012 implementation did this and was corrected by
  `2fc5aeb`.
- Do not make Shortcut/UI adapters manually orchestrate `active` then
  `recommend`; call canonical `activate`.
- Do not require a caller-supplied duration to activate work. The caller cap is
  optional and distinct from hard availability and recommended duration.
- Do not expose complex temporal unions to the provider. POS-022 moved to fixed
  wire shapes and deterministic normalization after ordinary weekday input
  failed.
- Do not require users to learn a capture syntax or rewrite valid natural
  language around provider/schema failures.
- Do not require a fake Task merely to create a Project.
- Do not copy a Project deadline onto child Tasks.
- Do not treat every missing-year date identically; only supported explicit
  month/day forms receive deterministic next-occurrence resolution.
- Do not retry all failures. POS-026 permits one internal retry only for the
  narrow structured-output failure classes; configuration, authentication,
  generic provider, refusal, deterministic application, and persistence
  failures are not retried.
- Do not use brittle output word searches to prove action grounding.
- Do not expose the unauthenticated HTTP server on a LAN/public interface; keep
  it loopback-only and use a trusted tunnel.
- Do not create a second laptop database when the Home Mac is unavailable. That
  would create conflicting authoritative states.

#### 8. The onboarding guide captures repository rules but not the demonstrated collaboration workflow

Impact: High. A new agent could be technically correct while repeatedly working
in a way the user has already rejected.

Demonstrated preferences and workflow:

- ChatGPT acts as product/architecture manager and independent reviewer; Codex
  implements a bounded ticket.
- Codex should not decide that a ticket is complete merely because tests pass.
  The implementation report/diff returns for independent review.
- Feature work is reviewed before commit when risk is high, then committed and
  pushed to a feature branch; it is not merged or deployed until explicitly
  approved.
- The user normally performs or confirms the merge; the assistant verifies
  remote `main` afterward before deployment.
- Deployment is performed one stage at a time with exact machine context:
  laptop, Home Mac over SSH, or iPhone. The assistant waits for concrete output
  before the next state-changing step.
- The user prefers concise orientation followed by exact commands and expected
  results. They often ask “what do I do now”; the useful response is the next
  bounded action, not a broad menu.
- When a valid natural-language input fails, do not train the user to phrase it
  unnaturally. Isolate and correct the product boundary.
- When evidence isolates a UI/Shortcut problem, do not change the backend; when
  evidence isolates provider/application behavior, do not patch it in the
  Shortcut.
- Product phases should be driven by real dogfood friction, not speculative
  backlog breadth.

#### 9. A practiced deployment procedure exists, even though no repository runbook exists

Impact: High. “No runbook” is true only as a repository-documentation claim.

The project repeatedly used this operational sequence for schema-changing
releases:

1. Verify the merge and sync the laptop.
2. SSH to the Home Mac with forwarding disabled for the maintenance shell.
3. Read-only preflight: Git state, deployed commit, schema version, FK check,
   service status, and database presence.
4. Stop the launchd service.
5. Create a timestamped database backup.
6. Fast-forward the Home-Mac checkout from `origin/main`.
7. Run explicit `personal-os init-db` migration.
8. Verify new schema version and `PRAGMA foreign_key_check`.
9. Restart/bootstrap the launchd service.
10. Verify HTTP 200.
11. Run the exact live acceptance case that motivated the ticket.

Restore/downgrade has not been shown to work. The runbook should therefore
preserve the practiced upgrade/backup sequence while still marking restore and
rollback as unverified.

#### 10. The Home-Mac/Tailscale availability failure and split-brain rule are missing

Impact: High. This is the principal known operational failure mode.

Accessible history records an outage in which the Home Mac went offline from
Tailscale. SSH, browser UI, and Shortcut access all failed because the Home Mac
is the authoritative backend. The explicit decision was not to start using a
separate laptop database as a workaround. Once the Home Mac returned, normal
dogfooding resumed. Infrastructure reliability remains a real observation, but
no reliability ticket is currently approved.

### P2 — Material but not continuation-blocking

#### 11. The technical package has no conversation/external-artifact source index

Impact: Medium. Consequential claims cannot be traced after workspace transfer.

At minimum, the source bundle should identify the conversations and external
artifacts listed in section 3 below. Conversation titles alone are not enough:
one Codex task titled `Implement POS-024 state triage` was later reused for
POS-025 and POS-026 work, so title-based chronology is misleading.

#### 12. Shortcut status needs a three-state description

Impact: Medium.

The correct description is:

- repository artifact: absent;
- historical functional acceptance: present for the POS-012/POS-013 flow;
- current exported Shortcut definition and post-POS-026 revalidation: absent.

Neither “Shortcut implemented” nor “Shortcut not implemented” is precise enough
without those qualifiers.

#### 13. Backup evidence and restore evidence are conflated

Impact: Medium.

A POS-026 pre-migration backup was visibly created. That is evidence for the
backup step. It is not evidence that restore works, that the backup is complete,
or that downgrade is supported. The open-issues report should split these.

#### 14. The live-smoke defect is real, but its priority is overstated

Impact: Medium.

The recommendation smoke constructor mismatch is a verified defect in an
opt-in operational script. It is not on the application runtime path, and the
live system has other acceptance evidence. It should be repaired before relying
on that script, but there is no evidence that it should supersede dogfooding as
the next phase.

#### 15. The package understates evidence gaps in the separate narrative package

Impact: Medium.

The narrative-package conversation says its six Markdown documents contain
history, collaboration protocol, live state, instructions, and a source index.
Those actual files were represented by workspace-local download links and were
not readable from this technical task. Therefore this audit can identify likely
cross-package overlap and contradiction, but cannot certify the narrative
documents' contents or completeness.

## 2. Insert-ready corrected and expanded sections

The following sections are written to be inserted into the existing migration
package without restating the full technical reference.

### Insert: Evidence classes and source-of-truth boundaries

> ## Evidence classes
>
> Do not use one source hierarchy for every kind of claim.
>
> **Implemented behavior in a checkout**
>
> 1. Current source code, migrations, and tests.
> 2. `docs/MVP_SPEC.md` for constraints and deliberately unimplemented scope.
> 3. `BUILD_STATE.md` for the implementation ledger and dated validation.
> 4. `DECISIONS.md` for enduring rationale.
> 5. `PROJECT_CONTEXT.md` for product direction.
> 6. `README.md` for convenience only; it is currently incomplete/stale in
>    several interface descriptions.
>
> **Roadmap and continuation**
>
> Use the latest explicitly approved ticket or explicit stop decision. At the
> current handoff, POS-026 is complete and no POS-027 is approved. The current
> instruction is to dogfood the live loop and open a bounded ticket only from
> meaningful observed friction. Audit recommendations are not roadmap approval.
>
> **Deployed state**
>
> Use dated direct host/runtime evidence. Repository state cannot prove deployed
> state. The last accessible operational evidence is dated 2026-10-13 and is
> summarized below; it was not freshly re-executed during this technical audit.
>
> **External integrations**
>
> Distinguish “not tracked in Git” from “not built.” Shortcut, SSH, Tailscale,
> launchd, and Automator artifacts exist outside the repository and need their
> own dated verification/export.

### Insert: Exact continuation point

> ## Current continuation point
>
> POS-026, Capture Reliability & Project Intake, is merged at
> `11707a13cd5e642c715ab464353d1c4cfbf79e0f`. Automated validation is 635 passing
> tests. A 2026-10-13 operational transcript records deployment to the Home Mac,
> migration of the live database to schema 9, a clean foreign-key check, HTTP
> recovery, and successful live acceptance of the exact motivating input:
>
> `project: chinese culture presentation - due oct 22`
>
> The accepted result was one Project with a date-only deadline of
> `2026-10-22` and zero invented Tasks. Earlier failed Capture rows remained as
> history, as intended.
>
> There is no approved POS-027. Resume normal use of Capture -> State -> Find
> work -> Start -> Finished/Made progress/Blocked. Do not select a new product
> phase from the “not implemented” list merely because it exists. Use real
> dogfood evidence to define the next bounded ticket.
>
> Known maintenance findings—the stale recommendation smoke constructor,
> README drift, incomplete CLI state display, and missing checked-in operations
> documentation—remain unapproved backlog candidates.

### Insert: External runtime topology and last known live state

> ## External runtime topology
>
> The following topology is evidenced by project conversations but is not
> version-controlled in this repository:
>
> ```text
> iPhone Work Shortcut
>     -> SSH to Home Mac
>     -> source external runtime environment
>     -> personal-os-bridge (canonical activate/start/feedback contracts)
>
> Laptop /Applications/personal-os.app
>     -> establish or reuse SSH/Tailscale local forwarding
>     -> open http://127.0.0.1:8765/
>     -> Home-Mac loopback personal-os-http service
>
> Home Mac
>     -> ~/Documents/GitHub/personal-os
>     -> launchd label com.evan.personal-os.http
>     -> ~/.personal-os/bin/start-http.sh
>     -> ~/.personal-os/personal_os.db
>     -> ~/.personal-os/backups/
>     -> ~/.personal-os/logs/http.out.log and http.err.log
> ```
>
> The SSH alias used in maintenance transcripts is `personal-os-home`. Tailscale
> reachability is a prerequisite. The HTTP server remains loopback-only and
> unauthenticated; the tunnel is the trusted transport. Do not change the HTTP
> bind address to solve remote access.
>
> Last known live state, evidenced on 2026-10-13:
>
> - Home-Mac `main`: `11707a1`.
> - live database: schema 9 with no reported FK violations;
> - launchd HTTP service: running after deployment;
> - `/state`: HTTP 200;
> - exact POS-026 live capture: accepted.
>
> This is a dated last-known state, not a guarantee of present state. Before a
> runtime-affecting ticket, repeat a read-only preflight. Do not copy database
> contents, environment contents, logs, SSH material, or secrets into the
> migration package.

### Insert: Practiced deployment and migration procedure

> ## Practiced deployment procedure
>
> This procedure is reconstructed from successful deployments. It is not yet a
> checked-in repository runbook. Confirm current paths and obtain explicit
> authorization before using it.
>
> Read-only preflight from the laptop:
>
> ```bash
> ssh -o ClearAllForwardings=yes personal-os-home
> cd ~/Documents/GitHub/personal-os
> git status --short --branch
> git log -1 --oneline
> sqlite3 ~/.personal-os/personal_os.db "PRAGMA user_version;"
> sqlite3 ~/.personal-os/personal_os.db "PRAGMA foreign_key_check;"
> launchctl print gui/$(id -u)/com.evan.personal-os.http \
>   | grep -E 'state =|pid =|last exit code|program =|path ='
> ls -lh ~/.personal-os/personal_os.db
> ```
>
> Historical schema-changing deployment sequence:
>
> ```bash
> cd ~/Documents/GitHub/personal-os
> stamp=$(date +%Y%m%d-%H%M%S)
> mkdir -p ~/.personal-os/backups
> launchctl bootout gui/$(id -u)/com.evan.personal-os.http
> cp -p ~/.personal-os/personal_os.db \
>   ~/.personal-os/backups/personal_os-pre-upgrade-$stamp.db
> git pull --ff-only origin main
> git log -1 --oneline
> .venv/bin/personal-os init-db
> sqlite3 ~/.personal-os/personal_os.db "PRAGMA user_version;"
> sqlite3 ~/.personal-os/personal_os.db "PRAGMA foreign_key_check;"
> launchctl bootstrap gui/$(id -u) \
>   ~/Library/LaunchAgents/com.evan.personal-os.http.plist
> sleep 3
> curl -sS -o /dev/null -w '%{http_code}\n' \
>   http://127.0.0.1:8765/state
> ```
>
> Stop on any unexpected output. After service recovery, run the exact live
> acceptance case that motivated the ticket. A backup file has been created in
> practice, but restore, downgrade, and rollback from that backup remain
> unverified.

### Insert: Resolved approaches that must not be reintroduced

> ## Resolved approaches and rejected shortcuts
>
> - Active-session activation must not require recommendation-only timezone or
>   provider configuration. Active Session wins first.
> - Availability-now interfaces call canonical `activate`; they do not manually
>   coordinate `active` plus `recommend`.
> - Activation does not require minutes and does not auto-start work.
> - Hard availability, optional caller cap, and selected duration are separate.
> - Browser code sends no inferred timezone; the configured HTTP runtime owns
>   browser timezone context.
> - Natural capture uses ordinary language. Do not introduce tags or rigid
>   syntax to avoid fixing capture/provider failures.
> - Provider temporal wire shapes stay fixed and deterministic; do not restore
>   complex temporal unions.
> - Projects may exist without fake child Tasks, but Projects remain
>   non-executable.
> - Project deadlines are canonical Project facts and are not inherited by
>   Tasks.
> - Supported explicit month/day text without a year resolves to the next valid
>   occurrence on or after the trusted local date; ambiguous forms remain
>   unresolved.
> - Capture retry is internal, capped at one retry, and limited to structured
>   output instability. One user capture remains one durable Capture record.
> - Recommendation action grounding is a provider contract plus structural
>   validation; do not add brittle word-difference heuristics.
> - The laptop must not become a second authoritative database during Home-Mac
>   outages.
> - The loopback HTTP server must not be exposed directly to the network.

### Insert: Collaboration and verification protocol

> ## How to work with the owner on this repository
>
> 1. Use the latest real dogfood evidence to define one bounded POS ticket.
> 2. ChatGPT/product review defines scope and acceptance criteria; Codex
>    implements only that scope.
> 3. Inspect the actual working tree before editing and preserve unrelated work.
> 4. Report the implementation and exact validation, but do not treat tests
>    alone as product acceptance.
> 5. For material changes, provide an integrated diff for independent review
>    before commit/merge.
> 6. Keep feature branch, commit, push, merge, and deployment as distinct gates.
>    Do not merge or deploy without explicit instruction.
> 7. Verify the remote branch and merged `main`; do not rely only on a local
>    success report.
> 8. For deployment, say which machine each command runs on and proceed one
>    stage at a time: preflight, backup, stop, pull, migrate, verify, restart,
>    live acceptance.
> 9. Prefer one precise next action with expected output over a long set of
>    optional paths.
> 10. When a valid input fails, isolate the faulty layer. Do not redesign the
>     backend to fix a Shortcut variable problem, and do not teach awkward user
>     phrasing to hide a backend/provider problem.

### Insert: Corrected open-issue priorities

> ## Current priorities and open issues
>
> **Approved continuation:** no engineering ticket; dogfood the deployed loop.
>
> **Before any runtime-affecting future ticket:** repeat a read-only deployment
> preflight because the last known live state is dated evidence, not a perpetual
> guarantee.
>
> **Maintenance candidates, not approved roadmap:**
>
> - repair and offline-test the stale recommendation smoke constructor;
> - reconcile README operation/endpoint/timezone/State documentation;
> - decide whether the human `state` command should show Project deadlines and
>   commitment lifecycle status;
> - check in a privacy-safe operations runbook based on the practiced procedure;
> - test restore on an isolated copy before claiming rollback capability;
> - decide whether dependency locking is worth the maintenance cost.
>
> **Known operational risk:** all remote interfaces depend on Home-Mac and
> Tailscale availability. Do not create a competing laptop state store as a
> workaround. A reliability phase should be opened only if recurring outages
> justify it.

### Insert: Required source bundle

> ## Sources and external artifacts to transfer
>
> Repository sources:
>
> - `AGENTS.md`
> - `PROJECT_CONTEXT.md`
> - `docs/MVP_SPEC.md`
> - `BUILD_STATE.md`
> - `DECISIONS.md`
> - `README.md`
> - the full `docs/handoff/` package
> - the Git repository with history, not a source-only ZIP
>
> Separate narrative package:
>
> - `PERSONAL_OS_START_HERE.md`
> - `PERSONAL_OS_HISTORY_AND_DECISIONS.md`
> - `PERSONAL_OS_COLLABORATION_PROTOCOL.md`
> - `PERSONAL_OS_CURRENT_STATE.md`
> - `PERSONAL_OS_PROJECT_INSTRUCTIONS.md`
> - `PERSONAL_OS_SOURCE_INDEX.md`
>
> Key conversations, identified by title and ID:
>
> - `Remote project work` —
>   `6ab138bf-68fc-83ea-887e-677ac4ff7ad5`: POS-014 through POS-026-era
>   review/deployment/dogfood evidence, including the last live acceptance.
> - `main` — `6a91bfb9-b054-83ea-bfdf-b52b814c6ccd`: earlier authoritative
>   build management through POS-013, including the POS-012 correction.
> - `Design work now flow` —
>   `6a9ece7c-3bc4-83ea-b90e-bbd9efd39fd3`: activation product rationale and
>   separation of hard availability, caller cap, and recommendation duration.
> - `Build Activate Shortcut` —
>   `6aa6cb43-eb70-83e9-85f8-b830f3cc2dd4`: iPhone activation acceptance and
>   recommendation-coherence bug discovery.
> - `Rebuild JSON Parsing` —
>   `6aab4f2b-8d10-83e9-9cfc-02ab5c69f709`: Shortcut parsing/start/active-session
>   construction and corrections.
> - `Migration Package Creation` —
>   `6acecb06-c290-83ea-a239-41128248b9e4`: source of the separate narrative
>   package and its coverage disclaimer.
> - `Implement POS-024 state triage` —
>   `01a10f23-7603-7f13-94c9-210c004cd8b7`: despite its title, this Codex task
>   also contains later POS-025/POS-026 implementation turns.
>
> External artifacts to inventory or export separately, without secrets or
> personal data:
>
> - the current iPhone Work Shortcut definition/export;
> - `/Applications/personal-os.app` Automator workflow;
> - `~/Library/LaunchAgents/com.evan.personal-os.http.plist`;
> - `~/.personal-os/bin/start-http.sh`;
> - a redacted description of the `personal-os-home` SSH/Tailscale topology;
> - a redacted runtime configuration key-name inventory, not values;
> - the prototype Google Sheet named in `PROJECT_CONTEXT.md`, only if the owner
>   wants its data transferred and the destination policy permits it.
>
> Do not transfer the live SQLite database, backups, logs, populated environment
> files, SSH private keys, Keychain data, provider credentials, or personal
> Calendar/Sheet contents as part of the Markdown handoff.

## 3. Claims in the original package that need qualification

| Original claim or implication | Audit verdict | Required qualification |
| --- | --- | --- |
| Deployment/runtime parity is unverified | Overbroad | Last known parity was operationally verified on 2026-10-13; it was not freshly rechecked in this audit. |
| Runtime operation is manual | Misleading as a project-state claim | Manual start is all the repository documents; the actual Home Mac uses a launchd job and external start script. |
| Phone-to-Mac transport is undefined / SSH is only a possibility | Incorrect outside repo scope | iPhone-to-bridge SSH and laptop SSH/Tailscale tunneling were implemented externally and acceptance-tested. Exact current artifacts are uninspected. |
| No Shortcut is implemented | Ambiguous | No Shortcut file is in Git; a functional external Shortcut existed. Its current export and health are unknown. |
| No backup procedure is known | Incorrect | A repeated pre-migration backup sequence is conversation-evidenced; restore remains unverified. |
| Live schema 9 and POS-026 behavior are unvalidated | Outdated | A dated transcript records schema 9, clean FK check, HTTP 200, and exact live acceptance. |
| Fix the live-smoke script first | Unsupported prioritization | It is a valid maintenance issue, but the approved continuation is dogfooding with no POS-027. |
| `BUILD_STATE.md` fully represents current validation | Incomplete | It omits the post-test live POS-026 acceptance and scopes “No live AI provider” too broadly. |

## 4. Information that cannot be recovered from available context

The following should remain explicitly unknown until separately supplied or
inspected:

1. The complete contents of the six downloadable narrative-package Markdown
   files and ZIP. Their sandbox download references are not readable local
   artifacts in this task.
2. A complete transcript inventory for every historical Personal OS
   conversation. The accessible task list is recency-limited, and several
   messages expose only “user attached file/image” placeholders.
3. The contents of historical uploaded diffs, screenshots, and Library
   artifacts whose attachments were not returned by conversation retrieval.
4. The current iPhone Shortcut definition, its exact actions after the last
   screenshots, whether an NFC/Action Button trigger was configured, and
   whether the phone flow still works after POS-026.
5. The current contents of `/Applications/personal-os.app`, the launchd plist,
   `start-http.sh`, SSH configuration, and Tailscale/sleep settings.
6. The Home Mac's present commit, dirty state, dependency versions, service
   health, log state, database integrity/content, and current backup inventory
   after the last 2026-10-13 evidence.
7. Whether any database backup has been integrity-checked, restored, or used
   for a successful rollback. Only backup creation is evidenced.
8. The exact current provider/model configuration for both inference
   boundaries, current quota/availability, and current hosted-model behavior.
   A live capture historically recorded Groq and `openai/gpt-oss-20b`; that is
   not a complete or perpetual configuration inventory.
9. GitHub state after the last verified merge/deployment evidence, including
   any newly opened issue, PR, branch, or project-board item not represented by
   the local refs.
10. The current contents and transfer suitability of the prototype Google
    Sheet, Google Calendar data, runtime database, logs, and other personal
    operational data. None should be inferred or copied.
11. Any future POS-027 objective. The available context explicitly leaves it
    unapproved and dependent on future dogfood evidence.

## 5. Coverage conclusion

This audit found enough accessible evidence to materially correct the technical
package, especially its deployment, external-integration, continuation, and
collaboration sections. It did not recover all historical conversations or the
actual narrative-package files, and it did not inspect the live host or
external artifacts. The result should therefore be treated as a high-confidence
correction to the technical handoff, not as proof of exhaustive migration
coverage.
