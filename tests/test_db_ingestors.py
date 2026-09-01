import csv
import tempfile
import unittest
from pathlib import Path

from scripts.build_database import build
from src.db import database
from src.db.ingestors import understat as understat_ingestor
from src.db.ingestors.common import season_label


class DatabaseIngestorTests(unittest.TestCase):
    def test_season_labels_preserve_full_years_and_compact_codes(self):
        self.assertEqual(season_label(2014), "2014/15")
        self.assertEqual(season_label(2021), "2021/22")
        self.assertEqual(season_label("1920"), "2019/20")
        self.assertEqual(season_label("2627"), "2026/27")
        self.assertEqual(season_label("9394"), "1993/94")
        self.assertEqual(season_label("9900"), "1999/00")
        self.assertEqual(season_label("2024/25"), "2024/25")

    def test_build_loads_and_reloads_sources_idempotently(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            understat = root / "understat.csv"
            understat.write_text(
                "player_name,id,team_title,year,league,primary_position,games,time,goals,assists,npg,npxG,xG,xA,xGChain,xGBuildup,shots,key_passes,yellow_cards,red_cards\n"
                "Test Defender,101,\"Test FC,Previous FC\",2024,Serie_A,D,20,1800,2,3,2,1.2,2.0,3.0,4.5,1.5,20,10,2,0\n",
                encoding="utf-8",
            )

            roster = root / "roster.csv"
            roster.write_text(
                "player,club_2026_27,role,status,source_url,checked_at\n"
                "Test Defender,Test FC,D,confirmed,https://example.test,2026-08-23\n",
                encoding="utf-8",
            )

            votes_dir = root / "votes"
            votes_dir.mkdir()
            (votes_dir / "Voti_Stagione_2024-25_Giornata_01.csv").write_text(
                "Codice;Ruolo;Giocatore;Squadra;Voto;Fantavoto;Gol;Assist;Amm;Esp\n"
                "201;D;Test Defender;Test FC;7;10;1;0;0;0\n",
                encoding="utf-8",
            )

            matches_dir = root / "matches" / "2425"
            matches_dir.mkdir(parents=True)
            with (matches_dir / "I1.csv").open("w", newline="", encoding="utf-8") as handle:
                writer = csv.DictWriter(
                    handle,
                    fieldnames=[
                        "Date", "HomeTeam", "AwayTeam", "FTHG", "FTAG", "HTHG", "HTAG",
                        "HS", "AS", "HST", "AST", "HF", "AF", "HC", "AC", "HY", "AY", "HR", "AR",
                        "B365H", "B365D", "B365A",
                    ],
                )
                writer.writeheader()
                writer.writerow({
                    "Date": "20/08/2024", "HomeTeam": "Test FC", "AwayTeam": "Away FC",
                    "FTHG": 2, "FTAG": 1, "HTHG": 1, "HTAG": 0,
                    "HS": 12, "AS": 8, "HST": 5, "AST": 3, "HF": 10, "AF": 12,
                    "HC": 6, "AC": 4, "HY": 1, "AY": 2, "HR": 0, "AR": 0,
                    "B365H": 1.8, "B365D": 3.5, "B365A": 4.2,
                })

            db_path = root / "fantapredictor.db"
            first = build(
                db_path,
                roster_path=roster,
                understat_path=understat,
                votes_dir=votes_dir,
                matches_dir=root / "matches",
                season="2425",
            )
            second = build(
                db_path,
                roster_path=roster,
                understat_path=understat,
                votes_dir=votes_dir,
                matches_dir=root / "matches",
                season="2425",
            )

            self.assertEqual(first["votes"], 1)
            self.assertEqual(first["matches"], 1)
            self.assertEqual(second["votes"], 1)
            self.assertEqual(second["matches"], 1)

            import sqlite3
            connection = sqlite3.connect(db_path)
            self.assertEqual(connection.execute("SELECT COUNT(*) FROM player_match_ratings").fetchone()[0], 1)
            self.assertEqual(connection.execute("SELECT COUNT(*) FROM matches").fetchone()[0], 1)
            self.assertEqual(connection.execute("SELECT matchday FROM matches").fetchone()[0], 1)
            self.assertEqual(connection.execute("SELECT COUNT(*) FROM player_season_stats").fetchone()[0], 1)
            self.assertEqual(connection.execute("SELECT COUNT(*) FROM match_odds").fetchone()[0], 1)
            self.assertEqual(
                connection.execute(
                    """SELECT c.name FROM player_season_stats ps
                       JOIN clubs c ON c.id = ps.club_id"""
                ).fetchone()[0],
                "Test FC",
            )
            self.assertEqual(
                connection.execute(
                    "SELECT xg_chain, xg_buildup FROM player_season_stats"
                ).fetchone(),
                (4.5, 1.5),
            )
            connection.close()

    def test_build_imports_all_numeric_manual_fbref_metrics_idempotently(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            manual_dir = root / "manual"
            manual_dir.mkdir()
            (manual_dir / "fbref_passing_2425.csv").write_text(
                "Player,Squad,Progressive Passes,Pass Completion %\n"
                "Test Midfielder,Test FC,42,87.5%\n",
                encoding="utf-8",
            )
            db_path = root / "fantapredictor.db"
            first = build(db_path, manual_fbref_dir=manual_dir, season="2425")
            second = build(db_path, manual_fbref_dir=manual_dir, season="2425")

            self.assertEqual(first["fbref"], 2)
            self.assertEqual(second["fbref"], 2)
            import sqlite3
            connection = sqlite3.connect(db_path)
            metrics = connection.execute(
                "SELECT metric, metric_label, value FROM player_season_stat_values ORDER BY metric"
            ).fetchall()
            connection.close()
            self.assertEqual(metrics, [
                ("pass_completion", "Pass Completion %", 87.5),
                ("progressive_passes", "Progressive Passes", 42.0),
            ])

    def test_understat_match_snapshot_loads_scores_xg_and_matchday_idempotently(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            matches = root / "understat_matches.csv"
            matches.write_text(
                "match_id,matchday,match_date,home_team,home_team_id,away_team,away_team_id,"
                "home_goals,away_goals,home_xg,away_xg,league,year\n"
                "31560,1,2026-08-22 16:30:00,Inter,106,Monza,271,4,1,1.5385,1.21666,Serie_A,2026\n",
                encoding="utf-8",
            )
            connection = database.get_connection(root / "fantapredictor.db")
            database.init_schema(connection)

            self.assertEqual(understat_ingestor.load_matches(connection, matches), 1)
            self.assertEqual(understat_ingestor.load_matches(connection, matches), 1)
            row = connection.execute(
                "SELECT matchday, home_goals, away_goals, home_xg, away_xg FROM matches"
            ).fetchone()
            team_xg = connection.execute(
                "SELECT side, xg FROM match_team_stats ORDER BY side"
            ).fetchall()
            connection.close()

            self.assertEqual(tuple(row), (1, 4, 1, 1.5385, 1.21666))
            self.assertEqual([tuple(value) for value in team_xg], [
                ("away", 1.21666), ("home", 1.5385),
            ])

    def test_historical_multi_club_aggregate_remains_unassigned_and_idempotent(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            stats = root / "understat.csv"
            stats.write_text(
                "player_name,id,team_title,year,league,primary_position,games,time,goals,assists,npg,npxG,xG,xA,xGChain,xGBuildup,shots,key_passes,yellow_cards,red_cards\n"
                "Moved Player,101,\"Old FC,New FC\",2024,Serie_A,M,2,90,1,0,1,0.8,0.8,0.1,1.0,0.2,3,1,0,0\n",
                encoding="utf-8",
            )
            connection = database.get_connection(root / "fantapredictor.db")
            database.init_schema(connection)

            self.assertEqual(understat_ingestor.load(connection, stats), 1)
            self.assertEqual(understat_ingestor.load(connection, stats), 1)
            rows = connection.execute(
                "SELECT club_id FROM player_season_stats"
            ).fetchall()
            connection.close()

            self.assertEqual(len(rows), 1)
            self.assertIsNone(rows[0][0])

    def test_roster_ingestor_rejects_invalid_status(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            roster = root / "roster.csv"
            roster.write_text(
                "player,club_2026_27,role,status,source_url,checked_at\n"
                "Test Player,Test FC,D,provisional,https://example.test,2026-08-23\n",
                encoding="utf-8",
            )

            with self.assertRaises(ValueError):
                build(root / "fantapredictor.db", roster_path=roster, season="2627")


if __name__ == "__main__":
    unittest.main()
