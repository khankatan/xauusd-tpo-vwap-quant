import numpy as np
import pandas as pd


def attach_macro_sentiment(df: pd.DataFrame, use_live_fetch: bool = True) -> pd.DataFrame:
    df = df.copy()
    df['dxy_bias'] = 0        # +1 = DXY อ่อนค่า (หนุนทองขึ้น), -1 = DXY แข็งค่า (กดดันทองลง)
    df['oi_regime'] = 'NEUTRAL' # NEW_LONGS, NEW_SHORTS, SHORT_COVERING, LONG_LIQUIDATION
    df['ls_sentiment'] = 0.0  # คะแนนรวม -1.0 ถึง +1.0

    if use_live_fetch:
        try:
            import yfinance as yf
            start_dt = (df['timestamp'].min() - pd.Timedelta(days=5)).strftime('%Y-%m-%d')
            end_dt = (df['timestamp'].max() + pd.Timedelta(days=2)).strftime('%Y-%m-%d')

            dxy = yf.download('DX-Y.NYB', start=start_dt, end=end_dt, interval='1h', progress=False)
            gc = yf.download('GC=F', start=start_dt, end=end_dt, interval='1d', progress=False)

            if not dxy.empty:
                dxy = dxy.reset_index()
                dt_col = 'Datetime' if 'Datetime' in dxy.columns else 'Date'
                dxy['ts'] = pd.to_datetime(dxy[dt_col]).dt.tz_localize(None)
                dxy['dxy_ret'] = dxy['Close'].pct_change(4)
                dxy_map = dxy[['ts', 'dxy_ret']].dropna().sort_values('ts')

                df = pd.merge_asof(
                    df.sort_values('timestamp'),
                    dxy_map,
                    left_on='timestamp',
                    right_on='ts',
                    direction='backward'
                )
                df['dxy_bias'] = np.where(df['dxy_ret'] < -0.001, 1, np.where(df['dxy_ret'] > 0.001, -1, 0))
                df.drop(columns=['ts', 'dxy_ret'], inplace=True, errors='ignore')

            if not gc.empty:
                gc = gc.reset_index()
                gc['date'] = pd.to_datetime(gc['Date']).dt.date
                gc['price_chg'] = gc['Close'].diff()
                gc['vol_chg'] = gc['Volume'].diff()

                # จำลองพฤติกรรม Open Interest + Price Action ตามหลัก Futures Market
                conds = [
                    (gc['price_chg'] > 0) & (gc['vol_chg'] > 0),
                    (gc['price_chg'] < 0) & (gc['vol_chg'] > 0),
                    (gc['price_chg'] > 0) & (gc['vol_chg'] <= 0),
                    (gc['price_chg'] < 0) & (gc['vol_chg'] <= 0),
                ]
                labs = ['NEW_LONGS', 'NEW_SHORTS', 'SHORT_COVERING', 'LONG_LIQUIDATION']
                gc['oi_regime'] = np.select(conds, labs, default='NEUTRAL')
                oi_dict = dict(zip(gc['date'], gc['oi_regime']))
                df['oi_regime'] = df['date'].map(oi_dict).fillna('NEUTRAL')

        except Exception:
            pass

    # Fallback / Internal Order-Flow Sentiment Proxy (คำนวณจาก Delta Volume & TPO Skew)
    candle_delta = np.where(df['close'] >= df['open'], df['volume'], -df['volume'])
    rolling_delta = pd.Series(candle_delta).rolling(16).sum()
    delta_norm = (rolling_delta / (df['volume'].rolling(16).sum().replace(0, np.nan))).fillna(0).clip(-1, 1)

    oi_score = df['oi_regime'].map({
        'NEW_LONGS': 0.4,
        'SHORT_COVERING': 0.1,
        'NEW_SHORTS': -0.4,
        'LONG_LIQUIDATION': -0.1,
        'NEUTRAL': 0.0
    }).fillna(0.0)

    df['ls_sentiment'] = (0.4 * df['dxy_bias'] + 0.3 * oi_score + 0.3 * delta_norm).clip(-1.0, 1.0)
    return df
