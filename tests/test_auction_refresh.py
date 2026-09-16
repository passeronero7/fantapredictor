import tempfile
import unittest
from pathlib import Path

import pandas as pd

from scripts.build_auction_dossier import allocate_market, SLOTS, BUDGETS
from scripts.prepare_auction_snapshot import merge_league_list, name_agrees, load_statistics, bridge_understat
from scripts.download_understat_season import build_match_frame
from src.db import database, repository
from src.db.ingestors import prices, understat, votes
from src.data_processing.prices_processor import match_prices_to_roster
from scripts.validate_release import priced_confirmed_role_counts


class AuctionRefreshTests(unittest.TestCase):
    def setUp(self):
        self.conn = database.get_connection(':memory:')
        database.init_schema(self.conn)
        self.tmp = tempfile.TemporaryDirectory()
        self.path = Path(self.tmp.name)/'prices.csv'

    def tearDown(self):
        self.conn.close()
        self.tmp.cleanup()

    def price_frame(self):
        return pd.DataFrame([{'player':'Test','source_ref':123,'team':'Roma','role_classic':'A',
                              'price_current':10,'fvm':20,'in_league_list':1,'fuori_lista':0}])

    def test_eligibility_survives_public_refresh_and_reingest_is_idempotent(self):
        frame = self.price_frame()
        frame.to_csv(self.path,index=False)
        prices.load(self.conn,self.path,'2627')
        frame.drop(columns=['in_league_list','fuori_lista']).assign(price_current=11).to_csv(self.path,index=False)
        prices.load(self.conn,self.path,'2627')
        prices.load(self.conn,self.path,'2627')
        rows=repository.load_prices(self.conn,'2627')
        self.assertEqual(len(rows),1)
        self.assertEqual(rows.iloc[0].fuori_lista,0)
        self.assertEqual(rows.iloc[0].price_current,11)

    def test_unknown_eligibility_is_excluded(self):
        self.price_frame().drop(columns=['in_league_list','fuori_lista']).to_csv(self.path,index=False)
        prices.load(self.conn,self.path,'2627')
        self.assertEqual(repository.load_prices(self.conn,'2627').iloc[0].fuori_lista,1)

    def test_invalid_eligibility_rejected(self):
        self.price_frame().assign(fuori_lista=2).to_csv(self.path,index=False)
        with self.assertRaises(ValueError):
            prices.load(self.conn,self.path,'2627')

    def test_existing_v5_migrates_without_losing_prices(self):
        self.conn.execute('ALTER TABLE player_prices DROP COLUMN in_league_list')
        self.conn.execute('ALTER TABLE player_prices DROP COLUMN fuori_lista')
        self.conn.execute('PRAGMA user_version=5')
        database.init_schema(self.conn)
        database.init_schema(self.conn)
        self.assertIn('fuori_lista',{r['name'] for r in self.conn.execute('PRAGMA table_info(player_prices)')})
        self.assertEqual(self.conn.execute('PRAGMA user_version').fetchone()[0],6)

    def test_league_list_controls_roles_exclusions_and_new_players(self):
        public=pd.DataFrame([{'source_ref':i,'player':f'Player{i}','team':'ROM','role_classic':'A'} for i in [1,2,3,5]])
        league=pd.DataFrame([{'#':1,'Nome':'Player1','Sq.':'Roma','R.':'C','Fuori lista':None},
                             {'#':2,'Nome':'Player2','Sq.':'Roma','R.':'A','Fuori lista':'*'},
                             {'#':4,'Nome':'Player4','Sq.':'Roma','R.':'A','Fuori lista':None},
                             {'#':5,'Nome':'Player5','Sq.':'Milan','R.':'A','Fuori lista':None}])
        result=merge_league_list(public,league).set_index('source_ref')
        self.assertEqual(result.loc[1,'role_classic'],'C')
        self.assertEqual(result.loc[1,'fuori_lista'],0)
        self.assertTrue(result.loc[[2,3,4,5],'fuori_lista'].eq(1).all())

    def test_namesakes_and_initials(self):
        self.assertTrue(name_agrees('Lautaro Martinez','Martinez L.'))
        self.assertFalse(name_agrees('Josep Martinez','Martinez L.'))
        self.assertTrue(name_agrees('Charles De Ketelaere','De Ketelaere'))
        self.assertFalse(name_agrees('Lorenzo Pellegrini','Pellegrino'))
        self.assertTrue(name_agrees('Francesco Pio Esposito','Esposito F.P.'))
        self.assertTrue(name_agrees('Rasmus Højlund','Hojlund'))

    def test_canonical_club_names_and_excluded_players_at_release_gate(self):
        roster=pd.DataFrame([{'player':'Test','club':'Roma','role':'A','status':'confirmed'}])
        roster_path=Path(self.tmp.name)/'roster.csv'
        roster.to_csv(roster_path,index=False)
        frame=self.price_frame()
        self.assertEqual(match_prices_to_roster(roster,frame).iloc[0].roster_index,0)
        frame.assign(fuori_lista=1).to_csv(self.path,index=False)
        self.assertEqual(priced_confirmed_role_counts(roster_path,self.path),{})

    def test_transferred_season_aggregate_replaces_stale_club_only(self):
        frame=pd.DataFrame([{'id':123,'player_name':'Test','team_title':'Roma','year':2026,
                              'xG':1.0,'xA':.5,'time':90}])
        frame.to_csv(self.path,index=False)
        understat.load(self.conn,self.path)
        frame.assign(team_title='Milan',time=180,xG=2).to_csv(self.path,index=False)
        understat.load(self.conn,self.path)
        self.assertEqual(self.conn.execute('SELECT count(*) FROM player_season_stats').fetchone()[0],1)
        self.assertEqual(self.conn.execute('SELECT minutes FROM player_season_stats').fetchone()[0],180)
        self.assertEqual(self.conn.execute('SELECT count(*) FROM players').fetchone()[0],1)

    def test_ambiguous_identity_bridge_does_not_create_alias(self):
        public=pd.DataFrame([{'player':'Esposito','team':'Inter'}, {'player':'Esposito F.','team':'Inter'}])
        data=pd.DataFrame([{'player_name':'Francesco Esposito','team_title':'Inter','id':99}])
        report=bridge_understat(self.conn,data,public)
        self.assertEqual(report.iloc[0].status,'unresolved')
        self.assertEqual(self.conn.execute('SELECT count(*) FROM player_aliases').fetchone()[0],0)

    def test_budget_conservation_for_eight_managers(self):
        frame=pd.DataFrame([{'role':role,'source_ref':i,'fvm':100-i} for role,slots in SLOTS.items() for i in range(8*slots+2)])
        result=allocate_market(frame,BUDGETS['con_modificatore'])
        for role,slots in SLOTS.items():
            selected=frame[frame.role.eq(role)].head(8*slots).index
            self.assertAlmostEqual(result.loc[selected].sum(),8*BUDGETS['con_modificatore'][role])
        self.assertTrue(result.ge(1).all())

    def test_future_fixtures_keep_null_scores_and_do_not_count_as_played(self):
        dates=[{'id':1,'isResult':True,'h':{'id':1,'title':'Roma'},'a':{'id':2,'title':'Milan'},
                'goals':{'h':1,'a':0},'xG':{'h':1.2,'a':0.8},'datetime':'2026-08-23'},
               {'id':2,'isResult':False,'h':{'id':2,'title':'Milan'},'a':{'id':1,'title':'Roma'},
                'goals':{'h':None,'a':None},'xG':{'h':None,'a':None},'datetime':'2026-09-20'}]
        frame=build_match_frame(dates,2026,'2026-09-16',include_future=True)
        frame.to_csv(self.path,index=False)
        understat.load_matches(self.conn,self.path)
        understat.load_matches(self.conn,self.path)
        self.assertEqual(self.conn.execute('SELECT count(*) FROM matches').fetchone()[0],2)
        self.assertEqual(self.conn.execute('SELECT count(*) FROM match_team_stats').fetchone()[0],2)
        self.assertEqual(len(repository.load_team_match_stats(self.conn,'2627')),2)
        # Add a second provider's description of the completed fixture.
        sid=self.conn.execute("SELECT id FROM sources WHERE slug='football-data.co.uk'").fetchone()[0]
        self.conn.execute('''INSERT INTO matches(season_id,matchday,match_date,home_club_id,away_club_id,
            home_goals,away_goals,source_id,source_match_id)
            SELECT season_id,matchday,match_date,home_club_id,away_club_id,home_goals,away_goals,?,'duplicate'
            FROM matches WHERE source_match_id='1' ''',(sid,))
        duplicate=self.conn.execute('SELECT last_insert_rowid()').fetchone()[0]
        self.conn.execute('''INSERT INTO match_team_stats(match_id,club_id,side,shots)
            SELECT ?,club_id,side,10 FROM match_team_stats WHERE match_id=1''',(duplicate,))
        joined=repository.load_team_match_stats(self.conn,'2627')
        self.assertEqual(len(joined),2)
        self.assertTrue(joined.shots.eq(10).all())

    def test_statistics_update_in_place(self):
        self.price_frame().to_csv(self.path,index=False)
        prices.load(self.conn,self.path,'2627')
        season=self.conn.execute("SELECT id FROM seasons WHERE name='2026/27'").fetchone()[0]
        frame=pd.DataFrame([{'player':'Test','source_ref':123,'club':'Roma','mv':6.5}])
        load_statistics(self.conn,frame,season,self.path)
        load_statistics(self.conn,frame.assign(mv=7),season,self.path)
        self.assertEqual(self.conn.execute('SELECT count(*) FROM player_season_stat_values').fetchone()[0],1)
        self.assertEqual(self.conn.execute('SELECT value FROM player_season_stat_values').fetchone()[0],7)

    def test_recovered_vote_provider_id_consolidates_unidentified_row(self):
        folder=Path(self.tmp.name)/'votes';folder.mkdir()
        path=folder/'Voti_Giornata_01.csv'
        frame=pd.DataFrame([{'player':'Test Current','team':'Roma','role':'A','vote':6,'fantavoto':6}])
        frame.to_csv(path,index=False);votes.load(self.conn,folder,'2627')
        old_player=self.conn.execute('SELECT player_id FROM player_match_ratings').fetchone()[0]
        sid=self.conn.execute("SELECT id FROM sources WHERE slug='fantacalcio'").fetchone()[0]
        # A legacy namesake may already have an unrelated historical ID.
        self.conn.execute("INSERT INTO player_aliases(player_id,source_id,source_ref) VALUES(?,?,'999')",(old_player,sid))
        self.price_frame().assign(player='Test Legacy').to_csv(self.path,index=False)
        prices.load(self.conn,self.path,'2627')
        frame.assign(id=123).to_csv(path,index=False)
        votes.load(self.conn,folder,'2627');votes.load(self.conn,folder,'2627')
        self.assertEqual(self.conn.execute('SELECT count(*) FROM player_match_ratings').fetchone()[0],1)
        self.assertEqual(self.conn.execute('SELECT count(*) FROM players').fetchone()[0],2)
        self.assertEqual(self.conn.execute('SELECT r.player_id=p.player_id FROM player_match_ratings r CROSS JOIN player_prices p').fetchone()[0],1)


if __name__=='__main__':
    unittest.main()
