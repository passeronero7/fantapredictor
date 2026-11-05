import sqlite3

import pytest

from scripts.inventory_form_data import inventory
from src.db import database


def test_inventory_separates_provider_and_missing_values(tmp_path):
    path = tmp_path / 'source.db'
    conn = database.get_connection(path)
    database.init_schema(conn)
    conn.executescript('''
        INSERT INTO seasons(id,name,start_year) VALUES(1,'2020/21',2020);
        INSERT INTO sources(id,slug,name) VALUES(901,'test_a','A'),(902,'test_b','B');
        INSERT INTO players(id,full_name,normalized_name) VALUES(1,'Anonymous','anonymous');
        INSERT INTO player_season_stats(player_id,season_id,source_id,minutes,xg) VALUES(1,1,901,90,NULL),(1,1,902,NULL,0.2);
    ''')
    conn.commit()
    conn.close()
    out = inventory(path)
    groups = {row['provider']: row for row in out['season_stats_by_provider']}
    assert groups['test_a']['minutes'] == 1 and groups['test_a']['xg'] == 0
    assert groups['test_b']['minutes'] == 0 and groups['test_b']['xg'] == 1
    assert out['status'] == 'NOT_PROMOTABLE'
    assert len(out['snapshot_sha256']) == 64


def test_missing_or_incomplete_db_fails_without_creation(tmp_path):
    missing = tmp_path / 'missing.db'
    with pytest.raises(FileNotFoundError):
        inventory(missing)
    assert not missing.exists()
    path = tmp_path / 'incomplete.db'
    sqlite3.connect(path).close()
    with pytest.raises(ValueError, match='Missing tables'):
        inventory(path)
