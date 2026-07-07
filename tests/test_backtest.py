import unittest

from app.backtest import run_backtest


class BacktestTests(unittest.TestCase):
    def test_run_backtest_returns_summary_metrics(self):
        prices = [100, 101, 102, 101, 100, 103, 104, 103, 105, 107]
        result = run_backtest(prices, weights={"technical": 0.35, "macro": 0.30, "news": 0.35})

        self.assertIn("total_return", result)
        self.assertIn("win_rate", result)
        self.assertIn("trades", result)
        self.assertIn("equity_curve", result)
        self.assertGreaterEqual(len(result["equity_curve"]), 1)
        self.assertGreaterEqual(result["trades"], 0)


if __name__ == "__main__":
    unittest.main()
