"""Dataset builder for match-level predictive modeling."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Dict, Optional

import numpy as np
import pandas as pd

from config.settings import config
from src.data_processing.players_processor import PlayersProcessor
from src.data_processing.votes_processor import VotesProcessor
from src.utils.name_matching import normalize_name, normalize_team_name

logger = logging.getLogger(__name__)


class MatchDataBuilder:
    """Constructs training and inference feature matrices for matchday predictions."""

    def __init__(self, season: Optional[str] = None) -> None:
        self.season = season or config.CURRENT_SEASON
        self.season_dir = config.get_season_dir(self.season)
        self.votes_processor = VotesProcessor(season=self.season)
        self.players_processor = PlayersProcessor(season=self.season)

    def build_complete_dataset(
        self,
        include_historical: bool = False,
        votes_df: Optional[pd.DataFrame] = None,
        players_df: Optional[pd.DataFrame] = None,
    ) -> Dict[str, pd.DataFrame]:
        """Build feature and target datasets for outfield players and goalkeepers.

        Returns:
            Dict with 'outfield' and 'goalkeepers' DataFrames.
        """
        if votes_df is None:
            votes_df = self.votes_processor.process_all_matchdays()

        if players_df is None:
            players_df = self.players_processor.merge_all_sources(votes_df=votes_df)

        if votes_df.empty:
            logger.warning("No vote data available; generating synthetic bootstrap training records.")
            return self._build_bootstrap_dataset(players_df)

        # Merge player static/historical features with each match instance
        if "player_normalized" not in votes_df.columns and "player" in votes_df.columns:
            votes_df["player_normalized"] = votes_df["player"].map(normalize_name)

        dataset = votes_df.merge(
            players_df,
            on="player_normalized",
            how="inner",
            suffixes=("", "_player_meta"),
        )

        # Separate outfield vs goalkeepers
        is_gk = dataset["role"].astype(str).str.upper().isin(["P", "GK", "POR", "GOALKEEPER"])
        df_gk = dataset[is_gk].copy()
        df_outfield = dataset[~is_gk].copy()

        # Construct engineered features
        for df in [df_outfield, df_gk]:
            if not df.empty:
                df["is_home"] = 1.0  # Default balanced indicator
                df["target_vote"] = df["vote"]
                df["target_fantavoto"] = df["fantavoto"]

        logger.info(
            f"Built training datasets: {len(df_outfield)} outfield samples, {len(df_gk)} goalkeeper samples"
        )
        return {"outfield": df_outfield, "goalkeepers": df_gk}

    def _build_bootstrap_dataset(self, players_df: pd.DataFrame) -> Dict[str, pd.DataFrame]:
        """Build default template feature sets when weekly matchday votes are pending."""
        if players_df.empty:
            players_df = self.players_processor.merge_all_sources()

        is_gk = players_df.get("primary_position", "").astype(str).str.upper().isin(["GK", "P"])
        df_gk = players_df[is_gk].copy()
        df_outfield = players_df[~is_gk].copy()

        # Add default target placeholders
        for df in [df_outfield, df_gk]:
            if not df.empty:
                df["target_vote"] = 6.0
                df["target_fantavoto"] = 6.0

        return {"outfield": df_outfield, "goalkeepers": df_gk}
