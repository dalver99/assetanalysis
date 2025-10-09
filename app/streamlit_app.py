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
        # Offer download of current assets config for easy editing
        try:
            with open(assets_path, "rb") as f:
                st.sidebar.download_button(
                    "Download assets.json", f, file_name="assets.json"
                )
        except Exception:
            pass
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

    chart = build_chart(dfs_processed, highlighted)
    st.altair_chart(chart, use_container_width=True)

    # Export current assets config for easy modification
    try:
        with open(assets_path, "rb") as f:
            st.sidebar.download_button(
                "Download assets.json", f, file_name="assets.json"
            )
    except Exception:
        pass


if __name__ == "__main__":
    main()
