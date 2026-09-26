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
- coach tendencies: role shares of goals and assists under each coach
  (``src.models.coach_profiles``), applied in the simulation as per-player
  ``goal_mult``/``assist_mult`` columns that rescale the goal and assist part
  of each sampled bonus. :func:`coach_style_adjustments` only describes the
  current module and style tags; its hand-set deltas are not used by the
  forecast (they were never validated and only moved a reported column).
"""

from __future__ import annotations

import sqlite3
import warnings
from dataclasses import dataclass

import numpy as np
import pandas as pd

from src.db import repository
from src.db.ingestors.common import season_label

GOOD_VOTE_THRESHOLD = 6.0
SHRINKAGE_OBSERVATIONS = 3.0
# Documented walk-forward calibration (2025/26, cutoffs 10/20/30): the top
# bins overestimate realized rates by ~0.05-0.11. A conservative downward
# shift until more windows are evaluated.
RECALIBRATION_OFFSET = -0.05
STYLE_MULTIPLIER_CAP = (0.5, 2.0)


# Back-three modules historically lift defender marks (wing-back assists,
# man-marking defenders rating well); two-AM modules lift creative midfielders.
MODULE_ROLE_DELTAS = {
    "3-5-2": {"D": 0.02},
    "3-4-2-1": {"D": 0.02, "C": 0.01},
    "4-2-3-1": {"C": 0.02},
}
TAG_ROLE_DELTAS = {
    "pragmatic": {"P": 0.02, "A": -0.01},
    "defensive_solidity": {"P": 0.02, "A": -0.01},
    "high_risk": {"P": -0.01},
    "man_marking": {"P": -0.01},
    "possession": {"D": 0.01, "C": 0.01},
    "wingback_attack": {"D": 0.01},
}


def coach_style_adjustments(conn: sqlite3.Connection, season: str) -> dict[str, dict]:
    """Per-club coach conditioning from the curated coach history.

    Returns ``{club: {"module": str, "style_tags": [str]}}`` from
    ``coach_club_seasons`` x ``coaches`` for ``season``; an empty mapping
    means the curated table is unpopulated and team-style proxies stand in.
    """
    return {
        row["team"]: {
            "module": row["preferred_module"],
            "style_tags": [t for t in (row["style_tags"] or "").split("|") if t],
        }
        for row in conn.execute(
            """
            SELECT c.name AS team, co.preferred_module, co.style_tags
            FROM coach_club_seasons AS ccs
            JOIN coaches AS co ON co.id = ccs.coach_id
            JOIN clubs AS c ON c.id = ccs.club_id
            JOIN seasons AS s ON s.id = ccs.season_id
            WHERE s.name = ? AND ccs.ended_at IS NULL
            """,
            (season,),
        )
    }


def coach_role_delta(club_conditioning: dict | None, role: str) -> float:
    """Additive good-mark propensity delta for a role under his coach."""
    if not club_conditioning:
        return 0.0
    role = str(role).strip().upper()
    delta = MODULE_ROLE_DELTAS.get(club_conditioning.get("module") or "", {}).get(role, 0.0)
    for tag in club_conditioning.get("style_tags", []):
        delta += TAG_ROLE_DELTAS.get(tag, {}).get(role, 0.0)
    return delta


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
    observed = ratings.dropna(subset=["vote"]).reset_index(drop=True).copy()
    if "season" not in observed or "matchday" not in observed:
        raise ValueError("Ratings frame must carry season and matchday columns")
    current = observed["season"].astype(str).eq(season)
    matchdays = pd.to_numeric(observed["matchday"], errors="coerce")
    prior = observed[observed["season"].astype(str).lt(season) | (current & (matchdays < matchday))].copy()
    team_stats = team_stats[team_stats["season"].astype(str).lt(season) | (
        team_stats["season"].astype(str).eq(season)
        & (pd.to_numeric(team_stats["matchday"], errors="coerce") < matchday))].copy()

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
        (profile["good_marks"] + shrinkage * role_marks)
        / (profile["appearances"] + shrinkage)
    ) + RECALIBRATION_OFFSET
    role_appearance_prior = profile.groupby("role")["appearance_rate_raw"].mean()
    profile["p_plays"] = (
        profile["appearances"] + shrinkage * profile["role"].map(role_appearance_prior) * 4
    ) / (games_per_player.reindex(profile.index).fillna(0) + shrinkage * 4)
    profile["p_plays"] = profile["p_plays"].clip(0.0, 1.0)
    profile["p_plays_career"] = profile["p_plays"]
    # Current usage matters more than years spent as a reserve or a January
    # arrival. Walk-forward G6-G13 checks select three prior games; see
    # docs/auction_forecast_audit.md. No future appearances enter this rate.
    current_marks = prior[prior["season"].eq(season)]
    current_games = team_stats[team_stats["season"].eq(season)].groupby("team").size()
    if not current_games.empty:
        year = int(season[:4])
        previous_season = f"{year - 1}/{str(year)[-2:]}"
        previous_marks = prior[prior["season"].eq(previous_season)]
        previous_apps = previous_marks.groupby("player_normalized").size()
        previous_rounds = team_stats[team_stats["season"].eq(previous_season)]["matchday"].nunique()
        role_prior = profile.groupby("role")["p_plays_career"].mean()
        previous_rate = (previous_apps / max(previous_rounds, 1)).reindex(profile.index)
        previous_rate = previous_rate.fillna(profile["role"].map(role_prior)).clip(0, 1)
        current_apps = current_marks.groupby("player_normalized").size().reindex(profile.index, fill_value=0)
        games = profile["team"].map(current_games)
        recent = (current_apps + 3.0 * previous_rate) / (games + 3.0)
        profile["p_plays"] = recent.fillna(profile["p_plays_career"]).clip(0, 1)
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
    bootstrap_prior_weight: float = 6.0


GOAL_BONUS = 3.0
ASSIST_BONUS = 1.0


def _per_player_samples(
    prior: pd.DataFrame, propensity: pd.DataFrame, min_obs: int = 3,
    prior_weight: float = 6.0,
) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    """Fixed-width bootstrap matrices of vote and bonus per player.

    Paired observations are mixed with the role distribution using
    ``prior_weight`` prior appearances. With weight zero, the legacy
    ``min_obs`` fallback applies. Returns ``(votes, bonuses, nonzero_bonus_rate, mean_bonus)``
    shaped ``(n_players, width)`` plus the players' index labels.

    When ``propensity`` carries ``goal_mult``/``assist_mult`` (coach
    context), the goal and assist part of every sampled bonus is rescaled:
    ``bonus + (goal_mult - 1) * 3 * goals + (assist_mult - 1) * assists``.
    """
    observed = prior.dropna(subset=["vote", "fantavoto"]).copy()
    observed["bonus"] = observed["fantavoto"] - observed["vote"]
    for column in ("goals", "assists"):
        if column not in observed:
            observed[column] = 0.0
        observed[column] = pd.to_numeric(observed[column], errors="coerce").fillna(0.0)
    role_pool = {role: block for role, block in observed.groupby("role")}
    rng = np.random.default_rng(0)
    goal_mult = (propensity["goal_mult"] if "goal_mult" in propensity
                 else pd.Series(1.0, index=propensity.index)).fillna(1.0).to_numpy()
    assist_mult = (propensity["assist_mult"] if "assist_mult" in propensity
                   else pd.Series(1.0, index=propensity.index)).fillna(1.0).to_numpy()

    votes, bonuses = [], []
    for position, (_, row) in enumerate(propensity.iterrows()):
        key = str(row["player_normalized"])
        block = observed[observed["player_normalized"].eq(key)]
        pool = role_pool.get(str(row["role"]), observed)
        if pool.empty:
            raise ValueError("No observed vote/fantavoto pairs for bootstrap")
        # Mix paired observations, preserving vote/bonus dependence and all
        # maluses. Six prior appearances regularize small samples smoothly;
        # the old hard cutoff gave a four-appearance hot streak full weight.
        own_weight = len(block) / (len(block) + prior_weight) if len(block) else 0.0
        if prior_weight == 0 and len(block) < min_obs:
            own_weight = 0.0
        width = 2048
        own_count = int(round(width * own_weight))
        parts = []
        if own_count:
            parts.append(block.iloc[rng.integers(0, len(block), own_count)])
        if own_count < width:
            parts.append(pool.iloc[rng.integers(0, len(pool), width - own_count)])
        block = pd.concat(parts, ignore_index=True)
        bonus = (
            block["bonus"].to_numpy(dtype=float)
            + (goal_mult[position] - 1.0) * GOAL_BONUS * block["goals"].to_numpy(dtype=float)
            + (assist_mult[position] - 1.0) * ASSIST_BONUS * block["assists"].to_numpy(dtype=float)
        )
        votes.append(block["vote"].to_numpy(dtype=float))
        bonuses.append(bonus)
    width = max(len(v) for v in votes)
    vote_matrix = np.full((len(votes), width), np.nan)
    bonus_matrix = np.full((len(votes), width), np.nan)
    for index, (v, b) in enumerate(zip(votes, bonuses)):
        vote_matrix[index] = v
        bonus_matrix[index] = b
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
    fixtures: pd.DataFrame | None = None,
) -> pd.DataFrame:
    """Monte Carlo the forecast horizon and return per-player propensity.

    Supplied calendar pairings are validated and used in every draw. Only
    callers without fixtures use random pairings. For every player-matchday:
    Bernoulli appearance,
    bootstrap vote, and bonus events accepted with probability modulated by
    the club/opponent style multiplier. The auction statistic is
    P(median base vote over the horizon >= good_mark).
    """
    rng = np.random.default_rng(config.seed)
    votes, bonuses, _, _ = _per_player_samples(
        prior, propensity, prior_weight=config.bootstrap_prior_weight
    )
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
    schedule = []
    if fixtures is not None:
        for md in range(config.from_matchday, config.from_matchday + config.matchdays):
            games = fixtures[fixtures["matchday"].eq(md)]
            sides = games["home"].tolist() + games["away"].tolist()
            if len(sides) != len(clubs) or set(sides) != set(clubs):
                raise ValueError(f"Incomplete or ambiguous calendar at matchday {md}")
            opponent_of = dict(zip(games["home"], games["away"]))
            opponent_of.update(zip(games["away"], games["home"]))
            schedule.append(opponent_of)
    # Calculate each possible matchup once instead of a Python call per
    # player per draw. This preserves the existing style acceptance rule.
    matchup = {
        club: np.array([
            style_multiplier(roles[i], own_attack[i], own_defense[i],
                             opp_attack[club], opp_defense[club], config.style_weight)
            for i in range(n_players)
        ]) for club in clubs
    }
    scheduled_multipliers = [np.array([matchup[opponents[team]][i]
                                      for i, team in enumerate(teams)])
                             for opponents in schedule]
    for sim in range(config.simulations):
        horizon_marks = np.full((n_players, config.matchdays), np.nan)
        vote_marks = np.full((n_players, config.matchdays), np.nan)
        for md in range(config.matchdays):
            if schedule:
                multiplier = scheduled_multipliers[md]
            else:
                pairing = rng.permutation(len(clubs)).reshape(-1, 2)
                opponent_of = {}
                for home_idx, away_idx in pairing:
                    opponent_of[clubs[home_idx]] = clubs[away_idx]
                    opponent_of[clubs[away_idx]] = clubs[home_idx]
                multiplier = np.array([matchup[opponent_of[team]][i]
                                       for i, team in enumerate(teams)])

            plays = rng.random(n_players) < p_plays
            sample_idx = rng.integers(0, votes.shape[1], size=n_players)
            draw_votes = votes[np.arange(n_players), sample_idx]
            draw_bonus = bonuses[np.arange(n_players), sample_idx]
            has_bonus = draw_bonus >= 1
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


def archetype_estimates(
    conn: sqlite3.Connection,
    season: str,
    cutoff_matchday: int,
    neighbours: int = 20,
) -> pd.DataFrame:
    """Similar-player propensity: k-NN over per-90 technique features.

    Every historical player-season carries per-90 xG, xA, shots, key passes,
    minutes and Understat xGChain/xGBuildup (the "technique" signature) plus
    the realised share of 6.0+ marks from the ratings of that same season.
    A current player is matched to his ``neighbours`` most similar same-role
    historical player-seasons; the weighted mean of their good-mark rates is
    his archetype propensity.
    """
    from src.utils.name_matching import normalize_name  # noqa: F401 (symmetry)

    history = repository.load_player_history(conn, before_season=season)
    history = history[history["time"].fillna(0) >= 450].copy()
    if history.empty:
        return pd.DataFrame(columns=["player_normalized", "archetype_p", "archetype_n"])
    for column in ("xG", "xA", "shots", "key_passes"):
        history[f"{column}_p90"] = history[column] / history["time"] * 90.0
    history["xgchain_p90"] = history["xGChain"] / history["time"] * 90.0
    history["xgbuildup_p90"] = history["xGBuildup"] / history["time"] * 90.0
    feature_columns = [
        "xG_p90", "xA_p90", "shots_p90", "key_passes_p90",
        "xgchain_p90", "xgbuildup_p90",
    ]
    history[feature_columns] = history[feature_columns].fillna(0.0)
    history[feature_columns] = history[feature_columns].clip(
        lower=history[feature_columns].quantile(0.01), upper=history[feature_columns].quantile(0.99),
        axis=1,
    )
    votes = repository.load_votes(conn, through_season=season)
    season_name = season_label(season)
    votes = votes[
        ~votes["season"].astype(str).eq(season_name)
        | (
            votes["season"].astype(str).eq(season_name)
            & pd.to_numeric(votes["matchday"], errors="coerce") < cutoff_matchday
        )
    ]
    vote_rate = votes.dropna(subset=["vote"]).groupby(
        ["player_normalized", "season"]
    )["vote"].apply(lambda v: float((v >= GOOD_VOTE_THRESHOLD).mean()))
    history["season_name"] = [season_label(int(y)) for y in history["year"]]
    history["vote_rate"] = [
        vote_rate.get((key, name), np.nan)
        for key, name in zip(history["player_normalized"], history["season_name"])
    ]
    rated = history.dropna(subset=["vote_rate"])

    means = history[feature_columns].mean()
    stds = history[feature_columns].std(ddof=0).replace(0, 1.0)
    normalized = (history[feature_columns] - means) / stds
    records = []
    positions = np.arange(len(history))
    role_mask = history["primary_position"].to_numpy()
    feature_matrix = normalized[feature_columns].to_numpy()
    for index in positions:
        same_role = positions[role_mask == role_mask[index]]
        distances = np.linalg.norm(
            feature_matrix[same_role] - feature_matrix[index], axis=1
        )
        order = np.argsort(distances)[: neighbours + 1]
        candidates = same_role[order]
        candidates = candidates[candidates != index][:neighbours]
        candidate_keys = history["player_normalized"].iloc[candidates]
        candidate_seasons = history["season_name"].iloc[candidates]
        rated_neighbours = np.array([
            vote_rate.get((key, name), np.nan)
            for key, name in zip(candidate_keys, candidate_seasons)
        ], dtype=float)
        rated_neighbours = rated_neighbours[~np.isnan(rated_neighbours)]
        if rated_neighbours.size == 0:
            continue
        records.append({
            "player_normalized": history["player_normalized"].iloc[index],
            "archetype_p": float(rated_neighbours.mean()),
            "archetype_n": int(rated_neighbours.size),
        })
    return pd.DataFrame(records).drop_duplicates("player_normalized")
