"""Deep probabilistic predictor for Fantacalcio player performance.

The network predicts two four-parameter Sinh-Arcsinh distributions: one for
the base vote and one for the final fantasy score. TensorFlow is used directly
so the model does not depend on the optional TensorFlow Probability package.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Optional

import numpy as np
import pandas as pd
from sklearn.preprocessing import StandardScaler

from config.settings import config
from src.models.distributions import SinhArcsinhDistribution

logger = logging.getLogger(__name__)


class FantacalcioPredictor:
    """Train, persist, and serve a deep distributional fantasy-score model."""

    def __init__(self, season: Optional[str] = None) -> None:
        self.season = season or config.CURRENT_SEASON
        self.models_dir = config.get_season_dir(self.season) / "outputs" / "models"
        self.models_dir.mkdir(parents=True, exist_ok=True)
        self.feature_columns = [
            "hist_minutes",
            "hist_xg",
            "hist_xa",
            "hist_xg_per90",
            "hist_xa_per90",
            "season_appearances",
            "mean_vote",
            "mean_fantavoto",
            "is_home",
        ]
        self.scaler = StandardScaler()
        self.outfield_model = None
        self.goalkeeper_model = None
        self.version: Optional[str] = None
        self.is_fitted = False

    @staticmethod
    def _tf():
        """Import TensorFlow lazily so database and parsing tasks stay lightweight."""
        try:
            import tensorflow as tf
        except ImportError as exc:
            raise RuntimeError("TensorFlow is required to train or serve the deep model") from exc
        return tf

    def _feature_frame(self, data: pd.DataFrame) -> pd.DataFrame:
        """Return a numeric feature frame without mutating caller-owned data."""
        frame = data.copy()
        for column in self.feature_columns:
            if column not in frame.columns:
                frame[column] = 0.0
            frame[column] = pd.to_numeric(frame[column], errors="coerce").fillna(0.0)
        return frame[self.feature_columns]

    def _build_model(self):
        """Build a shared-trunk deep network with vote and fantasy-score heads."""
        tf = self._tf()
        inputs = tf.keras.Input(shape=(len(self.feature_columns),), name="features")
        x = tf.keras.layers.Dense(128, activation="relu")(inputs)
        x = tf.keras.layers.BatchNormalization()(x)
        x = tf.keras.layers.Dropout(0.15)(x)
        x = tf.keras.layers.Dense(64, activation="relu")(x)
        x = tf.keras.layers.Dense(32, activation="relu")(x)
        vote_params = tf.keras.layers.Dense(4, name="vote_distribution")(x)
        fantasy_params = tf.keras.layers.Dense(4, name="fantasy_distribution")(x)
        outputs = tf.keras.layers.Concatenate(name="distribution_parameters")(
            [vote_params, fantasy_params]
        )
        model = tf.keras.Model(inputs=inputs, outputs=outputs)
        model.compile(optimizer=tf.keras.optimizers.Adam(learning_rate=0.001), loss=self._loss)
        return model

    @staticmethod
    def _log_shash_probability(tf, target, params):
        """TensorFlow log-density for the SHASH parameterization."""
        loc, raw_scale, skew, raw_tail = tf.unstack(params, axis=-1)
        loc = tf.clip_by_value(loc, 0.0, 20.0)
        skew = tf.clip_by_value(skew, -0.5, 0.5)
        scale = tf.nn.softplus(tf.clip_by_value(raw_scale, -5.0, 5.0)) + 0.1
        tail = tf.nn.softplus(tf.clip_by_value(raw_tail, -5.0, 5.0)) + 0.75
        z = (target - loc) / scale
        transformed = tf.sinh(tail * tf.asinh(z) - skew)
        radius = tail * tf.asinh(z) - skew
        abs_radius = tf.abs(radius)
        log_cosh = abs_radius + tf.nn.softplus(-2.0 * abs_radius) - tf.math.log(2.0)
        return (
            -0.5 * tf.square(transformed)
            - 0.5 * tf.math.log(2.0 * np.pi)
            + tf.math.log(tail)
            + log_cosh
            - tf.math.log(scale)
            - 0.5 * tf.math.log1p(tf.square(z))
        )

    @classmethod
    def _loss(cls, y_true, y_pred):
        """Negative log likelihood for base vote and fantasy score together."""
        tf = cls._tf()
        vote_log_prob = cls._log_shash_probability(tf, y_true[:, 0], y_pred[:, :4])
        fantasy_log_prob = cls._log_shash_probability(tf, y_true[:, 1], y_pred[:, 4:])
        vote_loc = tf.clip_by_value(y_pred[:, 0], 0.0, 20.0)
        fantasy_loc = tf.clip_by_value(y_pred[:, 4], 0.0, 20.0)
        point_loss = tf.square(y_true[:, 0] - vote_loc) + tf.square(y_true[:, 1] - fantasy_loc)
        return tf.reduce_mean(-(vote_log_prob + fantasy_log_prob) + 0.1 * point_loss)

    @staticmethod
    def _targets(data: pd.DataFrame) -> np.ndarray:
        """Validate and return real observed targets; synthetic targets are forbidden."""
        required = {"target_vote", "target_fantavoto"}
        missing = required - set(data.columns)
        if missing:
            raise ValueError(f"Training data is missing targets: {', '.join(sorted(missing))}")
        targets = data[["target_vote", "target_fantavoto"]].apply(pd.to_numeric, errors="coerce")
        if targets.isna().any().any():
            raise ValueError("Training targets contain missing or non-numeric values")
        if len(targets) < 8:
            raise ValueError("At least 8 observed player-match rows are required for training")
        return targets.to_numpy(dtype=np.float32)

    def train(
        self,
        outfield_data: pd.DataFrame,
        gk_data: pd.DataFrame,
        epochs: int = 100,
        batch_size: int = 32,
    ) -> dict[str, object]:
        """Train separate deep models using observed vote and fantavoto targets."""
        if outfield_data.empty and gk_data.empty:
            raise ValueError("No observed player-match data supplied")
        frames = [frame for frame in (outfield_data, gk_data) if not frame.empty]
        all_features = pd.concat([self._feature_frame(frame) for frame in frames], ignore_index=True)
        self.scaler.fit(all_features)
        tf = self._tf()
        tf.keras.utils.set_random_seed(42)
        histories: dict[str, object] = {}

        if not outfield_data.empty:
            out_targets = self._targets(outfield_data)
            self.outfield_model = self._build_model()
            out_features = self.scaler.transform(self._feature_frame(outfield_data)).astype(np.float32)
            histories["outfield"] = self.outfield_model.fit(
                out_features,
                out_targets,
                epochs=epochs,
                batch_size=min(batch_size, len(out_targets)),
                shuffle=False,
                verbose=0,
            ).history

        if not gk_data.empty:
            gk_targets = self._targets(gk_data)
            self.goalkeeper_model = self._build_model()
            gk_features = self.scaler.transform(self._feature_frame(gk_data)).astype(np.float32)
            histories["goalkeeper"] = self.goalkeeper_model.fit(
                gk_features,
                gk_targets,
                epochs=epochs,
                batch_size=min(batch_size, len(gk_targets)),
                shuffle=False,
                verbose=0,
            ).history

        self.is_fitted = True
        return {
            "status": "trained",
            "model_type": "tensorflow_deep_shash",
            "outfield_samples": len(outfield_data),
            "gk_samples": len(gk_data),
            "histories": histories,
        }

    @staticmethod
    def _decode_params(raw: np.ndarray) -> np.ndarray:
        """Convert unconstrained network outputs to valid distribution parameters."""
        params = raw.astype(float, copy=True)
        for location_column in (0, 4):
            params[:, location_column] = np.clip(params[:, location_column], 0.0, 20.0)
        for scale_column in (1, 5):
            params[:, scale_column] = np.logaddexp(
                0.0, np.clip(params[:, scale_column], -5.0, 5.0)
            ) + 0.1
        for tail_column in (3, 7):
            params[:, tail_column] = np.logaddexp(
                0.0, np.clip(params[:, tail_column], -5.0, 5.0)
            ) + 0.75
        params[:, 2] = np.clip(params[:, 2], -0.5, 0.5)
        params[:, 6] = np.clip(params[:, 6], -0.5, 0.5)
        return params

    def _predict_params(self, data: pd.DataFrame, goalkeeper: bool) -> np.ndarray:
        model = self.goalkeeper_model if goalkeeper else self.outfield_model
        if not self.is_fitted or model is None:
            role = "goalkeeper" if goalkeeper else "outfield"
            raise RuntimeError(f"No fitted {role} model is loaded")
        features = self.scaler.transform(self._feature_frame(data)).astype(np.float32)
        return self._decode_params(model.predict(features, verbose=0))

    def predict_matchday(self, matchday: int, players_data: Optional[pd.DataFrame] = None) -> pd.DataFrame:
        """Predict vote/fantasy-score distributions and q10/q50/q90 per player."""
        if players_data is None:
            from src.data_processing.players_processor import PlayersProcessor
            players_data = PlayersProcessor(season=self.season).merge_all_sources()
        if players_data.empty:
            return pd.DataFrame()

        output = players_data.copy().reset_index(drop=True)
        roles = output.get("role", output.get("primary_position", "M")).astype(str).str.upper()
        is_gk = roles.isin({"P", "GK", "POR", "GOALKEEPER"})
        raw_vote = np.zeros((len(output), 4), dtype=float)
        raw_fantasy = np.zeros((len(output), 4), dtype=float)
        if (~is_gk).any():
            params = self._predict_params(output.loc[~is_gk], goalkeeper=False)
            raw_vote[~is_gk] = params[:, :4]
            raw_fantasy[~is_gk] = params[:, 4:]
        if is_gk.any():
            params = self._predict_params(output.loc[is_gk], goalkeeper=True)
            raw_vote[is_gk] = params[:, :4]
            raw_fantasy[is_gk] = params[:, 4:]

        vote_quantiles = np.array([
            SinhArcsinhDistribution(*params).ppf([0.50])
            for params in raw_vote
        ]).reshape(-1)
        fantasy_quantiles = np.array([
            SinhArcsinhDistribution(*params).ppf([0.10, 0.50, 0.90])
            for params in raw_fantasy
        ])
        output["predicted_vote"] = np.round(np.clip(vote_quantiles, 0.0, 10.0), 2)
        output["predicted_fantavoto"] = np.round(
            np.clip(fantasy_quantiles[:, 1], -5.0, 30.0), 2
        )
        output["vote_dist_loc"] = raw_vote[:, 0]
        output["vote_dist_scale"] = raw_vote[:, 1]
        output["vote_dist_skewness"] = raw_vote[:, 2]
        output["vote_dist_tailweight"] = raw_vote[:, 3]
        output["dist_loc"] = raw_fantasy[:, 0]
        output["dist_scale"] = raw_fantasy[:, 1]
        output["dist_skewness"] = raw_fantasy[:, 2]
        output["dist_tailweight"] = raw_fantasy[:, 3]

        output[["floor_q10", "median_q50", "ceiling_q90"]] = np.round(
            np.clip(fantasy_quantiles, -5.0, 30.0), 2
        )
        output["predicted_matchday"] = matchday
        return output

    def save_model(self, version: str) -> Path:
        """Persist models, scaler parameters, and metadata in a reproducible bundle."""
        if not self.is_fitted:
            raise RuntimeError("Cannot save an unfitted model")
        if self.outfield_model is None and self.goalkeeper_model is None:
            raise RuntimeError("No fitted model exists")
        artifacts = {}
        if self.outfield_model is not None:
            path = self.models_dir / f"model_{version}_outfield.keras"
            self.outfield_model.save(path)
            artifacts["outfield"] = path.name
        if self.goalkeeper_model is not None:
            path = self.models_dir / f"model_{version}_goalkeeper.keras"
            self.goalkeeper_model.save(path)
            artifacts["goalkeeper"] = path.name
        metadata = {
            "version": version,
            "season": self.season,
            "model_type": "tensorflow_deep_shash",
            "feature_columns": self.feature_columns,
            "scaler_mean": self.scaler.mean_.tolist(),
            "scaler_scale": self.scaler.scale_.tolist(),
            "artifacts": artifacts,
        }
        metadata_path = self.models_dir / f"model_meta_{version}.json"
        metadata_path.write_text(json.dumps(metadata, indent=2), encoding="utf-8")
        self.version = version
        return metadata_path

    def load_latest_model(self) -> None:
        """Restore the newest complete model bundle, including scaler state."""
        metadata_files = sorted(self.models_dir.glob("model_meta_*.json"))
        if not metadata_files:
            raise FileNotFoundError(f"No model metadata found in {self.models_dir}")
        metadata_path = metadata_files[-1]
        metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
        tf = self._tf()
        artifacts = metadata.get("artifacts", {})
        if not artifacts:
            raise ValueError(f"Model metadata has no serialized artifacts: {metadata_path}")
        self.outfield_model = (
            tf.keras.models.load_model(self.models_dir / artifacts["outfield"], compile=False)
            if "outfield" in artifacts else None
        )
        self.goalkeeper_model = (
            tf.keras.models.load_model(self.models_dir / artifacts["goalkeeper"], compile=False)
            if "goalkeeper" in artifacts else None
        )
        self.feature_columns = metadata["feature_columns"]
        self.scaler.mean_ = np.asarray(metadata["scaler_mean"], dtype=float)
        self.scaler.scale_ = np.asarray(metadata["scaler_scale"], dtype=float)
        self.scaler.var_ = self.scaler.scale_ ** 2
        self.scaler.n_features_in_ = len(self.feature_columns)
        self.scaler.feature_names_in_ = np.asarray(self.feature_columns, dtype=object)
        self.version = metadata["version"]
        self.is_fitted = True
