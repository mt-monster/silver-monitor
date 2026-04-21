---
name: update-tests-and-docs
description: |
  在 silver-monitor 项目完成功能修改后，自动补充和更新测试用例，并同步更新 docs/ 目录下的相关 Markdown 文档。
  
  触发场景：
  1. 用户完成某个功能点/bug修复后说"补一下测试"或"更新文档"
  2. 用户修改了策略算法、API接口、数据模型或前端逻辑
  3. 用户新增了功能模块或配置项
  4. 任何涉及 tests/ 或 docs/ 目录的变更请求
  
  本 skill 覆盖：Python 后端单元测试、JavaScript 前端测试、API 接口测试、性能/回归测试，以及对应的技术文档更新。
---

# 功能修改后补充测试与文档

## 核心流程

修改完功能点后，按以下顺序执行：

1. **分析变更影响范围** —— 确定修改了哪些模块
2. **识别测试缺口** —— 哪些行为需要新测试，哪些旧测试需要更新
3. **编写/更新测试** —— 遵循项目测试风格
4. **识别文档缺口** —— 哪些文档需要同步更新
5. **更新文档** —— 遵循项目文档风格
6. **运行验证** —— 确保新测试通过且旧测试不挂

---

## 第一步：分析变更影响范围

从用户的修改描述中提取以下信息：

| 维度 | 需要回答的问题 |
|------|--------------|
| **修改位置** | 改了哪些文件？后端/前端/配置？ |
| **修改性质** | 新增功能 / 修复 bug / 重构 / 参数调整？ |
| **接口变化** | API 签名、返回值结构、字段有变化吗？ |
| **配置变化** | monitor.config.json 有新增或变更配置项吗？ |
| **策略变化** | 信号计算逻辑、阈值、参数有变化吗？ |
| **前端变化** | 渲染逻辑、数据流、UI 组件有变化吗？ |

**关键原则**：不要只测修改的那一行代码，要测"修改后该模块对外承诺的行为"。

---

## 第二步：识别测试缺口

根据变更类型，参考以下检查清单：

### 后端策略算法变更（如 momentum.py / reversal.py）

- [ ] 新算法分支是否覆盖？（如新增了一个 signal 类型）
- [ ] 边界条件是否测试？（空序列、最小长度、极大值）
- [ ] 参数变化是否影响旧测试？需要更新期望值吗？
- [ ] 配置驱动的参数（如 realtime 段覆盖）是否被测试？

参考：`tests/test_momentum_strategy.py`

### 后端 API 变更（如 http_server.py）

- [ ] 新接口是否有冒烟测试？
- [ ] 接口返回值结构变化是否同步到 tests？
- [ ] 错误码和异常分支是否覆盖？
- [ ] SSE / 轮询数据格式是否验证？

参考：`tests/test_smoke.py`、`tests/test_backtest_api.py`

### 前端逻辑变更（如 core.js / momentum.js / reversal.js）

- [ ] 前端单元测试存在吗？（本项目前端测试较少，优先补充关键计算函数）
- [ ] 参数加载和 fallback 逻辑是否验证？
- [ ] 数据流变化（如从浏览器计算改为后端推送）是否需要 mock 测试？

### 数据模型/字段变更

- [ ] 新增字段是否有默认值/兼容性处理？
- [ ] 字段类型变化（如 int -> float）是否影响序列化/反序列化？
- [ ] 缓存结构变化（如 state.py 新增字段）是否被测试？

### 配置系统变更

- [ ] 新配置项是否有默认值？
- [ ] 配置优先级（default < symbol < realtime.default < realtime.symbol）是否正确？
- [ ] 配置缺失时是否有 graceful fallback？

---

## 第三步：编写/更新测试

### Python 后端测试规范

**文件位置**：`tests/test_<module>.py`

**命名规范**：
```python
class MomentumCoreTestCase(unittest.TestCase):
    def test_golden_last_bar_strong_uptrend(self):
        """单调大幅上涨：快慢线多头、张口与短线斜率同向应触发强多。"""
        ...
```

**风格要求**：
- 使用 `unittest` 框架（不引入 pytest 等额外依赖）
- 测试方法名用 `test_<场景>_<预期行为>` 格式
- 复杂场景用 docstring 中文描述业务含义
- 使用 `assertAlmostEqual` 比较浮点数
- 使用 `assertIsNotNone` / `assertIsNone` 验证存在性
- 构造测试数据时优先使用确定性序列（如等差数列），避免随机数据

**示例**：
```python
def test_custom_thresholds_weaker_entry(self):
    """缓涨：默认张口/斜率不足；放宽后应出现多头信号。"""
    base = 10000.0
    vals = [base + i * 0.45 for i in range(50)]
    default = calc_momentum(vals)
    self.assertEqual(default["signal"], "neutral")
    loose = calc_momentum(
        vals,
        MomentumParams(spread_entry=0.01, spread_strong=0.05, slope_entry=0.001),
    )
    self.assertIn(loose["signal"], ("buy", "strong_buy"))
```

**边界测试必须覆盖**：
- 输入长度不足（返回 None 或空值）
- 恒定序列（零波动）
- 单点突变（极端值）
- 参数为 0 / 负数时的行为

### 运行测试

```powershell
.\.venv\Scripts\Activate.ps1
python -m unittest discover -s tests -p "test_*.py" -v
```

或针对单个文件：
```powershell
python -m unittest tests.test_momentum_strategy -v
```

---

## 第四步：识别文档缺口

根据变更类型，确定需要更新的文档：

| 变更类型 | 可能涉及的文档 |
|---------|--------------|
| 策略算法修改 | `docs/momentum-strategy.md`、`docs/strategy-backtest.md` |
| 数据模型/字段变更 | `docs/data-models.md`、`docs/data-integration.md` |
| API 接口变更 | `docs/strategy-backtest.md`（含 API 章节）、相关页面文档 |
| 配置系统变更 | `docs/business-architecture.md`（含配置说明） |
| 测试流程变更 | `docs/testing-guide.md` |
| 新增研究/分析功能 | `docs/research-monte-carlo.md` 或新建文档 |

**文档更新检查清单**：
- [ ] 算法描述是否与实际代码一致？
- [ ] 参数表格是否包含新增/修改的参数？
- [ ] 默认值是否与 `monitor.config.json` 一致？
- [ ] API 请求/响应示例是否更新？
- [ ] 字段说明是否完整（类型、含义、是否可选）？
- [ ] 最后更新日期是否修改？

---

## 第五步：更新文档

### 文档风格

- 使用 Markdown 格式
- 技术文档用中文撰写
- 参数说明使用表格：`| 字段 | 类型 | 说明 |`
- 代码示例使用 fenced code blocks，标注语言
- 日期格式：`YYYY-MM-DD`

### 更新策略

**增量更新优先**：不要重写整篇文档，只更新变更相关的章节。

**参数同步规则**：
- 文档中的"默认值"必须与 `monitor.config.json` 中的值一致
- 如果修改了配置文件的默认值，同步更新所有引用该参数的文档
- 使用 grep 搜索参数名，确保没有遗漏

**算法描述同步规则**：
- 如果修改了计算公式，更新文档中的公式和伪代码
- 如果新增了信号类型或分支，更新信号对照表
- 如果修改了阈值逻辑，更新阈值判定流程

---

## 第六步：运行验证

### 测试验证

```powershell
# 1. 运行全部测试
python -m unittest discover -s tests -p "test_*.py"

# 2. 如果新增测试文件，单独验证
python -m unittest tests.test_<新模块> -v

# 3. 检查测试覆盖率（手动审查）
# 重点检查：修改的代码路径是否都有测试覆盖
```

### 文档验证

- [ ] 文档中的代码示例是否可执行？
- [ ] 参数值是否与代码一致？（交叉验证）
- [ ] 链接是否有效？（相对路径检查）

---

## 项目结构参考

详见 [references/project-structure.md](references/project-structure.md) 了解测试与文档的对应关系。

## 常见测试模式参考

详见 [references/testing-patterns.md](references/testing-patterns.md) 获取各类测试的模板和示例。
