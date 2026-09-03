import unittest

import numpy as np
import pandas as pd

from src.models.propensity import (
    SimulationConfig,
    club_style_index,
    player_propensity,
    simulate_horizon,
    style_multiplier,
)


def build_team_stats(season: str = "2025/26", matchdays: int = 6) -> pd.DataFrame:
    clubs = ["Alpha", "Beta", "Gamma", "Delta"]
    rows = []
    for md in range(1, matchdays + 1):
        pairs = [(clubs[0], clubs[1]), (clubs[2], clubs[3])]
        for home, away in pairs:
            for side, team, opponent in (("home", home, away), ("away", away, home)):
                rows.append({
                    "season": season, "matchday": md, "team": team,
                    "opponent": opponent,
                    "is_home": 1 if side == "home" else 0,
                    "goals_for": 3 if team == "Alpha" else 1,
                    "goals_against": 0 if team == "Alpha" else 1,
                    "shots": 18 if team == "Alpha" else 8,
                    "corners": 6 if team == "Alpha" else 3,
                })
    return pd.DataFrame(rows)


def build_ratings(season: str = "2025/26", matchdays: int = 6) -> pd.DataFrame:
    rows = []
    rng = np.random.default_rng(7)
    for md in range(1, matchdays + 1):
        # Alpha striker: strong marks; Delta striker: weak marks.
        rows.append({"player": "Star", "player_normalized": "star", "team": "Alpha",
                     "role": "A", "matchday": md, "vote": 7.0, "fantavoto": 9.0,
                     "season": season})
        rows.append({"player": "Weak", "player_normalized": "weak", "team": "Delta",
                     "role": "A", "matchday": md, "vote": 5.0, "fantavoto": 5.0,
                     "season": season})
        # Role fillers for the fallback pools.
        for index in range(6):
            rows.append({
                "player": f"FillerA{index}", "player_normalized": f"fillera{index}",
                "team": "Beta", "role": "A", "matchday": md,
                "vote": 6.0 + float(rng.integers(0, 2)), "fantavoto": 6.5,
                "season": season,
            })
        for index in range(4):
            rows.append({
                "player": f"Keeper{index}", "player_normalized": f"keeper{index}",
                "team": "Gamma", "role": "P", "matchday": md,
                "vote": 6.5, "fantavoto": 6.5, "season": season,
            })
    return pd.DataFrame(rows)


def build_propensity_frame() -> pd.DataFrame:
    ratings = build_ratings()
    team_stats = build_team_stats()
    return player_propensity(ratings, team_stats, "2025/26", 7)


class ClubStyleIndexTests(unittest.TestCase):
    def test_attack_index_ranks_high_shot_club_first(self):
        style = club_style_index(build_team_stats())
        alpha = style[style["team"] == "Alpha"]["attack_index"].iloc[0]
        delta = style[style["team"] == "Delta"]["attack_index"].iloc[0]
        self.assertGreater(alpha, delta)
        self.assertGreater(style[style["team"] == "Alpha"]["defense_index"].iloc[0],
                           style[style["team"] == "Delta"]["defense_index"].iloc[0])

    def test_style_is_standardised_within_season(self):
        style = club_style_index(build_team_stats())
        self.assertAlmostEqual(style["attack_index"].mean(), 0.0, places=6)


class PlayerPropensityTests(unittest.TestCase):
    def test_probability_columns_are_bounded(self):
        frame = build_propensity_frame()
        self.assertTrue((frame["p_good_mark"] >= 0).all() and (frame["p_good_mark"] <= 1).all())
        self.assertTrue((frame["p_plays"] >= 0).all() and (frame["p_plays"] <= 1).all())

    def test_high_scoring_player_has_higher_propensity(self):
        frame = build_propensity_frame().set_index("player_normalized")
        self.assertGreater(frame.at["star", "p_good_mark"], frame.at["weak", "p_good_mark"])

    def test_target_matchday_is_excluded_from_history(self):
        ratings = build_ratings()
        team_stats = build_team_stats()
        # Give Star a catastrophic mark at the cutoff matchday itself.
        ratings = pd.concat([ratings, pd.DataFrame([{
            "player": "Star", "player_normalized": "star", "team": "Alpha",
            "role": "A", "matchday": 7, "vote": 4.0, "fantavoto": 4.0,
            "season": "2025/26",
        }])], ignore_index=True)
        frame = player_propensity(ratings, team_stats, "2025/26", 7)
        self.assertEqual(frame[frame["player_normalized"] == "star"][
            "vote_median"].iloc[0], 7.0)


class StyleMultiplierTests(unittest.TestCase):
    def test_attacker_gains_from_own_attack_and_weak_defense(self):
        base = style_multiplier("A", 0.0, 0.0, 0.0, 0.0)
        boosted = style_multiplier("A", 2.0, 0.0, 0.0, -2.0)
        self.assertAlmostEqual(base, 1.0)
        self.assertGreater(boosted, base)

    def test_goalkeeper_suffers_strong_opponent_attack(self):
        neutral = style_multiplier("P", 0.0, 0.0, 0.0, 0.0)
        pressured = style_multiplier("P", 0.0, 0.0, 2.0, 0.0)
        self.assertLess(pressured, neutral)

    def test_multiplier_is_capped(self):
        extreme = style_multiplier("A", 10.0, 0.0, 0.0, -10.0, weight=2.0)
        self.assertLessEqual(extreme, 2.0)


class SimulateHorizonTests(unittest.TestCase):
    def test_simulation_is_deterministic_for_a_seed(self):
        frame = build_propensity_frame()
        style = club_style_index(build_team_stats())
        clubs = sorted(frame["team"].unique())
        config = SimulationConfig(from_matchday=7, matchdays=4, simulations=30, seed=11)
        first = simulate_horizon(frame, build_ratings(), style, clubs, config)
        second = simulate_horizon(frame, build_ratings(), style, clubs, config)
        pd.testing.assert_frame_equal(first, second)

    def test_outputs_are_valid_probabilities(self):
        frame = build_propensity_frame()
        style = club_style_index(build_team_stats())
        clubs = sorted(frame["team"].unique())
        config = SimulationConfig(from_matchday=7, matchdays=4, simulations=50, seed=5)
        result = simulate_horizon(frame, build_ratings(), style, clubs, config)
        for column in ("p_good_mark", "p_plays", "simulated_mark_rate",
                       "p_horizon_median_good"):
            self.assertTrue((result[column] >= 0).all() and (result[column] <= 1).all(),
                            column)
        self.assertTrue((result["horizon_median_vote"] > 0).all())


if __name__ == "__main__":
    unittest.main()


class CoachConditioningTests(unittest.TestCase):
    def test_module_and_tag_deltas(self):
        from src.models.propensity import coach_role_delta
        cond = {"module": "3-4-2-1", "style_tags": ["possession", "wingback_attack"]}
        self.assertGreater(coach_role_delta(cond, "D"), 0)
        self.assertAlmostEqual(coach_role_delta(cond, "P"), 0.0)
        pragmatic = {"module": "4-3-3", "style_tags": ["pragmatic"]}
        self.assertGreater(coach_role_delta(pragmatic, "P"), 0)
        self.assertLess(coach_role_delta(pragmatic, "A"), 0)
        self.assertEqual(coach_role_delta(None, "A"), 0.0)

    def test_coach_style_adjustments_empty_without_history(self):
        import sqlite3
        from src.db import database
        from src.models.propensity import coach_style_adjustments
        conn = database.get_connection(":memory:")
        database.init_schema(conn)
        try:
            self.assertEqual(coach_style_adjustments(conn, "2026/27"), {})
        finally:
            conn.close()
