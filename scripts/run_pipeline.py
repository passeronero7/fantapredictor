#!/usr/bin/env python3
"""
Main pipeline orchestrator for Fantacalcio prediction system.

This script coordinates all stages of the offline data pipeline from local
source validation to prediction generation.
"""

import argparse
import json
import logging
import sys
from pathlib import Path
from datetime import datetime

# Add src to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from config.settings import config

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format=config.LOG_FORMAT,
    handlers=[
        logging.FileHandler(config.LOG_FILE),
        logging.StreamHandler(sys.stdout)
    ]
)
logger = logging.getLogger(__name__)


class FantacalcioPipeline:
    """Main pipeline orchestrator."""
    
    def __init__(self, season: str = None, include_history: bool = False):
        """
        Initialize pipeline.
        
        Args:
            season: Season identifier (e.g., '2324')
            include_history: Whether to include historical seasons for training
        """
        self.season = season or config.CURRENT_SEASON
        self.include_history = include_history
        
        # Ensure directories exist
        config.ensure_directories(self.season)
        
        logger.info(f"Initialized pipeline for season {self.season}")
    
    def run_stage_1_manual_fbref(self):
        """
        Stage 1: Load manually exported FBref data.
        """
        from src.data_processing.fbref_manual import load_manual_exports
        
        logger.info("=" * 60)
        logger.info("STAGE 1: Loading Manual FBref Exports")
        logger.info("=" * 60)

        manual_dir = config.get_season_dir(self.season) / "manual"
        exports = load_manual_exports(manual_dir, self.season)
        if not exports:
            logger.warning(f"No manual FBref exports found at {manual_dir}")
            logger.warning("Export FBref tables in a browser before using FBref features")
            return exports
        for category, frame in exports.items():
            logger.info(f"✓ Loaded {category} export with {len(frame)} rows")
        return exports
    
    def run_stage_2_votes(self, max_matchday: int = None):
        """
        Stage 2: Process vote data.
        
        Args:
            max_matchday: Maximum matchday to process (None = all available)
        """
        logger.info("=" * 60)
        logger.info("STAGE 2: Processing Votes")
        logger.info("=" * 60)
        
        # NOTE: This stage requires manual vote downloads
        votes_dir = config.get_season_dir(self.season) / "fantacalcio" / config.VOTES_DIR
        
        if not votes_dir.exists():
            logger.warning(f"Votes directory not found: {votes_dir}")
            logger.warning("Please download vote files from fantacalcio.it")
            logger.warning("Skipping votes processing...")
            return
        
        # Import here to avoid circular dependencies
        try:
            from src.data_processing.votes_processor import VotesProcessor
            
            processor = VotesProcessor(season=self.season)
            votes_df = processor.process_all_matchdays(max_matchday=max_matchday)
            
            output_file = config.get_mid_output_path(config.PLAYERS_VOTES_FILE, season=self.season)
            votes_df.to_excel(output_file)
            
            logger.info(f"✓ Processed votes for {len(votes_df)} player-match entries")
            logger.info(f"✓ Saved to {output_file}")
        except Exception as e:
            logger.error(f"Error in votes processing: {e}")
            logger.warning("Continuing without votes data...")
    
    def run_stage_3_players(self):
        """Stage 3: Merge player data from all sources."""
        logger.info("=" * 60)
        logger.info("STAGE 3: Merging Player Data")
        logger.info("=" * 60)
        
        try:
            from src.data_processing.players_processor import PlayersProcessor
            from src.data_processing.votes_processor import VotesProcessor

            processor = PlayersProcessor(season=self.season)
            vote_processor = VotesProcessor(season=self.season)
            if config.DATA_DIR.joinpath("fantapredictor.db").exists():
                votes_df = vote_processor.load_from_database()
            else:
                votes_df = vote_processor.process_all_matchdays()
            players_df = processor.merge_all_sources(votes_df=votes_df)
            
            output_file = config.get_mid_output_path(config.PLAYERS_STATS_FILE, season=self.season)
            players_df.to_excel(output_file)
            
            logger.info(f"✓ Merged data for {len(players_df)} players")
            logger.info(f"✓ Saved to {output_file}")
        except Exception as e:
            logger.error(f"Error in player processing: {e}")
            raise
    
    def run_stage_4_training_data(self):
        """Stage 4: Build training dataset."""
        logger.info("=" * 60)
        logger.info("STAGE 4: Building Training Dataset")
        logger.info("=" * 60)
        
        try:
            from src.data_processing.match_data_builder import MatchDataBuilder
            
            builder = MatchDataBuilder(season=self.season)
            datasets = builder.build_complete_dataset(
                include_historical=self.include_history
            )
            
            # Save datasets
            output_file = config.get_mid_output_path(config.DATABASE_ENTRIES_FILE, season=self.season)
            datasets['outfield'].to_excel(output_file)
            
            output_file_gk = config.get_mid_output_path(config.DATABASE_ENTRIES_GK_FILE, season=self.season)
            datasets['goalkeepers'].to_excel(output_file_gk)
            
            logger.info(f"✓ Created {len(datasets['outfield'])} outfield training samples")
            logger.info(f"✓ Created {len(datasets['goalkeepers'])} goalkeeper training samples")
        except Exception as e:
            logger.error(f"Error building training data: {e}")
            raise
    
    def run_stage_5_training(self, epochs: int = None):
        """
        Stage 5: Train neural network models.
        
        Args:
            epochs: Number of training epochs (None = use config default)
        """
        logger.info("=" * 60)
        logger.info("STAGE 5: Training Neural Networks")
        logger.info("=" * 60)
        
        try:
            from src.models.neural_network import FantacalcioPredictor
            
            # Load training data
            outfield_file = config.get_mid_output_path(config.DATABASE_ENTRIES_FILE, season=self.season)
            gk_file = config.get_mid_output_path(config.DATABASE_ENTRIES_GK_FILE, season=self.season)
            
            import pandas as pd
            outfield_data = pd.read_excel(outfield_file, index_col=0)
            gk_data = pd.read_excel(gk_file, index_col=0)
            
            # Train model
            predictor = FantacalcioPredictor(season=self.season)
            history = predictor.train(
                outfield_data, 
                gk_data,
                epochs=epochs or config.NN_EPOCHS
            )
            
            # Save model
            model_version = f"{self.season}_v{datetime.now().strftime('%Y%m%d')}"
            predictor.save_model(version=model_version)
            
            logger.info(f"✓ Model trained and saved as {model_version}")
        except Exception as e:
            logger.error(f"Error training model: {e}")
            raise
    
    def run_stage_6_predictions(self, matchday: int):
        """
        Stage 6: Generate predictions for upcoming matchday.
        
        Args:
            matchday: Matchday number to predict
        """
        logger.info("=" * 60)
        logger.info(f"STAGE 6: Generating Predictions for Matchday {matchday}")
        logger.info("=" * 60)
        
        try:
            from src.models.neural_network import FantacalcioPredictor
            from src.data_processing.players_processor import PlayersProcessor
            from src.data_processing.prices_processor import merge_current_prices
            from src.data_processing.votes_processor import VotesProcessor
            
            # Load latest model
            predictor = FantacalcioPredictor(season=self.season)
            predictor.load_latest_model()

            # Build prediction features only from information available before
            # the requested matchday; do not use the target round itself.
            vote_processor = VotesProcessor(season=self.season)
            if config.DATA_DIR.joinpath("fantapredictor.db").exists():
                prior_votes = vote_processor.load_from_database()
                prior_votes = prior_votes[prior_votes["matchday"] < matchday].copy()
            else:
                prior_votes = vote_processor.process_all_matchdays(
                    max_matchday=max(matchday - 1, 0)
                )
            players_data = PlayersProcessor(season=self.season).merge_all_sources(
                votes_df=prior_votes
            )
            if config.DATA_DIR.joinpath("fantapredictor.db").exists():
                from src.db import database, repository

                conn = database.get_connection(config.DATA_DIR / "fantapredictor.db")
                try:
                    prices = repository.load_prices(conn, self.season)
                finally:
                    conn.close()
            else:
                prices_path = config.get_season_dir(self.season) / "fantacalcio" / "prices.csv"
                if prices_path.exists():
                    import pandas as pd
                    prices = pd.read_csv(prices_path)
                else:
                    prices = None
            if prices is not None and not players_data.empty:
                players_data = merge_current_prices(players_data, prices)

            # Generate predictions
            predictions = predictor.predict_matchday(
                matchday=matchday, players_data=players_data
            )
            
            # Save predictions
            output_file = config.get_season_dir(self.season) / "outputs" / f"pred_matchday_{matchday}.xlsx"
            predictions.to_excel(output_file)
            
            logger.info(f"✓ Generated predictions for {len(predictions)} players")
            logger.info(f"✓ Saved to {output_file}")
            
            return predictions
        except Exception as e:
            logger.error(f"Error generating predictions: {e}")
            raise

    def run_stage_7_lineup(
        self,
        matchday: int,
        strategy: str = "expected_value",
        formation: str = config.DEFAULT_FORMATION,
        budget: float = config.DEFAULT_BUDGET,
        simulations: int = 1000,
    ):
        """Optimize a legal lineup from the requested matchday predictions."""
        from scripts.optimize_lineup import optimize

        prediction_file = config.get_season_dir(self.season) / "outputs" / f"pred_matchday_{matchday}.xlsx"
        result = optimize(
            prediction_file,
            budget=budget,
            formation=formation,
            strategy=strategy,
            simulations=simulations,
        )
        output_file = config.get_season_dir(self.season) / "outputs" / f"lineup_matchday_{matchday}.json"
        output_file.write_text(json.dumps(result, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        logger.info(f"✓ Optimized lineup saved to {output_file}")
        return result
    
    def run_complete_pipeline(self, matchday: int = None):
        """
        Run the complete pipeline from start to finish.
        
        Args:
            matchday: Matchday to predict (None = don't run predictions)
        """
        logger.info("=" * 80)
        logger.info(f"STARTING COMPLETE FANTACALCIO PIPELINE - Season {self.season}")
        logger.info("=" * 80)
        
        start_time = datetime.now()
        
        try:
            # Stage 1: Manual FBref exports
            self.run_stage_1_manual_fbref()
            
            # Stage 2: Votes
            self.run_stage_2_votes()
            
            # Stage 3: Players
            self.run_stage_3_players()
            
            # Stage 4: Training data
            self.run_stage_4_training_data()
            
            # Stage 5: Training
            self.run_stage_5_training()
            
            # Stage 6: Predictions (if matchday specified)
            if matchday:
                self.run_stage_6_predictions(matchday)
                self.run_stage_7_lineup(matchday)
            
            elapsed = datetime.now() - start_time
            logger.info("=" * 80)
            logger.info(f"✓ PIPELINE COMPLETED SUCCESSFULLY in {elapsed}")
            logger.info("=" * 80)
            
        except Exception as e:
            logger.error("=" * 80)
            logger.error(f"✗ PIPELINE FAILED: {e}")
            logger.error("=" * 80)
            raise


def main():
    """Main entry point."""
    parser = argparse.ArgumentParser(
        description='Fantacalcio prediction pipeline',
        formatter_class=argparse.RawDescriptionHelpFormatter
    )
    
    parser.add_argument(
        '--season',
        type=str,
        default=config.CURRENT_SEASON,
        help='Season identifier (e.g., 2627 for 2026/27)'
    )
    
    parser.add_argument(
        '--stage',
        type=str,
        choices=['manual-fbref', 'votes', 'players', 'training-data', 'train', 'predict', 'lineup', 'all'],
        default='all',
        help='Pipeline stage to run (default: all)'
    )
    
    parser.add_argument(
        '--matchday',
        type=int,
        help='Matchday number for predictions'
    )

    parser.add_argument(
        '--strategy',
        choices=['expected_value', 'ceiling', 'floor'],
        default='expected_value',
        help='Lineup objective when using the lineup stage'
    )

    parser.add_argument(
        '--formation',
        default=config.DEFAULT_FORMATION,
        help='Formation for lineup optimization'
    )

    parser.add_argument(
        '--budget',
        type=float,
        default=config.DEFAULT_BUDGET,
        help='Credit budget for lineup optimization'
    )

    parser.add_argument(
        '--simulations',
        type=int,
        default=1000,
        help='Monte Carlo simulations for lineup optimization'
    )
    
    parser.add_argument(
        '--include-history',
        action='store_true',
        help='Include historical seasons in training'
    )
    
    parser.add_argument(
        '--epochs',
        type=int,
        help='Number of training epochs'
    )
    
    args = parser.parse_args()
    
    # Initialize pipeline
    pipeline = FantacalcioPipeline(
        season=args.season,
        include_history=args.include_history
    )
    
    # Run requested stage(s)
    if args.stage == 'all':
        pipeline.run_complete_pipeline(
            matchday=args.matchday,
        )
    elif args.stage == 'manual-fbref':
        pipeline.run_stage_1_manual_fbref()
    elif args.stage == 'votes':
        pipeline.run_stage_2_votes()
    elif args.stage == 'players':
        pipeline.run_stage_3_players()
    elif args.stage == 'training-data':
        pipeline.run_stage_4_training_data()
    elif args.stage == 'train':
        pipeline.run_stage_5_training(epochs=args.epochs)
    elif args.stage == 'predict':
        if not args.matchday:
            logger.error("--matchday is required for prediction stage")
            sys.exit(1)
        pipeline.run_stage_6_predictions(args.matchday)
    elif args.stage == 'lineup':
        if not args.matchday:
            logger.error("--matchday is required for lineup stage")
            sys.exit(1)
        pipeline.run_stage_7_lineup(
            args.matchday,
            strategy=args.strategy,
            formation=args.formation,
            budget=args.budget,
            simulations=args.simulations,
        )


if __name__ == '__main__':
    main()
