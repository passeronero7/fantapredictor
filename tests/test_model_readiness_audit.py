import json
import sqlite3
from pathlib import Path

import pytest

from scripts.audit_model_readiness import audit


def test_inventory_counts_missing_values_and_rejects_incomplete_bundles(tmp_path):
    db = tmp_path / 'warehouse.db'
    with sqlite3.connect(db) as conn:
        conn.executescript('''
        CREATE TABLE seasons(id INTEGER, name TEXT);
        CREATE TABLE players(id INTEGER, role TEXT);
        CREATE TABLE player_match_ratings(season_id INTEGER, player_id INTEGER, vote REAL, fantavoto REAL);
        CREATE TABLE matches(home_goals INTEGER, away_goals INTEGER, home_xg REAL, away_xg REAL);
        INSERT INTO seasons VALUES(1,'test');
        INSERT INTO players VALUES(1,'D');
        INSERT INTO player_match_ratings VALUES(1,1,6,NULL);
        INSERT INTO matches VALUES(1,0,NULL,NULL);
        ''')
    models = tmp_path / 'models'
    models.mkdir()
    (models / 'model_meta_bad.json').write_text(json.dumps({'artifacts': {'model': '../outside.keras'}}))
    result = audit(db, models)
    assert result['status'] == 'NOT_PROMOTABLE'
    assert result['ratings'][0]['fantavotes'] == 0
    assert result['match_coverage'] == {'matches': 1, 'results': 1, 'xg': 0}
    assert result['bundles'][0]['complete'] is False


def test_missing_database_is_not_created(tmp_path):
    db = tmp_path / 'missing.db'
    with pytest.raises(FileNotFoundError):
        audit(db, tmp_path)
    assert not db.exists()
