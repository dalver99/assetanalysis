# =============================================================
# 데이터 전처리 파이프라인
# - 다수의 데이터프레임을 받아 결측 보간, 날짜 인덱스 통합, 종가 정규화 수행
# =============================================================
import pandas as pd
import yfinance as yf


def preprocess_data(dataframes: list[pd.DataFrame]) -> list[pd.DataFrame]:
    """입력 데이터프레임 배열을 전처리하여 동일한 날짜축과 정규화된 종가로 반환합니다.

    단계:
    1) 앞/뒤 채우기로 결측치 보간
    2) 날짜 인덱스 합집합으로 재인덱싱 후 보간
    3) 첫 유효·비영점 종가 기준으로 정규화
    """
    # 각 프레임의 결측을 앞 채우기
    processed = []
    for df in dataframes:
        df_filled = df.ffill()  # Forward fill missing values within each dataframe
        # 시작 구간 보완을 위해 뒤 채우기
        df_filled = df_filled.bfill()
        processed.append(df_filled)

    # 모든 프레임의 날짜 인덱스를 합집합으로 결합
    common_dates = processed[0].index
    for df in processed[1:]:
        common_dates = common_dates.union(df.index)

    # 공통 날짜로 재인덱싱 후 다시 앞/뒤 채우기
    final_processed = []
    for df in processed:
        df_new = df.reindex(common_dates).ffill()  # Reindex and ffill missing dates
        # Backfill
        df_new = df_new.bfill()
        # 첫 유효·비영점 종가로 정규화
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
    """티커 목록의 가격 이력을 조회합니다.

    - start/end가 주어지면 해당 구간을, 없으면 period(예: "10d")를 사용합니다.
    - 시각화를 위해 티커 문자열을 Name 컬럼으로 추가할 수 있습니다.
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
