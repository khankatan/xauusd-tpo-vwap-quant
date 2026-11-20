import numpy as np
import pandas as pd


def compute_indicators(df: pd.DataFrame, tick_size: float = 0.50) -> pd.DataFrame:
    df = df.copy()
    df['timestamp'] = pd.to_datetime(df['timestamp'])
    df = df.sort_values('timestamp').reset_index(drop=True)
    df['date'] = df['timestamp'].dt.date

    # 1. ATR (14)
    high_low = df['high'] - df['low']
    high_close = (df['high'] - df['close'].shift()).abs()
    low_close = (df['low'] - df['close'].shift()).abs()
    tr = pd.concat([high_low, high_close, low_close], axis=1).max(axis=1)
    df['atr'] = tr.ewm(span=14, adjust=False).mean()

    # 2. Rolling 24-Hour VWAP (96 แท่ง M15)
    df['typical_price'] = (df['high'] + df['low'] + df['close']) / 3.0
    df['pv'] = df['typical_price'] * df['volume']
    df['pv2'] = (df['typical_price'] ** 2) * df['volume']

    roll_vol = df['volume'].rolling(96, min_periods=20).sum().replace(0, np.nan)
    roll_pv = df['pv'].rolling(96, min_periods=20).sum()
    roll_pv2 = df['pv2'].rolling(96, min_periods=20).sum()

    df['vwap'] = roll_pv / roll_vol
    variance = (roll_pv2 / roll_vol) - (df['vwap'] ** 2)
    df['vwap_std'] = np.sqrt(variance.clip(lower=0))
    df['vwap_upper_1'] = df['vwap'] + df['vwap_std']
    df['vwap_lower_1'] = df['vwap'] - df['vwap_std']
    df['vwap_upper_2'] = df['vwap'] + (2.0 * df['vwap_std'])
    df['vwap_lower_2'] = df['vwap'] - (2.0 * df['vwap_std'])

    # 3. Session TPO Profile (มาตรฐาน 32 แท่ง = 8 ชม. ตามสูตร V7 Core)
    poc_list, vah_list, val_list = [], [], []
    lookback = 32

    for i in range(len(df)):
        if i < lookback:
            poc_list.append(df['close'].iloc[i])
            vah_list.append(df['high'].iloc[i])
            val_list.append(df['low'].iloc[i])
            continue

        window = df.iloc[i - lookback:i]
        p_min = np.floor(window['low'].min() / tick_size) * tick_size
        p_max = np.ceil(window['high'].max() / tick_size) * tick_size
        bins = np.arange(p_min, p_max + tick_size, tick_size)

        if len(bins) < 3:
            poc_list.append(window['close'].mean())
            vah_list.append(window['high'].max())
            val_list.append(window['low'].min())
            continue

        tpo_counts = np.zeros(len(bins) - 1)
        for _, row in window.iterrows():
            mask = (bins[:-1] <= row['high']) & (bins[1:] >= row['low'])
            tpo_counts[mask] += 1

        poc_idx = int(np.argmax(tpo_counts))
        poc_price = (bins[poc_idx] + bins[poc_idx + 1]) / 2.0

        total_tpo = tpo_counts.sum()
        target_tpo = total_tpo * 0.70
        current_tpo = tpo_counts[poc_idx]
        low_idx, high_idx = poc_idx, poc_idx

        while current_tpo < target_tpo and (low_idx > 0 or high_idx < len(tpo_counts) - 1):
            up_val = tpo_counts[high_idx + 1] if high_idx + 1 < len(tpo_counts) else -1
            dn_val = tpo_counts[low_idx - 1] if low_idx - 1 >= 0 else -1
            if up_val >= dn_val and high_idx + 1 < len(tpo_counts):
                high_idx += 1
                current_tpo += up_val
            elif low_idx - 1 >= 0:
                low_idx -= 1
                current_tpo += dn_val
            else:
                break

        poc_list.append(round(poc_price, 2))
        vah_list.append(round(bins[high_idx + 1], 2))
        val_list.append(round(bins[low_idx], 2))

    df['tpo_poc'] = poc_list
    df['tpo_vah'] = vah_list
    df['tpo_val'] = val_list
    return df
