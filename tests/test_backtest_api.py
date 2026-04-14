import json
import threading
import unittest
from unittest.mock import patch
from urllib.request import Request, urlopen

from backend.http_server import MonitorRequestHandler, ThreadedHttpServer


class BacktestApiTestCase(unittest.TestCase):
    def setUp(self):
        self.httpd = ThreadedHttpServer(("127.0.0.1", 0), MonitorRequestHandler)
        self.port = self.httpd.server_address[1]
        self.thread = threading.Thread(target=self.httpd.serve_forever, daemon=True)
        self.thread.start()

    def tearDown(self):
        self.httpd.shutdown()
        self.httpd.server_close()

    @patch("backend.http_server.load_history", autospec=True)
    def test_backtest_ok_with_mock_history(self, mock_load):
        bars = [{"t": 1_000_000 + i * 60_000, "y": 10000.0 + i * 3.0} for i in range(60)]
        mock_load.return_value = (bars, "60m", None)
        request = Request(
            f"http://127.0.0.1:{self.port}/api/backtest",
            data=json.dumps({"strategy": "momentum", "symbol": "huyin", "mode": "long_only"}).encode(
                "utf-8"
            ),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urlopen(request, timeout=5) as response:
            payload = json.loads(response.read().decode("utf-8"))
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["meta"]["interval"], "60m")
        self.assertIn("equity", payload)
        self.assertIn("metrics", payload)

    def test_backtest_unknown_symbol_400(self):
        from urllib.error import HTTPError

        request = Request(
            f"http://127.0.0.1:{self.port}/api/backtest",
            data=json.dumps({"strategy": "momentum", "symbol": "invalid", "mode": "long_only"}).encode(
                "utf-8"
            ),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with self.assertRaises(HTTPError) as ctx:
            urlopen(request, timeout=5)
        self.assertEqual(ctx.exception.code, 400)


if __name__ == "__main__":
    unittest.main()
