import numpy as np
import pandas as pd


def apply_trend_filter(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    
    # ความชันของเส้น VWAP และ EMA50/EMA200 สำหรับวัดโครงสร้างเทรนด์
    df['ema_fast'] = df['close'].ewm(span=32, adjust=False).mean()
    df['ema_slow'] = df['close'].ewm(span=96, adjust=False).mean()
    df['vwap_slope'] = (df['vwap'] - df['vwap'].shift(4)) / df['atr']

    # ADX แบบย่อเพื่อแยกตลาดวิ่งเป็นเทรนด์ (Imbalance) กับออกข้าง (Balance)
    up_move = df['high'].diff()
    down_move = -df['low'].diff()
    plus_dm = np.where((up_move > down_move) & (up_move > 0), up_move, 0.0)
    minus_dm = np.where((down_move > up_move) & (down_move > 0), down_move, 0.0)

    tr_smooth = df['atr'] * 14
    plus_di = 100 * (pd.Series(plus_dm).ewm(span=14).mean() / tr_smooth)
    minus_di = 100 * (pd.Series(minus_dm).ewm(span=14).mean() / tr_smooth)
    dx = (np.abs(plus_di - minus_di) / (plus_di + minus_di).replace(0, np.nan)) * 100
    df['adx'] = dx.ewm(span=14).mean().fillna(20)

    conditions = [
        (df['adx'] >= 22) & (df['close'] > df['vwap']) & (df['ema_fast'] > df['ema_slow']),
        (df['adx'] >= 22) & (df['close'] < df['vwap']) & (df['ema_fast'] < df['ema_slow']),
    ]
    choices = ['TREND_UP', 'TREND_DOWN']
    df['regime'] = np.select(conditions, choices, default='BALANCE_SIDEWAY')
    return df
