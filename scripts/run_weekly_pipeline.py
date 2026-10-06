#!/usr/bin/env python3
"""Unified One-Click Weekly In-Season Refresh & Lineup Advisory Pipeline.

Executes the complete in-season weekly maintenance lifecycle in strict reproducible order:
1. SQLite hot backup
2. Download fresh snapshot (prices, probable lineups, injuries, Understat, votes)
3. Ingestion into normalized warehouse
4. Availability return date derivation
5. Coach continuity verification
6. Lineup recommendation for the user's roster
"""

from __future__ import annotations

import argparse
import datetime
import json
import logging
import sqlite3
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from config.settings import config

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("weekly_pipeline")


def backup_database(db_path: Path, backup_dir: Path) -> Path:
    """Take a non-blocking hot backup of the SQLite warehouse."""
    backup_dir.mkdir(parents=True, exist_ok=True)
    target = backup_dir / "fantapredictor.db"
    logger.info(f"==> Step 1: Taking SQLite backup: {target}")
    with sqlite3.connect(db_path) as src, sqlite3.connect(target) as dst:
        src.backup(dst)
    logger.info(f"✓ Backup complete ({target.stat().st_size:,} bytes)")
    return target


def run_cmd(cmd: list[str | Path], cwd: Path | None = None) -> None:
    """Run subprocess command and fail closed on error."""
    cmd_str = " ".join(str(c) for c in cmd)
    logger.info(f"Running: {cmd_str}")
    res = subprocess.run([str(c) for c in cmd], cwd=cwd or ROOT, capture_output=True, text=True)
    if res.returncode != 0:
        logger.error(f"Command failed with exit code {res.returncode}:\n{res.stderr}")
        raise RuntimeError(f"Step failed: {cmd_str}\n{res.stderr}")
    if res.stdout.strip():
        logger.info(res.stdout.strip().split("\n")[-1])


def run_weekly_pipeline(
    matchday: int,
    skip_download: bool = False,
    roster_path: Path | None = None,
    defence_modifier: bool = True,
) -> None:
    data_dir = config.DATA_DIR
    season_dir = data_dir / "season_2026_27"
    db_path = data_dir / "fantapredictor.db"
    today_str = datetime.date.today().isoformat()
    today_tag = today_str.replace("-", "_")

    py = sys.executable

    logger.info(f"===========================================================")
    logger.info(f"FantaPredictor: In-Season Weekly Pipeline (Matchday {matchday})")
    logger.info(f"Data Dir: {data_dir}")
    logger.info(f"===========================================================")

    # 1. Hot Backup
    backup_folder = data_dir / "backups" / f"weekly_md{matchday}_{today_tag}_pre"
    backup_database(db_path, backup_folder)

    # 2. Download and ingest snapshot if not skipped
    snapshot_dir = season_dir / "raw" / f"refresh_{today_tag}"
    last_md = max(1, matchday - 1)

    if not skip_download:
        logger.info(f"==> Step 2: Downloading fresh snapshot to {snapshot_dir}")
        run_cmd([
            py, ROOT / "scripts/download_auction_snapshot.py",
            "--snapshot", snapshot_dir,
            "--last-matchday", str(last_md),
        ])

        logger.info(f"==> Step 3: Ingesting snapshot into SQLite")
        # Find latest league list
        league_lists = sorted(season_dir.glob("fantacalcio/lista_ufficiale_*.xlsx"))
        league_list = league_lists[-1] if league_lists else season_dir / "fantacalcio/lista_ufficiale_fantasborrati777_2026_09_24.xlsx"
        manifest_file = snapshot_dir / "acquisition_manifest.json"
        checked_at = datetime.datetime.now(datetime.timezone.utc).isoformat()
        if manifest_file.exists():
            manifest = json.loads(manifest_file.read_text())
            checked_at = manifest.get("checked_at", checked_at)

        run_cmd([
            py, ROOT / "scripts/prepare_auction_snapshot.py",
            "--snapshot", snapshot_dir,
            "--league-list", league_list,
            "--league-list-as-of", "2026-09-24",
            "--data-dir", data_dir,
            "--checked-at", checked_at,
        ])
    else:
        logger.info("==> Step 2 & 3: Skipping download & raw ingestion as requested")

    # 4. Ingest availability & derive return dates
    logger.info(f"==> Step 4: Deriving availability return dates as of {today_str}")
    avail_file = season_dir / "coaches/availability_current.csv"
    if avail_file.exists():
        run_cmd([
            py, ROOT / "scripts/ingest_availability.py",
            "--csv", avail_file,
            "--derive-dates",
            "--as-of", today_str,
        ])
        injuries_twin = season_dir / "coaches/injuries_2026_27.csv"
        injuries_twin.write_bytes(avail_file.read_bytes())

    # 5. Ingest coaches
    logger.info(f"==> Step 5: Checking coach assignments")
    coach_file = season_dir / "coaches/coach_history.csv"
    if coach_file.exists():
        run_cmd([
            py, ROOT / "scripts/ingest_coaches.py",
            "--csv", coach_file,
        ])

    # 6. Recommend lineup for the user's roster
    logger.info(f"==> Step 6: Generating Lineup Recommendation for Matchday {matchday}")
    lineup_cmd = [
        py, ROOT / "scripts/recommend_lineup.py",
        "--matchday", str(matchday),
    ]
    if roster_path:
        lineup_cmd.extend(["--roster", str(roster_path)])
    if not defence_modifier:
        lineup_cmd.append("--no-defence-modifier")

    # Run recommendation directly so output displays to user
    res = subprocess.run(lineup_cmd, cwd=ROOT)
    if res.returncode != 0:
        raise RuntimeError("Lineup recommendation failed")

    logger.info(f"✓ Weekly refresh and lineup recommendation completed successfully!")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--matchday", type=int, default=6, help="Target matchday (default: 6)")
    parser.add_argument("--skip-download", action="store_true", help="Skip online download and use local data")
    parser.add_argument("--roster", type=Path, help="User roster file (default: auto-detected in asta/)")
    parser.add_argument("--no-defence-modifier", action="store_true", help="Disable defence modifier calculation")
    args = parser.parse_args()

    run_weekly_pipeline(
        matchday=args.matchday,
        skip_download=args.skip_download,
        roster_path=args.roster,
        defence_modifier=not args.no_defence_modifier,
    )


if __name__ == "__main__":
    main()
