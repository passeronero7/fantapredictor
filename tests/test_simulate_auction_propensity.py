import unittest
import sqlite3
from datetime import date

import pandas as pd

from scripts.simulate_auction_propensity import NON_TITOLAR_FACTOR, formation_factors
from scripts.simulate_auction_propensity import club_horizon_dates, calendar_availability_factor


class ClubCalendarTests(unittest.TestCase):
    def test_return_between_early_and_late_fixtures_uses_the_players_club(self):
        with sqlite3.connect(":memory:") as conn:
            conn.executescript("""
                CREATE TABLE seasons(id INTEGER, name TEXT);
                CREATE TABLE clubs(id INTEGER, name TEXT);
                CREATE TABLE matches(season_id INTEGER,matchday INTEGER,match_date TEXT,
                                     home_club_id INTEGER,away_club_id INTEGER);
                INSERT INTO seasons VALUES (1,'2026/27');
                INSERT INTO clubs VALUES (1,'Early'),(2,'Late'),(3,'A'),(4,'B');
                INSERT INTO matches VALUES (1,6,'2026-10-10',1,3),(1,6,'2026-10-12',2,4);
            """)
            dates = club_horizon_dates(conn, "2026/27", 6, 1)
        self.assertEqual(dates["Early"], [date(2026, 10, 10)])
        self.assertEqual(calendar_availability_factor("2026-10-11", dates["Early"]), 0)
        self.assertEqual(calendar_availability_factor("2026-10-11", dates["Late"]), 1)


class FormationFactorTests(unittest.TestCase):
    def setUp(self):
        self.formations = pd.DataFrame([
            {"club": "Juventus", "titulars": "Thuram K.;Vlahovic", "source_refs": "101;102"},
            {"club": "Inter", "titulars": "Lautaro;Barella", "source_refs": "201;202"},
        ])
        self.prices = pd.DataFrame([
            {"player_normalized": "thuram k", "source_ref": 101},
            {"player_normalized": "thuram", "source_ref": 203},
            {"player_normalized": "barella", "source_ref": 202},
        ])

    def factors(self, rows):
        return list(formation_factors(pd.DataFrame(rows), self.formations, self.prices))

    def test_titolar_is_identified_by_official_id(self):
        rows = [{"player": "Barella", "player_normalized": "barella", "team": "Inter"}]
        self.assertEqual(self.factors(rows), [1.0])

    def test_name_substring_from_another_club_does_not_count(self):
        # Marcus Thuram (Inter, not in the probable XI) must not inherit
        # Khephren Thuram's Juventus titolar status through "thuram" ⊂ "thuram k".
        rows = [{"player": "Thuram", "player_normalized": "thuram", "team": "Inter"}]
        self.assertEqual(self.factors(rows), [NON_TITOLAR_FACTOR])

    def test_name_fallback_is_exact_and_club_scoped(self):
        rows = [
            {"player": "Vlahovic", "player_normalized": "vlahovic", "team": "Juventus"},
            {"player": "Vlahovic", "player_normalized": "vlahovic", "team": "Inter"},
        ]
        self.assertEqual(self.factors(rows), [1.0, NON_TITOLAR_FACTOR])


if __name__ == "__main__":
    unittest.main()
