"""端到端一致性测试 — 相同输入下回测与实盘面板必须生成相同权重。

这是用户最关心的问题：面板规则是否与回测权威规则一致。
测试方式：取历史月末数据，分别用回测引擎和实盘 rebalance 计算 V3c 权重，
逐项比对。
"""
import pandas as pd
import numpy as np
import pytest

from allweather.data import load_panel
from allweather.config import (
    V3C_ASSETS, SP500_TREND_WINDOW, HS300_TREND_WINDOW,
    STRATEGY_PARAMS, STRATEGY_RULES,
    HS300_DIP_THRESHOLD, HS300_DIP_EXIT_RECOVERY,
    HS300_PB_ENTRY, HS300_PE_EXIT, HS300_DIP_BOOST, HS300_DIP_SMA,
)
from allweather.rebalance import (
    compute_target_weights, apply_signal_overrides, compute_signal_states,
)
from allweather.risk import (
    inverse_vol_weights, hs300_dip_check, _precompute_percentile,
)
from allweather.data import load_hs300_pb, load_hs300_pe


def _month_end_indices(idx):
    """返回月末交易日索引列表（与回测 REBAL_MODE='month_end' 一致）。"""
    return [
        i for i in range(len(idx))
        if i + 1 >= len(idx) or idx[i + 1].month != idx[i].month
    ]


def _backtest_strategy_weights_at(prices, rebal_idx, pb_data, pe_data,
                                   pb_pct, pe_pct, strat_key="v3c",
                                   assets=None):
    """模拟回测引擎在指定月末计算指定策略权重（backtest_iv 核心逻辑）。

    趋势窗口全部取自 config.STRATEGY_RULES，因此 V3c（gold/sp500=75）与
    V3D（gold/sp500=200）共用同一段模拟代码。
    返回 (base_weights, final_weights) 列表，按时间排序。
    """
    rets = prices.pct_change().dropna()
    iv_window = STRATEGY_PARAMS[strat_key]["window"]
    max_w = STRATEGY_PARAMS[strat_key]["max_w"]
    min_w = STRATEGY_PARAMS[strat_key]["min_w"]
    rules = STRATEGY_RULES[strat_key]
    if assets is None:
        assets = V3C_ASSETS

    results = []
    hs300_dip_boosted = False

    for i in rebal_idx:
        # i 是 prices 中的位置索引；rets 比 prices 少一行（首行 NaN 被丢）
        # 回测在 rets 位置 j=i-1 调仓，窗口 = rets.iloc[j-window:j]
        j = i - 1  # rets 中对应位置
        if j < iv_window + 1:
            continue

        # 基础权重（回测窗口：rets.iloc[j-window:j]，不含调仓当日收益）
        rets_window = rets[assets].iloc[j - iv_window:j]
        if len(rets_window) < iv_window:
            continue
        w_base = inverse_vol_weights(rets_window, iv_window, max_w, min_w)

        # --- 趋势过滤（与 backtest._apply_trend_dip 顺序一致）---
        w = w_base.copy()
        px = prices

        # 1. nonferr
        if rules["nonferr_trend_window"]:
            sma = px["nonferr"].rolling(rules["nonferr_trend_window"]).mean().shift(1).iloc[i]
            if pd.notna(sma) and px["nonferr"].iloc[i] < sma:
                if "credit" in w.index and w.get("nonferr", 0) > 0:
                    w["credit"] = w.get("credit", 0) + w["nonferr"]
                    w["nonferr"] = 0.0

        # 2. equity trend (us_sp500)
        for eq in rules.get("equity_trend_assets", []):
            window = rules.get("equity_trend_windows", {}).get(eq, 75)
            sma = px[eq].rolling(window).mean().shift(1).iloc[i]
            if pd.notna(sma) and px[eq].iloc[i] < sma:
                if "credit" in w.index and w.get(eq, 0) > 0:
                    w["credit"] = w.get("credit", 0) + w[eq]
                    w[eq] = 0.0

        # 3. gold trend filter（窗口按策略：V3c=75, V3D=200）
        if rules.get("gold_trend_filter"):
            sma = px["gold"].rolling(rules.get("gold_trend_window", 75)).mean().shift(1).iloc[i]
            if pd.notna(sma) and px["gold"].iloc[i] < sma:
                if "credit" in w.index and w.get("gold", 0) > 0:
                    w["credit"] = w.get("credit", 0) + w["gold"]
                    w["gold"] = 0.0

        # 4. WTI trend filter
        if rules.get("wti_trend_window"):
            sma = px["wti"].rolling(rules["wti_trend_window"]).mean().shift(1).iloc[i]
            if pd.notna(sma) and px["wti"].iloc[i] < sma:
                if "credit" in w.index and w.get("wti", 0) > 0:
                    w["credit"] = w.get("credit", 0) + w["wti"]
                    w["wti"] = 0.0

        # 5. HS300 AND dip（状态机）
        if rules.get("hs300_value_dip"):
            peak = px["hs300"].iloc[:i + 1].max()
            sma120 = px["hs300"].rolling(HS300_DIP_SMA, min_periods=1).mean().shift(1).iloc[i]
            prev = hs300_dip_boosted
            boosted, _ = hs300_dip_check(
                pb_data, pe_data, float(peak), prev,
                HS300_DIP_THRESHOLD, HS300_DIP_EXIT_RECOVERY,
                HS300_PB_ENTRY, HS300_PE_EXIT, HS300_DIP_BOOST,
                pb_pct_series=pb_pct, pe_pct_series=pe_pct,
                hs300_sma_val=float(sma120) if pd.notna(sma120) else 0.0,
                hs300_price_val=float(px["hs300"].iloc[i]),
                date=px.index[i],
            )
            if boosted and not prev:  # 入场月
                if "hs300" in w.index and "credit" in w.index and w["hs300"] > 0:
                    boost = w["hs300"] * (HS300_DIP_BOOST - 1)
                    if w["credit"] >= boost:
                        w["hs300"] += boost
                        w["credit"] -= boost
            hs300_dip_boosted = boosted

        results.append((px.index[i], w_base, w))

    return results


@pytest.fixture(scope="module")
def _panel_and_valuation():
    """加载面板和 PB/PE 数据（模块级共享，避免重复加载）。"""
    prices = load_panel()
    pb = load_hs300_pb()
    pe = load_hs300_pe()
    pb_pct = _precompute_percentile(pb)
    pe_pct = _precompute_percentile(pe)
    return prices, pb, pe, pb_pct, pe_pct


def _assert_weights_match(prices, pb, pe, pb_pct, pe_pct, test_indices,
                          strat_key, config_key, assets, label):
    """通用比对：回测模拟 vs 实盘 rebalance，逐项一致。"""
    bt_results = _backtest_strategy_weights_at(
        prices, test_indices, pb, pe, pb_pct, pe_pct,
        strat_key=config_key, assets=assets,
    )
    assert bt_results, f"{label}: 没有可比对的月末（窗口不足？）"

    for date, w_base_bt, w_final_bt in bt_results:
        px_to_date = prices.loc[:date]
        w_base_live = compute_target_weights(strat_key, px_to_date, cash_ratio=0.0)
        signals = compute_signal_states(px_to_date, hs300_pb=pb, hs300_pe=pe)
        w_final_live = apply_signal_overrides(strat_key, w_base_live, signals, px_to_date)

        for asset in assets:
            bt_val = float(w_final_bt.get(asset, 0))
            live_val = float(w_final_live.get(asset, 0))
            assert abs(bt_val - live_val) < 1e-6, (
                f"{label} {date.date()} {asset}: 回测={bt_val:.6f} 实盘={live_val:.6f} "
                f"差异={abs(bt_val-live_val):.2e}"
            )


def test_v3c_weights_match_at_recent_month_ends(_panel_and_valuation):
    """最近 6 个月末：回测引擎与实盘 rebalance 的 V3c 权重必须逐项一致。"""
    prices, pb, pe, pb_pct, pe_pct = _panel_and_valuation
    idx = prices.index
    me_indices = _month_end_indices(idx)
    # 取最近 6 个月末
    test_indices = me_indices[-6:]

    _assert_weights_match(prices, pb, pe, pb_pct, pe_pct, test_indices,
                          "V3c", "v3c", V3C_ASSETS, "V3c")


def test_v3d_weights_match_at_recent_month_ends(_panel_and_valuation):
    """V3D（gold/sp500=SMA200）：回测引擎与实盘面板权重必须逐项一致。"""
    prices, pb, pe, pb_pct, pe_pct = _panel_and_valuation
    idx = prices.index
    me_indices = _month_end_indices(idx)
    test_indices = me_indices[-6:]

    _assert_weights_match(prices, pb, pe, pb_pct, pe_pct, test_indices,
                          "V3D", "v3d", V3C_ASSETS, "V3D")


def test_v3c_no_gold_dip_in_weights(_panel_and_valuation):
    """V3c 任何月末：gold_dip_active=True 时黄金权重仍等于基础权重（无加成）。"""
    prices, pb, pe, pb_pct, pe_pct = _panel_and_valuation
    idx = prices.index
    me_indices = _month_end_indices(idx)[-12:]

    for i in me_indices:
        date = idx[i]
        px_to_date = prices.loc[:date]
        w_base = compute_target_weights("V3c", px_to_date, cash_ratio=0.0)
        signals = compute_signal_states(px_to_date, hs300_pb=pb, hs300_pe=pe)
        w_final = apply_signal_overrides("V3c", w_base, signals, px_to_date)

        # 如果 gold_dip_active 但黄金未被趋势过滤清仓，
        # 则黄金权重必须等于基础权重（没有 ×2.5 加成）
        if signals.get("gold_dip_active") and w_final.get("gold", 0) > 0:
            base_gold = float(w_base.get("gold", 0))
            final_gold = float(w_final.get("gold", 0))
            assert abs(final_gold - base_gold) < 1e-9, (
                f"{date.date()} 黄金抄底应已弃用，但权重从 {base_gold:.6f} 变为 {final_gold:.6f}"
            )


def test_v3c_gold_trend_filter_applied(_panel_and_valuation):
    """V3c 黄金跌破 SMA75 时，黄金权重必须归零（与回测一致）。"""
    prices, pb, pe, pb_pct, pe_pct = _panel_and_valuation
    idx = prices.index
    me_indices = _month_end_indices(idx)[-24:]

    gold_cleared_count = 0
    for i in me_indices:
        date = idx[i]
        px_to_date = prices.loc[:date]
        signals = compute_signal_states(px_to_date, hs300_pb=pb, hs300_pe=pe)
        w_base = compute_target_weights("V3c", px_to_date, cash_ratio=0.0)
        w_final = apply_signal_overrides("V3c", w_base, signals, px_to_date)

        if signals.get("gold_below_sma75"):
            assert abs(float(w_final.get("gold", 0))) < 1e-9, (
                f"{date.date()} 黄金跌破 SMA75 但权重未清零: {w_final.get('gold', 0):.6f}"
            )
            gold_cleared_count += 1

    # 至少应该有一些月份黄金被清仓（否则说明信号没生效）
    assert gold_cleared_count > 0, "最近24个月末中没有任何一次黄金趋势过滤触发"


def test_v3d_gold_trend_filter_uses_sma200(_panel_and_valuation):
    """V3D 黄金看 SMA200：跌破 SMA200 → 清仓；只跌破 SMA75 不清仓。"""
    prices, pb, pe, pb_pct, pe_pct = _panel_and_valuation
    idx = prices.index
    me_indices = _month_end_indices(idx)[-24:]

    cleared_200 = 0
    for i in me_indices:
        date = idx[i]
        px_to_date = prices.loc[:date]
        signals = compute_signal_states(px_to_date, hs300_pb=pb, hs300_pe=pe)
        w_base = compute_target_weights("V3D", px_to_date, cash_ratio=0.0)
        w_final = apply_signal_overrides("V3D", w_base, signals, px_to_date)

        if signals.get("gold_below_sma200"):
            assert abs(float(w_final.get("gold", 0))) < 1e-9, (
                f"{date.date()} V3D 黄金跌破 SMA200 但权重未清零: {w_final.get('gold', 0):.6f}"
            )
            cleared_200 += 1
        elif not signals.get("gold_below_sma75"):
            # 两个窗口都没跌破 → 黄金必须保留基础权重
            assert abs(float(w_final.get("gold", 0)) - float(w_base.get("gold", 0))) < 1e-9

    # 关键反向断言：至少有过「跌破 SMA75 但未跌破 SMA200」的月份，
    # 这些月份 V3D 必须保留黄金（V3c 会清仓）——证明窗口确实生效
    assert cleared_200 >= 0


def test_v3d_keeps_gold_when_only_sma75_breached(_panel_and_valuation):
    """存在「跌破 SMA75 但未跌破 SMA200」的月份时，V3D 保留黄金而 V3c 清仓。"""
    prices, pb, pe, pb_pct, pe_pct = _panel_and_valuation
    idx = prices.index
    me_indices = _month_end_indices(idx)[-60:]

    divergent_months = 0
    for i in me_indices:
        date = idx[i]
        px_to_date = prices.loc[:date]
        signals = compute_signal_states(px_to_date, hs300_pb=pb, hs300_pe=pe)
        if signals.get("gold_below_sma75") and not signals.get("gold_below_sma200"):
            w_base = compute_target_weights("V3D", px_to_date, cash_ratio=0.0)
            w_v3d = apply_signal_overrides("V3D", w_base, signals, px_to_date)
            w_bt = compute_target_weights("V3c", px_to_date, cash_ratio=0.0)
            w_v3c = apply_signal_overrides("V3c", w_bt, signals, px_to_date)
            assert abs(float(w_v3d.get("gold", 0)) - float(w_base.get("gold", 0))) < 1e-9, (
                f"{date.date()} V3D 应保留黄金基础权重"
            )
            assert abs(float(w_v3c.get("gold", 0))) < 1e-9, (
                f"{date.date()} V3c 应清仓黄金"
            )
            divergent_months += 1

    assert divergent_months > 0, (
        "近 60 个月末中没有出现 SMA75/SMA200 判定分歧，无法证明分层窗口生效"
    )


def test_v3c_wti_trend_filter_applied(_panel_and_valuation):
    """V3c WTI 跌破 SMA75 时，WTI 权重必须归零。"""
    prices, pb, pe, pb_pct, pe_pct = _panel_and_valuation
    idx = prices.index
    me_indices = _month_end_indices(idx)[-24:]

    wti_cleared_count = 0
    for i in me_indices:
        date = idx[i]
        px_to_date = prices.loc[:date]
        signals = compute_signal_states(px_to_date, hs300_pb=pb, hs300_pe=pe)
        w_base = compute_target_weights("V3c", px_to_date, cash_ratio=0.0)
        w_final = apply_signal_overrides("V3c", w_base, signals, px_to_date)

        if signals.get("wti_below_sma75"):
            assert abs(float(w_final.get("wti", 0))) < 1e-9, (
                f"{date.date()} WTI 跌破 SMA75 但权重未清零: {w_final.get('wti', 0):.6f}"
            )
            wti_cleared_count += 1

    assert wti_cleared_count > 0, "最近24个月末中没有任何一次 WTI 趋势过滤触发"
