import unittest
import numpy as np

from src.models.distributions import SinhArcsinhDistribution


class SinhArcsinhDistributionTests(unittest.TestCase):
    def test_invalid_parameters_raise_value_error(self):
        with self.assertRaises(ValueError):
            SinhArcsinhDistribution(loc=0.0, scale=-1.0)
        with self.assertRaises(ValueError):
            SinhArcsinhDistribution(loc=0.0, scale=1.0, tailweight=0.0)

    def test_pdf_is_positive_and_integrates_to_one(self):
        dist = SinhArcsinhDistribution(loc=6.0, scale=1.2, skewness=0.3, tailweight=1.0)
        x_grid = np.linspace(-5.0, 20.0, 1000)
        pdf_vals = dist.pdf(x_grid)
        self.assertTrue(np.all(pdf_vals >= 0.0))

        # Numerical integration check
        dx = x_grid[1] - x_grid[0]
        integral = np.sum(pdf_vals) * dx
        self.assertAlmostEqual(integral, 1.0, places=2)

    def test_cdf_and_ppf_are_inverses(self):
        dist = SinhArcsinhDistribution(loc=6.5, scale=1.5, skewness=0.4, tailweight=1.1)
        quantiles = [0.05, 0.10, 0.25, 0.50, 0.75, 0.90, 0.95]
        for q in quantiles:
            val = dist.ppf(q)
            recovered_q = dist.cdf(val)
            self.assertAlmostEqual(q, recovered_q, places=5)

    def test_rvs_generates_correct_sample_size(self):
        dist = SinhArcsinhDistribution(loc=6.0, scale=1.0, skewness=0.2, tailweight=1.0)
        samples = dist.rvs(size=500, random_state=42)
        self.assertEqual(len(samples), 500)
        self.assertAlmostEqual(float(np.median(samples)), 6.0, delta=0.3)

    def test_mle_fit_recovers_distribution_parameters(self):
        true_dist = SinhArcsinhDistribution(loc=6.0, scale=1.5, skewness=0.3, tailweight=1.0)
        synthetic_data = true_dist.rvs(size=2000, random_state=42)
        fitted = SinhArcsinhDistribution.fit(synthetic_data)

        self.assertAlmostEqual(fitted.loc, 6.0, delta=0.3)
        self.assertAlmostEqual(fitted.scale, 1.5, delta=0.3)


if __name__ == "__main__":
    unittest.main()
