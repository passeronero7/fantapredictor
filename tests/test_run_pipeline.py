import unittest
from unittest.mock import patch

import pandas as pd

from scripts.run_pipeline import FantacalcioPipeline


class TrainingStageReadsFromWarehouseTests(unittest.TestCase):
    def test_stage_5_builds_datasets_from_the_warehouse_not_mid_outputs_excel(self):
        """Regression test for A1: no dependence on a pre-existing mid_outputs Excel.

        Previously this stage unconditionally read
        ``mid_outputs/database_entries(_gk).xlsx``, so running ``--stage
        train`` on its own (without ``training-data`` in the same process)
        required that file to already be on disk. It must now build its
        training data the same way stage 4 and evaluate_model.py do: directly
        from :class:`MatchDataBuilder`, with no Excel round trip.
        """
        outfield = pd.DataFrame([{"target_vote": 6.5, "target_fantavoto": 7.0}])
        goalkeepers = pd.DataFrame([{"target_vote": 6.0, "target_fantavoto": 5.5}])
        datasets = {"outfield": outfield, "goalkeepers": goalkeepers}

        with (
            patch("src.data_processing.match_data_builder.MatchDataBuilder.build_complete_dataset",
                  return_value=datasets) as build_complete_dataset,
            patch("src.models.neural_network.FantacalcioPredictor.train",
                  return_value={"status": "trained"}) as train,
            patch("src.models.neural_network.FantacalcioPredictor.save_model"),
            patch("pandas.read_excel") as read_excel,
        ):
            pipeline = FantacalcioPipeline(season="2627", include_history=True)
            pipeline.run_stage_5_training(epochs=5)

        build_complete_dataset.assert_called_once_with(include_historical=True)
        train.assert_called_once()
        called_outfield, called_gk = train.call_args.args
        pd.testing.assert_frame_equal(called_outfield, outfield)
        pd.testing.assert_frame_equal(called_gk, goalkeepers)
        read_excel.assert_not_called()


if __name__ == "__main__":
    unittest.main()
