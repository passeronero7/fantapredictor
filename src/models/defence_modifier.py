"""Empirical calibration of the league defence modifier for roster building.

League rule: average the goalkeeper's vote with the best three defenders'
votes; +1 strictly above 6.5, +3 strictly above 7.0.  The lineup optimizer
applies the rule exactly each matchday; this module turns it into a linear,
per-player auction premium by measuring how the expected modifier changes
with the lineup's average vote on historical matchdays.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd
from scipy.stats import norm

THRESHOLDS = ((6.5, 1.0), (7.0, 3.0))


def modifier_points(average: np.ndarray | pd.Series | float) -> np.ndarray:
    """League modifier for a GK + best-three-defenders average (strict)."""
    average = np.asarray(average, dtype=float)
    points = np.zeros_like(average)
    for threshold, value in THRESHOLDS:
        points = np.where(average > threshold, value, points)
    return points


def lineup_averages(votes: pd.DataFrame) -> pd.DataFrame:
    """Per club and matchday: GK vote plus the best three defender votes.

    Only matchdays where the club fielded a voted goalkeeper and at least
    three voted defenders count; the modifier does not apply otherwise.
    """
    frame = votes.dropna(subset=["vote", "team"]).copy()
    frame["role"] = frame["role"].astype(str).str.upper().str.strip()
    rows = []
    for (season, team, matchday), group in frame.groupby(["season", "team", "matchday"]):
        keepers = group.loc[group["role"].eq("P"), "vote"]
        defenders = group.loc[group["role"].eq("D"), "vote"].sort_values(ascending=False)
        if keepers.empty or len(defenders) < 3:
            continue
        average = (float(keepers.max()) + float(defenders.head(3).sum())) / 4.0
        rows.append({"season": season, "team": team, "matchday": matchday, "average": average})
    return pd.DataFrame(rows)


@dataclass(frozen=True)
class ModifierCalibration:
    center: float
    sd: float
    matchdays: int
    mean_points: float
    marginal_per_player: float

    def as_dict(self) -> dict[str, float]:
        return {
            "lineup_average_center": round(self.center, 4),
            "lineup_average_sd_within_team": round(self.sd, 4),
            "team_matchdays": self.matchdays,
            "observed_mean_modifier_points": round(self.mean_points, 4),
            "marginal_points_per_vote_point_per_player": round(self.marginal_per_player, 4),
        }


def marginal_per_player(center: float, sd: float) -> float:
    """d E[modifier] / d(one player's expected vote) under a normal average.

    One player moves the four-vote average by a quarter of his own change.
    """
    density = sum(value_step * norm.pdf(threshold, loc=center, scale=sd)
                  for threshold, value_step in _steps())
    return density / 4.0


def _steps():
    previous = 0.0
    for threshold, value in THRESHOLDS:
        yield threshold, value - previous
        previous = value


def calibrate(averages: pd.DataFrame) -> ModifierCalibration:
    """Centre, within-team spread and marginal value from observed matchdays."""
    if averages.empty:
        raise ValueError("No matchday with a voted goalkeeper and three defenders")
    team_mean = averages.groupby(["season", "team"])["average"].transform("mean")
    residual = averages["average"] - team_mean
    sd = float(residual.std(ddof=1))
    center = float(averages["average"].mean())
    return ModifierCalibration(
        center=center,
        sd=sd,
        matchdays=int(len(averages)),
        mean_points=float(modifier_points(averages["average"]).mean()),
        marginal_per_player=marginal_per_player(center, sd),
    )
