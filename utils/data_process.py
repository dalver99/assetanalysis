# A full pipeline for preprocessing data that come in an array of dataframes
import pandas as pd
import yfinance as yf


def preprocess_data(dataframes: list[pd.DataFrame]) -> list[pd.DataFrame]:
    # First, forward-fill the data in each DataFrame to fill in any missing values
    processed = []
    for df in dataframes:
        df_filled = df.ffill()  # Forward fill missing values within each dataframe
        # Then backward fill to fill in any missing values at the start of the dataframe
        df_filled = df_filled.bfill()
        processed.append(df_filled)

    # Now, find the union of all dates across all dataframes
    common_dates = processed[0].index
    for df in processed[1:]:
        common_dates = common_dates.union(df.index)

    # Reindex all dataframes to the common set of dates and apply forward-fill again
    final_processed = []
    for df in processed:
        df_new = df.reindex(common_dates).ffill()  # Reindex and ffill missing dates
        # Backfill
        df_new = df_new.bfill()
        # Normalize the 'Close' column
        # Normalize 'Close' by dividing by the first non-null, non-zero value
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
    """Fetch price history for a list of tickers.

    If start (and optional end) are provided, use explicit date range; otherwise use period.
    Optionally adds a "Name" column with the ticker symbol for downstream plotting.
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
