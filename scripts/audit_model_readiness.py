#!/usr/bin/env python3
"""Read-only inventory for the form-model research programme."""
import argparse
import json
import sqlite3
from pathlib import Path


def audit(db: Path, models: Path) -> dict:
    if not db.is_file():
        raise FileNotFoundError(db)
    result = {'status': 'NOT_PROMOTABLE', 'reasons': [], 'ratings': [], 'bundles': []}
    with sqlite3.connect(db.resolve().as_uri() + '?mode=ro', uri=True) as conn:
        result['ratings'] = [dict(zip(('season', 'role', 'rows', 'votes', 'fantavotes'), row)) for row in conn.execute('''
            SELECT s.name, COALESCE(p.role, 'unknown'), COUNT(*), COUNT(r.vote), COUNT(r.fantavoto)
            FROM player_match_ratings r JOIN seasons s ON s.id=r.season_id
            JOIN players p ON p.id=r.player_id GROUP BY s.name, p.role ORDER BY s.name, p.role
        ''')]
        result['match_coverage'] = dict(zip(('matches', 'results', 'xg'), conn.execute('''
            SELECT COUNT(*), COUNT(CASE WHEN home_goals IS NOT NULL AND away_goals IS NOT NULL THEN 1 END),
            COUNT(CASE WHEN home_xg IS NOT NULL AND away_xg IS NOT NULL THEN 1 END) FROM matches
        ''').fetchone()))
    for path in sorted(models.glob('model_meta_*.json')):
        entry = {'metadata': path.name, 'complete': False}
        try:
            meta = json.loads(path.read_text(encoding='utf-8'))
            files = meta.get('artifacts', {})
            entry['artifacts'] = files
            entry['complete'] = bool(files) and all(isinstance(v, str) and Path(v).name == v and (models / v).is_file() for v in files.values())
        except (OSError, ValueError, TypeError) as exc:
            entry['error'] = str(exc)
        result['bundles'].append(entry)
    result['reasons'].append('Inventory alone does not establish chronological validation or approval')
    if not any(b['complete'] for b in result['bundles']):
        result['reasons'].append('No complete model bundle found')
    result['limitations'] = ['Ratings do not identify eligible non-playing players or minutes', 'Counts do not establish historical availability at prediction cutoff', 'Completeness does not establish artifact integrity or predictive quality']
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--db', type=Path, required=True)
    parser.add_argument('--models', type=Path, required=True)
    parser.add_argument('--output', type=Path)
    args = parser.parse_args()
    report = json.dumps(audit(args.db, args.models), indent=2, ensure_ascii=False) + '\n'
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(report, encoding='utf-8')
    print(report, end='')


if __name__ == '__main__':
    main()
