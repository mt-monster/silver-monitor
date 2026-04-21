# 常见测试模式参考

## 1. 策略算法测试模板

### 基础信号测试

```python
import unittest
from backend.strategies.xxx import calc_xxx, XxxParams

class XxxStrategyTestCase(unittest.TestCase):
    def test_insufficient_length_returns_none(self):
        """数据不足时应返回 None。"""
        vals = [100.0] * 10  # 少于最小要求长度
        self.assertIsNone(calc_xxx(vals))
    
    def test_flat_series_neutral(self):
        """恒定价格序列应返回 neutral。"""
        vals = [100.0] * 50
        info = calc_xxx(vals)
        self.assertIsNotNone(info)
        self.assertEqual(info["signal"], "neutral")
    
    def test_uptrend_signal(self):
        """单调上涨应触发多头信号。"""
        base = 10000.0
        vals = [base + i * 80.0 for i in range(50)]
        info = calc_xxx(vals)
        self.assertIsNotNone(info)
        self.assertIn(info["signal"], ("buy", "strong_buy"))
    
    def test_downtrend_signal(self):
        """单调下跌应触发空头信号。"""
        base = 10000.0
        vals = [base - i * 80.0 for i in range(50)]
        info = calc_xxx(vals)
        self.assertIsNotNone(info)
        self.assertIn(info["signal"], ("sell", "strong_sell"))
```

### 参数覆盖测试

```python
    def test_custom_params_override_default(self):
        """自定义参数应改变信号结果。"""
        base = 10000.0
        vals = [base + i * 0.45 for i in range(50)]
        
        # 默认参数下应为 neutral
        default = calc_xxx(vals, XxxParams())
        self.assertEqual(default["signal"], "neutral")
        
        # 放宽阈值后应出现信号
        loose = calc_xxx(vals, XxxParams(threshold=0.01))
        self.assertIn(loose["signal"], ("buy", "strong_buy"))
```

### 边界条件测试

```python
    def test_empty_list(self):
        """空列表应返回 None。"""
        self.assertIsNone(calc_xxx([]))
    
    def test_single_element(self):
        """单元素列表应返回 None。"""
        self.assertIsNone(calc_xxx([100.0]))
    
    def test_extreme_value(self):
        """包含极端值不应抛异常。"""
        vals = [100.0] * 49 + [999999.0]
        info = calc_xxx(vals)
        self.assertIsNotNone(info)
```

## 2. 回测引擎测试模板

```python
import unittest
from backend.backtest import run_xxx_backtest
from backend.strategies.xxx import XxxParams

class BacktestEngineTestCase(unittest.TestCase):
    def test_equity_length_matches_bars(self):
        """权益曲线长度应与输入 bar 数一致。"""
        bars = [{"t": 1_000_000 + i * 60_000, "y": 10000.0 + i * 5.0} 
                for i in range(80)]
        out = run_xxx_backtest(bars, XxxParams())
        self.assertEqual(len(out["equity"]), 80)
        self.assertIn("metrics", out)
    
    def test_flat_market_no_trades(self):
        """横盘市场应无交易或权益接近初始值。"""
        bars = [{"t": i * 60_000, "y": 10000.0} for i in range(60)]
        out = run_xxx_backtest(bars, XxxParams())
        last_eq = out["equity"][-1]["equity"]
        self.assertAlmostEqual(last_eq, 1.0, places=3)
    
    def test_metrics_structure(self):
        """绩效指标应包含预期字段。"""
        bars = [{"t": i * 60_000, "y": 10000.0 + i * 5.0} 
                for i in range(80)]
        out = run_xxx_backtest(bars, XxxParams())
        metrics = out["metrics"]
        self.assertIn("totalReturnPct", metrics)
        self.assertIn("maxDrawdownPct", metrics)
```

## 3. API 接口测试模板

```python
import unittest
import json
from backend.http_server import RequestHandler

class ApiTestCase(unittest.TestCase):
    def setUp(self):
        """模拟请求环境。"""
        # 根据实际项目调整 mock 方式
        pass
    
    def test_api_returns_expected_structure(self):
        """API 应返回预期的数据结构。"""
        # 发送请求并验证响应结构
        pass
    
    def test_api_error_handling(self):
        """异常输入应返回合适的错误码。"""
        # 测试 400 / 503 等错误分支
        pass
```

## 4. 配置系统测试模板

```python
import unittest
from backend.config import load_config  # 或实际配置加载函数

class ConfigTestCase(unittest.TestCase):
    def test_config_priority(self):
        """配置优先级：default < symbol < realtime。"""
        # 验证配置覆盖顺序
        pass
    
    def test_config_missing_fallback(self):
        """配置缺失时应有默认值。"""
        # 验证 graceful fallback
        pass
```

## 5. 状态管理测试模板

```python
import unittest
from backend import state

class StateTestCase(unittest.TestCase):
    def test_state_thread_safety(self):
        """状态更新应线程安全。"""
        # 验证 cache_lock 使用
        pass
    
    def test_state_initialization(self):
        """新字段应有合理的初始值。"""
        # 验证新增 state 字段
        pass
```

## 6. 性能/回归测试模板

```python
import unittest
import time

class PerformanceTestCase(unittest.TestCase):
    def test_calculation_under_100ms(self):
        """计算应在 100ms 内完成。"""
        start = time.time()
        # 执行计算
        elapsed = time.time() - start
        self.assertLess(elapsed, 0.1)
    
    def test_memory_usage_stable(self):
        """内存使用应保持稳定。"""
        # 适用于 buffer/cache 类功能
        pass
```

## 测试数据构造最佳实践

### 确定性序列

```python
# 等差上涨序列
uptrend = [base + i * step for i in range(n)]

# 等差下跌序列
downtrend = [base - i * step for i in range(n)]

# 恒定序列
flat = [base] * n

# 正弦波动序列（周期性）
import math
oscillating = [base + amplitude * math.sin(i * freq) for i in range(n)]

# V型反转序列
v_shape = [base + i * step for i in range(n//2)] + \
          [base + (n//2)*step - i * step for i in range(n//2)]
```

### 避免使用随机数据

```python
# ❌ 不推荐
import random
vals = [random.uniform(90, 110) for _ in range(50)]

# ✅ 推荐
determined_vals = [100.0 + (i % 5) * 2.0 for i in range(50)]
```

## 测试命名规范

| 场景 | 命名示例 |
|-----|---------|
| 正常流程 | `test_golden_path_returns_success` |
| 边界条件 | `test_insufficient_length_returns_none` |
| 错误处理 | `test_invalid_params_raises_value_error` |
| 参数覆盖 | `test_custom_thresholds_changes_signal` |
| 性能要求 | `test_calculation_completes_under_100ms` |
| 并发安全 | `test_concurrent_updates_are_thread_safe` |
