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
    print("1. กำลังโหลดข้อมูลและคำนวณ Dynamic KAMA + Adaptive TPO V8...")
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
    current_date = None
    daily_losses_count = 0
    blocked_sides_today = set()
    consecutive_losses = 0

    print("2. กำลังรัน Simulation V8 (Core 5 Setups Only + Adaptive KAMA + Anti-Streak Throttling)...")
    for i in range(100, len(df)):
        row = df.iloc[i]
        prev_row = df.iloc[i - 1]
        risk_mgr.on_new_bar(row['date'], risk_mgr.equity)

        if current_date != row['date']:
            current_date = row['date']
            daily_losses_count = 0
            blocked_sides_today = set()

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
            one_r = abs(pos['entry'] - pos['initial_sl'])

            # Partial TP 50% ที่ +1.2R
            if not pos.get('partial_taken', False) and pos['lot'] >= 0.02 and one_r > 0:
                target_partial = (pos['entry'] + 1.2 * one_r) if pos['side'] == 'BUY' else (pos['entry'] - 1.2 * one_r)
                hit_partial = (row['high'] >= target_partial) if pos['side'] == 'BUY' else (row['low'] <= target_partial)

                if hit_partial:
                    close_lot = round(pos['lot'] * 0.5, 2)
                    pos['lot'] = round(pos['lot'] - close_lot, 2)
                    pos['partial_taken'] = True
                    p_diff = (target_partial - pos['entry']) if pos['side'] == 'BUY' else (pos['entry'] - target_partial)
                    net_p = (p_diff * risk_mgr.contract_size * close_lot) - (risk_mgr.commission_per_lot * close_lot)
                    risk_mgr.equity += net_p
                    consecutive_losses = 0

                    closed_trades.append({
                        'trade_id': pos['id'],
                        'entry_time': pos['entry_time'],
                        'exit_time': row['timestamp'],
                        'side': pos['side'],
                        'setup': pos['setup'] + '_PARTIAL',
                        'regime': pos['regime'],
                        'sentiment_score': pos['sentiment'],
                        'lot': close_lot,
                        'entry_price': pos['entry'],
                        'initial_sl': pos['initial_sl'],
                        'exit_price': round(target_partial, 2),
                        'exit_reason': 'PARTIAL_TP_1.2R',
                        'net_pnl_usd': round(net_p, 2),
                        'return_pct': round((net_p / initial_capital) * 100, 4),
                        'equity_after': round(risk_mgr.equity, 2)
                    })

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

                if net_pnl < -20.0:
                    daily_losses_count += 1
                    blocked_sides_today.add(pos['side'])
                    if not pos.get('partial_taken', False):
                        consecutive_losses += 1
                elif net_pnl > 20.0:
                    consecutive_losses = 0

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
        open_positions = strategy.manage_step_lock_exits(open_positions, row)

        if not risk_mgr.daily_halted and not is_friday_close and daily_losses_count < 2:
            signal = strategy.generate_signal(row, prev_row, open_positions, blocked_sides_today)

            if signal:
                orig_risk = risk_mgr.max_risk_pct
                if consecutive_losses >= 2:
                    risk_mgr.max_risk_pct = orig_risk * 0.5

                lot, adjusted_sl = risk_mgr.calculate_safe_lot(
                    open_positions,
                    signal['side'],
                    signal['entry'],
                    signal['sl'],
                    row['atr']
                )
                risk_mgr.max_risk_pct = orig_risk

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
                        'current_sl': adjusted_sl,
                        'partial_taken': False
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
    print(f"เสร็จสิ้น! รายการปิดทั้งหมด {len(trades_df)} รายการ | Equity สุดท้าย: ${risk_mgr.equity:,.2f}")


if __name__ == '__main__':
    run_backtest()
