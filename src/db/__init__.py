"""Relational data layer for the Fantacalcio research project.

Provide a normalised, self-documenting SQLite warehouse of every free data
source this project consumes: rosters, player-season advanced stats, match
results and trends, coach history and – once manually exported from a browser –
FBref tables that are otherwise blocked against automation.
"""

# Keep in sync with pyproject.toml [project] version. The version follows
# SemVer: bump the minor for any backwards-compatible addition to the schema
# or ingestion surface, the major for breaking changes.
__version__ = "0.5.0"

__all__ = ["__version__"]
