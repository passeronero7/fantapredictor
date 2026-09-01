"""Dataset builder for match-level predictive modeling."""

from __future__ import annotations

import logging
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
        match_context: Optional[pd.DataFrame] = None,
    ) -> Dict[str, pd.DataFrame]:
        """Build feature and target datasets for outfield players and goalkeepers.

        Returns:
            Dict with 'outfield' and 'goalkeepers' DataFrames.
        """
        if votes_df is None:
            if config.DATA_DIR.joinpath("fantapredictor.db").exists():
                if include_historical:
                    from src.db import database, repository

                    conn = database.get_connection(config.DATA_DIR / "fantapredictor.db")
                    try:
                        votes_df = repository.load_votes(
                            conn, through_season=self.season
                        )
                    finally:
                        conn.close()
                else:
                    votes_df = self.votes_processor.load_from_database()
            else:
                if include_historical:
                    raise FileNotFoundError(
                        "Historical training requires the authoritative SQLite warehouse"
                    )
                votes_df = self.votes_processor.process_all_matchdays()

        if votes_df.empty:
            raise ValueError(
                "Observed vote data is required for training; no synthetic targets are generated."
            )

        from src.db.ingestors.common import season_label

        current_label = season_label(self.season)
        votes_df = votes_df.copy()
        if "season" not in votes_df.columns:
            votes_df["season"] = current_label
        if include_historical:
            current_year = int(current_label.split("/", 1)[0])
            season_year = pd.to_numeric(
                votes_df["season"].astype(str).str.extract(r"(\d{4})", expand=False),
                errors="coerce",
            )
            votes_df = votes_df[season_year <= current_year].copy()
        else:
            votes_df = votes_df[votes_df["season"].eq(current_label)].copy()
        if votes_df.empty:
            raise ValueError(f"No observed votes are available for season {current_label}")

        if "player_normalized" not in votes_df.columns and "player" in votes_df.columns:
            votes_df["player_normalized"] = votes_df["player"].map(normalize_name)

        if include_historical and players_df is None:
            season_frames = []
            ordered_seasons = sorted(
                votes_df["season"].dropna().astype(str).unique(),
                key=lambda value: int(value.split("/", 1)[0]),
            )
            for target_season in ordered_seasons:
                season_votes = votes_df[votes_df["season"].eq(target_season)].copy()
                roster = self._observed_roster(season_votes)
                season_players = PlayersProcessor(season=target_season).merge_all_sources(
                    roster_df=roster,
                    votes_df=season_votes,
                    skill_stats_df=pd.DataFrame(),
                    as_of_season=target_season,
                )
                season_frames.append(
                    self._build_rows(season_votes, season_players, match_context)
                )
            dataset = pd.concat(season_frames, ignore_index=True)
        else:
            if players_df is None:
                players_df = self.players_processor.merge_all_sources(
                    votes_df=votes_df,
                    skill_stats_df=pd.DataFrame(),
                    as_of_season=current_label,
                )
            dataset = self._build_rows(votes_df, players_df, match_context)

        # Separate outfield vs goalkeepers
        is_gk = dataset["role"].astype(str).str.upper().isin(["P", "GK", "POR", "GOALKEEPER"])
        df_gk = dataset[is_gk].copy()
        df_outfield = dataset[~is_gk].copy()

        # Construct engineered features
        for df in [df_outfield, df_gk]:
            if not df.empty:
                df["target_vote"] = df["vote"]
                df["target_fantavoto"] = df["fantavoto"]

        logger.info(
            f"Built training datasets: {len(df_outfield)} outfield samples, {len(df_gk)} goalkeeper samples"
        )
        return {"outfield": df_outfield, "goalkeepers": df_gk}

    @staticmethod
    def _observed_roster(votes: pd.DataFrame) -> pd.DataFrame:
        """Build one confirmed historical membership row per observed player."""
        ordered = votes.sort_values("matchday")
        columns = [
            column
            for column in ("player", "player_normalized", "role", "team")
            if column in ordered.columns
        ]
        roster = ordered.drop_duplicates("player_normalized", keep="last")[columns].copy()
        if "team" in roster.columns:
            roster = roster.rename(columns={"team": "club_2026_27"})
        roster["status"] = "confirmed"
        return roster

    @staticmethod
    def _build_rows(
        votes_df: pd.DataFrame,
        players_df: pd.DataFrame,
        match_context: Optional[pd.DataFrame],
    ) -> pd.DataFrame:
        """Merge one or more seasons and compute strictly prior vote features."""
        dataset = votes_df.merge(
            players_df,
            on="player_normalized",
            how="inner",
            suffixes=("", "_player_meta"),
        )

        # Every feature must be known before the target matchday. The aggregate
        # vote columns from PlayersProcessor include the current row, so replace
        # them with expanding prior-only values to prevent target leakage.
        dataset = dataset.sort_values(
            ["season", "player_normalized", "matchday"]
        ).reset_index(drop=True)
        groups = dataset.groupby(["season", "player_normalized"], sort=False)
        prior_count = groups["vote"].transform(lambda values: values.notna().cumsum().shift(fill_value=0))
        prior_vote_sum = groups["vote"].transform(lambda values: values.fillna(0).cumsum().shift(fill_value=0))
        prior_fv_sum = groups["fantavoto"].transform(lambda values: values.fillna(0).cumsum().shift(fill_value=0))
        dataset["season_appearances"] = prior_count.astype(float)
        dataset["mean_vote"] = np.where(prior_count > 0, prior_vote_sum / prior_count, np.nan)
        dataset["mean_fantavoto"] = np.where(prior_count > 0, prior_fv_sum / prior_count, np.nan)

        if match_context is not None and not match_context.empty:
            context = match_context.copy()
            if "team" in context.columns:
                context["team_normalized"] = context["team"].map(normalize_team_name)
            if "team_normalized" in dataset.columns:
                dataset = dataset.merge(
                    context,
                    on=["matchday", "team_normalized"],
                    how="left",
                    suffixes=("", "_context"),
                )
            else:
                dataset["context_available"] = 0
        else:
            # Missing context is explicit; never turn it into a false home signal.
            dataset["is_home"] = np.nan
            dataset["context_available"] = 0

        return dataset
