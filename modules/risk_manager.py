class RiskManager:
    def __init__(
        self,
        initial_capital: float = 100000.0,
        max_risk_per_trade_pct: float = 0.0025,  # 0.25%
        max_daily_dd_pct: float = 0.025,         # ตัดจบที่ 2.5% เพื่อกัน Slippage ทะลุ 3.0%
        contract_size: float = 100.0,            # XAUUSD 1 Lot = 100 oz
        commission_per_lot: float = 7.0,
        max_pyramiding_positions: int = 3
    ):
        self.initial_capital = initial_capital
        self.equity = initial_capital
        self.max_risk_pct = max_risk_per_trade_pct
        self.max_daily_dd_pct = max_daily_dd_pct
        self.contract_size = contract_size
        self.commission_per_lot = commission_per_lot
        self.max_positions = max_pyramiding_positions

        self.current_day = None
        self.day_start_equity = initial_capital
        self.daily_halted = False

    def on_new_bar(self, bar_date, current_equity: float):
        self.equity = current_equity
        if self.current_day != bar_date:
            self.current_day = bar_date
            self.day_start_equity = current_equity
            self.daily_halted = False

        daily_pnl_pct = (self.equity - self.day_start_equity) / self.day_start_equity
        if daily_pnl_pct <= -self.max_daily_dd_pct:
            self.daily_halted = True

    def get_net_open_risk_usd(self, open_positions: list[dict]) -> float:
        total_risk = 0.0
        for pos in open_positions:
            if pos['side'] == 'BUY':
                risk_per_oz = pos['entry'] - pos['current_sl']
            else:
                risk_per_oz = pos['current_sl'] - pos['entry']

            pos_risk = (risk_per_oz * self.contract_size * pos['lot']) + (self.commission_per_lot * pos['lot'])
            if pos_risk > 0:
                total_risk += pos_risk
        return total_risk

    def normalize_sl(self, side: str, entry_price: float, sl_price: float, atr: float) -> float:
        """บังคับระยะ SL ขั้นต่ำอย่างน้อย 0.8 เท่าของ ATR ป้องกัน Lot ใหญ่ผิดปกติจาก SL แคบเกินไป"""
        min_sl_dist = max(3.0, 0.8 * atr)
        raw_dist = abs(entry_price - sl_price)
        final_dist = max(raw_dist, min_sl_dist)
        if side == 'BUY':
            return round(entry_price - final_dist, 2)
        return round(entry_price + final_dist, 2)

    def calculate_safe_lot(self, open_positions: list[dict], side: str, entry_price: float, sl_price: float, atr: float = 5.0) -> tuple[float, float]:
        """คืนค่า (safe_lot, adjusted_sl) เพื่อให้ระยะ SL จริงตรงกับ Lot Size เสมอ"""
        adjusted_sl = self.normalize_sl(side, entry_price, sl_price, atr)

        if self.daily_halted or len(open_positions) >= self.max_positions:
            return 0.0, adjusted_sl

        base_capital = min(self.equity, self.day_start_equity)
        max_risk_usd = base_capital * self.max_risk_pct
        current_risk_usd = self.get_net_open_risk_usd(open_positions)
        available_risk_usd = max_risk_usd - current_risk_usd

        # ไม่อนุญาตให้เปิดไม้เพิ่ม หากไม้เดิมยังไม่ถูกเลื่อน SL มาล็อกทุน (ต้องเหลือโควตา >= 90%)
        if available_risk_usd < (max_risk_usd * 0.90):
            return 0.0, adjusted_sl

        sl_dist = abs(entry_price - adjusted_sl)
        if sl_dist <= 0.10:
            return 0.0, adjusted_sl

        risk_per_lot = (sl_dist * self.contract_size) + self.commission_per_lot
        raw_lot = available_risk_usd / risk_per_lot
        safe_lot = int(raw_lot * 100) / 100.0
        return (safe_lot if safe_lot >= 0.01 else 0.0), adjusted_sl
