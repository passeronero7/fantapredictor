"""Player data merging module combining multi-source statistics with Fantacalcio metadata."""

from __future__ import annotations

import logging
from typing import Optional

import numpy as np
import pandas as pd

from config.settings import config
from src.utils.name_matching import normalize_name, normalize_team_name

logger = logging.getLogger(__name__)


class PlayersProcessor:
    """Merges player statistics across statistical providers and Fantacalcio records."""

    def __init__(self, season: Optional[str] = None) -> None:
        self.season = season or config.CURRENT_SEASON
        self.season_dir = config.get_season_dir(self.season)

    def merge_all_sources(
        self,
        roster_df: Optional[pd.DataFrame] = None,
        history_df: Optional[pd.DataFrame] = None,
        votes_df: Optional[pd.DataFrame] = None,
    ) -> pd.DataFrame:
        """Merge roster, historical event data (xG/xA), and in-season votes into unified records."""
        # 1. Load active roster
        if roster_df is None or roster_df.empty:
            roster_path = self.season_dir / "rosters" / f"virgilio_rosters_{config.CURRENT_SEASON_FULL}.csv"
            if roster_path.exists():
                roster_df = pd.read_csv(roster_path)
            elif votes_df is not None and not votes_df.empty:
                # Derive unique player roster directly from votes data
                cols = [c for c in ["player", "player_normalized", "role", "team"] if c in votes_df.columns]
                unique_players = votes_df.drop_duplicates("player_normalized")[cols].copy()
                unique_players["status"] = "confirmed"
                roster_df = unique_players
            else:
                logger.warning(f"Roster file not found at {roster_path}, attempting fallback.")
                roster_df = pd.DataFrame(columns=["player", "club_2026_27", "player_normalized", "status"])

        if "player_normalized" not in roster_df.columns and "player" in roster_df.columns:
            roster_df["player_normalized"] = roster_df["player"].map(normalize_name)

        # 2. Load historical advanced stats (Understat / open league data)
        if history_df is None:
            history_path = self.season_dir / "historical" / "understat_open_league_history_for_roster.csv"
            if history_path.exists():
                history_df = pd.read_csv(history_path)
            else:
                history_df = pd.DataFrame()

        # Compute aggregate historical metrics per player
        if not history_df.empty:
            if "player_normalized" not in history_df.columns:
                player_col = "player" if "player" in history_df.columns else "player_name"
                history_df["player_normalized"] = history_df[player_col].map(normalize_name)

            for col in ["time", "xG", "xA", "npxG", "shots", "key_passes", "goals", "assists"]:
                if col in history_df.columns:
                    history_df[col] = pd.to_numeric(history_df[col], errors="coerce").fillna(0.0)

            hist_agg = history_df.groupby("player_normalized").agg(
                hist_games=("games", "sum") if "games" in history_df.columns else ("year", "size"),
                hist_minutes=("time", "sum"),
                hist_xg=("xG", "sum"),
                hist_xa=("xA", "sum"),
                hist_npxg=("npxG", "sum"),
                hist_goals=("goals", "sum"),
                hist_assists=("assists", "sum"),
                latest_year=("year", "max"),
                primary_position=("primary_position", "first") if "primary_position" in history_df.columns else ("position", "first"),
            ).reset_index()

            # Apply Bayesian shrinkage to per90 metrics for low-minute samples
            prior_minutes = 450.0
            hist_agg["hist_xg_per90"] = np.where(
                hist_agg["hist_minutes"] > 0,
                90.0 * hist_agg["hist_xg"] / (hist_agg["hist_minutes"] + prior_minutes),
                0.0,
            )
            hist_agg["hist_xa_per90"] = np.where(
                hist_agg["hist_minutes"] > 0,
                90.0 * hist_agg["hist_xa"] / (hist_agg["hist_minutes"] + prior_minutes),
                0.0,
            )
        else:
            hist_agg = pd.DataFrame(columns=["player_normalized", "hist_minutes", "hist_xg", "hist_xa", "hist_xg_per90", "hist_xa_per90"])

        # 3. Aggregate weekly votes if present
        if votes_df is not None and not votes_df.empty:
            if "player_normalized" not in votes_df.columns:
                votes_df["player_normalized"] = votes_df["player"].map(normalize_name)

            # Filter valid voted games
            voted_games = votes_df[votes_df["vote"] > 0]
            votes_agg = voted_games.groupby("player_normalized").agg(
                season_appearances=("matchday", "nunique"),
                mean_vote=("vote", "mean"),
                mean_fantavoto=("fantavoto", "mean"),
                std_vote=("vote", "std"),
                std_fantavoto=("fantavoto", "std"),
                season_goals=("goals", "sum"),
                season_assists=("assists", "sum"),
                season_yellows=("yellow_cards", "sum"),
                season_reds=("red_cards", "sum"),
            ).reset_index()
            votes_agg["std_vote"] = votes_agg["std_vote"].fillna(0.0)
            votes_agg["std_fantavoto"] = votes_agg["std_fantavoto"].fillna(0.0)
        else:
            votes_agg = pd.DataFrame(columns=["player_normalized", "season_appearances", "mean_vote", "mean_fantavoto"])

        # 4. Join all tables on player_normalized
        merged = roster_df.copy()
        if not hist_agg.empty:
            merged = merged.merge(hist_agg, on="player_normalized", how="left")
        if not votes_agg.empty:
            merged = merged.merge(votes_agg, on="player_normalized", how="left")

        # Clean team and position representations
        if "club_2026_27" in merged.columns:
            merged["team"] = merged["club_2026_27"].map(normalize_team_name)

        logger.info(f"Merged master player dataset: {len(merged)} players")
        return merged
