# Architectural Decisions

## 2026-08-28 — Python package foundation

Personal OS requires Python 3.12 or newer and uses a `src` package layout. The
package supports both `python -m personal_os` and a `personal-os` console entry
point. Imports perform no filesystem or database work.

## 2026-08-28 — SQLite and schema evolution

Local persistence uses Python's standard-library `sqlite3` module with no ORM.
SQLite `PRAGMA user_version` is the authoritative schema version, advanced by an
explicit ordered migration mechanism. Migrations and version changes are
transactional. Infrastructure schema version 1 intentionally contains no
product-domain tables.

## 2026-08-28 — External runtime state

Runtime state defaults to `~/.personal-os`, with `personal_os.db` as the database
filename. `PERSONAL_OS_DATA_DIR` is the single directory override. Runtime data
and secrets do not belong in Git.

## 2026-08-28 — Timestamp representation

Persisted Personal OS timestamps will be timezone-aware UTC values in one
normalized representation. Naive timestamps and invented local timezone data
are not valid persistence values. POS-001 has no timestamp-bearing domain
tables.

## 2026-08-28 — Thin interfaces

CLI, HTTP, Shortcut, NFC, voice, and other interfaces remain thin adapters over
centralized application and domain logic. POS-001's CLI exposes only database
initialization.
