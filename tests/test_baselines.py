import unittest

import pandas as pd

from src.models.baselines import compute_baseline_predictions


def build_ratings() -> pd.DataFrame:
    rows = []
    # Player "veteran": five prior-season observations (own quantiles win).
    for fantavoto in (4.0, 5.0, 6.0, 7.0, 12.0):
        rows.append({
            "player": "Veteran", "player_normalized": "veteran", "team": "Roma",
            "role": "A", "matchday": 1, "fantavoto": fantavoto, "season": "2024/25",
        })
    # Player "rookie": only current-season observations below the cutoff.
    for matchday, fantavoto in ((1, 5.0), (2, 7.0)):
        rows.append({
            "player": "Rookie", "player_normalized": "rookie", "team": "Roma",
            "role": "A", "matchday": matchday, "fantavoto": fantavoto,
            "season": "2025/26",
        })
    # Role filler so the A-role distribution exists.
    for fantavoto in (5.0, 6.0, 7.0, 8.0):
        rows.append({
            "player": f"Filler{fantavoto}", "player_normalized": f"filler{fantavoto}",
            "team": "Milan", "role": "A", "matchday": 1, "fantavoto": fantavoto,
            "season": "2024/25",
        })
    # Goalkeeper history for the role fallback path.
    for fantavoto in (5.5, 6.0, 6.5, 7.0):
        rows.append({
            "player": f"Keeper{fantavoto}", "player_normalized": f"keeper{fantavoto}",
            "team": "Milan", "role": "P", "matchday": 1, "fantavoto": fantavoto,
            "season": "2024/25",
        })
    return pd.DataFrame(rows)


def build_roster() -> pd.DataFrame:
    return pd.DataFrame([
        {"player": "Veteran", "player_normalized": "veteran", "club_2026_27": "Roma", "role": "A", "status": "confirmed"},
        {"player": "Rookie", "player_normalized": "rookie", "club_2026_27": "Roma", "role": "A", "status": "confirmed"},
        {"player": "Keeper", "player_normalized": "keeper", "club_2026_27": "Roma", "role": "P", "status": "confirmed"},
        {"player": "Watch", "player_normalized": "watch", "club_2026_27": "Roma", "role": "A", "status": "watchlist"},
    ])


class BaselinePredictionTests(unittest.TestCase):
    def test_predictions_cover_confirmed_roster_with_quantiles(self):
        result = compute_baseline_predictions(build_ratings(), build_roster(), "2025/26", 3)
        self.assertEqual(result["player_normalized"].tolist(), ["veteran", "rookie", "keeper"])
        for column in ("floor_q10", "median_q50", "ceiling_q90"):
            self.assertIn(column, result.columns)
        self.assertTrue((result["floor_q10"] <= result["median_q50"]).all())
        self.assertTrue((result["median_q50"] <= result["ceiling_q90"]).all())

    def test_players_with_enough_history_get_their_own_distribution(self):
        result = compute_baseline_predictions(build_ratings(), build_roster(), "2025/26", 3)
        veteran = result[result["player_normalized"] == "veteran"].iloc[0]
        self.assertEqual(veteran["prediction_source"], "expanding_prior_baseline")
        self.assertEqual(veteran["median_q50"], 6.0)

    def test_players_without_history_fall_back_to_role_quantiles(self):
        result = compute_baseline_predictions(build_ratings(), build_roster(), "2025/26", 3)
        keeper = result[result["player_normalized"] == "keeper"].iloc[0]
        self.assertEqual(keeper["prediction_source"], "global_median_baseline")
        self.assertEqual(keeper["median_q50"], 6.25)

    def test_current_season_observations_below_cutoff_are_used(self):
        # Rookie has two observations strictly below matchday 3: not enough
        # for the expanding prior, but the target matchday must be excluded.
        ratings = build_ratings()
        ratings = pd.concat([ratings, pd.DataFrame([{
            "player": "Rookie", "player_normalized": "rookie", "team": "Roma",
            "role": "A", "matchday": 3, "fantavoto": 15.0, "season": "2025/26",
        }])], ignore_index=True)
        result = compute_baseline_predictions(ratings, build_roster(), "2025/26", 3)
        rookie = result[result["player_normalized"] == "rookie"].iloc[0]
        # Without the target-matchday 15.0, role fallback applies.
        self.assertEqual(rookie["prediction_source"], "global_median_baseline")

    def test_target_matchday_is_never_leaked_into_priors(self):
        ratings = build_ratings()
        rookie_extra = pd.DataFrame([{
            "player": "Rookie", "player_normalized": "rookie", "team": "Roma",
            "role": "A", "matchday": 3, "fantavoto": 15.0, "season": "2025/26",
        }])
        result = compute_baseline_predictions(
            pd.concat([ratings, rookie_extra], ignore_index=True),
            build_roster(), "2025/26", 3,
        )
        # If the 15.0 leaked, the rookie's median would jump above 6.0.
        self.assertLessEqual(result["median_q50"].max(), 12.0)


if __name__ == "__main__":
    unittest.main()
