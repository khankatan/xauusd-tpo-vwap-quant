import numpy as np
import pandas as pd


def compute_kama(series: pd.Series, er_period: int = 20, fast_sc: int = 4, slow_sc: int = 80) -> pd.Series:
    close_vals = series.values
    n = len(close_vals)
    kama = np.full(n, np.nan)
    if n <= er_period:
        return pd.Series(close_vals, index=series.index)

    fast_alpha = 2.0 / (fast_sc + 1.0)
    slow_alpha = 2.0 / (slow_sc + 1.0)
    kama[er_period] = close_vals[er_period]

    for i in range(er_period + 1, n):
        change = abs(close_vals[i] - close_vals[i - er_period])
        volatility = np.sum(np.abs(np.diff(close_vals[i - er_period:i + 1])))
        er = (change / volatility) if volatility > 0 else 0.0
        sc = (er * (fast_alpha - slow_alpha) + slow_alpha) ** 2
        kama[i] = kama[i - 1] + sc * (close_vals[i] - kama[i - 1])

    return pd.Series(kama, index=series.index).bfill()


def apply_trend_filter(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()

    df['ema_fast'] = df['close'].ewm(span=32, adjust=False).mean()
    df['ema_slow'] = df['close'].ewm(span=96, adjust=False).mean()
    df['ema_macro'] = df['close'].ewm(span=288, adjust=False).mean()
    df['kama_macro'] = compute_kama(df['close'], er_period=24, fast_sc=6, slow_sc=90)

    # Kaufman Efficiency Ratio (KER 20 แท่ง)
    net_change = (df['close'] - df['close'].shift(20)).abs()
    sum_volatility = df['close'].diff().abs().rolling(20).sum().replace(0, np.nan)
    df['efficiency_ratio'] = (net_change / sum_volatility).fillna(0.2)

    up_move = df['high'].diff()
    down_move = -df['low'].diff()
    plus_dm = np.where((up_move > down_move) & (up_move > 0), up_move, 0.0)
    minus_dm = np.where((down_move > up_move) & (down_move > 0), down_move, 0.0)

    tr_smooth = df['atr'] * 14
    plus_di = 100 * (pd.Series(plus_dm).ewm(span=14).mean() / tr_smooth)
    minus_di = 100 * (pd.Series(minus_dm).ewm(span=14).mean() / tr_smooth)
    dx = (np.abs(plus_di - minus_di) / (plus_di + minus_di).replace(0, np.nan)) * 100
    df['adx'] = dx.ewm(span=14).mean().fillna(20)

    is_clean_trend = (df['adx'] >= 20) & (df['efficiency_ratio'] >= 0.25)

    conditions = [
        is_clean_trend & (df['close'] > df['vwap']) & (df['ema_fast'] > df['ema_slow']) & (df['close'] > df['ema_macro']),
        is_clean_trend & (df['close'] < df['vwap']) & (df['ema_fast'] < df['ema_slow']) & (df['close'] < df['ema_macro']),
    ]
    choices = ['TREND_UP', 'TREND_DOWN']
    df['regime'] = np.select(conditions, choices, default='BALANCE_SIDEWAY')
    return df
