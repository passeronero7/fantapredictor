#!/usr/bin/env python3
"""Create a checksum manifest for private source snapshots."""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from config.settings import config
from src.db import __version__ as schema_version


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def build_manifest(data_dir: str | Path) -> dict[str, object]:
    """Return checksums for source files, excluding derived outputs."""
    data_dir = Path(data_dir)
    files = []
    for path in sorted(data_dir.rglob("*")):
        if not path.is_file() or path.name == "manifest.json":
            continue
        if any(part in {"outputs", "mid_outputs"} for part in path.relative_to(data_dir).parts):
            continue
        files.append({
            "path": path.relative_to(data_dir).as_posix(),
            "size": path.stat().st_size,
            "sha256": _sha256(path),
        })
    return {"schema_version": schema_version, "files": files}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-dir", type=Path, default=config.DATA_DIR)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    output = args.output or args.data_dir / "manifest.json"
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(build_manifest(args.data_dir), indent=2) + "\n", encoding="utf-8")
    print(f"Manifest: {output}")


if __name__ == "__main__":
    main()
