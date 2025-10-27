# =============================================================
# Streamlit app to explore ticker time series with highlighting
# Ensures imports work when launched via Streamlit from the app folder
# =============================================================

import os
import sys
from pathlib import Path

# Make project root importable so `utils` can be resolved
PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import pandas as pd
import streamlit as st
import altair as alt
import json

from utils.data_process import fetch_data, preprocess_data


def build_chart(dataframes: list[pd.DataFrame], highlighted: set[str]) -> alt.Chart:
    # Combine into a single long DataFrame for Altair
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

    # Load asset config from JSON (project root)
    assets_path = PROJECT_ROOT / "assets.json"
    if assets_path.exists():
        try:
            with open(assets_path, "r", encoding="utf-8") as f:
                cfg = json.load(f)
                default_assets = [
                    (
                        a.get("symbol", ""),
                        a.get("name", a.get("symbol", "")),
                        bool(a.get("enabled", True)),
                    )
                    for a in cfg.get("assets", [])
                    if a.get("symbol")
                ]
        except Exception:
            default_assets = []
    else:
        default_assets = []
    if not default_assets:
        # Fallback list if config missing or invalid
        default_assets = [
            ("068270.KS", "Celltrion", True),
            ("GC=F", "Gold", True),
            ("^IXIC", "Nasdaq", True),
            ("^GSPC", "S&P 500", True),
            ("BTC-USD", "Bitcoin", True),
            ("^TNX", "10Y Treasury Yield", True),
            ("^VIX", "VIX", True),
        ]

    st.sidebar.subheader("Select assets")
    selected_symbols: list[str] = []
    symbol_to_display: dict[str, str] = {}
    for symbol, friendly, enabled in default_assets:
        include = st.sidebar.checkbox(friendly, value=enabled, key=f"asset_{symbol}")
        if include:
            selected_symbols.append(symbol)
            symbol_to_display[symbol] = friendly

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

        # Run button to avoid fetching on every control change
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
        params = st.session_state.get(
            "run_params",
            {
                "symbols": tuple(selected_symbols),
                "period": period or "10d",
                "start": start,
                "end": end,
            },
        )
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

    # Apply chosen display names
    symbol_iter = iter(selected_symbols)
    for df in dfs_processed:
        try:
            symbol = next(symbol_iter)
        except StopIteration:
            break
        df["Name"] = symbol_to_display.get(symbol, symbol)

    tab_chart, tab_stats, tab_div = st.tabs(["Chart", "Statistics", "Division"])

    with tab_chart:
        chart = build_chart(dfs_processed, highlighted)
        st.altair_chart(chart, use_container_width=True)

    with tab_stats:
        st.subheader("Summary Statistics")
        # Build a wide DataFrame of normalized close by name
        wide = {}
        for df in dfs_processed:
            if "Name" in df.columns:
                wide[str(df["Name"].iloc[0])] = df["Close"].astype(float)
        wide_df = pd.DataFrame(wide)

        # Compute daily returns
        returns = wide_df.pct_change().dropna(how="all")

        # Annualization factor (approx trading days); for crypto indices use 365, but 252 is fine as a rough standard
        ann_factor = 252

        # Metrics
        vol = returns.std() * (ann_factor**0.5)
        mean_ret = returns.mean() * ann_factor
        sharpe_like = mean_ret / vol.replace({0: pd.NA})

        # Max drawdown per series
        def max_drawdown(series: pd.Series) -> float:
            running_max = series.cummax()
            drawdown = (series / running_max) - 1.0
            return float(drawdown.min()) if not drawdown.empty else float("nan")

        mdd = wide_df.apply(max_drawdown)

        # Pack a table
        summary = pd.DataFrame(
            {
                "Annualized Return": mean_ret,
                "Annualized Volatility": vol,
                "Sharpe-like": sharpe_like,
                "Max Drawdown": mdd,
            }
        ).sort_index()

        # Formatting for display
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
        # Heatmap with annotations
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
                    "Correlation:Q",
                    scale=alt.Scale(domain=[-1, 1], scheme="redblue"),
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
                x="Asset1:N",
                y="Asset2:N",
                text=alt.Text("Correlation:Q", format=".2f"),
            )
        )
        st.altair_chart((heat + text).properties(height=400), use_container_width=True)

        # Rolling 30-day annualized volatility
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

    with tab_div:
        st.subheader("Price Ratio (Division)")
        # Build wide DataFrame of normalized close
        wide = {}
        for df in dfs_processed:
            if "Name" in df.columns:
                wide[str(df["Name"].iloc[0])] = df["Close"].astype(float)
        wide_df = pd.DataFrame(wide)

        if wide_df.shape[1] < 2:
            st.info("Select at least two assets to compute a ratio.")
        else:
            names = list(wide_df.columns)
            col1, col2 = st.columns(2)
            with col1:
                asset_a = st.selectbox("Asset A (numerator)", options=names, index=0)
            with col2:
                asset_b = st.selectbox(
                    "Asset B (denominator)",
                    options=names,
                    index=1 if len(names) > 1 else 0,
                )

            # Determine available date range for both series
            pair = wide_df[[asset_a, asset_b]].dropna(how="any")
            if pair.empty:
                st.warning("No overlapping dates between the selected assets.")
            else:
                min_date = pair.index.min().date()
                max_date = pair.index.max().date()
                r1, r2 = st.columns(2)
                with r1:
                    dr_start = st.date_input(
                        "Start date",
                        value=min_date,
                        min_value=min_date,
                        max_value=max_date,
                    )
                with r2:
                    dr_end = st.date_input(
                        "End date",
                        value=max_date,
                        min_value=min_date,
                        max_value=max_date,
                    )

                if dr_start > dr_end:
                    st.warning("Start date must be on or before end date.")
                else:
                    mask = (pair.index.date >= dr_start) & (pair.index.date <= dr_end)
                    sub = pair.loc[mask]
                    if sub.empty:
                        st.warning("No data in the selected date range.")
                    else:
                        ratio = (sub[asset_a] / sub[asset_b]).rename(
                            f"{asset_a} / {asset_b}"
                        )
                        ratio_df = ratio.to_frame(name="Ratio").copy()
                        ratio_df["Date"] = ratio_df.index

                        base = (
                            alt.Chart(ratio_df)
                            .mark_line(color="#d62728", strokeWidth=2.5)
                            .encode(
                                x=alt.X("Date:T", title="Date"),
                                y=alt.Y(
                                    "Ratio:Q",
                                    title="Price Ratio",
                                    scale=alt.Scale(zero=False),
                                ),
                                tooltip=[
                                    alt.Tooltip("Date:T", title="Date"),
                                    alt.Tooltip("Ratio:Q", title="Ratio", format=".3f"),
                                ],
                            )
                        )

                        # Reference line at 1.0
                        ref = (
                            alt.Chart(pd.DataFrame({"y": [1]}))
                            .mark_rule(color="gray", strokeDash=[4, 4])
                            .encode(y="y:Q")
                        )

                        # Overlay original asset prices (normalized) as background
                        prices = sub.copy()
                        prices["Date"] = prices.index
                        prices_long = prices.melt(
                            id_vars=["Date"], var_name="Name", value_name="Price"
                        )
                        price_layer = (
                            alt.Chart(prices_long)
                            .mark_line(opacity=0.35)
                            .encode(
                                x=alt.X("Date:T", title="Date"),
                                y=alt.Y(
                                    "Price:Q",
                                    title="Normalized Price",
                                    scale=alt.Scale(zero=False),
                                ),
                                color=alt.Color(
                                    "Name:N", legend=alt.Legend(title="Assets")
                                ),
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


if __name__ == "__main__":
    main()
