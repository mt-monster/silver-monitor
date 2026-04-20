"""验证 Admin 数据源配置变更能实时影响轮询数据获取。

以沪银 AG0 为例：
1. 默认优先级 ifind → sina，验证 ifind 优先
2. 通过修改 state.source_priority 切换为 sina only
3. 验证切换后数据来自 sina
4. 模拟 POST /api/admin/source-config 验证 HTTP API 能正确切换
"""
import io
import json
import threading
import unittest
from unittest.mock import patch, MagicMock


# 构造 mock 数据源函数
def _mock_ifind_ok():
    return {"price": 8100.0, "source": "iFinD-AG0", "timestamp": 1}

def _mock_sina_ok():
    return {"price": 8099.0, "source": "Sina-AG0", "timestamp": 1}

def _mock_ifind_fail():
    return None


class TestSourceSwitchAG0(unittest.TestCase):
    """测试 Admin 切换数据源后，轮询是否使用新配置。"""

    def setUp(self):
        """每个测试前重置 state.source_priority 并替换 dispatch 函数。"""
        from backend.state import state
        from backend import pollers
        self._original_priority = {k: list(v) for k, v in state.source_priority.items()}
        state.source_priority["ag0"] = ["ifind", "sina"]
        # 保存原始 dispatch 条目并替换为 mock
        self._orig_dispatch_ifind = pollers._SOURCE_DISPATCH.get(("ag0", "ifind"))
        self._orig_dispatch_sina = pollers._SOURCE_DISPATCH.get(("ag0", "sina"))
        pollers._SOURCE_DISPATCH[("ag0", "ifind")] = _mock_ifind_ok
        pollers._SOURCE_DISPATCH[("ag0", "sina")] = _mock_sina_ok

    def tearDown(self):
        from backend.state import state
        from backend import pollers
        state.source_priority.update(self._original_priority)
        # 恢复原始 dispatch
        if self._orig_dispatch_ifind is not None:
            pollers._SOURCE_DISPATCH[("ag0", "ifind")] = self._orig_dispatch_ifind
        if self._orig_dispatch_sina is not None:
            pollers._SOURCE_DISPATCH[("ag0", "sina")] = self._orig_dispatch_sina

    # ── 1. _fetch_by_priority 动态读取 source_priority ──────────

    def test_default_priority_ifind_first(self):
        """默认优先级 [ifind, sina]，ifind 成功时应返回 iFinD 数据。"""
        from backend.pollers import _fetch_by_priority

        result = _fetch_by_priority("ag0")
        self.assertIsNotNone(result)
        self.assertEqual(result["source"], "iFinD-AG0")

    def test_switch_to_sina_only(self):
        """切换为 [sina]，应返回 Sina 数据。"""
        from backend.state import state
        from backend.pollers import _fetch_by_priority

        state.source_priority["ag0"] = ["sina"]
        result = _fetch_by_priority("ag0")
        self.assertIsNotNone(result)
        self.assertEqual(result["source"], "Sina-AG0")

    def test_switch_back_to_ifind(self):
        """先切到 sina，再切回 ifind，验证动态生效。"""
        from backend.state import state
        from backend.pollers import _fetch_by_priority

        # Step 1: 切到 sina only
        state.source_priority["ag0"] = ["sina"]
        r1 = _fetch_by_priority("ag0")
        self.assertEqual(r1["source"], "Sina-AG0")

        # Step 2: 切回 ifind 优先
        state.source_priority["ag0"] = ["ifind", "sina"]
        r2 = _fetch_by_priority("ag0")
        self.assertEqual(r2["source"], "iFinD-AG0")

    def test_ifind_fail_fallback_to_sina(self):
        """ifind 失败时自动降级到 sina。"""
        from backend import pollers
        from backend.pollers import _fetch_by_priority

        pollers._SOURCE_DISPATCH[("ag0", "ifind")] = _mock_ifind_fail
        result = _fetch_by_priority("ag0")
        self.assertIsNotNone(result)
        self.assertEqual(result["source"], "Sina-AG0")

    def test_reverse_priority_sina_first(self):
        """优先级 [sina, ifind]，应返回 Sina 数据。"""
        from backend.state import state
        from backend.pollers import _fetch_by_priority

        state.source_priority["ag0"] = ["sina", "ifind"]
        result = _fetch_by_priority("ag0")
        self.assertIsNotNone(result)
        self.assertEqual(result["source"], "Sina-AG0")

    # ── 2. HTTP API 验证 ──────────────────────────────────────

    def test_post_source_config_updates_state(self):
        """POST /api/admin/source-config 能正确更新 state.source_priority。"""
        from backend.state import state
        from backend.http_server import MonitorRequestHandler

        new_priority = {"ag0": ["sina"]}
        body_bytes = json.dumps({"priority": new_priority}).encode("utf-8")

        handler = MagicMock(spec=MonitorRequestHandler)
        handler.headers = {"Content-Length": str(len(body_bytes))}
        handler.rfile = io.BytesIO(body_bytes)
        handler.wfile = io.BytesIO()
        handler.send_response = MagicMock()
        handler.send_header = MagicMock()
        handler.end_headers = MagicMock()

        MonitorRequestHandler._handle_admin_source_config_post(handler)

        handler.send_response.assert_called_with(200)
        self.assertEqual(state.source_priority["ag0"], ["sina"])

    def test_post_then_fetch_uses_new_priority(self):
        """POST 切换后，_fetch_by_priority 立即使用新优先级。"""
        from backend.state import state
        from backend.http_server import MonitorRequestHandler
        from backend.pollers import _fetch_by_priority

        # 初始状态：ifind 优先
        r1 = _fetch_by_priority("ag0")
        self.assertEqual(r1["source"], "iFinD-AG0")

        # 通过 HTTP API 切到 sina only
        body = json.dumps({"priority": {"ag0": ["sina"]}}).encode("utf-8")
        handler = MagicMock(spec=MonitorRequestHandler)
        handler.headers = {"Content-Length": str(len(body))}
        handler.rfile = io.BytesIO(body)
        handler.wfile = io.BytesIO()
        handler.send_response = MagicMock()
        handler.send_header = MagicMock()
        handler.end_headers = MagicMock()
        MonitorRequestHandler._handle_admin_source_config_post(handler)

        # 立即验证：下一次 fetch 应该用 sina
        r2 = _fetch_by_priority("ag0")
        self.assertEqual(r2["source"], "Sina-AG0")

    # ── 3. 并发安全 ──────────────────────────────────────────

    def test_concurrent_switch_and_fetch(self):
        """并发切换 source_priority 时 _fetch_by_priority 不崩溃。"""
        from backend.state import state
        from backend.pollers import _fetch_by_priority

        errors = []

        def switcher():
            for _ in range(100):
                state.source_priority["ag0"] = ["sina"]
                state.source_priority["ag0"] = ["ifind", "sina"]

        def fetcher():
            for _ in range(100):
                try:
                    r = _fetch_by_priority("ag0")
                    if r:
                        self.assertIn(r["source"], ("iFinD-AG0", "Sina-AG0"))
                except Exception as e:
                    errors.append(e)

        t1 = threading.Thread(target=switcher)
        t2 = threading.Thread(target=fetcher)
        t1.start()
        t2.start()
        t1.join()
        t2.join()

        self.assertEqual(errors, [], f"并发错误: {errors}")


if __name__ == "__main__":
    unittest.main()
