import streamlit as st
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go

st.set_page_config(page_title="XAUUSD TPO + VWAP Quant Dashboard", layout="wide")
st.title("📊 XAUUSD TPO + VWAP Quant Backtest Dashboard")

try:
    trades_df = pd.read_csv('outputs/trade_history_export.csv')
    equity_df = pd.read_csv('outputs/equity_curve.csv')
except FileNotFoundError:
    st.warning("ไม่พบไฟล์ผลลัพธ์ กรุณารันคำสั่ง `python main_backtest.py` ก่อนเปิดหน้าแดชบอร์ด")
    st.stop()

trades_df['entry_time'] = pd.to_datetime(trades_df['entry_time'])
trades_df['exit_time'] = pd.to_datetime(trades_df['exit_time'])
trades_df['date'] = trades_df['exit_time'].dt.date

# --- คำนวณตัวชี้วัดหลัก (KPIs) ---
initial_cap = 100000.0
final_equity = trades_df['equity_after'].iloc[-1] if not trades_df.empty else initial_cap
net_profit = final_equity - initial_cap
net_profit_pct = (net_profit / initial_cap) * 100

wins = trades_df[trades_df['net_pnl_usd'] > 0]
losses = trades_df[trades_df['net_pnl_usd'] <= 0]
win_rate = (len(wins) / len(trades_df)) * 100 if len(trades_df) > 0 else 0
profit_factor = wins['net_pnl_usd'].sum() / abs(losses['net_pnl_usd'].sum()) if len(losses) > 0 else 0

daily_pnl = trades_df.groupby('date')['net_pnl_usd'].sum().reset_index()
daily_pnl['daily_return_pct'] = (daily_pnl['net_pnl_usd'] / initial_cap) * 100
max_daily_dd_pct = daily_pnl['daily_return_pct'].min()
avg_daily_return_pct = daily_pnl['daily_return_pct'].mean()

# --- แถบปุ่มดาวน์โหลดสำหรับส่งให้ AI วิเคราะห์ต่อ ---
col_btn1, col_btn2 = st.columns([1, 3])
with col_btn1:
    csv_data = trades_df.to_csv(index=False).encode('utf-8-sig')
    st.download_button(
        label="📥 โหลดประวัติการเทรด (CSV) ส่งวิเคราะห์ต่อ",
        data=csv_data,
        file_name="xauusd_tpo_vwap_trades_report.csv",
        mime="text/csv",
        type="primary"
    )
with col_btn2:
    st.info("กดปุ่มด้านซ้ายเพื่อดาวน์โหลดไฟล์ `xauusd_tpo_vwap_trades_report.csv` แล้วอัปโหลดส่งกลับมาในแชตนี้เพื่อวิเคราะห์หาจุดปรับปรุง Win Rate / Profit Factor และจูนพารามิเตอร์รายเดือน")

st.divider()

# --- แสดง Metrics ---
m1, m2, m3, m4, m5, m6 = st.columns(6)
m1.metric("Net Profit", f"${net_profit:,.2f}", f"{net_profit_pct:+.2f}%")
m2.metric("Total Trades", f"{len(trades_df)}")
m3.metric("Win Rate", f"{win_rate:.2f}%")
m4.metric("Profit Factor", f"{profit_factor:.2f}")
m5.metric("Avg Daily Return", f"{avg_daily_return_pct:+.3f}%")
m6.metric("Worst Daily DD", f"{max_daily_dd_pct:.2f}%", delta="Limit: -3.00%", delta_color="normal")

# --- กราฟ Equity Curve & Daily PnL ---
c1, c2 = st.columns(2)
with c1:
    fig_eq = px.line(equity_df, x='timestamp', y='equity', title="Equity Curve (9-Month Simulation)")
    fig_eq.update_traces(line_color='#00C805')
    st.plotly_chart(fig_eq, use_container_width=True)

with c2:
    daily_pnl['color'] = daily_pnl['daily_return_pct'].apply(lambda x: 'Profit' if x >= 0 else 'Loss')
    fig_daily = px.bar(
        daily_pnl, x='date', y='daily_return_pct', color='color',
        color_discrete_map={'Profit': '#00C805', 'Loss': '#FF4B4B'},
        title="Daily Return (%) & Drawdown Check"
    )
    fig_daily.add_hline(y=-3.0, line_dash="dash", line_color="red", annotation_text="Max Daily DD (-3%)")
    fig_daily.add_hline(y=1.0, line_dash="dot", line_color="green", annotation_text="Target (+1%)")
    st.plotly_chart(fig_daily, use_container_width=True)

# --- ตารางวิเคราะห์แยกตาม Setup และ Market Regime ---
c3, c4 = st.columns(2)
with c3:
    st.subheader("ผลงานแยกตาม Setup")
    setup_summary = trades_df.groupby('setup').agg(
        Trades=('trade_id', 'count'),
        Win_Rate=('net_pnl_usd', lambda x: f"{(x > 0).mean() * 100:.1f}%"),
        Total_PnL=('net_pnl_usd', 'sum')
    ).reset_index()
    st.dataframe(setup_summary, use_container_width=True)

with c4:
    st.subheader("ผลงานแยกตามสภาวะตลาด (Regime)")
    regime_summary = trades_df.groupby('regime').agg(
        Trades=('trade_id', 'count'),
        Win_Rate=('net_pnl_usd', lambda x: f"{(x > 0).mean() * 100:.1f}%"),
        Total_PnL=('net_pnl_usd', 'sum')
    ).reset_index()
    st.dataframe(regime_summary, use_container_width=True)

st.subheader("ประวัติการเทรดล่าสุด (50 ไม้ล่าสุด)")
st.dataframe(trades_df.tail(50).iloc[::-1], use_container_width=True)
