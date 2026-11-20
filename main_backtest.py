import os
import pandas as pd
from modules.indicators import compute_indicators
from modules.trend_filter import apply_trend_filter
from modules.macro_sentiment import attach_macro_sentiment
from modules.risk_manager import RiskManager
from modules.strategy import TpoVwapStrategy


def load_data(filepath: str) -> pd.DataFrame:
    df = pd.read_csv(filepath)
    df.columns = [c.strip().lower() for c in df.columns]
    time_col = next((c for c in ['timestamp', 'time', 'datetime', 'date'] if c in df.columns), None)
    if time_col != 'timestamp':
        df.rename(columns={time_col: 'timestamp'}, inplace=True)
    if 'volume' not in df.columns:
        df['volume'] = df.get('tick_volume', 100.0)
    return df


def run_backtest(csv_path: str = 'data/xauusd_m15_history.csv', initial_capital: float = 100000.0):
    print("1. กำลังโหลดข้อมูลและคำนวณ Rolling 24H VWAP + Session TPO...")
    df = load_data(csv_path)
    df = compute_indicators(df)
    df = apply_trend_filter(df)
    df = attach_macro_sentiment(df, use_live_fetch=True)

    risk_mgr = RiskManager(initial_capital=initial_capital)
    strategy = TpoVwapStrategy()

    open_positions = []
    closed_trades = []
    equity_records = []
    trade_id_counter = 1

    # เริ่มรันตั้งแต่แท่งที่ 100 เพื่อให้ Rolling 24H VWAP (96 แท่ง) คำนวณครบสมบูรณ์ก่อนเปิดไม้แรก
    print("2. กำลังรัน Simulation V3 (Pyramiding Risk <= 0.25% | Daily DD Limit <= 3%)...")
    for i in range(100, len(df)):
        row = df.iloc[i]
        prev_row = df.iloc[i - 1]
        risk_mgr.on_new_bar(row['date'], risk_mgr.equity)

        # ปิดออเดอร์ทั้งหมดทันทีหากชน Daily DD Circuit Breaker หรือก่อนตลาดปิดวันศุกร์ 20:00 UTC
        is_friday_close = (row['timestamp'].weekday() == 4 and row['timestamp'].hour >= 20)
        force_close_reason = None
        if risk_mgr.daily_halted:
            force_close_reason = 'DAILY_DD_CIRCUIT_BREAKER'
        elif is_friday_close:
            force_close_reason = 'FRIDAY_WEEKEND_CLOSE'

        remaining_positions = []
        for pos in open_positions:
            exit_price = None
            exit_reason = None

            if force_close_reason:
                exit_price = row['close']
                exit_reason = force_close_reason
            elif pos['side'] == 'BUY' and row['low'] <= pos['current_sl']:
                exit_price = pos['current_sl']
                exit_reason = 'STEP_LOCK_SL'
            elif pos['side'] == 'SELL' and row['high'] >= pos['current_sl']:
                exit_price = pos['current_sl']
                exit_reason = 'STEP_LOCK_SL'

            if exit_price is not None:
                price_diff = (exit_price - pos['entry']) if pos['side'] == 'BUY' else (pos['entry'] - exit_price)
                gross_pnl = price_diff * risk_mgr.contract_size * pos['lot']
                comm = risk_mgr.commission_per_lot * pos['lot']
                net_pnl = gross_pnl - comm
                risk_mgr.equity += net_pnl

                closed_trades.append({
                    'trade_id': pos['id'],
                    'entry_time': pos['entry_time'],
                    'exit_time': row['timestamp'],
                    'side': pos['side'],
                    'setup': pos['setup'],
                    'regime': pos['regime'],
                    'sentiment_score': pos['sentiment'],
                    'lot': pos['lot'],
                    'entry_price': pos['entry'],
                    'initial_sl': pos['initial_sl'],
                    'exit_price': round(exit_price, 2),
                    'exit_reason': exit_reason,
                    'net_pnl_usd': round(net_pnl, 2),
                    'return_pct': round((net_pnl / initial_capital) * 100, 4),
                    'equity_after': round(risk_mgr.equity, 2)
                })
            else:
                remaining_positions.append(pos)

        open_positions = remaining_positions

        # อัปเดต Step-Lock Trailing Stop
        open_positions = strategy.manage_step_lock_exits(open_positions, row)

        # ตรวจสอบสัญญาณเข้าใหม่หรือ Pyramiding
        if not risk_mgr.daily_halted and not is_friday_close:
            signal = strategy.generate_signal(row, prev_row, open_positions)
            if signal:
                lot, adjusted_sl = risk_mgr.calculate_safe_lot(
                    open_positions,
                    signal['side'],
                    signal['entry'],
                    signal['sl'],
                    row['atr']
                )
                if lot >= 0.01:
                    open_positions.append({
                        'id': trade_id_counter,
                        'entry_time': row['timestamp'],
                        'side': signal['side'],
                        'setup': signal['setup'],
                        'regime': row['regime'],
                        'sentiment': round(row['ls_sentiment'], 3),
                        'lot': lot,
                        'entry': signal['entry'],
                        'initial_sl': adjusted_sl,
                        'current_sl': adjusted_sl
                    })
                    trade_id_counter += 1

        if i % 4 == 0:
            equity_records.append({
                'timestamp': row['timestamp'],
                'equity': round(risk_mgr.equity, 2),
                'open_positions': len(open_positions)
            })

    os.makedirs('outputs', exist_ok=True)
    trades_df = pd.DataFrame(closed_trades)
    equity_df = pd.DataFrame(equity_records)
    trades_df.to_csv('outputs/trade_history_export.csv', index=False)
    equity_df.to_csv('outputs/equity_curve.csv', index=False)
    print(f"เสร็จสิ้น! เทรดทั้งหมด {len(trades_df)} ไม้ | Equity สุดท้าย: ${risk_mgr.equity:,.2f}")


if __name__ == '__main__':
    run_backtest()
