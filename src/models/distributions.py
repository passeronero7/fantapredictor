"""Probabilistic distribution utilities for sports fantasy performance modeling.

Implements the 4-parameter Sinh-Arcsinh (SHASH) distribution (Jones & Pewsey, 2009)
which parameterizes location, scale, skewness, and tailweight. This distribution
is exceptionally suited for modeling sports fantasy scores that exhibit asymmetry
(explosive scoring potential for attackers) and heavy-tailed extreme outcomes.
"""

from __future__ import annotations

import math
from typing import Optional, Tuple, Union

import numpy as np
from scipy import optimize, stats


class SinhArcsinhDistribution:
    """Four-parameter Sinh-Arcsinh (SHASH) distribution.

    Let Z ~ Normal(0, 1). The random variable Y ~ SHASH(loc, scale, skewness, tailweight)
    is defined by:
        Y = loc + scale * sinh((asinh(Z) + skewness) / tailweight)
    or conversely:
        Z = sinh(tailweight * asinh((Y - loc) / scale) - skewness)
    """

    def __init__(
        self,
        loc: float = 0.0,
        scale: float = 1.0,
        skewness: float = 0.0,
        tailweight: float = 1.0,
    ) -> None:
        if scale <= 0:
            raise ValueError(f"scale must be strictly positive, got {scale}")
        if tailweight <= 0:
            raise ValueError(f"tailweight must be strictly positive, got {tailweight}")

        self.loc = float(loc)
        self.scale = float(scale)
        self.skewness = float(skewness)
        self.tailweight = float(tailweight)

    def pdf(self, x: Union[float, np.ndarray]) -> Union[float, np.ndarray]:
        """Probability density function."""
        x_arr = np.asarray(x, dtype=float)
        z_trans = (x_arr - self.loc) / self.scale
        # r = tailweight * asinh(z_trans) - skewness
        r = self.tailweight * np.arcsinh(z_trans) - self.skewness
        cosh_r = np.cosh(r)
        # derivative dz/dx = tailweight * cosh(r) / (scale * sqrt(1 + z_trans^2))
        deriv = self.tailweight * cosh_r / (self.scale * np.sqrt(1.0 + z_trans**2))
        # standard normal pdf of sinh(r)
        sinh_r = np.sinh(r)
        norm_pdf = np.exp(-0.5 * sinh_r**2) / math.sqrt(2.0 * math.pi)
        res = norm_pdf * deriv
        return float(res) if np.isscalar(x) else res

    def logpdf(self, x: Union[float, np.ndarray]) -> Union[float, np.ndarray]:
        """Logarithm of the probability density function."""
        pdf_val = self.pdf(x)
        with np.errstate(divide="ignore", invalid="ignore"):
            res = np.log(np.maximum(pdf_val, 1e-300))
        return float(res) if np.isscalar(x) else res

    def cdf(self, x: Union[float, np.ndarray]) -> Union[float, np.ndarray]:
        """Cumulative distribution function."""
        x_arr = np.asarray(x, dtype=float)
        z_trans = (x_arr - self.loc) / self.scale
        r = self.tailweight * np.arcsinh(z_trans) - self.skewness
        z_std = np.sinh(r)
        res = stats.norm.cdf(z_std)
        return float(res) if np.isscalar(x) else res

    def ppf(self, q: Union[float, np.ndarray]) -> Union[float, np.ndarray]:
        """Percent point function (inverse CDF / quantile function)."""
        q_arr = np.asarray(q, dtype=float)
        if np.any((q_arr < 0.0) | (q_arr > 1.0)):
            raise ValueError("Quantiles must be between 0 and 1")
        z_std = stats.norm.ppf(q_arr)
        # r = asinh(z_std)
        r = np.arcsinh(z_std)
        # transform back: y = loc + scale * sinh((r + skewness) / tailweight)
        y = self.loc + self.scale * np.sinh((r + self.skewness) / self.tailweight)
        return float(y) if np.isscalar(q) else y

    def rvs(self, size: int = 1, random_state: Optional[int] = None) -> np.ndarray:
        """Draw random samples from the distribution."""
        rng = np.random.default_rng(random_state)
        z = rng.standard_normal(size=size)
        r = np.arcsinh(z)
        return self.loc + self.scale * np.sinh((r + self.skewness) / self.tailweight)

    @classmethod
    def fit(cls, data: np.ndarray) -> SinhArcsinhDistribution:
        """Fit distribution parameters to data using Maximum Likelihood Estimation (MLE)."""
        clean_data = np.asarray(data, dtype=float)
        clean_data = clean_data[np.isfinite(clean_data)]
        if len(clean_data) < 4:
            raise ValueError("At least 4 data points required to fit SinhArcsinh distribution")

        init_loc = float(np.median(clean_data))
        init_scale = float(stats.iqr(clean_data) / 1.349) if stats.iqr(clean_data) > 0 else float(np.std(clean_data))
        if init_scale <= 0:
            init_scale = 1.0
        init_skew = 0.0
        init_tail = 1.0

        def neg_log_lik(params: Tuple[float, float, float, float]) -> float:
            loc, scale, skewness, tailweight = params
            if scale <= 1e-4 or tailweight <= 1e-4:
                return 1e10
            dist = cls(loc=loc, scale=scale, skewness=skewness, tailweight=tailweight)
            ll = np.sum(dist.logpdf(clean_data))
            if not np.isfinite(ll):
                return 1e10
            return -ll

        res = optimize.minimize(
            neg_log_lik,
            x0=[init_loc, init_scale, init_skew, init_tail],
            bounds=[
                (None, None),
                (1e-3, None),
                (-5.0, 5.0),
                (0.1, 5.0),
            ],
            method="L-BFGS-B",
        )

        loc, scale, skewness, tailweight = res.x
        return cls(loc=loc, scale=scale, skewness=skewness, tailweight=tailweight)
