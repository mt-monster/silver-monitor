---
name: update-tests-and-docs
description: |
  **强制性后置流程**：在 silver-monitor 项目中，**每次修改业务代码后**（backend/、assets/js/、miniprogram/、monitor.config.json 任何一处），必须按固定顺序执行：
    ① 跑一遍完整单元测试；
    ② 跑一遍完整 API / 集成测试；
    ③ 对缺失覆盖的新行为补业务测试案例；
    ④ 同步更新 docs/ 下所有受影响的中文文档。
  未完成 ①② 不得声明"任务完成"。

  触发场景：
  1. 任何对 backend/ 的修改（哪怕只改 1 行）。
  2. 用户显式说"补测试""跑测试""更新文档"。
  3. 新增/修改策略算法、API 接口、数据模型、配置项、前端页面逻辑。
  4. 修复 bug（必须补回归测试，不得删原测试）。

  覆盖范围：Python 后端单元测试、API 集成测试、性能/回归测试、外部数据源联调脚本、以及对应的中文技术文档。
---

# 功能修改后的强制验证流程

> **铁律**：**改完代码不等于任务完成**。必须在结束前完成本 skill 全部 6 步，且最终消息中必须展示 pytest 的 `N passed, M failed` 行。

## 核心流程（严格顺序）

0. **基线快照** —— 开工前或 `git stash` 后先跑一次完整测试，记录当前 pass/fail（重点关注 AGENTS.md §5.3 中的"已知失败"）。
1. **分析变更影响范围** —— 确定修改了哪些模块。
2. **识别测试缺口** —— 哪些行为需要新测试，哪些旧测试需要更新。
3. **编写/更新测试** —— 遵循项目 unittest.TestCase 风格（pytest 兼容运行）。
4. **完整复跑单元 + 集成测试** —— 与第 0 步基线对比，**不得新增任何失败**。
5. **识别并更新 docs/** —— 同步相关中文文档。
6. **最终复跑一次** —— 确认文档改动不影响测试，在消息中展示最终 pytest 汇总行。

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
- **编写**时沿用 `unittest.TestCase` 风格，**运行**用 pytest（pytest 原生兼容 unittest.TestCase）
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

### 运行测试（日常开发速查）

```powershell
# 激活虚拟环境（已激活可跳过）
.\.venv\Scripts\Activate.ps1

# 完整回归（排除研究脚本和外部联调）
python -m pytest tests/ -q --ignore-glob="tests/_*.py" --ignore-glob="tests/verify_*.py"

# 单文件快速迭代
python -m pytest tests/test_momentum_strategy.py -v
```

> 项目统一用 **pytest** 运行（AGENTS.md §5.1）。现有用例基于 `unittest.TestCase`，pytest 天然兼容，**不要**把 unittest 风格重写成 pytest 风格。

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

## 第六步：运行验证（强制命令）

### 测试分层

| 层级 | 对应文件 | 是否必跑 |
|------|----------|---------|
| **单元测试** | `tests/test_*.py`（除下一行的 API 集成）| ✅ 必跑 |
| **API / 集成测试** | `test_smoke.py`、`test_backtest_api.py`、`test_threshold_api.py`、`test_source_switch.py`、`test_config_validation.py` | ✅ 必跑 |
| **外部数据源联调** | `tests/verify_*.py`（iFinD / Infoway / BTC） | ⚠️ 仅在数据源接入变更时跑 |
| **一次性回测 / 研究脚本** | `tests/_run_*.py`、`tests/_explore_*.py`、`tests/_inspect_*.py` | ❌ 不纳入回归 |

### 强制测试命令（按顺序）

```powershell
# 确保日志目录存在（项目根自带 logs/，无则创建）
if (-not (Test-Path logs)) { New-Item -ItemType Directory logs | Out-Null }

# ① 基线（开工前或 git stash 后跑一次，产物 logs/pytest-baseline.xml）
python -m pytest tests/ -q --tb=line `
  --junit-xml=logs/pytest-baseline.xml `
  --ignore-glob="tests/_*.py" --ignore-glob="tests/verify_*.py"

# ② 改完代码后必须再跑一次完整回归（产物 logs/pytest-latest.xml）
python -m pytest tests/ -q --tb=short `
  --junit-xml=logs/pytest-latest.xml `
  --ignore-glob="tests/_*.py" --ignore-glob="tests/verify_*.py"

# ③ 首个失败处停止（调试用）
python -m pytest tests/ -x -q --tb=short `
  --ignore-glob="tests/_*.py" --ignore-glob="tests/verify_*.py"

# ④ 单独复核新增/修改的模块
python -m pytest tests/test_<新模块>.py -v
```

### 测试报告输出（强制产物）

**每次执行 ①② 后必须输出两份报告**：

1. **机器可读** — `logs/pytest-baseline.xml` / `logs/pytest-latest.xml`（pytest `--junit-xml` 自动生成，无需额外依赖）。
2. **人类可读** — 在聊天消息末尾展示如下结构化 Markdown 报告（从 pytest 输出摘取，不得省略）：

```markdown
## 测试报告（<YYYY-MM-DD HH:MM>）

- **范围**：`pytest tests/ --ignore-glob="tests/_*.py" --ignore-glob="tests/verify_*.py"`
- **汇总**：`N passed, M failed, K subtests passed`（从 pytest 最后一行复制）
- **耗时**：`<秒数> s`
- **JUnit XML**：`logs/pytest-latest.xml`

### 失败清单（对比 AGENTS.md §5.3 基线）

| 用例 | 类型 | 原因摘要 | 基线? |
|------|------|---------|------|
| `tests/test_xxx.py::...` | FAILED | AssertionError: ... | 是/否 |

### 新增/修改测试

| 文件 | 新增用例数 | 覆盖行为 |
|------|----------|---------|
| `tests/test_xxx.py` | 3 | <本次修改对外承诺的行为> |

### 结论

- [ ] 失败数与 AGENTS.md §5.3 基线一致（允许通过）
- [ ] 新增失败全部已修复 / 或已明示为预期影响
- [ ] 新增测试全部 PASS
```

**禁止**只说"测试通过"、"全部绿"之类模糊措辞。**禁止**省略"失败清单"段落（即使 0 failed 也要写 "无"）。

### 与基线对比（必做）

- **允许**：新增测试通过；`AGENTS.md §5.3` 列出的已知失败仍失败（当前基线：4 failed，详见 AGENTS.md §5.3，不在此处冗余列举以防过期）。
- **禁止**：出现任何新失败。必须当场修复，或在消息中**明示**"此失败为本次修改的预期影响，已同步更新测试期望值"。
- **必须展示**：最终 pytest 末尾的 `N passed, M failed` 行，不得只说"跑过了"。

### 测试补充原则（当覆盖缺失时触发）

- 顺序：**happy path → 边界（空、极值、负数、0）→ 错误分支**。
- 优先覆盖**对外承诺**（API 返回字段、配置驱动路径、信号类型分支），再考虑实现细节。
- **禁止**为让红转绿弱化断言；**禁止**删除或 `skip` 已有测试。
- 新增测试必须在"强制测试命令 ②" 下 PASS。

### 文档验证

- [ ] 文档中参数默认值是否与 `monitor.config.json` 一致？（用 `grep_search` 交叉核对参数名）
- [ ] 代码示例是否可直接运行？
- [ ] 相对链接是否有效？
- [ ] 日期格式 `YYYY-MM-DD`？
- [ ] 若修改了 API 契约，`docs/strategy-backtest.md` / `docs/data-integration.md` / `AGENTS.md §8 API 概览` 是否同步？

---

## 项目结构参考

详见 [references/project-structure.md](references/project-structure.md) 了解测试与文档的对应关系。

## 常见测试模式参考

详见 [references/testing-patterns.md](references/testing-patterns.md) 获取各类测试的模板和示例。
