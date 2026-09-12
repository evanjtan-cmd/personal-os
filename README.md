# Personal OS

Personal OS is a personal-use AI operating system intended to turn captured
intent into structured state, recommend a concrete eligible action, track a
work session, and update that state. The product direction is described in
`PROJECT_CONTEXT.md`, and the executable MVP constraints are in
`docs/MVP_SPEC.md`.

## Current boundary

The completed minimal loop is exposed through a thin human-facing dogfood CLI.
POS-007 adds a read-only `state` inspection command over one coherent snapshot
of all canonical tables. Machine Interface v1 adds a separate one-shot
`personal-os-bridge` JSON stdin/stdout adapter for trusted local automation.
Both adapters use the same application services. Neither provides a timer,
background process, HTTP endpoint, network listener, Shortcut file, NFC action,
or UI. See `BUILD_STATE.md` for the exact state.

## Requirements and setup

- Python 3.12 or newer

Create and activate a virtual environment, then install the project and test
dependency:

```bash
python -m pip install -e ".[dev]"
```

Importing `personal_os` has no filesystem side effects.

Capture and recommendation each select an explicit inference provider and
model. Supported providers are `openai` and `groq`; both use the OpenAI Python
SDK's Responses interface with the same strict JSON schemas and fail-closed
application validation. The recommendation model never falls back to the
capture model. No provider or model is assumed, and no secret or `.env` file
belongs in the repository.

Capture, recommendation, and session start also require an explicit IANA
timezone, supplied either per command with `--timezone` or through
`PERSONAL_OS_TIMEZONE`. Personal OS does not infer the machine timezone.

For an OpenAI-hosted dogfood run, configure:

```bash
export PERSONAL_OS_CAPTURE_PROVIDER=openai
export PERSONAL_OS_RECOMMEND_PROVIDER=openai
export OPENAI_API_KEY=...
export PERSONAL_OS_CAPTURE_MODEL=...
export PERSONAL_OS_RECOMMEND_MODEL=...
export PERSONAL_OS_TIMEZONE=America/New_York
```

For Groq-hosted GPT-OSS inference, configure:

```bash
export PERSONAL_OS_CAPTURE_PROVIDER=groq
export PERSONAL_OS_RECOMMEND_PROVIDER=groq
export GROQ_API_KEY=...
export PERSONAL_OS_CAPTURE_MODEL=openai/gpt-oss-20b
export PERSONAL_OS_RECOMMEND_MODEL=openai/gpt-oss-120b
export PERSONAL_OS_TIMEZONE=America/New_York
```

Groq defaults to its official OpenAI-compatible base URL,
`https://api.groq.com/openai/v1`. A proxy or compatible Groq gateway can be
selected explicitly with `PERSONAL_OS_GROQ_BASE_URL`. Capture and recommendation
may use different supported providers. Provider API keys are read only when an
AI request is actually needed; `init-db`, session feedback, and active-session
display do not require them.

Groq currently describes its Responses API as beta. A configured model must
support Responses and strict JSON-schema output; GPT-OSS 20B and 120B satisfy
that requirement. Automated tests exercise the complete protocol with fake
clients but intentionally do not certify live provider availability, quotas, or
model-specific behavior.

An explicitly live, non-pytest smoke check is available for manual provider
verification:

```bash
PERSONAL_OS_LIVE_AI_SMOKE=1 python scripts/live_ai_smoke.py capture
PERSONAL_OS_LIVE_AI_SMOKE=1 python scripts/live_ai_smoke.py recommend
```

These commands make billable external requests. Without the exact opt-in value
`1`, the script exits before constructing a provider client.

## Initialize the database

The default runtime directory is `~/.personal-os/`, and the default database is
`~/.personal-os/personal_os.db`.

```bash
personal-os init-db
```

The equivalent module command is:

```bash
python -m personal_os init-db
```

Set `PERSONAL_OS_DATA_DIR` to override the runtime directory:

```bash
PERSONAL_OS_DATA_DIR=/path/outside/the/repository personal-os init-db
```

An explicit override is the user's responsibility. Do not place personal
runtime state inside this repository, and never commit databases, populated
environment files, credentials, logs, or secrets.

Initialization is always explicit. Product commands do not create, migrate, or
repair a database; run `personal-os init-db` first.

## Dogfood CLI

The available commands are:

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

`personal-os state` prints Projects, Tasks, Commitments, Rules, Inbox,
Captures, and Sessions in deterministic ID order. It requires an already-current
database, performs no migration or mutation, needs no timezone or AI provider
configuration, and intentionally omits interpretation payloads and provider
internals.

For example:

```text
Projects (1)
  #1 [ACTIVE] MVP
    Description: none
    Source capture: #1

Tasks (1)
  #1 [COMPLETED/MUST] Finish loop
    Project: #1
    Schedule: FLEXIBLE
    Deadline: none
    Estimate: 10 minutes
    Source capture: #1
```

A manual loop looks like:

```bash
personal-os init-db
personal-os capture "Finish my essay by Friday."
personal-os recommend --available-minutes 30
personal-os start 1 25 --available-minutes 30
personal-os active
personal-os progress --note "Finished the outline"
personal-os recommend
```

A recommendation is advisory. `start` always performs fresh authoritative
validation against current state and may reject a formerly valid task or
duration. A generated action stays ephemeral until the recommendation is
accepted with `start`; `--action` then preserves its exact text as session
history. Starting a session does not start a countdown, timer, Focus mode, or
background worker.

## Machine bridge

`personal-os-bridge` reads exactly one versioned JSON request from stdin,
writes exactly one JSON response to stdout, and exits. Its v1 operations are
`activate`, `recommend`, `start`, `feedback`, and `active`. `activate` is the
canonical availability-now operation: it returns current work when a session is
active, otherwise delegates to recommendation without starting work. It requires an already
initialized current-version database and never initializes or migrates state.
For example:

```bash
printf '%s\n' '{"version":1,"operation":"activate","timezone":"America/New_York","time_cap_minutes":20}' | personal-os-bridge
printf '%s\n' '{"version":1,"operation":"recommend","available_minutes":30,"timezone":"America/New_York"}' | personal-os-bridge
printf '%s\n' '{"version":1,"operation":"start","task_id":1,"planned_minutes":25,"timezone":"America/New_York","selected_action":"Draft the introduction."}' | personal-os-bridge
printf '%s\n' '{"version":1,"operation":"active"}' | personal-os-bridge
printf '%s\n' '{"version":1,"operation":"feedback","outcome":"PROGRESS","result_note":"Drafted two paragraphs."}' | personal-os-bridge
```

Successful responses use
`{"version":1,"ok":true,"operation":"...","result":{...}}`. Protocol errors
use exit status 2; expected Personal OS operational errors use exit status 1
and include a structured error object. The bridge has no authentication or
remote transport of its own. A trusted transport such as SSH may invoke it.
The human `personal-os` output remains intentionally human-readable and should
not be scraped as a machine contract.

## Tests

```bash
pytest
```

Architectural decisions are recorded in `DECISIONS.md`. Guidance for future
repository work is in `AGENTS.md`.
