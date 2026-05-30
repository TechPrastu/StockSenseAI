import unittest
from unittest.mock import MagicMock, patch
import pandas as pd

from ai.predictor import StockPredictor


class TestStockPredictor(unittest.TestCase):
    @patch('ai.predictor.Nse')
    @patch('ai.predictor.Ticker')
    @patch('ai.predictor.yf.Ticker')
    def test_get_insights_returns_expected_fields(self, mock_yf_ticker, mock_yq_ticker, mock_nse):
        dates = pd.date_range(start='2026-01-01', periods=30, freq='D')
        fake_history = pd.DataFrame({
            'Date': dates,
            'Open': [100.0 + i for i in range(30)],
            'High': [101.0 + i for i in range(30)],
            'Low': [99.0 + i for i in range(30)],
            'Close': [100.0 + i * 0.5 for i in range(30)],
            'Volume': [1000 + i * 10 for i in range(30)],
        })

        fake_yf = MagicMock()
        fake_yf.history.return_value = fake_history
        fake_yf.news = []
        mock_yf_ticker.return_value = fake_yf

        fake_yq = MagicMock()
        fake_yq.calendar = {}
        mock_yq_ticker.return_value = fake_yq

        mock_nse.return_value = MagicMock()

        predictor = StockPredictor()
        predictor.model = MagicMock()
        predictor.model.predict.return_value = [110.0]
        predictor.trained = True

        insights = predictor.get_insights('RELIANCE')

        self.assertIsInstance(insights, dict)
        self.assertIn('forecast', insights)
        self.assertIn('chart_pattern', insights)
        self.assertIn('advice', insights)
        self.assertIn('breakout_prediction', insights)
        self.assertIn('pattern_title', insights)
        self.assertTrue(isinstance(insights['forecast'], str))
        self.assertIn('Predicted next close', insights['forecast'])


if __name__ == '__main__':
    unittest.main()
