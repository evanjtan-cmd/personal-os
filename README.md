# Personal OS

Personal OS is a personal-use AI operating system intended to turn captured
intent into structured state, recommend a concrete eligible action, track a
work session, and update that state. The product direction is described in
`PROJECT_CONTEXT.md`, and the executable MVP constraints are in
`docs/MVP_SPEC.md`.

## Current boundary

POS-001 provides repository and persistence infrastructure only. It does not
implement capture, task or project workflows, recommendations, sessions,
calendar behavior, AI behavior, integrations, or user interfaces. See
`BUILD_STATE.md` for the exact implemented state.

## Requirements and setup

- Python 3.12 or newer

Create and activate a virtual environment, then install the project and test
dependency:

```bash
python -m pip install -e ".[dev]"
```

Importing `personal_os` has no filesystem side effects.

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
