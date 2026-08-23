import tempfile
import unittest
from pathlib import Path

import pandas as pd

from scripts.optimize_lineup import optimize


class OptimizeLineupScriptTests(unittest.TestCase):
    def test_optimize_returns_json_serializable_starters(self):
        rows = []
        for role, count, prefix in (("P", 1, "Keeper"), ("D", 3, "Defender"), ("C", 4, "Midfielder"), ("A", 3, "Forward")):
            for index in range(count):
                rows.append({
                    "player": f"{prefix} {index}",
                    "role": role,
                    "price": 10,
                    "predicted_fantavoto": 6,
                    "team": prefix,
                })
        frame = pd.DataFrame(rows)

        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "predictions.csv"
            frame.to_csv(path, index=False)
            result = optimize(path, simulations=20)

        self.assertEqual(len(result["starters"]), 11)
        self.assertEqual(result["total_cost"], 110.0)
        self.assertIsInstance(result["starters"], list)


if __name__ == "__main__":
    unittest.main()
