from backend.backtest import load_history, momentum_params_for_symbol, reversal_params_from_body, run_momentum_long_only_backtest, run_reversal_long_only_backtest
symbol = 'comex'
bars, _, err = load_history(symbol)
if err:
    print(f'comex: 无历史数据')
    exit(1)
print('【COMEX白银 动量策略】')
p = momentum_params_for_symbol(symbol)
result = run_momentum_long_only_backtest(bars, p)
m = result['metrics']
print(f'总收益={m["totalReturnPct"]:.2f}%, 年化={m["annualizedReturnPct"]}, 夏普={m["sharpeRatio"]}, 回撤={m["maxDrawdownPct"]:.2f}%, 回合={m["roundTripCount"]}, 胜率={m["winRatePct"]}')
print('\n【COMEX白银 反转策略】')
p = reversal_params_from_body({}, symbol)
result = run_reversal_long_only_backtest(bars, p)
m = result['metrics']
print(f'总收益={m["totalReturnPct"]:.2f}%, 年化={m["annualizedReturnPct"]}, 夏普={m["sharpeRatio"]}, 回撤={m["maxDrawdownPct"]:.2f}%, 回合={m["roundTripCount"]}, 胜率={m["winRatePct"]}')
