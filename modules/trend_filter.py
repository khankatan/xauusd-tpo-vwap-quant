import numpy as np
import pandas as pd


def apply_trend_filter(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()

    df['ema_fast'] = df['close'].ewm(span=32, adjust=False).mean()
    df['ema_slow'] = df['close'].ewm(span=96, adjust=False).mean()
    df['ema_macro'] = df['close'].ewm(span=288, adjust=False).mean()  # เทรนด์ 3 วัน (H1/H4 Proxy)

    # Kaufman Efficiency Ratio (KER 20 แท่ง): วัดความตรงของเทรนด์ (ใกล้ 1 = เทรนด์ชัด, ใกล้ 0 = ฟันปลา/Sideway)
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

    # ต้องผ่านทั้ง ADX >= 20, เรียงตัวตาม EMA Macro และ Efficiency Ratio >= 0.25 จึงจะถือว่าเป็น Trend จริง
    is_clean_trend = (df['adx'] >= 20) & (df['efficiency_ratio'] >= 0.25)

    conditions = [
        is_clean_trend & (df['close'] > df['vwap']) & (df['ema_fast'] > df['ema_slow']) & (df['close'] > df['ema_macro']),
        is_clean_trend & (df['close'] < df['vwap']) & (df['ema_fast'] < df['ema_slow']) & (df['close'] < df['ema_macro']),
    ]
    choices = ['TREND_UP', 'TREND_DOWN']
    df['regime'] = np.select(conditions, choices, default='BALANCE_SIDEWAY')
    return df
