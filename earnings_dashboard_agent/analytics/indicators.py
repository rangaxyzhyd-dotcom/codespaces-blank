"""Technical indicators calculated from OHLCV price series."""

import pandas as pd


def simple_moving_average(prices: pd.Series, window: int = 20) -> pd.Series:
    if window < 1:
        raise ValueError("window must be at least 1")
    return prices.rolling(window=window, min_periods=window).mean()


def relative_strength_index(prices: pd.Series, window: int = 14) -> pd.Series:
    if window < 1:
        raise ValueError("window must be at least 1")
    changes = prices.diff()
    gains = changes.clip(lower=0)
    losses = -changes.clip(upper=0)
    average_gains = gains.ewm(alpha=1 / window, min_periods=window, adjust=False).mean()
    average_losses = losses.ewm(alpha=1 / window, min_periods=window, adjust=False).mean()
    relative_strength = average_gains / average_losses
    rsi = 100 - (100 / (1 + relative_strength))
    return rsi.mask((average_losses == 0) & (average_gains > 0), 100).mask(
        (average_losses == 0) & (average_gains == 0), 50
    )


def average_directional_index(ohlcv: pd.DataFrame, window: int = 14) -> pd.Series:
    if window < 1:
        raise ValueError("window must be at least 1")
    required = {"High", "Low", "Close"}
    if not required.issubset(ohlcv.columns):
        raise ValueError(f"OHLCV data must include {', '.join(sorted(required))}")
    high, low, close = ohlcv["High"], ohlcv["Low"], ohlcv["Close"]
    upward = high.diff()
    downward = -low.diff()
    positive_dm = upward.where((upward > downward) & (upward > 0), 0.0)
    negative_dm = downward.where((downward > upward) & (downward > 0), 0.0)
    true_range = pd.concat(
        [high - low, (high - close.shift()).abs(), (low - close.shift()).abs()], axis=1
    ).max(axis=1)
    smoothed_tr = true_range.ewm(alpha=1 / window, min_periods=window, adjust=False).mean()
    positive_di = 100 * positive_dm.ewm(alpha=1 / window, min_periods=window, adjust=False).mean() / smoothed_tr
    negative_di = 100 * negative_dm.ewm(alpha=1 / window, min_periods=window, adjust=False).mean() / smoothed_tr
    denominator = positive_di + negative_di
    dx = (100 * (positive_di - negative_di).abs() / denominator).where(denominator != 0)
    return dx.ewm(alpha=1 / window, min_periods=window, adjust=False).mean()


def relative_volume(volumes: pd.Series, window: int = 20) -> float | None:
    if window < 1:
        raise ValueError("window must be at least 1")
    if len(volumes.dropna()) < window + 1:
        return None
    average = volumes.iloc[-window - 1:-1].mean()
    if pd.isna(average) or average == 0:
        return None
    return float(volumes.iloc[-1] / average)


def session_vwap(intraday: pd.DataFrame) -> float | None:
    required = {"High", "Low", "Close", "Volume"}
    if intraday.empty or not required.issubset(intraday.columns):
        return None
    prices = (intraday["High"] + intraday["Low"] + intraday["Close"]) / 3
    volume = intraday["Volume"].fillna(0)
    total_volume = volume.sum()
    if total_volume <= 0:
        return None
    return float((prices * volume).sum() / total_volume)


def annualized_volatility(prices: pd.Series, periods_per_year: int = 252) -> float:
    if periods_per_year < 1:
        raise ValueError("periods_per_year must be at least 1")
    returns = prices.pct_change().dropna()
    if returns.empty:
        return 0.0
    return float(returns.std() * periods_per_year**0.5)