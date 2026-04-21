from backend.backtest import load_history, momentum_params_for_symbol, reversal_params_from_body, run_momentum_long_only_backtest, run_reversal_long_only_backtest
symbols = ['huyin', 'comex', 'hujin', 'comex_gold']
print('【动量策略】')
for s in symbols:
    bars, _, err = load_history(s)
    if err:
        print(f'{s}: 无历史数据')
        continue
    p = momentum_params_for_symbol(s)  # 只传 symbol
    result = run_momentum_long_only_backtest(bars, p)
    m = result['metrics']
    print(f'{s}: 总收益={m["totalReturnPct"]:.2f}%, 年化={m["annualizedReturnPct"]}, 夏普={m["sharpeRatio"]}, 回撤={m["maxDrawdownPct"]:.2f}%, 回合={m["roundTripCount"]}, 胜率={m["winRatePct"]}')
print('\n【反转策略】')
for s in symbols:
    bars, _, err = load_history(s)
    if err:
        print(f'{s}: 无历史数据')
        continue
    p = reversal_params_from_body({}, s)
    result = run_reversal_long_only_backtest(bars, p)
    m = result['metrics']
    print(f'{s}: 总收益={m["totalReturnPct"]:.2f}%, 年化={m["annualizedReturnPct"]}, 夏普={m["sharpeRatio"]}, 回撤={m["maxDrawdownPct"]:.2f}%, 回合={m["roundTripCount"]}, 胜率={m["winRatePct"]}')
