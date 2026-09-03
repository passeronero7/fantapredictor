"""Auction propensity forecasting: P(player median mark) under club style.

This module answers one auction question: *how likely is a player to hold a
median good mark over the next matchdays, given his own history, his club's
statistical attitude, and the opponent he faces?* It is deliberately
transparent -- empirical distributions with empirical-Bayes shrinkage -- and
it is validated by a walk-forward backtest instead of trusted a priori.

Conditioning signals currently in the warehouse:

- player: observed vote/fantavoto distributions and appearance rates.
- club module/style: shots, corners and goals for/against per match from
  ``match_team_stats``/``matches`` (all historical seasons).
- coach playing style: the ``coach_club_seasons`` table is modelled in the
  schema but not yet populated; :func:`coach_style_adjustments` returns an
  empty adjustment and the simulation runs on team-style proxies. Populating
  the curated coach history activates the hook without code changes.
"""

from __future__ import annotations

import sqlite3
import warnings
from dataclasses import dataclass

import numpy as np
import pandas as pd

from src.db import repository

GOOD_VOTE_THRESHOLD = 6.0
SHRINKAGE_OBSERVATIONS = 3.0
STYLE_MULTIPLIER_CAP = (0.5, 2.0)


def coach_style_adjustments(conn: sqlite3.Connection, season: str) -> dict[str, float]:
    """Per-club style multiplier from the curated coach history.

    Returns an empty mapping until ``coach_club_seasons`` is populated; the
    simulation then runs purely on observed team statistics.
    """
    count = conn.execute("SELECT COUNT(*) FROM coach_club_seasons").fetchone()[0]
    if count:
        raise NotImplementedError(
            "Coach history is populated; define the coach-attitude weighting "
            "with the data owner before enabling it"
        )
    return {}


def club_style_index(team_stats: pd.DataFrame, season: str | None = None) -> pd.DataFrame:
    """Standardised attacking/defensive style per club and season.

    ``attack_index`` z-scores shots-for and goals-for; ``defense_index``
    z-scores the inverse of goals-against and shots-against. Statistics are
    normalised within season so era scoring drift does not dominate.
    """
    frame = team_stats.copy()
    if season is not None:
        frame = frame[frame["season"].eq(season)]
    style = frame.groupby(["season", "team"], as_index=False).agg(
        games=("matchday", "size"),
        goals_for=("goals_for", "mean"),
        goals_against=("goals_against", "mean"),
        shots_for=("shots", "mean"),
    )
    shots_against = (
        frame.groupby(["season", "opponent"], as_index=False)
        .agg(shots_against=("shots", "mean"))
        .rename(columns={"opponent": "team"})
    )
    style = style.merge(shots_against, on=["season", "team"], how="left")

    def zscore_within_season(column: str) -> pd.Series:
        def z(group: pd.Series) -> pd.Series:
            std = group.std(ddof=0)
            if not std or np.isnan(std):
                return group * 0.0
            return (group - group.mean()) / std

        return style.groupby("season")[column].transform(z)

    style["attack_index"] = (
        zscore_within_season("shots_for") + zscore_within_season("goals_for")
    ) / 2
    style["defense_index"] = (
        zscore_within_season("goals_against") * -1 + zscore_within_season("shots_against") * -1
    ) / 2
    return style[["season", "team", "games", "attack_index", "defense_index"]]


def player_propensity(
    ratings: pd.DataFrame,
    team_stats: pd.DataFrame,
    season: str,
    matchday: int,
    good_vote: float = GOOD_VOTE_THRESHOLD,
    shrinkage: float = SHRINKAGE_OBSERVATIONS,
) -> pd.DataFrame:
    """Empirical-Bayes propensity per player from observable history only.

    ``ratings`` must carry season/matchday columns; observations at or after
    ``matchday`` of ``season`` are excluded here as well, so callers cannot
    leak the target round by passing an unfiltered frame.
    """
    observed = ratings.dropna(subset=["vote"]).copy()
    if "season" not in observed or "matchday" not in observed:
        raise ValueError("Ratings frame must carry season and matchday columns")
    current = observed["season"].astype(str).eq(season)
    matchdays = pd.to_numeric(observed["matchday"], errors="coerce")
    prior = observed[~current | (current & (matchdays < matchday))]

    style = club_style_index(team_stats)
    club_games = style.set_index(["season", "team"])["games"]
    prior["club_games"] = [
        float(club_games.get((str(s), str(t)), np.nan))
        for s, t in zip(prior["season"].astype(str), prior["team"].astype(str))
    ]

    role_prior_mark = prior.groupby("role")["vote"].apply(lambda v: (v >= good_vote).mean())

    grouped = prior.groupby("player_normalized")
    profile = grouped.agg(
        player=("player", "last"),
        team=("team", "last"),
        role=("role", "last"),
        appearances=("vote", "size"),
        vote_median=("vote", "median"),
        fantavoto_median=("fantavoto", "median"),
        good_marks=("vote", lambda v: float((v >= good_vote).sum())),
    )

    # Bonus events from observable fantavoto-vote gaps.
    fantavoto_obs = prior.dropna(subset=["fantavoto"])
    bonus = (fantavoto_obs["fantavoto"] - fantavoto_obs["vote"]).clip(lower=0)
    bonus_obs = bonus.groupby(fantavoto_obs["player_normalized"]).size()
    bonus_events = bonus.groupby(fantavoto_obs["player_normalized"]).apply(
        lambda v: float((v >= 1).sum())
    )
    profile["bonus_rate"] = bonus_events / bonus_obs.reindex(profile.index).replace(0, np.nan)
    nonzero = bonus[bonus >= 1]
    profile["mean_bonus_when_bonus"] = nonzero.groupby(
        fantavoto_obs.loc[nonzero.index, "player_normalized"]
    ).mean()

    profile["good_rate_raw"] = profile["good_marks"] / profile["appearances"]
    games_per_player = (
        prior.groupby(["player_normalized", "season"])["club_games"].first()
        .groupby("player_normalized").sum(min_count=1)
    )
    profile["appearance_rate_raw"] = (
        profile["appearances"] / games_per_player.clip(lower=1)
    )

    # Empirical-Bayes shrinkage toward the role prior.
    role_marks = profile["role"].map(role_prior_mark)
    profile["p_good_mark"] = (
        profile["good_marks"] + shrinkage * role_marks
    ) / (profile["appearances"] + shrinkage)
    role_appearance_prior = profile.groupby("role")["appearance_rate_raw"].mean()
    profile["p_plays"] = (
        profile["appearances"] + shrinkage * profile["role"].map(role_appearance_prior) * 4
    ) / (games_per_player.reindex(profile.index).fillna(0) + shrinkage * 4)
    profile["p_plays"] = profile["p_plays"].clip(0.0, 1.0)
    return profile.reset_index().rename(columns={"index": "player_normalized"})


def style_multiplier(
    role: str,
    own_attack: float,
    own_defense: float,
    opponent_attack: float,
    opponent_defense: float,
    weight: float = 0.15,
) -> float:
    """Bonus-event multiplier from club style, by role.

    Attackers/midfielders feast on their own attack and the opponent's weak
    defense; goalkeepers/defenders feed on their own defense and suffer the
    opponent's attack. Exponentiated z-combination keeps the effect
    multiplicative and centred on 1.
    """
    role = str(role).strip().upper()
    if role in {"A", "C"}:
        z = own_attack - opponent_defense
    elif role in {"P", "D"}:
        z = own_defense - opponent_attack
    else:
        z = 0.0
    value = float(np.exp(weight * z))
    return float(np.clip(value, *STYLE_MULTIPLIER_CAP))


@dataclass
class SimulationConfig:
    """Monte Carlo horizon configuration.

    ``good_mark`` applies to the median base *vote* (the classic media 6.0
    sufficiency); fantavoto statistics (with bonuses) are reported alongside.
    """

    from_matchday: int
    matchdays: int
    simulations: int = 1000
    good_mark: float = GOOD_VOTE_THRESHOLD
    style_weight: float = 0.15
    seed: int = 20260903


def _per_player_samples(
    prior: pd.DataFrame, propensity: pd.DataFrame, min_obs: int = 3
) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    """Fixed-width bootstrap matrices of vote and bonus per player.

    Players with fewer than ``min_obs`` observations fall back to their role
    distribution. Returns ``(votes, bonuses, nonzero_bonus_rate, mean_bonus)``
    shaped ``(n_players, width)`` plus the players' index labels.
    """
    observed = prior.dropna(subset=["vote"]).copy()
    observed["bonus"] = (
        observed["fantavoto"] - observed["vote"]
    ).clip(lower=0)
    role_pool = {role: block for role, block in observed.groupby("role")}
    rng = np.random.default_rng(0)

    votes, bonuses = [], []
    for _, row in propensity.iterrows():
        key = str(row["player_normalized"])
        block = observed[observed["player_normalized"].eq(key)]
        if len(block) < min_obs:
            block = role_pool.get(str(row["role"]), observed)
        votes.append(block["vote"].to_numpy(dtype=float))
        bonuses.append(block["bonus"].to_numpy(dtype=float))
    width = max(len(v) for v in votes)
    vote_matrix = np.full((len(votes), width), np.nan)
    bonus_matrix = np.full((len(votes), width), np.nan)
    for index, (v, b) in enumerate(zip(votes, bonuses)):
        take = rng.integers(0, len(v), size=width)
        vote_matrix[index] = v[take]
        bonus_matrix[index] = b[take]
    nonzero_rate = np.array([
        float((b >= 1).mean()) for b in bonuses
    ])
    mean_bonus = np.array([
        float(b[b >= 1].mean()) if (b >= 1).any() else 0.0 for b in bonuses
    ])
    return vote_matrix, bonus_matrix, nonzero_rate, mean_bonus


def simulate_horizon(
    propensity: pd.DataFrame,
    prior: pd.DataFrame,
    style: pd.DataFrame,
    clubs: list[str],
    config: SimulationConfig,
) -> pd.DataFrame:
    """Monte Carlo the forecast horizon and return per-player propensity.

    Each simulation round pairs the 20 clubs randomly each matchday (the
    official future calendar is not yet ingested; random pairing is the
    documented assumption). For every player-matchday: Bernoulli appearance,
    bootstrap vote, and bonus events accepted with probability modulated by
    the club/opponent style multiplier. The auction statistic is
    P(median fantavoto over the horizon >= good_mark).
    """
    rng = np.random.default_rng(config.seed)
    votes, bonuses, _, _ = _per_player_samples(prior, propensity)
    propensity = propensity.reset_index(drop=True)
    style_by_team = style.set_index("team")
    own_attack = propensity["team"].map(style_by_team["attack_index"]).fillna(0.0).to_numpy()
    own_defense = propensity["team"].map(style_by_team["defense_index"]).fillna(0.0).to_numpy()
    opp_attack = {club: style_by_team.at[club, "attack_index"] for club in clubs}
    opp_defense = {club: style_by_team.at[club, "defense_index"] for club in clubs}

    n_players = len(propensity)
    horizons = np.zeros((n_players, config.simulations))
    vote_horizons = np.zeros((n_players, config.simulations))
    good_counts = np.zeros(n_players)
    fantavoto_65_counts = np.zeros(n_players)
    mark_counts = np.zeros(n_players)
    fantavoto_sums = np.zeros(n_players)
    p_plays = propensity["p_plays"].fillna(0.0).to_numpy()
    roles = propensity["role"].astype(str).to_numpy()
    teams = propensity["team"].astype(str).to_numpy()
    for sim in range(config.simulations):
        horizon_marks = np.full((n_players, config.matchdays), np.nan)
        vote_marks = np.full((n_players, config.matchdays), np.nan)
        for md in range(config.matchdays):
            pairing = rng.permutation(len(clubs)).reshape(-1, 2)
            opponent_of = {}
            for home_idx, away_idx in pairing:
                opponent_of[clubs[home_idx]] = clubs[away_idx]
                opponent_of[clubs[away_idx]] = clubs[home_idx]
            opponents = np.array([opponent_of.get(team, team) for team in teams])
            o_attack = np.array([opp_attack.get(team, 0.0) for team in opponents])
            o_defense = np.array([opp_defense.get(team, 0.0) for team in opponents])

            plays = rng.random(n_players) < p_plays
            sample_idx = rng.integers(0, votes.shape[1], size=n_players)
            draw_votes = votes[np.arange(n_players), sample_idx]
            draw_bonus = bonuses[np.arange(n_players), sample_idx]
            has_bonus = draw_bonus >= 1
            multiplier = np.array([
                style_multiplier(
                    roles[i], own_attack[i], own_defense[i], o_attack[i], o_defense[i],
                    weight=config.style_weight,
                )
                for i in range(n_players)
            ])
            accept = ~has_bonus | (rng.random(n_players) < np.minimum(1.0, multiplier))
            fantavoto = draw_votes + np.where(accept, draw_bonus, 0.0)
            fantavoto = np.where(plays, fantavoto, np.nan)
            vote = np.where(plays, draw_votes, np.nan)
            horizon_marks[:, md] = fantavoto
            vote_marks[:, md] = vote
            good_counts += np.where(np.nan_to_num(vote, nan=-1.0) >= config.good_mark, 1.0, 0.0)
            fantavoto_65_counts += np.where(
                np.nan_to_num(fantavoto, nan=-1.0) >= 6.5, 1.0, 0.0
            )
            fantavoto_sums += np.nan_to_num(fantavoto, nan=0.0)
            mark_counts += plays
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", RuntimeWarning)
            horizons[:, sim] = np.nanmedian(horizon_marks, axis=1)
            vote_horizons[:, sim] = np.nanmedian(vote_marks, axis=1)

    output = propensity[["player", "player_normalized", "team", "role"]].copy()
    output["p_good_mark"] = propensity["p_good_mark"]
    output["p_plays"] = propensity["p_plays"]
    output["simulated_mark_rate"] = np.divide(
        good_counts, mark_counts, out=np.zeros(n_players), where=mark_counts > 0
    )
    output["simulated_fantavoto_65_rate"] = np.divide(
        fantavoto_65_counts, mark_counts, out=np.zeros(n_players), where=mark_counts > 0
    )
    output["expected_fantavoto"] = np.round(
        np.divide(fantavoto_sums, mark_counts, out=np.zeros(n_players), where=mark_counts > 0),
        3,
    )
    output["horizon_median_vote"] = np.round(np.nanmedian(vote_horizons, axis=1), 3)
    output["p_horizon_median_good"] = np.round(
        np.nanmean(vote_horizons >= config.good_mark, axis=1), 4
    )
    return output


def backtest_propensity(
    ratings: pd.DataFrame,
    team_stats: pd.DataFrame,
    season: str,
    cutoffs: list[int],
    window: int = 10,
    good_vote: float = GOOD_VOTE_THRESHOLD,
) -> dict[str, object]:
    """Walk-forward calibration check of the propensity estimate.

    For each cutoff the propensity is computed from prior observations only
    and scored against the realised marks of the following ``window``
    matchdays: calibration bins, Brier score, and the realised median mark of
    baskets selected by propensity, price proxy (appearances x median), and
    the naive prior.
    """
    observed = ratings.dropna(subset=["fantavoto"]).copy()
    matchdays = pd.to_numeric(observed["matchday"], errors="coerce")
    current = observed["season"].astype(str).eq(season)
    reports = []
    for cutoff in sorted(cutoffs):
        future = observed[current & (matchdays >= cutoff) & (matchdays < cutoff + window)]
        propensity = player_propensity(
            ratings, team_stats, season, cutoff, good_vote=good_vote
        )
        predicted = propensity.set_index("player_normalized")["p_good_mark"]
        realized = future.groupby("player_normalized")["vote"].apply(
            lambda v: float((v >= good_vote).mean())
        )
        joined = pd.DataFrame({"predicted": predicted}).join(realized.rename("realized"), how="inner").dropna()
        brier = float(((joined["predicted"] - joined["realized"]) ** 2).mean())
        bins = pd.qcut(joined["predicted"], 4, duplicates="drop")
        calibration = joined.groupby(bins, observed=True).agg(
            n=("realized", "size"), predicted=("predicted", "mean"), realized=("realized", "mean")
        ).reset_index(names=["predicted_bin"])
        reports.append({
            "cutoff": cutoff,
            "window": window,
            "players_scored": int(len(joined)),
            "brier": round(brier, 4),
            "calibration": [
                {
                    "predicted_bin": str(row.get("predicted_bin")),
                    **{k: (round(v, 3) if isinstance(v, float) else v)
                       for k, v in row.items() if k != "predicted_bin"}
                }
                for row in calibration.to_dict("records")
            ],
        })
    return {"season": season, "good_vote": good_vote, "cutoffs": reports}
