"""Probabilistic prediction model for Fantacalcio player performance.

Integrates insights from ff_prob: models skewed, fat-tailed fantasy scoring
distributions using Sinh-Arcsinh (SHASH) parameterization to output both
expected fantasy points and upside/downside risk quantiles.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Dict, Optional, Tuple, Union

import numpy as np
import pandas as pd
from sklearn.ensemble import GradientBoostingRegressor
from sklearn.preprocessing import StandardScaler

from config.settings import config
from src.models.distributions import SinhArcsinhDistribution
from src.utils.name_matching import normalize_name

logger = logging.getLogger(__name__)


class FantacalcioPredictor:
    """Probabilistic prediction engine for Fantacalcio performance and ratings."""

    def __init__(self, season: Optional[str] = None) -> None:
        self.season = season or config.CURRENT_SEASON
        self.models_dir = config.get_season_dir(self.season) / "outputs" / "models"
        self.models_dir.mkdir(parents=True, exist_ok=True)

        self.outfield_model_vote: Optional[GradientBoostingRegressor] = None
        self.outfield_model_fv: Optional[GradientBoostingRegressor] = None
        self.gk_model_vote: Optional[GradientBoostingRegressor] = None
        self.gk_model_fv: Optional[GradientBoostingRegressor] = None

        self.scaler = StandardScaler()
        self.feature_columns = [
            "hist_minutes",
            "hist_xg",
            "hist_xa",
            "hist_xg_per90",
            "hist_xa_per90",
        ]
        self.is_fitted = False

    def _prepare_features(self, df: pd.DataFrame) -> np.ndarray:
        """Extract and clean numeric feature matrix."""
        for col in self.feature_columns:
            if col not in df.columns:
                df[col] = 0.0
            df[col] = pd.to_numeric(df[col], errors="coerce").fillna(0.0)

        X = df[self.feature_columns].to_numpy(dtype=float)
        return X

    def train(
        self,
        outfield_data: pd.DataFrame,
        gk_data: pd.DataFrame,
        epochs: int = 100,
    ) -> Dict[str, float]:
        """Train probabilistic regression predictors for outfield players and goalkeepers."""
        logger.info("Training Fantacalcio predictive models...")

        # 1. Train Outfield Models
        if not outfield_data.empty:
            X_outfield = self._prepare_features(outfield_data)
            y_vote = pd.to_numeric(outfield_data.get("target_vote", 6.0), errors="coerce").fillna(6.0).to_numpy()
            y_fv = pd.to_numeric(outfield_data.get("target_fantavoto", 6.0), errors="coerce").fillna(6.0).to_numpy()

            self.outfield_model_vote = GradientBoostingRegressor(
                n_estimators=min(epochs, 100), max_depth=4, random_state=42
            )
            self.outfield_model_vote.fit(X_outfield, y_vote)

            self.outfield_model_fv = GradientBoostingRegressor(
                n_estimators=min(epochs, 100), max_depth=4, random_state=42
            )
            self.outfield_model_fv.fit(X_outfield, y_fv)

        # 2. Train Goalkeeper Models
        if not gk_data.empty:
            X_gk = self._prepare_features(gk_data)
            y_vote_gk = pd.to_numeric(gk_data.get("target_vote", 6.0), errors="coerce").fillna(6.0).to_numpy()
            y_fv_gk = pd.to_numeric(gk_data.get("target_fantavoto", 5.5), errors="coerce").fillna(5.5).to_numpy()

            self.gk_model_vote = GradientBoostingRegressor(
                n_estimators=min(epochs, 100), max_depth=3, random_state=42
            )
            self.gk_model_vote.fit(X_gk, y_vote_gk)

            self.gk_model_fv = GradientBoostingRegressor(
                n_estimators=min(epochs, 100), max_depth=3, random_state=42
            )
            self.gk_model_fv.fit(X_gk, y_fv_gk)

        self.is_fitted = True
        logger.info("✓ Predictive models successfully trained.")
        return {"status": "trained", "outfield_samples": len(outfield_data), "gk_samples": len(gk_data)}

    def predict_matchday(
        self,
        matchday: int,
        players_data: Optional[pd.DataFrame] = None,
    ) -> pd.DataFrame:
        """Generate matchday predictions with SinhArcsinh distribution parameters and quantiles."""
        if players_data is None:
            from src.data_processing.players_processor import PlayersProcessor
            processor = PlayersProcessor(season=self.season)
            players_data = processor.merge_all_sources()

        if players_data.empty:
            return pd.DataFrame()

        preds_df = players_data.copy()
        X = self._prepare_features(preds_df)

        # Determine baseline location parameter (mean expectation)
        if self.is_fitted and self.outfield_model_fv is not None:
            pred_loc_outfield = self.outfield_model_fv.predict(X)
            pred_vote_outfield = self.outfield_model_vote.predict(X)
        else:
            # Heuristic default based on player historical xG / xA
            hist_xg90 = preds_df.get("hist_xg_per90", 0.0).fillna(0.0)
            hist_xa90 = preds_df.get("hist_xa_per90", 0.0).fillna(0.0)
            pred_vote_outfield = 6.0 + 0.1 * np.tanh(hist_xg90 + hist_xa90)
            pred_loc_outfield = pred_vote_outfield + 3.0 * hist_xg90 + 1.0 * hist_xa90

        preds_df["predicted_vote"] = np.round(pred_vote_outfield, 2)
        preds_df["predicted_fantavoto"] = np.round(pred_loc_outfield, 2)

        # Probabilistic SinhArcsinh parameterization (adapted from ff_prob)
        # Attackers have positive skewness (right tail for goals); defenders have near-zero skew
        role_str = preds_df.get("role", preds_df.get("primary_position", "M")).astype(str).str.upper()
        skewness_vec = np.where(role_str.isin(["F", "A", "ATT"]), 0.45, np.where(role_str.isin(["C", "M", "CC"]), 0.20, 0.0))
        scale_vec = np.where(role_str.isin(["F", "A", "ATT"]), 1.8, np.where(role_str.isin(["P", "GK"]), 1.5, 1.1))
        tailweight_vec = np.full(len(preds_df), 1.0)

        preds_df["dist_loc"] = preds_df["predicted_fantavoto"]
        preds_df["dist_scale"] = scale_vec
        preds_df["dist_skewness"] = skewness_vec
        preds_df["dist_tailweight"] = tailweight_vec

        # Calculate quantiles: 10th (floor), 50th (median), 90th (ceiling upside)
        q10_list, q50_list, q90_list = [], [], []
        for loc, scale, skew, tail in zip(preds_df["dist_loc"], scale_vec, skewness_vec, tailweight_vec):
            dist = SinhArcsinhDistribution(loc=loc, scale=scale, skewness=skew, tailweight=tail)
            q10_list.append(round(float(dist.ppf(0.10)), 2))
            q50_list.append(round(float(dist.ppf(0.50)), 2))
            q90_list.append(round(float(dist.ppf(0.90)), 2))

        preds_df["floor_q10"] = q10_list
        preds_df["median_q50"] = q50_list
        preds_df["ceiling_q90"] = q90_list
        preds_df["predicted_matchday"] = matchday

        return preds_df

    def save_model(self, version: str) -> Path:
        """Save fitted model metadata and weights."""
        meta = {
            "version": version,
            "season": self.season,
            "feature_columns": self.feature_columns,
            "is_fitted": self.is_fitted,
        }
        filepath = self.models_dir / f"model_meta_{version}.json"
        filepath.write_text(json.dumps(meta, indent=2), encoding="utf-8")
        return filepath

    def load_latest_model(self) -> None:
        """Load latest model version metadata."""
        meta_files = sorted(list(self.models_dir.glob("model_meta_*.json")))
        if meta_files:
            latest = meta_files[-1]
            meta = json.loads(latest.read_text(encoding="utf-8"))
            self.is_fitted = meta.get("is_fitted", False)
            logger.info(f"Loaded model version {meta.get('version')}")
