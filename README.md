# Personal OS

Personal OS is a personal-use AI operating system intended to turn captured
intent into structured state, recommend a concrete eligible action, track a
work session, and update that state. The product direction is described in
`PROJECT_CONTEXT.md`, and the executable MVP constraints are in
`docs/MVP_SPEC.md`.

## Current boundary

POS-003 provides durable natural-language capture, constrained OpenAI Responses
API interpretation, deterministic temporal resolution, and atomic application
to the canonical SQLite-backed state. These operations are currently a Python
API; the CLI remains limited to database initialization. Recommendations,
eligibility, sessions, calendar behavior, additional integrations, and user
interfaces are not implemented. See `BUILD_STATE.md` for the exact state.

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
