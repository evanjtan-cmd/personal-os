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
application services. The CLI is not a stable machine-readable API and does not
provide a timer, background process, HTTP endpoint, Shortcut, NFC action, or UI.
See `BUILD_STATE.md` for the exact state.

## Requirements and setup

- Python 3.12 or newer

Create and activate a virtual environment, then install the project and test
dependency:

```bash
python -m pip install -e ".[dev]"
```

Importing `personal_os` has no filesystem side effects.

To use the production capture interpreter, set `PERSONAL_OS_CAPTURE_MODEL` to
an OpenAI model that supports strict structured output and provide
`OPENAI_API_KEY` through the standard SDK environment. No model is assumed and
no secret or `.env` file belongs in the repository.

The production recommendation ranker separately requires
`PERSONAL_OS_RECOMMEND_MODEL`; it never falls back to the capture model. It uses
the same standard `OPENAI_API_KEY` configuration.

Capture, recommendation, and session start also require an explicit IANA
timezone, supplied either per command with `--timezone` or through
`PERSONAL_OS_TIMEZONE`. Personal OS does not infer the machine timezone.

For a normal production dogfood run, configure:

```bash
export OPENAI_API_KEY=...
export PERSONAL_OS_CAPTURE_MODEL=...
export PERSONAL_OS_RECOMMEND_MODEL=...
export PERSONAL_OS_TIMEZONE=America/New_York
```

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
