import csv
import tempfile
import unittest
from pathlib import Path

from scripts.build_database import build
from src.db.ingestors.common import season_label


class DatabaseIngestorTests(unittest.TestCase):
    def test_season_labels_preserve_full_years_and_compact_codes(self):
        self.assertEqual(season_label(2014), "2014/15")
        self.assertEqual(season_label("2627"), "2026/27")
        self.assertEqual(season_label("2024/25"), "2024/25")

    def test_build_loads_and_reloads_sources_idempotently(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            understat = root / "understat.csv"
            understat.write_text(
                "player_name,id,team_title,year,league,primary_position,games,time,goals,assists,npg,npxG,xG,xA,shots,key_passes,yellow_cards,red_cards\n"
                "Test Defender,101,Test FC,2024,Serie_A,D,20,1800,2,3,2,1.2,2.0,3.0,20,10,2,0\n",
                encoding="utf-8",
            )

            roster = root / "roster.csv"
            roster.write_text(
                "player,club_2026_27,status,source_url,checked_at\n"
                "Test Defender,Test FC,confirmed,https://example.test,2026-08-23\n",
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
            self.assertEqual(connection.execute("SELECT COUNT(*) FROM player_season_stats").fetchone()[0], 1)
            self.assertEqual(connection.execute("SELECT COUNT(*) FROM match_odds").fetchone()[0], 1)
            connection.close()


if __name__ == "__main__":
    unittest.main()
