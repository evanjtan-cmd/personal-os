# Build State

Last updated: 2026-08-28 for POS-001.

## Implemented

- Python 3.12+ project metadata with a `src` package layout.
- Importable `personal_os` package with no import-time filesystem side effects.
- Equivalent `personal-os` and `python -m personal_os` CLI entry points.
- Infrastructure-only `init-db` command.
- Runtime data defaults to `~/.personal-os/personal_os.db` and can be overridden
  with `PERSONAL_OS_DATA_DIR`.
- Runtime directories are created only when database initialization requires
  them.
- Standard-library SQLite persistence at schema version 1.
- `PRAGMA user_version` schema tracking with explicit ordered, transactional
  migrations.
- Idempotent current-version initialization and clear rejection of newer schemas
  or unversioned databases containing unexpected schema objects.
- Pytest coverage for package import, configuration, database initialization,
  migration rollback, incompatible states, and CLI behavior.
- Git ignore rules for runtime data, secrets, logs, environments, caches, test
  output, and build artifacts.

## Not implemented

- Natural-language capture or parsing
- Task, project, rule, or inbox domain models and workflows
- Eligibility or recommendation logic
- Work-session lifecycle or outcomes
- Calendar behavior or integrations
- AI or OpenAI calls
- Google Sheets or other imports
- HTTP endpoints, Shortcuts, NFC, voice, UI, notifications, or background work

## Validation

Run on 2026-08-28 with Python 3.12.13:

- `python -m pip install -e ".[dev]"` — passed; installed the editable package
  and pytest 8.4.2.
- `python -m pytest` — passed: 14 passed, 0 failed.
- `python -m personal_os --help` — passed with exit code 0.
- `personal-os --help` — passed with exit code 0.
- `python -m personal_os init-db` with an isolated temporary
  `PERSONAL_OS_DATA_DIR`, run twice — passed with exit code 0 at schema version
  1.
- `python -m compileall -q src tests` — passed.
- Direct isolated checks for configuration normalization, clean initialization,
  idempotence, incompatible schema rejection, and transactional rollback —
  passed.
- `python3 -m pip wheel --no-deps --no-build-isolation` against a temporary copy
  of the project — passed and produced `personal_os-0.1.0-py3-none-any.whl`;
  importing the package and running its module entry point from that wheel also
  passed, and the wheel contains the `personal-os` console entry point.
- `git diff --check` — passed.
