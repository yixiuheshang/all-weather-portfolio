"""实盘权重叠加测试 — 验证 apply_signal_overrides 与回测权威规则一致。

核心原则：V3c 不再执行黄金抄底（回测已弃用），黄金/WTI 趋势过滤对 V3c 生效，
HS300 抄底仅入场月 ×1.8 且 credit 不足时整笔不加（回测行为）。
"""
import pandas as pd
from allweather.rebalance import apply_signal_overrides


def _sleeve(**kwargs):
    return pd.Series(kwargs, dtype=float)


# ============================================================
# 黄金抄底：V3c 全局弃用（回测口径）
# ============================================================

def test_v3c_gold_dip_disabled_no_boost():
    """V3c 不再执行黄金回撤抄底：gold_dip_active 不改变权重。"""
    w = _sleeve(gold=0.125, credit=0.25, hs300=0.125, bond_30y=0.25,
                nonferr=0.125, us_sp500=0.125, wti=0.0)
    out = apply_signal_overrides("V3c", w, {"gold_dip_active": True})
    assert abs(out["gold"] - 0.125) < 1e-9
    assert abs(out["credit"] - 0.25) < 1e-9


def test_v3c_gold_dip_disabled_sum_unchanged():
    """V3c 黄金抄底弃用后权重合计不变。"""
    w = _sleeve(gold=0.0875, credit=0.175, hs300=0.0875, bond_30y=0.175,
                nonferr=0.0875, us_sp500=0.0875, wti=0.0875)
    total = w.sum()
    out = apply_signal_overrides("V3c", w, {"gold_dip_active": True})
    assert abs(out.sum() - total) < 1e-9
    assert abs(out["gold"] - 0.0875) < 1e-9


# ============================================================
# 黄金趋势过滤：V3c 生效（与回测一致）
# ============================================================

def test_v3c_gold_trend_filter_clears_to_credit():
    """V3c 黄金跌破 SMA75 → 清仓转城投债。"""
    w = _sleeve(gold=0.125, credit=0.25, hs300=0.125, bond_30y=0.25,
                nonferr=0.125, us_sp500=0.125, wti=0.0)
    out = apply_signal_overrides("V3c", w, {"gold_below_sma75": True})
    assert abs(out["gold"]) < 1e-9
    assert abs(out["credit"] - 0.375) < 1e-9
    assert abs(out.sum() - w.sum()) < 1e-9


def test_bcon_gold_trend_filter_not_applied():
    """B-Con 不做黄金趋势过滤（config.STRATEGY_RULES gold_trend_filter=False）。"""
    w = _sleeve(gold=0.10, credit=0.20, hs300=0.10, bond_10y=0.15,
                bond_30y=0.15, nonferr=0.10, us_sp500=0.10, wti=0.10)
    out = apply_signal_overrides("B-Con", w, {"gold_below_sma75": True})
    assert abs(out["gold"] - 0.10) < 1e-9


# ============================================================
# WTI 趋势过滤：所有策略生效
# ============================================================

def test_v3c_wti_trend_filter_clears_to_credit():
    """V3c WTI 跌破 SMA75 → 清仓转城投债。"""
    w = _sleeve(gold=0.125, credit=0.25, hs300=0.125, bond_30y=0.25,
                nonferr=0.125, us_sp500=0.125, wti=0.125)
    out = apply_signal_overrides("V3c", w, {"wti_below_sma75": True})
    assert abs(out["wti"]) < 1e-9
    assert abs(out["credit"] - 0.375) < 1e-9


# ============================================================
# 标普500 趋势过滤
# ============================================================

def test_v3c_sp500_trend_filter_clears_to_credit():
    """V3c 标普500 跌破 SMA75 → 清仓转城投债。"""
    w = _sleeve(gold=0.125, credit=0.25, hs300=0.125, bond_30y=0.25,
                nonferr=0.125, us_sp500=0.125, wti=0.125)
    out = apply_signal_overrides("V3c", w, {"sp500_below_sma75": True})
    assert abs(out["us_sp500"]) < 1e-9
    assert abs(out["credit"] - 0.375) < 1e-9


# ============================================================
# 有色金属趋势过滤
# ============================================================

def test_v3c_nonferr_trend_filter_clears_to_credit():
    """V3c 有色跌破 SMA75 → 清仓转城投债。"""
    w = _sleeve(gold=0.125, credit=0.25, hs300=0.125, bond_30y=0.25,
                nonferr=0.125, us_sp500=0.125, wti=0.125)
    out = apply_signal_overrides("V3c", w, {"nonferr_below_sma75": True})
    assert abs(out["nonferr"]) < 1e-9
    assert abs(out["credit"] - 0.375) < 1e-9


# ============================================================
# HS300 AND 抄底：状态机，仅入场月 ×1.8
# ============================================================

def test_v3c_hs300_dip_entry_boosts_1_8x():
    """HS300 抄底入场月 → 权重 ×1.8，从 credit 筹资。"""
    w = _sleeve(hs300=0.125, credit=0.25, gold=0.125, bond_30y=0.25,
                nonferr=0.125, us_sp500=0.125, wti=0.0)
    out = apply_signal_overrides("V3c", w, {"hs300_dip_entry": True})
    assert abs(out["hs300"] - 0.125 * 1.8) < 1e-9
    assert abs(out["credit"] - (0.25 - 0.125 * 0.8)) < 1e-9


def test_v3c_hs300_dip_holding_no_boost():
    """HS300 抄底持有中（非入场月）→ 不再加仓。"""
    w = _sleeve(hs300=0.125, credit=0.25, gold=0.125, bond_30y=0.25,
                nonferr=0.125, us_sp500=0.125, wti=0.0)
    out = apply_signal_overrides("V3c", w, {"hs300_dip_active": True})
    assert abs(out["hs300"] - 0.125) < 1e-9


def test_v3c_hs300_dip_entry_credit_insufficient_no_partial():
    """HS300 抄底入场但 credit 不足 → 整笔不加（回测行为，不做部分加仓）。"""
    w = _sleeve(hs300=0.20, credit=0.05, gold=0.10, bond_30y=0.10,
                nonferr=0.10, us_sp500=0.10, wti=0.0)
    out = apply_signal_overrides("V3c", w, {"hs300_dip_entry": True})
    # 需要 0.20*0.8=0.16，credit 只有 0.05 → 不加
    assert abs(out["hs300"] - 0.20) < 1e-9
    assert abs(out["credit"] - 0.05) < 1e-9


# ============================================================
# 多信号叠加：顺序与回测一致
# ============================================================

def test_v3c_multi_signal_nonferr_and_gold_and_sp500():
    """多个趋势过滤同时触发 → 各自清仓转 credit，合计守恒。"""
    w = _sleeve(gold=0.125, credit=0.25, hs300=0.125, bond_30y=0.25,
                nonferr=0.125, us_sp500=0.125, wti=0.125)
    total_before = w.sum()
    out = apply_signal_overrides("V3c", w, {
        "nonferr_below_sma75": True,
        "gold_below_sma75": True,
        "sp500_below_sma75": True,
        "wti_below_sma75": True,
    })
    assert abs(out["nonferr"]) < 1e-9
    assert abs(out["gold"]) < 1e-9
    assert abs(out["us_sp500"]) < 1e-9
    assert abs(out["wti"]) < 1e-9
    assert abs(out["credit"] - (0.25 + 0.125 * 4)) < 1e-9
    assert abs(out.sum() - total_before) < 1e-9


def test_v3c_trend_then_dip_credit_reflects_prior_clears():
    """趋势过滤先清仓转 credit，再判断 HS300 抄底筹资（顺序与回测一致）。"""
    w = _sleeve(hs300=0.125, credit=0.10, gold=0.125, bond_30y=0.25,
                nonferr=0.125, us_sp500=0.125, wti=0.125)
    # nonferr/gold/sp500/wti 全部清仓 → credit 收到 0.50
    # 再 HS300 抄底入场：需 0.125*0.8=0.10，credit 有 0.60 足够
    out = apply_signal_overrides("V3c", w, {
        "nonferr_below_sma75": True,
        "gold_below_sma75": True,
        "sp500_below_sma75": True,
        "wti_below_sma75": True,
        "hs300_dip_entry": True,
    })
    assert abs(out["hs300"] - 0.125 * 1.8) < 1e-9
    assert abs(out["credit"] - (0.10 + 0.50 - 0.10)) < 1e-9


# ============================================================
# 权重合计守恒（无信号时）
# ============================================================

def test_v3c_no_signals_unchanged():
    """无任何信号触发 → 权重不变。"""
    w = _sleeve(gold=0.125, credit=0.25, hs300=0.125, bond_30y=0.25,
                nonferr=0.125, us_sp500=0.125, wti=0.0)
    out = apply_signal_overrides("V3c", w, {})
    assert abs(out - w).max() < 1e-9
