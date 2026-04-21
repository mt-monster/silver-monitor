---
name: sync-docs-tests
description: 'Sync project docs and tests after feature changes. Use when: finishing a feature, refactoring backend/frontend, changing config schema, adding new strategy or indicator, modifying data models or API, after any code change that should be reflected in docs or test coverage. TRIGGERS: "更新文档", "同步文档", "补测试", "完善测试", "sync docs", "update docs and tests", "功能完成后同步", "检查文档和测试".'
argument-hint: 'Describe what changed (e.g. "added reversal strategy", "changed bar_window_ms config")'
---

# Sync Docs & Tests After Feature Change

## When to Use

After completing any code change in silver-monitor — especially:
- New strategy / indicator logic (backend or frontend JS)
- Config schema changes (`monitor.config.json` / `backend/config.py`)
- Data model / API field changes (`backend/models.py`, `backend/state.py`)
- New data source or poller behavior (`backend/pollers.py`, `backend/sources.py`)
- Refactored modules (e.g. splitting JS files, renaming functions)
- New test utilities or verify scripts

---

## Doc Map: Code → Document

| Changed Code | Primary Doc to Update |
|---|---|
| `backend/models.py`, `backend/state.py` | `docs/data-models.md` |
| `backend/pollers.py`, `backend/sources.py`, `backend/ifind.py` | `docs/data-integration.md` |
| `assets/js/monitor/momentum.js`, `backend/strategies/momentum.py` | `docs/momentum-strategy.md` |
| `assets/js/monitor/reversal.js` | `docs/momentum-strategy.md` (reversal section) |
| `assets/js/monitor/indicators.js` | `docs/momentum-strategy.md` (算法章节) |
| `backend/backtest.py`, `backend/analytics.py` | `docs/strategy-backtest.md` |
| `backend/research/monte_carlo.py`, `backend/research/samples.py` | `docs/research-monte-carlo.md` |
| `backend/alerts.py`, `backend/market_hours.py` | `docs/business-architecture.md` |
| `monitor.config.json` schema / new keys | All docs that reference config fields |
| `tests/` new files or coverage changes | `docs/testing-guide.md` |
| New JS files in `assets/js/monitor/` | `docs/business-architecture.md` (展示层章节) |

---

## Procedure

### Step 1 — Identify what changed

If given a description (argument), parse it. Otherwise:
1. Read the current diff or ask: "这次改了哪些文件或功能？"
2. Map changed files to the doc table above.
3. Identify which docs need updating (may be multiple).

### Step 2 — Audit existing docs

For each doc to update:
1. Read the relevant section(s) with `read_file`.
2. Note what is **stale**: outdated field names, removed params, wrong default values, missing sections.
3. Note what is **missing**: new features, new config keys, new modules not yet mentioned.

Key things to check per doc type:
- **data-models.md**: field tables match current `models.py` / `state.py` types exactly
- **momentum-strategy.md**: algorithm params (periods, thresholds) match `monitor.config.json` defaults; minLen formula is correct
- **data-integration.md**: bar_window_ms, polling logic, buffer behavior described accurately
- **testing-guide.md**: test file list is current; manual checklist steps are still valid
- **business-architecture.md**: module list and load order in `index.html` reflects actual state

### Step 3 — Update docs

Make targeted edits using `replace_string_in_file` or `multi_replace_string_in_file`.

Rules:
- Update the `> 更新日期：` line at the top of each changed doc to today's date.
- Only change sections that are actually stale — do not rewrite unrelated content.
- Keep Chinese section headings and formatting consistent with existing style.
- Tables: align columns, match existing width style.
- Code blocks: use same language tag as surrounding file.

### Step 4 — Audit test coverage

1. Run `pytest tests/ -q` to see current pass/fail state.
2. For each changed code module, check if a test file exists:

| Module | Expected Test File |
|---|---|
| `backend/analytics.py` | `tests/test_analytics.py` |
| `backend/backtest.py` | `tests/test_backtest.py`, `tests/test_backtest_api.py` |
| `backend/alerts.py` | `tests/test_alerts_tick_jump.py`, `tests/test_threshold_api.py` |
| `backend/market_hours.py` | `tests/test_market_hours.py` |
| `backend/strategies/momentum.py` | `tests/test_momentum_strategy.py`, `tests/test_strategy_perf.py` |
| `backend/strategies/reversal.py` | `tests/test_strategy_perf.py` |
| `backend/research/monte_carlo.py` | `tests/test_monte_carlo.py` |
| `backend/pollers.py` (bar logic) | `tests/test_smoke.py` (integration) |
| New config keys | `tests/test_smoke.py` (config load) |

3. For any gap (new code with no test), add test cases.

### Step 5 — Write missing tests

When adding tests to an existing file:
- Read the file first to match naming style (`test_` prefix, class-free functions, `assert` style).
- Use `pytest.fixture` and `unittest.mock.patch` patterns already present in the file.
- Add a comment `# --- <feature name> ---` to group new tests.
- Keep tests isolated: no real network calls, no real file I/O.

When creating a new test file:
- Match the header pattern in existing test files.
- Import from `backend.*` (not relative paths).
- Include at least: one happy-path test, one edge-case test, one error/invalid-input test.

### Step 6 — Run tests and confirm

```powershell
.\.venv\Scripts\python -m pytest tests/ -q
```

Expected: all previously-passing tests still pass, new tests pass.
If failures: fix the test or the code before marking the task done.

### Step 6b — Backtest performance validation (applies when strategy params changed)

**Trigger**: momentum or reversal strategy parameters changed (thresholds, weights, periods, etc.)

Run the performance comparison suite:
```powershell
.\.venv\Scripts\python -m pytest tests/test_strategy_perf.py -v
```

This suite proves updates are improvements by:
| Test | What it proves |
|------|----------------|
| `test_comex_momentum_new_vs_overtight` | New COMEX thresholds fire where old over-tight params couldn't |
| `test_comex_momentum_return_on_uptrend` | New momentum params capture uptrend profit |
| `test_comex_momentum_old_params_produce_no_trades` | Documents the pre-fix broken state |
| `test_reversal_new_weights_active` | New reversal weights still produce trades (not broken) |
| `test_reversal_new_weights_score_balance` | Mathematical proof: new RSI+BB weight balance reduces missed early reversals |
| `test_reversal_both_produce_signals_on_crash` | New weights return valid signal on extreme market |

**If a test fails after your param change**: the change may have broken something that was previously working. Either:
1. Revise the params to fix the failure, OR
2. Update the test's baseline to reflect a deliberate trade-off (add a comment explaining why)

**When adding new strategy params**: add a corresponding test to `tests/test_strategy_perf.py` using the `_uptrend_bars()` or `_crash_recovery_bars()` helpers (or add a new data generator if needed). Use daily timestamps to avoid annualization overflow.

### Step 7 — Report

Summarize:
- Which docs were updated and what changed
- Which tests were added (file + function names)
- Backtest comparison result (roundTripCount and totalReturnPct for old vs new params)
- Final test result (N passed, M failed — list any failures)

---

## Known Pre-existing Failures (as of 2026-04-21)

These 3 failures existed before the bar-window refactor and are **unrelated** to current work. Do not treat them as regressions:
- `tests/test_source_switch.py` — source switch API not yet implemented
- *(check with `pytest tests/ -q` for current baseline)*

---

## Project Quick Reference

```
docs/               # All documentation (Chinese, Markdown)
tests/              # pytest tests + verify_*.py connectivity scripts
backend/            # Python server: pollers, strategies, models, alerts
assets/js/monitor/  # Frontend JS modules
monitor.config.json # Runtime config (loaded by both backend and frontend)
```

Config defaults live in **both** `monitor.config.json` AND `backend/config.py` (`DEFAULT_CONFIG`). When a config key changes, update both files and any doc that references its default value.

Bar window: `frontend.bar_window_ms` (default: `30000` ms = 30s per bar)
