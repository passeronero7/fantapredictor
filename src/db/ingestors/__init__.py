"""Provider-specific loaders that populate the research warehouse.

Each ingestor exposes a single `load(conn, ...) -> None` function that ingests
one source's raw files into the given SQLite connection. Ingestors must be:

  * **Idempotent** — safe to re-run; they upsert or delete-and-insert by
    natural key.
  * **Offline** — they never open a network connection. They read from local
    raw files that a separate step downloaded (or a human exported by hand).
  * **Self-contained** — third-party dependencies are imported lazily inside
    the function body and documented in the module docstring.
"""

__all__ = [
    "coaches", "fbref", "football_data", "prices", "rosters", "understat", "votes",
]
