#!/usr/bin/env python3
"""Produce a read-only, provider-separated inventory from a SQLite snapshot."""
import argparse
import hashlib
import json
import sqlite3
import tempfile
from datetime import datetime, timezone
from pathlib import Path


def inventory(database: Path) -> dict:
    if not database.is_file():
        raise FileNotFoundError(database)
    with tempfile.TemporaryDirectory() as directory:
        snapshot = Path(directory) / 'snapshot.db'
        with sqlite3.connect(database.resolve().as_uri() + '?mode=ro', uri=True) as source:
            with sqlite3.connect(snapshot) as copy:
                source.backup(copy)
        digest = hashlib.sha256(snapshot.read_bytes()).hexdigest()
        with sqlite3.connect(snapshot.resolve().as_uri() + '?mode=ro', uri=True) as conn:
            conn.row_factory = sqlite3.Row
            tables = [r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name")]
            def rows(query):
                return [dict(row) for row in conn.execute(query)]
            required = {'sources', 'seasons', 'player_match_ratings', 'player_season_stats', 'match_team_stats', 'matches', 'availability_notes'}
            if required - set(tables):
                raise ValueError(f'Missing tables: {sorted(required - set(tables))}')
            return {
                'snapshot_sha256': digest,
                'snapshot_method': 'sqlite backup, includes committed WAL',
                'generated_at': datetime.now(timezone.utc).isoformat(),
                'tables': {table: conn.execute('SELECT COUNT(*) FROM "' + table.replace('"', '""') + '"').fetchone()[0] for table in tables},
                'ratings_by_provider_season': rows('''SELECT s.name season, COALESCE(src.slug, 'unknown') provider, COUNT(*) rows, COUNT(r.vote) votes, COUNT(r.fantavoto) fantavotes, COUNT(DISTINCT r.player_id) players FROM player_match_ratings r LEFT JOIN seasons s ON s.id=r.season_id LEFT JOIN sources src ON src.id=r.source_id GROUP BY s.name,src.slug ORDER BY s.name,src.slug'''),
                'season_stats_by_provider': rows('''SELECT s.name season, COALESCE(src.slug, 'unknown') provider, COUNT(*) rows, COUNT(p.minutes) minutes, COUNT(p.xg) xg, COUNT(p.xa) xa, COUNT(DISTINCT p.player_id) players FROM player_season_stats p LEFT JOIN seasons s ON s.id=p.season_id LEFT JOIN sources src ON src.id=p.source_id GROUP BY s.name,src.slug ORDER BY s.name,src.slug'''),
                'team_stats_by_match_provider': rows('''SELECT s.name season, COALESCE(src.slug, 'unknown') match_provider, COUNT(*) rows, COUNT(t.xg) xg FROM match_team_stats t JOIN matches m ON m.id=t.match_id LEFT JOIN seasons s ON s.id=m.season_id LEFT JOIN sources src ON src.id=m.source_id GROUP BY s.name,src.slug ORDER BY s.name,src.slug'''),
                'availability': dict(conn.execute('''SELECT COUNT(*) total, COUNT(player_id) matched_player, COUNT(source_url) sourced, COUNT(checked_at) checked, COUNT(expected_return) dated_return FROM availability_notes''').fetchone()),
                'possible_rating_duplicates': rows('''SELECT s.name season, COUNT(*) groups, SUM(n-1) extra_rows FROM (SELECT season_id,matchday,player_id,COUNT(*) n FROM player_match_ratings GROUP BY season_id,matchday,player_id HAVING COUNT(*)>1) d LEFT JOIN seasons s ON s.id=d.season_id GROUP BY s.name'''),
                'limits': ['Counts are provider-specific and are not deduplicated across sources', 'Season minutes are not per-match minutes', 'Availability notes have no historical revisions; checked_at is not publication time', 'Unknown eligible nonplayers and lineup labels cannot be reconstructed from ratings alone', 'Team stats source is the match provider, not necessarily the original xG provider', 'No source freshness or historical availability is inferred from row presence'],
                'status': 'NOT_PROMOTABLE',
            }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--db', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    result = inventory(args.db)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2, ensure_ascii=False) + '\n', encoding='utf-8')
    print(f"Inventory saved: {args.output}; snapshot SHA-256 {result['snapshot_sha256']}")


if __name__ == '__main__':
    main()
