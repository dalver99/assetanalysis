from __future__ import annotations

# =============================================================
# 차트/통계 유틸리티: 메인 차트, 통계 탭, 디비전(비율) 탭 렌더링
# - Altair 기반 시각화 구성 요소 모음
# - mplfinance 기반 캔들스틱 차트
# - 공용 wide 데이터프레임 생성 함수 포함
# =============================================================

from typing import List, Set, Dict

import pandas as pd
import altair as alt
import streamlit as st
import mplfinance as mpf
import matplotlib.pyplot as plt


def build_chart(dataframes: List[pd.DataFrame], highlighted: Set[str]) -> alt.Chart:
    """정규화 종가를 라인 차트로 시각화합니다. 선택된 하이라이트는 불투명도를 높입니다."""
    long_frames: List[pd.DataFrame] = []
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
                scale=alt.Scale(zero=False),
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


def build_wide_df(dfs_processed: List[pd.DataFrame]) -> pd.DataFrame:
    """각 자산의 정규화 종가를 열로 갖는 wide 형태의 데이터프레임을 생성합니다."""
    wide = {}
    for df in dfs_processed:
        if "Name" in df.columns:
            wide[str(df["Name"].iloc[0])] = df["Close"].astype(float)
    return pd.DataFrame(wide)


def render_statistics_tab(dfs_processed: List[pd.DataFrame]) -> None:
    """요약 통계 표, 상관행렬 히트맵, 롤링 변동성 차트를 렌더링합니다."""
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


def render_division_tab(dfs_processed: List[pd.DataFrame]) -> None:
    """두 자산 선택 후 비율(Price Ratio)을 시계열로 표시하고, 원자산 가격을 배경으로 겹쳐 표시합니다."""
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

    # Compute MA 20 on the ratio
    ratio_df["MA20"] = ratio_df["Ratio"].rolling(window=20).mean()

    ratio_layer = base + ref

    # Add MA 20 line to ratio chart
    ma_line = (
        alt.Chart(ratio_df)
        .mark_line(color="#1f77b4", strokeWidth=1.5, strokeDash=[5, 3])
        .encode(
            x=alt.X("Date:T"),
            y=alt.Y("MA20:Q", scale=alt.Scale(zero=False)),
            tooltip=[
                alt.Tooltip("Date:T", title="Date"),
                alt.Tooltip("MA20:Q", title="MA 20", format=".3f"),
            ],
        )
    )

    ratio_layer = base + ref + ma_line
    combined = (
        alt.layer(price_layer, ratio_layer)
        .resolve_scale(y="independent")
        .properties(height=400)
    )
    st.altair_chart(combined, use_container_width=True)

    # Legend note for MA
    st.caption("📈 **Red line**: Price Ratio | **Blue dashed**: 20-day Moving Average | **Gray dashed**: Reference (1.0)")


def render_candlestick_tab(
    raw_dfs: List[pd.DataFrame], symbol_to_display: Dict[str, str]
) -> None:
    """mplfinance를 사용하여 선택된 자산의 캔들스틱 차트를 렌더링합니다."""
    st.subheader("Candlestick Chart")

    if not raw_dfs:
        st.info("No data available for candlestick chart.")
        return

    # Build asset selector from available data
    available_assets = []
    asset_df_map = {}
    for df in raw_dfs:
        if "Name" in df.columns and not df.empty:
            name = str(df["Name"].iloc[0])
            display_name = symbol_to_display.get(name, name)
            available_assets.append(display_name)
            asset_df_map[display_name] = df

    if not available_assets:
        st.info("No assets available for candlestick chart.")
        return

    selected_asset = st.selectbox(
        "Select asset for candlestick chart",
        options=available_assets,
        index=0,
        key="candlestick_asset",
    )

    df = asset_df_map[selected_asset].copy()

    # Ensure we have OHLC columns
    required_cols = ["Open", "High", "Low", "Close"]
    missing = [c for c in required_cols if c not in df.columns]
    if missing:
        st.warning(f"Missing columns for candlestick: {missing}")
        return

    # Prepare data for mplfinance (needs DatetimeIndex)
    if not isinstance(df.index, pd.DatetimeIndex):
        if "Date" in df.columns:
            df = df.set_index("Date")
        else:
            df.index = pd.to_datetime(df.index)

    # Select OHLCV columns
    ohlc_cols = ["Open", "High", "Low", "Close"]
    if "Volume" in df.columns:
        ohlc_cols.append("Volume")
        show_volume = True
    else:
        show_volume = False

    df_ohlc = df[ohlc_cols].copy()
    df_ohlc = df_ohlc.dropna()

    if df_ohlc.empty:
        st.warning("No valid OHLC data for candlestick chart.")
        return

    # Chart style options
    col1, col2 = st.columns(2)
    with col1:
        chart_style = st.selectbox(
            "Chart style",
            ["charles", "mike", "nightclouds", "yahoo", "tradingview"],
            index=4,
            key="candle_style",
        )
    with col2:
        show_ma = st.checkbox("Show MA 20", value=True, key="candle_ma20")

    # Build mplfinance chart
    fig, axes = mpf.plot(
        df_ohlc,
        type="candle",
        style=chart_style,
        title=f"{selected_asset} Candlestick",
        ylabel="Price",
        volume=show_volume,
        mav=(20,) if show_ma else (),
        returnfig=True,
        figsize=(12, 7),
        tight_layout=True,
    )

    st.pyplot(fig)
    plt.close(fig)  # Clean up

    # Show recent data table
    with st.expander("📊 Recent OHLC Data"):
        st.dataframe(
            df_ohlc.tail(20).style.format(
                {col: "{:.2f}" for col in ["Open", "High", "Low", "Close"]}
            ),
            use_container_width=True,
        )
