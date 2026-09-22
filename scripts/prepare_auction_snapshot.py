#!/usr/bin/env python3
"""Normalize saved public snapshots and the private league list, then load SQLite.

No network calls. Keep the input directory and its provenance manifest private.
The league XLSX, identified by provider ID, controls auction eligibility.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import shutil
from pathlib import Path

import pandas as pd
from bs4 import BeautifulSoup

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts.download_understat_season import build_match_frame
from scripts.reconcile_official_transfers import CLUB_CODES
from src.db import database
from src.db.ingestors import prices, rosters, understat, votes, football_data
from src.db.ingestors.common import club_id, player_id, number, source_id, start_run, finish_run
from src.utils.name_matching import normalize_name

INJURY_URL = 'https://www.fantacalcio.it/serie-a/indisponibili'
FORMATION_URL = 'https://www.fantacalcio.it/probabili-formazioni-serie-a'
PRICE_URL = 'https://www.fantacalcio.it/quotazioni-fantacalcio'


def parse_statistics(html: str) -> pd.DataFrame:
    records = []
    for tr in BeautifulSoup(html, 'html.parser').select('#stats tbody tr.player-row'):
        link = tr.select_one('a.player-link')
        row = {'player': link.get_text(' ', strip=True), 'source_ref': int(link['href'].rstrip('/').split('/')[-1])}
        for cell in tr.select('td[data-col-key]'):
            key, value = cell['data-col-key'], cell.get_text(' ', strip=True)
            if key == 'sq':
                row['club'] = CLUB_CODES[value]
            elif key == 'rig':
                made, attempted = value.split('/')
                row['penalties_scored'], row['penalties_attempted'] = number(made), number(attempted)
            else:
                row[key] = number(value)
        records.append(row)
    frame = pd.DataFrame(records)
    if frame.empty or frame.source_ref.duplicated().any():
        raise ValueError('Missing or duplicate provider IDs in statistics')
    return frame


def parse_formations(html: str, checked_at: str) -> pd.DataFrame:
    records = []
    clubs = {c.lower(): c for c in CLUB_CODES.values()}
    for team in BeautifulSoup(html, 'html.parser').select('.pitch .team'):
        links = team.select('.team-lineup a.player-link')
        if len(links) != 11:
            raise ValueError('Probable XI must contain 11 players')
        club_slugs = {link['href'].split('/squadre/')[1].split('/')[0] for link in links}
        if len(club_slugs) != 1:
            raise ValueError('Mixed clubs in probable XI')
        records.append({'club': clubs[club_slugs.pop()], 'module': team.get('data-team-formation'),
                        'titulars': '; '.join(link.get_text(' ', strip=True) for link in links),
                        'source_refs': ';'.join(link['href'].rstrip('/').split('/')[-1] for link in links),
                        'source': FORMATION_URL, 'checked_at': checked_at})
    frame = pd.DataFrame(records)
    if len(frame) != 20 or frame.club.nunique() != 20:
        raise ValueError('Expected exactly 20 distinct club formations')
    return frame


def parse_injuries(html: str, checked_at: str) -> pd.DataFrame:
    records = []
    soup = BeautifulSoup(html, 'html.parser')
    cards = soup.select('.team-card')
    if len(cards) != 20:
        raise ValueError('Expected all 20 clubs on availability page')
    for card in cards:
        club = card.select_one('.team-name').get_text(strip=True)
        for li in card.select('li'):
            name, description = li.select_one('.item-name'), li.select_one('.item-description')
            if name is None or description is None:
                continue
            note = description.get_text(' ', strip=True)
            records.append({'player': name.get_text(strip=True), 'club': club,
                            'kind': 'suspension' if 'squalificat' in note.lower() else 'injury_evaluation',
                            'expected_return': None, 'note': note,
                            'source_url': INJURY_URL, 'checked_at': checked_at})
    return pd.DataFrame(records)


def merge_league_list(public: pd.DataFrame, league: pd.DataFrame) -> pd.DataFrame:
    """Fail closed for missing players; never infer eligibility from quotations."""
    if league['#'].duplicated().any() or public.source_ref.duplicated().any():
        raise ValueError('Duplicate provider ID')
    official = league.rename(columns={'#': 'source_ref', 'Nome': 'league_name', 'Sq.': 'league_club', 'R.': 'league_role'})
    merged = public.merge(official[['source_ref', 'league_name', 'league_club', 'league_role', 'Fuori lista']],
                          on='source_ref', how='outer', indicator=True, validate='one_to_one')
    merged['in_league_list'] = merged['_merge'].ne('left_only').astype(int)
    merged['fuori_lista'] = (merged['_merge'].ne('both') | merged['Fuori lista'].fillna('').astype(str).str.strip().ne('')).astype(int)
    merged['player'] = merged['player'].fillna(merged['league_name'])
    merged['team'] = merged['team'].map(lambda v: CLUB_CODES.get(v, v)).fillna(merged['league_club'])
    # A team disagreement needs review; role eligibility remains the league's.
    conflict = merged['_merge'].eq('both') & merged['team'].ne(merged['league_club'])
    merged.loc[conflict, 'fuori_lista'] = 1
    merged['role_classic'] = merged['league_role'].fillna(merged['role_classic'])
    merged['player_normalized'] = merged['player'].map(normalize_name)
    merged['public_current'] = merged['_merge'].ne('right_only')
    return merged.drop(columns=['_merge', 'Fuori lista'])


def name_agrees(full_name: str, fantasy_name: str) -> bool:
    """Match whole name tokens and explicit initials, never edit distance."""
    full = normalize_name(full_name.translate(str.maketrans({'ø':'o','Ø':'O','ł':'l','Ł':'L','đ':'d'}))).replace('-', ' ').split()
    raw = fantasy_name.split()
    required, initials = [], []
    for token in raw:
        norm = normalize_name(token.replace('.', ' ') if token.endswith('.') else token).replace('-', ' ').split()
        (initials if token.endswith('.') else required).extend(norm)
    if not required or not set(required).issubset(full):
        return False
    remaining = [t for t in full if t not in required]
    return all(any(t.startswith(initial) for t in remaining) for initial in initials)


def bridge_understat(conn, frame, public):
    """Move source-specific references only after a unique, club-scoped match.

    Preserve all universal players and their other sources. The bridge report
    records each decision, and leaves ambiguous names unresolved.
    """
    records = []
    sid = source_id(conn, 'understat')
    for row in frame.to_dict('records'):
        clubs = {database.TEAM_ALIAS_MAP.get(t.strip(),t.strip()) for t in row['team_title'].split(',')}
        pool = public[public.team.isin(clubs)]
        if 'position' in row and pd.notna(row['position']):
            is_keeper = 'GK' in str(row['position'])
            pool = pool[pool.role_classic.eq('P') if is_keeper else pool.role_classic.ne('P')]
        candidates = [p for p in pool.to_dict('records') if name_agrees(row['player_name'],p['player'])]
        if len(candidates) != 1:
            records.append({'understat_id':row['id'],'understat_name':row['player_name'],'club':row['team_title'],
                            'status':'unresolved','candidates':';'.join(p['player'] for p in candidates)})
            continue
        match = candidates[0]
        pid = player_id(conn,match['player'],'fantacalcio',int(match['source_ref']),match['role_classic'])
        ref = str(row['id'])
        # Do not combine colliding source rows automatically.
        old = conn.execute('SELECT player_id FROM player_aliases WHERE source_id=? AND source_ref=?',(sid,ref)).fetchall()
        if len(old) > 1:
            raise ValueError(f'Ambiguous existing Understat alias {ref}')
        conn.execute('UPDATE player_aliases SET player_id=? WHERE source_id=? AND source_ref=?',(pid,sid,ref))
        conn.execute('INSERT OR IGNORE INTO player_aliases(player_id,source_id,source_ref,label) VALUES(?,?,?,?)',
                     (pid,sid,ref,row['player_name']))
        conn.execute('UPDATE player_season_stats SET player_id=? WHERE source_id=? AND source_ref=?',(pid,sid,ref))
        records.append({'understat_id':row['id'],'understat_name':row['player_name'],'club':row['team_title'],
                        'status':'matched','fantacalcio_id':match['source_ref'],'fantacalcio_name':match['player'],
                        'rule':'unique whole tokens and initials within current club'})
    conn.commit()
    return pd.DataFrame(records)


def load_statistics(conn, frame, season_id, source_file):
    sid = source_id(conn, 'fantacalcio')
    run, _ = start_run(conn, 'fantacalcio')
    count = 0
    # This table represents the active provider season-summary snapshot.  Raw
    # dated HTML/CSV files retain the audit trail; keeping one database row per
    # snapshot would make the active value ambiguous because source_file is
    # part of the historical uniqueness key.
    conn.execute('''DELETE FROM player_season_stat_values
        WHERE season_id=? AND category='fantacalcio_summary' AND source_id=?''',
        (season_id, sid))
    for row in frame.to_dict('records'):
        pid = player_id(conn, row['player'], 'fantacalcio', row['source_ref'])
        cid = club_id(conn, row['club'], 'fantacalcio')
        for metric, value in row.items():
            if metric in {'player', 'source_ref', 'club'} or pd.isna(value):
                continue
            conn.execute('''INSERT INTO player_season_stat_values
                (player_id,club_id,season_id,category,metric,metric_label,value,source_id,source_file)
                VALUES (?,?,?,'fantacalcio_summary',?,?,?,?,?)
                ON CONFLICT(player_id,club_id,season_id,category,metric,source_id,source_file)
                DO UPDATE SET value=excluded.value,updated_at=datetime('now')''',
                (pid,cid,season_id,metric,metric,float(value),sid,str(source_file)))
            count += 1
    finish_run(conn, run, 'ok', count)
    conn.commit()
    return count


def prepare(snapshot: Path, league_path: Path, data_dir: Path, checked_at: str):
    season_dir = data_dir / 'season_2026_27'
    public = pd.read_csv(snapshot / 'prices_public.csv')
    league = pd.read_excel(league_path)
    merged = merge_league_list(public, league)
    stats = parse_statistics((snapshot / 'statistics.html').read_text())
    form = parse_formations((snapshot / 'formations.html').read_text(), checked_at)
    injuries = parse_injuries((snapshot / 'injuries.html').read_text(), checked_at)
    payload = json.loads((snapshot / 'understat_payload.html').read_text())
    fixtures = build_match_frame(payload['dates'], 2026, checked_at, include_future=True)
    # Reject invalid round assignments, rather than silently using array order.
    for md, block in fixtures.groupby('matchday'):
        clubs = list(block.home_team) + list(block.away_team)
        if len(block) != 10 or len(set(clubs)) != 20:
            raise ValueError(f'Invalid calendar round {md}; explicit round reconciliation required')
    if len(fixtures) != 380 or fixtures.duplicated(['home_team', 'away_team']).any():
        raise ValueError('Incomplete/duplicate calendar')
    for directory in ['fantacalcio', 'coaches', 'raw', 'reports']:
        (season_dir / directory).mkdir(parents=True, exist_ok=True)
    if (snapshot/'votes').exists():
        shutil.copytree(snapshot/'votes',season_dir/'fantacalcio/voti',dirs_exist_ok=True)
    merged.to_csv(season_dir / 'fantacalcio/prices.csv', index=False)
    stats_path = season_dir / 'fantacalcio/season_summary.csv'
    stats.to_csv(stats_path, index=False)
    form.to_csv(season_dir / 'coaches/probable_formations_2026_27.csv', index=False)
    injuries.to_csv(season_dir / 'coaches/availability_current.csv', index=False)
    injuries.to_csv(season_dir / 'coaches/injuries_2026_27.csv', index=False)
    fixtures.to_csv(season_dir / 'raw/understat_serie_a_2026_matches.csv', index=False)
    player_frame = pd.read_csv(snapshot / 'understat_serie_a_2026_season.csv')
    player_frame.to_csv(season_dir / 'raw/understat_serie_a_2026_season.csv', index=False)
    fd_target = data_dir / 'raw/football-data.co.uk/2627/I1.csv'
    fd_target.parent.mkdir(parents=True, exist_ok=True)
    fd_target.write_bytes((snapshot / 'football-data/2627/I1.csv').read_bytes())
    roster_path = season_dir / 'rosters/virgilio_rosters_2026_27.csv'
    roster = pd.read_csv(roster_path).fillna('')
    new_rows = []
    for row in merged[merged.public_current].to_dict('records'):
        key = normalize_name(row['player'])
        same = roster.player.map(normalize_name).eq(key)
        old = same & roster.club_2026_27.ne(row['team'])
        roster.loc[old, ['status','source_url','checked_at']] = ['excluded', PRICE_URL, checked_at]
        here = same & roster.club_2026_27.eq(row['team'])
        if here.any():
            roster.loc[here, ['status','role','source_url','checked_at']] = ['confirmed',row['role_classic'],PRICE_URL,checked_at]
        else:
            new_rows.append({'player':row['player'],'club':row['team'],'club_2026_27':row['team'],
                             'role':row['role_classic'],'status':'confirmed','source_url':PRICE_URL,'checked_at':checked_at})
    roster = pd.concat([roster, pd.DataFrame(new_rows)], ignore_index=True)
    roster.to_csv(roster_path, index=False)
    conn = database.get_connection(data_dir / 'fantapredictor.db')
    database.init_schema(conn)
    counts = {}
    counts['prices'] = prices.load(conn, season_dir / 'fantacalcio/prices.csv', '2627')
    counts['roster_rows'] = rosters.load(conn, roster_path, '2627')
    # Some provider IDs already resolve to older display spellings. Assert
    # membership on that canonical identity, and retain a rebuildable CSV row.
    sid_season = conn.execute("SELECT id FROM seasons WHERE name='2026/27'").fetchone()[0]
    canonical_rows = []
    for row in merged[merged.public_current].to_dict('records'):
        pid = player_id(conn,row['player'],'fantacalcio',int(row['source_ref']),row['role_classic'])
        cid = club_id(conn,row['team'],'fantacalcio')
        conn.execute("UPDATE roster_memberships SET status='excluded',source_url=?,checked_at=? WHERE player_id=? AND season_id=? AND club_id!=?",
                     (PRICE_URL,checked_at,pid,sid_season,cid))
        conn.execute('''INSERT INTO roster_memberships(player_id,club_id,season_id,role,status,source_url,checked_at)
            VALUES (?,?,?,?,'confirmed',?,?) ON CONFLICT(player_id,club_id,season_id)
            DO UPDATE SET role=excluded.role,status='confirmed',source_url=excluded.source_url,checked_at=excluded.checked_at''',
            (pid,cid,sid_season,row['role_classic'],PRICE_URL,checked_at))
        canonical = conn.execute('SELECT full_name FROM players WHERE id=?',(pid,)).fetchone()[0]
        old = roster.player.eq(canonical) & roster.club_2026_27.ne(row['team'])
        roster.loc[old,['status','source_url','checked_at']] = ['excluded',PRICE_URL,checked_at]
        here = roster.player.eq(canonical) & roster.club_2026_27.eq(row['team'])
        if here.any():
            roster.loc[here,['status','role','source_url','checked_at']] = ['confirmed',row['role_classic'],PRICE_URL,checked_at]
        else:
            canonical_rows.append({'player':canonical,'club':row['team'],'club_2026_27':row['team'],
                                   'role':row['role_classic'],'status':'confirmed','source_url':PRICE_URL,'checked_at':checked_at})
    pd.concat([roster,pd.DataFrame(canonical_rows)],ignore_index=True).to_csv(roster_path,index=False)
    conn.commit()
    bridge = bridge_understat(conn, player_frame, merged[merged.public_current])
    bridge.to_csv(season_dir / 'reports/understat_identity_bridge.csv', index=False)
    counts['understat_linked'] = int(bridge.status.eq('matched').sum())
    counts['understat_players'] = understat.load(conn, season_dir / 'raw/understat_serie_a_2026_season.csv')
    counts['calendar'] = understat.load_matches(conn, season_dir / 'raw/understat_serie_a_2026_matches.csv')
    counts['football_data_matches'] = football_data.load(conn, fd_target.parent)
    counts['votes'] = votes.load(conn, season_dir / 'fantacalcio/voti', '2627')
    season_id = conn.execute("SELECT id FROM seasons WHERE name='2026/27'").fetchone()[0]
    counts['summary_metrics'] = load_statistics(conn, stats, season_id, stats_path)
    # Exact provider identities, club scoped: preserve unknown identity as a gap.
    lookup = {(normalize_name(r['player']),r['team']): r for r in merged.to_dict('records')}
    unmatched = []
    current_ids = []
    for row in injuries.to_dict('records'):
        match = lookup.get((normalize_name(row['player']),row['club']))
        if match is None:
            unmatched.append({'player':row['player'],'club':row['club']})
            continue
        pid = player_id(conn, match['player'], 'fantacalcio', int(match['source_ref']))
        current_ids.append(pid)
        # Replace obsolete kinds/return dates for this identified player only.
        conn.execute('DELETE FROM availability_notes WHERE player_id=?', (pid,))
        conn.execute('''INSERT INTO availability_notes
            (player_id,club,kind,expected_return,source_url,checked_at) VALUES (?,?,?,?,?,?)''',
            (pid,row['club'],row['kind'],None,INJURY_URL,checked_at))
    # Superseded old notes are not current absence evidence. Keep originals in backup.
    conn.execute('DELETE FROM availability_notes WHERE checked_at < ?', (checked_at[:10],))
    conn.commit()
    counts.update({'eligible':int(merged.fuori_lista.eq(0).sum()), 'clubs':merged.team.nunique(),
                   'availability':len(current_ids),'unmatched_availability':unmatched,
                   'integrity':conn.execute('PRAGMA integrity_check').fetchone()[0],
                   'foreign_key_errors':len(conn.execute('PRAGMA foreign_key_check').fetchall())})
    conn.close()
    report = {'checked_at':checked_at,'season':'2026/27','league_list':str(league_path),
              'league_list_as_of':'2026-09-05','return_date_policy':'Unknown unless explicitly dated; narrative retained in CSV.',**counts}
    (season_dir / f'reports/refresh_{checked_at[:10].replace("-","_")}.json').write_text(json.dumps(report,indent=2,ensure_ascii=False)+'\n')
    return report


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--snapshot', type=Path, required=True)
    parser.add_argument('--league-list', type=Path, required=True)
    parser.add_argument('--data-dir', type=Path, required=True)
    parser.add_argument('--checked-at', required=True)
    args = parser.parse_args()
    print(json.dumps(prepare(args.snapshot,args.league_list,args.data_dir,args.checked_at),indent=2,ensure_ascii=False))
