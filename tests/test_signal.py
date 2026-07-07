import unittest
from fastapi.testclient import TestClient

from app.main import app


class SignalEndpointTests(unittest.TestCase):
    def test_signal_endpoint_returns_expected_fields(self):
        client = TestClient(app)
        response = client.get('/signal')

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertIn('composite_score', payload)
        self.assertIn('direction', payload)
        self.assertIn('current_price', payload)
        self.assertIn('technical_score', payload)
        self.assertIn('macro_score', payload)
        self.assertIn('news_score', payload)


if __name__ == '__main__':
    unittest.main()
