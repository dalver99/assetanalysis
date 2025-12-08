# =============================================================
# 스트림릿 앱 엔트리포인트
# - 자산 시계열 시각화, 통계 분석, 디비전(비율) 분석 탭 제공
# - 사이드바에서 자산/기간 선택 및 실행 제어
# =============================================================

import os
import sys
from pathlib import Path

# `utils` 모듈을 임포트할 수 있도록 프로젝트 루트를 경로에 추가
PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import pandas as pd
import streamlit as st
import altair as alt
import json

from utils.data_process import fetch_data, preprocess_data
from app.ui import (
    load_assets_config,
    render_sidebar_assets,
    gate_run_and_params,
    apply_display_names,
)
from app.charts import build_chart, render_statistics_tab, render_division_tab, render_candlestick_tab


def load_assets_config(project_root: Path) -> list[tuple[str, str, bool]]:
    """Load assets from assets.json, falling back to defaults if missing/invalid."""
    assets_path = project_root / "assets.json"
    if assets_path.exists():
        try:
            with open(assets_path, "r", encoding="utf-8") as f:
                cfg = json.load(f)
                parsed = [
                    (
                        a.get("symbol", ""),
                        a.get("name", a.get("symbol", "")),
                        bool(a.get("enabled", True)),
                    )
                    for a in cfg.get("assets", [])
                    if a.get("symbol")
                ]
                if parsed:
                    return parsed
        except Exception:
            pass

    return [
        ("068270.KS", "Celltrion", True),
        ("GC=F", "Gold", True),
        ("^IXIC", "Nasdaq", True),
        ("^GSPC", "S&P 500", True),
        ("BTC-USD", "Bitcoin", True),
        ("^TNX", "10Y Treasury Yield", True),
        ("^VIX", "VIX", True),
    ]


def render_sidebar_assets(
    default_assets: list[tuple[str, str, bool]],
) -> tuple[list[str], dict[str, str]]:
    """Render asset checkboxes and return selected symbols and display-name mapping."""
    st.sidebar.subheader("Select assets")
    selected_symbols: list[str] = []
    symbol_to_display: dict[str, str] = {}
    for symbol, friendly, enabled in default_assets:
        include = st.sidebar.checkbox(friendly, value=enabled, key=f"asset_{symbol}")
        if include:
            selected_symbols.append(symbol)
            symbol_to_display[symbol] = friendly
    return selected_symbols, symbol_to_display


def gate_run_and_params(
    selected_symbols: list[str], period, start, end
) -> tuple[bool, dict]:
    """Show Run button, store params in session state, and decide whether to proceed."""
    run_clicked = st.sidebar.button("Run")
    if run_clicked:
        st.session_state["do_run"] = True
        st.session_state["run_params"] = {
            "symbols": tuple(selected_symbols),
            "period": period or "10d",
            "start": start,
            "end": end,
        }
    if not st.session_state.get("do_run"):
        return False, {}
    params = st.session_state.get(
        "run_params",
        {
            "symbols": tuple(selected_symbols),
            "period": period or "10d",
            "start": start,
            "end": end,
        },
    )
    return True, params


def apply_display_names(
    dfs_processed: list[pd.DataFrame],
    selected_symbols: list[str],
    symbol_to_display: dict[str, str],
) -> None:
    """Assign chosen display names to each processed dataframe's Name column in order."""
    symbol_iter = iter(selected_symbols)
    for df in dfs_processed:
        try:
            symbol = next(symbol_iter)
        except StopIteration:
            break
        df["Name"] = symbol_to_display.get(symbol, symbol)


def build_wide_df(dfs_processed: list[pd.DataFrame]) -> pd.DataFrame:
    """Create a wide DataFrame with columns per asset of normalized Close."""
    wide: dict[str, pd.Series] = {}
    for df in dfs_processed:
        if "Name" in df.columns:
            wide[str(df["Name"].iloc[0])] = df["Close"].astype(float)
    return pd.DataFrame(wide)


def render_statistics_tab(dfs_processed: list[pd.DataFrame]) -> None:
    st.subheader("Summary Statistics")
    wide_df = build_wide_df(dfs_processed)

    returns = wide_df.pct_change().dropna(how="all")
    ann_factor = 252

    vol = returns.std() * (ann_factor**0.5)
    mean_ret = returns.mean() * ann_factor
    sharpe_like = mean_ret / vol.replace({0: pd.NA})

    def max_drawdown(series: pd.Series) -> float:
        running_max = series.cummax()
        drawdown = (series / running_max) - 1.0
        return float(drawdown.min()) if not drawdown.empty else float("nan")

    mdd = wide_df.apply(max_drawdown)

    summary = pd.DataFrame(
        {
            "Annualized Return": mean_ret,
            "Annualized Volatility": vol,
            "Sharpe-like": sharpe_like,
            "Max Drawdown": mdd,
        }
    ).sort_index()

    st.dataframe(
        summary.style.format(
            {
                "Annualized Return": "{:.2%}",
                "Annualized Volatility": "{:.2%}",
                "Sharpe-like": "{:.2f}",
                "Max Drawdown": "{:.1%}",
            }
        ),
        use_container_width=True,
    )

    st.subheader("Correlation Matrix (Daily Returns)")
    corr = returns.corr()
    corr_long = (
        corr.reset_index()
        .melt(
            id_vars=corr.index.name or "index",
            var_name="Asset2",
            value_name="Correlation",
        )
        .rename(columns={corr.index.name or "index": "Asset1"})
    )
    heat = (
        alt.Chart(corr_long)
        .mark_rect()
        .encode(
            x=alt.X("Asset1:N", sort=list(corr.columns)),
            y=alt.Y("Asset2:N", sort=list(corr.columns)),
            color=alt.Color(
                "Correlation:Q", scale=alt.Scale(domain=[-1, 1], scheme="redblue")
            ),
            tooltip=[
                alt.Tooltip("Asset1:N", title="Asset 1"),
                alt.Tooltip("Asset2:N", title="Asset 2"),
                alt.Tooltip("Correlation:Q", title="Corr", format=".2f"),
            ],
        )
    )
    text = (
        alt.Chart(corr_long)
        .mark_text(color="black")
        .encode(
            x="Asset1:N", y="Asset2:N", text=alt.Text("Correlation:Q", format=".2f")
        )
    )
    st.altair_chart((heat + text).properties(height=400), use_container_width=True)

    st.subheader("Rolling 30-Day Annualized Volatility")
    rolling_vol = returns.rolling(30).std() * (ann_factor**0.5)
    rv = rolling_vol.copy()
    rv["Date"] = rv.index
    rv_long = rv.melt(id_vars=["Date"], var_name="Name", value_name="Vol")
    rv_chart = (
        alt.Chart(rv_long)
        .mark_line()
        .encode(
            x=alt.X("Date:T", title="Date"),
            y=alt.Y("Vol:Q", title="Volatility", scale=alt.Scale(zero=False)),
            color=alt.Color("Name:N", legend=alt.Legend(title="Ticker")),
            tooltip=[
                "Name:N",
                alt.Tooltip("Date:T"),
                alt.Tooltip("Vol:Q", format=".2%"),
            ],
        )
        .properties(height=300)
    )
    st.altair_chart(rv_chart, use_container_width=True)


def render_division_tab(dfs_processed: list[pd.DataFrame]) -> None:
    st.subheader("Price Ratio (Division)")
    wide_df = build_wide_df(dfs_processed)

    if wide_df.shape[1] < 2:
        st.info("Select at least two assets to compute a ratio.")
        return

    names = list(wide_df.columns)
    col1, col2 = st.columns(2)
    with col1:
        asset_a = st.selectbox("Asset A (numerator)", options=names, index=0)
    with col2:
        asset_b = st.selectbox(
            "Asset B (denominator)", options=names, index=1 if len(names) > 1 else 0
        )

    pair = wide_df[[asset_a, asset_b]].dropna(how="any")
    if pair.empty:
        st.warning("No overlapping dates between the selected assets.")
        return

    min_date = pair.index.min().date()
    max_date = pair.index.max().date()
    r1, r2 = st.columns(2)
    with r1:
        dr_start = st.date_input(
            "Start date", value=min_date, min_value=min_date, max_value=max_date
        )
    with r2:
        dr_end = st.date_input(
            "End date", value=max_date, min_value=min_date, max_value=max_date
        )

    if dr_start > dr_end:
        st.warning("Start date must be on or before end date.")
        return

    mask = (pair.index.date >= dr_start) & (pair.index.date <= dr_end)
    sub = pair.loc[mask]
    if sub.empty:
        st.warning("No data in the selected date range.")
        return

    ratio = (sub[asset_a] / sub[asset_b]).rename(f"{asset_a} / {asset_b}")
    ratio_df = ratio.to_frame(name="Ratio").copy()
    ratio_df["Date"] = ratio_df.index

    base = (
        alt.Chart(ratio_df)
        .mark_line(color="#d62728", strokeWidth=2.5)
        .encode(
            x=alt.X("Date:T", title="Date"),
            y=alt.Y("Ratio:Q", title="Price Ratio", scale=alt.Scale(zero=False)),
            tooltip=[
                alt.Tooltip("Date:T", title="Date"),
                alt.Tooltip("Ratio:Q", title="Ratio", format=".3f"),
            ],
        )
    )

    ref = (
        alt.Chart(pd.DataFrame({"y": [1]}))
        .mark_rule(color="gray", strokeDash=[4, 4])
        .encode(y="y:Q")
    )

    prices = sub.copy()
    prices["Date"] = prices.index
    prices_long = prices.melt(id_vars=["Date"], var_name="Name", value_name="Price")
    price_layer = (
        alt.Chart(prices_long)
        .mark_line(opacity=0.35)
        .encode(
            x=alt.X("Date:T", title="Date"),
            y=alt.Y("Price:Q", title="Normalized Price", scale=alt.Scale(zero=False)),
            color=alt.Color("Name:N", legend=alt.Legend(title="Assets")),
            tooltip=[
                "Name:N",
                alt.Tooltip("Date:T", title="Date"),
                alt.Tooltip("Price:Q", title="Price", format=".3f"),
            ],
        )
    )

    ratio_layer = base + ref
    combined = (
        alt.layer(price_layer, ratio_layer)
        .resolve_scale(y="independent")
        .properties(height=400)
    )
    st.altair_chart(combined, use_container_width=True)


def build_chart(dataframes: list[pd.DataFrame], highlighted: set[str]) -> alt.Chart:
    # Altair 입력을 위해 여러 데이터프레임을 롱 포맷으로 결합
    long_frames: list[pd.DataFrame] = []
    for df in dataframes:
        if "Name" not in df.columns:
            continue
        name = str(df["Name"].iloc[0])
        tmp = df.reset_index()[["Date", "Close"]].copy()
        tmp["Name"] = name
        long_frames.append(tmp)

    if not long_frames:
        return alt.Chart(pd.DataFrame({"Date": [], "Close": [], "Name": []}))

    data_long = pd.concat(long_frames, ignore_index=True)

    chart = (
        alt.Chart(data_long)
        .mark_line()
        .encode(
            x=alt.X("Date:T", title="Date"),
            y=alt.Y(
                "Close:Q",
                title="Normalized Close",
                scale=alt.Scale(zero=False),  # tighten domain; avoid large gap at zero
            ),
            color=alt.Color(
                "Name:N",
                legend=alt.Legend(title="Ticker"),
                scale=alt.Scale(scheme="tableau10"),
            ),
            tooltip=[
                "Name:N",
                alt.Tooltip("Date:T", title="Date"),
                alt.Tooltip("Close:Q", title="Close", format=".3f"),
            ],
        )
    )

    if highlighted:
        chart = chart.encode(
            opacity=alt.condition(
                alt.FieldOneOfPredicate(field="Name", oneOf=list(highlighted)),
                alt.value(1.0),
                alt.value(0.25),
            )
        )

    return chart.properties(height=500)


def main() -> None:
    st.set_page_config(page_title="Asset Explorer", layout="wide")
    st.title("Asset Explorer")

    # Sidebar inputs
    st.sidebar.header("Controls")

    # Load assets
    default_assets = load_assets_config(PROJECT_ROOT)

    # Select assets
    selected_symbols, symbol_to_display = render_sidebar_assets(default_assets)

    date_mode = st.sidebar.radio(
        "Date selection mode", ["Period", "Range"], horizontal=True
    )
    if date_mode == "Period":
        period = st.sidebar.selectbox(
            "Period",
            ["5d", "10d", "1mo", "3mo", "6mo", "1y", "2y", "5y", "10y", "ytd", "max"],
            index=1,
        )
        start = None
        end = None
    else:
        start = st.sidebar.date_input("Start date")
        end = st.sidebar.date_input("End date")
        period = None

    # Run gate and params
    proceed, params = gate_run_and_params(selected_symbols, period, start, end)
    if not proceed:
        st.info("Adjust controls and click Run to fetch and plot.")
        return

    # Highlight selection (by display names)
    st.sidebar.subheader("Highlight")
    highlight_options = [symbol_to_display[s] for s in selected_symbols]
    highlighted = set(
        st.sidebar.multiselect(
            "Highlight (optional)", options=highlight_options, default=[]
        )
    )

    # Fetch and preprocess
    with st.spinner("Fetching data..."):
        dfs = fetch_data(
            tickers=list(params["symbols"]),
            period=params["period"],
            start=params["start"],
            end=params["end"],
            add_name=True,
        )

    if not dfs:
        st.warning("No data fetched. Check tickers or date range.")
        return

    with st.spinner("Preprocessing..."):
        dfs_processed = preprocess_data(dfs)

    # Apply chosen display names to processed data
    apply_display_names(dfs_processed, selected_symbols, symbol_to_display)

    # Also apply display names to raw data for candlestick tab
    apply_display_names(dfs, selected_symbols, symbol_to_display)

    tab_chart, tab_stats, tab_div, tab_candle = st.tabs(
        ["Chart", "Statistics", "Division", "Candlestick"]
    )

    with tab_chart:
        chart = build_chart(dfs_processed, highlighted)
        st.altair_chart(chart, use_container_width=True)

    with tab_stats:
        render_statistics_tab(dfs_processed)

    with tab_div:
        render_division_tab(dfs_processed)

    with tab_candle:
        render_candlestick_tab(dfs, symbol_to_display)


if __name__ == "__main__":
    main()
