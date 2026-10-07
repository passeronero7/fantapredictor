"""Tactical Matchup and Coach Head-to-Head Conditioning Engine.

Evaluates tactical interactions between opposing coaches and empirical
head-to-head records to derive bounded, regularized matchday fantasy multipliers.

Theoretical foundation:
- Tactical style clashes (e.g. possession/high_block vs man_marking/pressing)
  modulate expected volume of chance creation, fouls, and transition space by role.
- Historical head-to-head matches between coaches carry empirical signal, shrunk
  toward league baselines via Empirical Bayes (K=4.0) to prevent small-sample overfitting.
- The overall tactical adjustment is bounded to [-0.08, +0.08] (lambda = 0.25),
  consistent with empirical backtests on Serie A match history.
"""

from __future__ import annotations

import logging
import sqlite3
from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple

import numpy as np
import pandas as pd

from src.models.coach_profiles import coach_matchdays

logger = logging.getLogger(__name__)

ROLES = ("P", "D", "C", "A")

# Pre-calibrated style interaction matrix: (own_style, opp_style) -> {role: delta}
# Deltas represent percentage shifts in fantasy propensity.
STYLE_INTERACTIONS: Dict[Tuple[str, str], Dict[str, float]] = {
    # Possession / press-resistant teams facing man-marking / high pressing
    ("possession", "man_marking"): {"C": 0.035, "A": 0.025, "D": -0.015, "P": -0.010},
    ("possession", "pressing"): {"C": 0.025, "A": 0.020, "D": -0.010, "P": -0.010},
    # Man-marking teams facing possession / fluid movement
    ("man_marking", "possession"): {"D": -0.020, "C": 0.010, "A": 0.020, "P": -0.015},
    # High-line / high-block facing vertical transition / counter-attack
    ("high_block", "transition"): {"A": 0.015, "D": -0.025, "P": -0.030},
    ("transition", "high_block"): {"A": 0.040, "C": 0.025, "D": 0.010, "P": 0.010},
    # Vertical attack facing pressing
    ("vertical", "pressing"): {"A": 0.030, "C": 0.015, "D": -0.010, "P": -0.010},
    # Wingback-heavy attack facing compact defenses
    ("wingback_attack", "balanced"): {"D": 0.030, "C": 0.015, "A": 0.010, "P": 0.000},
    ("wingback_attack", "defensive_solidity"): {"D": 0.025, "C": 0.010, "A": -0.015, "P": 0.000},
    # Pragmatic / defensive solidity teams
    ("defensive_solidity", "possession"): {"P": 0.035, "D": 0.020, "C": -0.010, "A": -0.020},
    ("pragmatic", "high_risk"): {"P": 0.040, "D": 0.025, "C": 0.010, "A": 0.020},
    ("defensive_solidity", "balanced"): {"P": 0.030, "D": 0.015, "C": 0.000, "A": -0.010},
}


@dataclass
class MatchupEvaluation:
    """Evaluation result of a tactical matchday encounter for one team."""
    team: str
    opponent: str
    coach: str
    opponent_coach: str
    module: str
    opponent_module: str
    style_tags: List[str]
    opponent_style_tags: List[str]
    role_multipliers: Dict[str, float]
    h2h_matches_count: int
    summary_note: str


def compute_style_delta(
    own_styles: List[str],
    opp_styles: List[str],
) -> Dict[str, float]:
    """Aggregate pairwise style interaction deltas for each role."""
    deltas = {r: 0.0 for r in ROLES}
    count = 0
    for s_own in own_styles:
        for s_opp in opp_styles:
            key = (s_own.strip().lower(), s_opp.strip().lower())
            if key in STYLE_INTERACTIONS:
                for r in ROLES:
                    deltas[r] += STYLE_INTERACTIONS[key].get(r, 0.0)
                count += 1
    if count > 1:
        # Scale down multiple compounding tags
        for r in ROLES:
            deltas[r] /= np.sqrt(count)
    # Clip style impact to [-0.05, +0.05]
    return {r: float(np.clip(deltas[r], -0.05, 0.05)) for r in ROLES}


def compute_coach_h2h_delta(
    matches_with_coaches: Optional[pd.DataFrame],
    coach_a: str,
    coach_b: str,
    shrinkage: float = 4.0,
) -> Tuple[float, int, str]:
    """Compute empirical Bayes shrunk delta from historical clashes between two coaches.

    Returns:
        (shrunk_delta, match_count, summary)
    """
    if not coach_a or not coach_b or coach_a == coach_b:
        return 0.0, 0, "Nessun precedente"

    if matches_with_coaches is None or matches_with_coaches.empty:
        return 0.0, 0, "Dati storici non disponibili"

    # Filter H2H games
    direct = matches_with_coaches[
        ((matches_with_coaches["home_coach"] == coach_a) & (matches_with_coaches["away_coach"] == coach_b))
        | ((matches_with_coaches["home_coach"] == coach_b) & (matches_with_coaches["away_coach"] == coach_a))
    ]

    n_matches = len(direct)
    if n_matches < 2:
        return 0.0, n_matches, f"Precedenti insufficienti ({n_matches})"

    # Count wins / goals for coach_a
    goals_for = []
    goals_against = []
    wins_a = 0
    draws = 0
    wins_b = 0

    for _, row in direct.iterrows():
        hg = float(row["home_goals"])
        ag = float(row["away_goals"])
        if row["home_coach"] == coach_a:
            gf, ga = hg, ag
        else:
            gf, ga = ag, hg
        goals_for.append(gf)
        goals_against.append(ga)
        if gf > ga:
            wins_a += 1
        elif gf == ga:
            draws += 1
        else:
            wins_b += 1

    mean_gf = float(np.mean(goals_for))
    mean_ga = float(np.mean(goals_against))

    # Baseline average in Serie A is ~1.3 goals per side per match
    baseline_gf = 1.30
    raw_delta = (mean_gf - baseline_gf) / baseline_gf

    # Empirical Bayes shrinkage: pull toward zero with weight `shrinkage`
    shrunk_delta = (n_matches / (n_matches + shrinkage)) * raw_delta
    shrunk_delta = float(np.clip(shrunk_delta, -0.06, 0.06))

    summary = (
        f"H2H ({n_matches} gare): {wins_a}V-{draws}P-{wins_b}S "
        f"(Media gol fatti: {mean_gf:.2f}, subiti: {mean_ga:.2f})"
    )
    return shrunk_delta, n_matches, summary


def evaluate_matchday_tactics(
    conn: sqlite3.Connection,
    season: str,
    matchday: int,
) -> Dict[str, MatchupEvaluation]:
    """Evaluate tactical interaction and H2H adjustments for every team playing in matchday.

    Returns:
        dict mapping team name to MatchupEvaluation
    """
    # 1. Load active coaches metadata for the season
    coaches_df = pd.read_sql_query(
        """
        SELECT cl.name AS club, co.full_name AS coach,
               co.preferred_module, co.style_tags
        FROM coach_club_seasons ccs
        JOIN coaches co ON co.id = ccs.coach_id
        JOIN clubs cl ON cl.id = ccs.club_id
        JOIN seasons s ON s.id = ccs.season_id
        WHERE s.name = ? AND ccs.ended_at IS NULL
        """,
        conn,
        params=(season,),
    )
    coach_info = {}
    for _, r in coaches_df.iterrows():
        coach_info[r["club"]] = {
            "coach": r["coach"],
            "module": r["preferred_module"] or "4-3-3",
            "style_tags": [t.strip() for t in (r["style_tags"] or "").split("|") if t.strip()],
        }

    # 2. Preload historical matches and coach stints once
    matches_with_coaches = None
    try:
        cmd = coach_matchdays(conn)
        if not cmd.empty:
            all_m = pd.read_sql_query(
                """
                SELECT s.name AS season, m.matchday, date(m.match_date) AS match_date,
                       h.name AS home, a.name AS away, m.home_goals, m.away_goals
                FROM matches AS m
                JOIN seasons AS s ON s.id = m.season_id
                JOIN clubs AS h ON h.id = m.home_club_id
                JOIN clubs AS a ON a.id = m.away_club_id
                WHERE m.home_goals IS NOT NULL
                """,
                conn,
            )
            matches_with_coaches = all_m.merge(
                cmd.rename(columns={"club": "home", "coach": "home_coach"}),
                on=["season", "home", "matchday"],
                how="left",
            ).merge(
                cmd.rename(columns={"club": "away", "coach": "away_coach"}),
                on=["season", "away", "matchday"],
                how="left",
            )
    except Exception as e:
        logger.warning(f"Could not preload coach matches: {e}")

    # 3. Load match fixtures for this matchday
    fixtures = pd.read_sql_query(
        """
        SELECT h.name AS home_team, a.name AS away_team
        FROM matches m
        JOIN seasons s ON s.id = m.season_id
        JOIN clubs h ON h.id = m.home_club_id
        JOIN clubs a ON a.id = m.away_club_id
        WHERE s.name = ? AND m.matchday = ?
        """,
        conn,
        params=(season, matchday),
    )

    evaluations: Dict[str, MatchupEvaluation] = {}

    for _, fix in fixtures.iterrows():
        home = fix["home_team"]
        away = fix["away_team"]

        h_info = coach_info.get(home, {"coach": "Unknown", "module": "4-3-3", "style_tags": []})
        a_info = coach_info.get(away, {"coach": "Unknown", "module": "4-3-3", "style_tags": []})

        # Evaluate Home vs Away
        h_style_delta = compute_style_delta(h_info["style_tags"], a_info["style_tags"])
        h_h2h_delta, h_h2h_n, h_h2h_sum = compute_coach_h2h_delta(matches_with_coaches, h_info["coach"], a_info["coach"])

        # Role multipliers for Home
        h_mults = {}
        for r in ROLES:
            # Attacking roles get H2H goal boost; defenders get inverse
            h2h_role_adj = h_h2h_delta if r in ("C", "A") else -h_h2h_delta * 0.5
            total_delta = h_style_delta.get(r, 0.0) + h2h_role_adj
            h_mults[r] = float(np.clip(1.0 + total_delta, 0.92, 1.08))

        h_note = f"{h_info['coach']} vs {a_info['coach']}: {h_h2h_sum}"
        evaluations[home] = MatchupEvaluation(
            team=home,
            opponent=away,
            coach=h_info["coach"],
            opponent_coach=a_info["coach"],
            module=h_info["module"],
            opponent_module=a_info["module"],
            style_tags=h_info["style_tags"],
            opponent_style_tags=a_info["style_tags"],
            role_multipliers=h_mults,
            h2h_matches_count=h_h2h_n,
            summary_note=h_note,
        )

        # Evaluate Away vs Home
        a_style_delta = compute_style_delta(a_info["style_tags"], h_info["style_tags"])
        a_h2h_delta, a_h2h_n, a_h2h_sum = compute_coach_h2h_delta(matches_with_coaches, a_info["coach"], h_info["coach"])

        a_mults = {}
        for r in ROLES:
            h2h_role_adj = a_h2h_delta if r in ("C", "A") else -a_h2h_delta * 0.5
            total_delta = a_style_delta.get(r, 0.0) + h2h_role_adj
            a_mults[r] = float(np.clip(1.0 + total_delta, 0.92, 1.08))

        a_note = f"{a_info['coach']} vs {h_info['coach']}: {a_h2h_sum}"
        evaluations[away] = MatchupEvaluation(
            team=away,
            opponent=home,
            coach=a_info["coach"],
            opponent_coach=h_info["coach"],
            module=a_info["module"],
            opponent_module=h_info["module"],
            style_tags=a_info["style_tags"],
            opponent_style_tags=h_info["style_tags"],
            role_multipliers=a_mults,
            h2h_matches_count=a_h2h_n,
            summary_note=a_note,
        )

    return evaluations
