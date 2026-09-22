"""Budget-constrained optimizer for a complete Classic auction roster.

The optimizer consumes out-of-sample or simulated player forecasts.  It does
not train a model and deliberately keeps auction cost separate from the public
quotation used as a feature by upstream forecasts.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd
from scipy.optimize import Bounds, LinearConstraint, milp
from scipy.sparse import lil_matrix


ROSTER_SLOTS = {"P": 3, "D": 8, "C": 8, "A": 6}
DEPTH_WEIGHTS = {
    "P": (1.00, 0.22, 0.08),
    "D": (1.00, 0.96, 0.90, 0.82, 0.48, 0.38, 0.30, 0.24),
    "C": (1.00, 0.97, 0.92, 0.85, 0.62, 0.48, 0.36, 0.28),
    "A": (1.00, 0.97, 0.90, 0.72, 0.48, 0.32),
}


@dataclass(frozen=True)
class AuctionOptimizationConfig:
    budget: int = 500
    reserve: int = 0
    defence_modifier: bool = False
    reliability_weight: float = 0.25


def player_utility(frame: pd.DataFrame, reliability_weight: float = 0.25) -> pd.Series:
    """Risk-adjust expected fantasy contribution from Monte Carlo summaries."""
    expected = pd.to_numeric(frame["expected_fantavoto"], errors="coerce").fillna(0.0)
    plays = pd.to_numeric(frame["p_plays"], errors="coerce").fillna(0.0).clip(0.0, 1.0)
    reliable = pd.to_numeric(
        frame["p_horizon_median_good"], errors="coerce"
    ).fillna(0.0).clip(0.0, 1.0)
    availability = pd.to_numeric(
        frame.get("availability_factor", pd.Series(1.0, index=frame.index)),
        errors="coerce",
    ).fillna(1.0).clip(0.0, 1.0)
    multiplier = (1.0 - reliability_weight) + reliability_weight * reliable
    return expected * plays * multiplier * availability


def optimize_auction_roster(
    players: pd.DataFrame,
    config: AuctionOptimizationConfig = AuctionOptimizationConfig(),
) -> dict[str, object]:
    """Select exactly 3P/8D/8C/6A under the auction budget with MILP.

    Players are assigned to ordered depth slots.  This avoids pretending that
    the eighth defender contributes as much season utility as a regular
    starter, while retaining a linear and exactly reproducible optimization.
    """
    required = {
        "player", "team", "role", "auction_cost", "expected_fantavoto",
        "p_plays", "p_horizon_median_good",
    }
    missing = required - set(players.columns)
    if missing:
        raise ValueError(f"Missing optimizer columns: {', '.join(sorted(missing))}")

    frame = players.copy()
    frame["role"] = frame["role"].astype(str).str.upper().str.strip()
    frame["auction_cost"] = pd.to_numeric(frame["auction_cost"], errors="coerce")
    # Filter before reindexing: resetting the index first and filtering after
    # left gaps in frame.index while every downstream row-position lookup
    # (offset + player_index, frame.loc[player_index]) assumed a dense
    # range(len(frame)) index, causing out-of-bounds writes into the
    # constraint matrix whenever any row was dropped here.
    frame = frame[
        frame["role"].isin(ROSTER_SLOTS)
        & frame["auction_cost"].notna()
        & frame["auction_cost"].ge(1)
    ].copy().reset_index(drop=True)
    if frame["player"].duplicated().any():
        raise ValueError("Player names must be unique in the eligible pool")
    for role, count in ROSTER_SLOTS.items():
        if int(frame["role"].eq(role).sum()) < count:
            raise ValueError(f"Insufficient eligible {role} players")

    frame["utility"] = player_utility(frame, config.reliability_weight)
    if config.defence_modifier:
        # This league's modifier tops out at +3, so the roster-construction
        # premium is deliberately smaller than for the common +1/+3/+6 table.
        # Exact weekly points remain the responsibility of the lineup simulator.
        frame.loc[frame["role"].eq("D"), "utility"] *= 1.04

    slots = [
        (role, depth, weight)
        for role, count in ROSTER_SLOTS.items()
        for depth, weight in enumerate(DEPTH_WEIGHTS[role][:count], start=1)
    ]
    variables = [
        (player_index, slot_index)
        for slot_index, (role, _, _) in enumerate(slots)
        for player_index in frame.index[frame["role"].eq(role)]
    ]
    variable_index = {pair: index for index, pair in enumerate(variables)}
    objective = np.zeros(len(variables), dtype=float)
    costs = np.zeros(len(variables), dtype=float)
    for variable, (player_index, slot_index) in enumerate(variables):
        weight = slots[slot_index][2]
        objective[variable] = -float(frame.at[player_index, "utility"]) * weight
        costs[variable] = float(frame.at[player_index, "auction_cost"])

    # One player for every depth slot, each player at most once, total cost <= budget.
    rows = len(slots) + len(frame) + 1
    matrix = lil_matrix((rows, len(variables)), dtype=float)
    lower = np.full(rows, -np.inf)
    upper = np.full(rows, np.inf)
    for slot_index in range(len(slots)):
        for player_index in frame.index:
            variable = variable_index.get((player_index, slot_index))
            if variable is not None:
                matrix[slot_index, variable] = 1.0
        lower[slot_index] = upper[slot_index] = 1.0
    offset = len(slots)
    for player_index in frame.index:
        for slot_index in range(len(slots)):
            variable = variable_index.get((player_index, slot_index))
            if variable is not None:
                matrix[offset + player_index, variable] = 1.0
        upper[offset + player_index] = 1.0
    matrix[-1, :] = costs
    spendable = float(config.budget - config.reserve)
    upper[-1] = spendable

    solution = milp(
        c=objective,
        integrality=np.ones(len(variables)),
        bounds=Bounds(0.0, 1.0),
        constraints=LinearConstraint(matrix.tocsr(), lower, upper),
        options={"time_limit": 60.0},
    )
    if not solution.success or solution.x is None:
        raise ValueError(f"No legal roster found: {solution.message}")

    selected_rows = []
    for variable in np.flatnonzero(solution.x > 0.5):
        player_index, slot_index = variables[int(variable)]
        role, depth, weight = slots[slot_index]
        row = frame.loc[player_index].to_dict()
        row.update({
            "depth": depth,
            "depth_weight": weight,
            "weighted_utility": float(row["utility"]) * weight,
        })
        selected_rows.append(row)
    selected = pd.DataFrame(selected_rows).sort_values(["role", "depth"])
    counts = selected.groupby("role").size().to_dict()
    if counts != ROSTER_SLOTS or selected["player"].duplicated().any():
        raise RuntimeError("Solver returned an invalid roster")
    total_cost = int(round(selected["auction_cost"].sum()))
    if total_cost > spendable:
        raise RuntimeError("Solver returned an over-budget roster")
    return {
        "roster": selected.reset_index(drop=True),
        "total_cost": total_cost,
        "budget": config.budget,
        "reserve": config.reserve,
        "budget_remaining": config.budget - total_cost,
        "objective": float(selected["weighted_utility"].sum()),
        "defence_modifier": config.defence_modifier,
    }
