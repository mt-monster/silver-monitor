import json
import threading
import unittest
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from backend.http_server import MonitorRequestHandler, ThreadedHttpServer


class ThresholdApiTestCase(unittest.TestCase):
    def setUp(self):
        self.httpd = ThreadedHttpServer(("127.0.0.1", 0), MonitorRequestHandler)
        self.port = self.httpd.server_address[1]
        self.thread = threading.Thread(target=self.httpd.serve_forever, daemon=True)
        self.thread.start()

    def tearDown(self):
        self.httpd.shutdown()
        self.httpd.server_close()

    def post_threshold(self, value):
        request = Request(
            f"http://127.0.0.1:{self.port}/api/threshold",
            data=json.dumps({"threshold": value}).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urlopen(request, timeout=5) as response:
            return json.loads(response.read().decode("utf-8"))

    def test_threshold_accepts_valid_value(self):
        payload = self.post_threshold(0.15)
        self.assertTrue(payload["ok"])
        self.assertAlmostEqual(payload["threshold"], 0.15, places=3)

    def test_threshold_rejects_out_of_range(self):
        request = Request(
            f"http://127.0.0.1:{self.port}/api/threshold",
            data=json.dumps({"threshold": 6.0}).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with self.assertRaises(HTTPError) as context:
            urlopen(request, timeout=5)
        self.assertEqual(context.exception.code, 400)

    def test_alerts_endpoint_returns_applied_threshold(self):
        self.post_threshold(0.15)
        with urlopen(f"http://127.0.0.1:{self.port}/api/alerts", timeout=5) as response:
            payload = json.loads(response.read().decode("utf-8"))
        self.assertAlmostEqual(payload["threshold"], 0.15, places=3)

    def test_per_market_thresholds(self):
        request = Request(
            f"http://127.0.0.1:{self.port}/api/threshold",
            data=json.dumps({"thresholds": {"hu": 0.12, "comex": 0.08}}).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urlopen(request, timeout=5) as response:
            payload = json.loads(response.read().decode("utf-8"))
        self.assertTrue(payload["ok"])
        self.assertAlmostEqual(payload["thresholds"]["hu"], 0.12, places=3)
        self.assertAlmostEqual(payload["thresholds"]["comex"], 0.08, places=3)

    def test_alerts_returns_thresholds_dict(self):
        with urlopen(f"http://127.0.0.1:{self.port}/api/alerts", timeout=5) as response:
            payload = json.loads(response.read().decode("utf-8"))
        self.assertIn("thresholds", payload)
        self.assertIsInstance(payload["thresholds"], dict)


if __name__ == "__main__":
    unittest.main()
