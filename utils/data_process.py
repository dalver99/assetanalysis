# =============================================================
# 데이터 전처리 파이프라인: 다수의 데이터프레임 입력 처리
# - 결측치 보간 (앞/뒤 채우기)
# - 공통 날짜 인덱스 통합 및 재인덱싱
# - 종가 정규화 (첫 유효·비영점 값 기준)
# =============================================================
import pandas as pd
import yfinance as yf


def preprocess_data(dataframes: list[pd.DataFrame]) -> list[pd.DataFrame]:
    # 각 데이터프레임의 결측치를 우선 앞쪽 값으로 채웁니다.
    processed = []
    for df in dataframes:
        df_filled = df.ffill()  # 데이터프레임 내부 결측치 앞 채우기
        # 시작 구간의 결측을 보완하기 위해 뒤 채우기를 추가로 수행합니다.
        df_filled = df_filled.bfill()
        processed.append(df_filled)

    # 모든 데이터프레임의 날짜 인덱스를 합집합으로 결합합니다.
    common_dates = processed[0].index
    for df in processed[1:]:
        common_dates = common_dates.union(df.index)

    # 공통 날짜 인덱스로 재인덱싱 후, 남은 결측을 앞/뒤로 한 번 더 채웁니다.
    final_processed = []
    for df in processed:
        df_new = df.reindex(common_dates).ffill()  # 재인덱싱 및 앞 채우기
        # 뒤 채우기
        df_new = df_new.bfill()
        # 종가 'Close'를 첫 번째 유효(NA가 아니고 0이 아닌) 값으로 정규화합니다.
        valid_close = df_new["Close"].dropna()
        nonzero_close = valid_close[valid_close.ne(0)]
        first_nonzero = nonzero_close.iloc[0] if not nonzero_close.empty else 1.0
        df_new["Close"] = df_new["Close"] / first_nonzero
        final_processed.append(df_new)

    return final_processed


def fetch_data(
    tickers: list[str],
    period: str = "10d",
    start: str | pd.Timestamp | None = None,
    end: str | pd.Timestamp | None = None,
    add_name: bool = True,
) -> list[pd.DataFrame]:
    """주어진 티커 목록의 가격 이력을 조회합니다.

    start(와 선택적 end)가 주어지면 해당 날짜 구간을 사용하고,
    그렇지 않으면 period(예: "10d")를 사용합니다.
    시각화를 위해 티커를 "Name" 컬럼으로 추가할 수 있습니다.
    """
    dataframes: list[pd.DataFrame] = []
    for ticker in tickers:
        ticker_client = yf.Ticker(ticker)
        if start is not None:
            hist = ticker_client.history(start=start, end=end)
        else:
            hist = ticker_client.history(period=period)

        if hist is None or hist.empty:
            continue

        if add_name:
            hist["Name"] = ticker
        dataframes.append(hist)

    return dataframes
