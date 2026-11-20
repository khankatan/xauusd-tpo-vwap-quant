import numpy as np
import pandas as pd


def attach_macro_sentiment(df: pd.DataFrame, use_live_fetch: bool = True) -> pd.DataFrame:
    df = df.copy()
    df['dxy_bias'] = 0
    df['oi_regime'] = 'NEUTRAL'

    if use_live_fetch:
        try:
            import yfinance as yf
            start_dt = (df['timestamp'].min() - pd.Timedelta(days=10)).strftime('%Y-%m-%d')
            end_dt = (df['timestamp'].max() + pd.Timedelta(days=2)).strftime('%Y-%m-%d')

            dxy = yf.download('DX-Y.NYB', start=start_dt, end=end_dt, interval='1d', progress=False)
            gc = yf.download('GC=F', start=start_dt, end=end_dt, interval='1d', progress=False)

            if not dxy.empty:
                if isinstance(dxy.columns, pd.MultiIndex):
                    dxy.columns = dxy.columns.get_level_values(0)
                dxy = dxy.reset_index()
                dxy['date'] = pd.to_datetime(dxy['Date']).dt.date
                dxy['dxy_ret'] = dxy['Close'].pct_change().shift(1)
                dxy['dxy_bias'] = np.where(dxy['dxy_ret'] < -0.0015, 1, np.where(dxy['dxy_ret'] > 0.0015, -1, 0))
                dxy_dict = dict(zip(dxy['date'], dxy['dxy_bias']))
                df['dxy_bias'] = df['date'].map(dxy_dict).fillna(0).astype(int)

            if not gc.empty:
                if isinstance(gc.columns, pd.MultiIndex):
                    gc.columns = gc.columns.get_level_values(0)
                gc = gc.reset_index()
                gc['date'] = pd.to_datetime(gc['Date']).dt.date
                gc['price_chg'] = gc['Close'].diff().shift(1)
                gc['vol_chg'] = gc['Volume'].diff().shift(1)

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

    candle_delta = np.where(df['close'] >= df['open'], df['volume'], -df['volume'])
    rolling_delta = pd.Series(candle_delta).rolling(16).sum()
    delta_norm = (rolling_delta / (df['volume'].rolling(16).sum().replace(0, np.nan))).fillna(0).clip(-1, 1)

    oi_score = df['oi_regime'].map({
        'NEW_LONGS': 0.35,
        'SHORT_COVERING': 0.10,
        'NEW_SHORTS': -0.35,
        'LONG_LIQUIDATION': -0.10,
        'NEUTRAL': 0.0
    }).fillna(0.0)

    df['ls_sentiment'] = (0.35 * df['dxy_bias'] + 0.30 * oi_score + 0.35 * delta_norm).clip(-1.0, 1.0)
    return df
