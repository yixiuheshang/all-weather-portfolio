"""再平衡调仓工具 — Streamlit Web 界面.

用法: streamlit run streamlit_app/app.py
"""
import sys
import json
import math
from pathlib import Path
from datetime import date

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

import streamlit as st

st.set_page_config(
    page_title="全天候再平衡",
    page_icon="🌤️",
    layout="wide",
    initial_sidebar_state="expanded",
)

if "auto_fetch_done" not in st.session_state:
    st.session_state.auto_fetch_done = False

_LOADING = not st.session_state.auto_fetch_done
if _LOADING:
    st.title("🌤️ 全天候再平衡")
    st.caption("正在准备行情与信号，请稍候，不要关闭窗口。")
    _boot_bar = st.progress(0, text="加载模块…")
    _boot_step = st.empty()

import pandas as pd
import numpy as np

from allweather.rebalance import (
    compute_signal_states,
    compute_target_weights,
    apply_signal_overrides,
    STRATEGIES,
    ETF_META,
)
from allweather.fetch import load_market_px_panel, fetch_market_prices
from allweather.data import load_live_panel, clear_series_cache
from allweather.config import (
    DATA_DIR,
    STRATEGY_RULES,
    HS300_DIP_THRESHOLD,
    HS300_DIP_BOOST,
    HS300_DIP_SMA,
    HS300_PB_ENTRY,
    HS300_PE_EXIT,
    HS300_TREND_WINDOW,
    SP500_TREND_WINDOW,
)

# ============================================================
# 持仓记忆（跨会话持久化，data/holdings.json）
# ============================================================
HOLDINGS_FILE = DATA_DIR / "holdings.json"
MF_ASSET = "mf_511880"
MF_NAME = "货币 ETF（华宝添益）"
MF_CODE = "511880"


def _load_saved_state():
    try:
        data = json.loads(HOLDINGS_FILE.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def _save_state(payload):
    HOLDINGS_FILE.parent.mkdir(parents=True, exist_ok=True)
    HOLDINGS_FILE.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
    )


_saved_state = _load_saved_state()

st.markdown("""<style>
[role="tab"] { color: #a0a8c0 !important; }
[role="tab"][aria-selected="true"] { color: #ff4b4b !important; font-weight: 600; }
@media (prefers-color-scheme: light) {
  [role="tab"] { color: #555 !important; }
}
[data-testid="stDeployButton"] { display: none; }
[data-testid="stDecoration"] { display: none; }
#MainMenu { visibility: hidden; }
header [data-testid="stToolbar"] { display: none; }
/* 不能隐藏整个 header：折叠按钮在里面，藏掉后侧栏再也打不开 */
[data-testid="collapsedControl"] {
  display: flex !important;
  visibility: visible !important;
  z-index: 1000000 !important;
}
</style>""", unsafe_allow_html=True)

# ============================================================
# 信号 → 操作 映射表（与回测权威规则 config.STRATEGY_RULES 一致）
# ============================================================
_nf = f"{ETF_META['nonferr']['name']} ({ETF_META['nonferr']['code']})"
_au = f"{ETF_META['gold']['name']} ({ETF_META['gold']['code']})"
_hs = f"{ETF_META['hs300']['name']} ({ETF_META['hs300']['code']})"
_sp = f"{ETF_META['us_sp500']['name']} ({ETF_META['us_sp500']['code']})"
_cr = f"{ETF_META['credit']['name']} ({ETF_META['credit']['code']})"
_wt = f"{ETF_META['wti']['name']} ({ETF_META['wti']['code']})"

SIGNAL_ACTIONS = [
    {
        "key": "nonferr_below_sma75",
        "desc": f"{_nf} 跌破 SMA75",
        "condition": lambda s: s.get("nonferr_below_sma75", False),
        "sell": _nf,
        "buy": _cr,
        "strategies": ["B-Con", "B-RP", "V3c", "V3D"],
        "type": "趋势过滤",
    },
    {
        "key": "gold_below_sma75",
        "desc": f"{_au} 跌破 SMA75",
        "condition": lambda s: s.get("gold_below_sma75", False),
        "sell": _au,
        "buy": _cr,
        "strategies": ["B-RP", "V3c"],
        "type": "趋势过滤",
    },
    {
        "key": "gold_below_sma200",
        "desc": f"{_au} 跌破 SMA200（V3D 专用慢过滤）",
        "condition": lambda s: s.get("gold_below_sma200", False),
        "sell": _au,
        "buy": _cr,
        "strategies": ["V3D"],
        "type": "趋势过滤",
    },
    {
        "key": "wti_below_sma75",
        "desc": f"{_wt} 跌破 SMA75",
        "condition": lambda s: s.get("wti_below_sma75", False),
        "sell": _wt,
        "buy": _cr,
        "strategies": ["B-Con", "B-RP", "V3c", "V3D"],
        "type": "趋势过滤",
    },
    {
        "key": "sp500_below_sma75",
        "desc": f"{_sp} 跌破 SMA{SP500_TREND_WINDOW}",
        "condition": lambda s: s.get("sp500_below_sma75", False),
        "sell": _sp,
        "buy": _cr,
        "strategies": ["B-RP", "V3c"],
        "type": "趋势过滤",
    },
    {
        "key": "sp500_below_sma200",
        "desc": f"{_sp} 跌破 SMA200（V3D 专用慢过滤）",
        "condition": lambda s: s.get("sp500_below_sma200", False),
        "sell": _sp,
        "buy": _cr,
        "strategies": ["V3D"],
        "type": "趋势过滤",
    },
    {
        "key": "hs300_below_sma30",
        "desc": f"{_hs} 跌破 SMA{HS300_TREND_WINDOW}（仅 B-RP）",
        "condition": lambda s: s.get("hs300_below_sma30", False),
        "sell": _hs,
        "buy": _cr,
        "strategies": ["B-RP"],
        "type": "趋势过滤",
    },
    {
        "key": "hs300_dip_entry",
        "desc": f"HS300 AND 抄底入场：回撤>{HS300_DIP_THRESHOLD:.0%} + PB<{HS300_PB_ENTRY}%ile + 价>SMA{HS300_DIP_SMA}",
        "condition": lambda s: s.get("hs300_dip_entry", False),
        "sell": f"{_cr}（筹资）",
        "buy": f"{_hs} ×{HS300_DIP_BOOST:.1f}（仅入场月）",
        "strategies": ["B-Con", "B-RP", "V3c", "V3D"],
        "type": "抄底加仓（状态机）",
    },
    {
        "key": "hs300_dip_active",
        "desc": "HS300 AND 抄底持有中（已入场，尚未满足退出条件）",
        "condition": lambda s: s.get("hs300_dip_active", False) and not s.get("hs300_dip_entry", False),
        "sell": "—",
        "buy": "—（维持基础权重，不重复加仓）",
        "strategies": ["B-Con", "B-RP", "V3c", "V3D"],
        "type": "抄底持有",
    },
    {
        "key": "hs300_dip_exit",
        "desc": f"HS300 AND 抄底退出：回撤收窄至 {0.15:.0%} 以内 且 PE>{HS300_PE_EXIT}%ile",
        "condition": lambda s: s.get("hs300_dip_exit", False),
        "sell": f"{_hs} 恢复基础权重",
        "buy": _cr,
        "strategies": ["B-Con", "B-RP", "V3c", "V3D"],
        "type": "抄底退出",
    },
]

# ============================================================
# 数据新鲜度
# ============================================================
ASSETS_TO_CHECK = ["hs300", "us_sp500", "bond_credit", "bond_10y_etf", "bond_30y_etf", "gold", "nonferr", "wti"]


def _trading_days_ago(last_date, today):
    """估算交易日间隔（日历天 - 周末天数）。"""
    cal_days = (today - last_date).days
    weeks = cal_days // 7
    extra = min(cal_days % 7, 2)
    return max(1, cal_days - weeks * 2 - extra)

def _check_data_staleness():
    """返回 (最旧交易日数, 最旧资产名) 若无数据则返回 (None, None)。"""
    results = []
    now = pd.Timestamp.now().date()
    for name in ASSETS_TO_CHECK:
        fp = DATA_DIR / f"{name}.csv"
        if not fp.exists():
            return None, None
        try:
            df = pd.read_csv(fp, parse_dates=["date"])
            last_date = df["date"].max().date()
            results.append((name, _trading_days_ago(last_date, now)))
        except Exception:
            return None, None
    if not results:
        return None, None
    oldest = max(results, key=lambda x: x[1])
    return oldest[1], oldest[0]


# ============================================================
# Sidebar
# ============================================================
st.sidebar.title("🌤️ 全天候再平衡")
st.sidebar.caption("策略和现金档位在主页面顶部切换。")

# 自动拉取：净值超过 1 个交易日则增量更新；场内收盘价每次会话都刷新
staleness_days, staleness_asset = _check_data_staleness()

if _LOADING:
    def _boot_progress(done, total, msg):
        frac = (done / total) if total else 1.0
        _boot_bar.progress(min(frac, 1.0), text=msg)
        _boot_step.caption(msg)

    _boot_progress(0, 8, "检查本地数据…")
    from allweather.fetch import fetch_all
    today_str = date.today().strftime("%Y%m%d")
    if staleness_days is not None and staleness_days > 1:
        _boot_bar.progress(0.08, text="净值超过 1 个交易日，增量更新…")
        fetch_all(
            force=False,
            end=today_str,
            on_progress=lambda d, t, m: _boot_progress(d, t, f"更新行情：{m}"),
        )
    else:
        fetch_market_prices(
            force=False,
            on_progress=lambda d, t, m: _boot_progress(d, t, f"场内收盘：{m}"),
        )
    clear_series_cache()  # CSV 已更新，必须清缓存再读
    _boot_bar.progress(1.0, text="启动完成")
    st.session_state.auto_fetch_done = True
    st.cache_data.clear()
    st.rerun()

if staleness_days is not None:
    if staleness_days > 7:
        st.sidebar.warning(f"数据 {staleness_days} 天未更新")
    else:
        st.sidebar.success(f"数据新鲜（滞后 {staleness_days} 个交易日）")
else:
    st.sidebar.error("数据缺失")

if st.sidebar.button("🔄 拉取最新数据"):
    with st.sidebar:
        bar = st.progress(0, text="开始拉取…")
        def _sb_progress(done, total, msg):
            frac = (done / total) if total else 1.0
            bar.progress(min(frac, 1.0), text=msg)
        from allweather.fetch import fetch_all
        today_str = date.today().strftime("%Y%m%d")
        fetch_all(force=False, end=today_str, on_progress=_sb_progress)
        bar.progress(1.0, text="完成")
    st.session_state.auto_fetch_done = True
    st.cache_data.clear()
    st.rerun()

# ============================================================
# 数据加载（与回测同口径的延长面板，不截断到 BACKTEST_END）
# ============================================================
def _load_live_prices():
    """信号/权重用回测口径延长序列（指数缝合+汇率换算+30Y合成）。

    下单股数仍用场内未复权收盘价（load_market_px_panel），
    两者必须分开：不能用累计净值下错单，也不能用 ETF 公共
    历史算信号（会截断到 2024-03，破坏 SMA75/120 与状态回放）。
    """
    return load_live_panel()


@st.cache_data(ttl=300, show_spinner=False)
def _load_prices_and_signals():
    prices = _load_live_prices()
    signals = compute_signal_states(prices)
    market_px = load_market_px_panel()
    return prices, signals, market_px


prices, signals, market_px = _load_prices_and_signals()

last_date = prices.index[-1].strftime("%Y-%m-%d")
st.sidebar.caption(f"净值截止: {last_date}")
if market_px is not None and not market_px.empty:
    px_date = market_px.dropna(how="all").index.max().strftime("%Y-%m-%d")
    st.sidebar.caption(f"场内收盘: {px_date}")
else:
    px_date = None
    st.sidebar.error("缺少场内收盘价，建仓/调仓股数不可用")

# ============================================================
# 主区：策略切换（不放侧栏，避免折叠后找不到）
# ============================================================
_strat_display = {"B-Con": "V3-B 保守增强", "B-RP": "V3-B 风险平价", "V3c": "V3c 多元", "V3D": "V3D 混合窗口"}
_strat_order = ["B-Con", "B-RP", "V3c", "V3D"]
# 各策略的 gold / sp500 趋势窗口（回测与面板共用 config.STRATEGY_RULES，单一事实源）
_STRAT_CONFIG_KEY = {"B-Con": "con", "B-RP": "rp", "V3c": "v3c", "V3D": "v3d"}


def _strat_windows(strat_key):
    """返回该策略的 gold / sp500 趋势窗口（None 表示该策略不做该过滤）。"""
    rules = STRATEGY_RULES[_STRAT_CONFIG_KEY[strat_key]]
    gold_w = rules.get("gold_trend_window") if rules.get("gold_trend_filter") else None
    eq_windows = rules.get("equity_trend_windows") or {}
    sp500_w = eq_windows.get("us_sp500") if "us_sp500" in (rules.get("equity_trend_assets") or []) else None
    return gold_w, sp500_w
_tier_order = ["100", "85", "70"]
_def_strat = _saved_state.get("strat", "V3c")
_def_tier = _saved_state.get("tier", "70")
_sel1, _sel2 = st.columns(2)
with _sel1:
    strat_key = st.radio(
        "策略",
        _strat_order,
        format_func=lambda k: _strat_display[k],
        horizontal=True,
        key="strat_key",
        index=_strat_order.index(_def_strat) if _def_strat in _strat_order else 2,
    )
with _sel2:
    tier = st.radio(
        "现金档位",
        _tier_order,
        format_func=lambda t: f"{t}% RP",
        horizontal=True,
        key="tier",
        index=_tier_order.index(_def_tier) if _def_tier in _tier_order else 2,
    )

cash_ratio = 1 - int(tier) / 100

# 方案选择即时记忆：策略 / 档位一改就落盘，关掉窗口下次启动仍是这一档
if _saved_state.get("strat") != strat_key or _saved_state.get("tier") != tier:
    _auto_state = {**_saved_state, "strat": strat_key, "tier": tier}
    try:
        _save_state(_auto_state)
        _saved_state = _auto_state
    except Exception:
        pass  # 记忆失败不该影响面板正常使用
st.caption(f"当前方案 **{_strat_display[strat_key]} · {tier}% RP** 已记住，下次打开自动选中。")

missing = [a for a in STRATEGIES[strat_key]["assets"] if a not in prices.columns]
if missing:
    st.error(f"缺少数据: {missing}")
    st.stop()

# ============================================================
# 计算权重
# ============================================================
w0 = compute_target_weights(strat_key, prices, cash_ratio)
w = apply_signal_overrides(strat_key, w0, signals, prices)
cfg = STRATEGIES[strat_key]

if market_px is not None and not market_px.empty:
    latest_px = market_px.iloc[-1]
    px_rows = []
    for a in cfg["assets"]:
        meta = ETF_META.get(a, {"code": "", "name": a})
        val = latest_px.get(a, float("nan"))
        px_rows.append({
            "代码": meta["code"],
            "场内收盘": f"{val:.3f}" if pd.notna(val) else "—",
        })
    mf_val = latest_px.get(MF_ASSET, float("nan"))
    px_rows.append({
        "代码": MF_CODE,
        "场内收盘": f"{mf_val:.3f}" if pd.notna(mf_val) else "—",
    })
    st.sidebar.dataframe(pd.DataFrame(px_rows), width="stretch", hide_index=True)
    st.sidebar.caption("下单请用场内收盘，勿用累计净值")

tab1, tab2, tab3, tab4 = st.tabs(
    ["📊 信号仪表盘", "📋 目标权重", "🏗️ 建仓清单", "🔄 调仓清单"]
)

# ============================================================
# Tab 1: 信号仪表盘
# ============================================================
with tab1:
    st.caption("信号与权重用累计净值（与回测一致）。顶部切换策略；左侧场内收盘用于下单。")
    triggered = []
    calm = []
    not_applicable = []

    for sa in SIGNAL_ACTIONS:
        active = sa["condition"](signals)
        applies = strat_key in sa["strategies"]
        if active and applies:
            triggered.append(sa)
        elif not applies:
            not_applicable.append(sa)
        else:
            calm.append(sa)

    if triggered:
        st.subheader("⚠️ 已触发信号")
        st.caption(
            "这些信号已经写进「目标权重」——趋势过滤=清仓转城投债，"
            "HS300 抄底=入场月×1.8。请直接买表里的百分比，不要再乘一遍。"
        )
        for sa in triggered:
            with st.container(border=True):
                cols = st.columns([2, 1, 1])
                with cols[0]:
                    st.markdown(f"### {sa['desc']}")
                    st.caption(sa["type"])
                with cols[1]:
                    st.markdown(f"**卖出**\n\n{sa['sell']}")
                with cols[2]:
                    st.markdown(f"**买入**\n\n{sa['buy']}")
    else:
        st.success("当前无触发信号，所有资产正常配置")

    with st.expander(f"未触发信号（{len(calm)} 项，适用本策略）"):
        for sa in calm:
            st.text(f"✅ {sa['desc']}")

    with st.expander(f"不适用本策略（{len(not_applicable)} 项）"):
        for sa in not_applicable:
            st.text(f"⚪ {sa['desc']}")

    st.divider()
    st.subheader("估值分位")
    pb_col, pe_col = st.columns(2)
    with pb_col:
        pb_pct = signals.get("pb_pctile")
        if pb_pct is not None:
            st.metric("PB 分位", f"{pb_pct:.0f}%ile",
                      delta="便宜" if signals.get("pb_entry_ok") else "偏贵",
                      delta_color="inverse" if not signals.get("pb_entry_ok") else "normal")
            st.progress(min(pb_pct / 100, 1.0))
    with pe_col:
        pe_pct = signals.get("pe_pctile")
        if pe_pct is not None:
            st.metric("PE 分位", f"{pe_pct:.0f}%ile",
                      delta="偏贵" if signals.get("pe_exit_ok") is False else "正常",
                      delta_color="inverse" if signals.get("pe_exit_ok") is False else "normal")
            st.progress(min(pe_pct / 100, 1.0))

    st.divider()
    dd_col1, dd_col2 = st.columns(2)
    with dd_col1:
        gold_dd = signals.get("gold_dd_pct", 0)
        st.metric("黄金回撤(全程峰)", f"{gold_dd*100:.1f}%",
                  delta="抄底规则已弃用(仅展示)" if gold_dd <= -0.15 else "正常")
    with dd_col2:
        hs_dd = signals.get("hs300_dd_pct", 0)
        st.metric("沪深300回撤(全程峰)", f"{hs_dd*100:.1f}%",
                  delta=f"距抄底线 {(-HS300_DIP_THRESHOLD*100):.0f}% 还差 {(hs_dd*100 + HS300_DIP_THRESHOLD*100):.1f}%" if hs_dd > -HS300_DIP_THRESHOLD else "深度回撤")

    # 四季象限
    st.divider()
    st.subheader("宏观季节")

    growth_up = signals.get("hs300_above_sma120", False)
    gold_sma75 = prices["gold"].rolling(75).mean().iloc[-1]
    inflation_up = prices["gold"].iloc[-1] > gold_sma75

    QUADRANTS = [
        {"label": "复苏", "sub": "增长↑ 通胀↓", "growth": True,  "inflation": False,
         "icon": "🌸", "color": "#2e7d32", "assets": "沪深300 · 标普500"},
        {"label": "过热", "sub": "增长↑ 通胀↑",  "growth": True,  "inflation": True,
         "icon": "🔥", "color": "#c62828", "assets": "黄金 · 有色金属"},
        {"label": "滞胀", "sub": "增长↓ 通胀↑", "growth": False, "inflation": True,
         "icon": "💨", "color": "#e65100", "assets": "黄金（避险）"},
        {"label": "衰退", "sub": "增长↓ 通胀↓",  "growth": False, "inflation": False,
         "icon": "❄️", "color": "#1565c0", "assets": "10Y国债 · 30Y国债"},
    ]

    current_label = ""
    for q in QUADRANTS:
        if q["growth"] == growth_up and q["inflation"] == inflation_up:
            current_label = q["label"]
            break

    st.caption(f"当前：**{current_label}**（增长{'↑' if growth_up else '↓'}  通胀{'↑' if inflation_up else '↓'}）")

    cells = []
    for q in QUADRANTS:
        active = q["growth"] == growth_up and q["inflation"] == inflation_up
        border = "3px solid #ffd54f" if active else "1px solid #555"
        bg = "rgba(255,215,0,0.08)" if active else "transparent"
        cells.append(
            f"<div style='border:{border};border-radius:10px;padding:12px 16px;background:{bg};height:100px'>"
            f"<span style='font-size:24px'>{q['icon']}</span> "
            f"<strong style='font-size:16px'>{q['label']}</strong> "
            f"<span style='color:#888;font-size:12px'>{q['sub']}</span><br>"
            f"<span style='font-size:13px;color:#aaa'>{q['assets']}</span>"
            f"</div>"
        )

    html = "<div style='display:grid;grid-template-columns:1fr 1fr;gap:12px'>" + "".join(cells) + "</div>"
    st.markdown(html, unsafe_allow_html=True)

# ============================================================
# Tab 2: 目标权重
# ============================================================
with tab2:
    st.subheader(f"{cfg['name']}  —  {tier}% RP")

    rows = []
    rules = STRATEGY_RULES[_STRAT_CONFIG_KEY[strat_key]]
    for a in cfg["assets"]:
        meta = ETF_META.get(a, {"code": "", "name": a})
        pct = w.get(a, 0)
        status_parts = []

        # 趋势过滤（按 STRATEGY_RULES 判定适用性）
        if a == "nonferr" and rules.get("nonferr_trend_window") and signals.get("nonferr_below_sma75") and pct == 0:
            status_parts.append("趋势过滤→已清仓")
        if a == "gold" and rules.get("gold_trend_filter") and signals.get(f"gold_below_sma{rules.get('gold_trend_window', 75)}") and pct == 0:
            status_parts.append("趋势过滤→已清仓")
        if a == "wti" and rules.get("wti_trend_window") and signals.get("wti_below_sma75") and pct == 0:
            status_parts.append("趋势过滤→已清仓")
        if a == "us_sp500" and "us_sp500" in (rules.get("equity_trend_assets") or []) and signals.get(f"sp500_below_sma{(rules.get('equity_trend_windows') or {}).get('us_sp500', 75)}") and pct == 0:
            status_parts.append("趋势过滤→已清仓")
        if a == "hs300" and "hs300" in (rules.get("equity_trend_assets") or []) and signals.get("hs300_below_sma30") and pct == 0:
            status_parts.append("趋势过滤→已清仓")

        # HS300 抄底状态机
        pct0 = float(w0.get(a, 0))
        if a == "hs300" and signals.get("hs300_dip_entry") and pct > 0:
            if pct > pct0 + 1e-9:
                status_parts.append(f"AND抄底入场×{HS300_DIP_BOOST:.1f}（{pct0*100:.1f}%→{pct*100:.1f}%）")
        elif a == "hs300" and signals.get("hs300_dip_active") and not signals.get("hs300_dip_entry"):
            status_parts.append("抄底持有(不加仓)")
        if a == "hs300" and signals.get("hs300_dip_exit"):
            status_parts.append("抄底退出→恢复基础权重")

        # credit 接收标注
        if a == "credit":
            incoming = []
            if rules.get("nonferr_trend_window") and signals.get("nonferr_below_sma75"):
                incoming.append("有色")
            if rules.get("wti_trend_window") and signals.get("wti_below_sma75"):
                incoming.append("原油")
            if rules.get("gold_trend_filter") and signals.get(f"gold_below_sma{rules.get('gold_trend_window', 75)}"):
                incoming.append("黄金")
            for eq in rules.get("equity_trend_assets") or []:
                window = rules.get("equity_trend_windows", {}).get(eq, 75)
                sig_key = {
                    "us_sp500": f"sp500_below_sma{window}",
                    "hs300": "hs300_below_sma30",
                }.get(eq)
                if sig_key and signals.get(sig_key):
                    incoming.append({"us_sp500": "标普", "hs300": "沪深300"}.get(eq, eq))
            if signals.get("hs300_dip_entry") and pct + 1e-9 < pct0:
                incoming.append("为HS300抄底筹资")
            if incoming:
                status_parts.append(f"接收{'/'.join(incoming)}")

        rows.append({
            "资产": meta["name"],
            "代码": meta["code"],
            "权重": f"{pct*100:.1f}%",
            "场内收盘": (
                f"{float(market_px.iloc[-1].get(a, float('nan'))):.3f}"
                if market_px is not None and not market_px.empty
                and a in market_px.columns and pd.notna(market_px.iloc[-1].get(a))
                else "—"
            ),
            "状态": " / ".join(status_parts) if status_parts else "—",
        })

    if cash_ratio > 1e-9:
        mf_px_val = (
            float(market_px.iloc[-1].get(MF_ASSET, float("nan")))
            if market_px is not None and not market_px.empty
            and MF_ASSET in market_px.columns and pd.notna(market_px.iloc[-1].get(MF_ASSET))
            else None
        )
        rows.append({
            "资产": f"现金 / {MF_NAME}",
            "代码": MF_CODE,
            "权重": f"{cash_ratio*100:.1f}%",
            "场内收盘": f"{mf_px_val:.3f}" if mf_px_val is not None else "—",
            "状态": f"{tier}% RP 未投资部分",
        })

    st.dataframe(pd.DataFrame(rows), width="stretch", hide_index=True)
    st.caption(
        "百分比相对投资总额（含现金档）。信号加仓已写进上表，不要按仪表盘再乘一遍。"
        "权重用累计净值；场内收盘只用于核对券商报价。"
    )
    if signals.get("hs300_dip_entry") and float(w.get("hs300", 0)) > float(w0.get("hs300", 0)) + 1e-9:
        st.info(
            f"HS300 AND 抄底已计入：入场月目标权重 ×{HS300_DIP_BOOST:.1f}"
            f"（{float(w0.get('hs300',0))*100:.1f}%→{float(w.get('hs300',0))*100:.1f}%），多出部分从城投债 ETF 转出。"
        )

    _tf_assets = []
    if rules.get("nonferr_trend_window") and signals.get("nonferr_below_sma75"):
        _tf_assets.append("有色")
    if rules.get("gold_trend_filter") and signals.get(f"gold_below_sma{rules.get('gold_trend_window', 75)}"):
        _tf_assets.append("黄金")
    if rules.get("wti_trend_window") and signals.get("wti_below_sma75"):
        _tf_assets.append("原油")
    if "us_sp500" in (rules.get("equity_trend_assets") or []) and signals.get(f"sp500_below_sma{(rules.get('equity_trend_windows') or {}).get('us_sp500', 75)}"):
        _tf_assets.append("标普")
    if "hs300" in (rules.get("equity_trend_assets") or []) and signals.get("hs300_below_sma30"):
        _tf_assets.append("沪深300")
    if _tf_assets:
        st.info(f"趋势过滤触发 → {'/'.join(_tf_assets)} 已清仓，权重转入城投债 ETF (511220)")

# ============================================================
# Tab 3: 建仓清单
# ============================================================
with tab3:
    st.subheader("从零建仓")
    if px_date:
        st.caption(f"场内收盘 {px_date}（不复权）。股数按此价 / 100 股取整，盘中成交可能略有差异。")
    else:
        st.error("没有场内收盘价，无法生成可下单的股数。请点侧边栏「拉取最新数据」。")

    amount = st.number_input(
        "投资总额（元）",
        min_value=1000,
        value=500000,
        step=10000,
        format="%d",
        key="build_amount_input",
    )

    if amount > 0 and market_px is not None and not market_px.empty:
        latest = market_px.iloc[-1]
        lot_size = 100

        rows = []
        total_used = 0
        missing_px = []
        for a in cfg["assets"]:
            meta = ETF_META.get(a, {"code": "", "name": a})
            pct = w.get(a, 0)
            if pct <= 0:
                continue
            target_amount = pct * amount
            price = float(latest.get(a, np.nan))
            if np.isnan(price) or price <= 0:
                missing_px.append(meta["code"])
                continue
            shares = int(target_amount / price / lot_size) * lot_size
            actual = shares * price
            total_used += actual
            rows.append({
                "资产": meta["name"],
                "代码": meta["code"],
                "权重": f"{pct*100:.1f}%",
                "目标金额": f"¥{target_amount:,.0f}",
                "场内收盘": f"{price:.3f}",
                "买入股数": shares,
                "实际金额": f"¥{actual:,.0f}",
            })

        if rows:
            st.dataframe(pd.DataFrame(rows), width="stretch", hide_index=True)

            remainder = amount - total_used
            cols = st.columns(3)
            with cols[0]:
                st.metric("总投资", f"¥{amount:,.0f}")
            with cols[1]:
                st.metric("已分配", f"¥{total_used:,.0f}")
            with cols[2]:
                st.metric("剩余现金", f"¥{remainder:,.0f}",
                          delta=f"放入{MF_NAME}({MF_CODE})")

            if any(a == "us_sp500" for a in cfg["assets"]) and w.get("us_sp500", 0) > 0:
                st.info("标普500 QDII 经常限购，买不到用场外联接 050025 替代")
            if missing_px:
                st.warning(f"缺场内收盘、已跳过: {', '.join(missing_px)}")
        else:
            st.warning("无有效资产可建仓")

# ============================================================
# Tab 4: 调仓清单
# ============================================================
with tab4:
    st.subheader("旧仓 + 新钱")
    if px_date:
        st.caption(
            f"填入当前持仓股数、活期现金和本月新增资金。目标 = 权重 ×（旧仓市值 + 货基 + 活期 + 新钱），"
            f"按场内收盘 {px_date} 计算买卖股数。"
            f"持仓与剩余现金会记住上一次保存的调仓结果（data/holdings.json）。"
        )
    else:
        st.error("没有场内收盘价，无法计算调仓股数。请点侧边栏「拉取最新数据」。")

    latest = market_px.iloc[-1] if market_px is not None and not market_px.empty else None
    lot_size = 100

    _saved_holdings = _saved_state.get("holdings", {}).get(strat_key, {})

    new_cash = st.number_input(
        "本月新增资金（元）",
        min_value=0,
        value=0,
        step=1000,
        format="%d",
        key=f"new_cash_{strat_key}",
        help="定投/转入的现金。与旧仓市值合计后，再按目标权重分配。",
    )

    st.markdown("**当前持仓股数**")
    holdings_shares = {}
    cols = st.columns(3)
    for i, a in enumerate(cfg["assets"]):
        meta = ETF_META.get(a, {"code": "", "name": a})
        with cols[i % 3]:
            holdings_shares[a] = st.number_input(
                f"{meta['name']} ({meta['code']})",
                min_value=0,
                value=int(_saved_holdings.get(a, 0)),
                step=100,
                format="%d",
                key=f"holdings_{strat_key}_{a}",
            )
    with cols[len(cfg["assets"]) % 3]:
        mf_shares = st.number_input(
            f"{MF_NAME} ({MF_CODE})",
            min_value=0,
            value=int(_saved_state.get("mf_shares", 0)),
            step=100,
            format="%d",
            key="holdings_mf",
            help=f"现金档位的货币仓。目标 = 现金比例 ×（旧仓市值 + 货基 + 活期 + 新钱）。",
        )
    with cols[(len(cfg["assets"]) + 1) % 3]:
        cash_yuan = st.number_input(
            "活期 / 现金余额（元）",
            min_value=0,
            value=int(_saved_state.get("cash_yuan", 0)),
            step=100,
            format="%d",
            key="holdings_cash",
            help="银行卡活期里的现金（含上次调仓剩下来、不够买一手货基的零头）。计入再平衡基数。",
        )

    mf_price = float(latest.get(MF_ASSET, 0) or 0) if latest is not None else 0.0

    if latest is None:
        st.caption("有场内收盘价后才会生成调仓清单")
    else:
        if mf_price <= 0:
            st.warning(f"缺 {MF_CODE} 场内收盘价，货基仓未计入再平衡基数。点侧栏「拉取最新数据」后重试。")
        holdings_mv = sum(
            holdings_shares.get(a, 0) * float(latest.get(a, 0) or 0)
            for a in cfg["assets"]
        )
        mf_mv = mf_shares * mf_price if mf_price > 0 else 0.0
        total_value = holdings_mv + mf_mv + float(cash_yuan) + float(new_cash)
        if total_value > 0:
            st.divider()
            m1, m2, m3, m4, m5 = st.columns(5)
            with m1:
                st.metric("旧仓市值", f"¥{holdings_mv:,.0f}")
            with m2:
                st.metric("货基市值", f"¥{mf_mv:,.0f}")
            with m3:
                st.metric("活期现金", f"¥{cash_yuan:,.0f}")
            with m4:
                st.metric("新增资金", f"¥{new_cash:,.0f}")
            with m5:
                st.metric("合计（再平衡基数）", f"¥{total_value:,.0f}")

            plan = []
            for a in cfg["assets"]:
                meta = ETF_META.get(a, {"code": "", "name": a})
                price = float(latest.get(a, 0) or 0)
                shares = holdings_shares.get(a, 0)
                plan.append({
                    "key": a, "name": meta["name"], "code": meta["code"],
                    "price": price, "shares": shares, "current": shares * price,
                    "target": w.get(a, 0) * total_value,
                })
            if mf_price > 0:
                plan.append({
                    "key": MF_ASSET, "name": f"{MF_NAME}（现金档）", "code": MF_CODE,
                    "price": mf_price, "shares": mf_shares, "current": mf_mv,
                    "target": cash_ratio * total_value,
                })

            for p in plan:
                p["diff"] = p["target"] - p["current"]
                p["pct"] = abs(p["diff"]) / total_value if total_value > 0 else 0
                p["exact"] = p["diff"] / p["price"] / lot_size if p["price"] > 0 else 0.0
                if p["pct"] < 0.005:
                    p["lots"] = 0
                else:
                    mag = int(math.floor(abs(p["exact"]) + 0.5))
                    p["lots"] = mag if p["exact"] > 0 else -mag

            def _plan_leftover():
                buy = sum(p["lots"] * lot_size * p["price"] for p in plan if p["lots"] > 0)
                sell = sum(-p["lots"] * lot_size * p["price"] for p in plan if p["lots"] < 0)
                return float(new_cash) + float(cash_yuan) + sell - buy

            leftover = _plan_leftover()
            while leftover < 0:
                moves = [
                    (lot_size * p["price"], i)
                    for i, p in enumerate(plan)
                    if p["lots"] > 0
                    or (p["lots"] < 0 and -p["lots"] < math.ceil(-p["exact"] - 1e-9))
                ]
                if not moves:
                    break
                amt, i = max(moves)
                plan[i]["lots"] -= 1
                leftover += amt

            def _signal_note(a):
                """调仓清单每行的信号备注，与「目标权重」Tab 标注一致。

                目的：把仪表盘上亮着的信号（抄底/趋势过滤）直接写到买卖行，
                避免「信号触发了却看不出清单里哪一步是它」而误操作。
                """
                if a == MF_ASSET:
                    return f"现金档（{tier}% RP 未投资部分）"
                wa = float(w.get(a, 0))
                wa0 = float(w0.get(a, 0))
                parts = []
                if a == "nonferr" and rules.get("nonferr_trend_window") and signals.get("nonferr_below_sma75") and wa == 0:
                    parts.append("趋势过滤→清仓转城投")
                if a == "gold" and rules.get("gold_trend_filter") and signals.get(f"gold_below_sma{rules.get('gold_trend_window', 75)}") and wa == 0:
                    parts.append("趋势过滤→清仓转城投")
                if a == "wti" and rules.get("wti_trend_window") and signals.get("wti_below_sma75") and wa == 0:
                    parts.append("趋势过滤→清仓转城投")
                if a == "us_sp500" and "us_sp500" in (rules.get("equity_trend_assets") or []) and signals.get(f"sp500_below_sma{(rules.get('equity_trend_windows') or {}).get('us_sp500', 75)}") and wa == 0:
                    parts.append("趋势过滤→清仓转城投")
                if a == "hs300" and "hs300" in (rules.get("equity_trend_assets") or []) and signals.get("hs300_below_sma30") and wa == 0:
                    parts.append("趋势过滤→清仓转城投")
                if a == "hs300" and signals.get("hs300_dip_entry") and wa > 0:
                    if wa > wa0 + 1e-9:
                        parts.append(f"AND抄底入场×{HS300_DIP_BOOST:.1f}（{wa0*100:.1f}%→{wa*100:.1f}%）")
                elif a == "hs300" and signals.get("hs300_dip_active") and not signals.get("hs300_dip_entry"):
                    parts.append("抄底持有(不加仓)")
                if a == "hs300" and signals.get("hs300_dip_exit"):
                    parts.append("抄底退出→恢复基础权重")
                if a == "credit":
                    incoming = []
                    if rules.get("nonferr_trend_window") and signals.get("nonferr_below_sma75"):
                        incoming.append("有色")
                    if rules.get("wti_trend_window") and signals.get("wti_below_sma75"):
                        incoming.append("原油")
                    if rules.get("gold_trend_filter") and signals.get(f"gold_below_sma{rules.get('gold_trend_window', 75)}"):
                        incoming.append("黄金")
                    for eq in rules.get("equity_trend_assets") or []:
                        window = rules.get("equity_trend_windows", {}).get(eq, 75)
                        sig_key = {
                            "us_sp500": f"sp500_below_sma{window}",
                            "hs300": "hs300_below_sma30",
                        }.get(eq)
                        if sig_key and signals.get(sig_key):
                            incoming.append({"us_sp500": "标普", "hs300": "沪深300"}.get(eq, eq))
                    if signals.get("hs300_dip_entry") and wa + 1e-9 < wa0:
                        incoming.append("为HS300抄底筹资")
                    if incoming:
                        parts.append(f"接收{'/'.join(incoming)}")
                return " / ".join(parts) if parts else "—"

            trade_rows = []
            post_shares = {}
            mf_post_shares = mf_shares
            any_trade = False
            buy_cash = 0.0      # 场内 ETF 买入金额
            sell_cash = 0.0
            otc_items = []      # 场外联接基金买入项（目标金额不够一手时）
            otc_total = 0.0

            # 第一轮：只处理场内 ETF（能凑整手的买卖）
            for p in plan:
                diff_shares = p["lots"] * lot_size
                trade_amt = diff_shares * p["price"]
                needs_otc = (
                    p["exact"] > 0 and p["lots"] == 0
                    and p["price"] > 0 and p["diff"] > total_value * 0.005
                    and p["key"] != MF_ASSET
                )

                if trade_amt > 0:
                    action = f"买入 {diff_shares} 股"
                    any_trade = True
                    buy_cash += trade_amt
                elif trade_amt < 0:
                    action = f"卖出 {-diff_shares} 股"
                    any_trade = True
                    sell_cash += -trade_amt
                elif needs_otc:
                    # 标记为场外候选，金额待第二轮决定
                    lot_cost = lot_size * p["price"]
                    otc_items.append({
                        "name": p["name"], "code": p["code"],
                        "target_diff": p["diff"], "lot_cost": lot_cost,
                    })
                    action = "场外买入（待定）"  # 临时标记，第二轮更新
                else:
                    action = "不变" if p["pct"] < 0.005 else "不变（不满一手）"

                if p["key"] == MF_ASSET:
                    mf_post_shares = p["shares"] + diff_shares
                else:
                    post_shares[p["key"]] = p["shares"] + diff_shares

                trade_rows.append({
                    "资产": p["name"],
                    "代码": p["code"],
                    "信号备注": _signal_note(p["key"]),
                    "场内收盘": f"{p['price']:.3f}" if p["price"] > 0 else "—",
                    "持仓股数": p["shares"],
                    "市值 (¥)": f"{p['current']:,.0f}",
                    "目标 (¥)": f"{p['target']:,.0f}",
                    "差额 (¥)": f"{p['diff']:+,.0f}" if abs(p["diff"]) >= 1 else "—",
                    "操作": action,
                    "操作金额 (¥)": f"{trade_amt:+,.0f}" if trade_amt else "—",
                })

            # 第二轮：场内交易完成后的剩余现金，分配给场外买入
            etf_leftover = float(new_cash) + float(cash_yuan) + sell_cash - buy_cash
            for item in otc_items:
                buyable = min(item["target_diff"], max(0.0, etf_leftover - otc_total))
                item["amount"] = buyable
                otc_total += buyable
                # 更新对应行的操作和金额
                for row in trade_rows:
                    if row["代码"] == item["code"]:
                        if buyable >= item["target_diff"] - 1:
                            row["操作"] = f"场外买入 ¥{buyable:,.0f}"
                        elif buyable > 0:
                            row["操作"] = f"场外买入 ¥{buyable:,.0f}（目标 ¥{item['target_diff']:,.0f}，现金不足）"
                            item["partial"] = True
                        else:
                            row["操作"] = f"暂缓（现金不足，下月累计）"
                            item["deferred"] = True
                        row["操作金额 (¥)"] = f"-{buyable:,.0f}" if buyable > 0 else "—"
                        break
            if otc_total > 0:
                any_trade = True
                buy_cash += otc_total


            _dip_notes = []
            if signals.get("hs300_dip_entry") and float(w.get("hs300", 0)) > float(w0.get("hs300", 0)) + 1e-9:
                _dip_notes.append(
                    f"HS300 AND 抄底已计入：入场月目标权重 ×{HS300_DIP_BOOST:.1f}"
                    f"（{float(w0.get('hs300',0))*100:.1f}%→{float(w.get('hs300',0))*100:.1f}%），多出部分从城投债 ETF 转出。"
                )
            if signals.get("hs300_dip_exit"):
                _dip_notes.append("HS300 AND 抄底退出 → 恢复基础权重（回撤收窄 且 PE 分位>70 同时满足）。")
            _tf = []
            if rules.get("nonferr_trend_window") and signals.get("nonferr_below_sma75"):
                _tf.append("有色")
            if rules.get("gold_trend_filter") and signals.get(f"gold_below_sma{rules.get('gold_trend_window', 75)}"):
                _tf.append("黄金")
            if rules.get("wti_trend_window") and signals.get("wti_below_sma75"):
                _tf.append("原油")
            if "us_sp500" in (rules.get("equity_trend_assets") or []) and signals.get(f"sp500_below_sma{(rules.get('equity_trend_windows') or {}).get('us_sp500', 75)}"):
                _tf.append("标普")
            if "hs300" in (rules.get("equity_trend_assets") or []) and signals.get("hs300_below_sma30"):
                _tf.append("沪深300")
            if _tf:
                _dip_notes.append(f"趋势过滤触发：{'/'.join(_tf)} 应清仓，权重转入城投债 ETF (511220)。")
            for _n in _dip_notes:
                st.info(_n)

            st.dataframe(pd.DataFrame(trade_rows), width="stretch", hide_index=True)
            st.caption(
                "「信号备注」列写明每行受哪个信号驱动（抄底/趋势过滤/为抄底筹资），下单前先核对。"
                "操作金额 = 操作股数 × 场内收盘；股数按最接近的手数取整（现金不足时买入自动减手），"
                "与「差额」的残差计入剩余现金。"
            )

            # 场外联接基金建议（目标金额不够一手时）
            if otc_items:
                otc_lines = []
                for item in otc_items:
                    amt = item.get("amount", 0)
                    target = item["target_diff"]
                    lot_cost = item["lot_cost"]
                    if item.get("deferred"):
                        otc_lines.append(
                            f"- **{item['name']}（{item['code']}）**：目标 ¥{target:,.0f}，"
                            f"场内一手需 ¥{lot_cost:,.0f}（买不起）→ "
                            f"**本月暂缓**（场内交易后无剩余现金），下月新增资金累计后再买"
                        )
                    elif item.get("partial"):
                        otc_lines.append(
                            f"- **{item['name']}（{item['code']}）**：目标 ¥{target:,.0f}，"
                            f"场内一手需 ¥{lot_cost:,.0f}（买不起）→ "
                            f"**场外买入 ¥{amt:,.0f}**（现金不足，差 ¥{target-amt:,.0f}，下月补齐）"
                        )
                    else:
                        otc_lines.append(
                            f"- **{item['name']}（{item['code']}）**：目标 ¥{target:,.0f}，"
                            f"场内一手需 ¥{lot_cost:,.0f}（买不起）→ "
                            f"**场外买入 ¥{amt:,.0f}**"
                        )
                st.warning(
                    f"⚠️ 以下资产目标金额不够场内一手（100 股），建议用**场外联接基金**买入。\n\n"
                    + "\n".join(otc_lines) + "\n\n"
                    f"**操作方式**：通过天天基金 / 支付宝 / 银行 APP 买入对应 ETF 的联接基金（A 类或 C 类），"
                    f"场外基金按金额申购，10 元起，没有整数手限制。\n\n"
                    f"场外买入合计 ¥{otc_total:,.0f}，已计入「预计买入」，需从券商转出至基金账户。"
                )

            leftover = float(new_cash) + float(cash_yuan) + sell_cash - buy_cash
            s1, s2, s3 = st.columns(3)
            with s1:
                st.metric("预计买入", f"¥{buy_cash:,.0f}",
                          delta=f"含场外 ¥{otc_total:,.0f}" if otc_items else None)
            with s2:
                st.metric("预计卖出", f"¥{sell_cash:,.0f}")
            with s3:
                st.metric("剩余现金", f"¥{leftover:,.0f}",
                          delta=f"场外买入需从券商转出 ¥{otc_total:,.0f}" if otc_items else f"保存后记为下月活期；够一手可买{MF_CODE}")

            c_save, c_save_hint = st.columns([1, 2])
            with c_save:
                if st.button(
                    "💾 记住本次调仓后持仓",
                    help="下单完成后点这个：把表里的「持仓 ± 操作股数」和剩余现金存为下次默认值。",
                ):
                    _save_state({
                        "strat": strat_key,
                        "tier": tier,
                        "mf_shares": int(mf_post_shares),
                        "cash_yuan": int(round(leftover)),
                        "holdings": {
                            **_saved_state.get("holdings", {}),
                            strat_key: {a: int(post_shares.get(a, 0)) for a in cfg["assets"]},
                        },
                        "saved_at": pd.Timestamp.now().strftime("%Y-%m-%d %H:%M"),
                    })
                    _saved_state = _load_saved_state()
                    st.success("已保存。下次打开面板自动填入本次调仓后的持仓。")
            with c_save_hint:
                _saved_at = _saved_state.get("saved_at")
                if _saved_at:
                    st.caption(f"上次保存: {_saved_at}（策略 {_strat_display.get(_saved_state.get('strat'), '—')} / {_saved_state.get('tier', '—')}% RP）")

            if sell_cash > 0:
                st.warning("有卖出：先卖后买，等卖出资金 T+0 可用再买。")
            if not any_trade:
                st.success("所有资产偏离 < 0.5%，无需调仓")
            if any(a == "us_sp500" for a in cfg["assets"]) and w.get("us_sp500", 0) > 0:
                st.info("标普500 QDII 限购时用场外联接 050025 替代")

            with st.expander("调仓规则说明"):
                st.markdown(f"""
            1. 每月最后一个交易日执行一次
            2. **旧仓 + 新钱**：目标金额 = 当前权重 ×（已有市值 + 货基 + 新增资金）
            3. 先卖后买 — 卖出资金 T+0 可用后再买入
            4. 趋势过滤触发时，被清仓资产应卖掉，权重在城投债
            5. 偏离 < 0.5% 或不满 100 股 不用动
            6. 价格为场内收盘价；现金档与零头放货币 ETF {MF_CODE}
            7. 标普500 QDII 限购时用场外联接 050025 替代
            8. 下单完成后点「💾 记住本次调仓后持仓」，下月自动带入
            """)
        else:
            st.caption("输入持仓股数和/或新增资金后生成买卖清单")

# ============================================================
# 底部：多策略对比（含 V3D）
# ============================================================
st.divider()
with st.expander(f"📈 {len(_strat_order)} 策略权重对比"):
    all_weights = {}
    for k in _strat_order:
        w0_cmp = compute_target_weights(k, prices, cash_ratio)
        w_cmp = apply_signal_overrides(k, w0_cmp, signals, prices)
        all_weights[k] = w_cmp

    cmp_rows = []
    for a in ["hs300", "us_sp500", "credit", "bond_10y", "bond_30y", "gold", "nonferr", "wti"]:
        meta = ETF_META.get(a, {"code": "", "name": a})
        row = {"资产": meta["name"], "代码": meta["code"]}
        for k in _strat_order:
            row[_strat_display[k]] = f"{all_weights[k].get(a, 0)*100:.1f}%"
        cmp_rows.append(row)

    st.dataframe(pd.DataFrame(cmp_rows), width="stretch", hide_index=True)
