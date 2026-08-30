# Personal OS

Personal OS is a personal-use AI operating system intended to turn captured
intent into structured state, recommend a concrete eligible action, track a
work session, and update that state. The product direction is described in
`PROJECT_CONTEXT.md`, and the executable MVP constraints are in
`docs/MVP_SPEC.md`.

## Current boundary

POS-005 completes the minimal internal loop through Python APIs: constrained
capture, deterministic eligibility, ephemeral recommendation, atomic session
start, and FINISHED/PROGRESS/BLOCKED feedback with durable session history.
The CLI remains limited to database initialization. Calendar integrations,
product-facing interfaces, and post-MVP automation are not implemented. See
`BUILD_STATE.md` for the exact state.

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

## Tests

```bash
pytest
```

Architectural decisions are recorded in `DECISIONS.md`. Guidance for future
repository work is in `AGENTS.md`.
