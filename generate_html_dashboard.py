import os
import json
import pandas as pd


def build_html_dashboard(
    trades_csv: str = 'outputs/trade_history_export.csv',
    equity_csv: str = 'outputs/equity_curve.csv',
    output_html: str = 'outputs/dashboard.html',
    initial_cap: float = 100000.0
):
    if not os.path.exists(trades_csv) or not os.path.exists(equity_csv):
        print("ไม่พบไฟล์ผลลัพธ์ กรุณารัน main_backtest.py ก่อน")
        return

    trades_df = pd.read_csv(trades_csv)
    equity_df = pd.read_csv(equity_csv)

    if trades_df.empty:
        print("ไม่มีรายการเทรดในรอบนี้")
        return

    trades_df['exit_time_dt'] = pd.to_datetime(trades_df['exit_time'])
    trades_df['date_str'] = trades_df['exit_time_dt'].dt.strftime('%Y-%m-%d')

    # คำนวณ KPIs
    final_equity = float(trades_df['equity_after'].iloc[-1])
    net_profit = final_equity - initial_cap
    net_profit_pct = (net_profit / initial_cap) * 100
    total_trades = len(trades_df)

    wins = trades_df[trades_df['net_pnl_usd'] > 0]
    losses = trades_df[trades_df['net_pnl_usd'] <= 0]
    win_rate = (len(wins) / total_trades) * 100
    gross_win = wins['net_pnl_usd'].sum()
    gross_loss = abs(losses['net_pnl_usd'].sum())
    profit_factor = (gross_win / gross_loss) if gross_loss > 0 else 0.0

    daily_pnl = trades_df.groupby('date_str')['net_pnl_usd'].sum().reset_index()
    daily_pnl['daily_pct'] = (daily_pnl['net_pnl_usd'] / initial_cap) * 100
    avg_daily_pct = daily_pnl['daily_pct'].mean()
    worst_daily_pct = daily_pnl['daily_pct'].min()

    # สรุปแยกตาม Setup และ Regime
    setup_grp = trades_df.groupby('setup').agg(
        trades=('trade_id', 'count'),
        win_rate=('net_pnl_usd', lambda x: round((x > 0).mean() * 100, 1)),
        pnl=('net_pnl_usd', lambda x: round(x.sum(), 2))
    ).reset_index()

    regime_grp = trades_df.groupby('regime').agg(
        trades=('trade_id', 'count'),
        win_rate=('net_pnl_usd', lambda x: round((x > 0).mean() * 100, 1)),
        pnl=('net_pnl_usd', lambda x: round(x.sum(), 2))
    ).reset_index()

    # เตรียมข้อมูล JSON และ Raw CSV ฝังลงใน HTML
    raw_csv_text = trades_df.drop(columns=['exit_time_dt', 'date_str']).to_csv(index=False)
    eq_times = json.dumps(equity_df['timestamp'].tolist())
    eq_vals = json.dumps(equity_df['equity'].tolist())
    d_dates = json.dumps(daily_pnl['date_str'].tolist())
    d_pcts = json.dumps([round(x, 3) for x in daily_pnl['daily_pct'].tolist()])
    recent_trades_html = trades_df.drop(columns=['exit_time_dt', 'date_str']).tail(50).iloc[::-1].to_html(
        index=False, classes='trade-table', border=0
    )
    setup_table_html = setup_grp.to_html(index=False, classes='summary-table', border=0)
    regime_table_html = regime_grp.to_html(index=False, classes='summary-table', border=0)

    html_content = f"""<!DOCTYPE html>
<html lang="th">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>XAUUSD TPO + VWAP Quant Dashboard</title>
<script src="https://cdn.plot.ly/plotly-2.27.0.min.js"></script>
<style>
  body {{ font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif; background: #0f172a; color: #f8fafc; margin: 0; padding: 20px; }}
  .container {{ max-width: 1400px; margin: auto; }}
  .header {{ display: flex; justify-content: space-between; align-items: center; flex-wrap: wrap; gap: 15px; border-bottom: 1px solid #334155; padding-bottom: 15px; margin-bottom: 20px; }}
  .header h1 {{ margin: 0; font-size: 1.5rem; color: #38bdf8; }}
  .btn-download {{ background: #10b981; color: #fff; border: none; padding: 12px 20px; font-size: 1rem; font-weight: bold; border-radius: 8px; cursor: pointer; transition: 0.2s; }}
  .btn-download:hover {{ background: #059669; }}
  .kpi-grid {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(180px, 1fr)); gap: 15px; margin-bottom: 25px; }}
  .kpi-card {{ background: #1e293b; padding: 16px; border-radius: 10px; border: 1px solid #334155; }}
  .kpi-title {{ font-size: 0.85rem; color: #94a3b8; margin-bottom: 6px; }}
  .kpi-val {{ font-size: 1.4rem; font-weight: bold; }}
  .pos {{ color: #10b981; }} .neg {{ color: #ef4444; }}
  .chart-grid {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(500px, 1fr)); gap: 20px; margin-bottom: 25px; }}
  .card {{ background: #1e293b; padding: 18px; border-radius: 10px; border: 1px solid #334155; overflow-x: auto; }}
  .card h3 {{ margin-top: 0; color: #e2e8f0; font-size: 1.1rem; }}
  table {{ width: 100%; border-collapse: collapse; font-size: 0.85rem; }}
  th, td {{ padding: 10px; text-align: left; border-bottom: 1px solid #334155; }}
  th {{ background: #0f172a; color: #38bdf8; position: sticky; top: 0; }}
  tr:hover {{ background: #263349; }}
</style>
</head>
<body>
<div class="container">
  <div class="header">
    <div>
      <h1>📊 XAUUSD TPO + VWAP Quant Report</h1>
      <div style="color:#94a3b8; font-size:0.9rem; margin-top:4px;">Risk Cap: 0.25% / Trade (Pyramiding) | Daily DD Limit: 3.0%</div>
    </div>
    <button class="btn-download" onclick="downloadCSV()">📥 โหลดประวัติการเทรด (CSV) ส่งวิเคราะห์ต่อ</button>
  </div>

  <div class="kpi-grid">
    <div class="kpi-card"><div class="kpi-title">Net Profit</div><div class="kpi-val {'pos' if net_profit >= 0 else 'neg'}">${net_profit:,.2f} ({net_profit_pct:+.2f}%)</div></div>
    <div class="kpi-card"><div class="kpi-title">Total Trades</div><div class="kpi-val">{total_trades}</div></div>
    <div class="kpi-card"><div class="kpi-title">Win Rate</div><div class="kpi-val">{win_rate:.2f}%</div></div>
    <div class="kpi-card"><div class="kpi-title">Profit Factor</div><div class="kpi-val">{profit_factor:.2f}</div></div>
    <div class="kpi-card"><div class="kpi-title">Avg Daily Return</div><div class="kpi-val {'pos' if avg_daily_pct >= 0 else 'neg'}">{avg_daily_pct:+.3f}%</div></div>
    <div class="kpi-card"><div class="kpi-title">Worst Daily DD</div><div class="kpi-val {'neg' if worst_daily_pct < -3.0 else 'pos'}">{worst_daily_pct:.2f}%</div></div>
  </div>

  <div class="chart-grid">
    <div class="card"><div id="equityChart" style="height:360px;"></div></div>
    <div class="card"><div id="dailyChart" style="height:360px;"></div></div>
  </div>

  <div class="chart-grid">
    <div class="card"><h3>ผลงานแยกตาม Setup</h3>{setup_table_html}</div>
    <div class="card"><h3>ผลงานแยกตามสภาวะตลาด (Market Regime)</h3>{regime_table_html}</div>
  </div>

  <div class="card">
    <h3>ประวัติการเทรดล่าสุด (50 ไม้ล่าสุด)</h3>
    {recent_trades_html}
  </div>
</div>

<script>
  const rawCsvData = {json.dumps(raw_csv_text)};

  function downloadCSV() {{
    const blob = new Blob(["\\uFEFF" + rawCsvData], {{ type: 'text/csv;charset=utf-8;' }});
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = 'xauusd_tpo_vwap_trades_report.csv';
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
  }}

  Plotly.newPlot('equityChart', [{{
    x: {eq_times},
    y: {eq_vals},
    type: 'scatter',
    mode: 'lines',
    line: {{ color: '#10b981', width: 2 }},
    name: 'Equity ($)'
  }}], {{
    title: 'Equity Curve (9-Month Simulation)',
    paper_bgcolor: '#1e293b', plot_bgcolor: '#1e293b',
    font: {{ color: '#f8fafc' }},
    xaxis: {{ gridcolor: '#334155' }}, yaxis: {{ gridcolor: '#334155' }},
    margin: {{ t: 40, l: 55, r: 20, b: 40 }}
  }}, {{responsive: true}});

  const dailyPcts = {d_pcts};
  Plotly.newPlot('dailyChart', [{{
    x: {d_dates},
    y: dailyPcts,
    type: 'bar',
    marker: {{ color: dailyPcts.map(v => v >= 0 ? '#10b981' : '#ef4444') }},
    name: 'Daily Return (%)'
  }}], {{
    title: 'Daily Return (%) & Drawdown Check (-3% Limit)',
    paper_bgcolor: '#1e293b', plot_bgcolor: '#1e293b',
    font: {{ color: '#f8fafc' }},
    xaxis: {{ gridcolor: '#334155' }}, yaxis: {{ gridcolor: '#334155' }},
    shapes: [
      {{ type: 'line', x0: 0, x1: 1, xref: 'paper', y0: -3.0, y1: -3.0, line: {{ color: '#ef4444', width: 1.5, dash: 'dash' }} }},
      {{ type: 'line', x0: 0, x1: 1, xref: 'paper', y0: 1.0, y1: 1.0, line: {{ color: '#38bdf8', width: 1, dash: 'dot' }} }}
    ],
    margin: {{ t: 40, l: 50, r: 20, b: 40 }}
  }}, {{responsive: true}});
</script>
</body>
</html>
"""
    os.makedirs(os.path.dirname(output_html), exist_ok=True)
    with open(output_html, 'w', encoding='utf-8') as f:
        f.write(html_content)
    print(f"สร้างไฟล์แดชบอร์ดสำเร็จที่: {output_html}")


if __name__ == '__main__':
    build_html_dashboard()
