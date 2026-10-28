<div align="center">

# 桥水全天候策略 · 中国版

[![Pages](https://img.shields.io/badge/docs-online-blue)](https://idealauror.github.io/all-weather-portfolio/)
[![License](https://img.shields.io/badge/license-AGPL--3.0-blue.svg)](LICENSE)
[![Python](https://img.shields.io/badge/python-3.10+-blue.svg)](https://www.python.org/)
[![Backtest](https://img.shields.io/badge/backtest-2005--2026-green)]()
</div>

<div align="center">

[English](README.md) | **中文**

</div>

基于 A 股 / 债 / 商品 ETF 真实数据的全天候风险平价回测工程，覆盖 **2005–2026 年（~21 年完整牛熊）**，提供 **3 套可落地策略 + 1 套实验性变体（V3D 混合窗口）**，每套支持 3-4 档现金管理（100% / 85% / 70% / 动态），共 11 个回测。

在线文档：[https://idealauror.github.io/all-weather-portfolio/](https://idealauror.github.io/all-weather-portfolio/)


## 策略速查

| 方案 | 风格 | CAGR | 波动率 | 最大回撤 | Sharpe | 一句话 |
|------|:----:|:----:|:------:|:--------:|:-----:|--------|
| **V3-B 保守增强(20d)** | 保守增强 | **{BCON_CAGR}** | {BCON_VOL} | **{BCON_MDD}** | **{BCON_SHARPE}** | 逆波动率 20d + nonferr(75d) + HS300 AND 抄底 |
| **V3-B 风险平价(20d)** | 学院派 | {BRP_CAGR} | {BRP_VOL} | {BRP_MDD} | {BRP_SHARPE} | 4 桶等权 HRP + nonferr/gold/sp500/hs300 趋势 + 抄底 + 波动率控制 |
| **V3c 多元** | 多元全天候 | **{V3C_CAGR}** | {V3C_VOL} | {V3C_MDD} | {V3C_SHARPE} | 6 资产逆波动率 20d + {V3C_TREND_DESC} + HS300 AND 抄底 |
| **V3D 混合窗口** ⚠️ | V3c 变体 | **10.83%** | — | **-5.92%** | **1.76** | 同 V3c，仅 gold/sp500 趋势改 SMA200（分层窗口） |

> V3-B RP 四重趋势过滤：nonferr(75d) + gold(75d) + sp500(75d) + hs300(30d)；V3c 三重趋势过滤：nonferr(75d) + gold(75d) + sp500(75d)。不含 bond_10y（CAGR +1.43pp, Sharpe -0.02）。V3c 多元 6 资产逆波动率 20d，同样不含 bond_10y。三策略均含原油（WTI 75d 趋势过滤，默认集成）。
>
> **V3D 混合窗口**（2026-10 新增）是 V3c 的分层窗口变体：gold/sp500 趋势过滤改用 SMA200，nonferr/wti 保持 SMA75。回测 CAGR +0.68pp、MDD -6.30%→-5.92%，前后半段子样本均占优。⚠️ **实验性方案**：200 为同数据网格选出的样本内参数，存在二阶数据挖掘风险；黄金若出现 V 型急跌，SMA200 会比 SMA75 离场更晚。详见 [docs/strategy-v3d.md](docs/strategy-v3d.md)。

| | 定位 | CAGR | MDD | 核心约束 | 趋势过滤 | 负收益年 |
|--|:--:|:---:|:---:|:--------:|:--------:|:--------:|
| **V3-B 保守增强** | 保守防御 | ≥ 7% | ≤ -7% | Sharpe ≥ 1.2 | 1 个 | {BCON_NEG_YEARS} |
| **V3-B 风险平价** | 进取高回报 | ≥ 8.5% | ≤ -9% | CAGR 优先 | 4 个 | {BRP_NEG_YEARS} |
| **V3c 多元** | 中位中枢 | ≥ 8.5% | ≤ -8.5% | 回撤优先 | 3 个 | {V3C_NEG_YEARS} |
| **V3D 混合窗口** ⚠️ | 实验性 | — | — | 同 V3c 风控逻辑 | 3 个（gold/sp500 用 200d） | 0 |

> 三策略均含原油（WTI 75d 趋势过滤），指标为含原油口径。V3D 同口径，但为实验性方案。

### 一句话选策略

| 你的情况 | 选 |
|---------|:---:|
| 退休金、不能亏、随时可能用钱 | **V3-B 保守增强** |
| 长期储蓄（5年+）、认同全天候理念、能承受短期波动 | **V3-B 风险平价** |
| 追求高回报、接受多元资产分散、理解趋势过滤逻辑 | **V3c 多元** |
| 已在用 V3c、愿意尝试分层窗口并接受样本内选参风险 | **V3D 混合窗口**（先小仓位/观察） |


## 资产宇宙

基于桥水原版**四象限宏观暴露**框架，在 A 股可投范围内选择 ETF：

| 桶 | 资产 | 代码 | V3-B Con | V3-B RP | V3c 多元 | V3D 混合窗口 |
|----|------|:----:|:--------:|:-------:|:--------:|:-----------:|
| **增长↑** | 沪深 300 | 510300 | ✓ | ✓ | ✓ | ✓ |
| | 标普 500 | 513500 | ✓ | ✓ | ✓ | ✓ |
| **收益垫** | 城投债 | 511220 | ✓ | ✓ | ✓ | ✓ |
| **增长↓ 10Y** | 10 年国债 | 511260 | ✓ | — | — | — |
| **增长↓ 30Y** | 30 年国债 | 511130 | ✓ | ✓ | ✓ | ✓ |
| **通胀↑** | 黄金 | 518850 | ✓ | ✓ | ✓ | ✓ |
| | 有色金属 | 159980 | ✓ | ✓ | ✓ | ✓ |
| | 原油（LOF） | 501018 | ✓ | ✓ | ✓ | ✓ |

> V3D 的资产与 V3c 完全相同（含 WTI），仅 gold/sp500 的趋势窗口为 200 日。
>
> V3c 和 V3-B RP 不含 bond_10y（与 bond_30y 同在增长↓桶，久期更短，对组合贡献冗余）。
> 
> 30 年国债 ETF（511130）2024 年 3 月上市。回测覆盖 2005–2024 年数据缺口：**2005–2020** 10Y 国债指数 × 久期放大(×3.0)，**2020–2024** 利差法（10Y + 期限利差），**2024+** 真实数据。合成段年化扣减 0.3%。
>
> **原油（南方原油 LOF 501018）**：回测默认集成，75d 趋势过滤，MDD 改善 1-2pp（CAGR +0.2~-0.3pp），在通胀桶内与 gold/nonferr 低相关分散。**2026-08 起实盘不再纳入**——沪深交易所 LOF 退市新规要求 QDII/商品期货 LOF 于 2027 年底前终止上市，501018 属清退范围。实盘采用无 WTI 版本，详见 [调仓记录 · V3c 无 WTI 版本](docs/rebalance-2026-08-v3c-no-wti.md)。


## 快速开始

```bash
pip install -e ".[fetch]"
pip install streamlit
py main.py                             # 全量回测（自动增量更新数据 + 报告）
# py main.py --force-fetch             # 强制重拉所有数据
# py main.py --no-excel                # 跳过 Excel 报告
# py main.py --no-markdown             # 跳过 Markdown 报告
py -m allweather.rebalance             # CLI 再平衡
```

### 再平衡面板（推荐）

Windows **双击桌面上的「全天候再平衡面板」图标**（太阳+播放键，每月调仓点这个）。图标由这条命令生成：

```bash
py streamlit_app/install_desktop_shortcut.py            # 生成 run-icon.ico + 桌面快捷方式
py streamlit_app/install_desktop_shortcut.py --remove   # 不要了就删掉快捷方式
```

脚本内部走 `run.bat` / `py`，避免微软商店的 `python` 占位程序闪退。不想放桌面可直接双击 `streamlit_app/run.bat`，或：

```bash
pip install streamlit
py streamlit_app/run.py
```

浏览器打开 `http://localhost:8501`。**不要关黑色命令行窗口**，关了服务就停；退出用窗口里 `Ctrl+C`。

| 步骤 | 说明 |
|------|------|
| 切策略 | 主页面顶部选 V3-B 保守增强 / 风险平价 / V3c / V3D 混合窗口，以及 100%/85%/70% RP。**选择即时写入 `data/holdings.json`，下次打开自动选中同一方案** |
| 信号 / 权重 | 用累计净值计算，与回测同一口径 |
| 场内收盘 | 左侧列表与建仓/调仓表，用于核对券商报价、计算股数（不是累计净值） |
| 从零建仓 | 「建仓清单」只填**这笔新资金**（空仓首次买入） |
| 旧仓 + 新钱 | 「调仓清单」填当前持仓股数 + 本月新增资金，按权重 ×（旧仓市值+新钱）给出买卖 |
| 定投节奏 | 月末最后一个交易日操作；有卖出则先卖后买；零头放货基 511990 |
| 刷新行情 | 侧栏「拉取最新数据」 |

首次启动会拉场内收盘价（`data/*_px.csv`）。若提示找不到 Python：安装 3.10+ 并使用 `py`，或关闭「设置 → 应用 → 高级应用设置 → 应用执行别名」里的 `python.exe`。

**输出文件**:

| 文件 | 说明 |
|------|------|
| `output/report.xlsx` | 11-sheet Excel 综合报告 |
| `output/nv_curves.csv` | 全部回测净值曲线宽表 |
| `output/weight_history_*.csv` | 权重历史 |
| `output/signal_log.csv` | 风控信号触发日志 |
| `docs/charts/*.png` | 8 张分析图表 |
| `docs/data.json` | 结构化指标（前端展示用） |



## 回测局限

- **30 年国债数据合成**：2024 年 3 月前无真实 ETF 数据，三阶段合成（久期乘数 → 利差法 → 真实数据），合成段年化扣减 0.3%
- **QDII 限购**：标普 500（513500）受 QDII 额度限制，极端行情可能溢价或暂停申购
- **费用假设**：回测以价格收益率为准，未扣管理费/托管费（ETF 层面 ~0.5%/年），通过无风险利率修正 Sharpe
- **不可执行风险**：回测假设每月**月末最后交易日**收盘价成交（避开商品期货月中换月窗口，`REBAL_MODE=month_end`），实盘存在滑点和流动性差异


## 项目目录

```
├── main.py                  # 入口：全量回测
├── pyproject.toml
├── allweather/              # 核心模块
│   ├── config.py            常量（参数阈值、回测区间）
│   ├── types.py             共享类型定义
│   ├── data.py              数据加载 + 30Y 国债三阶段合成
│   ├── fetch.py             通过 akshare 拉取实时数据
│   ├── backtest.py          统一回测引擎（V3-B RP/V3-B Con/V3c）
│   ├── strategy_b.py        V3-B 引擎（分层风险平价 + 保守增强）
│   ├── risk.py              逆波动率 / 风险平价 / 趋势过滤算法
│   ├── stats.py             绩效指标 / Bootstrap / D_excess 尾部诊断
│   ├── reports.py           控制台输出
│   ├── charts.py            8 张分析图表生成
│   ├── excel_export.py      Excel 报告
│   ├── markdown_report.py   Markdown 报告
│   ├── update_docs.py       README/CLAUDE.md/docs 同步
│   ├── experiment_log.py    实验日志
│   ├── rebalance.py         实盘再平衡（CLI）
│   └── pipeline.py          6 步流水线编排
├── streamlit_app/           # Web 再平衡面板（推荐）
│   ├── app.py
│   ├── app.py               面板（Streamlit）
│   ├── run-icon.png         图标源图
│   ├── run-icon.ico         快捷方式图标（脚本生成）
│   ├── install_desktop_shortcut.py  生成桌面快捷方式
│   ├── run.bat              实际启动脚本
│   └── run.py               自动开浏览器
├── joinquant/               # 聚宽平台量化测试代码
├── portfolio_comparison/    # 多策略对比工具
├── data/                    # 历史数据 CSV
├── docs/                    # GitHub Pages 文档
│   ├── index.html           交互式报告
│   ├── data.json            结构化指标
│   ├── strategy-paper.md    策略设计论文
│   ├── strategy-v3d.md      V3D 混合窗口方案说明与风险
│   └── charts/              分析图表 PNG
└── output/                  # 自动生成（回测报告/Excel/权重日志）
```

## 聚宽版

三策略已移植到 [聚宽（JoinQuant）](https://www.joinquant.com/) 平台，单文件粘贴运行，不依赖本地环境。

| 策略 | 本地 CAGR | 聚宽 CAGR | 差异 | 聚宽 MDD | 聚宽 Sharpe |
|------|:---------:|:---------:|:----:|:--------:|:----------:|
| **V3c 多元** | 9.21% | 9.50% | +0.29pp | −7.73% | 1.01 |
| **V3-B 保守增强** | 8.69% | 7.99% | −0.70pp | −5.22% | 1.04 |
| **V3-B 风险平价** | 10.03% | 10.23% | +0.20pp | −7.51% | 0.93 |

> 聚宽版简化项：HS300 抄底从 PB/PE 分位+价格版（纯价格版）、趋势检查月频而非日频、回测起点 2020 年。对比详情见 `joinquant/comparison.md`。

详见 `joinquant/` 目录或 [joinquant/README.md](joinquant/README.md)。
