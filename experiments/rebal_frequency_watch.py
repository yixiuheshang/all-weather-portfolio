"""调仓频率对照实验：月末一次 vs 每天/隔几天盯盘、见信号就调仓。

用法:
    py experiments/rebal_frequency_watch.py          # V3D（默认）
    py experiments/rebal_frequency_watch.py v3c      # V3c 交叉验证

用引擎的 rebal_mode="signal_watch"（每 N 交易日检查趋势信号，状态翻转即调仓）
对比月末基准，回答"是不是跑得越勤越好"。

产出:
    output/rebal_frequency_watch_{strategy}.json   各变体核心指标 + 换手 + 成本拖累
    output/rebal_frequency_grid_{strategy}.json    检查间隔网格 + 子样本稳健性 + 逐年差
"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import numpy as np
import pandas as pd

from allweather.data import load_panel, load_hs300_pb, load_hs300_pe
from allweather.config import (
    STRATEGY_RULES, STRATEGY_PARAMS, V3D_ASSETS, V3C_ASSETS, SP500_TREND_WINDOW,
)
from allweather.backtest import backtest_iv, adjust_nav_for_cash, _compute_weights
from allweather.stats import perf_metrics, yearly_returns
from allweather.pipeline import _precompute_percentile

# 单边交易成本场景（佣金+冲击成本）：默认万5，悲观千1
FEE_SCENARIOS = {"万5(0.05%单边)": 0.0005, "千1(0.10%单边)": 0.0010}


def build_common(strategy: str) -> tuple[list[str], dict]:
    """从 config 单一事实源构造该策略的引擎参数（与 pipeline.py 口径一致）。"""
    rules = STRATEGY_RULES[strategy]
    params = STRATEGY_PARAMS[strategy]
    assets = V3D_ASSETS if strategy == "v3d" else V3C_ASSETS
    common = dict(
        assets=assets,
        cash_ratio=0.0,
        iv_window=params["window"], max_w=params["max_w"], min_w=params["min_w"],
        nonferr_trend_window=rules["nonferr_trend_window"],
        wti_trend_window=rules["wti_trend_window"],
        gold_trend_filter=rules["gold_trend_filter"],
        gold_trend_window=rules["gold_trend_window"],
        gold_dip_threshold=rules["gold_dip_threshold"],
        gold_dip_cap=0.20,
        equity_trend_assets=rules["equity_trend_assets"],
        equity_trend_windows=rules["equity_trend_windows"],
        equity_trend_window=SP500_TREND_WINDOW,
        hs300_value_dip=rules["hs300_value_dip"],
        hs300_pb_data=load_hs300_pb(), hs300_pe_data=load_hs300_pe(),
        track_weights=True, track_signals=False,
        signal_label=strategy.upper(),
    )
    common["hs300_pb_pct"] = _precompute_percentile(common["hs300_pb_data"])
    common["hs300_pe_pct"] = _precompute_percentile(common["hs300_pe_data"])
    return assets, common


def month_end_index(index: pd.DatetimeIndex) -> set:
    return {index[i] for i in range(len(index))
            if i + 1 >= len(index) or index[i].month != index[i + 1].month}


def annual_turnover(weight_df: pd.DataFrame, rets: pd.DataFrame, initial_w: np.ndarray) -> float:
    """漂移感知的真实换手：调仓前先把上一目标权重按实际收益漂移，再与目标权重比较。"""
    dates = list(weight_df.index)
    r = rets[list(weight_df.columns)]
    idx = r.index
    total_to = 0.0
    prev_date, prev_w = None, None
    for d in dates:
        w_target = weight_df.loc[d].values.astype(float)
        if prev_w is None:
            pre = np.asarray(initial_w, dtype=float)
        else:
            growth = (1.0 + r.loc[(idx > prev_date) & (idx <= d)]).prod().values
            pre = prev_w * growth
            s = pre.sum()
            if s > 0:
                pre = pre / s * max(w_target.sum(), 1e-9)
        total_to += 0.5 * float(np.abs(pre - w_target).sum())
        prev_w, prev_date = w_target, d
    return total_to / ((dates[-1] - dates[0]).days / 365.25)


def quick_reversals(weight_df: pd.DataFrame, rets: pd.DataFrame, days: int = 10) -> int:
    """统计 10 个交易日内又反手回去的调仓次数（假信号/抖动代理指标）。"""
    pos = {d: i for i, d in enumerate(rets.index)}
    idx = list(weight_df.index)
    return sum(1 for k in range(1, len(idx)) if pos[idx[k]] - pos[idx[k - 1]] <= days)


def run_variant(rets, common, rows, key, label, **kw):
    t0 = time.time()
    res = backtest_iv(rets, **common, **kw)
    nv = res.nv.dropna()
    perf = perf_metrics(nv, rets=nv.pct_change().dropna())
    nv70 = adjust_nav_for_cash(nv, 0.30)
    perf70 = perf_metrics(nv70, rets=nv70.pct_change().dropna())
    row = {
        "key": key, "variant": label, "cagr": perf["cagr"], "vol": perf["vol"],
        "mdd": perf["mdd"], "sharpe": perf["sharpe"], "calmar": perf["calmar"],
        "cagr_70": perf70["cagr"], "mdd_70": perf70["mdd"], "sharpe_70": perf70["sharpe"],
        "n_rebal": int(res.n_rebal),
        "annual_turnover": annual_turnover(res.weight_df, rets, initial_w_rows[key]),
        "cost_drag": {k: None for k in FEE_SCENARIOS},
        "seconds": round(time.time() - t0, 1),
    }
    for k, fee in FEE_SCENARIOS.items():
        row["cost_drag"][k] = row["annual_turnover"] * 2 * fee
        row.setdefault("cagr_after_cost", {})[k] = perf["cagr"] - row["cost_drag"][k]
        row.setdefault("cagr_70_after_cost", {})[k] = perf70["cagr"] - row["cost_drag"][k] * 0.7
    row["quick_reversals_10d"] = quick_reversals(res.weight_df, rets)
    rows.append(row)
    return row, nv, res


VARIANTS = [
    ("monthly", "月末基准（当前做法）", {}),
    ("watch1", "每天检查·信号翻转即调", dict(rebal_mode="signal_watch", watch_every=1)),
    ("watch1t1", "每天检查·翻转·T+1执行", dict(rebal_mode="signal_watch", watch_every=1, watch_delay=1)),
    ("watch1full", "每天检查·照单执行(每日全调)", dict(rebal_mode="signal_watch", watch_every=1, watch_full=True)),
    ("watch2", "每2交易日·翻转即调", dict(rebal_mode="signal_watch", watch_every=2)),
    ("watch3", "每3交易日·翻转即调", dict(rebal_mode="signal_watch", watch_every=3)),
    ("watch5", "每5交易日(≈周频)·翻转即调", dict(rebal_mode="signal_watch", watch_every=5)),
    ("watch5full", "每5交易日·照单执行(每周全调)", dict(rebal_mode="signal_watch", watch_every=5, watch_full=True)),
    ("watch1event", "每天检查·纯事件驱动(无月末)", dict(rebal_mode="signal_watch", watch_every=1, watch_keep_month_end=False)),
]

GRID = [1, 2, 3, 5, 8, 10, 15, 21]

initial_w_rows: dict = {}


def main(strategy: str = "v3d"):
    assets, common = build_common(strategy)
    panel = load_panel()
    rets = panel.pct_change().dropna()[assets].dropna()
    start, end = rets.index[0], rets.index[-1]
    years_full = (end - start).days / 365.25
    print(f"策略 {strategy.upper()}  区间 {start.date()} ~ {end.date()}  "
          f"{len(rets)} 交易日 ({years_full:.1f} 年)", flush=True)

    lookback = common["iv_window"]
    init_w = _compute_weights(rets.iloc[:lookback], "inverse_vol", lookback, 0,
                              common["max_w"], common["min_w"], "equal", None).values
    for k, _, _ in VARIANTS:
        initial_w_rows[k] = init_w

    rows, nvs = [], {}
    for key, label, kw in VARIANTS:
        row, nv, _res = run_variant(rets, common, rows, key, label, **kw)
        nvs[key] = nv
        print(f"  ok {label:<26} CAGR {row['cagr']*100:6.2f}%  MDD {row['mdd']*100:7.2f}%  "
              f"调仓/年 {row['n_rebal']/years_full:5.1f}  年换手 {row['annual_turnover']*100:6.1f}%  "
              f"10日内反手 {row['quick_reversals_10d']:4d}  ({row['seconds']}s)", flush=True)

    # ---- 检查间隔网格 ----
    grid_rows = []
    for every in GRID:
        res = backtest_iv(rets, **common, rebal_mode="signal_watch", watch_every=every)
        nv = res.nv.dropna()
        p = perf_metrics(nv, rets=nv.pct_change().dropna())
        grid_rows.append({
            "watch_every": every, "cagr": p["cagr"], "mdd": p["mdd"], "sharpe": p["sharpe"],
            "calmar": p["calmar"], "rebal_per_year": int(res.n_rebal) / years_full,
            "annual_turnover": annual_turnover(res.weight_df, rets, init_w),
            "quick_reversals_10d": quick_reversals(res.weight_df, rets),
        })
    print("\n检查间隔网格（越小=盯得越勤）")
    print(f"{'间隔':>6}{'CAGR':>9}{'MDD':>9}{'Sharpe':>8}{'Calmar':>8}{'调仓/年':>9}{'10日内反手':>11}")
    for g in grid_rows:
        print(f"{g['watch_every']:>6}{g['cagr']*100:8.2f}%{g['mdd']*100:8.2f}%"
              f"{g['sharpe']:8.2f}{g['calmar']:8.2f}{g['rebal_per_year']:9.1f}"
              f"{g['quick_reversals_10d']:>11}")

    # ---- 子样本稳健性 ----
    subperiods = [("前半段", slice(start, f"{start.year+10}-12-31")),
                  ("后半段", slice(f"{start.year+11}", str(end.date()))),
                  ("近5年", slice("2021", str(end.date())))]
    sub_rows = []
    base_nv = nvs["monthly"]
    for name, sl in subperiods:
        b = base_nv.loc[sl]
        if len(b) < 60:
            continue
        line = {"区间": name, "月末基准": perf_metrics(b / b.iloc[0], rets=b.pct_change().dropna())["cagr"]}
        for key in ("watch5", "watch1"):
            s = nvs[key].loc[sl]
            pk = perf_metrics(s / s.iloc[0], rets=s.pct_change().dropna())
            line[f"{key}_cagr"] = pk["cagr"]
            line[f"{key}_diff"] = pk["cagr"] - line["月末基准"]
        sub_rows.append(line)
        print(f"\n{name}: 月末 {line['月末基准']*100:.2f}%  "
              f"每5日 {line['watch5_cagr']*100:.2f}% ({line['watch5_diff']*100:+.2f}pp)  "
              f"每天 {line['watch1_cagr']*100:.2f}% ({line['watch1_diff']*100:+.2f}pp)")

    # ---- 逐年胜率 ----
    yb = yearly_returns(base_nv, rets=base_nv.pct_change().dropna())
    yearly_diff, wins = [], {}
    for key in ("watch5", "watch1"):
        yv = yearly_returns(nvs[key], rets=nvs[key].pct_change().dropna())
        wins[key] = sum(1 for y in yb.index if yv.get(y, np.nan) > yb[y])
        yearly_diff.append({"key": key, "years": {str(y): float(yv.get(y, np.nan) - yb[y]) for y in yb.index},
                            "wins": int(wins[key]), "total": int(len(yb))})
    for w in yearly_diff:
        print(f"\n{w['key']}: {w['wins']}/{w['total']} 个自然年战胜月末基准")

    payload = {
        "strategy": strategy,
        "period": {"start": str(start.date()), "end": str(end.date()), "years": round(years_full, 2)},
        "fee_assumptions": FEE_SCENARIOS,
        "variants": rows,
        "grid": grid_rows,
        "subperiod": sub_rows,
        "yearly_diff": yearly_diff,
    }
    out1 = ROOT / "output" / f"rebal_frequency_watch_{strategy}.json"
    out1.write_text(json.dumps(payload, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    print(f"\n已保存 {out1}")


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "v3d")
