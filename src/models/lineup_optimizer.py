"""Budget-aware and correlation-aware lineup optimization."""

from __future__ import annotations

import itertools
import logging
from typing import Dict, List, Optional, Union

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)

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
    """Find legal priced lineups and evaluate them with joint simulations."""

    def __init__(
        self,
        predictions_df: pd.DataFrame,
        budget: float = 500.0,
        formation: str = "3-4-3",
        enable_modificatore: bool = True,
        simulations: int = 1000,
        seed: int = 42,
        candidate_pool: int = 14,
        beam_width: int = 250,
    ) -> None:
        self.df = predictions_df.copy().reset_index(drop=True)
        self.budget = float(budget)
        self.formation = formation if formation in VALID_FORMATIONS else "3-4-3"
        self.enable_modificatore = enable_modificatore
        self.simulations = int(simulations)
        self.seed = seed
        self.candidate_pool = candidate_pool
        self.beam_width = beam_width
        if self.budget <= 0:
            raise ValueError("budget must be positive")
        if self.simulations <= 0:
            raise ValueError("simulations must be positive")

        if "role" not in self.df.columns:
            self.df["role"] = self.df.get("primary_position", "C")
        self.df["role_norm"] = self.df["role"].astype(str).str.upper().map(self._normalize_role)
        price_column = next(
            (column for column in ("price", "cost", "credits", "quotazione") if column in self.df),
            None,
        )
        if price_column is None:
            raise ValueError("Lineup optimization requires a player price column (price/cost/credits)")
        self.df["price"] = pd.to_numeric(self.df[price_column], errors="coerce")
        if self.df["price"].isna().any() or (self.df["price"] < 0).any():
            raise ValueError("Player prices must be numeric and non-negative")

    @staticmethod
    def _normalize_role(role: str) -> str:
        if role in {"P", "GK", "POR", "GOALKEEPER"}:
            return "P"
        if role in {"D", "DF", "DIF", "DEF"}:
            return "D"
        if role in {"C", "M", "CC", "MID", "MIDFIELDER"}:
            return "C"
        if role in {"A", "F", "ATT", "FW", "FORWARD"}:
            return "A"
        return "C"

    @staticmethod
    def calculate_defense_modifier(gk_vote: float, def_votes: List[float]) -> float:
        """Return the standard +1/+3/+6 bonus from the best three defenders."""
        if len(def_votes) < 3:
            return 0.0
        mean_grade = (float(gk_vote) + sum(sorted(def_votes, reverse=True)[:3])) / 4.0
        if mean_grade >= 7.0:
            return 6.0
        if mean_grade >= 6.5:
            return 3.0
        if mean_grade >= 6.0:
            return 1.0
        return 0.0

    def _score_column(self, strategy: str) -> str:
        if strategy == "ceiling" and "ceiling_q90" in self.df:
            return "ceiling_q90"
        if strategy == "floor" and "floor_q10" in self.df:
            return "floor_q10"
        if "predicted_fantavoto" in self.df:
            return "predicted_fantavoto"
        if "median_q50" in self.df:
            return "median_q50"
        raise ValueError("Predictions need predicted_fantavoto or median_q50")

    def _draw_matrix(self, seed: Optional[int] = None) -> tuple[np.ndarray, np.ndarray]:
        """Draw correlated fantasy scores and base votes for every player."""
        rng = np.random.default_rng(self.seed if seed is None else seed)
        n_players = len(self.df)
        common_by_group: dict[str, np.ndarray] = {}
        groups = self.df.get("team", pd.Series(["all"] * n_players)).fillna("all").astype(str)
        score_matrix = np.empty((n_players, self.simulations), dtype=float)
        vote_matrix = np.empty((n_players, self.simulations), dtype=float)
        for index, row in self.df.iterrows():
            group = groups.iloc[index]
            if group not in common_by_group:
                common_by_group[group] = rng.standard_normal(self.simulations)
            common = common_by_group[group]
            independent = rng.standard_normal(self.simulations)
            latent = np.sqrt(0.20) * common + np.sqrt(0.80) * independent
            loc = float(row.get("dist_loc", row.get("predicted_fantavoto", 6.0)))
            scale = float(row.get("dist_scale", 1.2))
            skew = float(row.get("dist_skewness", 0.0))
            tail = float(row.get("dist_tailweight", 1.0))
            score_matrix[index] = loc + scale * np.sinh((np.arcsinh(latent) + skew) / tail)

            vote_loc = float(row.get("vote_dist_loc", row.get("predicted_vote", 6.0)))
            vote_scale = float(row.get("vote_dist_scale", 0.8))
            vote_skew = float(row.get("vote_dist_skewness", 0.0))
            vote_tail = float(row.get("vote_dist_tailweight", 1.0))
            vote_matrix[index] = vote_loc + vote_scale * np.sinh(
                (np.arcsinh(latent) + vote_skew) / vote_tail
            )
        return score_matrix, vote_matrix

    def _role_combinations(self, role: str, count: int, score_column: str) -> list[tuple[int, ...]]:
        """Return a bounded set of high-value role combinations."""
        candidates = self.df[self.df["role_norm"] == role].copy()
        if len(candidates) < count:
            raise ValueError(f"Need at least {count} players for role {role}, found {len(candidates)}")
        candidates["value"] = pd.to_numeric(candidates[score_column], errors="coerce").fillna(0.0) / candidates["price"].clip(lower=1.0)
        candidates = candidates.sort_values([score_column, "value"], ascending=False)
        candidate_indices = candidates.head(self.candidate_pool).index.tolist()
        combinations = list(itertools.combinations(candidate_indices, count))
        combinations.sort(
            key=lambda combo: (
                sum(float(self.df.loc[index, score_column]) for index in combo),
                -sum(float(self.df.loc[index, "price"]) for index in combo),
            ),
            reverse=True,
        )
        return combinations[: self.beam_width]

    def _metric(self, values: np.ndarray, strategy: str) -> float:
        if strategy == "ceiling":
            return float(np.quantile(values, 0.90))
        if strategy == "floor":
            return float(np.quantile(values, 0.10))
        return float(np.mean(values))

    def get_optimal_lineup(
        self,
        formation: Optional[str] = None,
        strategy: str = "expected_value",
    ) -> Dict[str, Union[pd.DataFrame, float, str]]:
        """Optimize a lineup under the 500-credit default budget.

        The search uses a beam over high-value combinations for each position,
        then evaluates complete candidates with correlated Monte Carlo draws.
        ``strategy`` may be ``expected_value``, ``ceiling``, or ``floor``.
        """
        if strategy not in {"expected_value", "ceiling", "floor"}:
            raise ValueError("strategy must be expected_value, ceiling, or floor")
        formation = formation or self.formation
        if formation not in VALID_FORMATIONS:
            raise ValueError(f"Unsupported formation: {formation}")
        n_def, n_mid, n_fwd = VALID_FORMATIONS[formation]
        score_column = self._score_column(strategy)
        score_matrix, vote_matrix = self._draw_matrix()

        role_specs = [("P", 1), ("D", n_def), ("C", n_mid), ("A", n_fwd)]
        role_options = [self._role_combinations(role, count, score_column) for role, count in role_specs]

        # States contain (indices, cost, score draws, vote draws). Keep only the
        # strongest states after each role to avoid enumerating every squad.
        states: list[tuple[tuple[int, ...], float, np.ndarray, np.ndarray]] = [((), 0.0, np.zeros(self.simulations), np.zeros(self.simulations))]
        for options in role_options:
            expanded = []
            for indices, cost, score_draws, vote_draws in states:
                for option in options:
                    option_cost = float(self.df.loc[list(option), "price"].sum())
                    total_cost = cost + option_cost
                    if total_cost <= self.budget:
                        expanded.append((
                            indices + option,
                            total_cost,
                            score_draws + score_matrix[list(option)].sum(axis=0),
                            vote_draws + vote_matrix[list(option)].sum(axis=0),
                        ))
            if not expanded:
                raise ValueError(f"No {formation} lineup fits the {self.budget:g}-credit budget")
            expanded.sort(key=lambda state: self._metric(state[2], strategy), reverse=True)
            states = expanded[: self.beam_width]

        best = None
        for indices, cost, score_draws, vote_draws in states:
            modifier_draws = np.zeros(self.simulations)
            if self.enable_modificatore and n_def >= 4:
                gk_index = indices[0]
                defender_indices = indices[1:1 + n_def]
                defender_votes = np.sort(vote_matrix[list(defender_indices)], axis=0)[::-1][:3]
                average = (vote_matrix[gk_index] + defender_votes.sum(axis=0)) / 4.0
                modifier_draws = np.select(
                    [average >= 7.0, average >= 6.5, average >= 6.0],
                    [6.0, 3.0, 1.0],
                    default=0.0,
                )
            total_draws = score_draws + modifier_draws
            objective = self._metric(total_draws, strategy)
            if best is None or objective > best["objective"]:
                best = {
                    "indices": indices,
                    "cost": cost,
                    "total_draws": total_draws,
                    "modifier_draws": modifier_draws,
                    "objective": objective,
                }

        assert best is not None
        starters = self.df.loc[list(best["indices"])].copy().reset_index(drop=True)
        total_draws = best["total_draws"]
        modifier_draws = best["modifier_draws"]
        return {
            "formation": formation,
            "strategy": strategy,
            "starters": starters,
            "total_cost": round(float(best["cost"]), 2),
            "budget": self.budget,
            "budget_remaining": round(self.budget - float(best["cost"]), 2),
            "base_points": round(float(np.mean(total_draws - modifier_draws)), 2),
            "defense_modifier_bonus": round(float(np.mean(modifier_draws)), 2),
            "total_expected_points": round(float(np.mean(total_draws)), 2),
            "simulation_q10": round(float(np.quantile(total_draws, 0.10)), 2),
            "simulation_q50": round(float(np.quantile(total_draws, 0.50)), 2),
            "simulation_q90": round(float(np.quantile(total_draws, 0.90)), 2),
        }

    def simulate_matchday_slates(self, n_simulations: Optional[int] = None) -> pd.DataFrame:
        """Return correlated fantasy-score draws with players as rows."""
        original = self.simulations
        if n_simulations is not None:
            self.simulations = int(n_simulations)
        try:
            score_matrix, _ = self._draw_matrix()
        finally:
            self.simulations = original
        index = self.df["player"] if "player" in self.df.columns else range(len(self.df))
        return pd.DataFrame(score_matrix, index=index)
