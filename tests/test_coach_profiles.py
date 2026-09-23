import tempfile
import unittest
from datetime import date
from pathlib import Path

import numpy as np
import pandas as pd

from scripts.simulate_auction_propensity import calendar_availability_factor
from src.db import database
from src.db.ingestors import coaches
from src.db.ingestors.common import club_id
from src.models.coach_profiles import (
    attach_coach,
    coach_matchdays,
    coach_profiles,
    context_multipliers,
)
from src.models.propensity import _per_player_samples, coach_style_adjustments


def rated_rows(coach: str, team: str, season: str, goals_by_role: dict, matchdays: int = 10):
    """One row per role and matchday; goals/assists spread over matchdays."""
    rows = []
    for md in range(1, matchdays + 1):
        for role, (goals, assists) in goals_by_role.items():
            rows.append({
                "season": season, "team": team, "matchday": md, "coach": coach,
                "player_normalized": f"{team}-{role}", "role": role,
                "goals": goals if md == 1 else 0, "assists": assists if md == 1 else 0,
            })
    return rows


class CoachMatchdayTests(unittest.TestCase):
    def setUp(self):
        self.conn = database.get_connection(":memory:")
        database.init_schema(self.conn)
        home = club_id(self.conn, "Fiorentina", "leaf-node-manual")
        away = club_id(self.conn, "Venezia", "leaf-node-manual")
        season = self.conn.execute(
            "INSERT INTO seasons (name, start_year) VALUES ('2026/27', 2026)"
        ).lastrowid
        for md, day in ((1, "2026-08-24"), (2, "2026-08-29"), (3, "2026-09-06"), (4, "2026-09-11")):
            self.conn.execute(
                "INSERT INTO matches (season_id, matchday, match_date, home_club_id, away_club_id)"
                " VALUES (?, ?, ?, ?, ?)", (season, md, day, home, away),
            )
        self.conn.commit()
        csv = Path(tempfile.mkdtemp()) / "coaches.csv"
        pd.DataFrame([
            {"season": "2026/27", "club": "Fiorentina", "coach": "Fabio Grosso",
             "started_at": "2026-08-22", "ended_at": "2026-09-06", "preferred_module": "4-3-3"},
            {"season": "2026/27", "club": "Fiorentina", "coach": "Paolo Vanoli",
             "started_at": "2026-09-06", "ended_at": None, "preferred_module": "4-3-2-1"},
            {"season": "2026/27", "club": "Venezia", "coach": "Giovanni Stroppa",
             "started_at": "2026-08-22", "ended_at": None, "preferred_module": "3-5-2"},
        ]).to_csv(csv, index=False)
        coaches.load(self.conn, csv)
        coaches.load(self.conn, csv)  # idempotent

    def tearDown(self):
        self.conn.close()

    def test_in_season_change_attributes_matches_by_date(self):
        table = coach_matchdays(self.conn)
        fiorentina = table[table.club.eq("Fiorentina")].set_index("matchday")["coach"]
        # Sacked on 6 Sep, the day of matchday 3: that match stays Grosso's.
        self.assertEqual(list(fiorentina.loc[[1, 2, 3, 4]]),
                         ["Fabio Grosso"] * 3 + ["Paolo Vanoli"])
        self.assertEqual(self.conn.execute("SELECT COUNT(*) FROM coach_club_seasons").fetchone()[0], 3)

    def test_current_module_comes_from_open_stint(self):
        current = coach_style_adjustments(self.conn, "2026/27")
        self.assertEqual(current["Fiorentina"]["module"], "4-3-2-1")

    def test_attach_coach_ignores_club_case(self):
        ratings = pd.DataFrame({"season": ["2026/27"], "team": ["FIORENTINA"], "matchday": [4]})
        self.assertEqual(attach_coach(ratings, coach_matchdays(self.conn))["coach"].iloc[0], "Paolo Vanoli")


class CoachProfileTests(unittest.TestCase):
    def build(self):
        rows = []
        # "Midfield" coach: midfielders score most of the goals.
        rows += rated_rows("Mid Coach", "Alpha", "2024/25", {"D": (2, 4), "C": (30, 10), "A": (8, 6)})
        # "Striker" coach: forwards score almost everything.
        rows += rated_rows("Striker Coach", "Beta", "2024/25", {"D": (2, 4), "C": (4, 10), "A": (34, 6)})
        return pd.DataFrame(rows)

    def test_shares_are_shrunk_toward_league(self):
        profiles = coach_profiles(self.build(), shrinkage=40)
        raw_mid_share = 30 / 40
        shrunk = profiles.goal_share.at["Mid Coach", "C"]
        self.assertLess(shrunk, raw_mid_share)
        self.assertGreater(shrunk, profiles.league_goal_share["C"])
        self.assertAlmostEqual(profiles.goal_share.loc["Mid Coach"].sum(), 1.0)

    def test_multiplier_is_one_when_coach_unchanged_and_moves_with_context(self):
        rated = self.build()
        profiles = coach_profiles(rated, shrinkage=40)
        current = pd.DataFrame({
            "player_normalized": ["Alpha-C", "Beta-C"],
            "role": ["C", "C"],
            "coach": ["Mid Coach", "Mid Coach"],
        })
        result = context_multipliers(rated, profiles, current, strength=0.5).set_index("player_normalized")
        self.assertAlmostEqual(result.at["Alpha-C", "goal_mult"], 1.0)
        # A midfielder moving from the striker coach to the midfield coach gains.
        self.assertGreater(result.at["Beta-C", "goal_mult"], 1.0)
        # Assist shares are identical for both coaches: no assist effect.
        self.assertAlmostEqual(result.at["Beta-C", "assist_mult"], 1.0)

    def test_unknown_coach_falls_back_to_league_share(self):
        rated = self.build()
        profiles = coach_profiles(rated, shrinkage=40)
        self.assertAlmostEqual(profiles.share("goal", "Nobody", "A"), profiles.league_goal_share["A"])


class BonusRescaleTests(unittest.TestCase):
    def test_goal_multiplier_rescales_goal_part_of_bonus(self):
        prior = pd.DataFrame({
            "player_normalized": ["x"] * 4, "role": ["C"] * 4,
            "vote": [6.0, 6.5, 7.0, 6.0], "fantavoto": [6.0, 9.5, 8.0, 6.0],
            "goals": [0, 1, 0, 0], "assists": [0, 0, 1, 0],
        })
        base = pd.DataFrame({"player_normalized": ["x"], "role": ["C"]})
        _, plain, _, _ = _per_player_samples(prior, base)
        boosted = base.assign(goal_mult=1.5, assist_mult=1.0)
        _, scaled, _, _ = _per_player_samples(prior, boosted)
        # Same bootstrap indices (fixed rng): goal rows gain 1.5 points.
        diff = scaled - plain
        self.assertTrue(np.all(np.isclose(diff, 0.0) | np.isclose(diff, 1.5)))
        self.assertTrue(np.isclose(diff, 1.5).any())


class CalendarAvailabilityTests(unittest.TestCase):
    def test_share_of_matchdays_after_return(self):
        dates = [date(2026, 10, 11), date(2026, 10, 17), date(2026, 10, 25), date(2026, 11, 1)]
        self.assertEqual(calendar_availability_factor("2026-10-15", dates), 0.75)
        self.assertEqual(calendar_availability_factor("2026-10-01", dates), 1.0)
        self.assertEqual(calendar_availability_factor("2027-01-01", dates), 0.0)
        self.assertEqual(calendar_availability_factor(None, dates), 1.0)


if __name__ == "__main__":
    unittest.main()
