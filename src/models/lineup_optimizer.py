"""Lineup optimizer for Fantacalcio with Monte Carlo simulation support."""

from __future__ import annotations

import logging
from typing import Dict, List, Optional, Tuple, Union

import numpy as np
import pandas as pd

from config.settings import config
from src.models.distributions import SinhArcsinhDistribution

logger = logging.getLogger(__name__)

# Standard legal Fantacalcio formations (Defenders - Midfielders - Forwards)
VALID_FORMATIONS = {
    "3-4-3": (3, 4, 3),
    "3-5-2": (3, 5, 2),
    "4-3-3": (4, 3, 3),
    "4-4-2": (4, 4, 2),
    "4-5-1": (4, 5, 1),
    "5-3-2": (5, 3, 2),
    "5-4-1": (5, 4, 1),
}


class LineupOptimizer:
    """Optimizes Fantacalcio lineups using Monte Carlo probabilistic simulation."""

    def __init__(
        self,
        predictions_df: pd.DataFrame,
        budget: float = 500.0,
        formation: str = "3-4-3",
        enable_modificatore: bool = True,
        simulations: int = 1000,
    ) -> None:
        self.df = predictions_df.copy()
        self.budget = float(budget)
        self.formation = formation if formation in VALID_FORMATIONS else "3-4-3"
        self.enable_modificatore = enable_modificatore
        self.simulations = simulations

        # Normalize role column
        if "role" not in self.df.columns:
            if "primary_position" in self.df.columns:
                self.df["role"] = self.df["primary_position"]
            else:
                self.df["role"] = "M"

        self.df["role_norm"] = self.df["role"].astype(str).str.upper().map(
            lambda r: "P" if r in ["P", "GK", "POR"]
            else "D" if r in ["D", "DF", "DIF"]
            else "C" if r in ["C", "M", "CC", "MID"]
            else "A" if r in ["A", "F", "ATT", "FW"]
            else "C"
        )

    def calculate_defense_modifier(self, gk_vote: float, def_votes: List[float]) -> float:
        """Calculate standard Italian Serie A defense modifier bonus points.

        Rules:
        - Takes the Goalkeeper grade plus top 3 Defender grades (4 total ratings).
        - If the arithmetic mean >= 6.0: +1 bonus
        - If >= 6.5: +3 bonus
        - If >= 7.0: +6 bonus
        """
        if len(def_votes) < 3:
            return 0.0
        top3_def = sorted(def_votes, reverse=True)[:3]
        mean_grade = (gk_vote + sum(top3_def)) / 4.0

        if mean_grade >= 7.0:
            return 6.0
        elif mean_grade >= 6.5:
            return 3.0
        elif mean_grade >= 6.0:
            return 1.0
        return 0.0

    def get_optimal_lineup(
        self,
        formation: Optional[str] = None,
        strategy: str = "expected_value",
    ) -> Dict[str, Union[pd.DataFrame, float, str]]:
        """Select the highest-scoring legal starting lineup.

        Args:
            formation: e.g. '3-4-3', '4-3-3', etc.
            strategy: 'expected_value' (mean), 'ceiling' (q90 upside), or 'floor' (q10 safe).
        """
        formation = formation or self.formation
        if formation not in VALID_FORMATIONS:
            formation = "3-4-3"

        n_def, n_mid, n_fwd = VALID_FORMATIONS[formation]

        # Determine metric column
        if strategy == "ceiling" and "ceiling_q90" in self.df.columns:
            score_col = "ceiling_q90"
        elif strategy == "floor" and "floor_q10" in self.df.columns:
            score_col = "floor_q10"
        elif "predicted_fantavoto" in self.df.columns:
            score_col = "predicted_fantavoto"
        elif "selection_score" in self.df.columns:
            score_col = "selection_score"
        else:
            score_col = "median_q50" if "median_q50" in self.df.columns else self.df.columns[0]

        # Separate positions
        gks = self.df[self.df["role_norm"] == "P"].sort_values(score_col, ascending=False)
        defs = self.df[self.df["role_norm"] == "D"].sort_values(score_col, ascending=False)
        mids = self.df[self.df["role_norm"] == "C"].sort_values(score_col, ascending=False)
        fwds = self.df[self.df["role_norm"] == "A"].sort_values(score_col, ascending=False)

        selected_gk = gks.head(1)
        selected_def = defs.head(n_def)
        selected_mid = mids.head(n_mid)
        selected_fwd = fwds.head(n_fwd)

        starters = pd.concat([selected_gk, selected_def, selected_mid, selected_fwd], ignore_index=True)
        base_points = float(pd.to_numeric(starters[score_col], errors="coerce").fillna(0.0).sum()) if not starters.empty else 0.0

        # Compute modifier bonus if 4+ defenders in formation
        mod_bonus = 0.0
        if self.enable_modificatore and n_def >= 4 and not selected_gk.empty and not selected_def.empty:
            gk_vote_val = float(selected_gk.iloc[0].get("predicted_vote", 6.0))
            def_vote_vals = selected_def["predicted_vote"].astype(float).tolist() if "predicted_vote" in selected_def.columns else [6.0] * n_def
            mod_bonus = self.calculate_defense_modifier(gk_vote_val, def_vote_vals)

        total_projected = round(base_points + mod_bonus, 2)

        return {
            "formation": formation,
            "strategy": strategy,
            "starters": starters,
            "base_points": round(base_points, 2),
            "defense_modifier_bonus": mod_bonus,
            "total_expected_points": total_projected,
        }

    def simulate_matchday_slates(self, n_simulations: Optional[int] = None) -> pd.DataFrame:
        """Run Monte Carlo simulations across all players to obtain outcome distributions."""
        n_sims = n_simulations or self.simulations
        results = []

        for _, row in self.df.iterrows():
            loc = float(row.get("dist_loc", row.get("predicted_fantavoto", 6.0)))
            scale = float(row.get("dist_scale", 1.2))
            skew = float(row.get("dist_skewness", 0.0))
            tail = float(row.get("dist_tailweight", 1.0))

            dist = SinhArcsinhDistribution(loc=loc, scale=scale, skewness=skew, tailweight=tail)
            draws = dist.rvs(size=n_sims)
            results.append(draws)

        sim_matrix = np.array(results)
        return pd.DataFrame(sim_matrix, index=self.df["player"] if "player" in self.df.columns else range(len(self.df)))
