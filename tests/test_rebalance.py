"""实盘权重叠加：抄底必须改权重，不能仪表盘亮了目标不动。"""
import pandas as pd
from allweather.rebalance import apply_signal_overrides


def _sleeve(**kwargs):
    return pd.Series(kwargs, dtype=float)


def test_gold_dip_becomes_2_5x_when_credit_covers():
    # V3c 典型：黄金 12.5%、城投 25%。旧逻辑要 12.5%×2.5=31.25% 城投，整笔跳过。
    w = _sleeve(gold=0.125, credit=0.25, hs300=0.125, bond_30y=0.25, nonferr=0.125, us_sp500=0.125)
    out = apply_signal_overrides("V3c", w, {"gold_dip_active": True})
    assert abs(out["gold"] - 0.3125) < 1e-9
    assert abs(out["credit"] - 0.0625) < 1e-9
    assert abs(out.sum() - 1.0) < 1e-9


def test_gold_dip_uses_remaining_credit_when_short():
    w = _sleeve(gold=0.20, credit=0.10, hs300=0.70)
    out = apply_signal_overrides("V3c", w, {"gold_dip_active": True})
    assert abs(out["gold"] - 0.30) < 1e-9
    assert abs(out["credit"] - 0.0) < 1e-9


def test_gold_dip_keeps_cash_sleeve_sum():
    w = _sleeve(gold=0.0875, credit=0.175, hs300=0.0875, bond_30y=0.175, nonferr=0.0875, us_sp500=0.0875)
    assert abs(w.sum() - 0.7) < 1e-9
    out = apply_signal_overrides("V3c", w, {"gold_dip_active": True})
    assert abs(out.sum() - 0.7) < 1e-9
    assert abs(out["gold"] - 0.0875 * 2.5) < 1e-9
