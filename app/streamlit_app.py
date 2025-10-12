# =============================================================
# 스트림릿 앱: 자산 시계열 시각화 및 통계 분석
# - 하이라이트 기능 포함
# - 앱 폴더에서 실행 시 모듈 임포트를 위해 경로를 설정합니다.
# =============================================================

import os
import sys
from pathlib import Path

# `utils` 모듈 임포트를 위해 프로젝트 루트를 파이썬 경로에 추가
PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import pandas as pd
import streamlit as st
import altair as alt
import json

from utils.data_process import fetch_data, preprocess_data


def build_chart(dataframes: list[pd.DataFrame], highlighted: set[str]) -> alt.Chart:
    # Altair를 위해 하나의 긴(long) 데이터프레임으로 결합
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
                scale=alt.Scale(zero=False),  # 도메인 축소; 0에서 큰 간격 방지
            ),
            color=alt.Color(
                "Name:N",
                legend=alt.Legend(title="티커"),
                scale=alt.Scale(scheme="tableau10"),
            ),
            tooltip=[
                "Name:N",
                alt.Tooltip("Date:T", title="Date"),
                alt.Tooltip("Close:Q", title="종가", format=".3f"),
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

    # JSON(프로젝트 루트)에서 자산 구성 로드
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
        # 구성 누락 또는 유효하지 않은 경우 기본 목록
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

    date_mode = st.sidebar.radio("날짜 선택 모드", ["Period", "Range"], horizontal=True)
    if date_mode == "Period":
        period = st.sidebar.selectbox(
            "기간",
            ["5d", "10d", "1mo", "3mo", "6mo", "1y", "2y", "5y", "10y", "ytd", "max"],
            index=1,
        )
        start = None
        end = None
    else:
        start = st.sidebar.date_input("시작 날짜")
        end = st.sidebar.date_input("종료 날짜")
        period = None

        # 모든 컨트롤 변경 시 가져오기 방지를 위한 실행 버튼
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
        st.info("컨트롤을 조정하고 실행 버튼을 클릭하여 가져오고 차트를 그립니다.")
        return

    # 하이라이트 선택 (표시 이름별)
    st.sidebar.subheader("Highlight")
    highlight_options = [symbol_to_display[s] for s in selected_symbols]
    highlighted = set(
        st.sidebar.multiselect(
            "하이라이트 (선택 사항)", options=highlight_options, default=[]
        )
    )

    # 데이터 가져오기 및 전처리
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
        st.warning("데이터를 가져오지 못했습니다. 티커 또는 날짜 범위를 확인하세요.")
        return

    with st.spinner("전처리 중..."):
        dfs_processed = preprocess_data(dfs)

    # 선택한 표시 이름 적용
    symbol_iter = iter(selected_symbols)
    for df in dfs_processed:
        try:
            symbol = next(symbol_iter)
        except StopIteration:
            break
        df["Name"] = symbol_to_display.get(symbol, symbol)

    tab_chart, tab_stats = st.tabs(["Chart", "Statistics"])

    with tab_chart:
        chart = build_chart(dfs_processed, highlighted)
        st.altair_chart(chart, use_container_width=True)

    with tab_stats:
        st.subheader("요약 통계")
        # Build a wide DataFrame of normalized close by name
        wide = {}
        for df in dfs_processed:
            if "Name" in df.columns:
                wide[str(df["Name"].iloc[0])] = df["Close"].astype(float)
        wide_df = pd.DataFrame(wide)

        # 일간 수익 계산
        returns = wide_df.pct_change().dropna(how="all")

        # 연간화 요인 (약 거래일); 암호화폐 지수의 경우 365를 사용하지만, 252는 근사치로 적합합니다.
        ann_factor = 252

        # 지표
        vol = returns.std() * (ann_factor**0.5)
        mean_ret = returns.mean() * ann_factor
        sharpe_like = mean_ret / vol.replace({0: pd.NA})

        # 시리즈당 최대 하락
        def max_drawdown(series: pd.Series) -> float:
            running_max = series.cummax()
            drawdown = (series / running_max) - 1.0
            return float(drawdown.min()) if not drawdown.empty else float("nan")

        mdd = wide_df.apply(max_drawdown)

        # 테이블 패킹
        summary = pd.DataFrame(
            {
                "Annualized Return": mean_ret,
                "Annualized Volatility": vol,
                "Sharpe-like": sharpe_like,
                "Max Drawdown": mdd,
            }
        ).sort_index()

        # 표시 형식 지정
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

        st.subheader("상관 행렬 (일간 수익)")
        corr = returns.corr()
        # 주석이 있는 히트맵
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

        # 30일 연간화 변동성
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


if __name__ == "__main__":
    main()
