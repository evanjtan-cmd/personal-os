# Personal OS

Personal OS is a personal-use AI operating system intended to turn captured
intent into structured state, recommend a concrete eligible action, track a
work session, and update that state. The product direction is described in
`PROJECT_CONTEXT.md`, and the executable MVP constraints are in
`docs/MVP_SPEC.md`.

## Current boundary

POS-006 exposes the completed minimal loop through a thin human-facing dogfood
CLI. Capture, deterministic eligibility, ephemeral recommendation, atomic
session start, and FINISHED/PROGRESS/BLOCKED feedback remain centralized in the
application services. POS-007 adds a read-only `state` inspection command over
one coherent snapshot of all canonical tables. The CLI is not a stable
machine-readable API and does not provide a timer, background process, HTTP
endpoint, Shortcut, NFC action, or UI. See `BUILD_STATE.md` for the exact state.

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
personal-os start TASK_ID MINUTES [--available-minutes N] [--reason TEXT] [--timezone ZONE]
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
duration. Starting a session records durable state only; it does not start a
countdown, timer, Focus mode, or background worker.

## Tests

```bash
pytest
```

Architectural decisions are recorded in `DECISIONS.md`. Guidance for future
repository work is in `AGENTS.md`.
