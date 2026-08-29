# Repository Guidance

These instructions apply to all work in this repository.

## Before meaningful work

- Inspect the actual repository and working-tree state before implementing a ticket.
- Read `PROJECT_CONTEXT.md`, `docs/MVP_SPEC.md`, `BUILD_STATE.md`, and
  `DECISIONS.md`.
- Treat the code and tests as authoritative for what is currently implemented.
- Stay within the approved ticket. Record unrelated discoveries as follow-ups
  rather than fixing them opportunistically.

## Product and architecture boundaries

- Handle hard facts and eligibility deterministically whenever possible. AI may
  interpret or rank, but it must not invent dates, deadlines, conflicts,
  availability, dependencies, or completion state.
- Keep CLI, HTTP, Shortcut, NFC, voice, and other interfaces thin. Centralize
  application and domain behavior behind them.
- Projects are planning containers, not executable actions.
- Do not add speculative abstractions for future commercial scale.

## Data and validation

- Never commit personal runtime data, databases, logs, credentials, API keys,
  secrets, or populated environment files.
- Use isolated temporary storage in tests. Tests must not read or mutate the
  user's real Personal OS data directory.
- Run the documented validation commands relevant to a change.

## Documentation maintenance

- Update `BUILD_STATE.md` whenever implemented behavior changes.
- Update `DECISIONS.md` only when an enduring architectural decision changes.
- Do not modify `PROJECT_CONTEXT.md` without an explicitly approved,
  product-level reason.

