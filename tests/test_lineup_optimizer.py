import unittest
import pandas as pd

from src.models.lineup_optimizer import LineupOptimizer


class LineupOptimizerTests(unittest.TestCase):
    def setUp(self):
        self.players_df = pd.DataFrame([
            {"player": "GK1", "role": "P", "predicted_vote": 6.5, "predicted_fantavoto": 6.5, "ceiling_q90": 8.0, "floor_q10": 4.5},
            {"player": "D1", "role": "D", "predicted_vote": 6.5, "predicted_fantavoto": 6.5, "ceiling_q90": 7.5, "floor_q10": 5.5},
            {"player": "D2", "role": "D", "predicted_vote": 6.5, "predicted_fantavoto": 6.5, "ceiling_q90": 7.5, "floor_q10": 5.5},
            {"player": "D3", "role": "D", "predicted_vote": 6.5, "predicted_fantavoto": 6.5, "ceiling_q90": 7.5, "floor_q10": 5.5},
            {"player": "D4", "role": "D", "predicted_vote": 6.5, "predicted_fantavoto": 6.5, "ceiling_q90": 7.5, "floor_q10": 5.5},
            {"player": "C1", "role": "C", "predicted_vote": 6.5, "predicted_fantavoto": 7.5, "ceiling_q90": 10.0, "floor_q10": 5.5},
            {"player": "C2", "role": "C", "predicted_vote": 6.0, "predicted_fantavoto": 6.5, "ceiling_q90": 8.5, "floor_q10": 5.0},
            {"player": "C3", "role": "C", "predicted_vote": 6.0, "predicted_fantavoto": 6.5, "ceiling_q90": 8.5, "floor_q10": 5.0},
            {"player": "C4", "role": "C", "predicted_vote": 6.0, "predicted_fantavoto": 6.5, "ceiling_q90": 8.5, "floor_q10": 5.0},
            {"player": "A1", "role": "A", "predicted_vote": 6.5, "predicted_fantavoto": 9.5, "ceiling_q90": 14.5, "floor_q10": 5.0},
            {"player": "A2", "role": "A", "predicted_vote": 6.5, "predicted_fantavoto": 9.0, "ceiling_q90": 13.5, "floor_q10": 5.0},
            {"player": "A3", "role": "A", "predicted_vote": 6.0, "predicted_fantavoto": 8.0, "ceiling_q90": 12.0, "floor_q10": 4.5},
        ])
        self.players_df["price"] = [10, 10, 10, 10, 10, 10, 10, 10, 10, 20, 20, 20]

    def test_defense_modifier_calculation(self):
        optimizer = LineupOptimizer(self.players_df)
        # Average grade = (6.5 + 6.5 + 6.5 + 6.5)/4 = 6.5 -> +3 bonus
        bonus_65 = optimizer.calculate_defense_modifier(6.5, [6.5, 6.5, 6.5, 6.0])
        self.assertEqual(bonus_65, 3.0)

        # Average grade = (7.0 + 7.0 + 7.0 + 7.0)/4 = 7.0 -> +6 bonus
        bonus_70 = optimizer.calculate_defense_modifier(7.0, [7.0, 7.0, 7.0])
        self.assertEqual(bonus_70, 6.0)

        # Average grade = (6.0 + 6.0 + 6.0 + 6.0)/4 = 6.0 -> +1 bonus
        bonus_60 = optimizer.calculate_defense_modifier(6.0, [6.0, 6.0, 6.0])
        self.assertEqual(bonus_60, 1.0)

        # Below 6.0 -> 0 bonus
        bonus_55 = optimizer.calculate_defense_modifier(5.5, [5.5, 5.5, 5.5])
        self.assertEqual(bonus_55, 0.0)

    def test_optimal_lineup_respects_formation_counts(self):
        optimizer = LineupOptimizer(self.players_df, formation="3-4-3")
        res = optimizer.get_optimal_lineup()

        starters = res["starters"]
        self.assertEqual(len(starters), 11)
        self.assertEqual(len(starters[starters["role_norm"] == "P"]), 1)
        self.assertEqual(len(starters[starters["role_norm"] == "D"]), 3)
        self.assertEqual(len(starters[starters["role_norm"] == "C"]), 4)
        self.assertEqual(len(starters[starters["role_norm"] == "A"]), 3)

    def test_optimal_lineup_with_defense_modifier_adds_bonus(self):
        optimizer = LineupOptimizer(self.players_df, formation="4-3-3", enable_modificatore=True)
        res = optimizer.get_optimal_lineup()
        self.assertGreater(res["defense_modifier_bonus"], 2.0)
        self.assertGreater(res["total_expected_points"], res["base_points"])

    def test_monte_carlo_simulation_draws_matrix(self):
        optimizer = LineupOptimizer(self.players_df, simulations=500)
        sim_df = optimizer.simulate_matchday_slates()
        self.assertEqual(sim_df.shape, (len(self.players_df), 500))

    def test_budget_is_enforced(self):
        expensive = self.players_df.copy()
        expensive["price"] = 100
        with self.assertRaises(ValueError):
            LineupOptimizer(expensive, budget=500).get_optimal_lineup()


if __name__ == "__main__":
    unittest.main()
