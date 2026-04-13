import json
import threading
import unittest
from pathlib import Path
from urllib.request import urlopen

import server
from backend.analytics import rebuild_all_cache
from backend.http_server import MonitorRequestHandler, ThreadedHttpServer
from backend.state import state


class SmokeTestCase(unittest.TestCase):
    def setUp(self):
        state.silver_cache = {"data": {"price": 1000.0, "source": "smoke-silver"}, "ts": 0}
        state.comex_silver_cache = {"data": {"price": 5.0, "priceCny": 950.0, "source": "smoke-comex"}, "ts": 0}
        state.gold_cache = {"data": {"price": 700.0, "source": "smoke-gold"}, "ts": 0}
        state.comex_gold_cache = {"data": {"price": 100.0, "priceCnyG": 680.0, "source": "smoke-comex-gold"}, "ts": 0}
        rebuild_all_cache()

    def test_banner_contains_port(self):
        banner = server.build_startup_banner()
        self.assertIn("8765", banner)

    def test_runtime_config_file_is_valid_json(self):
        config_path = Path("monitor.config.json")
        self.assertTrue(config_path.exists())
        config = json.loads(config_path.read_text(encoding="utf-8"))
        self.assertIn("server", config)
        self.assertIn("polling", config)

    def test_http_status_endpoint_smoke(self):
        httpd = ThreadedHttpServer(("127.0.0.1", 0), MonitorRequestHandler)
        port = httpd.server_address[1]
        thread = threading.Thread(target=httpd.serve_forever, daemon=True)
        thread.start()
        try:
            with urlopen(f"http://127.0.0.1:{port}/api/status", timeout=5) as response:
                payload = json.loads(response.read().decode("utf-8"))
            self.assertEqual(payload["status"], "running")
            self.assertIn("fastPoll", payload)
        finally:
            httpd.shutdown()
            httpd.server_close()


if __name__ == "__main__":
    unittest.main()
