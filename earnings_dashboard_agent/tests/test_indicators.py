import unittest

import pandas as pd

from analytics.indicators import (
    annualized_volatility,
    average_directional_index,
    relative_strength_index,
    relative_volume,
    session_vwap,
    simple_moving_average,
)


class IndicatorTests(unittest.TestCase):
    def test_simple_moving_average_respects_window(self):
        result = simple_moving_average(pd.Series([1, 2, 3, 4]), window=3)

        self.assertTrue(pd.isna(result.iloc[1]))
        self.assertEqual(result.iloc[2], 2.0)

    def test_rsi_marks_uninterrupted_gains_as_overbought(self):
        result = relative_strength_index(pd.Series(range(1, 20)), window=5)

        self.assertEqual(result.iloc[-1], 100)

    def test_volatility_is_zero_for_constant_prices(self):
        self.assertEqual(annualized_volatility(pd.Series([10, 10, 10])), 0.0)

    def test_relative_volume_uses_prior_twenty_sessions(self):
        result = relative_volume(pd.Series([1] * 20 + [2]), window=20)

        self.assertEqual(result, 2.0)

    def test_session_vwap_is_volume_weighted(self):
        bars = pd.DataFrame({"High": [12, 22], "Low": [8, 18], "Close": [10, 20], "Volume": [3, 1]})

        self.assertEqual(session_vwap(bars), 12.5)

    def test_adx_returns_a_bounded_value_for_trending_ohlc(self):
        close = pd.Series(range(1, 50), dtype=float)
        bars = pd.DataFrame({"High": close + 1, "Low": close - 1, "Close": close})
        result = average_directional_index(bars, window=14).dropna()

        self.assertFalse(result.empty)
        self.assertTrue(result.between(0, 100).all())


if __name__ == "__main__":
    unittest.main()